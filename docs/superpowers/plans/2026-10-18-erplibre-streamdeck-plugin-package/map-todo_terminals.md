# B2 map: plugin `todo_terminals`

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD
b61156bf). Every range below was checked with `sed -n` / `grep -n`.
Target: `script/stream_deck/erplibre_streamdeck/plugins/todo_terminals.py`.

## 1. Module-level names owned by the domain

| Name | Lines | Target |
|---|---|---|
| `TODO_TERMINALS_PATH` (XDG_STATE_HOME/erplibre-home/todo_terminals.json, evaluated at import) | 200-203 | plugin: `REGISTRY_PATH = os.path.join(paths.STATE_DIR, "todo_terminals.json")` (needs `paths.STATE_DIR` = `$XDG_STATE_HOME or ~/.local/state` + `/erplibre-home`, shared with claude/mpv 192-199) |
| `COLOR_TODO_TERMINAL = (140, 90, 50)` | 205 | plugin constant (only user: this domain, lines 2838, 2841, 3094) — or `ui/colors.py` if the colour table must stay whole |
| `_load_todo_terminals()` | 236-248 | plugin `load_registry()` |
| `_save_todo_terminals(entries)` | 251-260 | plugin `save_registry(entries)` (tmp + `os.replace`, stderr line `todo terminals save: {e}`) |
| `_list_mutter_window_ids()` | 263-291 | plugin `live_window_ids(dbus)` (only callers: 1717, 1752) |
| `_get_focused_window_id()` | 294-310 | plugin `focused_window_id(dbus)` (only caller: 1712) |
| `_ANSI_RE` | 313 | plugin |
| `_TODO_MENU_RE` | 314 | plugin |
| `_strip_ansi(text)` | 317-318 | plugin (only caller: 331) |
| `_parse_todo_menu(text)` | 321-350 | plugin, keep the name `_parse_todo_menu` (tested by `script/stream_deck/test_erplibre_streamdeck_chunks.py:244-276`, `TodoMenuParseTest`, 4 tests) |
| `_read_todo_log_tail(path, max_bytes=8192)` | 353-364 | plugin |
| `_send_keys_to_window(window_id, text)` | 367-391 | plugin `send_keys(dbus, wid, text)` (only callers: 2863, 2911) |
| `MODE_TODO_SESSION = "todo_session"` | 541 | plugin `PAGE = "todo_session"` |
| Labels `'TODO'`, `'ENTER\n↵'`, `'FORGET'` | 163-165 | stay in `ui/i18n.py` table (`'FOCUS'` 167 is shared with claude_sessions, line 2982) |

Shared names this domain READS but does not own (stay in kernel/ui):
`DBUS_DEST/PATH/IFACE` 546-548 and `_parse_gdbus_string_tuple` 593-609
(-> `dbus.py`); `COLOR_EMPTY` 46, `COLOR_TIMER_TITLE` 51, `COLOR_BACK` 54,
`COLOR_CONFIRM` 58, `COLOR_CANCEL` 59, `COLOR_VOL` 63, `COLOR_ERR` 104
(-> `ui/colors.py`); `_wrap_button_label` 502-526 (-> `ui/text.py`);
`_t` 181-184 (-> `ui/i18n.py`); `set_key` 1483 (-> `ui/render.py`);
`RESULT_FLASH_SEC = 0.5` 110 (kernel).

## 2. Tiler methods owned

| Method | Lines | self.* read | self.* written | Calls into other domains / kernel |
|---|---|---|---|---|
| `_launch_todo_terminal` | 1643-1709 | — | `_pending_todo_capture_at`, `_pending_todo_log_path`, `last_result`, `result_time` | `_flag_err` (1763-1770, kernel flash), `render` |
| `_capture_pending_todo_terminal` | 1711-1740 | `todo_terminals`, `_pending_todo_log_path` | `todo_terminals`, `_pending_todo_log_path` | `_flag_err`, `render` (only on failure), `_get_focused_window_id`, `_list_mutter_window_ids`, `_save_todo_terminals` |
| `_refresh_todo_terminals` | 1742-1761 | `todo_terminals` | `todo_terminals` | `_load_todo_terminals`, `_list_mutter_window_ids`, `_save_todo_terminals` |
| `_todo_session_keys` | 2766-2776 | `rows`, `cols`, `total_keys` | — | — |
| `_todo_active_term` | 2778-2781 | `todo_terminals`, `_todo_session_window_id` | — | — |
| `_todo_session_items` | 2783-2792 | (via `_todo_active_term`) | — | `_parse_todo_menu`, `_read_todo_log_tail` |
| `_render_todo_session` | 2794-2844 | `rows`, `cols`, `total_keys`, `deck` | — | `set_key`, `_t`, `_wrap_button_label` |
| `_handle_todo_session_key` | 2846-2914 | `_todo_session_window_id`, `todo_terminals` | `mode`, `_todo_session_window_id`, `todo_terminals`, `last_result`, `result_time` | `render`, `_send_keys_to_window`, inline gdbus `FocusWindowById` (2870-2880), `_save_todo_terminals` |

Fragments inside shared methods:

| Fragment | Lines | Becomes |
|---|---|---|
| `__init__`: state attrs + comment | 1538-1543 | `setup` |
| `_compute_idle_buttons`: `"todo"` in `order` (9th, index 8) | 1601-1616 (list at 1602-1605) | `HomeButton(order=90)`; `home.py` allocation |
| `_compute_claude_buttons`: `self.todo_key` in the `used` set | 1869-1873 | `home.py` (home keys are excluded from the dashboard) |
| `handle_key` dispatch branch | 2011-2012 | kernel dispatch by page id |
| `_handle_idle_key` TODO button | 2154-2156 | `HomeButton.press` |
| `_handle_idle_key` dashboard tail (TODO index) | 2205-2213 (inside 2174-2213) | `TileProvider.press` |
| `_render_mode` branch | 2732-2733 | kernel render by page id |
| `_render_idle` TODO tile allocation | 3023, 3040-3044 | `TileProvider.items` + `home.py` |
| `_render_idle` TODO button face | 3071-3072 | `HomeButton.face` |
| `_render_idle` TODO tile face | 3092-3095 | `TileProvider.face` |
| `loop` TODO session poll | 3501-3515 | `Page.tick`, period 1.0 |
| `loop` idle: pending capture | 3522-3526 | `home_tick` |
| `loop` idle: registry refresh (with `_refresh_timers`, one render) | 3527-3531 (`_refresh_todo_terminals` at 3529) | `home_tick` |

## 3. Per-plugin state -> `ctx.state("todo_terminals")`

| Today | Init value | Line | New name |
|---|---|---|---|
| `self._todo_session_window_id` | `None` | 1538 | `st.window_id` |
| `self._pending_todo_capture_at` | `0.0` | 1541 | `st.capture_at` |
| `self._pending_todo_log_path` | `''` | 1542 | `st.capture_log_path` |
| `self.todo_terminals` | `_load_todo_terminals()` (disk read at start) | 1543 | `st.terminals` (filled by `setup`) |
| (new) | `0.0` | — | `st.last_refresh` — only if the home_tick gates its own 2 s refresh (see Trap 3) |
| `self.todo_key` | set by `_compute_idle_buttons` | 1606-1616 | NOT plugin state: `home.py` owns key allocation |

## 4. Pages

One page.

`Page(id="todo_session", keys=_session_keys, render=_render,
handle=_handle, tick=_tick, period=1.0)`

- **keys** — `_todo_session_keys` 2766-2776: `None` when
  `rows < 2 or cols < 4`; else `{"back": 0, "enter": 1, "focus": 2,
  "forget": 3, "item_slots": list(range(cols, total_keys))}`.
- **render** — `_render_todo_session` 2794-2844.
  - Deck too small (2796-2804): key 0 `COLOR_BACK, _t("BACK")`; key
    `total_keys // 2` `COLOR_ERR, _t("DECK\nTOO\nSMALL")`; others
    `COLOR_EMPTY, ""`.
  - Items = parsed menu of the active terminal's `log_path` tail
    (2783-2792). Parsed menu wins (2810-2815): `items[:len(slots)]`
    on `slots[i]`, face `COLOR_TODO_TERMINAL,
    f"[{digit}]\n{_wrap_button_label(label, max_chars=8,
    max_lines=2)}"`. Else numpad: `"1234567890"` on the
    first ≤10 slots (2816-2824), face `COLOR_TODO_TERMINAL, d`.
  - Row 0: back `COLOR_BACK _t("BACK")`, enter `COLOR_CONFIRM
    _t("ENTER\n↵")`, focus `COLOR_VOL _t("FOCUS")`, forget
    `COLOR_CANCEL _t("FORGET")` (2825-2844, item/digit faces 2834-2842). No icons anywhere.
- **handle** — `_handle_todo_session_key` 2846-2914, in order:
  1. keys None -> home + render (2849-2852);
  2. back -> `window_id=None`, home (2853-2857);
  3. `window_id` falsy -> home (2858-2861);
  4. enter -> `SendKeysToWindow(wid, "\n")`, flash ok/err, render,
     stay (2862-2867);
  5. focus -> gdbus `FocusWindowById(wid)`, ok = rc 0 and "true" in
     stdout, flash, render, stay (2868-2884);
  6. forget -> drop wid from registry, save, `window_id=None`, flash
     ok, home (2885-2895);
  7. key not in item_slots -> silent return, no render (2896-2900);
  8. item slot: parsed items re-read; `digit = items[idx][0]` when
     `items and idx < len(items)`, else `"1234567890"[idx]` (return when
     `idx >= 10`); `SendKeysToWindow(wid, f"{digit}\n")`, flash, render,
     stay (2901-2914).
- **tick** — loop branch 3501-3515, gated at 3506 `now -
  last_idle_refresh >= 1.0`: `_refresh_todo_terminals()`; when `window_id` is set and no
  registry entry has `str(window_id)` -> `window_id=None`, mode idle;
  then ONE `render()` (of whichever page is now current).
- Entry: only from the dashboard tile (2207-2212): `window_id = wid`,
  mode `todo_session`, render. No flash.

## 5. Home contributions

**HomeButton(order=90)** — 9th in `order` (1602-1605).
- face (3071-3072): `KeyFace(COLOR_TIMER_TITLE, ctx.t("TODO"))`, no icon.
- press (2154-2156): `_launch_todo_terminal` (1643-1709).

**Fixture**: none.

**TileProvider(order=40)** — after mpv, claude, running timers
(3024-3044 cursor walk; tap mirror 2174-2213).
- items (3040-3044): `st.terminals` as held in memory (NOT re-read from
  disk at render time), every entry, in registry order.
- face (3092-3095): `KeyFace(COLOR_TODO_TERMINAL,
  term.get("name") or "TODO")` — raw "TODO", not `_t`, no icon.
- press (2207-2213): `wid = str(term.get("window_id") or "")`; when
  `wid`: `st.window_id = wid; ctx.goto("todo_session")`; when empty:
  return with no render and no flash.

**home_tick** (3516-3531, idle branch of the loop):
- every pass (0.3 s): when `capture_at and now >= capture_at`:
  `capture_at = 0.0`; capture (1711-1740); render (3526);
- every 2.0 s (shared `last_idle_refresh`): `_refresh_timers()` then
  `_refresh_todo_terminals()` then ONE render (3527-3531).

## 6. External side effects to stub in characterization tests

| Effect | Where | Detail |
|---|---|---|
| env `XDG_STATE_HOME` | 200-203 (import time), 1670-1672 (call time) | registry path frozen at import; log dir read per launch. Set env before import, or patch the owning module's constant (Risk 3). |
| registry read | 239-248 | `os.path.exists`, `open(..., "r")`, `json.load`; non-list -> `[]`; `OSError/JSONDecodeError` -> `[]` |
| registry write | 254-260 | `os.makedirs(dirname, exist_ok=True)`, write `<path>.tmp`, `json.dump(entries)` (default separators), `os.replace`; `OSError` -> stderr `todo terminals save: {e}` |
| gdbus ListWindows | 265-291 | `subprocess.run(["gdbus","call","--session","--dest",DBUS_DEST,"--object-path",DBUS_PATH,"--method",f"{DBUS_IFACE}.ListWindows"], capture_output=True, text=True, timeout=2)`; rc≠0/unparsable/non-list/exception -> `None`; returns `{str(w["id"])}` for truthy ids |
| gdbus GetFocusedWindowId | 296-310 | same argv shape, `.GetFocusedWindowId`, timeout 2; rc≠0/exception -> `""` |
| gdbus SendKeysToWindow | 369-391 | argv `[..., f"{DBUS_IFACE}.SendKeysToWindow", str(window_id), text]` with `text` RAW (`"\n"` or `"<d>\n"`), timeout 2; ok = `"true" in stdout.lower()`; rc≠0 -> stderr `SendKeysToWindow: {stderr}`; exception -> stderr `SendKeysToWindow error: {e}`; falsy wid -> `False` without call |
| gdbus FocusWindowById | 2870-2880 | inline `subprocess.run([...,"--method",f"{DBUS_IFACE}.FocusWindowById", str(wid)], capture_output=True, text=True, timeout=2)`; ok = rc 0 and `"true" in stdout.lower()`; exception -> False |
| repo root | 1650-1651 | `abspath(join(dirname(abspath(__file__)), "..", ".."))` -> `paths.REPO_ROOT` |
| file checks | 1652-1657, 1664-1666 | `os.path.exists(<root>/script/todo/todo.py)` (missing -> `_flag_err(f"todo.py not found at {script}")` + render); `os.path.exists(<root>/.venv.erplibre/bin/activate)` chooses `inner` |
| `shutil.which` | 1668, 1687 | `"script"`; then `"gnome-terminal"`, `"kgx"`, `"xterm"` in that order |
| log dir | 1669-1673 | `os.makedirs(<state>/erplibre-home/todo, exist_ok=True)` |
| `time.time()` | 1675, 1734 | log name `todo-{int(time.time())}.log`; `opened_at` |
| Popen | 1680-1708 (argv list 1680-1685, loop 1687-1707) | `inner = f"source '{venv}' && python3 -u '{script}'"` (or `f"python3 -u '{script}'"`); with `script`: `cmd = f"script -fqc {shlex.quote(inner)} {shlex.quote(log_path)}"`, else `cmd = inner`, `log_path = ''`. argv: `["gnome-terminal","--working-directory",root,"--","bash","-lc",cmd]`, `["kgx","--working-directory",root,"--","bash","-lc",cmd]`, `["xterm","-e",f"cd '{root}' && {cmd}"]`; kwargs `stdin/stdout/stderr=subprocess.DEVNULL, start_new_session=True`. Popen exception -> stderr `todo terminal spawn failed: {e}`, try next; none -> `_flag_err("No terminal found (gnome-terminal / kgx / xterm)")` + render |
| `time.monotonic()` | 1699 (`capture_at = now + 1.0`), 1702 (flash), 2865, 2882, 2894, 2913 (flash), 3472 (loop `now`) | |
| log tail read | 353-364 | `os.path.exists`, `os.path.getsize`, `open(path,"rb")`, `seek(size-8192)` when larger, `decode("utf-8", errors="replace")`; `OSError` -> `''` |
| stderr via `_flag_err` | 1655, 1714, 1708 | `[erplibre-home] {reason}`; reasons: `todo.py not found at {script}`, `Could not capture TODO terminal window id`, `No terminal found (gnome-terminal / kgx / xterm)` |
| translator calls | — | none |
| `_t` calls | 2799, 2801, 2827, 2829, 2831, 2833, 3072 | `BACK`, `DECK\nTOO\nSMALL`, `ENTER\n↵`, `FOCUS`, `FORGET`, `TODO` |

Suggested reference inputs: registry of 2 entries (one with `log_path`
to a fixture log holding an ANSI-coloured `[1]..[3]` menu, one without),
an entry with empty `window_id`, ListWindows answering both ids, then
one id gone (auto-return), geometries 3×2 (page = DECK TOO SMALL, no
TODO button: 3 cols, 2 rows, no overflow), 4×2, 5×3 (TODO overflows to
key 5), 8×4 (TODO at key 8 -> row 1 col 0).

## 7. Draft plugin module

Assumes `ctx.dbus.call(method, *args, timeout=2)` returns an object with
`returncode` and `stdout` (a `CompletedProcess`) and may raise, and
`dbus.parse_string_tuple` is the moved `_parse_gdbus_string_tuple`
(see Trap 11). `ctx.flash` only sets the flash (as `_flag_err` does);
the caller renders.

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TODO terminals: the TODO home button opens todo.py in a terminal,
the registry remembers each terminal's window, and a page drives
todo.py through keys synthesised by the extension."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from erplibre_streamdeck import paths
from erplibre_streamdeck.dbus import parse_string_tuple
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, TileProvider,
)
from erplibre_streamdeck.ui.colors import (
    COLOR_BACK, COLOR_CANCEL, COLOR_CONFIRM, COLOR_EMPTY, COLOR_ERR,
    COLOR_TIMER_TITLE, COLOR_VOL,
)
from erplibre_streamdeck.ui.text import wrap_button_label

ID = "todo_terminals"
PAGE = "todo_session"
COLOR_TODO_TERMINAL = (140, 90, 50)
REGISTRY_PATH = os.path.join(paths.STATE_DIR, "todo_terminals.json")
CAPTURE_DELAY_SEC = 1.0
HOME_REFRESH_SEC = 2.0
DIGITS = "1234567890"

_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\r')
_TODO_MENU_RE = re.compile(r'^\s*\[(\d+)\]\s+(.+?)\s*$')


# ---- registry (lines 236-260) -------------------------------------
def load_registry():
    ...  # body of _load_todo_terminals, REGISTRY_PATH


def save_registry(entries):
    ...  # body of _save_todo_terminals, REGISTRY_PATH


# ---- D-Bus (lines 263-310, 367-391, 2870-2880) ---------------------
def live_window_ids(dbus):
    try:
        res = dbus.call("ListWindows", timeout=2)
        if res.returncode != 0:
            return None
        payload = parse_string_tuple(res.stdout)
        if not payload:
            return None
        windows = json.loads(payload)
        if not isinstance(windows, list):
            return None
        return {str(w.get("id")) for w in windows if w.get("id")}
    except Exception:
        return None


def focused_window_id(dbus):
    try:
        res = dbus.call("GetFocusedWindowId", timeout=2)
        if res.returncode != 0:
            return ""
        return parse_string_tuple(res.stdout) or ""
    except Exception:
        return ""


def send_keys(dbus, window_id, text):
    if not window_id:
        return False
    try:
        res = dbus.call("SendKeysToWindow", str(window_id), text,
                        timeout=2)
        if res.returncode != 0:
            print(f"SendKeysToWindow: {res.stderr}",
                  file=sys.stderr, flush=True)
            return False
        return "true" in res.stdout.lower()
    except Exception as e:
        print(f"SendKeysToWindow error: {e}", file=sys.stderr, flush=True)
        return False


def focus_window(dbus, window_id):
    try:
        res = dbus.call("FocusWindowById", str(window_id), timeout=2)
        return res.returncode == 0 and "true" in res.stdout.lower()
    except Exception:
        return False


# ---- todo.py log (lines 317-364) -----------------------------------
def _strip_ansi(text):
    return _ANSI_RE.sub('', text or '')


def _parse_todo_menu(text):
    ...  # unchanged, lines 321-350


def _read_todo_log_tail(path, max_bytes=8192):
    ...  # unchanged, lines 353-364


# ---- registry upkeep (lines 1711-1761) -----------------------------
def _refresh(ctx, st):
    st.terminals = load_registry()
    live = live_window_ids(ctx.dbus)
    if not live:
        return
    before = len(st.terminals)
    st.terminals = [t for t in st.terminals
                    if str(t.get("window_id")) in live]
    if len(st.terminals) != before:
        save_registry(st.terminals)


def _capture(ctx, st):
    """Return True when the screen must be redrawn (failure flash)."""
    wid = focused_window_id(ctx.dbus)
    if not wid:
        ctx.flash(False, "Could not capture TODO terminal window id")
        return True
    ...  # lines 1717-1740 on st.terminals / st.capture_log_path
    return False


def _launch(ctx):
    st = ctx.state(ID)
    root = str(paths.REPO_ROOT)
    ...  # lines 1652-1708; on spawn:
    #   st.capture_at = time.monotonic() + CAPTURE_DELAY_SEC
    #   st.capture_log_path = log_path
    #   ctx.flash(True); ctx.render(); return
    # failures: ctx.flash(False, reason); ctx.render()


# ---- page todo_session (lines 2766-2914) ---------------------------
def _session_keys(geo):
    if geo.rows < 2 or geo.cols < 4:
        return None
    return {"back": 0, "enter": 1, "focus": 2, "forget": 3,
            "item_slots": list(range(geo.cols, geo.total_keys))}


def _active_term(st):
    return next((t for t in (st.terminals or [])
                 if str(t.get("window_id")) == str(st.window_id)), None)


def _items(st):
    term = _active_term(st)
    log_path = term.get("log_path") if term else ''
    if not log_path:
        return []
    items, _prompt = _parse_todo_menu(_read_todo_log_tail(log_path))
    return items


def _render(ctx):
    ...  # lines 2795-2844 with ctx.set_key / ctx.t / ctx.geo


def _handle(ctx, key):
    st = ctx.state(ID)
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
        ctx.flash(send_keys(ctx.dbus, wid, "\n"))
        ctx.render()
        return
    if key == ts["focus"]:
        ctx.flash(focus_window(ctx.dbus, wid))
        ctx.render()
        return
    if key == ts["forget"]:
        st.terminals = [t for t in (st.terminals or [])
                        if str(t.get("window_id")) != str(wid)]
        save_registry(st.terminals)
        st.window_id = None
        ctx.flash(True)
        ctx.home()
        return
    ...  # lines 2896-2914 (item slot / numpad digit), flash, render


def _tick(ctx, now):
    st = ctx.state(ID)
    _refresh(ctx, st)
    wid = st.window_id
    if wid and not any(str(t.get("window_id")) == str(wid)
                       for t in (st.terminals or [])):
        st.window_id = None
        ctx.home()
        return
    ctx.render()


# ---- home ------------------------------------------------------------
def _home_tick(ctx, now):
    """Return True when the home screen must be redrawn."""
    st = ctx.state(ID)
    dirty = False
    if st.capture_at and now >= st.capture_at:
        st.capture_at = 0.0
        _capture(ctx, st)
        dirty = True                      # line 3526 renders always
    if now - st.last_refresh >= HOME_REFRESH_SEC:
        _refresh(ctx, st)
        st.last_refresh = now
        dirty = True
    return dirty


def _tile_press(ctx, term):
    wid = str(term.get("window_id") or "")
    if wid:
        ctx.state(ID).window_id = wid
        ctx.goto(PAGE)


def _setup(ctx):
    st = ctx.state(ID)
    st.window_id = None
    st.capture_at = 0.0
    st.capture_log_path = ""
    st.terminals = load_registry()
    st.last_refresh = 0.0


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page(id=PAGE, keys=_session_keys, render=_render,
                handle=_handle, tick=_tick, period=1.0)],
    home_buttons=[HomeButton(
        order=90,
        face=lambda ctx: KeyFace(COLOR_TIMER_TITLE, ctx.t("TODO")),
        press=_launch)],
    tiles=[TileProvider(
        order=40,
        items=lambda ctx: list(ctx.state(ID).terminals or []),
        face=lambda ctx, t: KeyFace(COLOR_TODO_TERMINAL,
                                    t.get("name") or "TODO"),
        press=_tile_press)],
    home_tick=_home_tick,
    home_period=0.0,
    setup=_setup,
)
```

Note: `ID` hard-coded duplicates the file stem the loader assigns; the
alternative is a `ctx.state()` with no argument returning the calling
plugin's namespace, or `__name__.rsplit(".", 1)[-1]`. Pick one rule for
all plugins.

## 8. Traps

1. **Flash suppresses every tick, the pending capture included.** Loop
   3479-3482: `if self.last_result:` is the head of the whole `elif`
   chain, so while a flash is up (0.5 s) nothing else runs, and
   `last_result` is cleared only by a render after expiry (2696-2702).
   The kernel must keep "flash active -> skip page tick AND home ticks",
   not just "flash expired -> render". The launch flash (0.5 s) ends
   before `capture_at` (+1.0 s), so the capture normally runs on time.
2. **One clock shared by two cadences.** `last_idle_refresh` gates both
   the todo_session poll (1.0 s, 3506) and the idle refresh (2.0 s,
   3527), and each writes it (3515, 3531). With per-page / per-plugin
   clocks in the kernel, entering or leaving the page shifts the next
   refresh by < 2 s. Not visible (each transition renders anyway);
   accept and note in the parity test that ticks are compared by
   state, not by timestamp.
3. **home_tick needs two cadences and today renders conditionally.**
   The capture is polled every pass (0.3 s) and renders only when due;
   the registry refresh is every 2 s. With the spec's single
   `home_period` and "render once if any ran", `home_period=0.0` would
   render the home screen every 0.3 s (each render runs `wpctl`, reads
   the mpv/claude state dirs and the layouts file): a behaviour and load
   change. Proposal (spec amendment, kernel side): `home_tick` returns
   a bool, and the kernel renders once if any returned true. The plugin
   uses `home_period=0.0` and gates its own 2 s refresh with
   `st.last_refresh`. Today two renders can happen in one pass (3526
   then 3530); one render gives the same final screen.
4. **The 2 s home render is shared.** The same render refreshes the mic
   indicator (sound fixture) and timer tiles. If timers and
   todo_terminals are both off, nothing triggers the 2 s home render
   and the mic indicator goes stale. Kernel/home owner: either keep a
   kernel 2 s home render or let the sound plugin's home_tick ask for
   it. Out of this plugin's hands; flag to the kernel plan.
5. **Page keys may be None.** `_todo_session_keys` returns `None` below
   2 rows or 4 cols, and render/handle branch on it (DECK TOO SMALL,
   any key -> home). `Page.keys: Callable[[Geometry], dict]` must allow
   `None` (or `{}`), and the kernel must not treat it as an error. The
   page is reachable on a 3×2 deck: the dashboard tile exists there
   (row 1) although the TODO button does not.
6. **Blank item key still types.** When a menu is parsed but the pressed
   slot is past the last item, the handler falls back to
   `DIGITS[idx]` (2902-2908) and sends it, though the key is drawn
   empty. Keep it; pin it in a characterization test.
7. **Tile with empty `window_id`** is drawn (name or "TODO") but a tap
   does nothing: no page change, no render, no flash (2209-2213). Keep.
8. **Tile items come from memory, never from disk at render.** The
   registry is reloaded only by the 2 s home refresh, the 1 s page tick
   and the capture; `items()` must return `st.terminals` and not call
   `load_registry()`.
9. **Capture appends to the in-memory list without re-reading the file**
   (1717-1740), so it can overwrite an entry the extension wrote in the
   last 2 s (`script/gnome-extension/erplibre_home/indicators/
   erplibre.js:326-380`, same format: `window_id` string, `name`
   `TODO <n>`, `opened_at`, `log_path`). Preserve; on-disk format is a
   contract the spec keeps.
10. **Flash raised from a tick.** `_capture_pending_todo_terminal`
    flashes ERR from the loop, not from a key; the overlay lands on
    `last_press_key` (normally the TODO button pressed ~1 s earlier).
    `ctx.flash` must work outside `handle` and use the kernel's
    `last_press_key`. The capture failure leaves
    `_pending_todo_log_path` set (1713-1716); harmless, preserve.
11. **D-Bus client contract.** All four calls use `timeout=2` (the
    availability check uses 3), raw argv strings (gdbus falls back to
    a plain string for an `s` argument that does not parse, which is
    how `"1\n"` and `"\n"` pass), and two callers read `"true" in
    stdout.lower()` while two parse the string tuple. `ctx.dbus.call`
    must take a per-call timeout, pass args through unquoted, and
    expose `returncode`/`stdout`/`stderr` (or the plugin keeps
    `subprocess.run` and only takes DEST/PATH/IFACE from `dbus.py`).
    Tests patch `erplibre_streamdeck.dbus` (Risk 3), so the plugin must
    reach gdbus only through it.
12. **Journal text changes.** `_flag_err` writes `[erplibre-home]
    <reason>`; through `ctx.flash(False, reason)` + `ctx.log` it will
    carry the plugin-id prefix. Direct stderr prints stay as is
    (`todo terminals save:`, `todo terminal spawn failed:`,
    `SendKeysToWindow:`). Not on the deck; acceptable, say so in the
    commit body.
13. **Repo root: `abspath` vs `resolve`.** Today `os.path.abspath` (no
    symlink resolution); `paths.REPO_ROOT` uses `Path.resolve()`. On a
    symlinked checkout the `--working-directory` and the quoted paths
    in `cmd` change text. Characterization tests must build expected
    argv from the module constant, not a literal.
14. **Import-time path.** `TODO_TERMINALS_PATH` is frozen at import from
    `XDG_STATE_HOME`; the log dir (1669-1672) is read at call time.
    Keep both behaviours (`REGISTRY_PATH` from `paths.STATE_DIR` at
    import, log dir computed in `_launch`, or from `paths` too — same
    value unless env changes at run time). Tests patch
    `plugins.todo_terminals.REGISTRY_PATH`.
15. **Auto-return renders once.** Today the tick sets mode idle and then
    calls one `render()` (3512-3514); `ctx.home()` must render exactly
    once and not also let the kernel render the page afterwards.
16. **Dashboard tap semantic change** (spec "the one change in
    behaviour"): today the TODO index is `idx - len(mpv) - len(claude) -
    len(running timers)` from FRESH loads (2180-2206); after B2 the tap
    reads the term dict stored at the last render. `window_id` is read
    from that dict, i.e. what the key showed.
17. **Existing test to move.** `TodoMenuParseTest`
    (`script/stream_deck/test_erplibre_streamdeck_chunks.py:244-276`)
    calls `GT._parse_todo_menu`; in step 3 it moves to
    `test/test_erplibre_streamdeck_*.py` and imports
    `erplibre_streamdeck.plugins.todo_terminals._parse_todo_menu`.
18. **Label table stays central.** `'TODO'`, `'ENTER\n↵'`, `'FORGET'`
    (163-165) are used only here, `'FOCUS'` (167) also by the Claude
    page; keep all in `ui/i18n.py` unless the kernel plan adds
    per-plugin label tables.
