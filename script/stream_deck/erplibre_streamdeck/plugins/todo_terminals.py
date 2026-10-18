# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TODO terminals: the TODO home key opens todo.py in a terminal, a
registry remembers each terminal's window, and a page drives todo.py
through keys the extension synthesises in that window.

`state().terminals` is the registry as last read: the dashboard tiles
draw from it, never from the file. Polls read the open windows away
from the lock, every 2 s on the home screen and every second on the
session page; their store reloads the registry and drops the closed
terminals. A third poll, due once at `capture_at`, reads the window of
a terminal just opened and registers it. The registry file is shared
with the extension, which adds the terminals its own menu opens; its
format does not change."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from erplibre_streamdeck import dbus as dbus_mod
from erplibre_streamdeck import jsonfile, paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, Poll, TileProvider,
)
from erplibre_streamdeck.ui import colors, render
from erplibre_streamdeck.ui.text import wrap_button_label

PAGE_ID = "todo_session"
# The new terminal's window is read this long after the spawn's result
# reaches the deck, once the window has settled and taken the focus.
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
        jsonfile.write_atomic(path, entries, indent=None)
    except OSError as e:
        print(f"todo terminals save: {e}", file=sys.stderr, flush=True)


# --------------------------------------------------------------- D-Bus


def live_window_ids(dbus):
    """The ids of the open windows, as strings, from the extension's
    ListWindows; None when the answer is missing or unreadable."""
    try:
        r = dbus.call("ListWindows", timeout=2)
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


def focused_window_id(dbus):
    """The id of the focused window; "" when unknown."""
    r = dbus.call("GetFocusedWindowId", timeout=2)
    return (r.string or "") if r.ok else ""


def send_keys(dbus, window_id, text):
    """Synthesise `text` into the window `window_id` through the
    extension's virtual keyboard. True when it answers `true`. Runs as
    a job, outside the lock: only `dbus` and its arguments."""
    if not window_id:
        return False
    r = dbus.call("SendKeysToWindow", str(window_id), text, timeout=2)
    if r.returncode is None:
        print(f"SendKeysToWindow error: {r.stderr}",
              file=sys.stderr, flush=True)
        return False
    if not r.ok:
        print(f"SendKeysToWindow: {r.stderr}", file=sys.stderr, flush=True)
        return False
    return r.true


def focus_window(dbus, window_id):
    """Raise and focus the window; True when the extension answers
    `true`. Runs as a job, outside the lock: only `dbus` and its
    arguments."""
    return dbus.call("FocusWindowById", str(window_id), timeout=2).true


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


def _read_live():
    """The registry polls' read: live_window_ids, without Context or
    lock."""
    return live_window_ids(dbus_mod)


def _refresh(ctx, live):
    """The registry polls' store: reload the registry from disk, so the
    terminals the extension registers show here too, then drop the
    entries whose window is not in `live`. An empty or id-less
    ListWindows answer (`live` empty or None) leaves the list whole: it
    would otherwise purge a terminal registered a moment ago. The file
    is read and written here, under the lock, so a capture or a FORGET
    is never overwritten by an older copy. True when the list
    changed."""
    st = ctx.state()
    before = st.terminals
    st.terminals = load_registry()
    if live:
        kept = [
            t for t in st.terminals if str(t.get("window_id")) in live
        ]
        if len(kept) != len(st.terminals):
            st.terminals = kept
            save_registry(st.terminals)
    return st.terminals != before


def _refresh_session(ctx, live):
    """The session page's store: the registry as on the home screen;
    once the page's terminal has left it, the deck goes home. False:
    the page tick redraws the page every second."""
    st = ctx.state()
    _refresh(ctx, live)
    wid = st.window_id
    if wid and not any(str(t.get("window_id")) == str(wid)
                       for t in (st.terminals or [])):
        st.window_id = None
        ctx.home()
    return False


def _capture_due(ctx):
    """A launched terminal awaits its capture and its time has come."""
    st = ctx.state()
    return bool(st.capture_at) and time.monotonic() >= st.capture_at


def _read_capture():
    """The capture poll's read: (focused window id, open window ids);
    the open windows are not asked for without a focused window."""
    wid = focused_window_id(dbus_mod)
    return wid, (live_window_ids(dbus_mod) if wid else None)


def _capture(ctx, data):
    """The capture poll's store: register the focused window as the
    terminal just opened, or flash ERR without one. The entry is
    appended to the list in memory, which is not re-read first, and the
    list is saved. True: the deck shows the new tile or the flash."""
    st = ctx.state()
    st.capture_at = 0.0
    wid, live = data
    if not wid:
        ctx.flash(False, "Could not capture TODO terminal window id")
        return True
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
    return True


def _spawn_terminal(terminals):
    """Start the first of `terminals` (argv lists) found on the PATH;
    True once one has started. Runs as a job, outside the lock: only
    its argument."""
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
        return True
    return False


def _launched(log_path):
    """then() of the launch: once a terminal has started, the capture
    of its window is armed CAPTURE_DELAY_SEC from now, with the log it
    writes, and OK flashes; ERR when none could start."""

    def then(ctx, started, error):
        if started and error is None:
            st = ctx.state()
            st.capture_at = time.monotonic() + CAPTURE_DELAY_SEC
            st.capture_log_path = log_path
            ctx.flash(True)
        elif error is None:
            ctx.flash(
                False, "No terminal found (gnome-terminal / kgx / xterm)"
            )
        else:
            ctx.flash(False)
        ctx.render()

    return then


def _launch_todo_terminal(ctx):
    """Open a terminal under the repository root, activate the ERPLibre
    venv, and run script/todo/todo.py. The command and its log path are
    built here; the terminal starts as a job. CAPTURE_DELAY_SEC after
    its result, the capture poll reads the window id, so the deck
    registers the terminal and shows a tile that drives the todo.py
    menu through the extension's SendKeysToWindow D-Bus method."""
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
    ctx.run_blocking(
        lambda: _spawn_terminal(terminals), _launched(log_path)
    )


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


def _sent(ctx, ok, error):
    """then() of a key sent to the terminal or of its focus: OK or ERR,
    then the page again."""
    ctx.flash(bool(ok) and error is None)
    ctx.render()


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
    dbus = ctx.dbus
    if key == ts["enter"]:
        ctx.run_blocking(lambda: send_keys(dbus, wid, "\n"), _sent)
        return
    if key == ts["focus"]:
        ctx.run_blocking(lambda: focus_window(dbus, wid), _sent)
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
    text = f"{digit}\n"
    ctx.run_blocking(lambda: send_keys(dbus, wid, text), _sent)


def _tick(ctx, now):
    """Draw the page again every second: its render re-reads the log,
    so a menu todo.py prints shows within a second."""
    ctx.render()


# ----------------------------------------------------------------- home


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
    polls=[
        Poll(REFRESH_SEC, lambda ctx: ctx.page == "idle", _read_live,
             _refresh),
        Poll(1.0, lambda ctx: ctx.page == PAGE_ID, _read_live,
             _refresh_session),
        Poll(0.0, _capture_due, _read_capture, _capture),
    ],
    setup=_setup,
)
