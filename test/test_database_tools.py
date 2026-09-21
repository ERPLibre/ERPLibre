#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import csv
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from unittest.mock import patch

from script.database.migrate.process_backup_file import process_zip


class TestProcessZip(unittest.TestCase):
    """Test ZIP file processing to remove lines containing a keyword."""

    def _create_zip(self, path, filename, content):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(filename, content)

    def test_removes_matching_lines(self):
        tmpdir = tempfile.mkdtemp()
        input_zip = os.path.join(tmpdir, "input.zip")
        output_zip = os.path.join(tmpdir, "output.zip")
        self._create_zip(
            input_zip,
            "dump.sql",
            "keep this line\ndelete secret line\nkeep also\n",
        )
        process_zip(input_zip, output_zip, "secret", "dump.sql")
        with zipfile.ZipFile(output_zip) as zf:
            content = zf.read("dump.sql").decode()
        self.assertIn("keep this line", content)
        self.assertIn("keep also", content)
        self.assertNotIn("secret", content)

    def test_preserves_all_when_no_match(self):
        tmpdir = tempfile.mkdtemp()
        input_zip = os.path.join(tmpdir, "input.zip")
        output_zip = os.path.join(tmpdir, "output.zip")
        original = "line1\nline2\nline3\n"
        self._create_zip(input_zip, "data.sql", original)
        process_zip(input_zip, output_zip, "nomatch", "data.sql")
        with zipfile.ZipFile(output_zip) as zf:
            content = zf.read("data.sql").decode()
        self.assertIn("line1", content)
        self.assertIn("line2", content)
        self.assertIn("line3", content)

    def test_removes_all_matching(self):
        tmpdir = tempfile.mkdtemp()
        input_zip = os.path.join(tmpdir, "input.zip")
        output_zip = os.path.join(tmpdir, "output.zip")
        self._create_zip(
            input_zip,
            "dump.sql",
            "bad line\nbad again\nbad too\n",
        )
        process_zip(input_zip, output_zip, "bad", "dump.sql")
        with zipfile.ZipFile(output_zip) as zf:
            content = zf.read("dump.sql").decode()
        self.assertEqual(content.strip(), "")

    def test_other_files_untouched(self):
        tmpdir = tempfile.mkdtemp()
        input_zip = os.path.join(tmpdir, "input.zip")
        output_zip = os.path.join(tmpdir, "output.zip")
        with zipfile.ZipFile(input_zip, "w") as zf:
            zf.writestr("target.sql", "keep\nremove secret\n")
            zf.writestr("other.txt", "secret stays here\n")
        process_zip(input_zip, output_zip, "secret", "target.sql")
        with zipfile.ZipFile(output_zip) as zf:
            target = zf.read("target.sql").decode()
            other = zf.read("other.txt").decode()
        self.assertNotIn("secret", target)
        self.assertIn("secret", other)


class TestCeQuUneSortieEnCatastropheLaisse(unittest.TestCase):
    """`run_cmd` sort par `sys.exit` dès qu'une commande échoue.

    L'étape de nettoyage ne tourne alors jamais, et les bases de travail
    restent sur l'instance SANS UN MOT. Une base orpheline ne se voit pas :
    elle occupe un nom que la prochaine génération réutilise, et la
    création échoue alors sur une collision dont la cause est trois
    exécutions plus tôt.

    ON NOMME, ON N'EFFACE PAS : la génération vient d'échouer, et ces bases
    sont l'état dans lequel elle a échoué.
    """

    @staticmethod
    def module():
        import importlib.util

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        chemin = os.path.join(racine, "script", "database", "image_db.py")
        spec = importlib.util.spec_from_file_location("image_db_banc", chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_every_temporary_database_is_named(self):
        lignes = self.module().nommer_les_bases_restantes(
            ["tmp_a", "tmp_b"], keep_database=False
        )
        texte = "\n".join(lignes)
        self.assertIn("tmp_a", texte)
        self.assertIn("tmp_b", texte)

    def test_it_says_how_to_remove_them(self):
        """Nommer sans dire comment retirer laisse chercher la commande."""
        lignes = self.module().nommer_les_bases_restantes(
            ["tmp_a"], keep_database=False
        )
        self.assertTrue(any("--drop --database tmp_a" in l for l in lignes))

    def test_it_offers_no_removal_when_the_run_asked_to_keep(self):
        """Proposer d'effacer ce qu'on a demandé de garder se lit comme un
        écran qui n'a pas suivi."""
        lignes = self.module().nommer_les_bases_restantes(
            ["tmp_a"], keep_database=True
        )
        self.assertTrue(any("tmp_a" in l for l in lignes))
        self.assertEqual([], [l for l in lignes if "--drop" in l])

    def test_no_temporary_database_says_nothing_at_all(self):
        """Une ligne vide après un échec se lit comme un second défaut."""
        self.assertEqual(
            [], self.module().nommer_les_bases_restantes([], False)
        )

    def test_the_crash_path_goes_through_the_naming(self):
        """Le contrôle porte sur le CHEMIN : sans lui, la fonction peut
        être juste et n'être appelée par personne — c'est l'état d'où l'on
        part."""
        import inspect

        corps = inspect.getsource(self.module().main)
        self.assertIn("except SystemExit", corps)
        self.assertIn("nommer_les_bases_restantes", corps)
        self.assertIn("raise", corps)


class TestLAideNOrdonnePasCeQueLeParserRefuse(unittest.TestCase):
    """L'aide et le parser du même script se contredisaient.

    La description était recopiée du script voisin, qui lit une
    sauvegarde : elle ordonnait « Use --backup_path or --backup_name »,
    et le parser rendait « unrecognized arguments » sur les deux. Le même
    écran donnait l'ordre et le refus.

    Le contrôle porte sur les DEUX scripts : celui qui avait la faute et
    celui d'où elle venait. Une recopie se refait.
    """

    SCRIPTS = (
        "script/database/get_repo_from_module.py",
        "script/database/get_repo_from_backup.py",
    )

    @staticmethod
    def racine():
        return os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def lancer(self, script, *args):
        import subprocess
        import sys

        return subprocess.run(
            [sys.executable, os.path.join(self.racine(), script)] + list(args),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )

    def test_every_flag_the_help_names_is_accepted(self):
        """L'épreuve TAPE le drapeau au lieu de lire la mise en page.

        Comparer le corps de l'aide à la ligne « usage: » se heurte à sa
        forme — « --help » n'y figure pas, il vit sous « options: ». Le
        seul contrôle qui ne dépende d'aucune mise en page est de jouer
        le drapeau et de regarder si l'analyseur le connaît.
        """
        import re

        for script in self.SCRIPTS:
            aide = self.lancer(script, "--help")
            with self.subTest(script=script, etape="aide"):
                self.assertEqual(0, aide.returncode)
            for drapeau in sorted(
                set(re.findall(r"--[a-z0-9_]+", aide.stdout))
            ):
                if drapeau == "--help":
                    continue
                vu = self.lancer(script, drapeau)
                sortie = vu.stdout + vu.stderr
                with self.subTest(script=script, drapeau=drapeau):
                    # LE DRAPEAU LUI-MÊME, et non n'importe quel refus :
                    # le script peut échouer pour une autre raison — un
                    # fichier absent, une valeur attendue — et c'est hors
                    # sujet. Lui donner une valeur au hasard fait d'ailleurs
                    # de « x » un positionnel orphelin sur un drapeau
                    # booléen, et c'est LUI que l'analyseur nomme alors.
                    self.assertNotIn(
                        f"unrecognized arguments: {drapeau}", sortie
                    )

    def test_the_only_useful_flag_is_required_and_says_so(self):
        """Sans lui, le script mourait sur « 'NoneType' object has no
        attribute 'split' » — une trace qui ne dit pas ce qui manque."""
        vu = self.lancer("script/database/get_repo_from_module.py")
        self.assertNotEqual(0, vu.returncode)
        self.assertIn("--module", vu.stdout + vu.stderr)
        self.assertNotIn("Traceback", vu.stdout + vu.stderr)


class TestCompareDatabaseApplicationLogic(unittest.TestCase):
    """Test CSV set comparison logic used by compare_database_application."""

    def _write_csv(self, path, rows, fieldnames):
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_identical_csvs(self):
        tmpdir = tempfile.mkdtemp()
        csv1 = os.path.join(tmpdir, "a.csv")
        csv2 = os.path.join(tmpdir, "b.csv")
        rows = [{"name": "mod1"}, {"name": "mod2"}]
        self._write_csv(csv1, rows, ["name"])
        self._write_csv(csv2, rows, ["name"])
        with open(csv1) as f1, open(csv2) as f2:
            r1 = csv.DictReader(f1)
            r2 = csv.DictReader(f2)
            s1 = {a["name"] for a in r1}
            s2 = {a["name"] for a in r2}
        self.assertEqual(s1, s2)
        self.assertEqual(len(s1.difference(s2)), 0)

    def test_different_csvs(self):
        tmpdir = tempfile.mkdtemp()
        csv1 = os.path.join(tmpdir, "a.csv")
        csv2 = os.path.join(tmpdir, "b.csv")
        self._write_csv(csv1, [{"name": "mod1"}, {"name": "mod2"}], ["name"])
        self._write_csv(csv2, [{"name": "mod2"}, {"name": "mod3"}], ["name"])
        with open(csv1) as f1, open(csv2) as f2:
            r1 = csv.DictReader(f1)
            r2 = csv.DictReader(f2)
            s1 = {a["name"] for a in r1}
            s2 = {a["name"] for a in r2}
        self.assertEqual(s1.intersection(s2), {"mod2"})
        self.assertEqual(s1.difference(s2), {"mod1"})
        self.assertEqual(s2.difference(s1), {"mod3"})

    def test_empty_csvs(self):
        tmpdir = tempfile.mkdtemp()
        csv1 = os.path.join(tmpdir, "a.csv")
        csv2 = os.path.join(tmpdir, "b.csv")
        self._write_csv(csv1, [], ["name"])
        self._write_csv(csv2, [], ["name"])
        with open(csv1) as f1, open(csv2) as f2:
            r1 = csv.DictReader(f1)
            r2 = csv.DictReader(f2)
            s1 = {a["name"] for a in r1}
            s2 = {a["name"] for a in r2}
        self.assertEqual(len(s1.union(s2)), 0)

    def test_one_empty_csv(self):
        tmpdir = tempfile.mkdtemp()
        csv1 = os.path.join(tmpdir, "a.csv")
        csv2 = os.path.join(tmpdir, "b.csv")
        self._write_csv(csv1, [{"name": "mod1"}], ["name"])
        self._write_csv(csv2, [], ["name"])
        with open(csv1) as f1, open(csv2) as f2:
            r1 = csv.DictReader(f1)
            r2 = csv.DictReader(f2)
            s1 = {a["name"] for a in r1}
            s2 = {a["name"] for a in r2}
        self.assertEqual(s1.difference(s2), {"mod1"})
        self.assertEqual(len(s2.difference(s1)), 0)


class UneDestructionNAnnonceQueCeQuElleAFait(unittest.TestCase):
    """« make db_drop_all » composait une commande « parallel », jetait son
    code de retour et imprimait la liste des bases comme détruites.

    Le cas s'atteint dès que « parallel » manque du PATH : le shell rend 127,
    pas une base n'est touchée, et l'opérateur passe à la suite en croyant
    ses bases parties. Une destruction qui annonce un succès qu'elle n'a pas
    obtenu est pire que celle qui échoue.
    """

    def _module(self):
        import importlib.util

        chemin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "script/database/db_drop_all.py",
        )
        spec = importlib.util.spec_from_file_location("db_drop_all", chemin)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _courir(self, code_destruction):
        import contextlib

        mod = self._module()

        def faux_shell(cmd):
            if "--list" in cmd:
                return 0, "test_alpha\ntest_beta"
            return code_destruction, (
                "" if not code_destruction else "parallel: command not found"
            )

        mod.execute_shell = faux_shell
        # LE CONTRÔLE D'EXERCICE EST NEUTRALISÉ ICI, et lui seul : sans base
        # à interroger, il refuse tout, et le script s'arrête AVANT ce que
        # cette classe tient — l'annonce de ce qui a vraiment été détruit.
        # Ce que le contrôle refuse et pourquoi s'éprouve dans ses propres
        # tests, avec une base sous la main.
        mod._verdict = lambda _db, force=False: mod.drill_guard.DRILL

        # LA CONFIG VIENT DE L'ANALYSEUR D'OPTIONS, et non d'une classe qui
        # recopie ses champs. Une option ajoutée à l'outil manquait au banc,
        # et ces épreuves levaient AttributeError avant d'atteindre ce
        # qu'elles tiennent — l'annonce de ce qui a été détruit.
        with mock.patch.object(sys, "argv", ["db_drop_all.py", "--test_only"]):
            config = mod.get_config()
        mod.get_config = lambda: config
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie):
            with contextlib.redirect_stderr(erreur):
                code = mod.main()
        return code, sortie.getvalue(), erreur.getvalue()

    def test_a_failed_drop_is_not_announced_as_done(self):
        code, sortie, erreur = self._courir(127)
        self.assertEqual(127, code)
        self.assertNotIn("Database deleted", sortie)
        self.assertNotIn("test_alpha", sortie)

    def test_the_cause_reaches_the_operator(self):
        """Le code de retour seul laisserait chercher : la sortie du shell
        nomme ce qui manque."""
        _code, _sortie, erreur = self._courir(127)
        self.assertIn("NOT deleted", erreur)
        self.assertIn("parallel", erreur)

    def test_a_real_drop_is_still_announced(self):
        """Le cas ordinaire ne change pas : les bases détruites se disent."""
        code, sortie, _erreur = self._courir(0)
        self.assertEqual(0, code)
        self.assertIn("Database deleted", sortie)
        self.assertIn("test_alpha", sortie)
        self.assertIn("test_beta", sortie)


if __name__ == "__main__":
    unittest.main()
