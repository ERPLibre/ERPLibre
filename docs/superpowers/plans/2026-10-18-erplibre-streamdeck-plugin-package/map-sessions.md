# B2 map: sessions domain (plugins `claude_sessions`, `mpv_sessions`)

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD
b61156bf). Every range below was checked with `grep -n` / `sed -n`.
Abbreviation: `M` = the monolith file.

---

## 1. Module-level names owned by the domain

| Name | Lines in M | Used at (M) | Target |
|---|---|---|---|
| `_DECK_LABELS['fr']` entries `'FOCUS'`, `'ACCEPT\n↵'`, `'SET\nWIN'` (comment l.166) | 166-169 | 2982, 2987, 2990 | stay in `ui/i18n.py` (the table is not split per plugin) |
| `_DECK_LABELS['fr']` entries `'PLAY\nPAUSE'`, `'VOL\n−'` (U+2212), `'VOL\n+'` (comment l.170) | 170-173 | 2937, 2941, 2943 | `ui/i18n.py` |
| shared labels `'BACK'`, `'QUIT'`, `'KILL'` | 127-129 | 2935/2980, 2939, 2992 | `ui/i18n.py` (shared) |
| `COLOR_CLAUDE_ACTIVE/WORKING/AWAIT_STOP/AWAIT_NOTIFY` + comment | 186-190 | 442-447, 2986 | `plugins/claude_sessions.py` (only user). Alternative: `ui/colors.py`; either keeps pixels identical |
| `CLAUDE_STATE_DIR` | 192-195 | 400, 402, 405 | `paths.STATE_HOME` (= `$XDG_STATE_HOME or ~/.local/state` + `erplibre-home`, evaluated at import like today) in `paths.py`; plugin module constant `STATE_DIR = os.path.join(paths.STATE_HOME, "claude")` |
| `MPV_STATE_DIR` | 196-199 | 212, 214, 217 | same, `"mpv"`, in `plugins/mpv_sessions.py` |
| `COLOR_MPV_ACTIVE` | 204 | 2937, 2941, 2943, 3082 | `plugins/mpv_sessions.py` |
| comment on `COLOR_TODO_TERMINAL` "distinct from claude/mpv" | 205 | — | todo domain; comment stays true |
| `_load_mpv_sessions()` | 208-233 | 2180, 2920, 3008 | `plugins/mpv_sessions.py` `load_sessions()` |
| `_load_claude_sessions()` | 394-437 | 1782†, 1826†, 2187, 2954, 3009 | `plugins/claude_sessions.py` `load_sessions()` |
| `_claude_color(session)` | 440-447 | 2985, 3086 (+ tests) | `plugins/claude_sessions.py` |
| `_claude_label(session, max_chars=18)` | 450-461 | 3087 (+ tests) | `plugins/claude_sessions.py` |
| `_chunk_text_for_cells(text, num_cells, per_cell=12)` | 464-487 | 2930, 2975 | `ui/text.py` (shared by both plugins) |
| `_wrap_chunk(text, line_chars=6)` | 490-499 | 2946, 2995, 3083 | `ui/text.py` |
| `MODE_CLAUDE_SESSION`, `MODE_MPV_SESSION` | 539-540 | 1789†, 2007, 2009, 2183, 2192, 2728, 2730 | disappear: page ids `"claude_session"`, `"mpv_session"` as plugin constants `PAGE_ID` |
| `DBUS_DEST/PATH/IFACE` | 546-548 | NOT used by this domain: 1796-1800 and 2057-2062 hard-code the same three strings | `dbus.py` (kernel) |
| `_icon_robot(draw, w, h)` | 1357-1393 | via `_ICONS["robot"]` l.1407; used 2983, 3087 | `ui/icons.py` (shared painter table) |

† = call site inside a dead helper (section 2).

Shared colours used by these pages (not owned, go to `ui/colors.py`):
`COLOR_EMPTY` 46, `COLOR_TITLE` 50, `COLOR_CANCEL` 59, `COLOR_VOL` 63,
`COLOR_LAYOUT_TITLE` 67.

Existing tests of these helpers:
`script/stream_deck/test_erplibre_streamdeck_chunks.py`
`ChunkTextForCellsTest` 136-162, `WrapChunkTest` 163-178,
`ClaudeColorTest` 179-200, `ClaudeLabelTest` 201-216. They move to
`test/` at the switch (spec step 3) and must import from `ui.text` and
`plugins.claude_sessions`.

---

## 2. Tiler methods owned

| Method | Lines | Reads self.* | Writes self.* | Other-domain / kernel calls |
|---|---|---|---|---|
| `_enter_claude_session_mode(key)` **DEAD** (no caller) | 1772-1790 | `claude_keys` | `_claude_session_sid`, `mode` | `_load_claude_sessions`, `render` |
| `_call_claude_dbus(method, sid)` | 1792-1817 | — | — | `subprocess.check_output` gdbus; stderr prints |
| `_focus_claude_for_key(key)` **DEAD** (no caller) | 1819-1832 | `claude_keys` | — | `_load_claude_sessions`, `_call_claude_dbus` |
| `_compute_claude_session_keys()` | 1834-1848 | `cols` | `claude_session_keys` | called once from `_compute_idle_buttons` l.1640 |
| `_compute_mpv_session_keys()` | 1850-1862 | `cols`, `rows` | `mpv_session_keys` | called once from l.1641 |
| `_compute_claude_buttons()` (misnamed: it computes the WHOLE dashboard key list) | 1864-1880 | `tile_key, timer_key, dev_reload_key, sound_key, layout_key, a11y_key, bluetooth_key, translator_key, todo_key, mic_status_key, layout_shortcut_keys, cols, total_keys` | `claude_keys` | called from l.1639. Goes to **`home.py`** (dashboard = every key from row 1 not taken by home buttons/fixtures), not to a plugin |
| `_handle_mpv_session_key(key)` | 2014-2051 | `mpv_session_keys`, `_mpv_session_pid` | `mode`, `last_result`, `result_time` | `_call_mpv_dbus`, `render`, `time.monotonic` |
| `_call_mpv_dbus(pid, command)` | 2053-2081 | — | — | `subprocess.check_output` gdbus; stderr prints |
| `_handle_claude_session_key(key)` | 2083-2125 | `claude_session_keys`, `_claude_session_sid` | `mode`, `last_result`, `result_time` | `_call_claude_dbus`, `render`, `time.monotonic` |
| `_render_mpv_session()` | 2916-2948 | `mpv_session_keys`, `_mpv_session_pid`, `total_keys`, `deck` | — | `_load_mpv_sessions`, `_chunk_text_for_cells`, `_wrap_chunk`, `set_key`, `_t` |
| `_render_claude_session()` | 2950-2997 | `claude_session_keys`, `_claude_session_sid`, `total_keys`, `deck` | — | `_load_claude_sessions`, `_claude_color`, `_chunk_text_for_cells`, `_wrap_chunk`, `set_key`, `_t` |

Fragments of shared methods that belong to the domain:

| Fragment | Lines | Becomes |
|---|---|---|
| `__init__`: `_claude_session_sid`, `_mpv_session_pid` | 1536-1537 | `setup` of each plugin (section 3) |
| `_compute_idle_buttons` calls | 1639-1641 | 1639 → `home.py`; 1640-1641 → `Page.keys` |
| `handle_key` dispatch branches | 2007-2010 | kernel dispatch by page id |
| `_handle_idle_key` dashboard branch, whole | 2174-2213 (mpv 2180-2185, claude 2186-2194, timers 2195-2204, todo 2205-2213) | `home.py` tap → map lookup → provider `press` |
| `_render_mode` branches | 2728-2731 | kernel render by page id |
| `_render_idle`: `session_keys` + loads | 3007-3009 | `home.py` + provider `items` |
| `_render_idle`: cursor allocation | 3020-3044 (mpv 3025-3029, claude 3030-3034) | `home.py` generic allocation in provider `order` |
| `_render_idle`: tile faces | 3079-3087 (mpv 3079-3083, claude 3084-3087) | provider `face` |

Dead code (spec step 0 "dead code commit"), verified by grep of the
whole repo: `_enter_claude_session_mode` 1772-1790 and
`_focus_claude_for_key` 1819-1832 have no caller. The dead `last_prompt`
read is **l.2973-2974** `or (session or {}).get('last_prompt')`: the dict
built at 427-435 has no `last_prompt` key. **Keep l.430-431**
(`d.get("description", "") or d.get("last_prompt", "")`): it reads the
state file, which the hook really writes
(`script/gnome-extension/erplibre_home/hooks/erplibre-home-hook.py:169,202`).
After removal l.2973 reads `text_to_show = (session or {}).get('description') or ''`.

---

## 3. Per-plugin state (`ctx.state(<id>)`)

| Plugin | Attribute in M | Init (M) | Namespace field | Set by |
|---|---|---|---|---|
| `claude_sessions` | `self._claude_session_sid` | l.1536 `None` | `sid = None` | tile press (2191) |
| `mpv_sessions` | `self._mpv_session_pid` | l.1537 `None` | `pid = None` | tile press (2182) |

Not state (derived from geometry, computed once in `__init__` today):
`claude_session_keys` (1839/1848) and `mpv_session_keys` (1855/1857)
→ `Page.keys(geo)`. `claude_keys` (1876) → `home.py`. `mode`,
`last_result`, `result_time`, `last_press_key` → kernel.

Neither plugin reads `settings.json`, so `setup` only initialises the
field.

---

## 4. Pages

### `claude_session` (owner `claude_sessions`)

- keys: `_compute_claude_session_keys` 1834-1848. `cols < 2` → `None`
  (return `{}` in the package: both call sites treat it as falsy /
  `or {}`). Else `{"back": 0, "focus": 1}` + `accept` 2 (cols>=3),
  `set_window` 3 (cols>=4), `kill` 4 (cols>=5).
  3×2: back,focus,accept. 4×2: +set_window. 5×3 and 8×4: +kill.
- render: `_render_claude_session` 2950-2997. Re-reads sessions, finds
  `session_id == sid`; text keys = all keys not in the action set; text =
  `notification_message` when status is `awaiting_notification` or
  `awaiting_stop` and the message is non-empty, else `description`;
  `_chunk_text_for_cells(text, len(text_keys))`, each chunk
  `_wrap_chunk`ped, `COLOR_EMPTY`. Faces: back `COLOR_TITLE`/`BACK`;
  focus `COLOR_VOL`/`FOCUS`/icon `robot`; accept `_claude_color(session)`
  or `COLOR_CLAUDE_AWAIT_STOP` when the sid is not found / `ACCEPT\n↵`;
  set_window `COLOR_LAYOUT_TITLE`/`SET\nWIN`; kill `COLOR_CANCEL`/`KILL`;
  remaining keys `COLOR_EMPTY`, `''`.
- handle: `_handle_claude_session_key` 2083-2125. falsy keys → home;
  back → home; no sid → home; focus/accept/set_window/kill → D-Bus
  `FocusClaudeSession`/`AcceptClaudeSession`/`SetClaudeSessionWindow`/
  `KillClaudeSession`, flash ok/err, home. Any other key: nothing (no
  render, no flash).
- loop branch: **none** (2467-2543 has no `MODE_CLAUDE_SESSION` arm; the
  page never refreshes by itself).
- → `Page("claude_session", page_keys, render, handle, tick=None, period=0.0)`

### `mpv_session` (owner `mpv_sessions`)

- keys: `_compute_mpv_session_keys` 1850-1862. `cols < 3` → `None`
  (→ `{}`). Else `{"back": 0, "play_pause": 1, "quit": 2}`, and when
  `rows >= 2` `vol_down = cols`, `vol_up = cols + 1`.
- render: `_render_mpv_session` 2916-2948. Re-reads sessions, finds
  `pid == self._mpv_session_pid`; text = `title or url or ''`, chunked
  over non-action keys, `_wrap_chunk`, `COLOR_EMPTY`. Faces: back
  `COLOR_TITLE`/`BACK`; play_pause `COLOR_MPV_ACTIVE`/`PLAY\nPAUSE`; quit
  `COLOR_CANCEL`/`QUIT`; vol_down `COLOR_MPV_ACTIVE`/`VOL\n−`; vol_up
  `COLOR_MPV_ACTIVE`/`VOL\n+`; rest `COLOR_EMPTY`, `''`. No icons.
- handle: `_handle_mpv_session_key` 2014-2051. falsy keys → home; back →
  home; falsy pid (None or 0) → home; play_pause/quit → `MpvSendCommand`,
  flash, home; vol_down/vol_up → `MpvSendCommand`, flash, **stay**
  (render). Other key: nothing.
- loop branch: **none**.
- → `Page("mpv_session", page_keys, render, handle, tick=None, period=0.0)`

---

## 5. Home contributions

- **HomeButton**: none for either plugin (no `*_key` in the order list
  1602-1605).
- **Fixture**: none.
- **TileProvider** (order matches today: mpv first, M 3025 before 3030,
  and 2180 before 2187):

| Provider | order | items (M) | face (M) | press (M) |
|---|---|---|---|---|
| `mpv_sessions` | 10 | `_load_mpv_sessions()` 3008 | 3080-3083: `COLOR_MPV_ACTIVE`, `_wrap_chunk((title or url or 'mpv')[:18])`, no icon, no `_t` | 2180-2185: `state.pid = item['pid']`, goto `mpv_session` (no flash). Note: a pid of 0 still opens the page |
| `claude_sessions` | 20 | `_load_claude_sessions()` 3009 | 3084-3087: `_claude_color(s)`, `_claude_label(s)`, icon `robot` (text visible only with labels on, `set_key` 1495) | 2186-2194: `sid = item.get('session_id') or ''`; if sid: `state.sid = sid`, goto `claude_session`; else **nothing** (no render) |

Dashboard keys themselves (`claude_keys`, 1864-1880) belong to
`home.py`: keys `cols .. total_keys-1` minus the home-button keys
(`>= 0`), `mic_status_key`, `layout_shortcut_keys`. Precedence in the
render chain (3046-3099): buttons > mic > shortcuts > mpv > claude >
timers > todo > NO EXT (key 0 only, never a dashboard key) > empty. No
overlap is possible because dashboard keys exclude used keys.

---

## 6. External side effects to stub (characterization)

| Effect | Lines (M) | Detail / stub |
|---|---|---|
| env read at import | 192-199 | `XDG_STATE_HOME` → patch module attributes `CLAUDE_STATE_DIR`, `MPV_STATE_DIR` on M (package: `plugins.claude_sessions.STATE_DIR`, `plugins.mpv_sessions.STATE_DIR`; risk 3: patch the owning module) |
| `os.path.isdir`, `os.listdir` (sorted), `open(..., encoding="utf-8")`, `json.load` | 212-222, 400-410 | point the dirs at a temp dir with fixture `*.json`; non-`.json` names and invalid JSON are skipped |
| liveness `os.path.exists(f"/proc/{pid}")` | 224, 412 | `pid <= 0` skips the check (entry kept). Fixture choice: pid 0 = always live; pid `4194305` (> max `pid_max` 2^22) = always dropped. For handle tests needing a real positive pid, patch `os.path.exists` with a side effect that answers `/proc/<n>` from a set and defers to the real function otherwise (do not patch globally without deferring) |
| ordering | 232, 436 | mpv by `-started_at` (ms epoch in the extension, `lib/mpv-state.js`), claude by `-max(ts_*)`; no clock read, fixtures fix the order |
| claude gdbus | 1794-1802 | `subprocess.check_output(["gdbus","call","--session","--dest","org.gnome.Shell","--object-path","/org/gnome/Shell/Extensions/ERPLibreHome","--method","org.gnome.Shell.Extensions.ERPLibreHome.<M>", sid], stderr=subprocess.STDOUT, timeout=2)`; `<M>` ∈ FocusClaudeSession (2099), AcceptClaudeSession (2106), SetClaudeSessionWindow (2113), KillClaudeSession (2120). ok = `"true" in out.lower()`; `CalledProcessError`, `SubprocessError`, `FileNotFoundError` → False |
| mpv gdbus | 2055-2064 | same prefix, method `org.gnome.Shell.Extensions.ERPLibreHome.MpvSendCommand`, args `str(int(pid)), command`, `command` ∈ `play_pause`, `quit`, `vol_down`, `vol_up` (2031-2038) |
| journal (stderr) | 1805-1807, 1810-1812, 1815-1816, 2067-2069, 2072-2075, 2078-2080 | `[erplibre-home] <Method>(<args>) returned/failed: ...`; not on screen, assert only if wanted |
| `time.monotonic()` | 2043, 2101, 2108, 2115, 2122 | flash start; patch `M.time.monotonic` to a fixed clock |
| translator `_t` | 2935, 2937, 2939, 2941, 2943, 2980, 2982, 2987, 2990, 2992 | `_DECK_LANG` frozen at import (l.123 from `LANG`); pin `_DECK_LANG` (e.g. `'en'` and one `'fr'` run) in the tests |
| `set_key` | 2935-2948, 2980-2997, 3082-3087 | the recorder `(key, color, text, icon)` of spec step 0 |
| files written | — | none |
| settings | — | none |

Recommended fixture set (one dir each): 2 live mpv (one with empty title
to hit the `url` fallback, one with neither to hit `'mpv'`), 1 dead mpv;
4 claude sessions, one per status (`active`, `working`, `awaiting_stop`
with `notification_message`, `awaiting_notification`), one with empty
`session_id`, one with a long description (> 18 chars, > cells × 12) for
chunking, one dead. Dashboard sizes from 1864-1880 (computed by hand
from 1602-1632): 3×2 → keys 4,5 (2 keys); 4×2 → 5,6,7 (3); 5×3 → 9,
11-14 (5; mic 10, no shortcuts since 4+3 > 5); 8×4 → 9-23, 25-27, 31
(19; mic 24, shortcuts 28-30). So 2 mpv + 6 claude overflows the small
decks and leaves room for timers/TODO on 8×4.

---

## 7. Draft plugin modules (79 cols)

API assumptions marked `# ASSUME` (see section 8).

```python
# plugins/claude_sessions.py
"""Claude sessions: dashboard tiles and the per-session action page.

Sessions come from the state directory the Claude hook writes, one JSON
file per session. A tile opens the action page of its session; the page
calls the extension over D-Bus with the session id.
"""

import json
import os

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import PLUGIN_API, Page, Plugin
from erplibre_streamdeck.plugin import KeyFace, TileProvider
from erplibre_streamdeck.ui import colors
from erplibre_streamdeck.ui.text import chunk_text_for_cells, wrap_chunk

ID = "claude_sessions"  # ASSUME: plugin knows its stem
PAGE_ID = "claude_session"
STATE_DIR = os.path.join(paths.STATE_HOME, "claude")

# Mirrors the GNOME extension badge palette.
COLOR_ACTIVE = (46, 125, 50)
COLOR_WORKING = (0, 131, 143)
COLOR_AWAIT_STOP = (212, 160, 23)
COLOR_AWAIT_NOTIFY = (198, 40, 40)

_ACTIONS = (
    ("focus", "FocusClaudeSession"),
    ("accept", "AcceptClaudeSession"),
    ("set_window", "SetClaudeSessionWindow"),
    ("kill", "KillClaudeSession"),
)


def load_sessions():
    ...  # body of M 399-437, reading STATE_DIR (B3: liveness at M 411-413)


def session_color(session):
    ...  # M 441-447


def session_label(session, max_chars=18):
    ...  # M 451-461


def page_keys(geo):
    if geo.cols < 2:
        return {}
    keys = {"back": 0, "focus": 1}
    if geo.cols >= 3:
        keys["accept"] = 2
    if geo.cols >= 4:
        keys["set_window"] = 3
    if geo.cols >= 5:
        keys["kill"] = 4
    return keys


def _find(sid):
    for s in load_sessions():
        if s.get("session_id") == sid:
            return s
    return None


def _render(ctx):
    cs = page_keys(ctx.geo)
    session = _find(ctx.state(ID).sid or "")
    text_keys = [k for k in range(ctx.geo.total_keys)
                 if k not in set(cs.values())]
    if (session and session.get("status")
            in ("awaiting_notification", "awaiting_stop")
            and session.get("notification_message")):
        text = session["notification_message"]
    else:
        text = (session or {}).get("description") or ""
    by_key = dict(zip(text_keys, chunk_text_for_cells(
        text, len(text_keys))))
    accept = session_color(session) if session else COLOR_AWAIT_STOP
    faces = {
        "back": (colors.TITLE, ctx.t("BACK"), None),
        "focus": (colors.VOL, ctx.t("FOCUS"), "robot"),
        "accept": (accept, ctx.t("ACCEPT\n↵"), None),
        "set_window": (colors.LAYOUT_TITLE, ctx.t("SET\nWIN"), None),
        "kill": (colors.CANCEL, ctx.t("KILL"), None),
    }
    by_action = {v: faces[n] for n, v in cs.items()}
    for key in range(ctx.geo.total_keys):
        if key in by_action:
            color, label, icon = by_action[key]
            ctx.set_key(key, color, label, icon=icon)
        else:
            ctx.set_key(key, colors.EMPTY,
                        wrap_chunk(by_key.get(key, "")))


def _handle(ctx, key):
    cs = page_keys(ctx.geo)
    sid = ctx.state(ID).sid
    if not cs or key == cs.get("back") or not sid:
        ctx.home()
        return
    for name, method in _ACTIONS:
        if name in cs and key == cs[name]:
            ctx.flash(ctx.dbus.call(method, sid, timeout=2))  # ASSUME
            ctx.home()
            return


def _setup(ctx):
    ctx.state(ID).sid = None


def _face(ctx, s):
    return KeyFace(session_color(s), session_label(s), icon="robot")


def _press(ctx, s):
    sid = s.get("session_id") or ""
    if sid:
        ctx.state(ID).sid = sid
        ctx.goto(PAGE_ID)


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page(PAGE_ID, page_keys, _render, _handle)],
    tiles=[TileProvider(20, lambda ctx: load_sessions(), _face, _press)],
    setup=_setup,
)
```

Note on `_render`: `wrap_chunk("")` returns `""`, so
"chunk or empty" collapses into one branch with the same `(key,
COLOR_EMPTY, '')` record; keep the two-branch form if the recorder
distinguishes `""` from `''` (it does not: same str).

```python
# plugins/mpv_sessions.py
"""mpv sessions: dashboard tiles and the per-player action page."""

import json
import os

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import PLUGIN_API, Page, Plugin
from erplibre_streamdeck.plugin import KeyFace, TileProvider
from erplibre_streamdeck.ui import colors
from erplibre_streamdeck.ui.text import chunk_text_for_cells, wrap_chunk

ID = "mpv_sessions"
PAGE_ID = "mpv_session"
STATE_DIR = os.path.join(paths.STATE_HOME, "mpv")
COLOR_ACTIVE = (40, 100, 180)

# command -> stays on the page (volume nudges repeat)
_COMMANDS = {
    "play_pause": False, "quit": False,
    "vol_down": True, "vol_up": True,
}


def load_sessions():
    ...  # body of M 211-233 (B3: liveness at M 223-225)


def page_keys(geo):
    if geo.cols < 3:
        return {}
    keys = {"back": 0, "play_pause": 1, "quit": 2}
    if geo.rows >= 2:
        keys["vol_down"] = geo.cols
        keys["vol_up"] = geo.cols + 1
    return keys


def _render(ctx):
    ms = page_keys(ctx.geo)
    pid = ctx.state(ID).pid
    sess = next((s for s in load_sessions() if s.get("pid") == pid), {})
    text_keys = [k for k in range(ctx.geo.total_keys)
                 if k not in set(ms.values())]
    title = sess.get("title") or sess.get("url") or ""
    by_key = dict(zip(text_keys, chunk_text_for_cells(
        title, len(text_keys))))
    faces = {
        "back": (colors.TITLE, ctx.t("BACK")),
        "play_pause": (COLOR_ACTIVE, ctx.t("PLAY\nPAUSE")),
        "quit": (colors.CANCEL, ctx.t("QUIT")),
        "vol_down": (COLOR_ACTIVE, ctx.t("VOL\n−")),
        "vol_up": (COLOR_ACTIVE, ctx.t("VOL\n+")),
    }
    by_action = {v: faces[n] for n, v in ms.items()}
    for key in range(ctx.geo.total_keys):
        if key in by_action:
            ctx.set_key(key, *by_action[key])
        else:
            ctx.set_key(key, colors.EMPTY,
                        wrap_chunk(by_key.get(key, "")))


def _handle(ctx, key):
    ms = page_keys(ctx.geo)
    pid = ctx.state(ID).pid
    if not ms or key == ms.get("back") or not pid:
        ctx.home()
        return
    for cmd, stay in _COMMANDS.items():
        if key == ms.get(cmd):
            ok = ctx.dbus.call(  # ASSUME
                "MpvSendCommand", str(int(pid)), cmd, timeout=2)
            ctx.flash(ok)
            if stay:
                ctx.render()
            else:
                ctx.home()
            return


def _setup(ctx):
    ctx.state(ID).pid = None


def _face(ctx, s):
    title = (s.get("title") or s.get("url") or "mpv")[:18]
    return KeyFace(COLOR_ACTIVE, wrap_chunk(title))


def _press(ctx, s):
    ctx.state(ID).pid = s["pid"]
    ctx.goto(PAGE_ID)


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page(PAGE_ID, page_keys, _render, _handle)],
    tiles=[TileProvider(10, lambda ctx: load_sessions(), _face, _press)],
    setup=_setup,
)
```

---

## 8. Traps and proposals

1. **`ctx.dbus.call` shape is not fixed by the spec.** Two gdbus styles
   coexist: the session calls use `check_output(..., stderr=STDOUT,
   timeout=2)` and test `"true"` in the MERGED output (1794-1803,
   2055-2065); the others use `run(capture_output, text, timeout=3)` and
   test stdout only (557-571). Proposal: `dbus.call(method, *args,
   timeout=3) -> Result(ok_exit, out)` where `out` merges stderr, plus a
   helper `dbus.true(method, *args, timeout)` returning `exit == 0 and
   "true" in out.lower()` (exactly today's session semantics: a non-zero
   exit raised `CalledProcessError` → False). Sessions pass `timeout=2`.
   The failure journal line becomes `ctx.log(...)` (prefixed by plugin
   id instead of `[erplibre-home]`): journal-only change, not on screen.
2. **`ctx.flash(ok)` with no reason must not write a journal line.**
   Today these handlers set `last_result` directly (2042-2043, 2100-2122)
   with no `_flag_err`; the gdbus helper already logged. The flash must
   also only SET state; the following `ctx.home()` / `ctx.render()` draws
   the page then the overlay (today: state set, then `mode = IDLE`, then
   `render()` overlays because the flash is fresh, 2692-2701).
3. **Page keys are not reachable from `ctx`.** The spec's `Page.keys`
   takes a geometry, but `Context` has no accessor for the current page's
   key map. Proposal: the plugin calls its own pure `page_keys(ctx.geo)`
   (cheap dicts), as in the skeleton; or the kernel caches and exposes
   `ctx.keys`. Pick one for every plugin.
4. **`None` keys on small decks.** Today `None` (cols < 2 / < 3) makes
   handle go home and render paint every key as text (`or {}`). Return
   `{}` from `page_keys`: identical for both paths. Unreachable at the
   four characterised geometries (all cols >= 3) — say so in the
   reference file.
5. **Plugin id inside the plugin.** `ctx.state(plugin_id)` needs the
   stem, which the loader sets and the plugin "does not declare". The
   skeleton hard-codes `ID`; a user copy under another stem would then
   share state with the original. Proposal: `ctx.state()` with no argument
   returns the CALLING plugin's namespace (the wrapper knows the id).
6. **Dashboard refresh cadence depends on other plugins.** Today the
   home re-renders every 2 s because of the idle arm 3516-3531 (timers +
   TODO refresh). Session tiles have no tick of their own. In the kernel
   model a render on home happens only "if any home_tick ran"; with
   `timers` and `todo_terminals` off, mpv/claude tiles would freeze.
   Proposal (ask): either the kernel re-renders home every 2.0 s on its
   own, or both session plugins declare `home_tick=<no-op>,
   home_period=2.0`. With equal periods and per-plugin last-run stamps
   set to the same `now`, all 2 s home ticks fire in the same iteration →
   still one render per 2 s, as today.
7. **Tap semantics (deliberate spec change).** Today 2174-2194 re-reads
   both lists at tap time and recomputes offsets (`cidx = idx -
   len(mpv)`); after B2 the press receives the item of the last render.
   Characterization of the monolith must therefore tap with the SAME
   fixture set as the preceding render, so both behaviours agree on the
   pinned cases.
8. **Silent presses.** Claude tile with empty `session_id`: no goto, no
   render, no flash (2190-2194) — keep `_press` returning without
   `ctx.goto`. Non-action keys on both pages: no render, no flash, but
   the kernel still records `last_press_key` (1983). mpv tile with pid 0
   (file without pid; kept because `pid > 0 and ...` short-circuits)
   opens the page; every action key then goes home WITHOUT a flash
   (2024-2028). Keep.
9. **Error isolation widens the fault case only.** `int(d.get("pid"))`
   and `int(d.get("ts_*"))` raise `ValueError/TypeError` on malformed
   values (223, 230, 411-417), and a JSON array makes `d.get` raise
   `AttributeError`; today that escapes `_render_idle` inside the loop
   thread. After B2 the provider is logged and its tiles stay empty.
   On-screen output for well-formed fixtures is unchanged; do not pin the
   malformed case as parity.
10. **Same key set, different dict.** `_render_mpv_session` builds the
    action set from five `.get`s with `None` discarded (2924-2926);
    `set(ms.values())` is identical. `_render_claude_session` adds
    optional actions only if present (2959-2962); same.
11. **Labels-off icon tiles.** The claude tile and the FOCUS key carry
    `icon='robot'`: text shows only when labels are on (`set_key` 1495,
    `_show_labels` read at call time — risk 4). The recorder records
    `(key, color, text, icon)` regardless, so parity is pinned either way.
12. **`_compute_claude_buttons` is the dashboard, not Claude.** It moves
    to `home.py`; its `used` set (1868-1874) must become "home-button
    keys + fixture keys", which reproduces today's set (all nine
    `*_key`s, `mic_status_key`, `layout_shortcut_keys`).
13. **Tile order is 10 (mpv) then 20 (claude)**, matching both
    3025/3030 and 2180/2187. `items` is called once per render; the
    loads happen before the timers list is read today (3008-3019) — the
    order of file reads is not visible.
14. **Hard-coded D-Bus names** in 1796-1800 and 2057-2062 equal
    `DBUS_DEST/PATH/IFACE` (546-548); `dbus.py` owns them after the move.
15. **Lint.** 2031-2032 use `if ...: cmd = ...` on one line (E701); the
    skeleton's table loop removes it. Move first, reformat in a separate
    commit (risk 7).

### B3 hooks (location only)

- Liveness (pid + starttime): the `/proc/{pid}` test in each
  `load_sessions()` (today M 223-225 mpv, M 411-413 claude); a shared
  helper would sit next to `paths.py` or in each plugin.
- Page refresh: `Page.tick` / `period` of `claude_session` and
  `mpv_session` (both `None` / `0.0` in B2); the tick would reload the
  session and `ctx.home()` when it is gone. The handle's guard (`not
  sid` / `not pid`) is where a "session still alive" check would join.

### Doc references to update at the docs step

`script/gnome-extension/erplibre_home/ARCHITECTURE.md:55,68`,
`script/gnome-extension/erplibre_home/lib/mpv-state.js:15` name
`erplibre_streamdeck.py` as the reader of the state directories.
