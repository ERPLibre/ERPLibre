#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La sauvegarde produite est relue, et le constat SURVIT.

Le témoin était écrit, documenté, éprouvé par vingt épreuves — et aucun
fichier de `script/` ne l'importait. C'est le motif de défaut que ce dépôt
collectionne : un mécanisme complet, absent du chemin réellement emprunté.

DEUX CHEMINS PRODUISENT UNE SAUVEGARDE, et ils ne se comportaient pas
pareil. Celui qui télécharge relisait l'archive puis jetait le constat ;
celui qui sauvegarde localement ne regardait même pas le code de retour,
si bien qu'un échec rendait exactement le même écran qu'un succès.

INTROUVABLE N'EST PAS ABSENTE. Le nom d'archive est résolu par `odoo-bin`,
dont le code ne vit pas dans ce dépôt : ne pas trouver le fichier dit
qu'on ne sait pas où il est. Annoncer « absente » là où la sauvegarde est
peut-être parfaite serait le mensonge que le témoin existe pour retirer.

Aucun fichier n'est écrit sur le disque : le vérificateur et le témoin
sont remplacés au banc.
"""

import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.database import backup_verify as V  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.database_manager import DatabaseManager  # noqa: E402

SAINE = V.Verification(V.SOUND, "image_db/essai.zip", 4096, ("dump",))
CASSEE = V.Verification(V.NO_DUMP, "image_db/essai.zip", 12, ())


class Execute:
    """Le lanceur de commandes, remplacé : rien ne part vers un shell."""

    def __init__(self, status=0):
        self.status = status
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        if kwargs.get("return_status_and_command"):
            return self.status, cmd
        return self.status, []


class Banc(unittest.TestCase):
    def setUp(self):
        self.poses = []
        self.vus = []
        patcheur = patch.multiple(
            "script.todo.database_manager.backup_witness",
            record=lambda constat: self.poses.append(constat) or {},
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def verificateur(self, constat):
        def verify(chemin, deep=True):
            self.vus.append(chemin)
            return constat._replace(path=chemin)

        return patch.object(
            __import__(
                "script.todo.database_manager", fromlist=["backup_verify"]
            ).backup_verify,
            "verify",
            verify,
        )


class TestOuLArchiveEstCherchee(unittest.TestCase):
    """Deux formes ont cours : « nom » et « nom.zip »."""

    def test_a_name_that_carries_its_extension_is_found(self):
        self.assertEqual(
            os.path.join("image_db", "essai.zip"),
            DatabaseManager.backup_archive(
                "essai.zip",
                exists=lambda p: p == os.path.join("image_db", "essai.zip"),
            ),
        )

    def test_a_bare_name_is_found_too(self):
        """`--restore_image` est documentée « nom sans .zip »."""
        self.assertEqual(
            os.path.join("image_db", "essai.zip"),
            DatabaseManager.backup_archive(
                "essai",
                exists=lambda p: p == os.path.join("image_db", "essai.zip"),
            ),
        )

    def test_the_exact_name_wins_over_the_suffixed_one(self):
        """Un fichier nommé « essai » ET un fichier « essai.zip » : c'est
        celui qu'on a demandé qui compte."""
        self.assertEqual(
            os.path.join("image_db", "essai"),
            DatabaseManager.backup_archive("essai", exists=lambda _p: True),
        )

    def test_not_found_is_an_empty_string(self):
        self.assertEqual(
            "", DatabaseManager.backup_archive("essai", exists=lambda _p: 0)
        )

    def test_it_looks_under_the_repository_image_directory(self):
        vus = []
        DatabaseManager.backup_archive(
            "essai", exists=lambda p: vus.append(p) or False
        )
        for chemin in vus:
            self.assertTrue(chemin.startswith("image_db"), chemin)


class TestLeConstatSurvit(Banc):
    def test_a_sound_backup_is_recorded(self):
        with self.verificateur(SAINE), contextlib.redirect_stdout(
            io.StringIO()
        ):
            DatabaseManager.verify_and_witness("image_db/essai.zip")
        self.assertEqual(1, len(self.poses))
        self.assertEqual(V.SOUND, self.poses[0].verdict)

    def test_a_broken_backup_is_recorded_too(self):
        """Le constat qui compte le plus est celui qui dit non : ne garder
        que les bons ferait d'un silence une bonne nouvelle."""
        with self.verificateur(CASSEE), contextlib.redirect_stdout(
            io.StringIO()
        ):
            DatabaseManager.verify_and_witness("image_db/essai.zip")
        self.assertEqual([V.NO_DUMP], [c.verdict for c in self.poses])

    def test_it_records_the_file_that_was_read(self):
        with self.verificateur(SAINE), contextlib.redirect_stdout(
            io.StringIO()
        ):
            DatabaseManager.verify_and_witness("image_db/autre.zip")
        self.assertEqual("image_db/autre.zip", self.poses[0].path)

    def test_an_unfound_archive_records_nothing(self):
        """Introuvable n'est pas absente : poser un constat « absente »
        serait le mensonge que le témoin existe pour retirer."""
        with contextlib.redirect_stdout(io.StringIO()) as ecran:
            constat = DatabaseManager.verify_and_witness("", "essai.zip")
        self.assertIsNone(constat)
        self.assertEqual([], self.poses)
        self.assertIn("not found where expected", ecran.getvalue())

    def test_a_witness_that_cannot_be_written_does_not_lose_the_backup(self):
        """Le constat est un PLUS : il ne doit pas emporter une
        sauvegarde qui, elle, est faite."""

        def explose(_constat):
            raise OSError("disque plein")

        with self.verificateur(SAINE), patch.object(
            __import__(
                "script.todo.database_manager", fromlist=["backup_witness"]
            ).backup_witness,
            "record",
            explose,
        ), contextlib.redirect_stdout(io.StringIO()) as ecran:
            constat = DatabaseManager.verify_and_witness("image_db/e.zip")
        self.assertEqual(V.SOUND, constat.verdict)
        self.assertIn("disque plein", ecran.getvalue())


class TestLaSauvegardeLocale(Banc):
    """Elle ne regardait ni le code de retour, ni ce qu'elle avait écrit."""

    def _sauvegarde(self, status=0, trouve=True):
        gestionnaire = DatabaseManager(Execute(status), lambda *a, **k: None)
        gestionnaire.select_database = lambda: "base_essai"
        with self.verificateur(SAINE), patch.object(
            DatabaseManager,
            "backup_archive",
            classmethod(
                lambda _cls, nom, exists=None: (
                    "image_db/essai.zip" if trouve else ""
                )
            ),
        ), patch("builtins.input", lambda *_a: "essai.zip"):
            with contextlib.redirect_stdout(io.StringIO()) as ecran:
                gestionnaire.create_backup_from_database()
        return ecran.getvalue()

    def test_a_successful_backup_is_read_back_and_recorded(self):
        self._sauvegarde()
        self.assertEqual(["image_db/essai.zip"], self.vus)
        self.assertEqual(1, len(self.poses))

    def test_a_failed_backup_is_said(self):
        """Un échec rendait exactement le même écran qu'un succès."""
        ecran = self._sauvegarde(status=1)
        self.assertIn("backup command failed", ecran)

    def test_a_failed_backup_verifies_nothing(self):
        """Relire une archive qui n'a pas été écrite dirait « absente »
        pour la mauvaise raison."""
        self._sauvegarde(status=1)
        self.assertEqual([], self.vus)
        self.assertEqual([], self.poses)

    def test_an_unfound_archive_after_success_is_said_not_recorded(self):
        ecran = self._sauvegarde(trouve=False)
        self.assertIn("not found where expected", ecran)
        self.assertEqual([], self.poses)


class TestLeCablage(unittest.TestCase):
    """L'épreuve qui manquait : le module voisin en a une, pas lui.

    Vingt épreuves vertes sur un module que personne n'appelle restent
    vertes le jour où le dernier appelant disparaît.
    """

    @staticmethod
    def source(chemin):
        with open(os.path.join(RACINE, chemin), encoding="utf-8") as f:
            return f.read()

    def test_the_repository_imports_the_witness_somewhere(self):
        import subprocess

        sortie = subprocess.run(
            ["grep", "-rl", "backup_witness", "script/"],
            cwd=RACINE,
            capture_output=True,
            text=True,
        ).stdout.split()
        appelants = [f for f in sortie if not f.endswith("backup_witness.py")]
        self.assertTrue(appelants, "aucun appelant du témoin dans script/")

    def test_both_backup_paths_go_through_the_same_seam(self):
        """Deux relectures écrites séparément divergent au premier
        correctif — c'est déjà ce qui les distinguait."""
        source = self.source("script/todo/database_manager.py")
        # Les APPELS, et non la définition qui s'y ajouterait.
        self.assertEqual(2, source.count("self.verify_and_witness("))

    def test_the_local_backup_listens_to_the_return_code(self):
        source = self.source("script/todo/database_manager.py")
        debut = source.index("def create_backup_from_database")
        fenetre = source[debut : debut + 2200]
        self.assertIn("if status:", fenetre)


if __name__ == "__main__":
    unittest.main()
