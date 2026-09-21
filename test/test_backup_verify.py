#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une sauvegarde tient-elle ? Un contrôle par mensonge possible.

LE MENSONGE QUI A MOTIVÉ CE MODULE : le téléchargement d'une sauvegarde
distante enregistre la réponse du serveur telle quelle, sans exiger qu'elle
soit un succès. Un mot de passe maître refusé produit une page d'erreur
écrite sous le nom du zip — non vide, horodatée, annoncée comme réussie.
D'où une épreuve qui fabrique exactement ce fichier.

Rien ici ne touche à PostgreSQL ni à Odoo : les archives sont fabriquées
dans un répertoire temporaire, et aucune épreuve n'est sautée.
"""

import os
import sys
import tempfile
import unittest
import zipfile

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.database import backup_verify as V  # noqa: E402


class BancDeSauvegardes(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)

    def chemin(self, nom):
        return os.path.join(self.dossier.name, nom)

    def zip_de(self, nom, membres):
        chemin = self.chemin(nom)
        with zipfile.ZipFile(chemin, "w") as archive:
            for membre, contenu in membres.items():
                archive.writestr(membre, contenu)
        return chemin

    def brut(self, nom, contenu):
        chemin = self.chemin(nom)
        with open(chemin, "wb") as fichier:
            fichier.write(contenu)
        return chemin


class TestCeQueChaqueControleAttrape(BancDeSauvegardes):
    def test_a_sound_backup_passes_every_check(self):
        chemin = self.zip_de(
            "bon.zip", {"dump.sql": "CREATE TABLE x;", "manifest.json": "{}"}
        )
        vu = V.verify(chemin)
        self.assertEqual(V.SOUND, vu.verdict)
        self.assertTrue(V.is_sound(chemin))
        self.assertEqual(
            ("present", "non-empty", "zip", "dump", "intact"), vu.checks
        )

    def test_a_file_that_is_not_there(self):
        self.assertEqual(V.ABSENT, V.verify(self.chemin("rien.zip")).verdict)

    def test_a_directory_bearing_the_name_counts_as_absent(self):
        """Ce qu'on cherchait à ouvrir n'est pas là."""
        chemin = self.chemin("un-dossier.zip")
        os.mkdir(chemin)
        self.assertEqual(V.ABSENT, V.verify(chemin).verdict)

    def test_an_empty_file(self):
        vu = V.verify(self.brut("vide.zip", b""))
        self.assertEqual(V.EMPTY, vu.verdict)
        self.assertEqual(("present",), vu.checks)

    def test_an_error_page_saved_under_the_zip_name(self):
        """LE mensonge : non vide, horodatée, et sans index d'archive."""
        chemin = self.brut(
            "refus.zip", b"<!DOCTYPE html><h1>Access denied</h1>"
        )
        vu = V.verify(chemin)
        self.assertEqual(V.NOT_A_ZIP, vu.verdict)
        self.assertGreater(vu.size, 0)
        self.assertIn("non-empty", vu.checks)
        self.assertNotIn("zip", vu.checks)

    def test_an_archive_without_the_dump(self):
        """C'est la SEULE pièce indispensable : elle porte les données."""
        vu = V.verify(self.zip_de("sans.zip", {"manifest.json": "{}"}))
        self.assertEqual(V.NO_DUMP, vu.verdict)

    def test_a_missing_manifest_is_not_an_error(self):
        """Une sauvegarde produite ailleurs n'en porte aucun, et la refuser
        reviendrait à refuser celles qu'on a le plus besoin de vérifier."""
        chemin = self.zip_de("sans-manifeste.zip", {"dump.sql": "x"})
        self.assertEqual(V.SOUND, V.verify(chemin).verdict)

    def test_a_dump_stored_under_a_folder_is_found(self):
        """Selon qui fabrique la sauvegarde, elle est à plat ou rangée."""
        chemin = self.zip_de("rangee.zip", {"sauvegarde/dump.sql": "x"})
        self.assertEqual(V.SOUND, V.verify(chemin).verdict)

    def test_a_member_whose_content_does_not_match_its_checksum(self):
        """Le seul contrôle qui couvre le filestore, et le seul qui coûte
        une décompression."""
        chemin = self.zip_de(
            "abimee.zip", {"dump.sql": "x" * 400, "filestore/a": "y" * 400}
        )
        with open(chemin, "r+b") as fichier:
            fichier.seek(60)
            fichier.write(b"\x00\x01\x02\x03")
        vu = V.verify(chemin)
        self.assertIn(vu.verdict, (V.CORRUPT, V.NOT_A_ZIP), vu)
        self.assertNotEqual(V.SOUND, vu.verdict)


class TestCeQuIlDitJusquOuIlEstAlle(BancDeSauvegardes):
    """« Vérifiée » est le mot le plus facile à croire : le verdict dit
    jusqu'où on a regardé, pas seulement ce qu'on en pense."""

    def test_each_refusal_stops_at_the_check_it_failed(self):
        cas = (
            (V.ABSENT, ()),
            (V.EMPTY, ("present",)),
            (V.NOT_A_ZIP, ("present", "non-empty")),
            (V.NO_DUMP, ("present", "non-empty", "zip")),
        )
        chemins = (
            self.chemin("rien.zip"),
            self.brut("vide.zip", b""),
            self.brut("html.zip", b"<html>"),
            self.zip_de("sans.zip", {"manifest.json": "{}"}),
        )
        for (verdict, passes), chemin in zip(cas, chemins):
            with self.subTest(verdict=verdict):
                vu = V.verify(chemin)
                self.assertEqual(verdict, vu.verdict)
                self.assertEqual(passes, vu.checks)

    def test_a_shallow_pass_says_it_did_not_decompress(self):
        """Une décompression intégrale est linéaire : un écran qui parcourt
        un répertoire ne peut pas la payer par fichier."""
        chemin = self.zip_de("bon.zip", {"dump.sql": "x"})
        vu = V.verify(chemin, deep=False)
        self.assertEqual(V.SOUND, vu.verdict)
        self.assertNotIn("intact", vu.checks)
        self.assertIn("intact", V.verify(chemin, deep=True).checks)

    def test_the_vocabulary_is_closed_and_pinned(self):
        self.assertEqual(
            ("absent", "empty", "not-a-zip", "no-dump", "corrupt", "sound"),
            V.VERDICTS,
        )

    def test_every_verdict_it_can_reach_is_in_the_vocabulary(self):
        for chemin in (
            self.chemin("rien.zip"),
            self.brut("vide.zip", b""),
            self.brut("html.zip", b"<html>"),
            self.zip_de("sans.zip", {"a": "b"}),
            self.zip_de("bon.zip", {"dump.sql": "x"}),
        ):
            with self.subTest(chemin=os.path.basename(chemin)):
                self.assertIn(V.verify(chemin).verdict, V.VERDICTS)

    def test_only_a_complete_pass_opens_the_door(self):
        self.assertFalse(V.is_sound(self.brut("html.zip", b"<html>")))
        self.assertTrue(V.is_sound(self.zip_de("bon.zip", {"dump.sql": "x"})))


class TestLAppelantRegardeCeQuIlVientDEcrire(unittest.TestCase):
    """Le contrôle d'après téléchargement relisait le chemin PAR DÉFAUT
    alors que l'opérateur peut en choisir un autre : il portait donc sur une
    sauvegarde d'avant — ou sur rien — et annonçait « validée »."""

    @staticmethod
    def _bloc():
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "database_manager.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.FunctionDef) and "backup" in noeud.name:
                for interne in ast.walk(noeud):
                    if (
                        isinstance(interne, ast.Call)
                        and isinstance(interne.func, ast.Attribute)
                        and interne.func.attr == "verify"
                    ):
                        return noeud, interne
        return None, None

    def test_the_check_goes_through_the_verifier(self):
        """Ouvrir un membre ne dit pas qu'il se décompresse, et le manifeste
        manque légitimement aux sauvegardes produites ailleurs."""
        fonction, appel = self._bloc()
        self.assertIsNotNone(appel, "le vérificateur n'est pas appelé")
        self.assertEqual("backup_verify", appel.func.value.id)

    def test_it_verifies_the_path_that_was_written(self):
        import ast

        _fonction, appel = self._bloc()
        self.assertEqual(1, len(appel.args))
        self.assertIsInstance(appel.args[0], ast.Name)
        self.assertEqual("output_path", appel.args[0].id)

    def test_the_default_path_is_no_longer_read_after_writing(self):
        """C'est le fichier d'AVANT qui se faisait valider. Le défaut reste
        employé pour PROPOSER un chemin ; ce qui devait disparaître est son
        emploi APRÈS l'écriture.

        Comparé par NUMÉRO DE LIGNE : le parcours d'un arbre ne suit pas
        l'ordre du source, et une comparaison de rangs n'y voudrait rien
        dire."""
        import ast

        fonction, appel = self._bloc()
        defauts = [
            n.lineno
            for n in ast.walk(fonction)
            if isinstance(n, ast.Name) and n.id == "default_output_path"
        ]
        self.assertTrue(defauts, "le défaut a disparu : épreuve à revoir")
        self.assertLess(max(defauts), appel.lineno)


class TestElleNeFaitRienDAutre(unittest.TestCase):
    def test_it_neither_prints_nor_prompts_nor_restores(self):
        import ast

        chemin = os.path.join(RACINE, "script", "database", "backup_verify.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        appels = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertTrue(appels, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "exec", "eval"):
            self.assertNotIn(interdit, appels)

    def test_it_never_writes_and_never_extracts(self):
        """Vérifier n'est pas restaurer, et un contrôle qui écrit sur le
        disque de l'opérateur n'est plus un contrôle."""
        chemin = os.path.join(RACINE, "script", "database", "backup_verify.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        for interdit in (
            "extractall",
            "extract(",
            'open(path, "w"',
            "remove(",
        ):
            self.assertNotIn(interdit, source)


if __name__ == "__main__":
    unittest.main()
