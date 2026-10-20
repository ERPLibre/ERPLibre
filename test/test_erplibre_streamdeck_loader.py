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


SHAPED = (
    "from erplibre_streamdeck.plugin import *\n"
    "PLUGIN = Plugin(api=PLUGIN_API, {kw})\n"
)
# Each entry: a Plugin(...) argument list the loader must refuse.
BAD_SHAPES = {
    "button_list": "home_button=[HomeButton(1, print, print)]",
    "button_order": "home_button=HomeButton('1', print, print)",
    "pages_not_list": "pages=Page('p', None, print, print)",
    "page_id": "pages=[Page(5, None, print, print)]",
    "page_render": "pages=[Page('q', None, 5, print)]",
    "page_period": "pages=[Page('r', None, print, print, print, 'x')]",
    "fixture_class": "fixtures=[object()]",
    "fixture_place": "fixtures=[Fixture(1, None, print, print)]",
    "tile_order": "tiles=[TileProvider(1.5, print, print, print)]",
    "tiles_not_list": "tiles=TileProvider(1, print, print, print)",
    "home_tick": "home_tick=5",
    "home_period": "home_period='2'",
    "shutdown": "shutdown='stop'",
    "polls_not_list": "polls=Poll(1, print, print, print)",
    "poll_class": "polls=[object()]",
    "poll_period": "polls=[Poll('1', print, print, print)]",
    "poll_bool": "polls=[Poll(True, print, print, print)]",
    "poll_read": "polls=[Poll(1, print, 5, print)]",
}


class ShapeTest(LoaderCase):
    def test_malformed_plugins_are_refused_the_others_load(self):
        for pid, kw in BAD_SHAPES.items():
            self.put(self.user, f"{pid}.py", SHAPED.format(kw=kw))
        self.put(self.repo, "fine.py", GOOD.format(page="f"))
        plugins, report = self.load()
        self.assertEqual(["fine"], [p.id for p in plugins])
        st = self.status(report)
        for pid in BAD_SHAPES:
            self.assertEqual("refused", st[pid][0], pid)
            self.assertTrue(st[pid][1], pid)
        self.assertIn("home_button", st["button_list"][1])
        for pid in ("polls_not_list", "poll_class", "poll_period"):
            self.assertIn("polls", st[pid][1], pid)

    def test_well_formed_parts_are_accepted(self):
        self.put(self.user, "full.py", SHAPED.format(kw=(
            "pages=[Page('p', None, print, print, print, 1)], "
            "home_button=HomeButton(1, print, print), "
            "fixtures=[Fixture(2, print, print, print)], "
            "tiles=[TileProvider(3, print, print, print)], "
            "home_tick=print, home_period=2.0, setup=print, "
            "shutdown=print, polls=[Poll(1.5, print, print, print)]"
        )))
        plugins, report = self.load()
        self.assertEqual(["full"], [p.id for p in plugins], report.lines())

    def test_repository_plugins_pass_the_shape_check(self):
        plugins, report = loader.load(user_dir=self.user)
        self.assertEqual(
            sorted(S.REPO_PLUGINS),
            [p.id for p in plugins],
            report.lines(),
        )


class ImportExitTest(LoaderCase):
    def test_sys_exit_at_import_is_refused(self):
        self.put(self.user, "quits.py", "import sys\nsys.exit(3)\n")
        self.put(self.repo, "fine.py", GOOD.format(page="f"))
        plugins, report = self.load()
        self.assertEqual(["fine"], [p.id for p in plugins])
        status, detail = self.status(report)["quits"]
        self.assertEqual("refused", status)
        self.assertIn("SystemExit", detail)

    def test_a_sigterm_at_import_propagates(self):
        self.put(
            self.user, "slow.py",
            "import deck_lock\nraise deck_lock.SigtermExit(143)\n",
        )
        with self.assertRaises(SystemExit) as caught:
            self.load()
        self.assertEqual(143, caught.exception.code)

    def test_keyboard_interrupt_at_import_propagates(self):
        self.put(self.user, "ctrl_c.py", "raise KeyboardInterrupt\n")
        with self.assertRaises(KeyboardInterrupt):
            self.load()


@unittest.skipIf(os.geteuid() == 0, "root lists any directory")
class UnreadableDirTest(LoaderCase):
    def test_unreadable_user_dir_is_reported_and_empty(self):
        self.put(self.user, "hidden.py", GOOD.format(page="h"))
        self.put(self.repo, "fine.py", GOOD.format(page="f"))
        self.user.chmod(0)
        self.addCleanup(self.user.chmod, 0o755)
        plugins, report = self.load()
        self.assertEqual(["fine"], [p.id for p in plugins])
        status, detail = self.status(report)[str(self.user)]
        self.assertEqual("unreadable", status)
        self.assertIn("PermissionError", detail)


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
