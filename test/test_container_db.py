#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La restauration de base dans le conteneur ERPLibre fait-elle ce qu'elle
promet ?

Les scripts shell de container_db s'exécutent ici POUR DE VRAI sous bash,
hors de tout conteneur : un faux odoo-bin note ses arguments et son
environnement. C'est la seule façon de prouver les deux promesses qui ne se
lisent pas dans le Python :

- le mot de passe PostgreSQL n'est jamais un argument — un processus du
  conteneur est visible par « ps » sur l'hôte ;
- TMPDIR pointe dans le répertoire de données, là où le filestore extrait
  n'a plus qu'à être renommé.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import container_db, container_menu  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

MOT_DE_PASSE = "motdepasse-essai-7f3a"


def bash(script, args=(), env=None, entree=b""):
    """Lance `script` comme le fait « exec … bash -c script bash args ».

    L'entrée est vide par défaut, et non celle du lanceur de tests : un
    script qui lit une ligne y attendrait jusqu'au délai.
    """
    return subprocess.run(
        ["bash", "-c", script, "bash", *args],
        env=env,
        input=entree,
        capture_output=True,
        timeout=30,
    )


class Prefixe:
    """Un faux /ERPLibre : versions, venv et odoo-bin qui notent l'appel."""

    def __init__(self, racine, avec_db=True):
        self.racine = Path(racine)
        self.data = self.racine / "data"
        self.data.mkdir()
        self.prefixe = self.racine / "ERPLibre"
        odoo = self.prefixe / "odoo18.0" / "odoo"
        (odoo / "odoo" / "cli").mkdir(parents=True)
        if avec_db:
            (odoo / "odoo" / "cli" / "db.py").write_text("")
        (self.prefixe / ".erplibre-version").write_text("odoo18.0_essai\n")
        (self.prefixe / ".odoo-version").write_text("18.0\n")
        venv = self.prefixe / ".venv.odoo18.0_essai" / "bin"
        venv.mkdir(parents=True)
        self.trace = self.racine / "trace"
        # Le faux python ignore l'interpréteur demandé et note tout.
        python = venv / "python"
        python.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$@" > "{self.trace}.argv"\n'
            f'env > "{self.trace}.env"\n'
        )
        python.chmod(0o755)
        (odoo / "odoo-bin").write_text("")
        self.conf = self.racine / "odoo.conf"
        self.conf.write_text(f"[options]\ndata_dir = {self.data}\n")

    def env(self, **extra):
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.racine),
            "ODOO_PREFIX": str(self.prefixe),
            "ODOO_RC": str(self.conf),
            "HOST": "db",
            "USER": "odoo",
            "PASSWORD": MOT_DE_PASSE,
        }
        env.update(extra)
        return env

    def argv(self):
        return Path(f"{self.trace}.argv").read_text().splitlines()

    def environ(self):
        lignes = Path(f"{self.trace}.env").read_text().splitlines()
        return dict(ligne.partition("=")[::2] for ligne in lignes)


class TestScripts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Prefixe(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_la_sonde_lit_data_dir_de_la_configuration(self):
        fin = bash(container_db.SONDE, env=self.p.env())
        sonde = container_db.lire_sonde(fin.stdout.decode())
        self.assertEqual(sonde["data_dir"], str(self.p.data))
        self.assertTrue(sonde["ecriture"])
        self.assertIsInstance(sonde["libre_data"], int)
        self.assertIsInstance(sonde["libre_tmp"], int)

    def test_sans_data_dir_la_sonde_prend_celui_d_odoo(self):
        self.p.conf.write_text("[options]\n")
        fin = bash(container_db.SONDE, env=self.p.env())
        sonde = container_db.lire_sonde(fin.stdout.decode())
        self.assertEqual(
            sonde["data_dir"], f"{self.p.racine}/.local/share/Odoo"
        )
        self.assertFalse(sonde["ecriture"])

    def test_la_reception_ecrit_le_zip_dans_le_dossier_de_travail(self):
        reste = self.p.data / container_db.TRAVAIL / "reste"
        reste.parent.mkdir()
        reste.write_text("restauration interrompue")
        fin = bash(container_db.RECEVOIR, env=self.p.env(), entree=b"ZIP")
        self.assertEqual(fin.returncode, 0, fin.stderr)
        travail = self.p.data / container_db.TRAVAIL
        self.assertEqual((travail / container_db.ZIP).read_bytes(), b"ZIP")
        self.assertTrue((travail / "tmp").is_dir())
        self.assertFalse(reste.exists())

    def test_la_restauration_ne_met_pas_le_mot_de_passe_en_argument(self):
        fin = bash(
            container_db.RESTAURER, ["essai_base", "-f"], env=self.p.env()
        )
        self.assertEqual(fin.returncode, 0, fin.stderr)
        argv = self.p.argv()
        self.assertNotIn(MOT_DE_PASSE, " ".join(argv))
        travail = self.p.data / container_db.TRAVAIL
        self.assertEqual(
            argv[1:],
            [
                "db",
                "-c",
                str(self.p.conf),
                "load",
                "-f",
                "essai_base",
                str(travail / container_db.ZIP),
            ],
        )
        env = self.p.environ()
        self.assertEqual(env["PGPASSWORD"], MOT_DE_PASSE)
        self.assertEqual(env["PGHOST"], "db")
        self.assertEqual(env["PGUSER"], "odoo")
        self.assertEqual(env["TMPDIR"], str(travail / "tmp"))

    def test_la_configuration_l_emporte_sur_l_environnement(self):
        self.p.conf.write_text(
            f"[options]\ndata_dir = {self.p.data}\ndb_host = pg-essai\n"
            "db_password = False\n"
        )
        bash(container_db.RESTAURER, ["essai_base"], env=self.p.env())
        env = self.p.environ()
        self.assertEqual(env["PGHOST"], "pg-essai")
        # « False » est le défaut d'Odoo, pas une valeur.
        self.assertEqual(env["PGPASSWORD"], MOT_DE_PASSE)

    def test_sans_commande_db_rien_n_est_lance(self):
        self._tmp.cleanup()
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Prefixe(self._tmp.name, avec_db=False)
        fin = bash(container_db.RESTAURER, ["essai_base"], env=self.p.env())
        self.assertEqual(fin.returncode, 3)
        self.assertFalse(Path(f"{self.p.trace}.argv").exists())

    def test_le_nettoyage_efface_le_dossier_de_travail(self):
        bash(container_db.RECEVOIR, env=self.p.env(), entree=b"ZIP")
        bash(container_db.NETTOYER, env=self.p.env())
        self.assertFalse((self.p.data / container_db.TRAVAIL).exists())
        self.assertTrue(self.p.data.is_dir())

    def test_le_mot_de_passe_maitre_arrive_par_l_entree_standard(self):
        for script, args in (
            (container_db.RESTAURER, ["essai_base", "-f"]),
            (container_db.SUPPRIMER, ["essai_base"]),
        ):
            fin = bash(
                script, args, env=self.p.env(), entree=b"maitre-invente-71\n"
            )
            self.assertEqual(fin.returncode, 0, fin.stderr)
            self.assertEqual(
                self.p.environ()["MASTER_PWD"], "maitre-invente-71"
            )
            self.assertNotIn("maitre-invente-71", " ".join(self.p.argv()))

    def test_une_ligne_vide_garde_le_mot_de_passe_du_conteneur(self):
        bash(
            container_db.SUPPRIMER,
            ["essai_base"],
            env=self.p.env(MASTER_PWD="du-conteneur-72"),
            entree=b"\n",
        )
        self.assertEqual(self.p.environ()["MASTER_PWD"], "du-conteneur-72")
        bash(
            container_db.SUPPRIMER,
            ["essai_base"],
            env=self.p.env(),
            entree=b"",
        )
        self.assertNotIn("MASTER_PWD", self.p.environ())

    def test_la_suppression_passe_par_db_drop(self):
        bash(container_db.SUPPRIMER, ["essai_base"], env=self.p.env())
        self.assertEqual(
            self.p.argv()[1:],
            ["db", "-c", str(self.p.conf), "drop", "essai_base"],
        )


class TestFaits(unittest.TestCase):
    def test_tailles_lues_dans_l_index_decompresse(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "essai_base.zip")
            with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("dump.sql", "x" * 10000)
                z.writestr("filestore/ab/abc", "y" * 3000)
                z.writestr("filestore/cd/cde", "z" * 2000)
                z.writestr("filestore/checklist/ab/abc", "")
                z.writestr("manifest.json", "{}")
            tailles = container_db.tailles_sauvegarde(chemin)
        self.assertEqual(tailles["dump"], 10000)
        self.assertEqual(tailles["filestore"], 5000)
        self.assertEqual(tailles["fichiers"], 2)
        self.assertLess(tailles["zip"], 15000)
        self.assertEqual(
            container_db.besoin(tailles), tailles["zip"] + 20000 + 5000
        )

    def test_un_zip_sans_dump_n_est_pas_une_sauvegarde(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "autre.zip")
            with zipfile.ZipFile(chemin, "w") as z:
                z.writestr("lisez-moi.txt", "")
            self.assertIsNone(container_db.tailles_sauvegarde(chemin))
            texte = os.path.join(tmp, "texte.zip")
            Path(texte).write_text("pas un zip")
            self.assertIsNone(container_db.tailles_sauvegarde(texte))

    def test_la_liste_marque_les_bases_vides(self):
        sortie = "WARNING: bruit\nbase=essai_a|f\nbase=essai_b|t\n"
        self.assertEqual(
            container_db.lire_liste(sortie),
            [("essai_a", False), ("essai_b", True)],
        )

    def test_le_compte_est_celui_d_odoo_meme_si_le_conteneur_part_en_root(
        self,
    ):
        self.assertEqual(container_db.compte({"utilisateur": "root"}), "odoo")
        self.assertEqual(
            container_db.compte(
                {"utilisateur": "", "env": {"ERPLIBRE_RUN_AS": "erp"}}
            ),
            "erp",
        )
        self.assertEqual(
            container_db.compte({"utilisateur": "1001:1001"}), "1001:1001"
        )

    def test_le_service_erplibre_par_etiquette_ou_par_nom(self):
        self.assertTrue(container_db.est_erplibre({"service": "ERPLibre"}))
        self.assertFalse(
            container_db.est_erplibre(
                {"service": "db", "nom": "essai-ERPLibre-1"}
            )
        )
        self.assertTrue(container_db.est_erplibre({"nom": "essai_ERPLibre_1"}))
        self.assertFalse(container_db.est_erplibre({"nom": "essai-db-1"}))

    def test_les_valeurs_voyagent_en_parametres(self):
        fiche = {"moteur": "docker", "sans_sudo": True}
        conteneur = {"nom": "essai-ERPLibre-1", "utilisateur": "root"}
        cmd = container_db.executer(
            fiche, conteneur, container_db.SUPPRIMER, ["essai_base"]
        )
        self.assertEqual(
            cmd[:6],
            ["docker", "exec", "-u", "odoo", "essai-ERPLibre-1", "bash"],
        )
        self.assertEqual(cmd[-2:], ["bash", "essai_base"])
        self.assertNotIn("essai_base", cmd[7])

    def test_nom_par_defaut(self):
        self.assertEqual(
            container_db.nom_par_defaut("/x/essai_2026-01-01_10h.zip"),
            "essai_2026-01-01_10h",
        )
        self.assertEqual(container_db.nom_par_defaut("/x/a b.zip"), "")


class FauxGestionnaire:
    def __init__(self, chemin):
        self.chemin = chemin
        self.depart = None

    def select_backup_path(self, start=None):
        self.depart = start
        return self.chemin


class TestMenuRestauration(unittest.TestCase):
    """Le parcours du menu, moteur et conteneur remplacés."""

    CONTENEUR = {
        "nom": "essai-ERPLibre-1",
        "dossier": "/ailleurs",
        "utilisateur": "root",
        "env": {},
        "etat": "running",
        "service": "ERPLibre",
    }
    SONDE = {
        "data_dir": "/home/odoo/.local/share/Odoo",
        "ecriture": True,
        "libre_data": 50 * 2**30,
        "libre_tmp": 50 * 2**30,
        "montage_data": "/home/odoo/.local/share/Odoo",
        "montage_tmp": "/",
    }

    def setUp(self):
        # Les réponses à getpass, dans l'ordre ; un appel de trop lève.
        self.maitre = ["maitre-invente-70"]
        self._tmp = tempfile.TemporaryDirectory()
        self.zip = os.path.join(self._tmp.name, "essai_base.zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("dump.sql", "x" * 1000)

    def tearDown(self):
        self._tmp.cleanup()

    def lancer(self, entrees, prompts=("essai_base",), bases=(), codes=None):
        self.libelles = []
        self.secrets = []
        todo = TODO.__new__(TODO)
        todo.db_manager = FauxGestionnaire(self.zip)
        todo._container_fiche = lambda: {"moteur": "docker", "sans_sudo": True}
        todo._container_sonder = lambda f, c: dict(self.SONDE)
        todo._container_lister_bases = lambda f, c: list(bases)
        lances = []
        codes = dict(codes or {})

        def dans(cmd, libelle, entree=None, secret=None):
            script = cmd[cmd.index("-c") + 1]
            for nom in ("RECEVOIR", "RESTAURER", "NETTOYER", "SUPPRIMER"):
                if script == getattr(container_db, nom):
                    lances.append((nom, cmd[cmd.index("-c") + 3 :]))
                    self.libelles.append(libelle)
                    self.secrets.append((nom, secret, "-i" in cmd))
                    return codes.get(nom, 0)
            raise AssertionError(cmd)

        todo._container_dans = dans
        suite = iter(entrees)
        sortie = io.StringIO()
        with (
            mock.patch.object(
                container_db,
                "conteneurs_erplibre",
                return_value=[self.CONTENEUR],
            ),
            mock.patch.object(
                container_menu.click, "prompt", side_effect=list(prompts)
            ),
            mock.patch("builtins.input", lambda *a: next(suite, "")),
            mock.patch.object(
                container_menu.getpass,
                "getpass",
                side_effect=lambda *a: self.maitre.pop(0),
            ),
            contextlib.redirect_stdout(sortie),
        ):
            todo._container_restaurer_base()
        return lances, sortie.getvalue()

    def test_l_ordre_reception_restauration_nettoyage(self):
        lances, _ = self.lancer(["n", "", "o"])
        self.assertEqual(
            lances,
            [
                ("RECEVOIR", []),
                ("RESTAURER", ["essai_base"]),
                ("NETTOYER", []),
            ],
        )

    def test_le_journal_recoit_un_libelle_et_non_le_script(self):
        self.lancer(["n", "", "o"])
        self.assertEqual(len(self.libelles), 3)
        restauration = self.libelles[1]
        self.assertIn("essai-ERPLibre-1 (odoo)", restauration)
        self.assertIn("odoo-bin db load essai_base", restauration)
        for libelle in self.libelles:
            self.assertNotIn("\n", libelle)

    def test_le_secret_est_la_premiere_ligne_de_l_entree(self):
        todo = TODO.__new__(TODO)
        code = todo._container_dans(
            ["sh", "-c", 'read l; [ "$l" = "maitre-invente-76" ]'],
            "libelle",
            secret="maitre-invente-76",
        )
        self.assertEqual(code, 0)

    def test_l_execution_passe_par_le_journal(self):
        todo = TODO.__new__(TODO)
        with mock.patch.object(
            container_menu.todo_journal, "lancer_journalise", return_value=7
        ) as lancer:
            code = todo._container_dans(
                ["docker", "exec"], "libelle", "entree"
            )
        self.assertEqual(code, 7)
        lancer.assert_called_once_with(
            ["docker", "exec"], libelle="libelle", stdin="entree"
        )

    def test_un_echec_de_copie_nettoie_et_ne_restaure_pas(self):
        lances, sortie = self.lancer(["n", "", "o"], codes={"RECEVOIR": 1})
        self.assertEqual([n for n, _ in lances], ["RECEVOIR", "NETTOYER"])

    def test_une_base_existante_n_est_ecrasee_que_sur_confirmation(self):
        lances, _ = self.lancer(["n"], bases=[("essai_base", True)])
        self.assertEqual(lances, [])
        lances, _ = self.lancer(
            ["o", "o", "n", "o"], bases=[("essai_base", True)]
        )
        self.assertEqual(
            lances[1], ("RESTAURER", ["essai_base", "-f", "-n", "--move"])
        )

    def test_une_base_neuve_ne_demande_pas_le_mot_de_passe(self):
        self.maitre = []
        self.lancer(["n", "", "o"])
        self.assertIn(("RESTAURER", "", True), self.secrets)

    def test_restaurer_par_dessus_demande_le_mot_de_passe(self):
        self.maitre = ["maitre-invente-73"]
        self.lancer(["o", "n", "", "o"], bases=[("essai_base", False)])
        self.assertIn(("RESTAURER", "maitre-invente-73", True), self.secrets)

    def test_par_defaut_une_copie_avec_un_nouvel_uuid(self):
        """Le défaut du gestionnaire web d'Odoo : « This database is a copy »."""
        lances, sortie = self.lancer(["n", "", "o"])
        self.assertEqual(lances[1], ("RESTAURER", ["essai_base"]))
        self.assertIn(
            container_menu.t("This database is a copy: it gets a new UUID."),
            sortie,
        )

    def test_une_base_deplacee_garde_son_uuid(self):
        lances, _ = self.lancer(["n", "n", "o"])
        self.assertEqual(lances[1], ("RESTAURER", ["essai_base", "--move"]))

    def test_un_refus_final_ne_copie_rien(self):
        lances, _ = self.lancer(["n", "", "n"])
        self.assertEqual(lances, [])

    def test_un_nom_invalide_ne_lance_rien(self):
        lances, sortie = self.lancer([], prompts=["a b"])
        self.assertEqual(lances, [])

    def test_le_manque_d_espace_se_dit_et_se_refuse(self):
        self.SONDE = dict(self.SONDE, libre_data=10)
        lances, sortie = self.lancer(["n"])
        self.assertEqual(lances, [])
        self.assertIn(
            container_menu.t("Not enough free space for this restore."), sortie
        )

    def test_la_base_vide_laissee_par_un_echec_peut_partir(self):
        self.maitre = ["maitre-invente-74", "maitre-invente-75"]
        todo_bases = [("essai_base", True)]
        lances, _ = self.lancer(
            ["o", "n", "", "o", "o"],
            bases=todo_bases,
            codes={"RESTAURER": 1},
        )
        self.assertEqual(
            [n for n, _ in lances],
            ["RECEVOIR", "RESTAURER", "NETTOYER", "SUPPRIMER"],
        )
        self.assertIn(("SUPPRIMER", "maitre-invente-75", True), self.secrets)


if __name__ == "__main__":
    unittest.main()
