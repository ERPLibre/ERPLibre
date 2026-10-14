#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Migration of a workstation from the extension's previous identity.

The extension was ``streamdeck-tiler@technolibre.ca`` before it became
``erplibre-home@technolibre.ca``. These tests hold the decisions of each
step on the inputs a workstation can present: nothing to migrate, the old
state only, the new state only, both, and no session bus. Every step must
be idempotent and the script must never fail the install that follows.
"""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "script" / "gnome-extension" / "erplibre_home"
SCRIPT = EXT / "tools" / "migrate_legacy.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = _load("migrate_legacy", SCRIPT)


def _tmp(case):
    """A temporary directory removed when the test ends."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)

OLD = "streamdeck-tiler@technolibre.ca"
NEW = "erplibre-home@technolibre.ca"


class Recorder:
    """Collects say/warn lines and answers runner calls from a table."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []
        self.said = []
        self.warned = []

    def run(self, cmd, stdin=None):
        self.calls.append((tuple(cmd), stdin))
        return self.answers.get(tuple(cmd), (0, ""))

    def say(self, msg):
        self.said.append(msg)

    def warn(self, msg):
        self.warned.append(msg)


class TestStrv(unittest.TestCase):
    def test_empty_typed_list(self):
        self.assertEqual(mig.parse_strv("@as []\n"), [])

    def test_list(self):
        self.assertEqual(mig.parse_strv(f"['a@x', '{OLD}']\n"), ["a@x", OLD])

    def test_round_trip(self):
        items = ["a@x", NEW]
        self.assertEqual(mig.parse_strv(mig.format_strv(items)), items)


class TestPlanEnabled(unittest.TestCase):
    def test_absent_means_nothing_to_do(self):
        self.assertIsNone(mig.plan_enabled(["a@x", NEW]))

    def test_replaced_in_place(self):
        self.assertEqual(mig.plan_enabled(["a@x", OLD, "b@y"]),
                         ["a@x", NEW, "b@y"])

    def test_new_already_after_drops_old(self):
        self.assertEqual(mig.plan_enabled([OLD, "a@x", NEW]), [NEW, "a@x"])

    def test_new_already_before_drops_old(self):
        self.assertEqual(mig.plan_enabled([NEW, "a@x", OLD]), [NEW, "a@x"])


class TestLegacyExtensionEntries(unittest.TestCase):
    def test_picks_uuid_and_reload_copies_only(self):
        names = [OLD, NEW, "streamdeck-tiler-reload-123@technolibre.ca",
                 "streamdeck-tiler-reload-9@elsewhere.org", "other@x"]
        self.assertEqual(
            mig.legacy_extension_entries(names),
            ["streamdeck-tiler-reload-123@technolibre.ca", OLD])


class TestPlanDconf(unittest.TestCase):
    def test_nothing_on_either_side(self):
        self.assertFalse(mig.plan_dconf("", ""))

    def test_old_only(self):
        self.assertTrue(mig.plan_dconf("[/]\nenable-media=true\n", ""))

    def test_new_already_set(self):
        self.assertFalse(mig.plan_dconf("[/]\na=1\n", "[/]\nb=2\n"))

    def test_whitespace_is_empty(self):
        self.assertFalse(mig.plan_dconf("\n  \n", ""))


class TestDataDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp(self)
        self.bases = [self.tmp / "config", self.tmp / "state",
                      self.tmp / "cache"]
        for base in self.bases:
            base.mkdir()

    def test_old_only_is_moved_with_its_content(self):
        (self.bases[1] / "streamdeck-tiler" / "claude").mkdir(parents=True)
        (self.bases[1] / "streamdeck-tiler" / "log.jsonl").write_text("x")
        rec = Recorder()
        mig.migrate_data_dirs(self.bases, rec.say, rec.warn)
        self.assertFalse((self.bases[1] / "streamdeck-tiler").exists())
        self.assertEqual(
            (self.bases[1] / "erplibre-home" / "log.jsonl").read_text(), "x")
        self.assertTrue((self.bases[1] / "erplibre-home" / "claude").is_dir())
        self.assertEqual(len(rec.said), 1)
        rec2 = Recorder()
        mig.migrate_data_dirs(self.bases, rec2.say, rec2.warn)
        self.assertEqual((rec2.said, rec2.warned), ([], []))

    def test_conflict_leaves_both_and_warns(self):
        (self.bases[0] / "streamdeck-tiler").mkdir()
        (self.bases[0] / "erplibre-home").mkdir()
        rec = Recorder()
        mig.migrate_data_dirs(self.bases, rec.say, rec.warn)
        self.assertTrue((self.bases[0] / "streamdeck-tiler").is_dir())
        self.assertTrue((self.bases[0] / "erplibre-home").is_dir())
        self.assertEqual(len(rec.warned), 1)
        self.assertIn("streamdeck-tiler", rec.warned[0])
        self.assertIn("merge", rec.warned[0])

    def test_nothing_to_do_says_nothing(self):
        rec = Recorder()
        mig.migrate_data_dirs(self.bases, rec.say, rec.warn)
        self.assertEqual((rec.said, rec.warned), ([], []))


class TestRemoveLegacyExtensions(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp(self)
        self.ext = self.tmp / "extensions"
        self.ext.mkdir()
        self.target = self.tmp / "checkout-ext"
        self.target.mkdir()
        (self.target / "keep.txt").write_text("k")

    def test_symlink_removed_target_untouched(self):
        (self.ext / OLD).symlink_to(self.target)
        rec = Recorder()
        mig.remove_legacy_extensions(self.ext, rec.say, rec.warn)
        self.assertFalse((self.ext / OLD).is_symlink())
        self.assertEqual((self.target / "keep.txt").read_text(), "k")

    def test_dangling_symlink_is_removed(self):
        (self.ext / OLD).symlink_to(self.tmp / "moved-away")
        rec = Recorder()
        mig.remove_legacy_extensions(self.ext, rec.say, rec.warn)
        self.assertFalse((self.ext / OLD).is_symlink())
        self.assertEqual(len(rec.said), 1)

    def test_reload_copy_removed_new_kept(self):
        reload_dir = self.ext / "streamdeck-tiler-reload-7@technolibre.ca"
        reload_dir.mkdir()
        (reload_dir / "extension.js").write_text("")
        (self.ext / NEW).symlink_to(self.target)
        rec = Recorder()
        mig.remove_legacy_extensions(self.ext, rec.say, rec.warn)
        self.assertFalse(reload_dir.exists())
        self.assertTrue((self.ext / NEW).is_symlink())

    def test_missing_directory_is_fine(self):
        rec = Recorder()
        mig.remove_legacy_extensions(self.tmp / "nope", rec.say, rec.warn)
        self.assertEqual((rec.said, rec.warned), ([], []))


GET = ("gsettings", "get", "org.gnome.shell", "enabled-extensions")


SET = ("gsettings", "set", "org.gnome.shell", "enabled-extensions",
       f"['{NEW}']")


class TestMigrateEnabled(unittest.TestCase):
    def test_set_failure_warns_and_says_nothing(self):
        rec = Recorder({GET: (0, f"['{OLD}']\n"), SET: (1, "denied")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual(rec.said, [])
        self.assertEqual(len(rec.warned), 1)

    def test_non_list_value_warns(self):
        rec = Recorder({GET: (0, "5\n")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual([c[0] for c in rec.calls], [GET])
        self.assertEqual(len(rec.warned), 1)

    def test_sets_the_replaced_list(self):
        rec = Recorder({GET: (0, f"['a@x', '{OLD}']\n")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual(rec.calls[-1][0], (
            "gsettings", "set", "org.gnome.shell", "enabled-extensions",
            f"['a@x', '{NEW}']"))
        self.assertEqual(len(rec.said), 1)

    def test_nothing_to_do_sets_nothing(self):
        rec = Recorder({GET: (0, f"['{NEW}']\n")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual([c[0] for c in rec.calls], [GET])
        self.assertEqual(rec.said, [])

    def test_gsettings_failure_warns_and_sets_nothing(self):
        rec = Recorder({GET: (1, "No such schema “org.gnome.shell”")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual([c[0] for c in rec.calls], [GET])
        self.assertEqual(len(rec.warned), 1)


DUMP_OLD = ("dconf", "dump", "/org/gnome/shell/extensions/streamdeck-tiler/")
DUMP_NEW = ("dconf", "dump", "/org/gnome/shell/extensions/erplibre-home/")
LOAD_NEW = ("dconf", "load", "/org/gnome/shell/extensions/erplibre-home/")


class TestMigrateDconf(unittest.TestCase):
    def test_copies_old_into_empty_new(self):
        dump = "[/]\nenable-media=true\n"
        rec = Recorder({DUMP_OLD: (0, dump), DUMP_NEW: (0, "")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertIn((LOAD_NEW, dump), rec.calls)
        self.assertEqual(len(rec.said), 1)

    def test_new_already_set_loads_nothing(self):
        rec = Recorder({DUMP_OLD: (0, "[/]\na=1\n"),
                        DUMP_NEW: (0, "[/]\nb=2\n")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertNotIn(LOAD_NEW, [c[0] for c in rec.calls])

    def test_new_dump_failure_warns(self):
        rec = Recorder({DUMP_OLD: (0, "[/]\na=1\n"), DUMP_NEW: (1, "error")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertNotIn(LOAD_NEW, [c[0] for c in rec.calls])
        self.assertEqual(len(rec.warned), 1)

    def test_load_failure_warns_and_says_nothing(self):
        dump = "[/]\na=1\n"
        rec = Recorder({DUMP_OLD: (0, dump), DUMP_NEW: (0, ""),
                        LOAD_NEW: (1, "denied")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertEqual(rec.said, [])
        self.assertEqual(len(rec.warned), 1)

    def test_dump_failure_warns(self):
        rec = Recorder({DUMP_OLD: (1, "error")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertNotIn(LOAD_NEW, [c[0] for c in rec.calls])
        self.assertEqual(len(rec.warned), 1)


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp(self)
        self.installer = _load(
            "install_claude_hooks", EXT / "hooks" / "install_claude_hooks.py")
        self.installer.SETTINGS = self.tmp / ".claude" / "settings.json"
        self.installer.SETTINGS.parent.mkdir()
        self.new_cmd = str(self.installer.HOOK_PATH)
        self.old_cmd = ("/somewhere/script/stream_deck/gnome-extension/"
                        "hooks/streamdeck-tiler-hook.py")

    def _write(self, data):
        self.installer.SETTINGS.write_text(json.dumps(data), encoding="utf-8")

    def _read(self):
        return json.loads(self.installer.SETTINGS.read_text(encoding="utf-8"))

    def _commands(self, data):
        return [h["command"] for ms in data.get("hooks", {}).values()
                for m in ms for h in m["hooks"]]

    def test_legacy_replaced_by_new(self):
        self._write({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": self.old_cmd}]}]}})
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        commands = self._commands(self._read())
        self.assertNotIn(self.old_cmd, commands)
        self.assertIn(self.new_cmd, commands)
        self.assertEqual(len(rec.said), 1)
        backups = list(self.installer.SETTINGS.parent.glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)

    def test_other_hooks_are_kept(self):
        other = "/usr/local/bin/some-other-hook"
        self._write({"model": "x", "hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": other}]},
            {"hooks": [{"type": "command", "command": self.old_cmd}]}]}})
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        data = self._read()
        self.assertEqual(data["model"], "x")
        self.assertIn(other, self._commands(data))
        self.assertNotIn(self.old_cmd, self._commands(data))
        self.assertEqual(rec.warned, [])

    def test_legacy_under_other_event_removed_once(self):
        self._write({"hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": self.old_cmd}]}]}})
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertNotIn(self.old_cmd, self._commands(self._read()))
        self.assertEqual(len(rec.said), 1)
        rec2 = Recorder()
        mig.migrate_hooks(self.installer, rec2.say, rec2.warn)
        self.assertEqual((rec2.said, rec2.warned), ([], []))
        backups = list(self.installer.SETTINGS.parent.glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)

    def test_without_legacy_entry_file_untouched(self):
        self._write({"hooks": {}})
        before = self.installer.SETTINGS.read_bytes()
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertEqual(self.installer.SETTINGS.read_bytes(), before)
        self.assertEqual(rec.said, [])

    def test_missing_settings_is_fine(self):
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertFalse(self.installer.SETTINGS.exists())
        self.assertEqual((rec.said, rec.warned), ([], []))

    def test_invalid_json_warns(self):
        self.installer.SETTINGS.write_text("{", encoding="utf-8")
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertEqual(len(rec.warned), 1)


class TestSessionBus(unittest.TestCase):
    def test_address_in_environment(self):
        env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/x/bus"}
        self.assertEqual(mig.session_bus_env(env), env)

    def test_no_address_no_socket(self):
        tmp = str(_tmp(self))
        self.assertIsNone(mig.session_bus_env({"XDG_RUNTIME_DIR": tmp}))

    def test_socket_in_runtime_dir(self):
        tmp = str(_tmp(self))
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(os.path.join(tmp, "bus"))
        self.addCleanup(sock.close)
        env = mig.session_bus_env({"XDG_RUNTIME_DIR": tmp})
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"],
                         f"unix:path={tmp}/bus")


class TestSteps(unittest.TestCase):
    def names(self, env):
        return [n for n, _ in mig.steps(env, Path("/h"), print, print)]

    def test_order_with_bus_stops_old_writers_first(self):
        env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/x/bus"}
        self.assertEqual(self.names(env), [
            "Claude hooks", "enabled-extensions", "dconf", "extensions",
            "data directories"])

    def test_order_without_bus(self):
        env = {"XDG_RUNTIME_DIR": str(_tmp(self))}
        self.assertEqual(self.names(env), [
            "Claude hooks", "session bus", "extensions",
            "data directories"])


class TestMain(unittest.TestCase):
    def test_unreadable_extensions_dir_still_exits_zero(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any directory")
        home = _tmp(self)
        ext = home / ".local" / "share" / "gnome-shell" / "extensions"
        ext.mkdir(parents=True)
        ext.chmod(0)
        self.addCleanup(ext.chmod, 0o755)
        env = {"HOME": str(home), "XDG_RUNTIME_DIR": str(_tmp(self)),
               "PATH": os.environ.get("PATH", "")}
        proc = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("migrate: warning:", proc.stderr)

    def test_main_without_bus_exits_zero_and_is_idempotent(self):
        home = _tmp(self)
        (home / ".local" / "state" / "streamdeck-tiler").mkdir(parents=True)
        runtime = str(_tmp(self))
        env = {"HOME": str(home), "XDG_RUNTIME_DIR": runtime,
               "PATH": os.environ.get("PATH", "")}
        first = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                               capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((home / ".local" / "state" / "erplibre-home").is_dir())
        self.assertIn("no session bus", first.stdout)
        second = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                                capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip().splitlines(),
                         [line for line in first.stdout.strip().splitlines()
                          if "no session bus" in line])


if __name__ == "__main__":
    unittest.main()
