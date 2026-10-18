#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Plugin discovery: both directories, refusals, DECK_PLUGINS_OFF."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import loader  # noqa: E402

GOOD = (
    "from erplibre_streamdeck.plugin import Page, Plugin, PLUGIN_API\n"
    "PLUGIN = Plugin(api=PLUGIN_API, pages=[Page({page!r}, None, "
    "print, print)])\n"
)


class LoaderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name, "repo")
        self.user = Path(tmp.name, "user")
        self.repo.mkdir()
        self.user.mkdir()

    def put(self, where, name, text):
        (where / name).write_text(text, encoding="utf-8")

    def load(self, off=()):
        return loader.load(off=off, repo_dir=self.repo, user_dir=self.user)

    def status(self, report):
        return {e[0]: (e[1], e[2]) for e in report.entries}


class LoaderTest(LoaderCase):
    def test_both_directories_sorted(self):
        self.put(self.repo, "beta.py", GOOD.format(page="b"))
        self.put(self.user, "alpha.py", GOOD.format(page="a"))
        plugins, _ = self.load()
        self.assertEqual(["alpha", "beta"], [p.id for p in plugins])
        self.assertEqual(["user", "repo"], [p.origin for p in plugins])

    def test_skips_underscore_and_refuses_bad_stem(self):
        self.put(self.repo, "_helper.py", "raise SystemExit\n")
        self.put(self.repo, "Bad-Name.py", GOOD.format(page="x"))
        plugins, report = self.load()
        self.assertEqual([], plugins)
        self.assertEqual("refused", self.status(report)["Bad-Name"][0])
        self.assertNotIn("_helper", self.status(report))

    def test_broken_user_plugin_is_refused(self):
        self.put(self.user, "broken.py", "def (:\n")
        self.put(self.repo, "fine.py", GOOD.format(page="f"))
        plugins, report = self.load()
        self.assertEqual(["fine"], [p.id for p in plugins])
        status, detail = self.status(report)["broken"]
        self.assertEqual("refused", status)
        self.assertIn("SyntaxError", detail)

    def test_missing_plugin_and_wrong_api(self):
        self.put(self.repo, "none.py", "X = 1\n")
        self.put(
            self.repo,
            "old.py",
            "from erplibre_streamdeck.plugin import Plugin\n"
            "PLUGIN = Plugin(api=0)\n",
        )
        _, report = self.load()
        st = self.status(report)
        self.assertEqual(("refused", "no PLUGIN"), st["none"])
        self.assertEqual("refused", st["old"][0])
        self.assertIn("api 0", st["old"][1])

    def test_duplicate_page_id(self):
        self.put(self.repo, "a.py", GOOD.format(page="same"))
        self.put(self.repo, "b.py", GOOD.format(page="same"))
        plugins, report = self.load()
        self.assertEqual(["a"], [p.id for p in plugins])
        self.assertIn("same", self.status(report)["b"][1])

    def test_user_replaces_repo_and_off_turns_both_off(self):
        self.put(self.repo, "dup.py", GOOD.format(page="r"))
        self.put(self.user, "dup.py", GOOD.format(page="u"))
        plugins, report = self.load()
        self.assertEqual("user", plugins[0].origin)
        self.assertIn("replaced by user", [e[1] for e in report.entries])
        plugins, report = self.load(off=["dup"])
        self.assertEqual([], plugins)
        self.assertEqual("off", self.status(report)["dup"][0])

    def test_parse_off(self):
        self.assertEqual(
            ["a", "b_c"], loader.parse_off(" a , ,b_c,\n")
        )


class ListPluginsTest(unittest.TestCase):
    def test_list_plugins_from_another_cwd(self):
        """Run through the real interpreter in a scratch cwd: the
        package's own sys.path setup must find everything. Skipped
        without the Stream Deck venv (Pillow, StreamDeck)."""
        python = S.ROOT / ".venv.streamdeck" / "bin" / "python"
        if not python.exists():
            self.skipTest("no .venv.streamdeck")
        with tempfile.TemporaryDirectory() as cwd:
            done = subprocess.run(
                [str(python), str(S.PACKAGE), "--list-plugins"],
                cwd=cwd, capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(0, done.returncode, done.stderr)
        for path in loader.REPO_DIR.glob("*.py"):
            if not path.name.startswith("_"):
                self.assertIn(f"{path.stem}: active", done.stdout)


if __name__ == "__main__":
    unittest.main()
