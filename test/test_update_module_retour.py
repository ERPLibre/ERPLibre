#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""update_module : redémarrage de PostgreSQL et retour arrière du code.

Le théâtre est celui de `test_update_module.py` (`FauxSysteme`, `Base`) :
aucun systemctl, psql ni pg_dump réel. S'y ajoutent :

- `sous_le_compte` appelle la fonction directement, sa valeur passée par
  JSON comme le ferait le vrai tube : l'extraction, la copie tar, leur
  remise et les renommages de filestore écrivent pour de vrai, dans le
  dossier temporaire du test ;
- les commandes git passent à un vrai git, dans des dépôts créés pour le
  test sous le dossier de travail de l'unité ;
- `pg_isready`, la requête des sessions de chaque base, `systemctl
  restart` et `start` de l'unité PostgreSQL, son état, le dossier de
  données, les droits du rôle, l'empreinte des modules, la fermeture, la
  réouverture et le renommage d'une base (psql sur son entrée) sont
  joués ;
- l'espace libre et le dispositif d'un chemin viennent de `volumes` :
  un test y range un dossier sur son propre système de fichiers ;
- la restauration (`odoo_backup.restaurer`) est remplacée : elle note
  son appel et crée le filestore de la copie, comme la vraie.

Les messages attendus passent par `t()` : les tests valent dans les deux
langues. Les noms sont inventés.
"""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profil_isole import profil_isole  # noqa: E402
from test_update_module import Base, FauxSysteme  # noqa: E402

from script.database import odoo_backup  # noqa: E402
from script.lib_ops import postgres, retour_code, service, systemd  # noqa: E402
from script.odoo import update_module as um  # noqa: E402

t = um.t

UNITE_PG = "postgresql@16-main.service"
LISTE_PG = (
    "postgresql.service loaded active exited PostgreSQL RDBMS\n"
    f"{UNITE_PG} loaded active running PostgreSQL Cluster 16-main\n"
)


def setUpModule():
    profil_isole()


def git(depot, *arguments):
    """Un vrai git dans `depot`, identité inventée ; rend stdout."""
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Exemple",
        GIT_AUTHOR_EMAIL="exemple@example.org",
        GIT_COMMITTER_NAME="Exemple",
        GIT_COMMITTER_EMAIL="exemple@example.org",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return subprocess.run(
        ["git", "-C", depot] + list(arguments),
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    ).stdout.strip()


def zip_de(chemin, membres):
    """Écrit le zip `chemin` : `membres` est [(nom, contenu)] ou
    [(ZipInfo, contenu)]."""
    with zipfile.ZipFile(chemin, "w") as archive:
        for nom, contenu in membres:
            archive.writestr(nom, contenu)
    return chemin


def lien(nom, cible):
    info = zipfile.ZipInfo(nom)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info, cible


class FauxSystemeRetour(FauxSysteme):
    """FauxSysteme, plus PostgreSQL, git, et les fonctions sous le compte
    de l'unité exécutées pour de vrai."""

    def __init__(self, wd, dossier_verrou):
        super().__init__(wd, dossier_verrou)
        self.sous_compte = []
        self.liste_unites = LISTE_PG
        self.unites_chargees = {UNITE_PG, "postgresql.service"}
        self.restart_pg_code = 0
        # L'ActiveState de l'unité PostgreSQL, celui qu'un restart en échec
        # lui laisse, et le code de son `systemctl start`.
        self.etat_pg = "active"
        self.etat_pg_apres_echec = "active"
        self.demarrage_pg_code = 0
        # Les réponses successives de pg_isready ; épuisées, prêt.
        self.pg_pret = []
        self.pg_isready_absent = False
        # {base: sessions} rendu par la requête des connexions ; None :
        # psql échoue.
        self.connexions = {"demo_db": 2}
        # Les réponses servies aux lectures successives des sessions avant
        # `connexions` ; épuisées, `connexions`.
        self.connexions_lectures = []
        # Le dossier de données du serveur (None : illisible), le droit
        # CREATEDB du rôle, l'empreinte des modules de la base.
        self.dossier_pg = os.path.join(os.path.dirname(wd), "pgdata")
        os.makedirs(self.dossier_pg, exist_ok=True)
        self.createdb = True
        self.empreinte = "0123456789abcdef0123456789abcdef"
        # {dossier: (dispositif, octets libres)} : un chemin sous l'un
        # d'eux en prend les valeurs ; les autres, le dispositif 0 et
        # `libre`.
        self.volumes = {}
        # Les renommages de bases joués : (ancienne, nouvelle) ; un nom
        # dans `renommage_refuse`, ou qui commence par un préfixe de
        # `prefixes_refuses`, fait échouer psql ; un nom de
        # `refus_passagers`, le nombre de fois donné.
        self.renommages = []
        self.renommage_refuse = set()
        self.prefixes_refuses = ()
        self.refus_passagers = {}
        # Les bases fermées puis rouvertes aux connexions, dans l'ordre.
        self.fermetures = []
        self.ouvertures = []
        # Les codes HTTP servis aux sondes successives ; épuisés, `sonde`.
        self.sondes = []

    def sous_le_compte(self, utilisateur, fonction, *arguments):
        self.appels.append(f"compte {fonction.__name__}")
        self.sous_compte.append((utilisateur, fonction.__name__))
        self._lever(fonction.__name__)
        return json.loads(json.dumps(fonction(*arguments)))

    def lanceur(self, argv, timeout=60):
        if argv[:2] == ["systemctl", "restart"]:
            self.appels.append(" ".join(argv))
            if self.restart_pg_code:
                self.etat_pg = self.etat_pg_apres_echec
            return self.restart_pg_code, "Job failed" * bool(
                self.restart_pg_code
            )
        if argv[:2] == ["systemctl", "start"] and argv[-1] in (
            self.unites_chargees
        ):
            self.appels.append(" ".join(argv))
            if not self.demarrage_pg_code:
                self.etat_pg = "active"
            return self.demarrage_pg_code, ""
        if argv[:2] == ["systemctl", "show"] and argv[-1] in (
            self.unites_chargees
        ):
            self.appels.append(" ".join(argv))
            return 0, f"LoadState=loaded\nActiveState={self.etat_pg}\n"
        return super().lanceur(argv, timeout)

    def _volume(self, chemin):
        trouve = None
        for dossier, valeurs in self.volumes.items():
            if chemin == dossier or chemin.startswith(dossier + os.sep):
                if trouve is None or len(dossier) > len(trouve[0]):
                    trouve = (dossier, valeurs)
        return trouve[1] if trouve else (0, self.libre)

    def espace_libre(self, chemin):
        return self._volume(chemin)[1]

    def dispositif(self, chemin):
        return self._volume(chemin)[0]

    def sonder(self, cible, delai):
        self.appels.append(f"sonde {cible}")
        return self.sondes.pop(0) if self.sondes else self.sonde

    def requete(self, argv, env, delai=60):
        noms = [os.path.basename(a) for a in argv]
        if "pg_isready" in noms:
            self.appels.append("pg_isready")
            if self.pg_isready_absent:
                return 127, "", "absent"
            if self.etat_pg != "active":
                return 2, "", ""
            pret = self.pg_pret.pop(0) if self.pg_pret else True
            return (0 if pret else 2), "", ""
        if "psql" in noms and argv[-1] == postgres.REQUETE_DOSSIER:
            if self.dossier_pg is None:
                return 2, "", "permission refusée"
            return 0, self.dossier_pg + "\n", ""
        if "psql" in noms and argv[-1] == postgres.REQUETE_DROITS:
            self.appels.append("droits")
            return 0, json.dumps({"createdb": self.createdb}) + "\n", ""
        if "psql" in noms and argv[-1] == postgres.REQUETE_EMPREINTE_MODULES:
            self.appels.append("empreinte")
            return 0, json.dumps({"stamp": self.empreinte}) + "\n", ""
        if "psql" in noms and argv[-1] == "SELECT 1":
            self.appels.append("select 1")
            return 0, "1\n", ""
        if "psql" in noms and argv[-1] == postgres.REQUETE_CONNEXIONS:
            self.appels.append("connexions")
            connexions = (
                self.connexions_lectures.pop(0)
                if self.connexions_lectures
                else self.connexions
            )
            if connexions is None:
                return 2, "", "connexion refusée"
            reponse = {"databases": connexions or None}
            return 0, json.dumps(reponse) + "\n", ""
        if argv[:1] == ["git"]:
            self.appels.append("git " + " ".join(argv[3:5]))
            fin = subprocess.run(
                argv,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            return fin.returncode, fin.stdout, fin.stderr
        return super().requete(argv, env, delai)

    def alimenter(self, argv, env, morceaux, delai):
        variables = dict(
            argv[i + 1].split("=", 1)
            for i, a in enumerate(argv)
            if a == "-v" and "=" in argv[i + 1]
        )
        script = b"".join(morceaux).decode("utf-8")
        if script == postgres.SCRIPT_FERMETURE:
            self.appels.append(f"fermer {variables['base']}")
            self.fermetures.append(variables["base"])
            return 0, [], False
        if script == postgres.SCRIPT_OUVERTURE:
            self.appels.append(f"ouvrir {variables['base']}")
            self.ouvertures.append(variables["base"])
            return 0, [], False
        ancienne, nouvelle = (
            variables.get("ancienne"),
            variables.get("nouvelle"),
        )
        self.appels.append(f"renommer {ancienne} {nouvelle}")
        self.vu.setdefault("scripts_renommage", []).append(script)
        if self.refus_passagers.get(ancienne):
            self.refus_passagers[ancienne] -= 1
            return 1, ["ERROR:  database is being accessed"], False
        if ancienne in self.renommage_refuse or ancienne.startswith(
            self.prefixes_refuses
        ):
            return 1, ["ERROR:  database is being accessed"], False
        self.renommages.append((ancienne, nouvelle))
        return 0, [], False


class BaseRetour(Base):
    def setUp(self):
        super().setUp()
        self.systeme = FauxSystemeRetour(self.wd, self.verrous)
        self.custom = os.path.join(self.wd, "custom")
        self.restaurations = []
        self.restauration_code = um.CODE_OK
        rustine = mock.patch.object(
            um.odoo_backup, "restaurer", self._restaurer
        )
        rustine.start()
        self.addCleanup(rustine.stop)

    def _restaurer(self, cible, systeme, rapport, fichier, nouvelle, **kw):
        systeme.appels.append(f"restaurer {nouvelle}")
        self.restaurations.append((fichier, nouvelle, kw))
        if self.restauration_code == um.CODE_OK:
            os.makedirs(os.path.join(cible.data_dir, "filestore", nouvelle))
        return self.restauration_code

    def lancer_seul(self, *options):
        """`lancer` sans le `--module my_module_*` par défaut."""
        argv = ["--log-dir", self.journaux]
        argv += ["--backup-dest", self.dest, "--state-dir", self.etat]
        argv += list(options) + ["--service", "erplibre_demo"]
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = um.report.Rapport(
            flux=sortie, erreurs=erreurs, couleur=False
        )
        with (
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(erreurs),
        ):
            code = um.main(argv, self.systeme, rapport)
        self.sortie, self.erreurs = sortie.getvalue(), erreurs.getvalue()
        return code

    def compte(self, debut):
        return sum(1 for a in self.systeme.appels if a.startswith(debut))

    def lire(self, *parties):
        with open(os.path.join(*parties), encoding="utf-8") as f:
            return f.read()


# --- Archive zip : inspection --------------------------------------------


class TestInspectionZip(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = d.name

    def chemin(self, nom="exemple.zip"):
        return os.path.join(self.tmp, nom)

    def refus(self, membres):
        zip_de(self.chemin(), membres)
        with self.assertRaises(service.Refus) as err:
            retour_code.inspecter_zip(self.chemin())
        return err.exception.message(t)

    def test_modules_et_versions(self):
        zip_de(
            self.chemin(),
            [
                ("mod_a/__manifest__.py", "{'version': '18.0.1.2'}"),
                ("mod_a/models/a.py", "x = 1\n"),
                ("mod_b/", ""),
                ("mod_b/__manifest__.py", "{'name': 'B'}"),
            ],
        )
        inspection = retour_code.inspecter_zip(self.chemin())
        self.assertEqual(
            inspection.modules, {"mod_a": "18.0.1.2", "mod_b": "?"}
        )
        self.assertGreater(inspection.octets, 0)

    def test_chemins_qui_sortent_refuses(self):
        for nom in (
            "/etc/exemple",
            "mod_a/../../exemple",
            "../exemple/__manifest__.py",
            "mod_a\\..\\exemple",
            "C:/exemple",
            "mod_a//double",
        ):
            with self.subTest(nom=nom):
                message = self.refus(
                    [("mod_a/__manifest__.py", "{}"), (nom, "x")]
                )
                self.assertIn(nom, message)

    def test_lien_symbolique_refuse(self):
        message = self.refus(
            [
                ("mod_a/__manifest__.py", "{}"),
                lien("mod_a/static/lien", "/etc/exemple"),
            ]
        )
        self.assertIn("mod_a/static/lien", message)

    def test_fichier_special_refuse(self):
        info = zipfile.ZipInfo("mod_a/tube")
        info.external_attr = (stat.S_IFIFO | 0o644) << 16
        message = self.refus([("mod_a/__manifest__.py", "{}"), (info, "")])
        self.assertIn("mod_a/tube", message)

    def test_fichier_a_la_racine_refuse(self):
        message = self.refus(
            [("mod_a/__manifest__.py", "{}"), ("LISEZMOI", "x")]
        )
        self.assertIn("LISEZMOI", message)

    def test_dossier_sans_manifeste_refuse(self):
        message = self.refus(
            [("mod_a/__manifest__.py", "{}"), ("pas_module/x.py", "")]
        )
        self.assertIn("pas_module", message)
        message = self.refus([("mod-a/__manifest__.py", "{}")])
        self.assertIn("mod-a", message)

    def test_nom_en_double_refuse(self):
        """L'extraction échouerait sur le second, Odoo déjà arrêté."""
        with self.assertWarns(UserWarning):
            message = self.refus(
                [
                    ("mod_a/__manifest__.py", "{}"),
                    ("mod_a/a.py", "1"),
                    ("mod_a/a.py", "2"),
                ]
            )
        self.assertIn("mod_a/a.py", message)

    def test_archive_illisible(self):
        with open(self.chemin(), "wb") as f:
            f.write(b"pas un zip")
        with self.assertRaises(service.Refus):
            retour_code.inspecter_zip(self.chemin())
        with self.assertRaises(service.Refus):
            retour_code.inspecter_zip(self.chemin("absente.zip"))


class TestExtractionEtRemise(unittest.TestCase):
    """Les fonctions sous le compte de l'unité, appelées directement."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = d.name
        self.addons = os.path.join(self.tmp, "addons")
        os.makedirs(os.path.join(self.addons, "mod_a", "vieux"))
        with open(
            os.path.join(self.addons, "mod_a", "__manifest__.py"), "w"
        ) as f:
            f.write("{'version': '1'}")
        with open(
            os.path.join(self.addons, "mod_a", "vieux", "retire.py"), "w"
        ) as f:
            f.write("ancien\n")
        self.archive = zip_de(
            os.path.join(self.tmp, "exemple.zip"),
            [
                ("mod_a/__manifest__.py", "{'version': '2'}"),
                ("mod_a/neuf.py", "neuf\n"),
                ("mod_c/__manifest__.py", "{'version': '1'}"),
            ],
        )
        self.copie = os.path.join(self.tmp, "copie.tar.gz")

    def contenu(self, *parties):
        with open(os.path.join(self.addons, *parties)) as f:
            return f.read()

    def test_aller_retour(self):
        modules = ["mod_a", "mod_c"]
        sauves = retour_code.copier_modules(self.addons, modules, self.copie)
        self.assertEqual(sauves, ["mod_a"])
        self.assertEqual(stat.S_IMODE(os.stat(self.copie).st_mode), 0o600)
        with open(self.archive, "rb") as fichier:
            places = retour_code.extraire_zip(fichier, self.addons, modules)
        self.assertEqual(places, modules)
        # Le dossier est remplacé en entier : l'ancien fichier est parti.
        self.assertFalse(
            os.path.exists(os.path.join(self.addons, "mod_a", "vieux"))
        )
        self.assertEqual(self.contenu("mod_a", "neuf.py"), "neuf\n")
        self.assertTrue(os.path.isdir(os.path.join(self.addons, "mod_c")))
        self.assertEqual(sorted(os.listdir(self.addons)), ["mod_a", "mod_c"])
        issue = retour_code.remettre_modules(
            self.addons, modules, self.copie, sauves
        )
        self.assertEqual(issue, {"remis": ["mod_a"], "retires": ["mod_c"]})
        self.assertEqual(
            self.contenu("mod_a", "vieux", "retire.py"), "ancien\n"
        )
        self.assertEqual(
            self.contenu("mod_a", "__manifest__.py"), "{'version': '1'}"
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.addons, "mod_a", "neuf.py"))
        )
        self.assertEqual(sorted(os.listdir(self.addons)), ["mod_a"])

    def test_copie_jamais_ecrasee(self):
        with open(self.copie, "w") as f:
            f.write("deja la")
        with self.assertRaises(FileExistsError):
            retour_code.copier_modules(self.addons, ["mod_a"], self.copie)
        with open(self.copie) as f:
            self.assertEqual(f.read(), "deja la")

    def test_archive_changee_depuis_l_inspection(self):
        """L'extraction revérifie chaque membre : rien n'est remplacé."""
        zip_de(
            self.archive,
            [
                ("mod_a/__manifest__.py", "{}"),
                ("mod_a/../../evade.py", "x"),
            ],
        )
        with open(self.archive, "rb") as fichier:
            with self.assertRaises(ValueError):
                retour_code.extraire_zip(fichier, self.addons, ["mod_a"])
        self.assertTrue(
            os.path.isdir(os.path.join(self.addons, "mod_a", "vieux"))
        )
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evade.py")))
        self.assertEqual(sorted(os.listdir(self.addons)), ["mod_a"])

    def test_copie_d_un_module_en_lien(self):
        ailleurs = os.path.join(self.tmp, "ailleurs", "mod_l")
        os.makedirs(ailleurs)
        os.symlink(ailleurs, os.path.join(self.addons, "mod_l"))
        sauves = retour_code.copier_modules(self.addons, ["mod_l"], self.copie)
        self.assertEqual(sauves, ["mod_l"])
        with tarfile.open(self.copie) as tar:
            (membre,) = tar.getmembers()
        self.assertTrue(membre.issym())
        os.unlink(os.path.join(self.addons, "mod_l"))
        os.mkdir(os.path.join(self.addons, "mod_l"))
        retour_code.remettre_modules(
            self.addons, ["mod_l"], self.copie, sauves
        )
        self.assertTrue(os.path.islink(os.path.join(self.addons, "mod_l")))
        self.assertTrue(os.path.isdir(ailleurs))

    def test_copie_qui_sort_refusee(self):
        with tarfile.open(self.copie, "w:gz") as tar:
            info = tarfile.TarInfo("../evade.py")
            tar.addfile(info, io.BytesIO(b""))
        with self.assertRaises(ValueError):
            retour_code.remettre_modules(
                self.addons, ["mod_a"], self.copie, ["mod_a"]
            )
        self.assertTrue(
            os.path.isdir(os.path.join(self.addons, "mod_a", "vieux"))
        )


# --- Archive zip : la mise à jour ----------------------------------------


class TestMiseAJourZip(BaseRetour):
    def setUp(self):
        super().setUp()
        ecrire = __import__("test_update_module").ecrire
        ecrire(os.path.join(self.custom, "my_module_a", "ancien.py"), "a\n")
        self.archive = zip_de(
            os.path.join(self.tmp, "modules.zip"),
            [
                ("my_module_a/__manifest__.py", "{'version': '18.0.2.0'}"),
                ("my_module_a/neuf.py", "n\n"),
                ("my_module_c/__manifest__.py", "{'version': '18.0.1.0'}"),
            ],
        )

    def copies(self):
        return sorted(
            n for n in os.listdir(self.dossier) if n.startswith("code-")
        )

    def test_ordre_copie_extraction_puis_mise_a_jour(self):
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_OK, self.sortie
        )
        rang = self.rang
        self.assertLess(rang("systemctl stop"), rang("backup "))
        self.assertLess(rang("backup "), rang("compte copier_modules"))
        self.assertLess(
            rang("compte copier_modules"), rang("compte extraire_zip")
        )
        self.assertLess(rang("compte extraire_zip"), rang("odoo "))
        self.assertLess(rang("odoo "), rang("systemctl start"))
        argv = self.systeme.vu["odoo"]["argv"]
        self.assertEqual(argv[argv.index("-u") + 1], "my_module_a,my_module_c")
        self.assertTrue(
            os.path.isfile(os.path.join(self.custom, "my_module_a", "neuf.py"))
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.custom, "my_module_a", "ancien.py")
            )
        )
        (copie,) = self.copies()
        with tarfile.open(os.path.join(self.dossier, copie)) as tar:
            noms = tar.getnames()
        self.assertIn("my_module_a/ancien.py", noms)
        self.assertFalse(any(n.startswith("my_module_c") for n in noms))
        self.assertEqual(self.restaurations, [])
        self.assertEqual(
            {nom for _u, nom in self.systeme.sous_compte},
            {"copier_modules", "extraire_zip"},
        )

    def test_echec_du_u_remet_la_base_puis_le_code(self):
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        rang = self.rang
        self.assertLess(rang("odoo "), rang("restaurer "))
        self.assertLess(rang("restaurer "), rang("fermer demo_db"))
        self.assertLess(rang("fermer demo_db"), rang("renommer demo_db "))
        self.assertLess(
            rang("renommer demo_db "), rang("compte remettre_modules")
        )
        self.assertLess(
            rang("compte remettre_modules"), rang("systemctl start")
        )
        self.assertEqual(self.systeme.etat, "active")
        # La base laissée par la mise à jour reste fermée aux connexions.
        self.assertEqual(self.systeme.fermetures, ["demo_db"])
        self.assertEqual(self.systeme.ouvertures, [])
        # Le code d'avant : le fichier retiré par l'archive est revenu,
        # le module ajouté est parti.
        self.assertTrue(
            os.path.isfile(
                os.path.join(self.custom, "my_module_a", "ancien.py")
            )
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.custom, "my_module_c"))
        )
        # La base : restaurée de la sauvegarde de CETTE exécution dans une
        # copie, qui prend la place de la base.
        ((fichier, copie, kw),) = self.restaurations
        self.assertRegex(os.path.basename(fichier), r"^demo_db_.*\.zip$")
        self.assertTrue(copie.startswith("demo_db_rollback_"))
        self.assertEqual(kw, {"rappels": False})
        ((a1, b1), (a2, b2)) = self.systeme.renommages
        self.assertEqual(a1, "demo_db")
        self.assertTrue(b1.startswith("demo_db_failed_"))
        self.assertEqual((a2, b2), (copie, "demo_db"))
        filestores = os.path.join(self.wd, "data", "filestore")
        self.assertEqual(
            sorted(os.listdir(filestores)), sorted(["demo_db", b1])
        )
        self.assertTrue(
            os.path.isfile(os.path.join(filestores, b1, "ab", "f0"))
        )
        self.assertIn(
            t(
                "Rollback done: the code and the database are those of"
                " before the update."
            ),
            self.sortie,
        )
        self.assertIn(
            t(
                "{failed} accepts no connection (Odoo does not list it); to"
                " examine it: ALTER DATABASE {failed} WITH ALLOW_CONNECTIONS"
                " true"
            ).format(failed=b1),
            self.sortie,
        )
        self.assertIn(t("Update failed."), self.sortie)

    def _verifier_interruption(self):
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_INTERROMPU
        )
        rang = self.rang
        self.assertLess(rang("restaurer "), rang("compte remettre_modules"))
        self.assertLess(
            rang("compte remettre_modules"), rang("systemctl start")
        )
        self.assertEqual(len(self.restaurations), 1)
        self.assertEqual(self.systeme.etat, "active")
        self.assertTrue(
            os.path.isfile(
                os.path.join(self.custom, "my_module_a", "ancien.py")
            )
        )

    def test_interruption_du_u_remet_la_base_et_le_code(self):
        self.systeme.odoo_issue = um.Issue(0, False, True)
        self._verifier_interruption()

    def test_ctrl_c_pendant_le_u_remet_la_base_et_le_code(self):
        self.systeme.lever["odoo"] = KeyboardInterrupt()
        self._verifier_interruption()

    def test_echec_de_la_relance_arrete_remet_puis_relance(self):
        # Première relance sans réponse HTTP, seconde servie.
        self.systeme.sondes = [0, 200]
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        self.assertEqual(self.compte("systemctl stop"), 2)
        self.assertEqual(self.compte("systemctl start"), 2)
        appels = self.systeme.appels
        second_stop = [
            i for i, a in enumerate(appels) if a.startswith("systemctl stop")
        ][1]
        self.assertLess(second_stop, self.rang("compte remettre_modules"))
        self.assertLess(
            self.rang("restaurer "),
            max(
                i
                for i, a in enumerate(appels)
                if a.startswith("systemctl start")
            ),
        )
        self.assertEqual(self.systeme.etat, "active")
        self.assertEqual(len(self.restaurations), 1)

    def code_de_la_mise_a_jour_reste(self):
        """Le code de l'archive est en place : la base n'est pas revenue,
        et l'ancien code ne doit pas tourner sur la base migrée."""
        self.assertFalse(self.a_appele("compte remettre_modules"))
        self.assertTrue(
            os.path.isfile(os.path.join(self.custom, "my_module_a", "neuf.py"))
        )
        self.assertIn(t("Rollback: the code was not put back."), self.sortie)
        self.assertIn(
            t("Rollback: the database was not restored."), self.sortie
        )

    def test_restauration_en_echec_garde_le_code_de_la_mise_a_jour(self):
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.restauration_code = um.CODE_ECHEC
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        self.assertEqual(self.systeme.renommages, [])
        self.code_de_la_mise_a_jour_reste()
        self.assertEqual(self.systeme.etat, "active")

    def test_renommage_refuse_defait_les_filestores(self):
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.systeme.renommage_refuse = {"demo_db"}
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        filestores = os.path.join(self.wd, "data", "filestore")
        ((_f, copie, _kw),) = self.restaurations
        self.assertEqual(
            sorted(os.listdir(filestores)), sorted(["demo_db", copie])
        )
        self.assertTrue(
            os.path.isfile(os.path.join(filestores, "demo_db", "ab", "f0"))
        )
        # Retenté, borné, puis la base rouverte sous son nom.
        self.assertEqual(
            self.compte("renommer demo_db "), um.TENTATIVES_RENOMMAGE
        )
        self.assertEqual(self.systeme.ouvertures, ["demo_db"])
        self.code_de_la_mise_a_jour_reste()

    def test_second_renommage_refuse_remet_la_base(self):
        """`<copie>` → `demo_db` refusé, une fois `demo_db` renommée : le
        renommage fait est défait, la base reprend son nom et rouvre."""
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.systeme.prefixes_refuses = ("demo_db_rollback_",)
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        ((_f, copie, _kw),) = self.restaurations
        (aller, retour) = self.systeme.renommages
        self.assertEqual(aller[0], "demo_db")
        self.assertTrue(aller[1].startswith("demo_db_failed_"))
        self.assertEqual(retour, (aller[1], "demo_db"))
        filestores = os.path.join(self.wd, "data", "filestore")
        self.assertEqual(
            sorted(os.listdir(filestores)), sorted(["demo_db", copie])
        )
        self.assertTrue(
            os.path.isfile(os.path.join(filestores, "demo_db", "ab", "f0"))
        )
        self.assertLess(
            self.rang(f"renommer {aller[1]} "), self.rang("ouvrir")
        )
        self.assertEqual(self.systeme.ouvertures, ["demo_db"])
        self.assertIn(
            t(
                "The restored copy {copy} could not take the place of"
                " {database}: both are kept, put them in place by hand."
            ).format(copy=copie, database="demo_db"),
            self.sortie,
        )
        self.code_de_la_mise_a_jour_reste()

    def test_session_qui_tarde_renommage_retente(self):
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.systeme.refus_passagers = {"demo_db": 1}
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        self.assertEqual(self.compte("renommer demo_db "), 2)
        self.assertEqual(len(self.systeme.renommages), 2)
        self.assertIn(
            t(
                "Rollback done: the code and the database are those of"
                " before the update."
            ),
            self.sortie,
        )

    def test_extraction_en_echec_remet_sans_restaurer(self):
        self.systeme.lever["extraire_zip"] = OSError("disque plein")
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_ECHEC
        )
        self.assertFalse(self.a_appele("odoo "))
        self.assertTrue(self.a_appele("compte remettre_modules"))
        self.assertEqual(self.restaurations, [])
        self.assertEqual(self.systeme.etat, "active")

    def test_refus_avant_l_arret(self):
        dangereuse = zip_de(
            os.path.join(self.tmp, "dangereuse.zip"),
            [("my_module_a/__manifest__.py", "{}"), ("../evade.py", "x")],
        )
        for options in (
            ("--zip", dangereuse),
            ("--zip", os.path.join(self.tmp, "absente.zip")),
            ("--zip", self.archive, "--addons-dir", "ailleurs"),
        ):
            with self.subTest(options=options):
                self.systeme.appels.clear()
                self.assertEqual(self.lancer_seul(*options), um.CODE_REFUS)
                self.assertFalse(self.a_appele("systemctl stop"))

    def test_module_plus_tot_dans_l_addons_path_refuse(self):
        ecrire = __import__("test_update_module").ecrire
        ecrire(
            os.path.join(self.wd, "addons", "my_module_a", "__manifest__.py"),
            "{}",
        )
        self.assertEqual(
            self.lancer_seul("--zip", self.archive, "--addons-dir", "custom"),
            um.CODE_REFUS,
        )
        self.assertIn(os.path.join(self.wd, "addons"), self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))

    def refus_de_place(self, dossier):
        """Le refus d'espace, avant l'arrêt, nomme `dossier`."""
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_REFUS
        )
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertIn(dossier, self.erreurs)

    def test_place_de_l_extraction_refuse(self):
        """Le dossier d'addons, sur son propre système de fichiers, n'a
        pas la place de l'archive décompressée ; la sauvegarde, si."""
        self.systeme.volumes = {self.custom: (1, 10)}
        self.refus_de_place(self.custom)
        self.assertNotIn(self.dest, self.erreurs)

    def test_place_de_la_copie_tar_refuse(self):
        """Le dossier de sauvegarde a la place du dump, pas du dump et de
        la copie tar ensemble."""
        ecrire = __import__("test_update_module").ecrire
        ecrire(
            os.path.join(self.custom, "my_module_a", "gros.bin"), "x" * 100000
        )
        self.systeme.volumes = {self.dest: (2, 50000)}
        self.refus_de_place(self.dest)

    def test_place_de_la_restauration_refuse(self):
        """Le dossier de données de PostgreSQL n'a pas la place de la
        copie que le retour arrière restaurerait."""
        self.systeme.volumes = {self.systeme.dossier_pg: (3, 100)}
        self.refus_de_place(self.systeme.dossier_pg)

    def test_createdb_absent_refuse(self):
        self.systeme.createdb = False
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_REFUS
        )
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertIn("CREATEDB", self.erreurs)

    def test_dossier_pg_illisible_refuse_hors_simulation(self):
        self.systeme.dossier_pg = None
        self.assertEqual(
            self.lancer_seul("--zip", self.archive), um.CODE_REFUS
        )
        self.assertFalse(self.a_appele("systemctl stop"))
        raison = t("data directory of PostgreSQL unreadable")
        self.assertIn(raison, self.erreurs)
        self.assertEqual(
            self.lancer_seul("--zip", self.archive, "--dry-run"), um.CODE_OK
        )
        self.assertIn(raison, self.sortie)

    def test_sans_sauvegarde_refuse(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as fin:
                um.analyser(["--zip", self.archive, "--no-backup"])
        self.assertEqual(fin.exception.code, 2)

    def test_simulation(self):
        self.assertEqual(
            self.lancer_seul("--zip", self.archive, "--dry-run"), um.CODE_OK
        )
        self.assertIn(t("replaced"), self.sortie)
        self.assertIn(t("new"), self.sortie)
        self.assertIn("my_module_c 18.0.1.0", self.sortie)
        self.assertIn(t("the tar copy put back"), self.sortie)
        self.assertFalse(self.a_appele("compte "))
        self.assertTrue(
            os.path.isfile(
                os.path.join(self.custom, "my_module_a", "ancien.py")
            )
        )


# --- Retour git -------------------------------------------------------------


class TestRetourGit(BaseRetour):
    def setUp(self):
        super().setUp()
        git(self.custom, "init", "-q")
        git(self.custom, "add", "-A")
        git(self.custom, "commit", "-q", "-m", "avant")
        self.avant = git(self.custom, "rev-parse", "HEAD")
        with open(
            os.path.join(self.custom, "my_module_a", "neuf.py"), "w"
        ) as f:
            f.write("n\n")
        git(self.custom, "add", "-A")
        git(self.custom, "commit", "-q", "-m", "apres")
        self.apres = git(self.custom, "rev-parse", "HEAD")
        self.depot = os.path.realpath(self.custom)
        self.reference = os.path.join(
            self.etat, "demo_db", um.NOM_REFERENCE_GIT
        )

    def noter(self, sha, empreinte=None):
        os.makedirs(os.path.dirname(self.reference), exist_ok=True)
        retour_code.ecrire_reference(
            self.reference,
            {self.depot: sha},
            1.0,
            self.systeme.empreinte if empreinte is None else empreinte,
        )

    def test_reference_d_autres_modules_ecartee(self):
        """La base a été mise à jour depuis la référence par un autre
        moyen : revenir à celle-ci remettrait un code plus ancien que la
        base restaurée. Seule la base revient."""
        self.noter(self.avant, empreinte="f" * 32)
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.assertEqual(self.lancer("--rollback", "git"), um.CODE_ECHEC)
        self.assertEqual(git(self.custom, "rev-parse", "HEAD"), self.apres)
        self.assertEqual(len(self.restaurations), 1)
        self.assertIn(
            t("the modules of the database changed since it was noted"),
            self.sortie,
        )

    def test_interruption_revient_a_la_reference(self):
        self.noter(self.avant)
        self.systeme.odoo_issue = um.Issue(0, False, True)
        self.assertEqual(self.lancer("--rollback", "git"), um.CODE_INTERROMPU)
        self.assertEqual(git(self.custom, "rev-parse", "HEAD"), self.avant)
        self.assertEqual(len(self.restaurations), 1)
        self.assertEqual(self.systeme.etat, "active")

    def test_seuls_les_depots_sous_le_dossier_de_travail(self):
        """Le dépôt du dossier de travail lui-même (le checkout qui porte
        les outils) et un dépôt hors de lui ne sont jamais ramenés."""
        ecrire = __import__("test_update_module").ecrire
        git(self.wd, "init", "-q")
        git(self.wd, "add", "run.sh")
        git(self.wd, "commit", "-q", "-m", "checkout")
        dehors = os.path.join(self.tmp, "dehors")
        ecrire(os.path.join(dehors, "mod_dehors", "__manifest__.py"), "{}")
        git(dehors, "init", "-q")
        git(dehors, "add", "-A")
        git(dehors, "commit", "-q", "-m", "dehors")
        chemin = os.path.join(self.wd, "trois.conf")
        with open(chemin, "w") as f:
            f.write(
                self.CONFIG.replace("addons,custom", f"addons,custom,{dehors}")
            )
        self.assertEqual(
            self.lancer("--rollback", "git", "--odoo-conf", chemin),
            um.CODE_OK,
            self.sortie,
        )
        with open(self.reference) as f:
            donnees = json.load(f)
        self.assertEqual(
            retour_code.depots_de_reference(donnees), {self.depot: self.apres}
        )

    def test_echec_revient_a_la_reference_et_restaure(self):
        self.noter(self.avant)
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.assertEqual(self.lancer("--rollback", "git"), um.CODE_ECHEC)
        self.assertEqual(git(self.custom, "rev-parse", "HEAD"), self.avant)
        # Détaché : la branche garde son commit.
        self.assertIn(
            self.apres, git(self.custom, "branch", "-v", "--no-abbrev")
        )
        self.assertEqual(len(self.restaurations), 1)
        self.assertLess(self.rang("odoo "), self.rang("restaurer "))
        self.assertLess(self.rang("restaurer "), self.rang("systemctl start"))
        self.assertEqual(self.systeme.etat, "active")

    def test_sans_reference_seule_la_base_revient(self):
        self.systeme.odoo_issue = um.Issue(1, False, False)
        self.assertEqual(self.lancer("--rollback", "git"), um.CODE_ECHEC)
        self.assertEqual(git(self.custom, "rev-parse", "HEAD"), self.apres)
        self.assertEqual(len(self.restaurations), 1)
        self.assertIn(
            t("No repository moved since the reference: the code stays."),
            self.sortie,
        )

    def test_reussite_note_la_reference(self):
        self.assertEqual(
            self.lancer("--rollback", "git"), um.CODE_OK, self.sortie
        )
        with open(self.reference) as f:
            donnees = json.load(f)
        self.assertEqual(
            retour_code.depots_de_reference(donnees), {self.depot: self.apres}
        )
        self.assertEqual(
            retour_code.empreinte_de_reference(donnees), self.systeme.empreinte
        )
        self.assertEqual(self.restaurations, [])
        self.assertEqual(git(self.custom, "rev-parse", "HEAD"), self.apres)

    def test_depot_modifie_refuse_avant_l_arret(self):
        self.noter(self.avant)
        with open(
            os.path.join(self.custom, "my_module_a", "neuf.py"), "w"
        ) as f:
            f.write("modifié\n")
        self.assertEqual(self.lancer("--rollback", "git"), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertIn(self.depot, self.erreurs)

    def test_commit_absent_refuse_avant_l_arret(self):
        self.noter("0" * 40)
        self.assertEqual(self.lancer("--rollback", "git"), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_sans_depot_refuse(self):
        self.assertEqual(
            self.lancer("--rollback", "git", "--odoo-conf", self.sans_git()),
            um.CODE_REFUS,
        )
        self.assertFalse(self.a_appele("systemctl stop"))

    def sans_git(self):
        chemin = os.path.join(self.wd, "sans_git.conf")
        with open(chemin, "w") as f:
            f.write(self.CONFIG.replace("addons,custom", "addons"))
        return chemin

    def test_simulation_montre_la_reference(self):
        self.noter(self.avant)
        self.assertEqual(
            self.lancer("--rollback", "git", "--dry-run"), um.CODE_OK
        )
        self.assertIn(f"{self.apres[:12]} → {self.avant[:12]}", self.sortie)
        self.assertEqual(git(self.custom, "rev-parse", "HEAD"), self.apres)

    def test_profil_ecarte_avec_no_backup(self):
        """`rollback` du profil ne rend pas invalide une ligne valide."""
        chemin = os.path.join(self.tmp, "odoo-exemple.service.json")
        um.profil.ecrire(
            chemin,
            {
                "version": um.profil.VERSION,
                "service": "odoo-exemple.service",
                "update_module": {"rollback": "git"},
            },
        )
        args = um.analyser(
            ["--module", "base", "--no-backup", "--profile", chemin]
        )
        self.assertEqual(args.rollback, "none")


# --- PostgreSQL ---------------------------------------------------------------


class TestRedemarragePostgresql(BaseRetour):
    def test_ordre_pendant_l_arret_d_odoo(self):
        self.systeme.pg_pret = [False, True]
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"),
            um.CODE_OK,
            self.sortie,
        )
        rang = self.rang
        self.assertLess(rang("connexions"), rang("systemctl stop"))
        self.assertLess(rang("systemctl stop"), rang("sessions"))
        self.assertLess(
            rang("sessions"), rang(f"systemctl restart -- {UNITE_PG}")
        )
        self.assertLess(
            rang(f"systemctl restart -- {UNITE_PG}"), rang("pg_isready")
        )
        self.assertLess(rang("pg_isready"), rang("backup "))
        self.assertLess(rang("backup "), rang("odoo "))
        self.assertEqual(self.compte("pg_isready"), 2)

    def test_relance_seule(self):
        self.assertEqual(
            self.lancer_seul(
                "--restart-only", "--restart-postgresql", "--yes"
            ),
            um.CODE_OK,
            self.sortie,
        )
        self.assertLess(
            self.rang("systemctl stop"), self.rang("systemctl restart")
        )
        self.assertLess(
            self.rang("systemctl restart"), self.rang("systemctl start")
        )

    def test_autre_base_connectee_refuse_sans_terminal(self):
        self.systeme.connexions = {"demo_db": 2, "autre_db": 1}
        self.assertEqual(self.lancer("--restart-postgresql"), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertIn("autre_db", self.erreurs)

    def test_seule_la_base_de_l_instance_passe_sans_terminal(self):
        self.assertEqual(self.lancer("--restart-postgresql"), um.CODE_OK)
        self.assertEqual(self.systeme.questions, [])

    def test_sessions_illisibles_refusent_sans_terminal(self):
        self.systeme.connexions = None
        self.assertEqual(self.lancer("--restart-postgresql"), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_question_au_terminal(self):
        self.systeme.interactif = True
        self.systeme.connexions = {"demo_db": 2, "autre_db": 1}
        self.systeme.reponses_oui = [False]
        self.assertEqual(self.lancer("--restart-postgresql"), um.CODE_REFUS)
        (question,) = self.systeme.questions
        self.assertIn("autre_db (1)", question)
        self.assertIn("demo_db (2)", question)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.systeme.reponses_oui = [True]
        self.systeme.appels.clear()
        self.assertEqual(self.lancer("--restart-postgresql"), um.CODE_OK)
        self.assertTrue(self.a_appele("systemctl restart"))

    def test_yes_saute_la_question(self):
        self.systeme.interactif = True
        self.systeme.connexions = {"autre_db": 1}
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"), um.CODE_OK
        )
        self.assertEqual(self.systeme.questions, [])

    def test_echec_du_restart_relance_odoo_sans_u(self):
        self.systeme.restart_pg_code = 1
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"), um.CODE_ECHEC
        )
        self.assertFalse(self.a_appele("odoo "))
        self.assertTrue(self.a_appele("systemctl start"))
        self.assertEqual(self.systeme.etat, "active")

    def test_attente_bornee(self):
        self.systeme.pg_pret = [False] * 1000
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes", "--start-wait", "5"),
            um.CODE_ECHEC,
        )
        self.assertFalse(self.a_appele("odoo "))
        self.assertTrue(self.a_appele("systemctl start"))
        self.assertLessEqual(self.compte("pg_isready"), 7)

    def test_sans_pg_isready_select_1(self):
        self.systeme.pg_isready_absent = True
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"), um.CODE_OK
        )
        self.assertTrue(self.a_appele("select 1"))

    def test_unite_ambigue_ou_absente_refuse(self):
        for liste in (
            LISTE_PG + "postgresql@15-main.service loaded active running x\n",
            "postgresql.service loaded inactive dead x\n",
        ):
            with self.subTest(liste=liste):
                self.systeme.liste_unites = liste
                self.systeme.appels.clear()
                self.assertEqual(
                    self.lancer("--restart-postgresql", "--yes"), um.CODE_REFUS
                )
                self.assertFalse(self.a_appele("systemctl stop"))

    def test_pg_service_nomme_l_unite(self):
        self.systeme.liste_unites = ""
        self.assertEqual(
            self.lancer(
                "--restart-postgresql", "--yes", "--pg-service", "postgresql"
            ),
            um.CODE_OK,
        )
        self.assertTrue(
            self.a_appele("systemctl restart -- postgresql.service")
        )

    def test_pg_service_hors_postgresql_refuse(self):
        """La valeur peut venir du profil : l'unité de l'instance ou une
        autre unité ne reçoivent jamais le restart."""
        self.systeme.unites_chargees.add("nginx.service")
        for unite in ("erplibre_demo.service", "nginx.service"):
            with self.subTest(unite=unite):
                self.systeme.appels.clear()
                self.assertEqual(
                    self.lancer(
                        "--restart-postgresql", "--yes", "--pg-service", unite
                    ),
                    um.CODE_REFUS,
                )
                self.assertFalse(self.a_appele("systemctl stop"))
                self.assertIn(unite, self.erreurs)

    def test_sessions_relues_avant_le_restart(self):
        """Sans accord, une autre base connectée pendant l'arrêt d'Odoo
        saute le restart : pas de -u, Odoo relancé."""
        self.systeme.connexions_lectures = [{"demo_db": 2}, {"autre_db": 1}]
        self.assertEqual(self.lancer("--restart-postgresql"), um.CODE_ECHEC)
        self.assertEqual(self.compte("connexions"), 2)
        self.assertFalse(self.a_appele("systemctl restart"))
        self.assertFalse(self.a_appele("odoo "))
        self.assertTrue(self.a_appele("systemctl start"))
        self.assertEqual(self.systeme.etat, "active")
        self.assertIn("autre_db", self.sortie)

    def test_accord_ne_relit_pas_les_sessions(self):
        self.systeme.connexions_lectures = [{"demo_db": 2}, {"autre_db": 1}]
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"), um.CODE_OK
        )
        self.assertEqual(self.compte("connexions"), 1)

    def test_restart_qui_laisse_postgresql_arrete_le_redemarre(self):
        self.systeme.restart_pg_code = 1
        self.systeme.etat_pg_apres_echec = "failed"
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"), um.CODE_ECHEC
        )
        self.assertLess(
            self.rang("systemctl restart"),
            self.rang(f"systemctl start -- {UNITE_PG}"),
        )
        self.assertEqual(self.systeme.etat_pg, "active")
        self.assertIn(
            t("PostgreSQL started again and accepting connections."),
            self.sortie,
        )
        self.assertFalse(self.a_appele("odoo "))
        self.assertEqual(self.systeme.etat, "active")

    def test_postgresql_qui_ne_repart_pas_le_dit(self):
        self.systeme.restart_pg_code = 1
        self.systeme.etat_pg_apres_echec = "failed"
        self.systeme.demarrage_pg_code = 1
        self.assertEqual(
            self.lancer("--restart-postgresql", "--yes"), um.CODE_ECHEC
        )
        self.assertIn(
            t(
                "PostgreSQL is not available: {unit} is {state}. Every"
                " database of the server stays down until it is started."
            ).format(unit=UNITE_PG, state="failed"),
            self.sortie,
        )
        self.assertEqual(self.systeme.etat, "active")

    def test_autre_hote_refuse(self):
        chemin = os.path.join(self.wd, "distant.conf")
        with open(chemin, "w") as f:
            f.write(self.CONFIG + "db_host = 192.0.2.20\n")
        self.assertEqual(
            self.lancer(
                "--restart-postgresql", "--yes", "--odoo-conf", chemin
            ),
            um.CODE_REFUS,
        )
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_simulation(self):
        self.systeme.connexions = {"demo_db": 2, "autre_db": 1}
        self.assertEqual(
            self.lancer("--restart-postgresql", "--dry-run"), um.CODE_OK
        )
        self.assertIn(f"systemctl restart -- {UNITE_PG}", self.sortie)
        self.assertIn(
            t("{database}: {count} session(s)").format(
                database="autre_db", count=1
            ),
            self.sortie,
        )
        self.assertFalse(self.a_appele("systemctl restart"))

    def test_options_refusees(self):
        for argv in (
            ["--update-list", "--restart-postgresql"],
            ["--module", "base", "--yes"],
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as fin:
                        um.analyser(argv)
                self.assertEqual(fin.exception.code, 2)


# --- Bibliothèques ----------------------------------------------------------


class TestUnitePostgresql(unittest.TestCase):
    def lanceur(self, sortie):
        return lambda argv, timeout=60: (0, sortie)

    def test_choix(self):
        for sortie, attendu in (
            (LISTE_PG, UNITE_PG),
            (
                "postgresql.service loaded active running x\n",
                "postgresql.service",
            ),
            (
                "postgresql-16.service loaded active running x\n",
                "postgresql-16.service",
            ),
        ):
            with self.subTest(sortie=sortie):
                self.assertEqual(
                    systemd.unite_postgresql(self.lanceur(sortie)), attendu
                )

    def test_ambigue_et_absente(self):
        with self.assertRaises(systemd.ErreurUnite) as err:
            systemd.unite_postgresql(
                self.lanceur(
                    LISTE_PG
                    + "postgresql@15-main.service loaded active running x\n"
                )
            )
        self.assertEqual(str(err.exception), "ambiguous")
        self.assertEqual(len(err.exception.candidates), 2)
        with self.assertRaises(systemd.ErreurUnite):
            systemd.unite_postgresql(self.lanceur(""))


class TestRenommageDeBase(unittest.TestCase):
    def test_noms_en_variables_jamais_dans_le_sql(self):
        cible = odoo_backup.Cible(
            prefixe=["runuser", "-u", "demo", "--"], outils={"psql": "psql"}
        )
        argv = odoo_backup.argv_renommage(cible, "exemple_db", "exemple_db_x")
        self.assertIn("ancienne=exemple_db", argv)
        self.assertIn("nouvelle=exemple_db_x", argv)
        self.assertNotIn("-c", argv)
        self.assertNotIn("exemple_db", postgres.SCRIPT_RENOMMAGE)

    def test_nom_invalide_refuse_sans_rien_lancer(self):
        systeme = mock.Mock()
        cible = odoo_backup.Cible(outils={})
        for message in (
            odoo_backup.renommer_base(cible, systeme, "a;b", "c"),
            odoo_backup.fermer_base(cible, systeme, "a;b"),
            odoo_backup.ouvrir_base(cible, systeme, "-a"),
        ):
            self.assertTrue(message)
        self.assertFalse(systeme.alimenter.called)

    def test_scripts_sans_nom(self):
        for script in (postgres.SCRIPT_FERMETURE, postgres.SCRIPT_OUVERTURE):
            self.assertIn(':"base"', script)
            self.assertNotIn("exemple_db", script)


class TestEspaceParSystemeDeFichiers(unittest.TestCase):
    """`verifier_espaces` somme les besoins d'un même dispositif."""

    def systeme(self, dispositifs):
        systeme = mock.Mock()
        systeme.espace_libre.return_value = 100
        systeme.dispositif.side_effect = lambda chemin: dispositifs[chemin]
        return systeme

    def test_meme_dispositif_somme(self):
        with (
            tempfile.TemporaryDirectory() as a,
            tempfile.TemporaryDirectory() as b,
        ):
            besoins = [(a, 60), (b, 60)]
            with self.assertRaises(odoo_backup.ManqueEspace):
                odoo_backup.verifier_espaces(
                    self.systeme({a: 1, b: 1}), besoins
                )
            odoo_backup.verifier_espaces(self.systeme({a: 1, b: 2}), besoins)

    def test_dispositif_illisible_seul(self):
        with (
            tempfile.TemporaryDirectory() as a,
            tempfile.TemporaryDirectory() as b,
        ):

            def dispositif(chemin):
                if chemin != a:
                    raise OSError("illisible")
                return 1

            systeme = self.systeme({})
            systeme.dispositif.side_effect = dispositif
            odoo_backup.verifier_espaces(systeme, [(a, 60), (b, 60)])


if __name__ == "__main__":
    unittest.main()
