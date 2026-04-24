#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Window Tiler — tile windows via Stream Deck.

Press TILE to enter tiling mode. Grid appears on the deck.
Press first corner, then second corner. The focused window is
tiled to that region via D-Bus (streamdeck-tiler gnome extension).

Press TIMER to list timers from the tracker@aliakseiz.github.com
extension and start/stop them.
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

GAME_META = {
    "name": "Window Tiler",
    "category": "sim",
    "multiplayer": False,
    "sdplus": False,
    "description": "Tile windows on a grid. Pick two corners to place.",
    "icon": "tiler"
}

COLOR_EMPTY = (20, 20, 30)
COLOR_GRID = (40, 60, 100)
COLOR_SELECTED = (0, 180, 255)
COLOR_PREVIEW = (0, 120, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_TIMER_TITLE = (120, 60, 0)
COLOR_TIMER_RUNNING = (0, 160, 40)
COLOR_TIMER_PAUSED = (50, 70, 110)
COLOR_BACK = (60, 60, 60)
COLOR_REFRESH = (80, 80, 110)
COLOR_NEW = (140, 80, 160)
COLOR_RESET = (180, 100, 0)
COLOR_CONFIRM = (0, 180, 40)
COLOR_CANCEL = (180, 0, 0)
COLOR_EXPORT = (0, 120, 140)
COLOR_DEV_RELOAD = (160, 40, 120)
COLOR_SOUND_TITLE = (100, 60, 180)
COLOR_VOL = (40, 120, 200)
COLOR_MIC = (150, 100, 50)
COLOR_MUTE_ON = (200, 0, 0)
COLOR_MUTE_OFF = (0, 180, 40)

VOL_STEP_PCT = 5
COLOR_ACTIVE = (255, 200, 0)
COLOR_OK = (0, 200, 60)
COLOR_ERR = (200, 0, 0)

MODE_IDLE = "idle"
MODE_TILING = "tiling"
MODE_TIMER_LIST = "timer_list"
MODE_TIMER_RESET_CONFIRM = "timer_reset_confirm"
MODE_SOUND = "sound"

WPCTL_SINK = "@DEFAULT_AUDIO_SINK@"
WPCTL_SOURCE = "@DEFAULT_AUDIO_SOURCE@"

DBUS_DEST = "org.gnome.Shell"
DBUS_PATH = "/org/gnome/Shell/Extensions/StreamDeckTiler"
DBUS_IFACE = "org.gnome.Shell.Extensions.StreamDeckTiler"


def _tile_via_dbus(grid_cols, grid_rows, c1, r1, c2, r2):
    """Call the GNOME extension to tile the focused window."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.TileWindow",
                str(grid_cols), str(grid_rows),
                str(c1), str(r1), str(c2), str(r2),
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            return True
        print(f"Tiler dbus: {result.stdout} {result.stderr}")
        return False
    except Exception as e:
        print(f"Tiler dbus error: {e}")
        return False


def _check_dbus_available():
    """Check if the streamdeck-tiler extension is available."""
    try:
        result = subprocess.run(
            [
                "gdbus", "introspect", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
            ],
            capture_output=True, text=True, timeout=3,
        )
        return "TileWindow" in result.stdout
    except Exception:
        return False


def _parse_gdbus_string_tuple(output):
    """Extract the string from gdbus output of form ('...',).

    GVariant single-quoted strings only need to escape backslash and
    single quote. Double quotes (from JSON content) pass through.
    """
    s = output.strip()
    if not (s.startswith("('") and s.endswith("',)")):
        return None
    inner = s[2:-3]
    # Unescape \\ and \' — placeholder avoids double substitution
    return (
        inner.replace("\\\\", "\x00")
        .replace("\\'", "'")
        .replace("\x00", "\\")
    )


def _list_tracker_timers():
    """Call the extension to list tracker timers. Returns list of dicts."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ListTrackerTimers",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            print(f"Timer list dbus: {result.stderr}")
            return []
        payload = _parse_gdbus_string_tuple(result.stdout)
        if not payload:
            return []
        return json.loads(payload)
    except Exception as e:
        print(f"Timer list error: {e}")
        return []


def _toggle_tracker_timer(timer_id):
    """Call the extension to toggle a tracker timer by id."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ToggleTrackerTimer",
                timer_id,
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            return True
        print(f"Timer toggle dbus: {result.stdout} {result.stderr}")
        return False
    except Exception as e:
        print(f"Timer toggle error: {e}")
        return False


def _add_tracker_timer():
    """Call the extension to add a new tracker timer and open edit mode.

    Returns the new timer id on success, empty string on failure.
    """
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.AddTrackerTimer",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            print(f"Timer add dbus: {result.stderr}")
            return ""
        payload = _parse_gdbus_string_tuple(result.stdout)
        return payload or ""
    except Exception as e:
        print(f"Timer add error: {e}")
        return ""


def _reset_all_tracker_timers():
    """Call the extension to reset every tracker timer to 0 elapsed."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ResetAllTrackerTimers",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            return True
        print(f"Timer reset dbus: {result.stdout} {result.stderr}")
        return False
    except Exception as e:
        print(f"Timer reset error: {e}")
        return False


def _wpctl_available():
    return shutil.which("wpctl") is not None


def _wpctl_get(target):
    """Return (volume_percent, muted) for target or (None, None) on error."""
    try:
        r = subprocess.run(
            ["wpctl", "get-volume", target],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode != 0:
            return None, None
        # Format: "Volume: 0.50" or "Volume: 0.50 [MUTED]"
        parts = r.stdout.strip().split()
        if len(parts) < 2:
            return None, None
        vol = float(parts[1])
        muted = len(parts) > 2 and "MUTED" in parts[2]
        return int(round(vol * 100)), muted
    except Exception as e:
        print(f"wpctl get error: {e}")
        return None, None


def _wpctl_volume_delta(target, delta_pct):
    sign = "+" if delta_pct > 0 else "-"
    try:
        r = subprocess.run(
            ["wpctl", "set-volume", "--limit", "1.5",
             target, f"{abs(delta_pct)}%{sign}"],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-volume error: {e}")
        return False


def _wpctl_mute_toggle(target):
    try:
        r = subprocess.run(
            ["wpctl", "set-mute", target, "toggle"],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-mute error: {e}")
        return False


def _hot_reload_extension():
    """Call the extension's HotReload D-Bus method. Returns True on success."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.HotReload",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"HotReload dbus: {result.stderr}")
            return False
        payload = _parse_gdbus_string_tuple(result.stdout)
        return bool(payload)
    except Exception as e:
        print(f"HotReload error: {e}")
        return False


def _ask_save_path():
    """Prompt the user for a file path via zenity. Returns '' if cancelled."""
    if not shutil.which("zenity"):
        print("zenity not installed — cannot open file dialog.")
        return ""
    try:
        result = subprocess.run(
            [
                "zenity", "--file-selection", "--save",
                "--confirm-overwrite",
                "--file-filter=CSV files | *.csv",
                "--filename=timers.csv",
            ],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            return ""  # cancelled
        path = result.stdout.strip()
        if path and not path.lower().endswith(".csv"):
            path += ".csv"
        return path
    except Exception as e:
        print(f"File dialog error: {e}")
        return ""


def _export_timers_csv(path, timers):
    """Write the given timers list to a CSV at path. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "seconds", "time"])
            for t in timers:
                name = t.get("name") or ""
                elapsed = int(t.get("elapsed") or 0)
                hh = elapsed // 3600
                mm = (elapsed % 3600) // 60
                ss = elapsed % 60
                writer.writerow([name, elapsed, f"{hh:02d}:{mm:02d}:{ss:02d}"])
        return True
    except Exception as e:
        print(f"CSV write error: {e}")
        return False


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 2 else 14 if len(text) <= 4 else 11
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((w - tw) // 2 + 1, (h - th) // 2 + 1),
            text, fill=(0, 0, 0), font=font,
        )
        draw.text(
            ((w - tw) // 2, (h - th) // 2),
            text, fill=(255, 255, 255), font=font,
        )
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


class Tiler:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        # Grid = full deck (each button = one grid cell)
        self.grid_cols = cols
        self.grid_rows = rows
        # State
        self.mode = MODE_IDLE
        self.corner1 = None  # (col, row)
        self.corner2 = None
        self.last_result = None  # "ok" or "err"
        self.result_time = 0
        self.dbus_ok = _check_dbus_available()
        # Timer state
        self.timers = []  # list of dicts from _list_tracker_timers
        # Map: key index -> timer id (for timer list mode)
        self.timer_key_map = {}
        # Idle entry points
        self._compute_idle_buttons()

    def _compute_idle_buttons(self):
        """Pick keys for the TILE, TIMER, DEV RELOAD and SOUND entry buttons."""
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        dev_reload_pos = None
        sound_pos = None
        if self.cols >= 5:
            tile_pos = (mid_c - 1, mid_r)
            timer_pos = (mid_c, mid_r)
            dev_reload_pos = (mid_c + 1, mid_r)
            sound_pos = (mid_c + 2, mid_r)
        elif self.cols >= 3:
            tile_pos = (mid_c - 1, mid_r)
            timer_pos = (mid_c, mid_r)
            dev_reload_pos = (mid_c + 1, mid_r)
        elif self.cols >= 2:
            tile_pos = (max(mid_c - 1, 0), mid_r)
            timer_pos = (mid_c, mid_r)
        elif self.rows >= 2:
            tile_pos = (0, mid_r)
            timer_pos = (0, min(mid_r + 1, self.rows - 1))
            if tile_pos == timer_pos:
                tile_pos = (0, max(mid_r - 1, 0))
        else:
            tile_pos = (0, 0)
            timer_pos = (0, 0)  # single-key deck: TILE only
        self.tile_key = tile_pos[1] * self.cols + tile_pos[0]
        self.timer_key = timer_pos[1] * self.cols + timer_pos[0]
        self.dev_reload_key = (
            dev_reload_pos[1] * self.cols + dev_reload_pos[0]
            if dev_reload_pos else -1
        )
        self.sound_key = (
            sound_pos[1] * self.cols + sound_pos[0]
            if sound_pos else -1
        )
        self._compute_sound_buttons()

    def _compute_sound_buttons(self):
        """Layout for sound mode. Requires >= 4 cols and >= 3 rows."""
        if self.cols < 4 or self.rows < 3:
            self.sound_keys = None
            return
        self.sound_keys = {
            "back": 0,
            "vol_down": self.cols + 1,
            "vol_up": self.cols + 2,
            "out_mute": self.cols + 3,
            "mic_down": 2 * self.cols + 1,
            "mic_up": 2 * self.cols + 2,
            "mic_mute": 2 * self.cols + 3,
        }

    # ---------- Key handling ----------

    def handle_key(self, key, state):
        if not state:
            return

        # Block input during result flash
        if self.last_result and time.monotonic() - self.result_time < 1.5:
            return

        if self.mode == MODE_IDLE:
            self._handle_idle_key(key)
        elif self.mode == MODE_TILING:
            self._handle_tiling_key(key)
        elif self.mode == MODE_TIMER_LIST:
            self._handle_timer_list_key(key)
        elif self.mode == MODE_TIMER_RESET_CONFIRM:
            self._handle_timer_reset_confirm_key(key)
        elif self.mode == MODE_SOUND:
            self._handle_sound_key(key)

    def _handle_idle_key(self, key):
        if key == self.dev_reload_key and self.dev_reload_key >= 0:
            ok = _hot_reload_extension()
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        if key == self.sound_key and self.sound_key >= 0:
            self.mode = MODE_SOUND
            self.render()
            return
        if key == self.timer_key and self.timer_key != self.tile_key:
            self._enter_timer_mode()
        elif key == self.tile_key:
            self.mode = MODE_TILING
            self.corner1 = None
            self.corner2 = None
            self.last_result = None
            self.render()
        else:
            # Legacy behavior: any key also enters tiling mode
            self.mode = MODE_TILING
            self.corner1 = None
            self.corner2 = None
            self.last_result = None
            self.render()

    def _handle_tiling_key(self, key):
        col = key % self.cols
        row = key // self.cols
        if self.corner1 is None:
            self.corner1 = (col, row)
            self.render()
            return
        self.corner2 = (col, row)
        c1 = min(self.corner1[0], self.corner2[0])
        r1 = min(self.corner1[1], self.corner2[1])
        c2 = max(self.corner1[0], self.corner2[0])
        r2 = max(self.corner1[1], self.corner2[1])
        ok = _tile_via_dbus(
            self.grid_cols, self.grid_rows, c1, r1, c2, r2
        )
        self.last_result = "ok" if ok else "err"
        self.result_time = time.monotonic()
        self.mode = MODE_IDLE
        self.corner1 = None
        self.corner2 = None
        self.render()

    def _handle_timer_list_key(self, key):
        # Layout: 0=BACK, total-4=EXPORT, total-3=NEW, total-2=RESET, total-1=RFSH
        if key == 0:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == self.total_keys - 1:
            self._refresh_timers()
            self.render()
            return
        if key == self.total_keys - 2:
            self.mode = MODE_TIMER_RESET_CONFIRM
            self.render()
            return
        if key == self.total_keys - 3:
            new_id = _add_tracker_timer()
            if new_id:
                self._refresh_timers()
                self.render()
            else:
                self.last_result = "err"
                self.result_time = time.monotonic()
                self.render()
            return
        if key == self.total_keys - 4:
            self._handle_export()
            return
        timer_id = self.timer_key_map.get(key)
        if not timer_id:
            return
        ok = _toggle_tracker_timer(timer_id)
        if ok:
            self._refresh_timers()
            self.render()
        else:
            self.last_result = "err"
            self.result_time = time.monotonic()
            self.render()

    def _handle_sound_key(self, key):
        sk = self.sound_keys
        if not sk:
            # Unsupported deck size: any key returns to idle
            self.mode = MODE_IDLE
            self.render()
            return
        if key == sk["back"]:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == sk["vol_down"]:
            _wpctl_volume_delta(WPCTL_SINK, -VOL_STEP_PCT)
        elif key == sk["vol_up"]:
            _wpctl_volume_delta(WPCTL_SINK, VOL_STEP_PCT)
        elif key == sk["out_mute"]:
            _wpctl_mute_toggle(WPCTL_SINK)
        elif key == sk["mic_down"]:
            _wpctl_volume_delta(WPCTL_SOURCE, -VOL_STEP_PCT)
        elif key == sk["mic_up"]:
            _wpctl_volume_delta(WPCTL_SOURCE, VOL_STEP_PCT)
        elif key == sk["mic_mute"]:
            _wpctl_mute_toggle(WPCTL_SOURCE)
        else:
            return
        self.render()

    def _handle_timer_reset_confirm_key(self, key):
        if key == 0:
            # Cancel
            self.mode = MODE_TIMER_LIST
            self.render()
            return
        if key == self.total_keys - 1:
            # Confirm
            ok = _reset_all_tracker_timers()
            self.mode = MODE_TIMER_LIST
            if ok:
                self._refresh_timers()
                self.last_result = "ok"
            else:
                self.last_result = "err"
            self.result_time = time.monotonic()
            self.render()
            return
        # Other keys: ignore (force explicit choice)

    def _enter_timer_mode(self):
        self.mode = MODE_TIMER_LIST
        self._refresh_timers()
        self.render()

    def _handle_export(self):
        # zenity blocks; freshen list before opening dialog for accurate export
        self._refresh_timers()
        path = _ask_save_path()
        if not path:
            # User cancelled — no flash, stay on list
            self.render()
            return
        ok = _export_timers_csv(path, self.timers)
        self.last_result = "ok" if ok else "err"
        self.result_time = time.monotonic()
        self.render()

    def _refresh_timers(self):
        self.timers = _list_tracker_timers()
        self.timer_key_map = {}
        # Keys for timers: 1 .. total-5
        # (skip BACK=0, EXPORT=total-4, NEW=total-3, RESET=total-2, RFSH=total-1)
        usable = list(range(1, self.total_keys - 4))
        for idx, timer in enumerate(self.timers):
            if idx >= len(usable):
                break
            self.timer_key_map[usable[idx]] = timer.get("id")

    # ---------- Rendering ----------

    def render(self):
        # Result flash
        if self.last_result:
            elapsed = time.monotonic() - self.result_time
            if elapsed < 1.5:
                color = COLOR_OK if self.last_result == "ok" else COLOR_ERR
                label = "OK!" if self.last_result == "ok" else "ERR"
                for key in range(self.total_keys):
                    set_key(self.deck, key, color, label)
                return
            self.last_result = None

        if self.mode == MODE_IDLE:
            self._render_idle()
        elif self.mode == MODE_TILING:
            self._render_tiling()
        elif self.mode == MODE_TIMER_LIST:
            self._render_timer_list()
        elif self.mode == MODE_TIMER_RESET_CONFIRM:
            self._render_timer_reset_confirm()
        elif self.mode == MODE_SOUND:
            self._render_sound()

    def _render_idle(self):
        for key in range(self.total_keys):
            if key == self.tile_key:
                set_key(self.deck, key, COLOR_TITLE, "TILE")
            elif key == self.timer_key and self.timer_key != self.tile_key:
                set_key(self.deck, key, COLOR_TIMER_TITLE, "TIMER")
            elif key == self.dev_reload_key and self.dev_reload_key >= 0:
                set_key(self.deck, key, COLOR_DEV_RELOAD, "DEV\nRELOAD")
            elif key == self.sound_key and self.sound_key >= 0:
                set_key(self.deck, key, COLOR_SOUND_TITLE, "SOUND")
            elif key == 0 and not self.dbus_ok:
                set_key(self.deck, key, COLOR_ERR, "NO\nEXT")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_sound(self):
        sk = self.sound_keys
        if not sk:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, "BACK")
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, "DECK\nTOO\nSMALL")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        out_vol, out_muted = _wpctl_get(WPCTL_SINK)
        mic_vol, mic_muted = _wpctl_get(WPCTL_SOURCE)

        labels = {
            sk["back"]: (COLOR_BACK, "BACK"),
            sk["vol_down"]: (COLOR_VOL, f"VOL\n-{VOL_STEP_PCT}%"),
            sk["vol_up"]: (COLOR_VOL, f"VOL\n+{VOL_STEP_PCT}%"),
            sk["mic_down"]: (COLOR_MIC, f"MIC\n-{VOL_STEP_PCT}%"),
            sk["mic_up"]: (COLOR_MIC, f"MIC\n+{VOL_STEP_PCT}%"),
        }
        if out_muted:
            labels[sk["out_mute"]] = (COLOR_MUTE_ON, "OUT\nMUTE")
        else:
            out_lbl = f"OUT\n{out_vol}%" if out_vol is not None else "OUT"
            labels[sk["out_mute"]] = (COLOR_MUTE_OFF, out_lbl)
        if mic_muted:
            labels[sk["mic_mute"]] = (COLOR_MUTE_ON, "MIC\nMUTE")
        else:
            mic_lbl = f"MIC\n{mic_vol}%" if mic_vol is not None else "MIC"
            labels[sk["mic_mute"]] = (COLOR_MUTE_OFF, mic_lbl)

        for key in range(self.total_keys):
            if key in labels:
                color, label = labels[key]
                set_key(self.deck, key, color, label)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_tiling(self):
        preview = set()
        if self.corner1:
            preview.add(self.corner1)
        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            if (c, r) == self.corner1:
                set_key(self.deck, key, COLOR_SELECTED, "1")
            elif (c, r) in preview:
                set_key(self.deck, key, COLOR_PREVIEW, "")
            else:
                label = f"{c},{r}"
                set_key(self.deck, key, COLOR_GRID, label)

    def _render_timer_list(self):
        for key in range(self.total_keys):
            if key == 0:
                set_key(self.deck, key, COLOR_BACK, "BACK")
                continue
            if key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_REFRESH, "RFSH")
                continue
            if key == self.total_keys - 2:
                set_key(self.deck, key, COLOR_RESET, "RESET\nALL")
                continue
            if key == self.total_keys - 3:
                set_key(self.deck, key, COLOR_NEW, "NEW")
                continue
            if key == self.total_keys - 4:
                set_key(self.deck, key, COLOR_EXPORT, "EXPT\nCSV")
                continue
            timer_id = self.timer_key_map.get(key)
            if not timer_id:
                # Empty slot — show hint if no timers exist at all
                if not self.timers and key == 1:
                    set_key(self.deck, key, COLOR_EMPTY, "NO\nTIMERS")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
                continue
            timer = next(
                (t for t in self.timers if t.get("id") == timer_id), None
            )
            if not timer:
                set_key(self.deck, key, COLOR_EMPTY, "")
                continue
            color = (
                COLOR_TIMER_RUNNING if timer.get("running")
                else COLOR_TIMER_PAUSED
            )
            label = _label_for_timer(timer)
            set_key(self.deck, key, color, label)

    def _render_timer_reset_confirm(self):
        # Layout: key 0 = CANCEL (red), last key = CONFIRM (green)
        # Center row shows "RESET ALL?" hint split across 2 cells if possible
        mid_key = self.total_keys // 2
        for key in range(self.total_keys):
            if key == 0:
                set_key(self.deck, key, COLOR_CANCEL, "CANCEL")
            elif key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_CONFIRM, "OK")
            elif key == mid_key - 1 and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, "RESET")
            elif key == mid_key and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, "ALL?")
            elif key == mid_key:
                set_key(self.deck, key, COLOR_EMPTY, "RESET\nALL?")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def loop(self):
        """Refresh loop: clear result flash + refresh timer list."""
        last_timer_refresh = 0
        while self.running and self.deck.is_open():
            now = time.monotonic()
            with self.lock:
                if self.last_result:
                    elapsed = now - self.result_time
                    if elapsed >= 1.5:
                        self.render()
                elif self.mode == MODE_TIMER_LIST:
                    # Auto-refresh every 2s to update elapsed time labels
                    if now - last_timer_refresh >= 2.0:
                        self._refresh_timers()
                        self.render()
                        last_timer_refresh = now
            time.sleep(0.3)


def _label_for_timer(timer):
    """Build a short 2-line label: first word of name + mm:ss."""
    name = timer.get("name") or "?"
    first = name.split()[0] if name.split() else name
    if len(first) > 6:
        first = first[:6]
    elapsed = int(timer.get("elapsed") or 0)
    mm = elapsed // 60
    ss = elapsed % 60
    return f"{first}\n{mm:02d}:{ss:02d}"


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Window Tiler on {deck.deck_type()} ({cols}x{rows})")

    dbus_ok = _check_dbus_available()
    if dbus_ok:
        print("D-Bus tiler extension detected!")
    else:
        print("WARNING: streamdeck-tiler extension not found.")
        print("Install: re-login to GNOME to activate the extension.")

    print("Press TILE to enter tiling mode (first corner, second corner).")
    print("Press TIMER to list and toggle tracker timers.")

    game = Tiler(deck)
    game.render()

    def key_cb(d, k, s):
        with game.lock:
            game.handle_key(k, s)

    deck.set_key_callback(key_cb)

    t = threading.Thread(target=game.loop, daemon=True)
    t.start()

    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        with deck:
            deck.reset()
            deck.close()


if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
