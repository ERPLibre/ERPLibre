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
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

import translator as _translator

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
COLOR_LAYOUT_TITLE = (80, 150, 80)
COLOR_SAVE = (180, 140, 0)
COLOR_LOAD_FILLED = (0, 150, 80)
COLOR_LOAD_EMPTY = (60, 60, 60)
COLOR_A11Y_TITLE = (180, 160, 60)
COLOR_FONT_STEP = (140, 110, 60)
COLOR_FONT_RESET = (80, 60, 160)
COLOR_BT_TITLE = (0, 100, 200)
COLOR_BT_ON = (0, 150, 220)
COLOR_BT_OFF = (60, 60, 60)
COLOR_BT_NA = (100, 40, 40)
COLOR_TR_TITLE = (160, 90, 200)
COLOR_REC_ON = (200, 30, 30)
COLOR_REC_OFF = (60, 60, 60)
COLOR_BACKEND = (90, 130, 80)
COLOR_OUTPUT = (50, 110, 150)

VOL_STEP_PCT = 5

LAYOUT_DIR = os.path.expanduser("~/.config/streamdeck-tiler")
LAYOUT_FILE = os.path.join(LAYOUT_DIR, "layouts.json")
SETTINGS_FILE = os.path.join(LAYOUT_DIR, "settings.json")
NUM_LAYOUT_SLOTS = 3

FONT_SCALE_MIN = 0.6
FONT_SCALE_MAX = 2.5
FONT_SCALE_STEP = 0.1
FONT_SCALE_DEFAULT = 1.0

_font_scale = FONT_SCALE_DEFAULT
_show_labels = False  # show text labels on buttons that have icons

GALLERY_RESTART_URL = "http://localhost:8042/api/restart"
COLOR_ACTIVE = (255, 200, 0)
COLOR_OK = (0, 200, 60)
COLOR_ERR = (200, 0, 0)

MODE_IDLE = "idle"
MODE_TILING = "tiling"
MODE_TIMER_LIST = "timer_list"
MODE_TIMER_RESET_CONFIRM = "timer_reset_confirm"
MODE_SOUND = "sound"
MODE_LAYOUT = "layout"
MODE_LAYOUT_DELETE_CONFIRM = "layout_delete_confirm"
MODE_A11Y = "a11y"
MODE_BLUETOOTH = "bluetooth"
MODE_TRANSLATOR = "translator"

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


def _bt_powered():
    """Return True/False/None. None = unable to determine."""
    if shutil.which("bluetoothctl"):
        try:
            r = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if line.strip().startswith("Powered:"):
                        return line.split(":", 1)[1].strip() == "yes"
        except Exception as e:
            print(f"bluetoothctl show error: {e}")
    if shutil.which("rfkill"):
        try:
            r = subprocess.run(
                ["rfkill", "list", "bluetooth"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout.strip():
                for line in r.stdout.splitlines():
                    if line.strip().startswith("Soft blocked:"):
                        return line.split(":", 1)[1].strip() == "no"
        except Exception as e:
            print(f"rfkill list error: {e}")
    return None


def _bt_set_power(on):
    """Toggle bluetooth power. Returns True on success."""
    if shutil.which("bluetoothctl"):
        try:
            r = subprocess.run(
                ["bluetoothctl", "power", "on" if on else "off"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                return True
        except Exception as e:
            print(f"bluetoothctl power error: {e}")
    if shutil.which("rfkill"):
        try:
            r = subprocess.run(
                ["rfkill", "unblock" if on else "block", "bluetooth"],
                capture_output=True, text=True, timeout=3,
            )
            return r.returncode == 0
        except Exception as e:
            print(f"rfkill error: {e}")
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


def _layouts_load():
    try:
        with open(LAYOUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"slots": {}}


def _layouts_save(data):
    os.makedirs(LAYOUT_DIR, exist_ok=True)
    with open(LAYOUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _settings_load():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _settings_save(data):
    os.makedirs(LAYOUT_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _init_font_scale():
    """Load persisted font scale from settings.json on startup."""
    global _font_scale, _show_labels
    data = _settings_load()
    try:
        val = float(data.get("font_scale", FONT_SCALE_DEFAULT))
        _font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, val))
    except (ValueError, TypeError):
        _font_scale = FONT_SCALE_DEFAULT
    _show_labels = bool(data.get("show_labels", False))


def _set_font_scale(scale):
    """Clamp, store in module global, and persist."""
    global _font_scale
    _font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))
    data = _settings_load()
    data["font_scale"] = round(_font_scale, 2)
    _settings_save(data)


def _toggle_show_labels():
    global _show_labels
    _show_labels = not _show_labels
    data = _settings_load()
    data["show_labels"] = _show_labels
    _settings_save(data)


def _list_windows_dbus():
    """Query the extension for all live windows. Returns list of dicts."""
    try:
        r = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ListWindows",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode != 0:
            print(f"ListWindows dbus: {r.stderr}")
            return []
        payload = _parse_gdbus_string_tuple(r.stdout)
        return json.loads(payload) if payload else []
    except Exception as e:
        print(f"ListWindows error: {e}")
        return []


def _apply_layout_dbus(windows):
    """Apply a list of window records via D-Bus. Returns matched count."""
    try:
        payload = json.dumps(windows)
        r = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ApplyLayout",
                payload,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            print(f"ApplyLayout dbus: {r.stderr}")
            return 0
        m = re.search(r"\((\d+),\)", r.stdout.strip())
        return int(m.group(1)) if m else 0
    except Exception as e:
        print(f"ApplyLayout error: {e}")
        return 0


def _save_layout_slot(slot_id):
    windows = _list_windows_dbus()
    if not windows:
        return False
    data = _layouts_load()
    data.setdefault("slots", {})[str(slot_id)] = {
        "saved_at": datetime.now().strftime("%H:%M"),
        "count": len(windows),
        "windows": windows,
    }
    _layouts_save(data)
    return True


def _load_layout_slot(slot_id):
    data = _layouts_load()
    slot = data.get("slots", {}).get(str(slot_id))
    if not slot:
        return False
    matched = _apply_layout_dbus(slot.get("windows") or [])
    return matched > 0


def _delete_layout_slot(slot_id):
    data = _layouts_load()
    slots = data.get("slots", {})
    if str(slot_id) not in slots:
        return False
    del slots[str(slot_id)]
    _layouts_save(data)
    return True


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


_ICON_WHITE = (255, 255, 255)
_ICON_RED = (220, 30, 30)


def _icon_mic(draw, w, h, muted=False):
    cx = w / 2
    cap_w = w * 0.30
    cap_h = h * 0.42
    cap_box = (cx - cap_w / 2, h * 0.18, cx + cap_w / 2, h * 0.18 + cap_h)
    draw.rounded_rectangle(cap_box, radius=cap_w / 2, fill=_ICON_WHITE)
    stroke = max(2, int(w * 0.05))
    draw.line((cx, h * 0.62, cx, h * 0.78), fill=_ICON_WHITE, width=stroke)
    arc_box = (w * 0.25, h * 0.50, w * 0.75, h * 0.78)
    draw.arc(arc_box, 0, 180, fill=_ICON_WHITE, width=stroke)
    draw.line(
        (w * 0.32, h * 0.78, w * 0.68, h * 0.78),
        fill=_ICON_WHITE, width=stroke,
    )
    if muted:
        draw.line(
            (w * 0.15, h * 0.85, w * 0.85, h * 0.15),
            fill=_ICON_RED, width=max(3, int(w * 0.08)),
        )


def _icon_mic_off(draw, w, h):
    _icon_mic(draw, w, h, muted=True)


def _icon_tile(draw, w, h):
    cells = [(0.18, 0.18), (0.55, 0.18), (0.18, 0.55), (0.55, 0.55)]
    cw = w * 0.27
    for x, y in cells:
        draw.rectangle(
            (w * x, h * y, w * x + cw, h * y + cw),
            fill=_ICON_WHITE,
        )


def _icon_timer(draw, w, h):
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.36
    box = (cx - r, cy - r, cx + r, cy + r)
    stroke = max(2, int(w * 0.05))
    draw.ellipse(box, outline=_ICON_WHITE, width=stroke)
    draw.line((cx, cy, cx, cy - r * 0.7), fill=_ICON_WHITE, width=stroke)
    draw.line((cx, cy, cx + r * 0.5, cy), fill=_ICON_WHITE, width=stroke)
    # Top stub knob
    knob = w * 0.06
    draw.rectangle(
        (cx - knob, cy - r - knob, cx + knob, cy - r),
        fill=_ICON_WHITE,
    )


def _icon_dev_reload(draw, w, h):
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.34
    box = (cx - r, cy - r, cx + r, cy + r)
    stroke = max(3, int(w * 0.07))
    # Arc ~300° leaving a gap top-right for the arrowhead
    draw.arc(box, 30, 320, fill=_ICON_WHITE, width=stroke)
    # Arrowhead at the end of the arc (top-right area, angle 30°)
    import math
    a = math.radians(30)
    tip = (cx + r * math.cos(a), cy + r * math.sin(a))
    size = w * 0.13
    draw.polygon(
        [
            (tip[0] + size, tip[1] - size * 0.2),
            (tip[0] - size * 0.2, tip[1] + size),
            (tip[0] - size * 0.4, tip[1] - size * 0.4),
        ],
        fill=_ICON_WHITE,
    )


def _icon_sound(draw, w, h):
    cy = h / 2
    # Speaker body: rect + triangle horn
    body_x0 = w * 0.20
    body_x1 = w * 0.36
    body_y0 = cy - h * 0.13
    body_y1 = cy + h * 0.13
    draw.rectangle(
        (body_x0, body_y0, body_x1, body_y1), fill=_ICON_WHITE
    )
    horn = [
        (body_x1, body_y0),
        (w * 0.55, h * 0.20),
        (w * 0.55, h * 0.80),
        (body_x1, body_y1),
    ]
    draw.polygon(horn, fill=_ICON_WHITE)
    stroke = max(2, int(w * 0.05))
    # Two sound waves
    for ofs, size in ((0.02, 0.20), (0.10, 0.32)):
        rb = (
            w * (0.55 + ofs),
            cy - h * size,
            w * (0.55 + ofs) + h * size * 2,
            cy + h * size,
        )
        draw.arc(rb, -45, 45, fill=_ICON_WHITE, width=stroke)


def _icon_layout(draw, w, h):
    stroke = max(2, int(w * 0.06))
    # Outer frame
    draw.rectangle(
        (w * 0.15, h * 0.20, w * 0.85, h * 0.80),
        outline=_ICON_WHITE, width=stroke,
    )
    # Sidebar split
    draw.line(
        (w * 0.40, h * 0.20, w * 0.40, h * 0.80),
        fill=_ICON_WHITE, width=stroke,
    )
    # Title bar
    draw.line(
        (w * 0.40, h * 0.36, w * 0.85, h * 0.36),
        fill=_ICON_WHITE, width=stroke,
    )


def _icon_a11y(draw, w, h):
    cx = w / 2
    # Head
    head_r = w * 0.10
    draw.ellipse(
        (cx - head_r, h * 0.14, cx + head_r, h * 0.14 + head_r * 2),
        fill=_ICON_WHITE,
    )
    stroke = max(2, int(w * 0.06))
    # Arms outstretched
    draw.line(
        (w * 0.20, h * 0.45, w * 0.80, h * 0.45),
        fill=_ICON_WHITE, width=stroke,
    )
    # Body trunk
    draw.line(
        (cx, h * 0.40, cx, h * 0.65),
        fill=_ICON_WHITE, width=stroke,
    )
    # Legs
    draw.line(
        (cx, h * 0.65, w * 0.32, h * 0.85),
        fill=_ICON_WHITE, width=stroke,
    )
    draw.line(
        (cx, h * 0.65, w * 0.68, h * 0.85),
        fill=_ICON_WHITE, width=stroke,
    )


def _icon_translator(draw, w, h):
    # Speech bubble with tail + 3 dots inside
    stroke = max(2, int(w * 0.05))
    box = (w * 0.15, h * 0.18, w * 0.85, h * 0.62)
    draw.rounded_rectangle(
        box, radius=h * 0.10, outline=_ICON_WHITE, width=stroke,
    )
    # Tail
    tail = [
        (w * 0.30, h * 0.62),
        (w * 0.25, h * 0.85),
        (w * 0.45, h * 0.62),
    ]
    draw.polygon(tail, fill=_ICON_WHITE)
    # Three dots inside
    cy = h * 0.40
    r = w * 0.05
    for cx in (w * 0.32, w * 0.50, w * 0.68):
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r), fill=_ICON_WHITE,
        )


def _icon_bt(draw, w, h):
    stroke = max(3, int(w * 0.07))
    cx = w / 2
    points = [
        (cx, h * 0.15),
        (w * 0.70, h * 0.35),
        (w * 0.30, h * 0.65),
        (w * 0.70, h * 0.65),
        (cx, h * 0.85),
        (cx, h * 0.15),
        (w * 0.30, h * 0.35),
        (w * 0.70, h * 0.65),
    ]
    draw.line(points, fill=_ICON_WHITE, width=stroke, joint="curve")


_ICONS = {
    "mic_on": _icon_mic,
    "mic_off": _icon_mic_off,
    "tile": _icon_tile,
    "timer": _icon_timer,
    "dev_reload": _icon_dev_reload,
    "sound": _icon_sound,
    "layout": _icon_layout,
    "a11y": _icon_a11y,
    "bt": _icon_bt,
    "translator": _icon_translator,
}


def set_key(deck, key, color, text="", icon=None):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    draw = ImageDraw.Draw(img)
    if icon and icon in _ICONS:
        _ICONS[icon](draw, w, h)
    if text and (icon is None or _show_labels):
        base_fs = 20 if len(text) <= 2 else 14 if len(text) <= 4 else 11
        fs = max(6, int(round(base_fs * _font_scale)))
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
        # Layout delete pending slot id (used by confirm mode)
        self.layout_delete_pending = None
        # Translator state
        self._stt_backends = _translator.detect_stt_backends()
        self._stt_index = 0
        self._output_methods = (
            _translator.detect_output_methods()
            or [_translator.OUTPUT_CLIP]
        )
        self._output_index = 0
        self._record_proc = None
        self._record_path = None
        # Restore last selections
        prefs = _settings_load()
        if prefs.get("translator_stt"):
            for i, b in enumerate(self._stt_backends):
                if b.name == prefs["translator_stt"]:
                    self._stt_index = i
                    break
        if prefs.get("translator_output") in self._output_methods:
            self._output_index = self._output_methods.index(
                prefs["translator_output"]
            )
        # Idle entry points
        self._compute_idle_buttons()

    def _compute_idle_buttons(self):
        """Idle menu: TILE, TIMER, DEV RELOAD, SOUND, LAYOUT left-aligned
        on row 0. Layout shortcuts on row 1, aligned under LAYOUT."""
        order = [
            "tile", "timer", "dev_reload", "sound", "layout", "a11y",
            "bluetooth", "translator",
        ]
        for i, name in enumerate(order):
            setattr(self, f"{name}_key", i if i < self.cols else -1)

        # Layout shortcuts: last row, aligned under LAYOUT, one per slot.
        self.layout_shortcut_keys = []
        if (self.layout_key >= 0
                and self.rows >= 2
                and self.layout_key + NUM_LAYOUT_SLOTS <= self.cols):
            base = (self.rows - 1) * self.cols + self.layout_key
            self.layout_shortcut_keys = [
                base + i for i in range(NUM_LAYOUT_SLOTS)
            ]

        # Mic status indicator at bottom-left (also a click target = toggle).
        self.mic_status_key = (
            (self.rows - 1) * self.cols if self.rows >= 2 else -1
        )

        self._compute_sound_buttons()
        self._compute_layout_buttons()
        self._compute_a11y_buttons()
        self._compute_bluetooth_buttons()
        self._compute_translator_buttons()

    def _compute_translator_buttons(self):
        """Translator mode keys. Requires >= 4 cols and >= 2 rows."""
        if self.cols < 4 or self.rows < 2:
            self.translator_keys = None
            return
        self.translator_keys = {
            "back": 0,
            "record": self.cols + 1,
            "backend": self.cols + 2,
            "output": self.cols + 3,
        }

    def _compute_bluetooth_buttons(self):
        """BLUETOOTH mode keys. Requires >= 2 cols and >= 2 rows."""
        if self.cols < 2 or self.rows < 2:
            self.bluetooth_keys = None
            return
        self.bluetooth_keys = {
            "back": 0,
            "toggle": self.cols + 1,
        }

    def _compute_a11y_buttons(self):
        """A11Y mode keys. Requires >= 4 cols and >= 2 rows."""
        if self.cols < 4 or self.rows < 2:
            self.a11y_keys = None
            return
        keys = {
            "back": 0,
            "font_down": self.cols + 1,
            "font_up": self.cols + 2,
            "font_reset": self.cols + 3,
        }
        if self.cols >= 5:
            keys["labels_toggle"] = self.cols + 4
        self.a11y_keys = keys

    def _compute_layout_buttons(self):
        """Layout mode keys. Requires >= 4 cols and >= 3 rows.
        Delete row shown when >= 4 rows fit."""
        if self.cols < 4 or self.rows < 3:
            self.layout_keys = None
            return
        self.layout_keys = {
            "back": 0,
            "save": [self.cols + 1 + i for i in range(NUM_LAYOUT_SLOTS)],
            "load": [2 * self.cols + 1 + i for i in range(NUM_LAYOUT_SLOTS)],
            "delete": (
                [3 * self.cols + 1 + i for i in range(NUM_LAYOUT_SLOTS)]
                if self.rows >= 4 else []
            ),
        }

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
        elif self.mode == MODE_LAYOUT:
            self._handle_layout_key(key)
        elif self.mode == MODE_LAYOUT_DELETE_CONFIRM:
            self._handle_layout_delete_confirm_key(key)
        elif self.mode == MODE_A11Y:
            self._handle_a11y_key(key)
        elif self.mode == MODE_BLUETOOTH:
            self._handle_bluetooth_key(key)
        elif self.mode == MODE_TRANSLATOR:
            self._handle_translator_key(key)

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
        if key == self.layout_key and self.layout_key >= 0:
            self.mode = MODE_LAYOUT
            self.render()
            return
        if key == self.a11y_key and self.a11y_key >= 0:
            self.mode = MODE_A11Y
            self.render()
            return
        if key == self.bluetooth_key and self.bluetooth_key >= 0:
            self.mode = MODE_BLUETOOTH
            self.render()
            return
        if key == self.translator_key and self.translator_key >= 0:
            self.mode = MODE_TRANSLATOR
            self.render()
            return
        if key == self.mic_status_key and self.mic_status_key >= 0:
            _wpctl_mute_toggle(WPCTL_SOURCE)
            self.render()
            return
        if key in self.layout_shortcut_keys:
            slot = self.layout_shortcut_keys.index(key) + 1
            slots = _layouts_load().get("slots", {})
            if str(slot) not in slots:
                return  # empty slot: no-op
            ok = _load_layout_slot(slot)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        if key == self.timer_key and self.timer_key != self.tile_key:
            self._enter_timer_mode()
            return
        if key == self.tile_key:
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

    def _handle_layout_key(self, key):
        lk = self.layout_keys
        if not lk:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == lk["back"]:
            self.mode = MODE_IDLE
            self.render()
            return
        if key in lk["save"]:
            slot = lk["save"].index(key) + 1
            ok = _save_layout_slot(slot)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        if key in lk["load"]:
            slot = lk["load"].index(key) + 1
            ok = _load_layout_slot(slot)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        if key in lk["delete"]:
            slot = lk["delete"].index(key) + 1
            if str(slot) not in _layouts_load().get("slots", {}):
                return  # empty slot: no-op
            self.layout_delete_pending = slot
            self.mode = MODE_LAYOUT_DELETE_CONFIRM
            self.render()
            return

    def _handle_layout_delete_confirm_key(self, key):
        if key == 0:
            # Cancel
            self.layout_delete_pending = None
            self.mode = MODE_LAYOUT
            self.render()
            return
        if key == self.total_keys - 1:
            # Confirm
            slot = self.layout_delete_pending
            ok = _delete_layout_slot(slot) if slot else False
            self.layout_delete_pending = None
            self.mode = MODE_LAYOUT
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        # Other keys ignored (force explicit choice)

    def _handle_translator_key(self, key):
        tk = self.translator_keys
        if not tk:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == tk["back"]:
            if self._record_proc is not None:
                _translator.stop_recording(self._record_proc)
                self._record_proc = None
            self.mode = MODE_IDLE
            self.render()
            return
        if key == tk["record"]:
            self._toggle_record()
            return
        if key == tk["backend"] and self._stt_backends:
            self._stt_index = (self._stt_index + 1) % len(self._stt_backends)
            data = _settings_load()
            data["translator_stt"] = self._stt_backends[self._stt_index].name
            _settings_save(data)
            self.render()
            return
        if key == tk["output"]:
            self._output_index = (
                (self._output_index + 1) % len(self._output_methods)
            )
            data = _settings_load()
            data["translator_output"] = (
                self._output_methods[self._output_index]
            )
            _settings_save(data)
            self.render()
            return

    def _toggle_record(self):
        if self._record_proc is None:
            if not self._stt_backends:
                self.last_result = "err"
                self.result_time = time.monotonic()
                self.render()
                return
            fd, path = tempfile.mkstemp(prefix="sttrec_", suffix=".wav")
            os.close(fd)
            self._record_path = path
            self._record_proc = _translator.start_recording(path)
            if self._record_proc is None:
                self.last_result = "err"
                self.result_time = time.monotonic()
                os.unlink(path)
                self._record_path = None
            self.render()
            return
        # Stop + transcribe
        _translator.stop_recording(self._record_proc)
        self._record_proc = None
        path = self._record_path
        self._record_path = None
        self.render()
        threading.Thread(
            target=self._finish_transcription,
            args=(path,),
            daemon=True,
        ).start()

    def _finish_transcription(self, wav_path):
        try:
            backend = self._stt_backends[self._stt_index]
            text = backend.transcribe(wav_path)
            ok = False
            if text:
                method = self._output_methods[self._output_index]
                ok = _translator.output_text(text, method)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        with self.lock:
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            if self.mode == MODE_TRANSLATOR:
                self.render()

    def _handle_bluetooth_key(self, key):
        bk = self.bluetooth_keys
        if not bk:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == bk["back"]:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == bk["toggle"]:
            current = _bt_powered()
            if current is None:
                self.last_result = "err"
                self.result_time = time.monotonic()
                self.render()
                return
            _bt_set_power(not current)
            self.render()

    def _handle_a11y_key(self, key):
        ak = self.a11y_keys
        if not ak:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == ak["back"]:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == ak["font_down"]:
            _set_font_scale(_font_scale - FONT_SCALE_STEP)
        elif key == ak["font_up"]:
            _set_font_scale(_font_scale + FONT_SCALE_STEP)
        elif key == ak["font_reset"]:
            _set_font_scale(FONT_SCALE_DEFAULT)
        elif key == ak.get("labels_toggle"):
            _toggle_show_labels()
        else:
            return
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
        elif self.mode == MODE_LAYOUT:
            self._render_layout()
        elif self.mode == MODE_LAYOUT_DELETE_CONFIRM:
            self._render_layout_delete_confirm()
        elif self.mode == MODE_A11Y:
            self._render_a11y()
        elif self.mode == MODE_BLUETOOTH:
            self._render_bluetooth()
        elif self.mode == MODE_TRANSLATOR:
            self._render_translator()

    def _render_idle(self):
        shortcut_slots = {}
        if self.layout_shortcut_keys:
            filled = _layouts_load().get("slots", {})
            for i, sk in enumerate(self.layout_shortcut_keys):
                if str(i + 1) in filled:
                    shortcut_slots[sk] = i + 1
        mic_color, mic_label = self._mic_indicator()
        for key in range(self.total_keys):
            if key == self.tile_key:
                set_key(self.deck, key, COLOR_TITLE, "TILE", icon="tile")
            elif key == self.timer_key and self.timer_key != self.tile_key:
                set_key(self.deck, key, COLOR_TIMER_TITLE, "TIMER",
                        icon="timer")
            elif key == self.dev_reload_key and self.dev_reload_key >= 0:
                set_key(self.deck, key, COLOR_DEV_RELOAD, "DEV\nRELOAD",
                        icon="dev_reload")
            elif key == self.sound_key and self.sound_key >= 0:
                set_key(self.deck, key, COLOR_SOUND_TITLE, "SOUND",
                        icon="sound")
            elif key == self.layout_key and self.layout_key >= 0:
                set_key(self.deck, key, COLOR_LAYOUT_TITLE, "LAYOUT",
                        icon="layout")
            elif key == self.a11y_key and self.a11y_key >= 0:
                set_key(self.deck, key, COLOR_A11Y_TITLE, "A11Y",
                        icon="a11y")
            elif key == self.bluetooth_key and self.bluetooth_key >= 0:
                set_key(self.deck, key, COLOR_BT_TITLE, "BT", icon="bt")
            elif key == self.translator_key and self.translator_key >= 0:
                set_key(
                    self.deck, key, COLOR_TR_TITLE, "TRANSL",
                    icon="translator",
                )
            elif key == self.mic_status_key and self.mic_status_key >= 0:
                icon_name = mic_label.split("\n")[0]  # "MIC" prefix
                icon = "mic_on" if "ON" in mic_label else (
                    "mic_off" if "OFF" in mic_label else None
                )
                set_key(self.deck, key, mic_color, mic_label, icon=icon)
            elif key in shortcut_slots:
                slot = shortcut_slots[key]
                set_key(self.deck, key, COLOR_LOAD_FILLED, f"*\n{slot}")
            elif key == 0 and not self.dbus_ok:
                set_key(self.deck, key, COLOR_ERR, "NO\nEXT")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _mic_indicator(self):
        """(color, label) tuple for the mic status icon."""
        vol, muted = _wpctl_get(WPCTL_SOURCE)
        if vol is None:
            return COLOR_BT_NA, "MIC\nN/A"
        if muted:
            return COLOR_MUTE_ON, "MIC\nOFF"
        return COLOR_MUTE_OFF, "MIC\nON"

    def _render_layout(self):
        lk = self.layout_keys
        if not lk:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, "BACK")
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, "DECK\nTOO\nSMALL")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        data = _layouts_load()
        slots = data.get("slots", {})
        assignments = {lk["back"]: (COLOR_BACK, "BACK")}
        for i, save_key in enumerate(lk["save"]):
            assignments[save_key] = (COLOR_SAVE, f"SAVE\n{i + 1}")
        for i, load_key in enumerate(lk["load"]):
            slot = slots.get(str(i + 1))
            if slot:
                count = slot.get("count", "?")
                when = slot.get("saved_at", "")
                label = f"LOAD {i + 1}\n{count}w\n{when}"
                assignments[load_key] = (COLOR_LOAD_FILLED, label)
            else:
                assignments[load_key] = (
                    COLOR_LOAD_EMPTY, f"LOAD {i + 1}\nEMPTY"
                )
        for i, del_key in enumerate(lk["delete"]):
            if str(i + 1) in slots:
                assignments[del_key] = (COLOR_CANCEL, f"DEL {i + 1}")
            else:
                assignments[del_key] = (COLOR_EMPTY, "")
        for key in range(self.total_keys):
            if key in assignments:
                color, label = assignments[key]
                set_key(self.deck, key, color, label)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_layout_delete_confirm(self):
        slot = self.layout_delete_pending or "?"
        mid_key = self.total_keys // 2
        for key in range(self.total_keys):
            if key == 0:
                set_key(self.deck, key, COLOR_CANCEL, "CANCEL")
            elif key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_CONFIRM, "OK")
            elif key == mid_key - 1 and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, "DELETE")
            elif key == mid_key and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, f"SLOT\n{slot}?")
            elif key == mid_key:
                set_key(self.deck, key, COLOR_EMPTY, f"DEL\n{slot}?")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_translator(self):
        tk = self.translator_keys
        if not tk:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, "BACK")
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, "DECK\nTOO\nSMALL")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return
        recording = self._record_proc is not None
        if self._stt_backends:
            backend_name = self._stt_backends[self._stt_index].name
        else:
            backend_name = "NONE"
        method = self._output_methods[self._output_index]
        method_lbl = "TYPE" if method == _translator.OUTPUT_TYPE else "CLIP"
        rec_color = COLOR_REC_ON if recording else COLOR_REC_OFF
        rec_label = "STOP" if recording else "REC"
        rec_icon = "mic_on" if recording else "mic_off"
        assignments = {
            tk["back"]: (COLOR_BACK, "BACK", None),
            tk["record"]: (rec_color, rec_label, rec_icon),
            tk["backend"]: (
                COLOR_BACKEND, f"STT\n{backend_name[:6]}", None,
            ),
            tk["output"]: (COLOR_OUTPUT, f"OUT\n{method_lbl}", None),
        }
        for key in range(self.total_keys):
            if key in assignments:
                color, label, icon = assignments[key]
                set_key(self.deck, key, color, label, icon=icon)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_bluetooth(self):
        bk = self.bluetooth_keys
        if not bk:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, "BACK")
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, "DECK\nTOO\nSMALL")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return
        powered = _bt_powered()
        if powered is None:
            toggle_color, toggle_label = COLOR_BT_NA, "BT\nN/A"
        elif powered:
            toggle_color, toggle_label = COLOR_BT_ON, "BT\nON"
        else:
            toggle_color, toggle_label = COLOR_BT_OFF, "BT\nOFF"
        assignments = {
            bk["back"]: (COLOR_BACK, "BACK"),
            bk["toggle"]: (toggle_color, toggle_label),
        }
        for key in range(self.total_keys):
            if key in assignments:
                color, label = assignments[key]
                set_key(self.deck, key, color, label)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_a11y(self):
        ak = self.a11y_keys
        if not ak:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, "BACK")
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, "DECK\nTOO\nSMALL")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return
        scale_lbl = f"SCALE\n{_font_scale:.1f}x"
        labels_lbl = (
            f"LABELS\n{'ON' if _show_labels else 'OFF'}"
        )
        assignments = {
            ak["back"]: (COLOR_BACK, "BACK"),
            ak["font_down"]: (COLOR_FONT_STEP, "FONT\n-"),
            ak["font_up"]: (COLOR_FONT_STEP, "FONT\n+"),
            ak["font_reset"]: (COLOR_FONT_RESET, "RESET"),
            self.total_keys // 2: (COLOR_EMPTY, scale_lbl),
        }
        if "labels_toggle" in ak:
            color = COLOR_MUTE_OFF if _show_labels else COLOR_BT_OFF
            assignments[ak["labels_toggle"]] = (color, labels_lbl)
        for key in range(self.total_keys):
            if key in assignments:
                color, label = assignments[key]
                set_key(self.deck, key, color, label)
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
        """Refresh loop: clear result flash + periodic mode refresh."""
        last_timer_refresh = 0
        last_idle_refresh = 0
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
                elif (self.mode == MODE_IDLE
                        and self.mic_status_key >= 0):
                    # Auto-refresh every 2s so mic mute toggled outside
                    # the deck is reflected on the indicator.
                    if now - last_idle_refresh >= 2.0:
                        self.render()
                        last_idle_refresh = now
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
    _init_font_scale()
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
