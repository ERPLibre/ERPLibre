#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Parsers of the system tools the deck plugins read."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402
import test_erplibre_streamdeck_pages as P  # noqa: E402

S.install()
from erplibre_streamdeck import dbus, paths, settings  # noqa: E402
from erplibre_streamdeck.kernel import Kernel  # noqa: E402
from erplibre_streamdeck.plugin import LoadedPlugin  # noqa: E402
from erplibre_streamdeck.plugins import (  # noqa: E402
    bluetooth, claude_sessions, layouts, sound, timers,
)
from erplibre_streamdeck.ui import render  # noqa: E402


WPCTL_STATUS = """\
Audio
 ├─ Devices:
 │      40. Built-in Audio                      [alsa]
 │
 ├─ Sinks:
 │  *   51. Built-in Audio Analog Stereo        [vol: 0.40]
 │      62. Demo Headset                        [vol: 0.70]
 │
 ├─ Sources:
 │  *   52. Built-in Audio Analog Stereo        [vol: 1.00 MUTED]
 │
 ├─ Filters:
"""


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


def by_argv(answers):
    """A subprocess.run stand-in answering by the first two argv words."""

    def run(argv, **kwargs):
        return answers.get(tuple(argv[:2]), done("", 1))

    return run


class WpctlTest(unittest.TestCase):
    def test_get_volume_and_mute(self):
        with mock.patch(
            "subprocess.run", return_value=done("Volume: 0.50 [MUTED]\n")
        ):
            self.assertEqual((50, True), sound._wpctl_get("@X@"))

    def test_get_volume_not_muted(self):
        with mock.patch(
            "subprocess.run", return_value=done("Volume: 1.00\n")
        ):
            self.assertEqual((100, False), sound._wpctl_get("@X@"))

    def test_get_malformed(self):
        with mock.patch("subprocess.run", return_value=done("garbage")):
            self.assertEqual((None, None), sound._wpctl_get("@X@"))

    def test_get_failure(self):
        with mock.patch("subprocess.run", return_value=done("", 1)):
            self.assertEqual((None, None), sound._wpctl_get("@X@"))

    def test_list_devices(self):
        with mock.patch("subprocess.run", return_value=done(WPCTL_STATUS)):
            sinks = sound._wpctl_list_devices("Sinks")
            sources = sound._wpctl_list_devices("Sources")
        self.assertEqual(
            [
                {"id": 51, "default": True,
                 "name": "Built-in Audio Analog Stereo"},
                {"id": 62, "default": False, "name": "Demo Headset"},
            ],
            sinks,
        )
        self.assertEqual([52], [d["id"] for d in sources])

    def test_list_devices_failure(self):
        with mock.patch("subprocess.run", return_value=done("", 1)):
            self.assertEqual([], sound._wpctl_list_devices("Sinks"))

    def test_default_short_is_last_word_cut_to_six(self):
        with mock.patch("subprocess.run", return_value=done(WPCTL_STATUS)):
            self.assertEqual("Stereo", sound._wpctl_default_short("Sinks"))

    def test_default_short_empty_without_devices(self):
        with mock.patch("subprocess.run", return_value=done("", 1)):
            self.assertEqual("", sound._wpctl_default_short("Sinks"))


class BluetoothTest(unittest.TestCase):
    def test_powered_from_bluetoothctl(self):
        shown = done(
            "Controller 00:00:5E:00:53:01\n\tPowered: yes\n"
        )
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", return_value=shown):
            self.assertIs(True, bluetooth._bt_powered())

    def test_powered_off_from_bluetoothctl(self):
        shown = done("Controller 00:00:5E:00:53:01\n\tPowered: no\n")
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", return_value=shown):
            self.assertIs(False, bluetooth._bt_powered())

    def test_powered_falls_back_to_rfkill(self):
        answers = {
            ("bluetoothctl", "show"): done("", 1),
            ("rfkill", "list"): done("0: hci0: Bluetooth\n"
                                     "\tSoft blocked: no\n"),
        }
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", by_argv(answers)):
            self.assertIs(True, bluetooth._bt_powered())

    def test_powered_unknown_without_any_tool(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(bluetooth._bt_powered())

    def test_paired_merges_connected(self):
        paired = done(
            "Device 00:00:5E:00:53:10 Demo Headphones\n"
            "Device 00:00:5E:00:53:11 Demo Keyboard\n"
        )
        connected = done("Device 00:00:5E:00:53:11 Demo Keyboard\n")

        def run(argv, **kwargs):
            return paired if argv[-1] == "Paired" else connected

        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", run):
            devices = bluetooth._bt_list_paired()
        self.assertEqual(
            [
                ("00:00:5E:00:53:10", "Demo Headphones", False),
                ("00:00:5E:00:53:11", "Demo Keyboard", True),
            ],
            devices,
        )

    def test_paired_empty_without_bluetoothctl(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual([], bluetooth._bt_list_paired())


class LayoutsTest(unittest.TestCase):
    def test_save_then_load_round_trips_through_layouts_file(self):
        answers = {
            "ListWindows": done("('[{\"id\": \"1\", \"x\": 0}]',)\n"),
            "ApplyLayout": done("(1,)\n"),
        }
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return answers[argv[8].rsplit(".", 1)[1]]

        import tempfile
        from pathlib import Path

        log = lambda msg: None  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "conf"
            with mock.patch.object(paths, "CONFIG_DIR", conf), \
                    mock.patch.object(
                        paths, "LAYOUTS_FILE", conf / "layouts.json"
                    ), mock.patch("subprocess.run", side_effect=run):
                self.assertTrue(layouts._save_layout_slot(dbus, log, 2))
                saved = layouts._layouts_load()["slots"]["2"]
                self.assertEqual([{"id": "1", "x": 0}], saved["windows"])
                self.assertEqual(1, saved["count"])
                windows = layouts._slot_windows(2)
                self.assertTrue(layouts._load_layout(dbus, log, windows))
                self.assertIsNone(layouts._slot_windows(3))
        self.assertTrue(calls[-1][-1].startswith('[{"id"'))


class TimersTest(unittest.TestCase):
    def test_label_is_first_word_and_minutes_seconds(self):
        timer = {"name": "Write report", "elapsed": 125}
        self.assertEqual("Write\n02:05", timers._label_for_timer(timer))

    def test_tracker_answer_gives_one_timer(self):
        class Ctx:
            pass

        ctx = Ctx()
        ctx.dbus = dbus
        ctx.log = lambda msg: None
        answer = done('(\'[{"id": "t1", "running": true}]\',)\n')
        with mock.patch("subprocess.run", return_value=answer):
            found = timers._list_timers(ctx)
        self.assertEqual([{"id": "t1", "running": True}], found)


class SessionsTest(unittest.TestCase):
    def test_bad_pid_file_is_skipped_or_isolated(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "claude"
            state.mkdir()
            (state / "bad.json").write_text(
                json.dumps({"session_id": "s", "pid": "abc"})
            )
            with mock.patch.object(paths, "state_dir", lambda: Path(tmp)):
                # int("abc") escapes load_sessions: it neither skips the
                # file nor drops the others.
                with self.assertRaises(ValueError):
                    claude_sessions.load_sessions()
                loaded = LoadedPlugin(
                    "claude_sessions", claude_sessions.PLUGIN, "repo",
                    Path(claude_sessions.__file__),
                )
                err = io.StringIO()
                with mock.patch.object(dbus, "available", lambda: False):
                    kernel = Kernel(S.FakeDeck(5, 3), [loaded])
                    with contextlib.redirect_stderr(err):
                        kernel.render()
                        kernel.render()
        lines = [
            ln for ln in err.getvalue().splitlines()
            if ln.startswith("[erplibre-home] claude_sessions")
        ]
        # One journal entry for the two renders, not none: the kernel
        # reports the failing provider once and goes on.
        self.assertEqual(1, len(lines))


class SlowKeyTest(unittest.TestCase):
    """A key whose action waits on D-Bus or a dialog starts one job: the
    key shows "…" until the next loop pass hands the result back, which
    then shows what the press alone showed before."""

    BUSY = ["5a5a28", "\u2026", None]

    def start(self, world, cols=5, rows=3):
        h = S.Harness(S.PackageTarget(), cols, rows)
        h.__enter__()
        self.addCleanup(h.__exit__, None, None, None)
        world(h)
        h.boot()
        return h

    def press_slow(self, h, key):
        """Press `key`, check it started one job and shows "…", run the
        job and one loop pass; the press, threads and loop steps."""
        h.press(key)
        self.assertEqual(1, len(S.FakeThread.queue))
        self.assertEqual(self.BUSY, h.deck.screen[key])
        h.run_threads()
        h.loop(1)
        h.check_clean(self)
        return h.steps[-3:]

    def assert_flash(self, h, key, label):
        """`label` shows on `key` and its row and column neighbours."""
        cols, rows = h.deck.cols, h.deck.rows
        c, r = key % cols, key // cols
        around = {
            y * cols + x
            for x, y in ((c, r), (c - 1, r), (c + 1, r), (c, r - 1),
                         (c, r + 1))
            if 0 <= x < cols and 0 <= y < rows
        }
        shown = {
            k for k, f in enumerate(h.deck.rendering())
            if f and f[1] == label
        }
        self.assertEqual(around, shown)

    def test_dev_reload_hot_reload_is_a_job(self):
        h = self.start(P.full_world)
        key = P.face_key(h, "DEV\nRELOAD")
        press, threads, loop = self.press_slow(h, key)
        self.assertEqual([], press["effects"])
        self.assertEqual(["gdbus HotReload"], threads["effects"])
        self.assertEqual("idle", loop["page"])
        self.assert_flash(h, key, "OK!")

    def test_dev_reload_failure_flashes_err(self):
        h = self.start(P.full_world)
        h.proc.answer("gdbus HotReload", returncode=1)
        key = P.face_key(h, "DEV\nRELOAD")
        self.press_slow(h, key)
        self.assert_flash(h, key, "ERR")

    def test_tiling_tile_window_is_a_job(self):
        h = self.start(P.empty_world)
        h.goto("tiling")
        h.press(0)
        last = h.deck.key_count() - 1
        press, threads, loop = self.press_slow(h, last)
        st = h.target.kernel.state("tiling")
        self.assertEqual((None, 0.0), (st.corner1, st.last_touch))
        self.assertEqual("tiling", press["page"])
        self.assertEqual([], press["effects"])
        self.assertEqual(
            ["gdbus TileWindow 5 3 0 0 4 2"], threads["effects"]
        )
        self.assertEqual("idle", loop["page"])
        self.assert_flash(h, last, "OK!")

    def test_tiling_failure_flashes_err_with_reason(self):
        h = self.start(P.empty_world)
        h.proc.answer("gdbus TileWindow", returncode=1)
        h.goto("tiling")
        h.press(0)
        self.press_slow(h, 1)
        self.assertEqual("idle", h.target.page())
        self.assert_flash(h, 1, "ERR")
        self.assertIn(
            "tiling: TileWindow(5x3 0,0-1,0) failed via D-Bus",
            h.journal.getvalue(),
        )

    def layout_page(self):
        h = self.start(P.full_world)
        h.goto("layout")
        return h

    def test_layout_save_is_a_job(self):
        h = self.layout_page()
        before = h.steps[-1]["files"]
        press, threads, loop = self.press_slow(h, 6)  # SAVE 1
        self.assertEqual(([], before), (press["effects"], press["files"]))
        self.assertEqual(["gdbus ListWindows"], threads["effects"])
        saved = threads["files"]["CONFIG/erplibre-home/layouts.json"]
        self.assertEqual(P.WINDOWS, saved["slots"]["1"]["windows"])
        self.assertEqual("layout", loop["page"])
        self.assert_flash(h, 6, "OK!")

    def test_layout_save_without_windows_flashes_err(self):
        h = self.layout_page()
        h.proc.answer("gdbus ListWindows", S.gvariant_string("[]"))
        self.press_slow(h, 7)  # SAVE 2
        self.assert_flash(h, 7, "ERR")
        self.assertIn("layout save slot 2 failed", h.journal.getvalue())

    def test_layout_save_write_failure_is_journaled(self):
        h = self.layout_page()
        denied = OSError(13, "Permission denied")
        with mock.patch.object(
            layouts.jsonfile, "write_atomic", side_effect=denied
        ):
            self.press_slow(h, 6)  # SAVE 1
        self.assertEqual("layout", h.target.page())
        self.assert_flash(h, 6, "ERR")
        journal = h.journal.getvalue()
        self.assertIn(
            "layouts: job failed: PermissionError(13, 'Permission "
            "denied')", journal,
        )
        self.assertIn("layout save slot 1 failed", journal)

    def test_layout_load_is_a_job(self):
        h = self.layout_page()
        press, threads, loop = self.press_slow(h, 11)  # LOAD 1
        self.assertEqual([], press["effects"])
        self.assertEqual(
            "gdbus ApplyLayout", threads["effects"][0][:17]
        )
        self.assertEqual("layout", loop["page"])
        self.assert_flash(h, 11, "OK!")

    def test_layout_load_of_empty_slot_starts_no_job(self):
        h = self.layout_page()
        h.press(12)  # LOAD 2, empty
        self.assertEqual([], S.FakeThread.queue)
        self.assert_flash(h, 12, "ERR")

    def test_layout_shortcut_load_is_a_job(self):
        h = self.start(P.full_world, 8, 4)  # the shortcuts fit at 8x4
        key = P.face_key(h, "*\n1")
        press, threads, loop = self.press_slow(h, key)
        self.assertEqual(
            "gdbus ApplyLayout", threads["effects"][0][:17]
        )
        self.assertEqual("idle", loop["page"])
        self.assert_flash(h, key, "OK!")

    def test_layout_shortcut_failure_flashes_err(self):
        h = self.start(P.full_world, 8, 4)  # the shortcuts fit at 8x4
        h.proc.answer("gdbus ApplyLayout", "(0,)\n")
        key = P.face_key(h, "*\n1")
        self.press_slow(h, key)
        self.assert_flash(h, key, "ERR")
        self.assertIn(
            "layout shortcut load slot 1 failed", h.journal.getvalue()
        )

    def timer_page(self):
        h = self.start(P.full_world)
        h.goto("timer_list")
        return h

    def assert_no_flash(self, h):
        faces = [f[1] for f in h.deck.rendering() if f]
        self.assertEqual([], [t for t in faces if t in ("OK!", "ERR")])

    def test_timer_toggle_is_a_job(self):
        h = self.timer_page()
        press, threads, loop = self.press_slow(h, 1)
        self.assertEqual([], press["effects"])
        self.assertEqual(
            ["gdbus ToggleTrackerTimer t1"], threads["effects"]
        )
        self.assertIn("gdbus ListTrackerTimers", loop["effects"])
        self.assertEqual("timer_list", loop["page"])
        self.assert_no_flash(h)
        self.assertEqual("Writin\n02:05", h.deck.screen[1][1])

    def test_timer_toggle_failure_flashes_err(self):
        h = self.timer_page()
        h.proc.answer("gdbus ToggleTrackerTimer", returncode=1)
        self.press_slow(h, 1)
        self.assert_flash(h, 1, "ERR")
        self.assertIn(
            "ToggleTrackerTimer(t1) failed", h.journal.getvalue()
        )

    def test_timer_add_is_a_job(self):
        h = self.timer_page()
        press, threads, loop = self.press_slow(h, 12)  # NEW
        self.assertEqual(["gdbus AddTrackerTimer"], threads["effects"])
        self.assertIn("gdbus ListTrackerTimers", loop["effects"])
        self.assert_no_flash(h)

    def test_timer_add_without_id_flashes_err(self):
        h = self.timer_page()
        h.proc.answer("gdbus AddTrackerTimer", S.gvariant_string(""))
        self.press_slow(h, 12)
        self.assert_flash(h, 12, "ERR")
        self.assertIn(
            "AddTrackerTimer returned no id", h.journal.getvalue()
        )

    def test_timer_export_dialog_and_write_are_one_job(self):
        h = self.timer_page()
        csv_path = S.SANDBOX / "tmp" / "export" / "timers.csv"
        press, threads, loop = self.press_slow(h, 11)  # EXPT CSV
        # The list is read under the lock, before the dialog opens.
        self.assertEqual(["gdbus ListTrackerTimers"], press["effects"])
        self.assertEqual(
            ["zenity"], [e.split()[0] for e in threads["effects"]]
        )
        self.assertEqual(P.TIMERS_CSV, csv_path.read_bytes().decode())
        self.assertEqual([], loop["effects"])
        self.assert_flash(h, 11, "OK!")

    def test_timer_export_cancelled_renders_without_flash(self):
        h = self.timer_page()
        h.proc.answer("zenity", returncode=1)
        self.press_slow(h, 11)
        self.assertEqual("timer_list", h.target.page())
        self.assert_no_flash(h)
        self.assertEqual("EXPT\nCSV", h.deck.screen[11][1])

    def test_timer_export_write_failure_flashes_err(self):
        h = self.timer_page()
        blocker = S.SANDBOX / "tmp" / "blocker"
        blocker.write_text("", encoding="utf-8")
        h.proc.answer("zenity", f"{blocker / 'timers'}\n")
        self.press_slow(h, 11)
        self.assert_flash(h, 11, "ERR")

    def test_timer_reset_is_a_job(self):
        h = self.timer_page()
        h.press(13)  # RESET ALL
        press, threads, loop = self.press_slow(h, 14)  # OK
        self.assertEqual("timer_reset_confirm", press["page"])
        self.assertEqual(
            ["gdbus ResetAllTrackerTimers"], threads["effects"]
        )
        self.assertEqual(["gdbus ListTrackerTimers"], loop["effects"])
        self.assertEqual("timer_list", loop["page"])
        self.assert_flash(h, 14, "OK!")

    def test_timer_reset_failure_flashes_err(self):
        h = self.timer_page()
        h.proc.answer("gdbus ResetAllTrackerTimers", returncode=1)
        h.press(13)
        self.press_slow(h, 14)
        self.assertEqual("timer_list", h.target.page())
        self.assert_flash(h, 14, "ERR")
        self.assertIn(
            "ResetAllTrackerTimers failed via D-Bus", h.journal.getvalue()
        )

    def bluetooth_page(self, world=P.full_world):
        h = self.start(world)
        h.goto("bluetooth")
        return h

    def test_bluetooth_power_is_a_job(self):
        h = self.bluetooth_page()
        press, threads, loop = self.press_slow(h, 6)  # BT ON
        # The power state is read under the lock; the switch is the job.
        self.assertEqual(["bluetoothctl show"], press["effects"])
        self.assertEqual(["bluetoothctl power off"], threads["effects"])
        self.assertIn("bluetoothctl show", loop["effects"])
        self.assertEqual("bluetooth", loop["page"])
        self.assert_no_flash(h)
        self.assertEqual("BT\nON", h.deck.screen[6][1])

    def test_bluetooth_power_failure_shows_no_flash(self):
        h = self.bluetooth_page(P.bt_off_world)
        h.proc.answer("bluetoothctl power", returncode=1)
        h.proc.answer("rfkill unblock", returncode=1)
        press, threads, loop = self.press_slow(h, 6)  # BT OFF
        self.assertEqual(
            ["bluetoothctl power on", "rfkill unblock bluetooth"],
            threads["effects"],
        )
        self.assert_no_flash(h)
        self.assertEqual("BT\nOFF", h.deck.screen[6][1])

    def test_bluetooth_without_adapter_flashes_err_without_job(self):
        h = self.bluetooth_page(P.bt_na_world)
        h.press(6)
        self.assertEqual([], S.FakeThread.queue)
        self.assert_flash(h, 6, "ERR")

    def test_bluetooth_disconnect_is_a_job(self):
        h = self.bluetooth_page()
        press, threads, loop = self.press_slow(h, 7)  # connected
        self.assertEqual(
            ["bluetoothctl devices Connected",
             "bluetoothctl devices Paired"],
            press["effects"],
        )
        self.assertEqual(
            ["bluetoothctl disconnect 00:00:5E:00:53:10"],
            threads["effects"],
        )
        self.assertIn("bluetoothctl show", loop["effects"])
        self.assert_no_flash(h)
        self.assertEqual("Headph", h.deck.screen[7][1])

    def test_bluetooth_connect_is_a_job(self):
        h = self.bluetooth_page()
        press, threads, loop = self.press_slow(h, 8)  # not connected
        self.assertEqual(
            ["bluetoothctl connect 00:00:5E:00:53:11"],
            threads["effects"],
        )
        self.assertEqual("bluetooth", loop["page"])
        self.assert_no_flash(h)

    def test_bluetooth_key_without_device_starts_no_job(self):
        h = self.bluetooth_page()
        h.press(9)  # a third slot, two paired devices
        self.assertEqual([], S.FakeThread.queue)
        self.assert_no_flash(h)

    def test_claude_session_actions_are_jobs(self):
        h = self.start(P.full_world)
        for key, method in enumerate(
            ("FocusClaudeSession", "AcceptClaudeSession",
             "SetClaudeSessionWindow", "KillClaudeSession"),
            start=1,
        ):
            h.goto("claude_session", sid="sess-a")
            h.wait(P.FLASH_GAP)
            press, threads, loop = self.press_slow(h, key)
            self.assertEqual("claude_session", press["page"])
            self.assertEqual([], press["effects"])
            self.assertEqual(
                [f"gdbus {method} sess-a"], threads["effects"]
            )
            self.assertEqual("idle", loop["page"])
            self.assert_flash(h, key, "OK!")

    def test_claude_session_failure_flashes_err_and_goes_home(self):
        h = self.start(P.full_world)
        h.proc.answer("gdbus KillClaudeSession", returncode=1)
        h.goto("claude_session", sid="sess-a")
        self.press_slow(h, 4)  # KILL
        self.assertEqual("idle", h.target.page())
        self.assert_flash(h, 4, "ERR")
        self.assertIn(
            "KillClaudeSession(sess-a) failed", h.journal.getvalue()
        )

    def test_mpv_commands_are_jobs(self):
        h = self.start(P.full_world)
        # key, command, page shown once the result is back
        for key, command, page in (
            (1, "play_pause", "idle"), (2, "quit", "idle"),
            (5, "vol_down", "mpv_session"), (6, "vol_up", "mpv_session"),
        ):
            h.goto("mpv_session", pid=1)
            h.wait(P.FLASH_GAP)
            press, threads, loop = self.press_slow(h, key)
            self.assertEqual("mpv_session", press["page"])
            self.assertEqual([], press["effects"])
            self.assertEqual(
                [f"gdbus MpvSendCommand 1 {command}"], threads["effects"]
            )
            self.assertEqual(page, loop["page"])
            self.assert_flash(h, key, "OK!")

    def test_mpv_volume_failure_flashes_err_on_the_page(self):
        h = self.start(P.full_world)
        h.proc.answer("gdbus MpvSendCommand", returncode=1)
        h.goto("mpv_session", pid=1)
        self.press_slow(h, 6)  # VOL +
        self.assertEqual("mpv_session", h.target.page())
        self.assert_flash(h, 6, "ERR")
        self.assertIn(
            "MpvSendCommand(1, 'vol_up') failed", h.journal.getvalue()
        )


class SettingsKeepTest(unittest.TestCase):
    def test_font_scale_save_keeps_other_keys(self):
        stored = {"translator_llm": "ollama", "font_scale": 1.0}

        def save(data):
            stored.clear()
            stored.update(data)

        with mock.patch.object(settings, "load", lambda: dict(stored)), \
                mock.patch.object(settings, "save", save):
            render.Style().set_font_scale(1.2, settings)
        self.assertEqual("ollama", stored["translator_llm"])
        self.assertEqual(1.2, stored["font_scale"])


if __name__ == "__main__":
    unittest.main()
