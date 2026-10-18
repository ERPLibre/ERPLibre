# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TODO terminals: the TODO home key opens todo.py in a terminal, a
registry remembers each terminal's window, and a page drives todo.py
through keys the extension synthesises in that window.

`state().terminals` is the registry as last read: the dashboard tiles
draw from it, never from the file. It is reloaded by the 2 s home
refresh, the page tick and the capture of a new terminal's window.
The registry file is shared with the extension, which adds the
terminals its own menu opens; its format does not change."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, TileProvider,
)
from erplibre_streamdeck.ui import colors, render
from erplibre_streamdeck.ui.text import wrap_button_label

PAGE_ID = "todo_session"
# The new terminal's window is read this long after the spawn, once it
# has settled and taken the focus.
CAPTURE_DELAY_SEC = 1.0
REFRESH_SEC = 2.0
DIGITS = "1234567890"

_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\r')
_TODO_MENU_RE = re.compile(r'^\s*\[(\d+)\]\s+(.+?)\s*$')


# ------------------------------------------------------------ registry


def registry_path():
    """$XDG_STATE_HOME/erplibre-home/todo_terminals.json, at call
    time."""
    return str(paths.state_dir() / "todo_terminals.json")


def load_registry():
    """Return the list of terminals opened from the deck TODO key or
    the extension. Each entry: {window_id, name, opened_at, log_path}.
    [] when the file is missing, unreadable or not a list."""
    path = registry_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (OSError, json.JSONDecodeError):
        return []


def save_registry(entries):
    """Replace the registry on disk (temporary file, then rename)."""
    path = registry_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        os.replace(tmp, path)
    except OSError as e:
        print(f"todo terminals save: {e}", file=sys.stderr, flush=True)


# --------------------------------------------------------------- D-Bus


def live_window_ids(ctx):
    """The ids of the open windows, as strings, from the extension's
    ListWindows; None when the answer is missing or unreadable."""
    try:
        r = ctx.dbus.call("ListWindows", timeout=2)
        if not r.ok:
            return None
        payload = r.string
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


def focused_window_id(ctx):
    """The id of the focused window; "" when unknown."""
    r = ctx.dbus.call("GetFocusedWindowId", timeout=2)
    return (r.string or "") if r.ok else ""


def send_keys(ctx, window_id, text):
    """Synthesise `text` into the window `window_id` through the
    extension's virtual keyboard. True when it answers `true`."""
    if not window_id:
        return False
    r = ctx.dbus.call("SendKeysToWindow", str(window_id), text, timeout=2)
    if r.returncode is None:
        print(f"SendKeysToWindow error: {r.stderr}",
              file=sys.stderr, flush=True)
        return False
    if not r.ok:
        print(f"SendKeysToWindow: {r.stderr}", file=sys.stderr, flush=True)
        return False
    return r.true


def focus_window(ctx, window_id):
    """Raise and focus the window; True when the extension answers
    `true`."""
    return ctx.dbus.call("FocusWindowById", str(window_id), timeout=2).true


# ------------------------------------------------------------ todo.py log


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
    text the user can ignore — only the buttons surface."""
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


# ------------------------------------------------------ registry upkeep


def _refresh(ctx):
    """Reload the registry from disk, so the terminals the extension
    registers show here too, then drop the entries whose window has
    closed. An empty or id-less ListWindows answer leaves the list
    whole: it would otherwise purge a terminal registered a moment
    ago."""
    st = ctx.state()
    st.terminals = load_registry()
    live = live_window_ids(ctx)
    if not live:
        return
    before = len(st.terminals)
    st.terminals = [
        t for t in st.terminals if str(t.get("window_id")) in live
    ]
    if len(st.terminals) != before:
        save_registry(st.terminals)


def _capture(ctx):
    """Register the focused window as the terminal just opened. The
    entry is appended to the list in memory, which is not re-read
    first, and the list is saved."""
    st = ctx.state()
    wid = focused_window_id(ctx)
    if not wid:
        ctx.flash(False, "Could not capture TODO terminal window id")
        return
    live = live_window_ids(ctx)
    if live:
        # Drop registrations whose windows have closed; an empty or
        # id-less answer leaves the list untouched so the terminal
        # just captured is not purged.
        st.terminals = [
            t for t in st.terminals if str(t.get("window_id")) in live
        ]
    existing = next((t for t in st.terminals
                     if str(t.get("window_id")) == str(wid)), None)
    if existing is None:
        n = len(st.terminals) + 1
        st.terminals.append({
            "window_id": str(wid),
            "name": f"TODO {n}",
            "opened_at": time.time(),
            "log_path": st.capture_log_path or "",
        })
    else:
        existing["log_path"] = st.capture_log_path or ""
    st.capture_log_path = ""
    save_registry(st.terminals)


def _launch_todo_terminal(ctx):
    """Open a terminal under the repository root, activate the ERPLibre
    venv, and run script/todo/todo.py. The window id is captured
    CAPTURE_DELAY_SEC later by the home tick, so the deck registers
    the terminal and shows a tile that drives the todo.py menu through
    the extension's SendKeysToWindow D-Bus method."""
    st = ctx.state()
    root = str(paths.REPO_ROOT)
    venv = os.path.join(root, ".venv.erplibre", "bin", "activate")
    script = os.path.join(root, "script", "todo", "todo.py")
    if not os.path.exists(script):
        ctx.flash(False, f"todo.py not found at {script}")
        ctx.render()
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
        log_dir = str(paths.state_dir() / "todo")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"todo-{int(time.time())}.log")
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
        except Exception as e:
            print(f"todo terminal spawn failed: {e}",
                  file=sys.stderr, flush=True)
            continue
        st.capture_at = time.monotonic() + CAPTURE_DELAY_SEC
        st.capture_log_path = log_path
        ctx.flash(True)
        ctx.render()
        return
    ctx.flash(False, "No terminal found (gnome-terminal / kgx / xterm)")
    ctx.render()


# --------------------------------------------------------- todo_session


def _session_keys(geo):
    """Row 0 holds BACK, ENTER, FOCUS, FORGET on its four leftmost
    keys; every key from row 1 to the end takes a parsed menu item (or
    the numpad). None below two rows or four columns."""
    if geo.rows < 2 or geo.cols < 4:
        return None
    keys = {"back": 0, "enter": 1, "focus": 2, "forget": 3}
    keys["item_slots"] = list(range(geo.cols, geo.total_keys))
    return keys


def _active_term(st):
    return next((t for t in (st.terminals or [])
                 if str(t.get("window_id")) == str(st.window_id)), None)


def _session_items(st):
    """The latest ``[N] label`` block of the active terminal's log,
    as [(digit, label)]; [] without a log."""
    term = _active_term(st)
    log_path = term.get("log_path") if term else ''
    if not log_path:
        return []
    items, _prompt = _parse_todo_menu(_read_todo_log_tail(log_path))
    return items


def _render(ctx):
    ts = _session_keys(ctx.geo)
    if not ts:
        render.too_small(ctx)
        return
    slots = ts["item_slots"]
    items = _session_items(ctx.state())
    item_by_key = {}
    digit_by_key = {}
    if items:
        # Parsed menu wins over numpad: each item lands on the
        # next free row 1+ slot in reading order so menus larger
        # than nine entries fit on bigger decks.
        for i, (digit, label) in enumerate(items[:len(slots)]):
            item_by_key[slots[i]] = (digit, label)
    else:
        # No menu detected (free-text prompt or ASCII logo): a numpad
        # in reading order still types digits 1..9, 0 into todo.py.
        for i, d in enumerate(DIGITS):
            if i >= len(slots):
                break
            digit_by_key[slots[i]] = d
    for key in range(ctx.geo.total_keys):
        if key == ts["back"]:
            ctx.set_key(key, colors.BACK, ctx.t("BACK"))
        elif key == ts["enter"]:
            ctx.set_key(key, colors.CONFIRM, ctx.t("ENTER\n↵"))
        elif key == ts["focus"]:
            ctx.set_key(key, colors.VOL, ctx.t("FOCUS"))
        elif key == ts["forget"]:
            ctx.set_key(key, colors.CANCEL, ctx.t("FORGET"))
        elif key in item_by_key:
            digit, label = item_by_key[key]
            wrapped = wrap_button_label(label, max_chars=8, max_lines=2)
            ctx.set_key(key, colors.TODO_TERMINAL, f"[{digit}]\n{wrapped}")
        elif key in digit_by_key:
            ctx.set_key(key, colors.TODO_TERMINAL, digit_by_key[key])
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle(ctx, key):
    st = ctx.state()
    ts = _session_keys(ctx.geo)
    wid = st.window_id
    if not ts:
        ctx.home()
        return
    if key == ts["back"]:
        st.window_id = None
        ctx.home()
        return
    if not wid:
        ctx.home()
        return
    if key == ts["enter"]:
        ctx.flash(send_keys(ctx, wid, "\n"))
        ctx.render()
        return
    if key == ts["focus"]:
        ctx.flash(focus_window(ctx, wid))
        ctx.render()
        return
    if key == ts["forget"]:
        st.terminals = [
            t for t in (st.terminals or [])
            if str(t.get("window_id")) != str(wid)
        ]
        save_registry(st.terminals)
        st.window_id = None
        ctx.flash(True)
        ctx.home()
        return
    slots = ts["item_slots"]
    try:
        idx = slots.index(key)
    except ValueError:
        return
    items = _session_items(st)
    if items and idx < len(items):
        digit, _label = items[idx]
    else:
        # A slot past the last item is drawn empty and still types its
        # numpad digit.
        if idx >= len(DIGITS):
            return
        digit = DIGITS[idx]
    # The digit and a newline: todo.py's input() prompt advances on a
    # single deck press.
    ctx.flash(send_keys(ctx, wid, f"{digit}\n"))
    ctx.render()


def _tick(ctx, now):
    """Re-read the registry and the log every second, so a menu todo.py
    prints shows within a second; a terminal closed meanwhile sends the
    deck back home. The reload counts as the home refresh's: back home,
    the next one waits REFRESH_SEC."""
    st = ctx.state()
    _refresh(ctx)
    st.last_refresh = now
    wid = st.window_id
    if wid and not any(str(t.get("window_id")) == str(wid)
                       for t in (st.terminals or [])):
        st.window_id = None
        ctx.home()
        return
    ctx.render()


# ----------------------------------------------------------------- home


def _home_tick(ctx, now):
    """Every pass: the capture of a launched terminal once due (True:
    the home screen shows the new tile, or the failure flash). Every
    REFRESH_SEC: the registry reload, which the kernel's own home
    refresh then draws (False)."""
    st = ctx.state()
    ran = False
    if st.capture_at and now >= st.capture_at:
        st.capture_at = 0.0
        _capture(ctx)
        ran = True
    if now - st.last_refresh >= REFRESH_SEC:
        st.last_refresh = now
        _refresh(ctx)
    return ran


def _tile_press(ctx, term):
    """Open the page of the terminal the key showed; an entry without
    a window id does nothing."""
    wid = str(term.get("window_id") or "")
    if wid:
        ctx.state().window_id = wid
        ctx.goto(PAGE_ID)


def _setup(ctx):
    st = ctx.state()
    st.window_id = None
    st.capture_at = 0.0
    st.capture_log_path = ""
    st.terminals = load_registry()
    st.last_refresh = 0.0


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[
        Page(PAGE_ID, None, _render, _handle, tick=_tick, period=1.0)
    ],
    home_button=HomeButton(
        90,
        face=lambda ctx: KeyFace(colors.TIMER_TITLE, ctx.t("TODO")),
        press=_launch_todo_terminal,
    ),
    tiles=[
        TileProvider(
            40,
            items=lambda ctx: list(ctx.state().terminals or []),
            face=lambda ctx, term: KeyFace(
                colors.TODO_TERMINAL, term.get("name") or "TODO"
            ),
            press=_tile_press,
        )
    ],
    home_tick=_home_tick,
    home_period=0.0,
    setup=_setup,
)
