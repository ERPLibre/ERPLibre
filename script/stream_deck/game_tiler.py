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
import shlex
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
    "section": "erplibre",
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
COLOR_LLM_OFF = (60, 60, 60)
COLOR_LLM_ON = (140, 60, 160)

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

# How long the OK / ERR flash takes over the deck after a button
# press. Short = snappier; the value is shared by the input lockout
# in handle_key, the render-time overlay, and the loop that clears
# it once expired.
RESULT_FLASH_SEC = 0.5

# Auto-cancel tiling mode after this many seconds of inactivity, so a
# half-started TILE selection (first corner picked, second never
# clicked) doesn't lock the deck on the tiling grid forever. Reset on
# any tiling key press.
TILING_IDLE_TIMEOUT_SEC = 5.0

# Lookup table for the few deck labels short enough to translate
# without overflowing a 72×72 pixel button. Most labels stay in their
# universal English/abbreviation form (TILE, OK, REC, STOP, BT, FOCUS,
# A11Y, etc.) since translating them would either lose recognition
# (TILE → TUILE) or no longer fit the rendered glyph budget.
_DECK_LANG = os.environ.get('LANG', 'en').lower()[:2]
_DECK_LABELS = {
    'fr': {
        # Navigation / actions
        'BACK':       'RETOUR',
        'QUIT':       'QUITTER',
        'KILL':       'TUER',
        'CANCEL':     'ANNULER',
        'CLEAR':      'EFFACER',
        'DELETE':     'SUPPR',
        'NEW':        'NOUV',
        # Timer page
        'RFSH':       'ACTUAL',
        'RESET\nALL': 'RAZ\nTOUT',
        'RESET':      'RAZ',
        'ALL?':       'TOUT?',
        'RESET\nALL?': 'RAZ\nTOUT?',
        'EXPT\nCSV':  'EXP\nCSV',
        'CLEAN\nDASH': 'NETTOY\nTABL',
        'NO\nTIMERS': 'AUCUN\nMINUT',
        # Idle screen titles
        'TILE':       'TUILE',
        'TIMER':      'MINUT',
        'SOUND':      'SON',
        'LAYOUT':     'DISPO',
        'TRANSL':     'TRADUC',
        # Sound / mic / bluetooth labels
        'MIC\nN/A':   'MIC\nN/D',
        'MIC\nON':    'MIC\nON',
        'MIC\nOFF':   'MIC\nMUET',
        'MIC\nMUTE':  'MIC\nMUET',
        'OUT\nMUTE':  'SORT\nMUET',
        'BT\nN/A':    'BT\nN/D',
        # Layout slot prompts
        'SAVE':       'ENREG',
        'EMPTY':      'VIDE',
        # Errors
        'NO\nEXT':    'EXT\nABS',
        'DECK\nTOO\nSMALL': 'DECK\nTROP\nPETIT',
        # Project shortcuts
        'TODO':       'TODO',
        'ENTER\n↵':   'ENTRER\n↵',
        'FORGET':     'OUBLI',
        # Claude session page
        'FOCUS':      'FOCUS',
        'ACCEPT\n↵':  'OK\n↵',
        'SET\nWIN':   'DEF\nFEN',
        # MPV session page
        'PLAY\nPAUSE': 'LECT\nPAUSE',
        'VOL\n−':     'VOL\n−',
        'VOL\n+':     'VOL\n+',
        # Result flash glyphs (kept short)
        'OK!':        'OK!',
        'ERR':        'ERR',
    },
}


def _t(label):
    """Translate `label` to the active deck language. Falls back to
    the original English label when no translation is recorded."""
    return _DECK_LABELS.get(_DECK_LANG, {}).get(label, label)

# Claude session indicator colours (mirrors GNOME extension badge palette).
COLOR_CLAUDE_ACTIVE = (46, 125, 50)     # green
COLOR_CLAUDE_WORKING = (0, 131, 143)    # cyan / teal
COLOR_CLAUDE_AWAIT_STOP = (212, 160, 23)  # yellow
COLOR_CLAUDE_AWAIT_NOTIFY = (198, 40, 40)  # red

CLAUDE_STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "streamdeck-tiler", "claude",
)
MPV_STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "streamdeck-tiler", "mpv",
)
TODO_TERMINALS_PATH = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "streamdeck-tiler", "todo_terminals.json",
)
COLOR_MPV_ACTIVE = (40, 100, 180)  # blue
COLOR_TODO_TERMINAL = (140, 90, 50)  # warm tan, distinct from claude/mpv


def _load_mpv_sessions():
    """Return active mpv sessions launched by the film indicator,
    sorted newest first. Drops entries whose pid is gone."""
    out = []
    if not os.path.isdir(MPV_STATE_DIR):
        return out
    for name in sorted(os.listdir(MPV_STATE_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(MPV_STATE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        pid = int(d.get("pid") or 0)
        if pid > 0 and not os.path.exists(f"/proc/{pid}"):
            continue
        out.append({
            "pid": pid,
            "title": d.get("title", "") or d.get("url", ""),
            "url": d.get("url", ""),
            "started_at": int(d.get("started_at") or 0),
        })
    out.sort(key=lambda s: -s.get("started_at", 0))
    return out


def _load_todo_terminals():
    """Return the list of terminals the user has opened from the deck
    TODO button. Each entry: {window_id, name, opened_at}."""
    if not os.path.exists(TODO_TERMINALS_PATH):
        return []
    try:
        with open(TODO_TERMINALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (OSError, json.JSONDecodeError):
        return []


def _save_todo_terminals(entries):
    """Replace the TODO terminal registry on disk."""
    try:
        os.makedirs(os.path.dirname(TODO_TERMINALS_PATH), exist_ok=True)
        tmp = TODO_TERMINALS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        os.replace(tmp, TODO_TERMINALS_PATH)
    except OSError as e:
        print(f"todo terminals save: {e}", file=sys.stderr, flush=True)


def _list_mutter_window_ids():
    """Ask the extension for the live set of window stable_sequence
    ids so we can prune stale TODO terminal registrations."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ListWindows",
            ],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return None
        payload = _parse_gdbus_string_tuple(result.stdout)
        if not payload:
            return None
        windows = json.loads(payload)
        if not isinstance(windows, list):
            return None
        ids = set()
        for w in windows:
            wid = w.get("id")
            if wid:
                ids.add(str(wid))
        return ids
    except Exception:
        return None


def _get_focused_window_id():
    """Query the extension for the id of the currently focused window."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.GetFocusedWindowId",
            ],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return ""
        return _parse_gdbus_string_tuple(result.stdout) or ""
    except Exception:
        return ""


_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\r')
_TODO_MENU_RE = re.compile(r'^\s*\[(\d+)\]\s+(.+?)\s*$')


def _strip_ansi(text):
    return _ANSI_RE.sub('', text or '')


def _parse_todo_menu(text):
    """Return ``(items, prompt)`` where ``items`` is a list of
    ``(digit_str, label)`` tuples for the most recent menu block in
    ``text`` (todo.py output captured via ``script -f``), and
    ``prompt`` is the trailing non-menu line that hints what the
    next input should be (often 'Select: ' or similar).

    The parser walks lines from the end and keeps consecutive
    ``[N] label`` matches. The last menu may be preceded by free
    text the user can ignore — we only surface the buttons."""
    raw = _strip_ansi(text or '')
    lines = raw.splitlines()
    items = []
    prompt = ''
    saw_items = False
    for line in reversed(lines):
        m = _TODO_MENU_RE.match(line)
        if m:
            items.append((m.group(1), m.group(2)))
            saw_items = True
            continue
        if not saw_items:
            stripped = line.strip()
            if stripped and not prompt:
                prompt = stripped
            continue
        # First non-menu line above the block: stop walking.
        break
    items.reverse()
    return items, prompt


def _read_todo_log_tail(path, max_bytes=8192):
    if not path or not os.path.exists(path):
        return ''
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            data = f.read()
        return data.decode('utf-8', errors='replace')
    except OSError:
        return ''


def _send_keys_to_window(window_id, text):
    """Synthesise `text` into the window with the given stable sequence
    id, via the extension's Clutter virtual keyboard."""
    if not window_id:
        return False
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.SendKeysToWindow",
                str(window_id), text,
            ],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            print(f"SendKeysToWindow: {result.stderr}",
                file=sys.stderr, flush=True)
            return False
        return "true" in result.stdout.lower()
    except Exception as e:
        print(f"SendKeysToWindow error: {e}",
            file=sys.stderr, flush=True)
        return False


def _load_claude_sessions():
    """Return active Claude sessions from the state dir, sorted newest first.

    Drops files whose PID is no longer running (best-effort).
    """
    out = []
    if not os.path.isdir(CLAUDE_STATE_DIR):
        return out
    for name in sorted(os.listdir(CLAUDE_STATE_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(CLAUDE_STATE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        pid = int(d.get("pid") or 0)
        if pid > 0 and not os.path.exists(f"/proc/{pid}"):
            continue
        ts_active = int(d.get("ts_active") or 0)
        ts_stop = int(d.get("ts_stop") or 0)
        ts_notif = int(d.get("ts_notification") or 0)
        ts_tool = int(d.get("ts_tool") or 0)
        ts = max(ts_active, ts_stop, ts_notif, ts_tool)
        if ts == ts_notif and ts_notif > 0:
            status = "awaiting_notification"
        elif ts == ts_stop and ts_stop > 0:
            status = "awaiting_stop"
        elif ts == ts_tool and ts_tool > 0:
            status = "working"
        else:
            status = "active"
        out.append({
            "session_id": d.get("session_id", ""),
            "cwd": d.get("cwd", ""),
            "description": d.get("description", "")
                or d.get("last_prompt", ""),
            "notification_message": d.get("notification_message", ""),
            "status": status,
            "ts": ts,
        })
    out.sort(key=lambda s: -s.get("ts", 0))
    return out


def _claude_color(session):
    if session.get("status") == "awaiting_notification":
        return COLOR_CLAUDE_AWAIT_NOTIFY
    if session.get("status") == "awaiting_stop":
        return COLOR_CLAUDE_AWAIT_STOP
    if session.get("status") == "working":
        return COLOR_CLAUDE_WORKING
    return COLOR_CLAUDE_ACTIVE


def _claude_label(session, max_chars=18):
    """Two short lines for the button."""
    desc = (session.get("description") or "").strip()
    if not desc:
        return ""
    if len(desc) <= max_chars:
        return desc
    # Word-break at a space close to the middle.
    cut = desc.rfind(" ", 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars
    return desc[:cut].rstrip()


def _chunk_text_for_cells(text, num_cells, per_cell=12):
    """Split `text` into up to `num_cells` chunks of ~`per_cell` chars.

    Breaks at word boundaries when a space is available close to the
    target length so reading flows from one cell to the next.
    """
    text = (text or "").strip()
    if not text or num_cells <= 0:
        return []
    chunks = []
    remaining = text
    for _ in range(num_cells):
        if not remaining:
            break
        if len(remaining) <= per_cell:
            chunks.append(remaining)
            remaining = ""
            break
        cut = remaining.rfind(" ", 0, per_cell + 2)
        if cut < per_cell // 2:
            cut = per_cell
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return chunks


def _wrap_chunk(text, line_chars=6):
    """Insert a newline near `line_chars` so set_key renders 2 lines
    instead of overflowing a narrow key."""
    text = (text or "").strip()
    if len(text) <= line_chars:
        return text
    cut = text.rfind(" ", 0, line_chars + 2)
    if cut < line_chars // 2:
        cut = line_chars
    return f"{text[:cut].rstrip()}\n{text[cut:].lstrip()}"


def _wrap_button_label(text, max_chars=8, max_lines=2):
    """Wrap `text` for a deck button with up to `max_lines` lines of
    `max_chars` glyphs each. Breaks at spaces when possible, hard-
    breaks long words, and appends a trailing ellipsis when the
    label still overflows."""
    text = (text or "").strip()
    if not text:
        return ""
    lines = []
    rest = text
    while rest and len(lines) < max_lines:
        if len(rest) <= max_chars:
            lines.append(rest)
            rest = ""
            break
        cut = rest.rfind(" ", 0, max_chars + 1)
        if cut < 1:
            cut = max_chars
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        last = lines[-1]
        room = max_chars - 1
        lines[-1] = (last[:room] if len(last) >= room else last) + "…"
    return "\n".join(lines)

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
MODE_TRANSLATOR_HISTORY = "translator_history"
MODE_CLAUDE_SESSION = "claude_session"
MODE_MPV_SESSION = "mpv_session"
MODE_TODO_SESSION = "todo_session"

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
        print(f"Tiler dbus: {result.stdout} {result.stderr}", file=sys.stderr, flush=True)
        return False
    except Exception as e:
        print(f"Tiler dbus error: {e}", file=sys.stderr, flush=True)
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
            print(f"Timer list dbus: {result.stderr}", file=sys.stderr, flush=True)
            return []
        payload = _parse_gdbus_string_tuple(result.stdout)
        if not payload:
            return []
        return json.loads(payload)
    except Exception as e:
        print(f"Timer list error: {e}", file=sys.stderr, flush=True)
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
        print(f"Timer toggle dbus: {result.stdout} {result.stderr}", file=sys.stderr, flush=True)
        return False
    except Exception as e:
        print(f"Timer toggle error: {e}", file=sys.stderr, flush=True)
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
            print(f"Timer add dbus: {result.stderr}", file=sys.stderr, flush=True)
            return ""
        payload = _parse_gdbus_string_tuple(result.stdout)
        return payload or ""
    except Exception as e:
        print(f"Timer add error: {e}", file=sys.stderr, flush=True)
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
        print(f"Timer reset dbus: {result.stdout} {result.stderr}", file=sys.stderr, flush=True)
        return False
    except Exception as e:
        print(f"Timer reset error: {e}", file=sys.stderr, flush=True)
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
            print(f"bluetoothctl show error: {e}", file=sys.stderr, flush=True)
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
            print(f"rfkill list error: {e}", file=sys.stderr, flush=True)
    return None


def _bt_list_paired():
    """Return [(mac, name, connected)] for paired devices via bluetoothctl."""
    paired = []
    if not shutil.which("bluetoothctl"):
        return paired
    try:
        r = subprocess.run(
            ["bluetoothctl", "devices", "Paired"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split(maxsplit=2)
                if len(parts) >= 3 and parts[0] == "Device":
                    paired.append((parts[1], parts[2]))
    except Exception as e:
        print(f"bluetoothctl devices Paired error: {e}", file=sys.stderr, flush=True)
        return []
    connected = set()
    try:
        r = subprocess.run(
            ["bluetoothctl", "devices", "Connected"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split(maxsplit=2)
                if len(parts) >= 2 and parts[0] == "Device":
                    connected.add(parts[1])
    except Exception:
        pass
    return [(mac, name, mac in connected) for mac, name in paired]


def _bt_connect(mac):
    if not shutil.which("bluetoothctl"):
        return False
    try:
        r = subprocess.run(
            ["bluetoothctl", "connect", mac],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"bluetoothctl connect error: {e}", file=sys.stderr, flush=True)
        return False


def _bt_disconnect(mac):
    if not shutil.which("bluetoothctl"):
        return False
    try:
        r = subprocess.run(
            ["bluetoothctl", "disconnect", mac],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"bluetoothctl disconnect error: {e}", file=sys.stderr, flush=True)
        return False


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
            print(f"bluetoothctl power error: {e}", file=sys.stderr, flush=True)
    if shutil.which("rfkill"):
        try:
            r = subprocess.run(
                ["rfkill", "unblock" if on else "block", "bluetooth"],
                capture_output=True, text=True, timeout=3,
            )
            return r.returncode == 0
        except Exception as e:
            print(f"rfkill error: {e}", file=sys.stderr, flush=True)
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
        print(f"wpctl get error: {e}", file=sys.stderr, flush=True)
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
        print(f"wpctl set-volume error: {e}", file=sys.stderr, flush=True)
        return False


def _wpctl_mute_toggle(target):
    try:
        r = subprocess.run(
            ["wpctl", "set-mute", target, "toggle"],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-mute error: {e}", file=sys.stderr, flush=True)
        return False


_WPCTL_DEV_RE = re.compile(
    r"^\s*│\s+(\*\s+)?(\d+)\.\s+(.+?)\s+\[vol:"
)


def _wpctl_list_devices(kind):
    """Parse `wpctl status` for Audio Sinks or Sources.

    kind = 'Sinks' | 'Sources'. Returns list of
    {id: int, name: str, default: bool}, ordered as printed.
    """
    try:
        r = subprocess.run(
            ["wpctl", "status"],
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return []
    if r.returncode != 0:
        return []
    out = []
    in_audio = False
    in_section = False
    for line in r.stdout.splitlines():
        if line.startswith("Audio"):
            in_audio = True
            continue
        if line.startswith("Video"):
            in_audio = False
            continue
        if not in_audio:
            continue
        if f"├─ {kind}:" in line:
            in_section = True
            continue
        if line.startswith(" ├─") or line.startswith(" └─"):
            in_section = False
            continue
        if in_section:
            m = _WPCTL_DEV_RE.match(line)
            if m:
                marker, id_str, name = m.groups()
                out.append({
                    "id": int(id_str),
                    "name": name.strip(),
                    "default": bool(marker),
                })
    return out


def _wpctl_set_default(device_id):
    try:
        r = subprocess.run(
            ["wpctl", "set-default", str(device_id)],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-default error: {e}", file=sys.stderr, flush=True)
        return False


def _wpctl_cycle_default(kind):
    """Switch to the next device in the section. Returns new active dict."""
    devices = _wpctl_list_devices(kind)
    if not devices:
        return None
    idx = next(
        (i for i, d in enumerate(devices) if d["default"]),
        0,
    )
    nxt = devices[(idx + 1) % len(devices)]
    if _wpctl_set_default(nxt["id"]):
        return nxt
    return None


def _wpctl_default_short(kind):
    """Short label for the currently default device (last word, ≤ 6 chars)."""
    for d in _wpctl_list_devices(kind):
        if d["default"]:
            words = d["name"].split()
            tail = words[-1] if words else d["name"]
            return tail[:6]
    return ""


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
            print(f"ListWindows dbus: {r.stderr}", file=sys.stderr, flush=True)
            return []
        payload = _parse_gdbus_string_tuple(r.stdout)
        return json.loads(payload) if payload else []
    except Exception as e:
        print(f"ListWindows error: {e}", file=sys.stderr, flush=True)
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
            print(f"ApplyLayout dbus: {r.stderr}", file=sys.stderr, flush=True)
            return 0
        m = re.search(r"\((\d+),\)", r.stdout.strip())
        return int(m.group(1)) if m else 0
    except Exception as e:
        print(f"ApplyLayout error: {e}", file=sys.stderr, flush=True)
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
            print(f"[streamdeck-tiler] HotReload dbus: "
                  f"{result.stderr.strip()}",
                  file=sys.stderr, flush=True)
            return False
        payload = _parse_gdbus_string_tuple(result.stdout)
        return bool(payload)
    except Exception as e:
        print(f"[streamdeck-tiler] HotReload error: {e}",
              file=sys.stderr, flush=True)
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
        print(f"File dialog error: {e}", file=sys.stderr, flush=True)
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
        print(f"CSV write error: {e}", file=sys.stderr, flush=True)
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


def _icon_robot(draw, w, h):
    stroke = max(2, int(w * 0.05))
    # Antenna
    cx = w / 2
    draw.line([(cx, h * 0.10), (cx, h * 0.22)],
              fill=_ICON_WHITE, width=stroke)
    draw.ellipse(
        [cx - w * 0.05, h * 0.05, cx + w * 0.05, h * 0.15],
        fill=_ICON_WHITE,
    )
    # Head
    draw.rounded_rectangle(
        [w * 0.20, h * 0.25, w * 0.80, h * 0.65],
        radius=int(w * 0.10), outline=_ICON_WHITE, width=stroke,
    )
    # Eyes
    eye_r = max(2, int(w * 0.05))
    draw.ellipse(
        [w * 0.32 - eye_r, h * 0.42 - eye_r,
         w * 0.32 + eye_r, h * 0.42 + eye_r],
        fill=_ICON_WHITE,
    )
    draw.ellipse(
        [w * 0.68 - eye_r, h * 0.42 - eye_r,
         w * 0.68 + eye_r, h * 0.42 + eye_r],
        fill=_ICON_WHITE,
    )
    # Mouth
    draw.line(
        [(w * 0.36, h * 0.55), (w * 0.64, h * 0.55)],
        fill=_ICON_WHITE, width=stroke,
    )
    # Body hint (shoulders)
    draw.line(
        [(w * 0.30, h * 0.72), (w * 0.70, h * 0.72)],
        fill=_ICON_WHITE, width=stroke,
    )


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
    "robot": _icon_robot,
}


def _draw_layout_preview(draw, w, h, windows, slot_num=None):
    """Render a thumbnail of saved layout windows on a button-sized canvas.
    Bounding box is computed from the windows themselves to keep the
    preview readable even when only a sub-region of the screen is used."""
    if not windows:
        return
    margin = 2
    cw = max(1, w - 2 * margin)
    ch = max(1, h - 2 * margin)
    xs = [win.get("x", 0) for win in windows]
    ys = [win.get("y", 0) for win in windows]
    xs2 = [win.get("x", 0) + win.get("w", 0) for win in windows]
    ys2 = [win.get("y", 0) + win.get("h", 0) for win in windows]
    bx0, by0 = min(xs), min(ys)
    bx1, by1 = max(xs2), max(ys2)
    bw = max(1, bx1 - bx0)
    bh = max(1, by1 - by0)
    scale = min(cw / bw, ch / bh)
    sw = bw * scale
    sh = bh * scale
    ox = margin + (cw - sw) / 2
    oy = margin + (ch - sh) / 2
    for win in sorted(windows, key=lambda v: v.get("stacking", 0)):
        x = ox + (win.get("x", 0) - bx0) * scale
        y = oy + (win.get("y", 0) - by0) * scale
        rw = max(2, win.get("w", 0) * scale)
        rh = max(2, win.get("h", 0) * scale)
        draw.rectangle(
            (x, y, x + rw, y + rh),
            outline=(220, 220, 220), width=1,
            fill=(60, 90, 130),
        )
    if slot_num is not None:
        font = _load_label_font(14)
        draw.text((3, 1), str(slot_num), fill=(255, 220, 0), font=font)


# Pillow's `load_default()` returns a tiny Latin-1 bitmap that
# renders missing glyphs as boxes — French accents, Spotify's "▶"
# etc. all break visually. Cache one TrueType font that ships on
# Debian / Fedora / Arch (DejaVu) and fall back to PIL's default
# only when it is genuinely missing.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_FONT_PATH = None
for _candidate in _FONT_CANDIDATES:
    if os.path.isfile(_candidate):
        _FONT_PATH = _candidate
        break


def _load_label_font(fs):
    """Return a font sized `fs` with broad Unicode coverage."""
    if _FONT_PATH:
        try:
            return ImageFont.truetype(_FONT_PATH, fs)
        except (OSError, IOError):
            pass
    try:
        return ImageFont.load_default(size=fs)
    except TypeError:
        return ImageFont.load_default()


def set_key(deck, key, color, text="", icon=None, extra_draw=None):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    draw = ImageDraw.Draw(img)
    if icon and icon in _ICONS:
        _ICONS[icon](draw, w, h)
    if extra_draw:
        try:
            extra_draw(draw, w, h)
        except Exception as e:
            print(f"extra_draw failed: {e}", file=sys.stderr, flush=True)
    if text and (icon is None or _show_labels):
        base_fs = 20 if len(text) <= 2 else 14 if len(text) <= 4 else 11
        fs = max(6, int(round(base_fs * _font_scale)))
        font = _load_label_font(fs)
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
        self.last_press_key = None  # which key triggered last_result
        self._claude_session_sid = None  # active session in MODE_CLAUDE_SESSION
        self._mpv_session_pid = None     # active mpv pid in MODE_MPV_SESSION
        self._todo_session_window_id = None  # active terminal id
        # Window-id capture for newly spawned TODO terminals: timestamp
        # set by _launch_todo_terminal, polled by the main loop.
        self._pending_todo_capture_at = 0.0
        self._pending_todo_log_path = ''
        self.todo_terminals = _load_todo_terminals()
        self._tiling_last_touch = 0.0    # monotonic ts of last tiling input
        self.dbus_ok = _check_dbus_available()
        # Timer state
        self.timers = []  # list of dicts from _list_tracker_timers
        # Map: key index -> timer id (for timer list mode)
        self.timer_key_map = {}
        # Timer ids the user has dismissed via Clean dashboard. The
        # render loop purges any id whose timer is no longer running
        # so a stop+start cycle resurfaces the timer on the idle
        # screen automatically.
        self._dashboard_hidden_timer_ids = set()
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
        self._llm_backends = _translator.detect_llm_backends()
        self._llm_index = 0
        self._llm_mode_index = 0  # off / translate / chat
        self._record_proc = None
        self._record_path = None
        self._record_started_at = 0.0
        self._vad_should_stop = False
        self._streaming_proc = None
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
        if prefs.get("translator_llm"):
            for i, b in enumerate(self._llm_backends):
                if b.name == prefs["translator_llm"]:
                    self._llm_index = i
                    break
        if prefs.get("translator_llm_mode") in _translator.LLM_MODES:
            self._llm_mode_index = _translator.LLM_MODES.index(
                prefs["translator_llm_mode"]
            )
        # Idle entry points
        self._compute_idle_buttons()

    def _compute_idle_buttons(self):
        """Idle menu: TILE, TIMER, DEV RELOAD, SOUND, LAYOUT left-aligned
        on row 0. Items that overflow row 0 spill onto row 1 starting
        at col 0 — only on decks with at least three rows so the mic
        + layout-shortcut bottom row stays free."""
        order = [
            "tile", "timer", "dev_reload", "sound", "layout", "a11y",
            "bluetooth", "translator", "todo",
        ]
        for i, name in enumerate(order):
            setattr(self, f"{name}_key", i if i < self.cols else -1)
        if self.rows >= 3:
            next_overflow = self.cols
            row1_end = self.cols * 2
            for name in order:
                if getattr(self, f"{name}_key") >= 0:
                    continue
                if next_overflow >= row1_end:
                    break
                setattr(self, f"{name}_key", next_overflow)
                next_overflow += 1

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
        self._compute_claude_buttons()
        self._compute_claude_session_keys()
        self._compute_mpv_session_keys()

    def _launch_todo_terminal(self):
        """Open a gnome-terminal under the project root, activate the
        ERPLibre venv, and run script/todo/todo.py. Schedule a window-
        id capture roughly one second later so the deck can register
        the freshly-opened terminal and surface a per-window button
        that drives the todo.py TUI via the extension's
        SendKeysToWindow D-Bus method."""
        root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        venv = os.path.join(root, ".venv.erplibre", "bin", "activate")
        script = os.path.join(root, "script", "todo", "todo.py")
        if not os.path.exists(script):
            self._flag_err(f"todo.py not found at {script}")
            self.render()
            return
        # Wrap the python invocation through ``script -fqc`` so the
        # interactive pty session is also mirrored to a log file the
        # deck can tail. ``-u`` unbuffers Python so menu lines hit
        # the log without waiting for the next input. Falls back to
        # the bare command when ``script`` is missing — the per-
        # terminal numpad still works without parsed menus.
        inner = (f"source '{venv}' && python3 -u '{script}'"
                 if os.path.exists(venv)
                 else f"python3 -u '{script}'")
        log_path = ''
        if shutil.which("script"):
            log_dir = os.path.join(
                os.environ.get("XDG_STATE_HOME")
                or os.path.expanduser("~/.local/state"),
                "streamdeck-tiler", "todo")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(
                log_dir, f"todo-{int(time.time())}.log")
            cmd = (f"script -fqc {shlex.quote(inner)} "
                   f"{shlex.quote(log_path)}")
        else:
            cmd = inner
        terminals = [
            ["gnome-terminal", "--working-directory", root,
                "--", "bash", "-lc", cmd],
            ["kgx", "--working-directory", root,
                "--", "bash", "-lc", cmd],
            ["xterm", "-e", f"cd '{root}' && {cmd}"],
        ]
        for argv in terminals:
            if shutil.which(argv[0]) is None:
                continue
            try:
                subprocess.Popen(argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True)
                # Capture happens on the first idle tick after the
                # delay so the new gnome-terminal has time to settle
                # and grab focus.
                self._pending_todo_capture_at = time.monotonic() + 1.0
                self._pending_todo_log_path = log_path
                self.last_result = "ok"
                self.result_time = time.monotonic()
                self.render()
                return
            except Exception as e:
                print(f"todo terminal spawn failed: {e}",
                    file=sys.stderr, flush=True)
        self._flag_err("No terminal found (gnome-terminal / kgx / xterm)")
        self.render()

    def _capture_pending_todo_terminal(self):
        wid = _get_focused_window_id()
        if not wid:
            self._flag_err("Could not capture TODO terminal window id")
            self.render()
            return
        live = _list_mutter_window_ids()
        if live:
            # Drop registrations whose windows have closed; if the
            # extension answer is empty or lacks ids, leave the list
            # untouched so the freshly-captured terminal is not
            # incorrectly purged.
            self.todo_terminals = [
                t for t in self.todo_terminals
                if str(t.get("window_id")) in live
            ]
        existing = next((t for t in self.todo_terminals
                         if str(t.get("window_id")) == str(wid)), None)
        if existing is None:
            n = len(self.todo_terminals) + 1
            self.todo_terminals.append({
                "window_id": str(wid),
                "name": f"TODO {n}",
                "opened_at": time.time(),
                "log_path": self._pending_todo_log_path or "",
            })
        else:
            existing["log_path"] = self._pending_todo_log_path or ""
        self._pending_todo_log_path = ""
        _save_todo_terminals(self.todo_terminals)

    def _refresh_todo_terminals(self):
        """Drop registrations whose windows have closed. Skip the
        purge entirely when the extension's ListWindows answer comes
        back empty or without ids — older extension builds did not
        ship the ``id`` field, and a stale-looking 'no live windows'
        snapshot would otherwise nuke a freshly-registered terminal
        the user just opened."""
        live = _list_mutter_window_ids()
        if not live:
            return
        before = len(self.todo_terminals)
        self.todo_terminals = [
            t for t in self.todo_terminals
            if str(t.get("window_id")) in live
        ]
        if len(self.todo_terminals) != before:
            _save_todo_terminals(self.todo_terminals)

    def _flag_err(self, reason):
        """Set the result-flash to 'err' AND surface `reason` in
        stderr so the terminal running game_tiler.py captures every
        button failure, not just the silent flash on the deck."""
        print(f"[streamdeck-tiler] {reason}",
              file=sys.stderr, flush=True)
        self.last_result = "err"
        self.result_time = time.monotonic()

    def _enter_claude_session_mode(self, key):
        """Open the actions page for the claude session attached to
        `key`. Stores the session id so re-renders survive state file
        churn from new prompts."""
        if not self.claude_keys:
            return
        try:
            idx = self.claude_keys.index(key)
        except ValueError:
            return
        sessions = _load_claude_sessions()
        if idx >= len(sessions):
            return
        sid = sessions[idx].get("session_id") or ""
        if not sid:
            return
        self._claude_session_sid = sid
        self.mode = MODE_CLAUDE_SESSION
        self.render()

    def _call_claude_dbus(self, method, sid):
        try:
            out = subprocess.check_output([
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell",
                "--object-path",
                "/org/gnome/Shell/Extensions/StreamDeckTiler",
                "--method",
                f"org.gnome.Shell.Extensions.StreamDeckTiler.{method}",
                sid,
            ], stderr=subprocess.STDOUT, timeout=2).decode()
            ok = "true" in out.lower()
            if not ok:
                print(f"[streamdeck-tiler] {method}({sid!r}) "
                      f"returned: {out.strip()}",
                      file=sys.stderr, flush=True)
            return ok
        except subprocess.CalledProcessError as e:
            print(f"[streamdeck-tiler] {method}({sid!r}) failed: "
                  f"{(e.output or b'').decode(errors='replace').strip()}",
                  file=sys.stderr, flush=True)
            return False
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            print(f"[streamdeck-tiler] {method}({sid!r}) failed: {e}",
                  file=sys.stderr, flush=True)
            return False

    def _focus_claude_for_key(self, key):
        if not self.claude_keys:
            return False
        try:
            idx = self.claude_keys.index(key)
        except ValueError:
            return False
        sessions = _load_claude_sessions()
        if idx >= len(sessions):
            return False
        sid = sessions[idx].get("session_id") or ""
        if not sid:
            return False
        return self._call_claude_dbus("FocusClaudeSession", sid)

    def _compute_claude_session_keys(self):
        """Layout for the per-session action page. Requires >= 2 cols.
        Cells fill row 0 left-to-right as the deck has more columns:
        BACK / FOCUS / ACCEPT / SET WINDOW / KILL."""
        if self.cols < 2:
            self.claude_session_keys = None
            return
        keys = {"back": 0, "focus": 1}
        if self.cols >= 3:
            keys["accept"] = 2
        if self.cols >= 4:
            keys["set_window"] = 3
        if self.cols >= 5:
            keys["kill"] = 4
        self.claude_session_keys = keys

    def _compute_mpv_session_keys(self):
        """Layout for the per-mpv action page. >= 3 cols required.
        BACK / PLAY-PAUSE / QUIT on the first row; VOL- / VOL+ on
        the second row when there's room."""
        if self.cols < 3:
            self.mpv_session_keys = None
            return
        self.mpv_session_keys = {
            "back": 0, "play_pause": 1, "quit": 2,
        }
        if self.rows >= 2:
            self.mpv_session_keys["vol_down"] = self.cols
            self.mpv_session_keys["vol_up"] = self.cols + 1

    def _compute_claude_buttons(self):
        """Reserve free cells (rows 1+, after mic + layout shortcuts) for
        Claude session indicators. One cell per running session."""
        used = set()
        for k in (self.tile_key, self.timer_key, self.dev_reload_key,
                  self.sound_key, self.layout_key, self.a11y_key,
                  self.bluetooth_key, self.translator_key,
                  self.todo_key, self.mic_status_key):
            if k >= 0:
                used.add(k)
        used.update(self.layout_shortcut_keys or [])
        # Walk rows 1..end in reading order, skipping used cells.
        self.claude_keys = []
        for k in range(self.cols, self.total_keys):
            if k in used:
                continue
            self.claude_keys.append(k)

    def _compute_translator_buttons(self):
        """Translator mode keys. Requires >= 4 cols and >= 2 rows.
        LLM controls appear when there is room (cols >= 6)."""
        if self.cols < 4 or self.rows < 2:
            self.translator_keys = None
            return
        keys = {
            "back": 0,
            "stream": self.cols + 0,
            "record": self.cols + 1,
            "backend": self.cols + 2,
            "output": self.cols + 3,
        }
        if self.cols >= 6:
            keys["llm_mode"] = self.cols + 4
            keys["llm_backend"] = self.cols + 5
        if self.cols >= 7:
            keys["history"] = self.cols + 6
        self.translator_keys = keys

    def _compute_bluetooth_buttons(self):
        """BLUETOOTH mode keys. Requires >= 2 cols and >= 2 rows.
        Paired-device slots fill row 1 after the toggle button."""
        if self.cols < 2 or self.rows < 2:
            self.bluetooth_keys = None
            return
        keys = {
            "back": 0,
            "toggle": self.cols + 1,
        }
        # Devices on row 1 cols 2..cols-1
        first = self.cols + 2
        last = 2 * self.cols
        keys["devices"] = list(range(first, last))
        self.bluetooth_keys = keys

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
        """Layout for sound mode. Requires >= 4 cols and >= 3 rows.
        Device picker keys (SINK / SRC) appear when row 0 has slack."""
        if self.cols < 4 or self.rows < 3:
            self.sound_keys = None
            return
        keys = {
            "back": 0,
            "vol_down": self.cols + 1,
            "vol_up": self.cols + 2,
            "out_mute": self.cols + 3,
            "mic_down": 2 * self.cols + 1,
            "mic_up": 2 * self.cols + 2,
            "mic_mute": 2 * self.cols + 3,
        }
        if self.cols >= 4:
            keys["sink"] = 1     # row 0, col 1 — cycles default output
            keys["source"] = 2   # row 0, col 2 — cycles default input
        self.sound_keys = keys

    # ---------- Key handling ----------

    def handle_key(self, key, state):
        if not state:
            return

        # Block input during result flash
        if (self.last_result and time.monotonic() - self.result_time
                < RESULT_FLASH_SEC):
            return

        # Remember which key triggered whichever result the dispatch
        # ends up setting, so the flash overlay paints only this key
        # and its 4-neighbours instead of the whole deck.
        self.last_press_key = key

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
        elif self.mode == MODE_TRANSLATOR_HISTORY:
            self._handle_translator_history_key(key)
        elif self.mode == MODE_CLAUDE_SESSION:
            self._handle_claude_session_key(key)
        elif self.mode == MODE_MPV_SESSION:
            self._handle_mpv_session_key(key)
        elif self.mode == MODE_TODO_SESSION:
            self._handle_todo_session_key(key)

    def _handle_mpv_session_key(self, key):
        ms = self.mpv_session_keys
        if not ms:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == ms.get("back"):
            self.mode = MODE_IDLE
            self.render()
            return
        pid = self._mpv_session_pid
        if not pid:
            self.mode = MODE_IDLE
            self.render()
            return
        cmd = None
        stay_on_page = False
        if key == ms.get("play_pause"): cmd = "play_pause"
        elif key == ms.get("quit"):     cmd = "quit"
        elif key == ms.get("vol_down"):
            cmd = "vol_down"
            stay_on_page = True
        elif key == ms.get("vol_up"):
            cmd = "vol_up"
            stay_on_page = True
        if not cmd:
            return
        ok = self._call_mpv_dbus(pid, cmd)
        self.last_result = "ok" if ok else "err"
        self.result_time = time.monotonic()
        if stay_on_page:
            # Volume nudges are repeatable — stay on the action page so
            # the user can press the button again without re-entering
            # the per-mpv mode.
            self.render()
            return
        self.mode = MODE_IDLE
        self.render()

    def _call_mpv_dbus(self, pid, command):
        try:
            out = subprocess.check_output([
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell",
                "--object-path",
                "/org/gnome/Shell/Extensions/StreamDeckTiler",
                "--method",
                "org.gnome.Shell.Extensions.StreamDeckTiler"
                ".MpvSendCommand",
                str(int(pid)), command,
            ], stderr=subprocess.STDOUT, timeout=2).decode()
            ok = "true" in out.lower()
            if not ok:
                print(f"[streamdeck-tiler] MpvSendCommand({pid}, "
                      f"{command!r}) returned: {out.strip()}",
                      file=sys.stderr, flush=True)
            return ok
        except subprocess.CalledProcessError as e:
            print(f"[streamdeck-tiler] MpvSendCommand({pid}, {command!r}) "
                  f"failed: "
                  f"{(e.output or b'').decode(errors='replace').strip()}",
                  file=sys.stderr, flush=True)
            return False
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            print(f"[streamdeck-tiler] MpvSendCommand({pid}, {command!r}) "
                  f"failed: {e}",
                  file=sys.stderr, flush=True)
            return False

    def _handle_claude_session_key(self, key):
        cs = self.claude_session_keys
        if not cs:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == cs.get("back"):
            self.mode = MODE_IDLE
            self.render()
            return
        sid = self._claude_session_sid
        if not sid:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == cs.get("focus"):
            ok = self._call_claude_dbus("FocusClaudeSession", sid)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.mode = MODE_IDLE
            self.render()
            return
        if "accept" in cs and key == cs["accept"]:
            ok = self._call_claude_dbus("AcceptClaudeSession", sid)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.mode = MODE_IDLE
            self.render()
            return
        if "set_window" in cs and key == cs["set_window"]:
            ok = self._call_claude_dbus("SetClaudeSessionWindow", sid)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.mode = MODE_IDLE
            self.render()
            return
        if "kill" in cs and key == cs["kill"]:
            ok = self._call_claude_dbus("KillClaudeSession", sid)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.mode = MODE_IDLE
            self.render()
            return

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
        if key == self.todo_key and self.todo_key >= 0:
            self._launch_todo_terminal()
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
            if ok:
                self.last_result = "ok"
                self.result_time = time.monotonic()
            else:
                self._flag_err(f"layout shortcut load slot {slot} failed")
            self.render()
            return
        if key in (self.claude_keys or []):
            session_keys = list(self.claude_keys or [])
            try:
                idx = session_keys.index(key)
            except ValueError:
                return
            mpv_sessions = _load_mpv_sessions()
            if idx < len(mpv_sessions):
                self._mpv_session_pid = mpv_sessions[idx]['pid']
                self.mode = MODE_MPV_SESSION
                self.render()
                return
            cidx = idx - len(mpv_sessions)
            claude_sessions = _load_claude_sessions()
            if cidx < len(claude_sessions):
                sid = claude_sessions[cidx].get('session_id') or ''
                if sid:
                    self._claude_session_sid = sid
                    self.mode = MODE_CLAUDE_SESSION
                    self.render()
                return
            tidx = cidx - len(claude_sessions)
            running_timers = [
                t for t in (self.timers or []) if t.get('running')
                and t.get('id') not in self._dashboard_hidden_timer_ids
            ]
            if tidx < len(running_timers):
                # Tapping a timer dashboard tile drops back to the
                # timer list page so the user can pause it.
                self._enter_timer_mode()
                return
            todoidx = tidx - len(running_timers)
            terms = self.todo_terminals or []
            if todoidx < len(terms):
                wid = str(terms[todoidx].get('window_id') or '')
                if wid:
                    self._todo_session_window_id = wid
                    self.mode = MODE_TODO_SESSION
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
            self._tiling_last_touch = time.monotonic()
            self.render()

    def _handle_tiling_key(self, key):
        # Bump the inactivity timer so the auto-cancel below does
        # not fire while the user is actively picking corners.
        self._tiling_last_touch = time.monotonic()
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
        if ok:
            self.last_result = "ok"
            self.result_time = time.monotonic()
        else:
            self._flag_err(
                f"TileWindow({self.grid_cols}x{self.grid_rows} "
                f"{c1},{r1}-{c2},{r2}) failed via D-Bus")
        self._tiling_last_touch = 0.0
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
                self._flag_err("AddTrackerTimer returned no id")
                self.render()
            return
        if key == self.total_keys - 4:
            self._handle_export()
            return
        if key == self.total_keys - 5:
            # Hide every currently-running timer from the idle
            # dashboard. They keep ticking in the tracker; the user
            # just dismisses them from the main screen.
            self._dashboard_hidden_timer_ids = {
                t.get('id') for t in (self.timers or [])
                if t.get('running') and t.get('id')}
            self.last_result = "ok"
            self.result_time = time.monotonic()
            self.render()
            return
        timer_id = self.timer_key_map.get(key)
        if not timer_id:
            return
        ok = _toggle_tracker_timer(timer_id)
        if ok:
            self._refresh_timers()
            self.render()
        else:
            self._flag_err(f"ToggleTrackerTimer({timer_id}) failed")
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
            if ok:
                self.last_result = "ok"
                self.result_time = time.monotonic()
            else:
                self._flag_err(f"layout save slot {slot} failed")
            self.render()
            return
        if key in lk["load"]:
            slot = lk["load"].index(key) + 1
            ok = _load_layout_slot(slot)
            if ok:
                self.last_result = "ok"
                self.result_time = time.monotonic()
            else:
                self._flag_err(f"layout load slot {slot} failed")
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
            if ok:
                self.last_result = "ok"
                self.result_time = time.monotonic()
            else:
                self._flag_err(f"layout delete slot {slot} failed")
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
        if key == tk.get("llm_mode"):
            self._llm_mode_index = (
                (self._llm_mode_index + 1) % len(_translator.LLM_MODES)
            )
            data = _settings_load()
            data["translator_llm_mode"] = (
                _translator.LLM_MODES[self._llm_mode_index]
            )
            _settings_save(data)
            self.render()
            return
        if key == tk.get("llm_backend") and self._llm_backends:
            self._llm_index = (
                (self._llm_index + 1) % len(self._llm_backends)
            )
            data = _settings_load()
            data["translator_llm"] = self._llm_backends[self._llm_index].name
            _settings_save(data)
            self.render()
            return
        if key == tk.get("history"):
            self.mode = MODE_TRANSLATOR_HISTORY
            self.render()
            return
        if key == tk.get("stream"):
            self._toggle_streaming()
            return

    def _handle_translator_history_key(self, key):
        # Layout: 0 = BACK, total-1 = CLEAR, others map to entries.
        if key == 0:
            self.mode = MODE_TRANSLATOR
            self.render()
            return
        if key == self.total_keys - 1:
            _translator.clear_history()
            self.render()
            return
        entries = list(reversed(_translator.load_history()))
        # Slot map: keys 1..total-2 map to entries[0..]
        idx = key - 1
        if 0 <= idx < len(entries):
            entry = entries[idx]
            method = self._output_methods[self._output_index]
            ok = _translator.output_text(entry.get("text", ""), method)
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()

    def _on_vad_silence(self):
        """Called from the VAD reader thread; defer to main loop."""
        self._vad_should_stop = True

    def _toggle_streaming(self):
        if self._streaming_proc is not None and (
                self._streaming_proc.poll() is None):
            try:
                self._streaming_proc.terminate()
                self._streaming_proc.wait(timeout=2)
            except Exception:
                try:
                    self._streaming_proc.kill()
                except Exception:
                    pass
            self._streaming_proc = None
            self.render()
            return
        script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "translator_stream.py",
        )
        try:
            self._streaming_proc = subprocess.Popen(
                [sys.executable, script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self._streaming_proc = None
            self._flag_err(f"streaming start failed: {e}")
        self.render()

    def _toggle_record(self):
        if self._record_proc is None:
            if not self._stt_backends:
                self._flag_err(
                    "translator: no STT backend available "
                    "(install whisper-cpp or vosk)")
                self.render()
                return
            fd, path = tempfile.mkstemp(prefix="sttrec_", suffix=".wav")
            os.close(fd)
            self._record_path = path
            self._vad_should_stop = False
            if _translator.vad_enabled():
                self._record_proc = _translator.start_recording_vad(
                    path, on_silence=self._on_vad_silence,
                )
            else:
                self._record_proc = _translator.start_recording(path)
            if self._record_proc is None:
                self._flag_err(
                    f"translator: failed to start recording at {path}")
                os.unlink(path)
                self._record_path = None
            else:
                self._record_started_at = time.monotonic()
            self.render()
            return
        # Stop + transcribe
        _translator.stop_recording(self._record_proc)
        self._record_proc = None
        self._record_started_at = 0.0
        path = self._record_path
        self._record_path = None
        self.render()
        threading.Thread(
            target=self._finish_transcription,
            args=(path,),
            daemon=True,
        ).start()

    def _finish_transcription(self, wav_path):
        ok = False
        try:
            backend = self._stt_backends[self._stt_index]
            raw = backend.transcribe(wav_path)
            llm_mode = _translator.LLM_MODES[self._llm_mode_index]
            llm_backend = (
                self._llm_backends[self._llm_index]
                if self._llm_backends else None
            )
            text = _translator.llm_postprocess(raw, llm_mode, llm_backend)
            if text:
                method = self._output_methods[self._output_index]
                ok = _translator.output_text(text, method)
                try:
                    _translator.append_history(
                        text,
                        llm_mode=llm_mode,
                        language=_translator.stt_language(),
                        wm_class=_translator.focused_window_class(),
                    )
                except Exception as e:
                    print(f"history append error: {e}", file=sys.stderr, flush=True)
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
                self._flag_err(
                    "bluetooth: bluetoothctl unavailable or no adapter")
                self.render()
                return
            _bt_set_power(not current)
            self.render()
            return
        if key in bk.get("devices", []):
            idx = bk["devices"].index(key)
            devices = _bt_list_paired()
            if idx < len(devices):
                mac, _name, connected = devices[idx]
                if connected:
                    _bt_disconnect(mac)
                else:
                    _bt_connect(mac)
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
        elif key == sk.get("sink"):
            _wpctl_cycle_default("Sinks")
        elif key == sk.get("source"):
            _wpctl_cycle_default("Sources")
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
                self.result_time = time.monotonic()
            else:
                self._flag_err("ResetAllTrackerTimers failed via D-Bus")
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
        # Keys for timers: 1 .. total-6
        # (skip BACK=0, CLEAN=total-5, EXPORT=total-4, NEW=total-3,
        #  RESET=total-2, RFSH=total-1)
        usable = list(range(1, self.total_keys - 5))
        for idx, timer in enumerate(self.timers):
            if idx >= len(usable):
                break
            self.timer_key_map[usable[idx]] = timer.get("id")

    # ---------- Rendering ----------

    def render(self):
        # Result flash. The pressed key + its 4-neighbours go green
        # (or red on error) so the user gets clear acknowledgement
        # without losing context on the rest of the deck.
        if self.last_result:
            elapsed = time.monotonic() - self.result_time
            if elapsed < RESULT_FLASH_SEC:
                self._render_mode()
                self._overlay_flash()
                return
            self.last_result = None
        self._render_mode()

    def _render_mode(self):
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
        elif self.mode == MODE_TRANSLATOR_HISTORY:
            self._render_translator_history()
        elif self.mode == MODE_CLAUDE_SESSION:
            self._render_claude_session()
        elif self.mode == MODE_MPV_SESSION:
            self._render_mpv_session()
        elif self.mode == MODE_TODO_SESSION:
            self._render_todo_session()

    def _overlay_flash(self):
        if self.last_press_key is None:
            # No specific key tracked (programmatic flash) — fall back
            # to the old whole-deck behaviour so the feedback is still
            # visible.
            color = COLOR_OK if self.last_result == "ok" else COLOR_ERR
            label = "OK!" if self.last_result == "ok" else "ERR"
            for key in range(self.total_keys):
                set_key(self.deck, key, color, label)
            return
        color = COLOR_OK if self.last_result == "ok" else COLOR_ERR
        label = "OK!" if self.last_result == "ok" else "ERR"
        keys = self._key_neighbors(self.last_press_key)
        keys.add(self.last_press_key)
        for k in keys:
            if 0 <= k < self.total_keys:
                set_key(self.deck, k, color, label)

    def _key_neighbors(self, key):
        if key is None or self.cols <= 0 or self.rows <= 0:
            return set()
        col = key % self.cols
        row = key // self.cols
        out = set()
        for (dc, dr) in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nc = col + dc
            nr = row + dr
            if 0 <= nc < self.cols and 0 <= nr < self.rows:
                out.add(nr * self.cols + nc)
        return out

    def _todo_session_keys(self):
        """Layout: row 0 has BACK, ENTER, FOCUS, FORGET on the four
        leftmost cells. Every cell from the start of row 1 to the
        end of the deck is reserved for parsed menu items (or the
        numpad fallback). Returns ``None`` when the deck has fewer
        than two rows."""
        if self.rows < 2 or self.cols < 4:
            return None
        keys = {"back": 0, "enter": 1, "focus": 2, "forget": 3}
        keys["item_slots"] = list(range(self.cols, self.total_keys))
        return keys

    def _todo_active_term(self):
        return next((t for t in (self.todo_terminals or [])
                     if str(t.get("window_id"))
                     == str(self._todo_session_window_id)), None)

    def _todo_session_items(self):
        """Read the captured todo.py log tail and surface the latest
        ``[N] label`` block as deck button candidates. Returns
        ``[(digit, label, key_index)]`` ordered for placement."""
        term = self._todo_active_term()
        log_path = term.get("log_path") if term else ''
        if not log_path:
            return []
        items, _prompt = _parse_todo_menu(_read_todo_log_tail(log_path))
        return items

    def _render_todo_session(self):
        ts = self._todo_session_keys()
        if not ts:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR,
                        _t("DECK\nTOO\nSMALL"))
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return
        slots = ts["item_slots"]
        items = self._todo_session_items()
        item_by_key = {}
        digit_by_key = {}
        if items:
            # Parsed menu wins over numpad: each item lands on the
            # next free row 1+ slot in reading order so menus larger
            # than nine entries fit on bigger decks.
            for i, (digit, label) in enumerate(items[:len(slots)]):
                item_by_key[slots[i]] = (digit, label)
        else:
            # No menu detected (free-text prompt or ASCII logo). Lay
            # out a numpad in reading order so the user can still
            # type digits 1..9, 0 to drive todo.py manually.
            digits = "1234567890"
            for i, d in enumerate(digits):
                if i >= len(slots):
                    break
                digit_by_key[slots[i]] = d
        for key in range(self.total_keys):
            if key == ts["back"]:
                set_key(self.deck, key, COLOR_BACK, _t("BACK"))
            elif key == ts["enter"]:
                set_key(self.deck, key, COLOR_CONFIRM, _t("ENTER\n↵"))
            elif key == ts["focus"]:
                set_key(self.deck, key, COLOR_VOL, _t("FOCUS"))
            elif key == ts["forget"]:
                set_key(self.deck, key, COLOR_CANCEL, _t("FORGET"))
            elif key in item_by_key:
                digit, label = item_by_key[key]
                wrapped = _wrap_button_label(label,
                    max_chars=8, max_lines=2)
                set_key(self.deck, key, COLOR_TODO_TERMINAL,
                        f"[{digit}]\n{wrapped}")
            elif key in digit_by_key:
                set_key(self.deck, key, COLOR_TODO_TERMINAL,
                        digit_by_key[key])
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _handle_todo_session_key(self, key):
        ts = self._todo_session_keys()
        wid = self._todo_session_window_id
        if not ts:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == ts["back"]:
            self.mode = MODE_IDLE
            self._todo_session_window_id = None
            self.render()
            return
        if not wid:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == ts["enter"]:
            ok = _send_keys_to_window(wid, "\n")
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        if key == ts["focus"]:
            try:
                result = subprocess.run([
                    "gdbus", "call", "--session",
                    "--dest", DBUS_DEST,
                    "--object-path", DBUS_PATH,
                    "--method", f"{DBUS_IFACE}.FocusWindowById",
                    str(wid),
                ], capture_output=True, text=True, timeout=2)
                ok = (result.returncode == 0
                      and "true" in result.stdout.lower())
            except Exception:
                ok = False
            self.last_result = "ok" if ok else "err"
            self.result_time = time.monotonic()
            self.render()
            return
        if key == ts["forget"]:
            self.todo_terminals = [
                t for t in (self.todo_terminals or [])
                if str(t.get("window_id")) != str(wid)]
            _save_todo_terminals(self.todo_terminals)
            self._todo_session_window_id = None
            self.last_result = "ok"
            self.result_time = time.monotonic()
            self.mode = MODE_IDLE
            self.render()
            return
        slots = ts["item_slots"]
        try:
            idx = slots.index(key)
        except ValueError:
            return
        items = self._todo_session_items()
        if items and idx < len(items):
            digit, _label = items[idx]
        else:
            digits = "1234567890"
            if idx >= len(digits):
                return
            digit = digits[idx]
        # Send the digit plus newline so todo.py's input() prompt
        # advances on a single deck press.
        ok = _send_keys_to_window(wid, f"{digit}\n")
        self.last_result = "ok" if ok else "err"
        self.result_time = time.monotonic()
        self.render()

    def _render_mpv_session(self):
        ms = self.mpv_session_keys or {}
        pid = self._mpv_session_pid
        sess = None
        for s in _load_mpv_sessions():
            if s.get('pid') == pid:
                sess = s
                break
        action_keys = {ms.get('back'), ms.get('play_pause'),
                       ms.get('quit'), ms.get('vol_up'), ms.get('vol_down')}
        action_keys.discard(None)
        text_keys = [k for k in range(self.total_keys)
                     if k not in action_keys]
        title = (sess or {}).get('title') or (sess or {}).get('url') or ''
        chunks = _chunk_text_for_cells(title, len(text_keys))
        chunk_by_key = dict(zip(text_keys, chunks))

        for key in range(self.total_keys):
            if key == ms.get('back'):
                set_key(self.deck, key, COLOR_TITLE, _t('BACK'))
            elif key == ms.get('play_pause'):
                set_key(self.deck, key, COLOR_MPV_ACTIVE, _t('PLAY\nPAUSE'))
            elif key == ms.get('quit'):
                set_key(self.deck, key, COLOR_CANCEL, _t('QUIT'))
            elif key == ms.get('vol_down'):
                set_key(self.deck, key, COLOR_MPV_ACTIVE, _t('VOL\n−'))
            elif key == ms.get('vol_up'):
                set_key(self.deck, key, COLOR_MPV_ACTIVE, _t('VOL\n+'))
            elif key in chunk_by_key:
                set_key(self.deck, key, COLOR_EMPTY,
                        _wrap_chunk(chunk_by_key[key]))
            else:
                set_key(self.deck, key, COLOR_EMPTY, '')

    def _render_claude_session(self):
        cs = self.claude_session_keys or {}
        sid = self._claude_session_sid or ''
        session = None
        for s in _load_claude_sessions():
            if s.get('session_id') == sid:
                session = s
                break

        action_keys = {cs.get('back'), cs.get('focus')}
        for k in ('accept', 'set_window', 'kill'):
            if k in cs:
                action_keys.add(cs[k])
        text_keys = [k for k in range(self.total_keys)
                     if k not in action_keys]
        # When the session needs the user (red/yellow), prefer the
        # notification text so the deck shows what Claude is asking
        # rather than the stale topic description.
        if (session and session.get('status')
                in ('awaiting_notification', 'awaiting_stop')
                and session.get('notification_message')):
            text_to_show = session['notification_message']
        else:
            text_to_show = (session or {}).get('description') \
                or (session or {}).get('last_prompt') or ''
        chunks = _chunk_text_for_cells(text_to_show, len(text_keys))
        chunk_by_key = dict(zip(text_keys, chunks))

        for key in range(self.total_keys):
            if key == cs.get('back'):
                set_key(self.deck, key, COLOR_TITLE, _t('BACK'))
            elif key == cs.get('focus'):
                set_key(self.deck, key, COLOR_VOL, _t('FOCUS'),
                        icon='robot')
            elif 'accept' in cs and key == cs['accept']:
                color = (_claude_color(session) if session
                         else COLOR_CLAUDE_AWAIT_STOP)
                set_key(self.deck, key, color, _t('ACCEPT\n↵'))
            elif 'set_window' in cs and key == cs['set_window']:
                set_key(self.deck, key, COLOR_LAYOUT_TITLE,
                        _t('SET\nWIN'))
            elif 'kill' in cs and key == cs['kill']:
                set_key(self.deck, key, COLOR_CANCEL, _t('KILL'))
            elif key in chunk_by_key:
                set_key(self.deck, key, COLOR_EMPTY,
                        _wrap_chunk(chunk_by_key[key]))
            else:
                set_key(self.deck, key, COLOR_EMPTY, '')

    def _render_idle(self):
        shortcut_slots = {}
        if self.layout_shortcut_keys:
            filled = _layouts_load().get("slots", {})
            for i, sk in enumerate(self.layout_shortcut_keys):
                if str(i + 1) in filled:
                    shortcut_slots[sk] = i + 1
        mic_color, mic_label, mic_icon = self._mic_indicator()
        session_keys = list(self.claude_keys or [])
        mpv_sessions = _load_mpv_sessions()
        claude_sessions = _load_claude_sessions()
        # Purge dismissed-but-now-stopped timers so a fresh start
        # surfaces them again next time.
        running_ids = {
            t.get('id') for t in (self.timers or []) if t.get('running')}
        self._dashboard_hidden_timer_ids &= running_ids
        running_timers = [
            t for t in (self.timers or [])
            if t.get('running')
            and t.get('id') not in self._dashboard_hidden_timer_ids
        ]
        mpv_by_key = {}
        claude_by_key = {}
        timer_by_key = {}
        todo_by_key = {}
        cursor = 0
        for s in mpv_sessions:
            if cursor >= len(session_keys):
                break
            mpv_by_key[session_keys[cursor]] = s
            cursor += 1
        for s in claude_sessions:
            if cursor >= len(session_keys):
                break
            claude_by_key[session_keys[cursor]] = s
            cursor += 1
        for t in running_timers:
            if cursor >= len(session_keys):
                break
            timer_by_key[session_keys[cursor]] = t
            cursor += 1
        for term in (self.todo_terminals or []):
            if cursor >= len(session_keys):
                break
            todo_by_key[session_keys[cursor]] = term
            cursor += 1
        for key in range(self.total_keys):
            if key == self.tile_key:
                set_key(self.deck, key, COLOR_TITLE, _t("TILE"),
                        icon="tile")
            elif key == self.timer_key and self.timer_key != self.tile_key:
                set_key(self.deck, key, COLOR_TIMER_TITLE, _t("TIMER"),
                        icon="timer")
            elif key == self.dev_reload_key and self.dev_reload_key >= 0:
                set_key(self.deck, key, COLOR_DEV_RELOAD, "DEV\nRELOAD",
                        icon="dev_reload")
            elif key == self.sound_key and self.sound_key >= 0:
                set_key(self.deck, key, COLOR_SOUND_TITLE, _t("SOUND"),
                        icon="sound")
            elif key == self.layout_key and self.layout_key >= 0:
                set_key(self.deck, key, COLOR_LAYOUT_TITLE, _t("LAYOUT"),
                        icon="layout")
            elif key == self.a11y_key and self.a11y_key >= 0:
                set_key(self.deck, key, COLOR_A11Y_TITLE, "A11Y",
                        icon="a11y")
            elif key == self.bluetooth_key and self.bluetooth_key >= 0:
                set_key(self.deck, key, COLOR_BT_TITLE, "BT", icon="bt")
            elif key == self.translator_key and self.translator_key >= 0:
                set_key(
                    self.deck, key, COLOR_TR_TITLE, _t("TRANSL"),
                    icon="translator",
                )
            elif key == self.todo_key and self.todo_key >= 0:
                set_key(self.deck, key, COLOR_TIMER_TITLE, _t("TODO"))
            elif key == self.mic_status_key and self.mic_status_key >= 0:
                set_key(self.deck, key, mic_color, mic_label,
                        icon=mic_icon)
            elif key in shortcut_slots:
                slot = shortcut_slots[key]
                set_key(self.deck, key, COLOR_LOAD_FILLED, f"*\n{slot}")
            elif key in mpv_by_key:
                s = mpv_by_key[key]
                title = (s.get('title') or s.get('url') or 'mpv')[:18]
                set_key(self.deck, key, COLOR_MPV_ACTIVE,
                        _wrap_chunk(title))
            elif key in claude_by_key:
                s = claude_by_key[key]
                set_key(self.deck, key, _claude_color(s),
                        _claude_label(s), icon="robot")
            elif key in timer_by_key:
                t = timer_by_key[key]
                set_key(self.deck, key, COLOR_TIMER_RUNNING,
                        _label_for_timer(t), icon="timer")
            elif key in todo_by_key:
                term = todo_by_key[key]
                set_key(self.deck, key, COLOR_TODO_TERMINAL,
                        term.get("name") or "TODO")
            elif key == 0 and not self.dbus_ok:
                set_key(self.deck, key, COLOR_ERR, _t("NO\nEXT"))
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _mic_indicator(self):
        """(color, label, icon) tuple for the mic status icon. Icon is
        resolved from the underlying mic state — not the translated
        label — so a French OFF rendered as MUET still picks the
        muted icon."""
        vol, muted = _wpctl_get(WPCTL_SOURCE)
        if vol is None:
            return COLOR_BT_NA, _t("MIC\nN/A"), None
        if muted:
            return COLOR_MUTE_ON, _t("MIC\nOFF"), "mic_off"
        return COLOR_MUTE_OFF, _t("MIC\nON"), "mic_on"

    def _render_layout(self):
        lk = self.layout_keys
        if not lk:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, _t("DECK\nTOO\nSMALL"))
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        data = _layouts_load()
        slots = data.get("slots", {})
        # Each entry: (color, label, extra_draw_or_None)
        assignments = {lk["back"]: (COLOR_BACK, _t("BACK"), None)}
        for i, save_key in enumerate(lk["save"]):
            assignments[save_key] = (
                COLOR_SAVE, f"{_t('SAVE')}\n{i + 1}", None)
        for i, load_key in enumerate(lk["load"]):
            slot = slots.get(str(i + 1))
            if slot:
                windows = slot.get("windows") or []
                slot_num = i + 1

                def _make_preview(_windows, _num):
                    return lambda d, w, h: _draw_layout_preview(
                        d, w, h, _windows, slot_num=_num,
                    )

                assignments[load_key] = (
                    COLOR_LOAD_FILLED, "",
                    _make_preview(windows, slot_num),
                )
            else:
                assignments[load_key] = (
                    COLOR_LOAD_EMPTY, f"LOAD {i + 1}\n{_t('EMPTY')}", None,
                )
        for i, del_key in enumerate(lk["delete"]):
            if str(i + 1) in slots:
                assignments[del_key] = (COLOR_CANCEL, f"DEL {i + 1}", None)
            else:
                assignments[del_key] = (COLOR_EMPTY, "", None)
        for key in range(self.total_keys):
            if key in assignments:
                color, label, extra = assignments[key]
                set_key(self.deck, key, color, label, extra_draw=extra)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_layout_delete_confirm(self):
        slot = self.layout_delete_pending or "?"
        mid_key = self.total_keys // 2
        for key in range(self.total_keys):
            if key == 0:
                set_key(self.deck, key, COLOR_CANCEL, _t("CANCEL"))
            elif key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_CONFIRM, _t("OK"))
            elif key == mid_key - 1 and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, _t("DELETE"))
            elif key == mid_key and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, f"SLOT\n{slot}?")
            elif key == mid_key:
                set_key(self.deck, key, COLOR_EMPTY, f"DEL\n{slot}?")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_translator_history(self):
        entries = list(reversed(_translator.load_history()))
        for key in range(self.total_keys):
            if key == 0:
                set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                continue
            if key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_CANCEL, _t("CLEAR"))
                continue
            idx = key - 1
            if idx < len(entries):
                text = entries[idx].get("text") or ""
                snippet = text[:8] if len(text) > 8 else text
                set_key(self.deck, key, COLOR_LOAD_FILLED, snippet)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_translator(self):
        tk = self.translator_keys
        if not tk:
            for key in range(self.total_keys):
                if key == 0:
                    set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, _t("DECK\nTOO\nSMALL"))
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
        llm_mode = _translator.LLM_MODES[self._llm_mode_index]
        llm_lbl = {
            _translator.LLM_MODE_OFF: "LLM\nOFF",
            _translator.LLM_MODE_TRANSLATE: "LLM\nTRSL",
            _translator.LLM_MODE_CHAT: "LLM\nCHAT",
        }[llm_mode]
        llm_color = (
            COLOR_LLM_OFF if llm_mode == _translator.LLM_MODE_OFF
            else COLOR_LLM_ON
        )
        if self._llm_backends:
            llm_be_name = self._llm_backends[self._llm_index].name[:6]
        else:
            llm_be_name = "NONE"
        assignments = {
            tk["back"]: (COLOR_BACK, _t("BACK"), None),
            tk["record"]: (rec_color, rec_label, rec_icon),
            tk["backend"]: (
                COLOR_BACKEND, f"STT\n{backend_name[:6]}", None,
            ),
            tk["output"]: (COLOR_OUTPUT, f"OUT\n{method_lbl}", None),
        }
        if "llm_mode" in tk:
            assignments[tk["llm_mode"]] = (llm_color, llm_lbl, None)
        if "llm_backend" in tk:
            assignments[tk["llm_backend"]] = (
                COLOR_BACKEND, f"LLM\n{llm_be_name}", None,
            )
        streaming_active = (
            self._streaming_proc is not None
            and self._streaming_proc.poll() is None
        )
        if "stream" in tk:
            stream_color = COLOR_REC_ON if streaming_active else COLOR_VOL
            stream_lbl = "STR\nON" if streaming_active else "STR"
            assignments[tk["stream"]] = (stream_color, stream_lbl, None)
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
                    set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, _t("DECK\nTOO\nSMALL"))
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return
        powered = _bt_powered()
        if powered is None:
            toggle_color, toggle_label = COLOR_BT_NA, _t("BT\nN/A")
        elif powered:
            toggle_color, toggle_label = COLOR_BT_ON, "BT\nON"
        else:
            toggle_color, toggle_label = COLOR_BT_OFF, "BT\nOFF"
        assignments = {
            bk["back"]: (COLOR_BACK, _t("BACK")),
            bk["toggle"]: (toggle_color, toggle_label),
        }
        # Device slots only when BT is powered (else listing is empty anyway)
        device_keys = bk.get("devices", [])
        if powered and device_keys:
            devices = _bt_list_paired()
            for i, k in enumerate(device_keys):
                if i >= len(devices):
                    break
                mac, name, connected = devices[i]
                words = name.split()
                short = words[-1][:6] if words else name[:6]
                color = COLOR_BT_ON if connected else COLOR_BT_OFF
                assignments[k] = (color, short)
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
                    set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, _t("DECK\nTOO\nSMALL"))
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return
        scale_lbl = f"SCALE\n{_font_scale:.1f}x"
        labels_lbl = (
            f"LABELS\n{'ON' if _show_labels else 'OFF'}"
        )
        assignments = {
            ak["back"]: (COLOR_BACK, _t("BACK")),
            ak["font_down"]: (COLOR_FONT_STEP, "FONT\n-"),
            ak["font_up"]: (COLOR_FONT_STEP, "FONT\n+"),
            ak["font_reset"]: (COLOR_FONT_RESET, _t("RESET")),
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
                    set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                elif key == self.total_keys // 2:
                    set_key(self.deck, key, COLOR_ERR, _t("DECK\nTOO\nSMALL"))
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        out_vol, out_muted = _wpctl_get(WPCTL_SINK)
        mic_vol, mic_muted = _wpctl_get(WPCTL_SOURCE)

        labels = {
            sk["back"]: (COLOR_BACK, _t("BACK")),
            sk["vol_down"]: (COLOR_VOL, f"VOL\n-{VOL_STEP_PCT}%"),
            sk["vol_up"]: (COLOR_VOL, f"VOL\n+{VOL_STEP_PCT}%"),
            sk["mic_down"]: (COLOR_MIC, f"MIC\n-{VOL_STEP_PCT}%"),
            sk["mic_up"]: (COLOR_MIC, f"MIC\n+{VOL_STEP_PCT}%"),
        }
        if "sink" in sk:
            short = _wpctl_default_short("Sinks") or "?"
            labels[sk["sink"]] = (COLOR_SOUND_TITLE, f"SINK\n{short}")
        if "source" in sk:
            short = _wpctl_default_short("Sources") or "?"
            labels[sk["source"]] = (COLOR_MIC, f"SRC\n{short}")
        if out_muted:
            labels[sk["out_mute"]] = (COLOR_MUTE_ON, _t("OUT\nMUTE"))
        else:
            out_lbl = f"OUT\n{out_vol}%" if out_vol is not None else "OUT"
            labels[sk["out_mute"]] = (COLOR_MUTE_OFF, out_lbl)
        if mic_muted:
            labels[sk["mic_mute"]] = (COLOR_MUTE_ON, _t("MIC\nMUTE"))
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
                set_key(self.deck, key, COLOR_BACK, _t("BACK"))
                continue
            if key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_REFRESH, _t("RFSH"))
                continue
            if key == self.total_keys - 2:
                set_key(self.deck, key, COLOR_RESET, _t("RESET\nALL"))
                continue
            if key == self.total_keys - 3:
                set_key(self.deck, key, COLOR_NEW, _t("NEW"))
                continue
            if key == self.total_keys - 4:
                set_key(self.deck, key, COLOR_EXPORT, _t("EXPT\nCSV"))
                continue
            if key == self.total_keys - 5:
                set_key(self.deck, key, COLOR_TIMER_PAUSED,
                        _t("CLEAN\nDASH"))
                continue
            timer_id = self.timer_key_map.get(key)
            if not timer_id:
                # Empty slot — show hint if no timers exist at all
                if not self.timers and key == 1:
                    set_key(self.deck, key, COLOR_EMPTY, _t("NO\nTIMERS"))
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
                set_key(self.deck, key, COLOR_CANCEL, _t("CANCEL"))
            elif key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_CONFIRM, _t("OK"))
            elif key == mid_key - 1 and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, _t("RESET"))
            elif key == mid_key and self.cols >= 3:
                set_key(self.deck, key, COLOR_EMPTY, _t("ALL?"))
            elif key == mid_key:
                set_key(self.deck, key, COLOR_EMPTY, _t("RESET\nALL?"))
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
                    if elapsed >= RESULT_FLASH_SEC:
                        self.render()
                elif (self.mode == MODE_TILING
                        and self._tiling_last_touch > 0
                        and (now - self._tiling_last_touch
                             >= TILING_IDLE_TIMEOUT_SEC)):
                    # Idle too long while picking corners — drop back
                    # to the idle layout without touching the focused
                    # window.
                    self.mode = MODE_IDLE
                    self.corner1 = None
                    self.corner2 = None
                    self._tiling_last_touch = 0.0
                    self.render()
                elif self.mode == MODE_TIMER_LIST:
                    # Auto-refresh every 2s to update elapsed time labels
                    if now - last_timer_refresh >= 2.0:
                        self._refresh_timers()
                        self.render()
                        last_timer_refresh = now
                elif self.mode == MODE_TODO_SESSION:
                    # Re-poll the todo.py log so freshly-printed menus
                    # become deck buttons within a second of appearing.
                    if now - last_idle_refresh >= 1.0:
                        self.render()
                        last_idle_refresh = now
                elif self.mode == MODE_IDLE:
                    # Auto-refresh every 2s so mic mute toggled
                    # outside the deck shows on the indicator and
                    # running timers update their mm:ss + appear /
                    # disappear as the user starts / stops them in
                    # the tracker.
                    if (self._pending_todo_capture_at
                            and now >= self._pending_todo_capture_at):
                        self._pending_todo_capture_at = 0.0
                        self._capture_pending_todo_terminal()
                        self.render()
                    if now - last_idle_refresh >= 2.0:
                        self._refresh_timers()
                        self._refresh_todo_terminals()
                        self.render()
                        last_idle_refresh = now
                elif (self.mode == MODE_TRANSLATOR
                        and self._record_proc is not None
                        and self._record_started_at > 0):
                    if self._vad_should_stop:
                        self._vad_should_stop = False
                        self._toggle_record()
                    else:
                        timeout = _translator.recording_timeout_seconds()
                        elapsed = now - self._record_started_at
                        if timeout > 0 and elapsed >= timeout:
                            self._toggle_record()
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
        print("WARNING: streamdeck-tiler extension not found.", file=sys.stderr, flush=True)
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
        if game._streaming_proc is not None:
            try:
                game._streaming_proc.terminate()
                game._streaming_proc.wait(timeout=2)
            except Exception:
                try:
                    game._streaming_proc.kill()
                except Exception:
                    pass
        with deck:
            deck.reset()
            deck.close()


if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
