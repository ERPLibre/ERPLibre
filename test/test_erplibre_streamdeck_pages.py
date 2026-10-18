#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Goldens of every deck page, at the four deck geometries.

Each scenario boots the deck program on a `FakeDeck`, in a world of
invented inputs (state files, D-Bus, wpctl, bluetoothctl answers), runs
its steps and compares what every key shows, every command the program
ran and the state files after each step with
`test/fixtures/erplibre_streamdeck/<name>.json`.

`PackagePages` runs the package against the goldens. A deliberate change
of the deck's output rewrites them with
`STREAMDECK_GOLDEN=update-from-package`. A scenario whose page has no
plugin, or a package that lacks a repository plugin, fails.

A page scenario reaches its page with `goto` right after boot, never by a
home press. The `home__*` scenarios pin the passage from the home screen
to each page.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
# One loop pass advances the clock by the kernel's LOOP_SEC.
from erplibre_streamdeck.kernel import LOOP_SEC  # noqa: E402

# Longer than the result flash (0.5 s): a press inside the flash is
# dropped, so `tap` waits this long after each press.
FLASH_GAP = 0.6

TRUE = "(true,)\n"
INTROSPECT_OK = (
    "node /org/gnome/Shell/Extensions/ERPLibreHome {\n"
    "  interface org.gnome.Shell.Extensions.ERPLibreHome {\n"
    "    methods:\n"
    "      TileWindow(in  i grid_cols, ...);\n"
    "  };\n"
    "};\n"
)
INTROSPECT_NOEXT = "node /org/gnome/Shell/Extensions/ERPLibreHome {\n};\n"

TIMERS = [
    {"id": "t1", "name": "Writing docs", "elapsed": 125, "running": True},
    {"id": "t2", "name": "Review notes", "elapsed": 3725, "running": True},
    {"id": "t3", "name": "Paused task", "elapsed": 60, "running": False},
]
TIMERS_CSV = (
    "name,seconds,time\r\n"
    "Writing docs,125,00:02:05\r\n"
    "Review notes,3725,01:02:05\r\n"
    "Paused task,60,00:01:00\r\n"
)
WINDOWS = [
    {"id": "101", "wm_class": "Demo-terminal", "title": "TODO",
     "x": 0, "y": 0, "w": 960, "h": 1080, "stacking": 1},
    {"id": "102", "wm_class": "Demo-browser", "title": "Demo page",
     "x": 960, "y": 0, "w": 960, "h": 540, "stacking": 2},
]
# What layout slot 1 holds before any save: one window, unlike WINDOWS,
# so a save over it shows in the file and the preview.
SAVED_WINDOWS = [
    {"id": "103", "wm_class": "Demo-editor", "title": "Notes",
     "x": 0, "y": 0, "w": 1920, "h": 1080, "stacking": 1},
]
TODO_LOG = (
    "\x1b[1mDemo menu\x1b[0m\r\n"
    "[1] First\r\n"
    "[2] Second\r\n"
    "Select: "
)
WPCTL_STATUS = (
    "Audio\n"
    " ├─ Devices:\n"
    " │      40. Demo Audio Controller            [alsa]\n"
    " │  \n"
    " ├─ Sinks:\n"
    " │  *   48. Demo Analog Stereo               [vol: 0.40]\n"
    " │      52. Demo Headset                     [vol: 0.70]\n"
    " │  \n"
    " ├─ Sources:\n"
    " │  *   49. Demo Analog Mic                  [vol: 0.65 MUTED]\n"
    " │  \n"
    " ├─ Filters:\n"
    " │  \n"
    " └─ Streams:\n"
    "\n"
    "Video\n"
    " ├─ Devices:\n"
)
BT_SHOW = "Controller 00:00:5E:00:53:01 (public)\n\tPowered: {}\n"
BT_PAIRED = (
    "Device 00:00:5E:00:53:10 Demo Headphones\n"
    "Device 00:00:5E:00:53:11 Demo Keyboard\n"
)
BT_CONNECTED = "Device 00:00:5E:00:53:10 Demo Headphones\n"
HISTORY = [
    {"text": "premier essai de dictée", "llm_mode": "off"},
    {"text": "second", "llm_mode": "off"},
]
# Tile colours of the home dashboard: mpv, the four Claude statuses, a
# running timer, a TODO terminal.
DASHBOARD = {
    "2864b4", "2e7d32", "00838f", "d4a017", "c62828", "00a028", "8c5a32",
}
HOME_LABELS = (
    "TILE", "TIMER", "DEV\nRELOAD", "SOUND", "LAYOUT", "A11Y", "BT",
    "TRANSL", "TODO",
)
# Home keys whose press runs as a job (kernel run_blocking).
HOME_JOBS = {"DEV\nRELOAD"}

EMPTY = (
    "EMPTY: extension present, no session, no timer, no window, wpctl "
    "fails, bluetooth off, no state file"
)
FULL = (
    "FULL: 1 mpv (pid 1), 2 Claude sessions (awaiting_stop with a "
    "notification, working), 3 timers (2 running), 1 TODO terminal whose "
    "log ends on a 2-item menu, layout slot 1, sink 40 %, source muted, "
    "2 sinks 1 source, bluetooth on with 2 paired 1 connected"
)
NOEXT = "NOEXT: EMPTY, introspect without TileWindow until 11 s"


# ----------------------------------------------------------------- worlds


def _actions(h):
    """Every action the deck can run succeeds."""
    answer = h.proc.answer
    for method in (
        "TileWindow", "ToggleTrackerTimer", "ResetAllTrackerTimers",
        "SendKeysToWindow", "FocusWindowById", "MpvSendCommand",
        "FocusClaudeSession", "AcceptClaudeSession",
        "SetClaudeSessionWindow", "KillClaudeSession",
    ):
        answer(f"gdbus {method}", TRUE)
    answer("gdbus AddTrackerTimer", S.gvariant_string("t4"))
    answer("gdbus HotReload", S.gvariant_string("reloaded"))
    answer("gdbus ApplyLayout", "(2,)\n")
    answer("gdbus GetFocusedWindowId", S.gvariant_string("201"))
    for command in (
        "wpctl set-volume", "wpctl set-mute", "wpctl set-default",
        "bluetoothctl power", "bluetoothctl connect",
        "bluetoothctl disconnect", "rfkill block", "rfkill unblock",
    ):
        answer(command)
    # The save dialog answers a name without extension: the export adds
    # ".csv".
    answer("zenity", f"{S.SANDBOX / 'tmp' / 'export' / 'timers'}\n")


def empty_world(h):
    _actions(h)
    answer = h.proc.answer
    answer("gdbus introspect", INTROSPECT_OK)
    answer("gdbus ListTrackerTimers", S.gvariant_string("[]"))
    answer("gdbus ListWindows", S.gvariant_string("[]"))
    answer("wpctl get-volume", returncode=1)
    answer("wpctl status", returncode=1)
    answer("bluetoothctl show", BT_SHOW.format("no"))
    answer("bluetoothctl devices")
    answer("rfkill list bluetooth")


def noext_world(h):
    empty_world(h)
    h.proc.answer("gdbus introspect", INTROSPECT_NOEXT)


def full_world(h):
    empty_world(h)
    answer = h.proc.answer
    answer("gdbus ListTrackerTimers", S.gvariant_string(json.dumps(TIMERS)))
    answer("gdbus ListWindows", S.gvariant_string(json.dumps(WINDOWS)))
    answer("wpctl get-volume @DEFAULT_AUDIO_SINK@", "Volume: 0.40\n")
    answer("wpctl get-volume @DEFAULT_AUDIO_SOURCE@",
           "Volume: 0.65 [MUTED]\n")
    answer("wpctl status", WPCTL_STATUS)
    answer("bluetoothctl show", BT_SHOW.format("yes"))
    answer("bluetoothctl devices Paired", BT_PAIRED)
    answer("bluetoothctl devices Connected", BT_CONNECTED)
    h.write_json(
        "STATE/erplibre-home/mpv/demo.json",
        {"pid": 1, "title": "Demo stream",
         "url": "https://example.org/demo", "started_at": 1799999000000},
    )
    h.write_json(
        "STATE/erplibre-home/claude/a.json",
        {"session_id": "sess-a", "pid": 0, "cwd": "/srv/demo",
         "description": "Refactor the demo parser module",
         "notification_message": "Allow the edit of parser.py?",
         "ts_active": 100, "ts_stop": 300},
    )
    h.write_json(
        "STATE/erplibre-home/claude/b.json",
        {"session_id": "sess-b", "pid": 0, "cwd": "/srv/demo",
         "description": "Write the demo tests",
         "ts_active": 150, "ts_tool": 200},
    )
    log = S.STATE / "erplibre-home" / "todo" / "todo-demo.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(TODO_LOG, encoding="utf-8")
    h.write_json(
        "STATE/erplibre-home/todo_terminals.json",
        [{"window_id": "101", "name": "TODO 1",
          "opened_at": 1799999000.0, "log_path": str(log)}],
    )
    h.write_json(
        "CONFIG/erplibre-home/layouts.json",
        {"slots": {"1": {"saved_at": "09:30", "count": 1,
                         "windows": SAVED_WINDOWS}}},
    )


def full_fr_world(h):
    full_world(h)
    h.lang = "fr"


def bt_off_world(h):
    full_world(h)
    h.proc.answer("bluetoothctl show", BT_SHOW.format("no"))


def bt_na_world(h):
    """No bluetoothctl; rfkill lists no adapter."""
    full_world(h)
    h.which.discard("bluetoothctl")


def history_world(h):
    empty_world(h)
    S.TRANSLATOR.history = [dict(entry) for entry in HISTORY]


def launch_world(h):
    """EMPTY, and the terminal the TODO key opens is window 201."""
    empty_world(h)
    window = dict(WINDOWS[0], id="201")
    h.proc.answer("gdbus ListWindows", S.gvariant_string(json.dumps(
        [window])))


# ---------------------------------------------------------------- helpers


def tap(h, key):
    """Press `key`, then let any flash it starts expire."""
    h.press(key)
    h.wait(FLASH_GAP)


def tap_job(h, key):
    """Press a key whose action runs as a job: the press shows "…", the
    job runs, one loop pass hands its result back. The clock ends where
    `tap` leaves it, past the flash that result starts: the steps after
    it see the same time (a TODO log name carries the wall clock)."""
    h.press(key)
    h.run_threads()
    h.loop(1)
    h.wait(FLASH_GAP - LOOP_SEC)


def face_key(h, text):
    """The first key showing `text`, or None when the deck shows none."""
    for key, face in enumerate(h.deck.rendering()):
        if face and face[1] == text:
            return key
    return None


def shown_keys(h):
    """Keys whose face carries a label, in key order."""
    return [k for k, f in enumerate(h.deck.rendering()) if f and f[1]]


def row(h, index, col):
    """Key at `col` of row `index`, or None when the deck lacks it."""
    if index >= h.deck.rows or col >= h.deck.cols:
        return None
    return index * h.deck.cols + col


# ---------------------------------------------------------------- mixin


class Scenarios:
    """Mixed into one TestCase per target."""

    def run_all(self, name, inputs, world, script, pages=()):
        runs = {}
        for cols, rows in S.GEOMETRIES:
            with S.Harness(self.make_target(), cols, rows) as h:
                world(h)
                h.boot()
                missing = [p for p in pages if not h.target.has_page(p)]
                self.assertEqual([], missing, "no plugin for these pages")
                self.assertTrue(h.target.complete(), "plugin missing")
                script(h)
                h.check_clean(self)
                runs[f"{cols}x{rows}"] = h.steps
        S.check_golden(self, name, inputs, runs)

    # -- home screen

    def test_home_empty(self):
        self.run_all("home__empty", EMPTY, empty_world,
                     lambda h: h.loop(1))

    def test_home_full(self):
        def script(h):
            h.loop(1)
            h.wait(2.1)
            h.loop(1)

        self.run_all("home__full", FULL, full_world, script)

    def test_home_full_fr(self):
        self.run_all("home__full_fr", FULL + "; lang fr", full_fr_world,
                     lambda h: h.loop(1))

    def test_home_noext(self):
        def script(h):
            start = h.clock.now

            def on_poll():
                if h.clock.now - start >= 11.0:
                    h.proc.answer("gdbus introspect", INTROSPECT_OK)

            # Rechecks every 5 s: two fail (5.1 s, 10.2 s), the third
            # (15.3 s) finds the extension; none follows by 20.7 s.
            h.loop(70, on_poll=on_poll)

        self.run_all("home__noext", NOEXT, noext_world, script)

    def test_home_presses(self):
        def script(h):
            for label in HOME_LABELS:
                key = face_key(h, label)
                if key is None:
                    continue
                (tap_job if label in HOME_JOBS else tap)(h, key)
                h.goto("idle")
            tap(h, face_key(h, "MIC\nOFF"))
            key = face_key(h, "*\n1")
            if key is not None:
                tap_job(h, key)

        self.run_all("home__presses", FULL, full_world, script)

    def test_home_dashboard(self):
        def script(h):
            h.loop(1)
            tiles = [
                k for k, f in enumerate(h.deck.rendering())
                if f and f[0] in DASHBOARD
            ]
            for key in tiles:
                tap(h, key)
                h.goto("idle")

        self.run_all("home__dashboard", FULL, full_world, script)

    def test_flash(self):
        def script(h):
            key = face_key(h, "DEV\nRELOAD")
            h.press(key)
            h.run_threads()
            h.loop(1)  # the result flashes OK
            h.press(key)  # inside the flash: dropped
            h.wait(FLASH_GAP)
            h.loop(2)

        self.run_all("flash", FULL, full_world, script)

    def test_todo_launch(self):
        def script(h):
            key = face_key(h, "TODO")
            if key is None:
                return
            h.press(key)
            # Passes at +0.6 s (the flash ends), +0.9 s (the 2 s home
            # refresh), +1.2 s (the capture, due at +1.0 s): the capture
            # never shares a pass with the refresh, whose renders the
            # two implementations count differently.
            h.wait(FLASH_GAP)
            h.loop(5)

        self.run_all("todo_launch", EMPTY + "; window 201 opens",
                     launch_world, script)

    # -- pages

    def test_tiling_select(self):
        def script(h):
            h.goto("tiling")
            tap(h, 0)
            tap_job(h, h.deck.key_count() - 1)

        self.run_all("tiling__select", EMPTY, empty_world, script,
                     pages=("tiling",))

    def test_tiling_timeout(self):
        def script(h):
            h.goto("tiling")
            h.press(0)
            h.wait(5.1)
            h.loop(1)

        self.run_all("tiling__timeout", EMPTY, empty_world, script,
                     pages=("tiling",))

    def test_timer_list_actions(self):
        def script(h):
            total = h.deck.key_count()
            h.goto("timer_list")
            if total - 5 > 1:
                tap_job(h, 1)
            h.loop(7)
            tap(h, total - 5)  # CLEAN DASH
            tap_job(h, total - 3)  # NEW
            tap_job(h, total - 4)  # EXPT CSV
            csv_path = S.SANDBOX / "tmp" / "export" / "timers.csv"
            self.assertEqual(
                TIMERS_CSV, csv_path.read_bytes().decode("utf-8")
            )
            tap(h, total - 2)  # RESET ALL
            tap_job(h, total - 1)  # OK
            tap(h, total - 2)  # RESET ALL
            tap(h, 0)  # CANCEL

        self.run_all("timer_list__actions", FULL, full_world, script,
                     pages=("timer_list", "timer_reset_confirm"))

    def test_sound_actions(self):
        def script(h):
            h.goto("sound")
            for key in shown_keys(h):
                tap(h, key)
                h.goto("sound")

        self.run_all("sound__actions", FULL, full_world, script,
                     pages=("sound",))

    def test_layout_actions(self):
        def script(h):
            h.goto("layout")
            if h.deck.cols < 4 or h.deck.rows < 3:
                return  # DECK TOO SMALL
            tap_job(h, row(h, 1, 1))  # SAVE 1
            tap_job(h, row(h, 2, 1))  # LOAD 1
            tap(h, row(h, 2, 2))  # LOAD 2, an empty slot
            delete = row(h, 3, 1)  # DEL 1
            if delete is None:
                return
            tap(h, delete)
            tap(h, h.deck.key_count() - 1)  # OK

        self.run_all("layout__actions", FULL, full_world, script,
                     pages=("layout", "layout_delete_confirm"))

    def test_a11y_actions(self):
        def script(h):
            h.goto("a11y")
            if h.deck.cols < 4:
                return  # DECK TOO SMALL
            # By position, not by face: at 5x3 the SCALE face covers
            # FONT+, which still answers.
            for col in (2, 2, 1, 3, 4):  # FONT+ x2, FONT-, RESET, LABELS
                key = row(h, 1, col)
                if key is not None:
                    tap(h, key)

        self.run_all("a11y__actions", EMPTY, empty_world, script,
                     pages=("a11y",))

    def _bluetooth(self, name, inputs, world, jobs=True):
        """`jobs`: the toggle and the slots of the two paired devices
        start a job; without an adapter, none does."""

        def script(h):
            cols = h.deck.cols
            h.goto("bluetooth")
            (tap_job if jobs else tap)(h, cols + 1)  # toggle
            for key in range(cols + 2, 2 * cols):  # device slots
                paired = key < cols + 4
                (tap_job if jobs and paired else tap)(h, key)

        self.run_all(name, inputs, world, script, pages=("bluetooth",))

    def test_bluetooth_on(self):
        self._bluetooth("bluetooth__on", FULL, full_world)

    def test_bluetooth_off(self):
        self._bluetooth("bluetooth__off", FULL + "; bluetooth off",
                        bt_off_world)

    def test_bluetooth_na(self):
        self._bluetooth(
            "bluetooth__na",
            FULL + "; no bluetoothctl, rfkill lists no adapter",
            bt_na_world, jobs=False,
        )

    def test_translator_record(self):
        def script(h):
            h.goto("translator")
            record = row(h, 1, 1)
            if h.deck.cols < 4 or record is None:
                return  # DECK TOO SMALL
            tap(h, record)  # REC
            tap(h, record)  # STOP
            h.run_threads()
            h.wait(FLASH_GAP)
            tap(h, row(h, 1, 2))  # STT
            tap(h, row(h, 1, 3))  # OUT
            for col in (5, 4):  # LLM backend, LLM mode
                key = row(h, 1, col)
                if key is not None:
                    tap(h, key)
            tap(h, row(h, 1, 0))  # STR on
            tap(h, row(h, 1, 0))  # STR off

        self.run_all("translator__record", EMPTY, empty_world, script,
                     pages=("translator",))

    def test_translator_vad_timeout(self):
        def script(h):
            h.goto("translator")
            record = row(h, 1, 1)
            if h.deck.cols < 4 or record is None:
                return  # DECK TOO SMALL
            S.TRANSLATOR.vad = True
            tap(h, record)  # REC, voice detection on
            S.TRANSLATOR.on_silence()
            h.loop(1)
            S.TRANSLATOR.vad = False
            tap(h, record)  # REC
            S.TRANSLATOR.timeout = 1
            h.wait(1.1)
            h.loop(1)

        self.run_all("translator__vad_timeout", EMPTY, empty_world,
                     script, pages=("translator",))

    def test_translator_history(self):
        def script(h):
            h.goto("translator_history")
            tap(h, 1)  # the newest entry
            tap(h, h.deck.key_count() - 1)  # CLEAR

        self.run_all("translator_history", EMPTY + "; 2 history entries",
                     history_world, script, pages=("translator_history",))

    def test_claude_session_actions(self):
        def script(h):
            for col in (1, 2, 3, 4):  # FOCUS, ACCEPT, SET WIN, KILL
                key = row(h, 0, col)
                if key is None:
                    continue
                h.goto("claude_session", sid="sess-a")
                tap_job(h, key)

        self.run_all("claude_session__actions", FULL, full_world, script,
                     pages=("claude_session",))

    def test_mpv_session_actions(self):
        def script(h):
            cols = h.deck.cols
            # PLAY/PAUSE, QUIT, VOL -, VOL +
            for key in (1, 2, cols, cols + 1):
                h.goto("mpv_session", pid=1)
                tap(h, key)

        self.run_all("mpv_session__actions", FULL, full_world, script,
                     pages=("mpv_session",))

    def test_todo_session_menu(self):
        def script(h):
            h.goto("todo_session", window_id="101")
            if h.deck.cols < 4:
                return  # DECK TOO SMALL
            tap(h, h.deck.cols)  # [1] First
            tap(h, 1)  # ENTER
            tap(h, 2)  # FOCUS
            h.loop(4)
            tap(h, 3)  # FORGET

        self.run_all("todo_session__menu", FULL, full_world, script,
                     pages=("todo_session",))

    def test_todo_session_closed(self):
        def script(h):
            h.goto("todo_session", window_id="101")
            h.proc.answer("gdbus ListWindows", S.gvariant_string(
                json.dumps(WINDOWS[1:])))
            # The page tick sees the window gone and goes home. The home
            # refresh is pinned on its own, once due on every schedule:
            # the passes right after the return are not.
            h.loop(1)
            h.wait(2.1)
            h.loop(1)

        self.run_all("todo_session__closed", FULL + "; window 101 closes",
                     full_world, script, pages=("todo_session",))


class PackagePages(Scenarios, unittest.TestCase):
    make_target = staticmethod(S.PackageTarget)


class PackageDashboardTap(unittest.TestCase):
    """A dashboard tap opens what the key showed at the last render,
    where the single file recomputed the tile from a fresh read: the
    one change of behaviour of the package, so no golden pins it."""

    def test_tap_opens_the_session_the_key_showed(self):
        with S.Harness(S.PackageTarget(), 5, 3) as h:
            full_world(h)
            h.boot()
            tiles = [
                k for k, f in enumerate(h.deck.rendering())
                if f and f[0] in DASHBOARD
            ]
            key = face_key(h, "Demo\nstream")
            self.assertEqual(tiles[0], key)
            # A newer player appears after the render: a fresh read
            # lists it first, the key still shows pid 1.
            h.write_json(
                "STATE/erplibre-home/mpv/later.json",
                {"pid": os.getpid(), "title": "Later stream",
                 "url": "https://example.org/later",
                 "started_at": 1799999900000},
            )
            mpv = sys.modules["erplibre_streamdeck.plugins.mpv_sessions"]
            self.assertEqual(os.getpid(), mpv.load_sessions()[0]["pid"])
            h.press(key)
            h.check_clean(self)
            self.assertEqual("mpv_session", h.target.page())
            self.assertEqual(1, h.target.kernel.state("mpv_sessions").pid)


class GoldenWriterTest(unittest.TestCase):
    RUNS = {"3x2": [{"do": "boot", "page": "idle", "screen": ["é"]}]}

    def test_update_writes_then_compare_reads(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            S, "GOLDEN_DIR", Path(tmp)
        ):
            env = {S.GOLDEN_ENV: S.GOLDEN_UPDATE}
            with mock.patch.dict(os.environ, env):
                S.check_golden(self, "w", {"k": 1}, self.RUNS)
            text = S.golden_path("w").read_text(encoding="utf-8")
            self.assertEqual(
                json.dumps(
                    {"format": 1, "inputs": {"k": 1},
                     "geometries": self.RUNS},
                    indent=1, ensure_ascii=False, sort_keys=True,
                ) + "\n",
                text,
            )
            with mock.patch.dict(os.environ, {S.GOLDEN_ENV: ""}):
                S.check_golden(self, "w", {"k": 1}, self.RUNS)


if __name__ == "__main__":
    unittest.main()
