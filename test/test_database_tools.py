#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import csv
import io
import json
import os
import tempfile
import unittest
import zipfile
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


if __name__ == "__main__":
    unittest.main()
