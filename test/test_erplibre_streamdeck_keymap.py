#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""keymap.json, the home layout per deck model: its loader, the
validation of one model's layout, and the --catalog output."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

app = S.load_package()
from erplibre_streamdeck import keymap  # noqa: E402
from erplibre_streamdeck import paths  # noqa: E402
from erplibre_streamdeck.plugin import Geometry  # noqa: E402
from erplibre_streamdeck.ui import icons  # noqa: E402

GEO = Geometry(4, 2, 8)
PLUGINS = {"timers", "tiling", "sound"}
ICONS = set(icons.ICONS)


def layout_file(keys, model="0084", **top):
    data = {"format": 1, "revision": 7, "layouts": {model: {"keys": keys}}}
    data.update(top)
    return data


class KeymapCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "keymap.json"
        self.journal = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stderr(self.journal))

    def write(self, data):
        text = data if isinstance(data, (str, bytes)) else json.dumps(data)
        mode = "wb" if isinstance(text, bytes) else "w"
        with open(self.path, mode) as f:
            f.write(text)

    def layout(self, keys, plugins=PLUGINS, geo=GEO):
        return keymap.layout_for(
            layout_file(keys), "0084", geo, plugins, ICONS
        )


class LoadTest(KeymapCase):
    def test_the_file_is_the_literal_config_dir_s_keymap_json(self):
        self.assertEqual(paths.CONFIG_DIR / "keymap.json", paths.KEYMAP_FILE)
        self.assertEqual("erplibre-home", paths.KEYMAP_FILE.parent.name)

    def test_a_missing_file_is_empty_and_silent(self):
        self.assertEqual({}, keymap.load(self.path))
        self.assertEqual("", self.journal.getvalue())

    def test_a_valid_file_loads(self):
        data = layout_file([{"key": 0, "action": "tiles"}])
        self.write(data)
        self.assertEqual(data, keymap.load(self.path))

    def test_a_bad_file_is_empty_with_one_line(self):
        """Bad JSON, bad UTF-8, a format other than 1, layouts that are
        not an object or name more than 16 models, a file too large, a
        nesting too deep: today's automatic layout, one line each."""
        too_many = {f"{i:04x}": {"keys": []} for i in range(17)}
        for content in (
            "{not json",
            b"\xff\xfe{}",
            "[]",
            json.dumps({"format": 2, "layouts": {}}),
            json.dumps({"format": "1", "layouts": {}}),
            json.dumps({"format": True, "layouts": {}}),
            json.dumps({"layouts": {}}),
            json.dumps({"format": 1, "layouts": []}),
            json.dumps({"format": 1, "layouts": too_many}),
            json.dumps({"format": 1, "pad": "x" * keymap.MAX_BYTES}),
            "[" * 100000 + "]" * 100000,
        ):
            self.journal.seek(0)
            self.journal.truncate()
            self.write(content)
            self.assertEqual({}, keymap.load(self.path), content[:40])
            lines = self.journal.getvalue().splitlines()
            self.assertEqual(1, len(lines), (content[:40], lines))
            self.assertIn("keymap", lines[0])

    def test_a_valid_file_over_max_bytes_is_refused_for_its_size(self):
        """A file that would load but for its size: refused, its line
        names the size; one byte less loads."""
        data = layout_file([{"key": 0, "action": "tiles"}], pad="")
        room = keymap.MAX_BYTES - len(json.dumps(data))
        for extra, loads in ((room, True), (room + 1, False)):
            self.journal.seek(0)
            self.journal.truncate()
            data["pad"] = "x" * extra
            self.write(data)
            self.assertEqual(keymap.MAX_BYTES + (not loads),
                             self.path.stat().st_size)
            self.assertEqual(data if loads else {}, keymap.load(self.path))
            if not loads:
                self.assertIn("larger than", self.journal.getvalue())

    def test_sixteen_models_load(self):
        data = {
            "format": 1,
            "layouts": {f"{i:04x}": {"keys": []} for i in range(16)},
        }
        self.write(data)
        self.assertEqual(data, keymap.load(self.path))

    def test_a_directory_in_place_of_the_file_is_empty(self):
        self.path.mkdir()
        self.assertEqual({}, keymap.load(self.path))
        self.assertEqual(1, len(self.journal.getvalue().splitlines()))

    def test_the_default_path_is_keymap_file(self):
        with mock.patch.object(keymap.paths, "KEYMAP_FILE", self.path):
            self.write(layout_file([]))
            self.assertEqual(layout_file([]), keymap.load())


class LayoutForTest(KeymapCase):
    def test_a_model_absent_or_no_file_keeps_the_automatic_layout(self):
        for data in ({}, layout_file([], model="0060")):
            self.assertEqual(
                (None, []),
                keymap.layout_for(data, "0084", GEO, PLUGINS, ICONS),
            )

    def test_a_valid_layout(self):
        entries, problems = self.layout(
            [
                {
                    "key": 0,
                    "action": "plugin:timers",
                    "icon": "timer",
                    "label": "Minuteries",
                },
                {"key": 1, "action": "tiles"},
                {"key": 2, "action": "empty"},
                {"key": 3, "action": "plugin:tiling"},
                {"key": 4, "action": "plugin:sound", "label": ""},
            ]
        )
        self.assertEqual([], problems)
        self.assertEqual(
            [
                keymap.Entry(0, "plugin:timers", "timer", "Minuteries"),
                keymap.Entry(1, "tiles"),
                keymap.Entry(2, "empty"),
                keymap.Entry(3, "plugin:tiling"),
                keymap.Entry(4, "plugin:sound", None, ""),
            ],
            entries,
        )

    def test_hostile_entries_are_skipped_one_problem_each(self):
        """Each hostile entry has its own key and its own loaded plugin,
        so the one field it breaks is the only reason to skip it."""
        bad = [
            "not an object",
            {"action": "tiles"},
            {"key": 32, "action": "tiles"},
            {"key": -1, "action": "tiles"},
            {"key": True, "action": "tiles"},
            {"key": 1.0, "action": "tiles"},
            {"key": "1", "action": "tiles"},
            {"key": 1},
            {"key": 2, "action": "run:rm -rf"},
            {"key": 3, "action": "plugin:Bad-Id"},
            {"key": 4, "action": "plugin:" + "a" * 65},
            {"key": 5, "action": "plugin:p5", "icon": "no_such"},
            {"key": 6, "action": "plugin:p6", "icon": None},
            {"key": 7, "action": "plugin:p7", "icon": 5},
            {"key": 8, "action": "plugin:p8", "label": "a\nb"},
            {"key": 9, "action": "plugin:p9", "label": "\x1b[31m"},
            {"key": 10, "action": "plugin:p10", "label": "\x85"},
            {"key": 11, "action": "plugin:p11", "label": "x" * 17},
            {"key": 12, "action": "plugin:p12", "label": 5},
            {"key": 13, "action": "empty", "icon": "no_such"},
            {"key": 14, "action": "tiles", "label": "\x07"},
        ]
        good = {"key": 0, "action": "plugin:timers"}
        plugins = PLUGINS | {f"p{i}" for i in range(32)} | {"a" * 65}
        entries, problems = self.layout(
            [good] + bad, plugins=plugins, geo=Geometry(8, 4, 32)
        )
        self.assertEqual([keymap.Entry(0, "plugin:timers")], entries)
        skipped = [p for p in problems if "skipped" in p]
        self.assertEqual(len(bad), len(skipped), problems)

    def test_the_icon_and_label_limits_admit_what_they_name(self):
        """The other side of the hostile entries: a catalog icon, a
        label of LABEL_MAX code points, and an empty label pass."""
        entries, problems = self.layout(
            [
                {"key": 0, "action": "plugin:timers", "icon": "timer"},
                {"key": 1, "action": "plugin:tiling", "label": "x" * 16},
                {"key": 2, "action": "plugin:sound", "label": ""},
            ]
        )
        self.assertEqual([], [p for p in problems if "skipped" in p])
        self.assertEqual(
            [
                keymap.Entry(0, "plugin:timers", "timer"),
                keymap.Entry(1, "plugin:tiling", None, "x" * 16),
                keymap.Entry(2, "plugin:sound", None, ""),
            ],
            entries,
        )

    def test_a_duplicate_key_or_plugin_is_skipped(self):
        entries, problems = self.layout(
            [
                {"key": 0, "action": "plugin:timers"},
                {"key": 0, "action": "tiles"},
                {"key": 1, "action": "plugin:timers"},
            ]
        )
        self.assertEqual([keymap.Entry(0, "plugin:timers")], entries)
        self.assertEqual(
            2, len([p for p in problems if "skipped" in p]), problems
        )

    def test_a_missing_or_off_plugin_leaves_its_key_empty(self):
        entries, problems = self.layout(
            [{"key": 2, "action": "plugin:gone", "icon": "timer"}],
        )
        self.assertEqual([keymap.Entry(2, "empty")], entries)
        self.assertTrue(
            any("gone" in p and "empty" in p for p in problems), problems
        )

    def test_a_label_of_sixteen_code_points_is_kept(self):
        label = "é" * 16
        entries, _ = self.layout(
            [{"key": 0, "action": "plugin:timers", "label": label}]
        )
        self.assertEqual(label, entries[0].label)

    def test_more_entries_than_keys_keeps_the_automatic_layout(self):
        keys = [{"key": i % 8, "action": "tiles"} for i in range(10000)]
        entries, problems = self.layout(keys)
        self.assertIsNone(entries)
        self.assertEqual(1, len(problems))

    def test_a_layout_without_a_keys_list_keeps_the_automatic_layout(self):
        for layout in ([], {"keys": {}}, {"keys": None}, {}):
            data = {"format": 1, "layouts": {"0084": layout}}
            entries, problems = keymap.layout_for(
                data, "0084", GEO, PLUGINS, ICONS
            )
            self.assertIsNone(entries, layout)
            self.assertEqual(1, len(problems), layout)

    def test_unnamed_plugins_are_reported(self):
        _, problems = self.layout([{"key": 0, "action": "plugin:timers"}])
        self.assertEqual(
            ["sound", "tiling"],
            sorted(
                pid
                for pid in PLUGINS
                if any(f"plugin {pid} has no key" in p for p in problems)
            ),
        )

    def test_unknown_fields_are_ignored(self):
        entries, problems = self.layout(
            [{"key": 0, "action": "tiles", "colour": "red"}]
        )
        self.assertEqual([keymap.Entry(0, "tiles")], entries)
        self.assertEqual([], [p for p in problems if "skipped" in p])

    def test_capped_keeps_the_journal_short(self):
        problems = [f"p{i}" for i in range(50)]
        lines = keymap.capped(problems)
        self.assertEqual(keymap.PROBLEM_LINES + 1, len(lines))
        self.assertEqual(problems[: keymap.PROBLEM_LINES], lines[:-1])
        self.assertIn(str(50 - keymap.PROBLEM_LINES), lines[-1])
        self.assertEqual(["a"], keymap.capped(["a"]))


class CatalogTest(unittest.TestCase):
    def setUp(self):
        S.wipe()
        S.TRANSPORTS.clear()

    def load_main(self):
        spec = importlib.util.spec_from_file_location(
            "erplibre_streamdeck_main_under_test", S.PACKAGE / "__main__.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_catalog(self):
        """catalog()'s exit code and stdout, with the deck lock and the
        SIGTERM handler replaced by mocks."""
        main = self.load_main()
        out = io.StringIO()
        with (
            mock.patch.object(
                main.deck_lock, "acquire_or_exit"
            ) as acquire_or_exit,
            mock.patch.object(main.deck_lock, "acquire") as acquire,
            mock.patch.object(
                main.deck_lock, "exit_on_sigterm"
            ) as exit_on_sigterm,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = main.catalog()
        self.untouched = (
            acquire_or_exit.call_count,
            acquire.call_count,
            exit_on_sigterm.call_count,
        )
        return code, out.getvalue()

    def test_catalog_needs_no_deck_and_no_lock(self):
        code, out = self.run_catalog()
        self.assertEqual(0, code)
        self.assertEqual((0, 0, 0), self.untouched)
        self.assertEqual(["dummy"], S.TRANSPORTS)
        json.loads(out)

    def test_catalog_lists_plugins_with_a_home_button_icons_and_models(self):
        directory = S.CONFIG / "erplibre-home" / "deck-plugins"
        directory.mkdir(parents=True, exist_ok=True)
        for pid, kw in (
            ("mine", "home_button=HomeButton(5, print, print)"),
            ("silent", ""),
        ):
            (directory / f"{pid}.py").write_text(
                "from erplibre_streamdeck.plugin import *\n"
                "print('noise on stdout')\n"
                f"PLUGIN = Plugin(api=PLUGIN_API, {kw})\n",
                encoding="utf-8",
            )
            self.addCleanup(
                sys.modules.pop, f"erplibre_streamdeck_user.{pid}", None
            )
        (S.CONFIG / "erplibre-home" / "streamdeck.conf").write_text(
            "DECK_PLUGINS_OFF=timers\n", encoding="utf-8"
        )
        _, out = self.run_catalog()
        data = json.loads(out)
        self.assertEqual(1, data["format"])
        actions = data["actions"]
        self.assertEqual(["tiles", "empty"], actions[-2:])
        self.assertIn("plugin:mine", actions)
        self.assertIn("plugin:tiling", actions)
        # An off plugin is still offered: the deck leaves its key empty.
        self.assertIn("plugin:timers", actions)
        self.assertNotIn("plugin:silent", actions)
        self.assertNotIn("plugin:claude_sessions", actions)
        self.assertEqual(sorted(actions[:-2]), actions[:-2])
        self.assertEqual(sorted(icons.ICONS), data["icons"])
        self.assertEqual(
            {
                "0060": {"cols": 5, "rows": 3, "keys": 15},
                "0063": {"cols": 3, "rows": 2, "keys": 6},
                "006c": {"cols": 8, "rows": 4, "keys": 32},
                "0084": {"cols": 4, "rows": 2, "keys": 8},
            },
            data["models"],
        )

    def test_the_catalog_is_valid_for_its_own_layouts(self):
        """Every action and icon of the catalog passes layout_for."""
        _, out = self.run_catalog()
        data = json.loads(out)
        plugins = {a[7:] for a in data["actions"] if a.startswith("plugin:")}
        keys = [
            {"key": i, "action": a, **({"icon": i_} if i_ else {})}
            for i, (a, i_) in enumerate(
                zip(data["actions"], data["icons"] + [None] * 32)
            )
        ]
        geo = Geometry(8, 4, 32)
        entries, problems = keymap.layout_for(
            layout_file(keys, model="006c"), "006c", geo, plugins, ICONS
        )
        self.assertEqual([], [p for p in problems if "skipped" in p])
        self.assertEqual(len(keys), len(entries))

    def test_help_names_keymap_json_and_catalog(self):
        text = self.load_main().parser().format_help()
        self.assertIn("--catalog", text)
        self.assertIn("erplibre-home/keymap.json", text)

    def test_catalog_and_list_plugins_are_exclusive(self):
        main = self.load_main()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main.parser().parse_args(["--catalog", "--list-plugins"])
        self.assertEqual(2, caught.exception.code)

    def test_catalog_from_the_real_library(self):
        """Through the real interpreter and library, in a scratch home:
        the dummy transport lists the models, no deck is opened. Skipped
        without the Stream Deck venv."""
        python = S.ROOT / ".venv.streamdeck" / "bin" / "python"
        if not python.exists():
            self.skipTest("no .venv.streamdeck")
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(
                os.environ,
                HOME=tmp,
                XDG_CONFIG_HOME=os.path.join(tmp, "config"),
                XDG_STATE_HOME=os.path.join(tmp, "state"),
                XDG_RUNTIME_DIR=tmp,
            )
            done = subprocess.run(
                [str(python), str(S.PACKAGE), "--catalog"],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual([], os.listdir(os.path.join(tmp)))
        self.assertEqual(0, done.returncode, done.stderr)
        data = json.loads(done.stdout)
        self.assertEqual(
            {"cols": 4, "rows": 2, "keys": 8}, data["models"]["0084"]
        )
        self.assertEqual(
            {"cols": 5, "rows": 3, "keys": 15}, data["models"]["0060"]
        )
        self.assertNotIn("0086", data["models"])  # the pedal: no screen
        self.assertIn("plugin:timers", data["actions"])


if __name__ == "__main__":
    unittest.main()
