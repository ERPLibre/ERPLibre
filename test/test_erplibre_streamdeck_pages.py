#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Goldens of every deck page, at the four deck geometries.

Each scenario boots the deck program on a `FakeDeck`, in a world of
invented inputs (state files, D-Bus, wpctl, bluetoothctl answers), runs
its steps and compares what every key shows, every command the program
ran and the state files after each step with
`test/fixtures/erplibre_streamdeck/<name>.json`.

`MonolithPages` runs the single file `erplibre_streamdeck.py`, the
reference: `STREAMDECK_GOLDEN=update` rewrites the goldens from it.
`PackagePages` runs the package against the same goldens; a scenario whose
page has no plugin yet is skipped, and a scenario that starts from the
home screen waits for every repository plugin.

A page scenario reaches its page with `goto` right after boot, never by a
home press: the home screen of an incomplete package differs. The
`home__*` scenarios pin the passage from the home screen to each page.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

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
NOEXT = "NOEXT: EMPTY, introspect without TileWindow until 5 s"


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
         "url": "https://example.org/demo", "started_at": 1799999000},
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

    def run_all(self, name, inputs, world, script, pages=(),
                home_based=False):
        runs, complete = {}, True
        for cols, rows in S.GEOMETRIES:
            with S.Harness(self.make_target(), cols, rows) as h:
                world(h)
                h.boot()
                missing = [p for p in pages if not h.target.has_page(p)]
                if missing:
                    self.skipTest(f"no plugin yet for {missing}")
                complete = complete and h.target.complete()
                if home_based and not complete:
                    self.skipTest("home screen incomplete")
                script(h)
                h.check_clean(self)
                runs[f"{cols}x{rows}"] = h.steps
        S.check_golden(self, name, inputs, runs, partial=not complete)

    # -- home screen

    def test_home_empty(self):
        self.run_all("home__empty", EMPTY, empty_world,
                     lambda h: h.loop(1), home_based=True)

    def test_home_full(self):
        def script(h):
            h.loop(1)
            h.wait(2.1)
            h.loop(1)

        self.run_all("home__full", FULL, full_world, script,
                     home_based=True)

    def test_home_full_fr(self):
        self.run_all("home__full_fr", FULL + "; lang fr", full_fr_world,
                     lambda h: h.loop(1), home_based=True)

    def test_home_noext(self):
        def script(h):
            start = h.clock.now

            def on_poll():
                if h.clock.now - start >= 5.0:
                    h.proc.answer("gdbus introspect", INTROSPECT_OK)

            h.loop(18, on_poll=on_poll)

        self.run_all("home__noext", NOEXT, noext_world, script,
                     home_based=True)

    def test_home_presses(self):
        def script(h):
            for label in HOME_LABELS:
                key = face_key(h, label)
                if key is None:
                    continue
                tap(h, key)
                h.goto("idle")
            tap(h, face_key(h, "MIC\nOFF"))
            key = face_key(h, "*\n1")
            if key is not None:
                tap(h, key)

        self.run_all("home__presses", FULL, full_world, script,
                     home_based=True)

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

        self.run_all("home__dashboard", FULL, full_world, script,
                     home_based=True)

    def test_flash(self):
        def script(h):
            key = face_key(h, "DEV\nRELOAD")
            h.press(key)
            h.press(key)
            h.wait(FLASH_GAP)
            h.loop(2)

        self.run_all("flash", FULL, full_world, script, home_based=True)

    def test_todo_launch(self):
        def script(h):
            key = face_key(h, "TODO")
            if key is None:
                return
            h.press(key)
            h.wait(1.1)
            h.loop(5)

        self.run_all("todo_launch", EMPTY + "; window 201 opens",
                     launch_world, script, home_based=True)

    # -- pages

    def test_tiling_select(self):
        def script(h):
            h.goto("tiling")
            tap(h, 0)
            tap(h, h.deck.key_count() - 1)

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
                tap(h, 1)
            h.loop(7)
            tap(h, total - 5)  # CLEAN DASH
            tap(h, total - 3)  # NEW
            tap(h, total - 4)  # EXPT CSV
            csv_path = S.SANDBOX / "tmp" / "export" / "timers.csv"
            self.assertEqual(
                TIMERS_CSV, csv_path.read_bytes().decode("utf-8")
            )
            tap(h, total - 2)  # RESET ALL
            tap(h, total - 1)  # OK
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
            tap(h, row(h, 1, 1))  # SAVE 1
            tap(h, row(h, 2, 1))  # LOAD 1
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

    def _bluetooth(self, name, inputs, world):
        def script(h):
            cols = h.deck.cols
            h.goto("bluetooth")
            tap(h, cols + 1)  # toggle
            for key in range(cols + 2, 2 * cols):  # device slots
                tap(h, key)

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
            bt_na_world,
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
                tap(h, key)

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
            h.loop(4)

        self.run_all("todo_session__closed", FULL + "; window 101 closes",
                     full_world, script, pages=("todo_session",))


@unittest.skipUnless(S.MONOLITH.exists(), "single file gone")
class MonolithPages(Scenarios, unittest.TestCase):
    target_kind = "monolith"
    make_target = staticmethod(S.MonolithTarget)


@unittest.skipUnless((S.PACKAGE / "app.py").exists(), "no package yet")
class PackagePages(Scenarios, unittest.TestCase):
    target_kind = "package"
    make_target = staticmethod(S.PackageTarget)


if __name__ == "__main__":
    unittest.main()
