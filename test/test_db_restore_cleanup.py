#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une restauration qui échoue ne laisse pas de base vide derrière elle.

Odoo crée la base AVANT d'extraire l'image. Un échec d'extraction laisse
donc une base vide ; quand c'est un cache « _cache_<image> », la relance
suivante le trouve, saute la restauration et clone le vide.

Trois protections, éprouvées ici avec la commande « db » d'Odoo simulée :

- l'échec supprime la base que CE passage a créée, et seulement elle ;
- un cache existant sans tables est supprimé et recréé avant d'être cloné ;
- deux passages simultanés sur la même image ne suppriment rien l'un à
  l'autre : le second attend le verrou du premier.
"""

import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.database import db_restore  # noqa: E402

ARG_BASE = "./odoo_bin.sh db"

# La trace d'Odoo quand l'extraction de l'image dépasse le quota de son
# temporaire : la pile passe par « _extract_member » de zipfile.
TRACE_EXTRACTION_QUOTA = """Traceback (most recent call last):
  File "/odoo/odoo/service/db.py", line 299, in restore_db
    z.extractall(dump_dir, ['dump.sql'] + filestore)
  File "/usr/lib/python3.12/zipfile/__init__.py", line 1744, in extractall
    self._extract_member(zipinfo, path, pwd)
  File "/usr/lib/python3.12/zipfile/__init__.py", line 1799, in _extract_member
    shutil.copyfileobj(source, target)
  File "/usr/lib/python3.12/shutil.py", line 204, in copyfileobj
    fdst_write(buf)
OSError: [Errno 122] Disk quota exceeded
"""


class FauxOdoo:
    """La commande « db » d'Odoo et PostgreSQL, réduits à un ensemble de noms.

    `bases` : nom → chargée (True) ou vide (False). « load » crée la
    base vide PUIS échoue si `echec_restauration` est posé, comme Odoo
    quand l'extraction échoue ; sinon il la charge, sauf si `restaure_vide`
    imite un « psql » qui rend zéro sans rien charger.
    `echec_avant_creation` imite un Odoo qui échoue avant de créer la base,
    `drop_sans_effet` un « drop » qui sort en zéro sans rien supprimer,
    et `pendant_restauration(nom)` est appelé une fois la base vide créée,
    comme pendant l'extraction.
    """

    def __init__(self, bases=None):
        self.bases = dict(bases or {})
        self.echec_restauration = False
        self.echec_avant_creation = False
        self.restaure_vide = False
        self.drop_sans_effet = False
        self.pendant_restauration = None
        self.supprimees = []
        self.commandes = []

    def check_output(self, args, env=None, **_kw):
        self.commandes.append(" ".join(args))
        action = args[2]
        if action == "list":
            return "\n".join(sorted(self.bases)).encode()
        if action == "load":
            nom = args[3]
            if nom in self.bases or self.echec_avant_creation:
                raise subprocess.CalledProcessError(1, args, b"")
            self.bases[nom] = False
            if self.pendant_restauration:
                self.pendant_restauration(nom)
            if self.echec_restauration:
                raise subprocess.CalledProcessError(
                    1, args, TRACE_EXTRACTION_QUOTA.encode()
                )
            self.bases[nom] = not self.restaure_vide
            return b""
        if action == "duplicate":
            source, nom = args[3], args[4]
            self.bases[nom] = self.bases[source]
            return b""
        raise AssertionError(args)

    def charger(self, args, env=None):
        # Passe par le « check_output » du module : un test qui le remplace
        # (une interruption, par exemple) atteint aussi le chargement.
        try:
            db_restore.check_output(args, env=env)
        except subprocess.CalledProcessError as erreur:
            repere = db_restore.RepereManqueDePlace()
            for ligne in (erreur.output or b"").decode().splitlines():
                repere.lire(ligne)
            return erreur.returncode, repere.vu
        return 0, False

    def run(self, args, **_kw):
        self.commandes.append(" ".join(args))
        assert args[2] == "drop", args
        nom = args[-1]
        if self.drop_sans_effet:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.bases.pop(nom, None) is not None:
            self.supprimees.append(nom)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def est_chargee(self, nom):
        return self.bases.get(nom)

    def base_existe(self, nom):
        return nom in self.bases


class Base(unittest.TestCase):
    def brancher(self, odoo):
        for cible, remplacement in (
            ("check_output", odoo.check_output),
            ("charger", odoo.charger),
            ("est_chargee", odoo.est_chargee),
            ("base_existe", odoo.base_existe),
            ("restore_env", lambda image: None),
            ("verify_filestore", lambda *a: None),
        ):
            patch = mock.patch.object(db_restore, cible, remplacement)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(db_restore.subprocess, "run", odoo.run)
        patch.start()
        self.addCleanup(patch.stop)
        sortie = mock.patch("sys.stdout", new_callable=io.StringIO)
        sortie.start()
        self.addCleanup(sortie.stop)
        # Les verrous vivent sous le répertoire personnel : un jetable.
        maison = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, maison)
        patch = mock.patch.dict(
            os.environ, {"HOME": maison, "XDG_CACHE_HOME": ""}
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.maison = maison
        return odoo

    def remplacer(self, objet, nom, valeur):
        patch = mock.patch.object(objet, nom, valeur)
        patch.start()
        self.addCleanup(patch.stop)

    def config(self, **kw):
        valeurs = dict(
            image="essai",
            database="essai_db",
            ignore_cache=False,
            neutralize=False,
        )
        valeurs.update(kw)
        return SimpleNamespace(**valeurs)

    def lancer(self, odoo, config):
        db_restore.restore_or_clone(config, ARG_BASE, f"_cache_{config.image}")


class TestNettoyageSurEchec(Base):
    def test_le_cache_cree_par_ce_passage_est_supprime(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        with self.assertRaises(SystemExit) as sortie:
            self.lancer(odoo, self.config())
        self.assertEqual(odoo.supprimees, ["_cache_essai"])
        self.assertNotIn("_cache_essai", odoo.bases)
        self.assertNotIn("essai_db", odoo.bases)  # le clone n'a pas eu lieu
        message = str(sortie.exception)
        self.assertIn("supprimée", message)
        self.assertIn("TMPDIR", message)

    def test_le_chemin_sans_cache_supprime_aussi_sa_base(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        with self.assertRaises(SystemExit):
            self.lancer(odoo, self.config(ignore_cache=True))
        self.assertEqual(odoo.supprimees, ["essai_db"])
        self.assertEqual(odoo.bases, {})

    def test_une_base_restee_vide_est_un_echec(self):
        # « psql » rend zéro sans rien charger : la base existe, vide.
        odoo = self.brancher(FauxOdoo())
        odoo.restaure_vide = True
        with self.assertRaises(SystemExit) as sortie:
            self.lancer(odoo, self.config())
        self.assertEqual(odoo.supprimees, ["_cache_essai"])
        self.assertIn("VIDE", str(sortie.exception))

    def test_une_base_qui_existait_avant_n_est_jamais_supprimee(self):
        # Une base au nom visé existe déjà (chargée ou non) : Odoo refuse
        # de restaurer par-dessus, et ce refus ne doit rien supprimer.
        odoo = self.brancher(FauxOdoo({"essai_db": True}))
        with self.assertRaises(SystemExit) as sortie:
            db_restore.restaurer(ARG_BASE, "essai", "essai_db")
        self.assertEqual(odoo.supprimees, [])
        self.assertEqual(odoo.bases, {"essai_db": True})
        self.assertIn("laissée telle quelle", str(sortie.exception))

    def test_une_interruption_defait_aussi(self):
        odoo = self.brancher(FauxOdoo())
        reel = odoo.check_output

        def interrompre(args, **kw):
            if args[2] == "load":
                reel(args, **kw)  # la base vide est créée…
                raise KeyboardInterrupt  # … puis l'opérateur interrompt
            return reel(args, **kw)

        self.remplacer(db_restore, "check_output", interrompre)
        with self.assertRaises(SystemExit):
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        self.assertEqual(odoo.supprimees, ["_cache_essai"])

    def test_un_etat_inconnu_ne_supprime_rien(self):
        # « psql » muet : la base est peut-être bonne, on ne la supprime
        # pas, et l'on n'échoue pas non plus — Odoo a rendu zéro.
        odoo = self.brancher(FauxOdoo())
        self.remplacer(db_restore, "est_chargee", lambda nom: None)
        with self.assertLogs(db_restore._logger, "WARNING") as journal:
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        self.assertEqual(odoo.supprimees, [])
        self.assertIn("_cache_essai", odoo.bases)
        self.assertIn("non vérifiée", "\n".join(journal.output))

    def test_un_echec_avant_creation_ne_pretend_rien_supprimer(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_avant_creation = True
        with self.assertRaises(SystemExit) as sortie:
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        self.assertFalse(odoo.commandes[-1].startswith(f"{ARG_BASE} drop"))
        message = str(sortie.exception)
        self.assertIn("avant de créer _cache_essai", message)
        self.assertNotIn("supprimée", message)

    def test_un_drop_sans_effet_n_est_pas_annonce_comme_fait(self):
        # « db drop » peut sortir en zéro sur une base qu'Odoo ne liste pas :
        # c'est PostgreSQL qui dit si elle a disparu.
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        odoo.drop_sans_effet = True
        with self.assertRaises(SystemExit) as sortie:
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        message = str(sortie.exception)
        self.assertIn("existe encore", message)
        self.assertIn("db drop _cache_essai", message)
        self.assertNotIn("supprimée", message)

    def test_une_suppression_ratee_dit_la_commande_a_lancer(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        echec = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        self.remplacer(db_restore.subprocess, "run", lambda *a, **k: echec)
        with self.assertLogs(db_restore._logger, "ERROR"):
            with self.assertRaises(SystemExit) as sortie:
                db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        self.assertIn(
            "./odoo_bin.sh db drop _cache_essai",
            str(sortie.exception),
        )


class TestConseilTmpdir(Base):
    """Une extraction qui manque de place nomme le TMPDIR où relancer."""

    COMMANDE = ["./script/database/db_restore.py", "--database", "test"]

    def setUp(self):
        self.remplacer(sys, "argv", list(self.COMMANDE))
        self.remplacer(
            db_restore, "espace_utilisable", lambda c: 40 * db_restore.GIO
        )

    def test_le_quota_donne_la_commande_avec_le_cache_utilisateur(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        with self.assertRaises(SystemExit) as sortie:
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        message = str(sortie.exception)
        self.assertIn(
            "TMPDIR=~/.cache/erplibre_restore ./script/database/"
            "db_restore.py --database test",
            message,
        )
        self.assertIn("40.0 Gio libres", message)
        self.assertNotIn("Si la trace parle", message)

    def test_sous_make_la_cible_est_rappelee(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        with (
            mock.patch.dict(os.environ, {"MAKELEVEL": "1"}),
            self.assertRaises(SystemExit) as sortie,
        ):
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        self.assertIn(
            "TMPDIR=~/.cache/erplibre_restore make <cible>",
            str(sortie.exception),
        )

    def test_un_repli_deja_plein_demande_un_autre_disque(self):
        odoo = self.brancher(FauxOdoo())
        odoo.echec_restauration = True
        repli = db_restore.dossier_travail()
        self.remplacer(
            db_restore, "restore_env", lambda image: {"TMPDIR": repli}
        )
        with self.assertRaises(SystemExit) as sortie:
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        message = str(sortie.exception)
        self.assertIn("le dossier de repli", message)
        self.assertIn("TMPDIR=<dossier> ./script/database/", message)

    def test_un_autre_echec_garde_le_conseil_general(self):
        odoo = self.brancher(FauxOdoo())
        reel = odoo.check_output

        def echouer(args, **kw):
            if "load" in args:
                raise subprocess.CalledProcessError(1, args, b"KeyError")
            return reel(args, **kw)

        self.remplacer(db_restore, "check_output", echouer)
        with self.assertRaises(SystemExit) as sortie:
            db_restore.restaurer(ARG_BASE, "essai", "_cache_essai")
        message = str(sortie.exception)
        self.assertIn("Si la trace parle", message)
        self.assertNotIn("TMPDIR=~", message)


class TestCharger(unittest.TestCase):
    """« charger » montre la sortie au fil de l'eau, ne retient que le
    manque de place de l'extraction, et ne laisse pas d'enfant derrière
    une interruption."""

    def lancer(self, script):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as vu:
            resultat = db_restore.charger([sys.executable, "-c", script], None)
        return resultat, vu.getvalue()

    def test_l_extraction_pleine_est_reperee(self):
        # Une vraie extraction zipfile, dont l'écriture lève ENOSPC : la
        # pile porte les cadres de l'interpréteur qui tourne.
        (code, manque), vu = self.lancer(
            "import errno, io, shutil, zipfile, tempfile\n"
            "tampon = io.BytesIO()\n"
            "with zipfile.ZipFile(tampon, 'w') as z:\n"
            "    z.writestr('dump.sql', 'select 1;')\n"
            "def plein(*a, **k):\n"
            "    raise OSError(errno.ENOSPC, 'No space left on device')\n"
            "shutil.copyfileobj = plein\n"
            "print('chargement', flush=True)\n"
            "with zipfile.ZipFile(tampon) as z:\n"
            "    z.extractall(tempfile.mkdtemp())\n"
        )
        self.assertEqual(code, 1)
        self.assertTrue(manque)
        self.assertIn("chargement", vu)
        self.assertIn("No space left on device", vu)

    def test_le_filestore_plein_n_accuse_pas_le_temporaire(self):
        # « shutil.move » vers un autre disque copie, et c'est le disque du
        # data_dir qui manque de place : TMPDIR n'y change rien.
        (code, manque), vu = self.lancer(
            "import errno, os, shutil, tempfile\n"
            "source, cible = tempfile.mkdtemp(), tempfile.mkdtemp()\n"
            "def autre_disque(*a, **k):\n"
            "    raise OSError(errno.EXDEV, 'Invalid cross-device link')\n"
            "def plein(*a, **k):\n"
            "    raise OSError(errno.ENOSPC, 'No space left on device')\n"
            "os.rename = autre_disque\n"
            "shutil.copytree = plein\n"
            "shutil.move(source, os.path.join(cible, 'filestore'))\n"
        )
        self.assertEqual(code, 1)
        self.assertFalse(manque)
        self.assertIn("No space left on device", vu)

    def test_un_manque_de_place_sans_trace_ne_signale_rien(self):
        (code, manque), _vu = self.lancer(
            "import sys\n"
            "sys.stderr.write('OSError: [Errno 28] No space left on device\\n')\n"
            "sys.exit(1)\n"
        )
        self.assertEqual((code, manque), (1, False))

    def test_une_trace_suivante_remet_le_repere_a_zero(self):
        repere = db_restore.RepereManqueDePlace()
        lignes = TRACE_EXTRACTION_QUOTA.splitlines()
        # Une première trace passe par l'extraction sans manquer de place,
        # la seconde manque de place ailleurs.
        for ligne in lignes[:-1]:
            repere.lire(ligne)
        repere.lire("Traceback (most recent call last):")
        repere.lire('  File "/usr/lib/python3.12/shutil.py", line 9, in move')
        repere.lire(lignes[-1])
        self.assertFalse(repere.vu)

    def test_une_sortie_saine_ne_signale_rien(self):
        (code, manque), vu = self.lancer("print('ok')")
        self.assertEqual((code, manque), (0, False))
        self.assertIn("ok", vu)

    def test_une_interruption_tue_l_enfant(self):
        lances = []
        vrai_popen = subprocess.Popen

        def espion(*args, **kwargs):
            lances.append(vrai_popen(*args, **kwargs))
            return lances[-1]

        def interrompre(_ligne):
            raise KeyboardInterrupt

        with (
            mock.patch.object(db_restore.subprocess, "Popen", espion),
            mock.patch.object(db_restore, "redact_secrets", interrompre),
            self.assertRaises(KeyboardInterrupt),
        ):
            db_restore.charger(
                [
                    sys.executable,
                    "-c",
                    "import time\nprint('ok', flush=True)\ntime.sleep(30)",
                ],
                None,
            )
        # Tué et attendu : le code de retour est connu, sans attendre les
        # trente secondes de l'enfant.
        self.assertEqual(lances[0].returncode, -9)


class TestCacheVide(Base):
    def test_un_cache_vide_est_supprime_recree_puis_clone(self):
        odoo = self.brancher(FauxOdoo({"_cache_essai": False}))
        with self.assertLogs(db_restore._logger, "WARNING"):
            self.lancer(odoo, self.config())
        self.assertEqual(odoo.supprimees, ["_cache_essai"])
        self.assertTrue(odoo.bases["_cache_essai"])
        self.assertTrue(odoo.bases["essai_db"])
        restaurations = [c for c in odoo.commandes if " load " in c]
        self.assertEqual(len(restaurations), 1)

    def test_un_cache_charge_est_clone_sans_restauration(self):
        odoo = self.brancher(FauxOdoo({"_cache_essai": True}))
        self.lancer(odoo, self.config())
        self.assertEqual(odoo.supprimees, [])
        self.assertFalse(any(" load " in c for c in odoo.commandes))
        self.assertTrue(odoo.bases["essai_db"])

    def test_un_cache_non_verifiable_est_clone_tel_quel(self):
        # L'état inconnu n'est pas un vide : rien n'est supprimé.
        odoo = self.brancher(FauxOdoo({"_cache_essai": True}))
        self.remplacer(db_restore, "est_chargee", lambda nom: None)
        self.lancer(odoo, self.config())
        self.assertEqual(odoo.supprimees, [])
        self.assertIn("essai_db", odoo.bases)

    def test_seul_le_cache_vise_est_touche(self):
        odoo = self.brancher(
            FauxOdoo({"_cache_essai": False, "_cache_autre": False})
        )
        with self.assertLogs(db_restore._logger, "WARNING"):
            self.lancer(odoo, self.config())
        self.assertEqual(odoo.supprimees, ["_cache_essai"])
        self.assertIn("_cache_autre", odoo.bases)


class TestPassagesSimultanes(Base):
    def test_un_second_passage_attend_au_lieu_de_supprimer(self):
        # A crée le cache vide et extrait encore quand B arrive. Sans
        # verrou, B voit un cache sans tables et le supprime sous A.
        odoo = self.brancher(FauxOdoo())
        cree, libere, attente = (threading.Event() for _ in range(3))

        def pendant(_nom):
            cree.set()
            libere.wait(10)

        class Guetteur(logging.Handler):
            def emit(self, record):
                if "attente" in record.getMessage():
                    attente.set()

        guetteur = Guetteur()
        db_restore._logger.addHandler(guetteur)
        self.addCleanup(db_restore._logger.removeHandler, guetteur)
        erreurs = []

        def passage(base):
            try:
                self.lancer(odoo, self.config(database=base))
            except BaseException as erreur:  # noqa: BLE001
                erreurs.append(erreur)

        odoo.pendant_restauration = pendant
        a = threading.Thread(target=passage, args=("essai_a",))
        a.start()
        self.assertTrue(cree.wait(10))
        b = threading.Thread(target=passage, args=("essai_b",))
        b.start()
        self.assertTrue(attente.wait(10), "B n'attend pas le verrou de A")
        libere.set()
        a.join(10)
        b.join(10)
        self.assertEqual(erreurs, [])
        self.assertEqual(odoo.supprimees, [])
        restaurations = [c for c in odoo.commandes if " load " in c]
        self.assertEqual(len(restaurations), 1)
        self.assertTrue(odoo.bases["essai_a"])
        self.assertTrue(odoo.bases["essai_b"])


class TestPsql(unittest.TestCase):
    """« psql » se connecte comme Odoo, et le nom n'entre pas dans le SQL."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)
        self.config = os.path.join(self.dossier, "odoo.conf")
        with open(self.config, "w") as f:
            f.write(
                "[options]\ndb_host = hote-essai\ndb_port = False\n"
                "db_user = role_essai\ndb_password = mot%de%passe\n"
            )
        patch = mock.patch.dict(os.environ, {"ODOO_RC": self.config})
        patch.start()
        self.addCleanup(patch.stop)
        self.appels = []

    def repondre(self, reponse):
        def check_output(args, **kw):
            self.appels.append((args, kw))
            return reponse

        patch = mock.patch.object(db_restore, "check_output", check_output)
        patch.start()
        self.addCleanup(patch.stop)

    def test_les_parametres_d_odoo_passent_a_psql(self):
        env = db_restore.environnement_pg("a=b")
        self.assertEqual(env["PGHOST"], "hote-essai")
        self.assertEqual(env["PGUSER"], "role_essai")
        self.assertEqual(env["PGPASSWORD"], "mot%de%passe")
        self.assertEqual(env["PGDATABASE"], "a=b")
        self.assertNotEqual(env.get("PGPORT"), "False")

    def test_est_chargee_sans_invite_ni_privilege(self):
        self.repondre(b"t\n")
        self.assertTrue(db_restore.est_chargee("_cache_x"))
        args, kw = self.appels[0]
        self.assertIn("-XtAqw", args)
        self.assertIn(b"to_regclass", kw["input"])
        self.assertEqual(kw["env"]["PGDATABASE"], "_cache_x")

    def test_base_existe_passe_le_nom_en_variable(self):
        self.repondre(b"0\n")
        self.assertIs(db_restore.base_existe("x'; drop"), False)
        args, kw = self.appels[0]
        self.assertIn("nom=x'; drop", args)
        self.assertNotIn(b"drop", kw["input"])
        self.assertEqual(kw["env"]["PGDATABASE"], "postgres")

    def test_psql_muet_rend_none(self):
        def echoue(*_a, **_k):
            raise subprocess.CalledProcessError(2, "psql")

        with mock.patch.object(db_restore, "check_output", echoue):
            with self.assertLogs(db_restore._logger, "ERROR"):
                self.assertIsNone(db_restore.est_chargee("_cache_x"))


class TestSupprimerBase(unittest.TestCase):
    def test_passe_par_la_commande_drop_d_odoo(self):
        vu = []

        def run(args, **kw):
            vu.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(db_restore.subprocess, "run", run):
            self.assertTrue(db_restore.supprimer_base(ARG_BASE, "_cache_x"))
        self.assertEqual(
            vu, [["./odoo_bin.sh", "db", "drop", "--if-exists", "_cache_x"]]
        )


if __name__ == "__main__":
    unittest.main()
