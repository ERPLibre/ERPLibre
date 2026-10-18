# B2 map: plugin `timers`

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines,
md5 `be3560405845407252c80f092eed8725`, HEAD `b61156bf`). Every range
below was read with `sed -n` / `grep -n`.

Target module: `script/stream_deck/erplibre_streamdeck/plugins/timers.py`
(id `timers`). Home button order 20, TileProvider order 30, two pages,
one page tick and one home tick, both 2.0 s.

---

## 1. Module-level names owned by the domain

| Name | Lines | Target |
|---|---|---|
| module docstring sentence "Press TIMER to list timers from the tracker@aliakseiz.github.com extension and start/stop them." | 11-12 | dropped with the file; one line in `plugins/timers.py` docstring |
| `import csv` | 19 | `plugins/timers.py` only (no other user: `csv.` only at 1148) |
| `COLOR_TIMER_TITLE = (120, 60, 0)` | 51 | `ui/colors.py` (SHARED: also the TODO home button, line 3072) |
| `COLOR_TIMER_RUNNING = (0, 160, 40)` | 52 | `ui/colors.py` (users: 3090, 3431, timers only) |
| `COLOR_TIMER_PAUSED = (50, 70, 110)` | 53 | `ui/colors.py` (users: 3413, 3432, timers only) |
| `COLOR_REFRESH = (80, 80, 110)` | 55 | `ui/colors.py` (only user 3401) |
| `COLOR_NEW = (140, 80, 160)` | 56 | `ui/colors.py` (only user 3407) |
| `COLOR_RESET = (180, 100, 0)` | 57 | `ui/colors.py` (only user 3404) |
| `COLOR_EXPORT = (0, 120, 140)` | 60 | `ui/colors.py` (only user 3410) |
| shared, used here: `COLOR_EMPTY` 46, `COLOR_BACK` 54, `COLOR_CONFIRM` 58, `COLOR_CANCEL` 59 | | `ui/colors.py` (many domains) |
| `_DECK_LABELS['fr']` timer entries: `'RFSH'`..`'NO\nTIMERS'` | 134-142 | stay in `ui/i18n.py` (single table; spec puts `_t` and labels there) |
| `_DECK_LABELS['fr']['TIMER']` | 145 | `ui/i18n.py` |
| shared labels used: `'BACK'` 127, `'CANCEL'` 130, `'NEW'` 133; `'OK'` has no entry (stays "OK") | | `ui/i18n.py` |
| `MODE_TIMER_LIST = "timer_list"` | 530 | page id literal in `plugins/timers.py` |
| `MODE_TIMER_RESET_CONFIRM = "timer_reset_confirm"` | 531 | page id literal in `plugins/timers.py` |
| `_list_tracker_timers()` | 611-632 | `plugins/timers.py` (transport via `ctx.dbus`) |
| `_toggle_tracker_timer(timer_id)` | 635-654 | `plugins/timers.py` |
| `_add_tracker_timer()` | 657-679 | `plugins/timers.py` |
| `_reset_all_tracker_timers()` | 682-700 | `plugins/timers.py` |
| `_ask_save_path()` | 1117-1140 | `plugins/timers.py` (only caller 2668) |
| `_export_timers_csv(path, timers)` | 1143-1160 | `plugins/timers.py` (only caller 2673) |
| `_icon_timer(draw, w, h)` | 1202-1215 | `ui/icons.py` (registry entry `"timer"` line 1400; spec puts every painter there) |
| `_label_for_timer(timer)` | 3546-3555 | `plugins/timers.py` (pure; backend test target per spec "Tests") |
| `main()` print "Press TIMER to list and toggle tracker timers." | 3582 | `app.py` keeps it verbatim (stdout banner) or drops it; not on the deck |

Shared helper consumed: `_parse_gdbus_string_tuple` 593-608 -> `dbus.py`
(also used at 278, 308, 1028, 1109). `DBUS_DEST/PATH/IFACE` 546-548 ->
`dbus.py`.

## 2. Tiler methods owned

| Method | Lines | Reads | Writes | Other-domain calls |
|---|---|---|---|---|
| `_handle_timer_list_key(key)` | 2256-2302 | `total_keys`, `timers`, `timer_key_map` | `mode` (IDLE / TIMER_RESET_CONFIRM), `_dashboard_hidden_timer_ids`, `last_result`, `result_time` | `self.render()`, `self._flag_err()` (kernel), `_add_tracker_timer`, `_toggle_tracker_timer`, `self._handle_export()`, `self._refresh_timers()` |
| `_handle_timer_reset_confirm_key(key)` | 2640-2658 | `total_keys` | `mode` (TIMER_LIST), `last_result`, `result_time` | `_reset_all_tracker_timers`, `_refresh_timers`, `_flag_err`, `render` |
| `_enter_timer_mode()` | 2660-2663 | - | `mode` | `_refresh_timers`, `render`. Callers: 2203 (dashboard tile), 2215 (TIMER button) |
| `_handle_export()` | 2665-2676 | `timers` | `last_result`, `result_time` | `_refresh_timers`, `_ask_save_path`, `_export_timers_csv`, `render` |
| `_refresh_timers()` | 2678-2688 | `total_keys` | `timers`, `timer_key_map` | `_list_tracker_timers`. Callers: 2263, 2273, 2298, 2651, 2662, 2667, loop 3498, loop 3528 |
| `_render_timer_list()` | 3395-3435 | `total_keys`, `timer_key_map`, `timers` | - | `set_key`, `_t`, `_label_for_timer` |
| `_render_timer_reset_confirm()` | 3437-3453 | `total_keys`, `cols` | - | `set_key`, `_t` |

Timer slices inside non-owned methods (they become plugin callbacks):

| Slice | Lines | Becomes |
|---|---|---|
| `handle_key` dispatch | 1989-1992 | kernel dispatch to `Page.handle` |
| `_render_mode` dispatch | 2710-2713 | kernel dispatch to `Page.render` |
| `_handle_idle_key`: dashboard timer branch | 2195-2204 (`tidx`, `running_timers`, `_enter_timer_mode`) | `TileProvider.press` |
| `_handle_idle_key`: TIMER button | 2214-2216 | `HomeButton.press` |
| `_render_idle`: hidden-set pruning + `running_timers` | 3010-3019 | `TileProvider.items` |
| `_render_idle`: `timer_by_key` fill | 3022, 3035-3039 | `home.py` allocation (generic cursor) |
| `_render_idle`: TIMER button face | 3049-3051 | `HomeButton.face` |
| `_render_idle`: dashboard tile face | 3088-3091 | `TileProvider.face` |
| `_compute_idle_buttons`: `"timer"` in `order` | 1602-1604 (list), 1606-1617 (allocation) | `home.py` with `order=20` |
| `_compute_claude_buttons`: `self.timer_key` in the used set | 1868 | `home.py` (home keys excluded from dashboard) |
| `loop`: `last_timer_refresh` init + timer-page branch | 3469, 3495-3500 | `Page.tick`, `period=2.0` |
| `loop`: idle refresh, `self._refresh_timers()` | 3470 (`last_idle_refresh`), 3516-3531 (call at 3528) | `Plugin.home_tick`, `home_period=2.0` |

## 3. Per-plugin state -> `ctx.state("timers")`

From `Tiler.__init__` 1547-1555:

| Attribute | Init | Line | New name |
|---|---|---|---|
| `self.timers` | `[]` | 1548 | `st.timers` |
| `self.timer_key_map` | `{}` | 1550 | `st.key_map` |
| `self._dashboard_hidden_timer_ids` | `set()` | 1555 | `st.hidden_ids` |

`setup(ctx)` sets these three; it makes NO D-Bus call (today the
first `ListTrackerTimers` happens on the first loop pass on home,
`last_idle_refresh = 0` at 3470, not in `__init__`).

Not state of this plugin: `self.timer_key` (allocated by `home.py`),
`self.tile_key` (tiling's), `last_timer_refresh` / `last_idle_refresh`
(kernel tick schedule).

## 4. Pages

### `timer_list`

- keys: no `_compute_*`; positions are computed inline from
  `total_keys` (n) in 2257-2289 (handler) and 3396-3415 (render), and
  slots in `_refresh_timers` 2681-2688:
  `{"back": 0, "clean": n-5, "export": n-4, "new": n-3, "reset": n-2,
  "refresh": n-1, "slots": list(range(1, n-5))}`.
  At 3x2 (n=6) `slots` is empty and key 1 is CLEAN, so no timer and no
  "NO TIMERS" hint can show; at 4x2 slots are [1, 2].
- render: `_render_timer_list` 3395-3435. Precedence per key: BACK(0),
  RFSH(n-1), RESET ALL(n-2), NEW(n-3), EXPT CSV(n-4), CLEAN DASH(n-5,
  colour `COLOR_TIMER_PAUSED`), then slot: no id -> "NO\nTIMERS" on
  key 1 only when `timers` is empty, else blank; id not found in
  `timers` -> blank; else running/paused colour + `_label_for_timer`
  (no icon).
- handle: `_handle_timer_list_key` 2256-2302 (+ `_handle_export`
  2665-2676). Key 0 -> idle; n-1 refresh+render; n-2 -> reset confirm;
  n-3 Add (ok: refresh+render; fail: `_flag_err("AddTrackerTimer
  returned no id")` + render); n-4 export; n-5 hidden := running ids
  with a truthy id, flash ok, render; slot -> toggle (ok:
  refresh+render; fail: `_flag_err(f"ToggleTrackerTimer({timer_id})
  failed")` + render); unmapped key -> nothing (no render).
- tick: loop 3495-3500: `if now - last_timer_refresh >= 2.0:
  _refresh_timers(); render(); last_timer_refresh = now`.
- -> `Page("timer_list", keys=_list_keys, render=_render_list,
  handle=_handle_list, tick=_tick_list, period=2.0)`.

### `timer_reset_confirm`

- keys: inline in 2641-2646 and 3440-3451:
  `{"cancel": 0, "ok": n-1, "mid": n // 2}`; RESET/ALL? split on
  `mid-1`/`mid` when `cols >= 3`, else "RESET\nALL?" on `mid`.
  At 3x2 the split lands on keys 2 and 3 (two different rows): kept.
- render: `_render_timer_reset_confirm` 3437-3453.
- handle: `_handle_timer_reset_confirm_key` 2640-2658. 0 -> timer_list
  + render (no refresh); n-1 -> Reset, page := timer_list, ok:
  refresh + flash ok; fail: `_flag_err("ResetAllTrackerTimers failed
  via D-Bus")`; render. Other keys: nothing, no render.
- tick: none (the loop has no branch for this mode).
- -> `Page("timer_reset_confirm", keys=_confirm_keys,
  render=_render_confirm, handle=_handle_confirm)`.

## 5. Home contributions

### HomeButton (TIMER)

- order: 20 (index 1 of `order` at 1602-1604; `tiling` is 10).
- face: 3049-3051 -> `KeyFace(COLOR_TIMER_TITLE, ctx.t("TIMER"),
  icon="timer")`.
- press: 2214-2215 -> `_enter_timer_mode` 2660-2663: refresh, page
  `timer_list`, render.

### Fixture

None.

### TileProvider (running timers)

- order: 30 (after mpv 10, claude 20; before todo 40: cursor order
  3026-3044).
- items: 3010-3019. First prunes `hidden_ids &= {id of running
  timers}` (ids may include `None`), then returns
  `[t for t in timers if t.get('running') and t.get('id') not in
  hidden_ids]`. Reads the cached `st.timers`; no D-Bus call.
- face: 3088-3091 -> `KeyFace(COLOR_TIMER_RUNNING,
  _label_for_timer(t), icon="timer")`.
- press: 2195-2204 -> `_enter_timer_mode()`; the item is ignored.

### home_tick

- 3516-3531: `if now - last_idle_refresh >= 2.0: _refresh_timers();
  _refresh_todo_terminals(); render(); last_idle_refresh = now`.
- -> `home_tick=_home_tick` (calls `_refresh(ctx)` only, no render),
  `home_period=2.0`; the kernel renders once after the home ticks.

## 6. External side effects to stub

| Effect | Where | Detail |
|---|---|---|
| `subprocess.run` gdbus List | 613-622 | `["gdbus","call","--session","--dest","org.gnome.Shell","--object-path","/org/gnome/Shell/Extensions/ERPLibreHome","--method","org.gnome.Shell.Extensions.ERPLibreHome.ListTrackerTimers"]`, `capture_output=True, text=True, timeout=3`. rc!=0 -> `[]` + stderr "Timer list dbus: {stderr}"; stdout `('<json>',)` parsed by `_parse_gdbus_string_tuple` then `json.loads` (629); any exception -> `[]` |
| gdbus Toggle | 637-647 | same prefix, `...ToggleTrackerTimer`, then `timer_id` as a bare argv item (gdbus parses it as GVariant text). OK iff rc 0 and `"true" in stdout.lower()` |
| gdbus Add | 662-671 | `...AddTrackerTimer`; returns parsed tuple string or `""`. The extension also opens its edit UI |
| gdbus ResetAll | 684-693 | `...ResetAllTrackerTimers`; OK iff rc 0 and `"true"` in stdout |
| `shutil.which("zenity")` | 1119 | missing -> stdout "zenity not installed — cannot open file dialog." and `""` |
| `subprocess.run` zenity | 1123-1131 | `["zenity","--file-selection","--save","--confirm-overwrite","--file-filter=CSV files \| *.csv","--filename=timers.csv"]`, `capture_output=True, text=True, timeout=180`; rc!=0 -> `""`; `.csv` appended when missing (1135-1136) |
| file write | 1146-1156 | `os.makedirs(dirname or ".", exist_ok=True)`; `open(path,"w",newline="",encoding="utf-8")`; header `name,seconds,time`; rows `name, elapsed, HH:MM:SS` |
| `time.monotonic` | 2290 (CLEAN flash), 2653 (reset ok), 2675 (export), 1770 (`_flag_err`), loop 3472 | all go through `ctx.flash` / the kernel clock after B2 |
| stderr prints | 624, 631, 650, 653, 673, 678, 696, 699, 1139, 1159 | become `ctx.log(...)` (the journal gains the `[timers]` prefix; not on the deck) |
| translator calls | none | the domain never touches `_translator` |
| `_t` | 3050, 3398-3420, 3443-3451 | `ctx.t` (deck labels) |

Characterization fixture for timers: a fake `ListTrackerTimers` stdout,
e.g. `('[{"id":"a","name":"Alpha task","elapsed":75,"running":true},
{"id":"b","name":"Beta","elapsed":3725,"running":false}]',)`, plus
toggle/add/reset replies `(true,)` / `('c',)`. Values invented.

## 7. Draft plugin module

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tracker timers: the TIMER page, its reset confirmation, and the
running timers on the home dashboard.

The timers come from the tracker extension through the ERPLibre Home
extension's D-Bus methods. ``st.timers`` is the last list read; the
home dashboard and the TIMER page both draw from it, so the page's
2 s refresh and the home's 2 s refresh are the only D-Bus reads.
"""

import csv
import json
import os
import shutil
import subprocess

from erplibre_streamdeck import dbus as _dbus
from erplibre_streamdeck.plugin import (
    HomeButton, KeyFace, Page, Plugin, TileProvider, PLUGIN_API)
from erplibre_streamdeck.ui.colors import (
    COLOR_BACK, COLOR_CANCEL, COLOR_CONFIRM, COLOR_EMPTY, COLOR_EXPORT,
    COLOR_NEW, COLOR_REFRESH, COLOR_RESET, COLOR_TIMER_PAUSED,
    COLOR_TIMER_RUNNING, COLOR_TIMER_TITLE)

LIST = "timer_list"
CONFIRM = "timer_reset_confirm"
REFRESH_SEC = 2.0


# ---------- backend ----------

def _call(ctx, method, *args):
    """gdbus call of one extension method; CompletedProcess or None."""
    try:
        return ctx.dbus.call(method, *args)
    except Exception as e:
        ctx.log(f"Timer {method} error: {e}")
        return None


def _list(ctx):
    r = _call(ctx, "ListTrackerTimers")
    if r is None:
        return []
    if r.returncode != 0:
        ctx.log(f"Timer list dbus: {r.stderr}")
        return []
    payload = _dbus.parse_string_tuple(r.stdout)
    if not payload:
        return []
    try:
        return json.loads(payload)
    except Exception as e:
        ctx.log(f"Timer list error: {e}")
        return []


def _ok(ctx, label, r):
    if r is not None and r.returncode == 0 and "true" in r.stdout.lower():
        return True
    if r is not None:
        ctx.log(f"Timer {label} dbus: {r.stdout} {r.stderr}")
    return False


def _toggle(ctx, timer_id):
    return _ok(ctx, "toggle", _call(ctx, "ToggleTrackerTimer", timer_id))


def _reset_all(ctx):
    return _ok(ctx, "reset", _call(ctx, "ResetAllTrackerTimers"))


def _add(ctx):
    r = _call(ctx, "AddTrackerTimer")
    if r is None:
        return ""
    if r.returncode != 0:
        ctx.log(f"Timer add dbus: {r.stderr}")
        return ""
    return _dbus.parse_string_tuple(r.stdout) or ""


def label_for_timer(timer):
    """Two lines: the first word of the name (6 chars max), mm:ss."""
    name = timer.get("name") or "?"
    first = name.split()[0] if name.split() else name
    first = first[:6]
    elapsed = int(timer.get("elapsed") or 0)
    return f"{first}\n{elapsed // 60:02d}:{elapsed % 60:02d}"


def ask_save_path(ctx):
    """zenity save dialog; '' when cancelled or unavailable."""
    ...  # body of 1117-1140, prints -> ctx.log / print kept


def export_csv(ctx, path, timers):
    """Write name, seconds, HH:MM:SS rows; True on success."""
    ...  # body of 1143-1160


# ---------- state ----------

def _setup(ctx):
    st = ctx.state("timers")
    st.timers = []
    st.key_map = {}
    st.hidden_ids = set()


def _list_keys(geo):
    n = geo.total_keys
    return {"back": 0, "clean": n - 5, "export": n - 4, "new": n - 3,
            "reset": n - 2, "refresh": n - 1,
            "slots": list(range(1, n - 5))}


def _refresh(ctx):
    st = ctx.state("timers")
    st.timers = _list(ctx)
    slots = _list_keys(ctx.geo)["slots"]
    st.key_map = {}
    for idx, timer in enumerate(st.timers):
        if idx >= len(slots):
            break
        st.key_map[slots[idx]] = timer.get("id")


def _enter(ctx, _item=None):
    _refresh(ctx)
    ctx.goto(LIST)


# ---------- timer_list ----------

def _render_list(ctx):
    ...  # 3395-3435, self.deck/set_key -> ctx.set_key, _t -> ctx.t


def _handle_list(ctx, key):
    st = ctx.state("timers")
    k = _list_keys(ctx.geo)
    if key == k["back"]:
        ctx.home()
    elif key == k["refresh"]:
        _refresh(ctx)
        ctx.render()
    elif key == k["reset"]:
        ctx.goto(CONFIRM)
    elif key == k["new"]:
        if _add(ctx):
            _refresh(ctx)
        else:
            ctx.flash(False, "AddTrackerTimer returned no id")
        ctx.render()
    elif key == k["export"]:
        _refresh(ctx)
        path = ask_save_path(ctx)
        if path:
            ctx.flash(export_csv(ctx, path, st.timers))
        ctx.render()
    elif key == k["clean"]:
        st.hidden_ids = {t.get("id") for t in st.timers or []
                         if t.get("running") and t.get("id")}
        ctx.flash(True)
        ctx.render()
    else:
        timer_id = st.key_map.get(key)
        if not timer_id:
            return
        if _toggle(ctx, timer_id):
            _refresh(ctx)
        else:
            ctx.flash(False, f"ToggleTrackerTimer({timer_id}) failed")
        ctx.render()


def _tick_list(ctx, now):
    _refresh(ctx)
    ctx.render()


# ---------- timer_reset_confirm ----------

def _confirm_keys(geo):
    return {"cancel": 0, "ok": geo.total_keys - 1,
            "mid": geo.total_keys // 2}


def _render_confirm(ctx):
    ...  # 3437-3453


def _handle_confirm(ctx, key):
    k = _confirm_keys(ctx.geo)
    if key == k["cancel"]:
        ctx.goto(LIST)
    elif key == k["ok"]:
        if _reset_all(ctx):
            _refresh(ctx)
            ctx.flash(True)
        else:
            ctx.flash(False, "ResetAllTrackerTimers failed via D-Bus")
        ctx.goto(LIST)          # one render, flash overlaid


# ---------- home ----------

def _home_tick(ctx, now):
    _refresh(ctx)               # the kernel renders after home ticks


def _running(ctx):
    st = ctx.state("timers")
    timers = st.timers or []
    st.hidden_ids &= {t.get("id") for t in timers if t.get("running")}
    return [t for t in timers if t.get("running")
            and t.get("id") not in st.hidden_ids]


PLUGIN = Plugin(
    api=PLUGIN_API,
    setup=_setup,
    pages=[
        Page(LIST, keys=_list_keys, render=_render_list,
             handle=_handle_list, tick=_tick_list, period=REFRESH_SEC),
        Page(CONFIRM, keys=_confirm_keys, render=_render_confirm,
             handle=_handle_confirm),
    ],
    home_buttons=[HomeButton(
        order=20,
        face=lambda ctx: KeyFace(COLOR_TIMER_TITLE, ctx.t("TIMER"),
                                 icon="timer"),
        press=_enter)],
    tiles=[TileProvider(
        order=30,
        items=_running,
        face=lambda ctx, t: KeyFace(COLOR_TIMER_RUNNING,
                                    label_for_timer(t), icon="timer"),
        press=_enter)],
    home_tick=_home_tick,
    home_period=REFRESH_SEC,
)
```

`ctx.dbus.call(method, *args)` is assumed to build exactly
`["gdbus","call","--session","--dest",DBUS_DEST,"--object-path",
DBUS_PATH,"--method",f"{DBUS_IFACE}.{method}",*args]` with
`capture_output=True, text=True, timeout=3` and return the
`CompletedProcess` (raising like `subprocess.run`). The plugin keeps the
"true in stdout" and tuple parsing; `parse_string_tuple` is the
`dbus.py` home of `_parse_gdbus_string_tuple`. If the kernel's
`call` returns a parsed value instead, `_ok`/`_add`/`_list` adapt; the
argv must stay byte-identical for the gdbus stub.

## 8. Traps

1. **`timer_key != tile_key` (2214, 3049) is a dead guard.** In
   `_compute_idle_buttons` 1606-1617 `tile` is index 0 so
   `tile_key == 0` on every deck with one column or more; `timer_key`
   is 1, an overflow key, or -1, never 0. The guard never changes the
   outcome. Drop it: in `home.py` home keys are distinct by
   construction. No screen change at any geometry. Add one test that
   TILE and TIMER never share a key at the four geometries.
2. **TIMER with `timer_key == -1`.** On a 1-column deck (or `cols==1,
   rows<3`) TIMER gets no key; today's `key == -1` never matches. The
   generic allocation reproduces it ("the rest get no key").
3. **Idle dispatch order.** Today the dashboard branch (2174-2213) is
   tested before TIMER (2214) and TILE (2217), and the TODO button,
   mic and shortcuts before both. Keys are disjoint (1868-1876
   excludes home keys from `claude_keys`), so order does not matter;
   `home.py` keeps disjointness as an invariant.
4. **Pruning lives in the home render.** `hidden_ids &= running` runs
   only in `_render_idle` (3010-3014), not in the timer page nor in the
   tap. Consequence kept: CLEAN DASH, then stop+restart the same timer
   while staying on the timer page -> back home, the first render
   prunes it (it was stopped only if a home render saw it stopped; if
   no home render happened while stopped, it stays hidden). `home.py`
   must call `items` on every home render even when no dashboard key
   is free (today the prune runs before the allocation regardless of
   `claude_keys` length); otherwise the hidden set drifts. Spec line
   "the dashboard once per render" covers it; add a test with 0 free
   dashboard keys (e.g. 3x2 with all home buttons).
5. **Dashboard tile tap.** Today 2174-2213 re-reads mpv/claude lists
   and `self.timers` at tap time; B2's deliberate change makes the tap
   read the last render's map. For timers `press` ignores the item
   (always opens the list), so the only visible difference is which
   provider a shifted key belongs to; it is the spec's accepted change.
6. **Two 2 s schedules, one shared with TODO.** `last_timer_refresh`
   (3469) is the page tick; `last_idle_refresh` (3470) is shared by the
   idle refresh (2 s) AND the TODO session poll (1 s, 3501-3514). After
   B2 the timers home tick has its own timestamp, so returning home
   from a TODO session refreshes timers on the next 0.3 s pass instead
   of up to 2 s later. Not visible in a frozen render; characterization
   tests must not pin tick timing across a todo_session -> idle
   transition. Kernel must keep: page tick timestamp per page (not
   reset on entry: today `_enter_timer_mode` refreshes, and the loop
   may refresh again on the next pass if 2 s elapsed since the last
   page tick; same with a per-page timestamp initialised to 0); first
   home tick immediate at start (`last_idle_refresh = 0`).
7. **Flash suppresses ticks.** The loop's `if self.last_result:`
   (3479) takes precedence over every tick while a flash is set, even
   before expiry (it only renders once expired; `render()` clears
   `last_result`, 2702). Kernel precedence step 1 must be "flash set ->
   render if expired, else nothing", not "expired flash -> render, else
   fall through to ticks". Otherwise CLEAN DASH's OK flash could be
   cleared/re-rendered by a 2 s page tick mid-flash (the overlay is
   repainted by render, so the screen is the same, but the call log is
   not).
8. **Render count in handlers.** Reset confirm sets `mode` before the
   flash and renders once (2649-2656). With `ctx.goto` rendering, call
   `ctx.flash` first then `ctx.goto(LIST)` (draft does) for one render
   with the overlay. For "cancel" (2641-2645) `ctx.goto(LIST)` = one
   render, no refresh, as today. References should record the final
   per-key image, or the full call log if renders match one-to-one; the
   draft keeps one render per press everywhere.
9. **Export failure has no reason.** 2673-2675 sets `err` without
   `_flag_err`; the reason is the "CSV write error" line printed by the
   writer (1159). Use `ctx.flash(False)` with no reason (draft:
   `ctx.flash(export_csv(...))`). Cancelled dialog: no flash, render
   (2669-2671).
10. **`_handle_export` blocks up to 180 s under the lock** (zenity,
    1130) and every gdbus call up to 3 s. B3 scope: keep as is.
11. **`json.loads` may return a non-list** (`null`, an object):
    `self.timers or []` guards 2197, 3013, 3016, 2287, but
    `_refresh_timers` 2685 `enumerate(self.timers)` raises on `None`,
    and `_render_timer_list` 3425 iterates it. Today that exception
    escapes into the loop thread / key callback. After B2 the kernel's
    isolation catches it (tick -> go home). Do not normalise silently in
    the move commit; if wanted, a separate `[FIX]` returning `[]` when
    the payload is not a list.
12. **`COLOR_TIMER_TITLE` is borrowed by the TODO home button** (3072).
    Put it in `ui/colors.py`; `todo_terminals` imports it from there,
    never from `plugins.timers` (no plugin-to-plugin import).
13. **`_icon_timer` is used by two faces** (home button, dashboard
    tile) via the `"timer"` key in `_ICONS` (1400). It stays in
    `ui/icons.py`; the plugin passes `icon="timer"`.
14. **Timer list labels have no icon** (3435) while the dashboard tile
    has `icon="timer"` (3091), so the dashboard tile text only shows
    when `_show_labels` is on (set_key 1495). Keep both faces exactly.
15. **Timer page geometry floor.** n < 6 would put CLEAN at key <= 0
    (n=5 -> CLEAN at 0, shadowed by BACK's earlier test). All supported
    decks have n >= 6; the characterization geometries 3x2, 4x2, 5x3,
    8x4 cover it. No guard added.
16. **Journal text.** `ctx.log` adds the `[timers]` prefix to the
    "Timer list dbus" etc. lines; `_flag_err`'s `[erplibre-home] `
    prefix becomes the kernel's. Not on the deck; tests asserting stderr
    must follow.
