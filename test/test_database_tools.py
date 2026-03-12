#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
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
