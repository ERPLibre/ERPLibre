# B2 map: plugins `layouts`, `tiling`, `dev_reload`

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD
`b61156bf`). Every range below was checked with `sed -n` / `grep -n`.
Ranges are inclusive and exclude the trailing blank lines.

## 1. Module-level names owned by the domain

### layouts

| Name | Lines | Target |
|---|---|---|
| `COLOR_LAYOUT_TITLE = (80, 150, 80)` | 67 | `ui/colors.py` (shared: also claude page, 2989) |
| `COLOR_SAVE = (180, 140, 0)` | 68 | `ui/colors.py` (only layouts uses it) |
| `COLOR_LOAD_FILLED = (0, 150, 80)` | 69 | `ui/colors.py` (shared: translator history, 3193) |
| `COLOR_LOAD_EMPTY = (60, 60, 60)` | 70 | `ui/colors.py` |
| `LAYOUT_DIR = os.path.expanduser("~/.config/erplibre-home")` | 88 | `paths.py` as `CONFIG_DIR` (also the dir of `SETTINGS_FILE`, 90; not XDG-aware today, keep literal `~/.config`) |
| `LAYOUT_FILE` | 89 | `plugins/layouts.py` (built on `paths.CONFIG_DIR`) |
| `NUM_LAYOUT_SLOTS = 3` | 91 | `plugins/layouts.py` |
| `_layouts_load()` | 956-961 | `plugins/layouts.py` |
| `_layouts_save(data)` | 964-967 | `plugins/layouts.py` (keeps `os.makedirs(LAYOUT_DIR, exist_ok=True)`) |
| `_list_windows_dbus()` | 1013-1032 | `plugins/layouts.py`, via `ctx.dbus` |
| `_apply_layout_dbus(windows)` | 1035-1056 | `plugins/layouts.py`, via `ctx.dbus` |
| `_save_layout_slot(slot_id)` | 1059-1070 | `plugins/layouts.py` (uses `datetime.now()`, import at 32) |
| `_load_layout_slot(slot_id)` | 1073-1079 | `plugins/layouts.py` |
| `_delete_layout_slot(slot_id)` | 1082-1089 | `plugins/layouts.py` |
| `_icon_layout(draw, w, h)` | 1269-1285 | `ui/icons.py` (registered `"layout"`, `_ICONS` 1403) |
| `_draw_layout_preview(draw, w, h, windows, slot_num=None)` | 1411-1445 | `plugins/layouts.py` (only user; calls `_load_label_font(14)` 1444 -> `ui.render.load_label_font`) |
| labels `'LAYOUT'`, `'SAVE'`, `'EMPTY'`, `'BACK'`, `'CANCEL'`, `'DELETE'`, `'DECK\nTOO\nSMALL'` | 124-178 (table) | `ui/i18n.py` (shared table, unchanged) |
| `MODE_LAYOUT`, `MODE_LAYOUT_DELETE_CONFIRM` | 533-534 | become `Page.id` strings in the plugin |

### tiling

| Name | Lines | Target |
|---|---|---|
| `COLOR_GRID = (40, 60, 100)` | 47 | `ui/colors.py` (tiling only) |
| `COLOR_SELECTED = (0, 180, 255)` | 48 | `ui/colors.py` (tiling only) |
| `COLOR_PREVIEW = (0, 120, 60)` | 49 | dead (see Traps T7); delete in the dead-code commit |
| `COLOR_TITLE = (0, 80, 160)` | 50 | `ui/colors.py` (shared: mpv 2935, claude 2980) |
| `TILING_IDLE_TIMEOUT_SEC = 5.0` | 116 (comment 112-115) | `plugins/tiling.py` |
| `_tile_via_dbus(grid_cols, grid_rows, c1, r1, c2, r2)` | 554-574 | `plugins/tiling.py`, via `ctx.dbus` |
| `_icon_tile(draw, w, h)` | 1192-1199 | `ui/icons.py` (`"tile"`, 1399) |
| label `'TILE'` | table | `ui/i18n.py` |
| `MODE_TILING` | 529 | `Page.id` |

### dev_reload

| Name | Lines | Target |
|---|---|---|
| `COLOR_DEV_RELOAD = (160, 40, 120)` | 61 | `ui/colors.py` |
| `_hot_reload_extension()` | 1092-1114 | `plugins/dev_reload.py`, via `ctx.dbus` |
| `_icon_dev_reload(draw, w, h)` | 1218-1237 | `ui/icons.py` (`"dev_reload"`, 1401; keeps its local `import math`) |

### Shared, not owned (used by the domain)

| Name | Lines | Owner |
|---|---|---|
| `DBUS_DEST/PATH/IFACE` | 546-548 | `dbus.py` |
| `_parse_gdbus_string_tuple` | 593-607 | `dbus.py` (also used at 278, 308, 626, 675) |
| `_check_dbus_available` (looks for `"TileWindow"`) | 577-590 | kernel / `dbus.py` (`available`) |
| `COLOR_EMPTY` 46, `COLOR_BACK` 54, `COLOR_CONFIRM` 58, `COLOR_CANCEL` 59, `COLOR_OK` 103, `COLOR_ERR` 104 | | `ui/colors.py` |
| `_t` | 181-184 | `ui/i18n.py` -> `ctx.t` |
| `_load_label_font` | 1470-1480 | `ui/render.py` |

## 2. Tiler methods owned

| Method / fragment | Lines | Reads | Writes | Other-domain calls |
|---|---|---|---|---|
| `_compute_layout_buttons` | 1933-1947 | `cols`, `rows` | `layout_keys` | none |
| `_compute_idle_buttons`, layout-shortcut part | 1619-1627 | `layout_key`, `rows`, `cols` | `layout_shortcut_keys` | none; read by `_compute_claude_buttons` 1874 (dashboard exclusion) |
| `_compute_idle_buttons`, order list | 1602-1605 | | `tile_key`, `dev_reload_key`, `layout_key` (+ others) | kernel `home.py` |
| `_handle_idle_key`, DEV RELOAD | 2128-2133 | `dev_reload_key` | `last_result`, `result_time` | `_hot_reload_extension`, `render` |
| `_handle_idle_key`, LAYOUT | 2138-2141 | `layout_key` | `mode` | `render` |
| `_handle_idle_key`, layout shortcut | 2161-2173 | `layout_shortcut_keys` | `last_result`, `result_time` | `_layouts_load`, `_load_layout_slot`, `_flag_err`, `render` |
| `_handle_idle_key`, TILE | 2217-2223 | `tile_key` | `mode`, `corner1`, `corner2`, `last_result`(=None), `_tiling_last_touch` | `render` |
| `_handle_tiling_key` | 2225-2254 | `cols`, `corner1`, `grid_cols`, `grid_rows` | `_tiling_last_touch`, `corner1`, `corner2`, `last_result`, `result_time`, `mode` | `_tile_via_dbus`, `_flag_err`, `render` |
| `_handle_layout_key` | 2304-2341 | `layout_keys` | `mode`, `last_result`, `result_time`, `layout_delete_pending` | `_save_layout_slot`, `_load_layout_slot`, `_layouts_load`, `_flag_err`, `render` |
| `_handle_layout_delete_confirm_key` | 2343-2363 | `total_keys`, `layout_delete_pending` | `layout_delete_pending`, `mode`, `last_result`, `result_time` | `_delete_layout_slot`, `_flag_err`, `render` |
| `_render_idle`, shortcut prep | 3000-3005 | `layout_shortcut_keys` | local `shortcut_slots` | `_layouts_load` |
| `_render_idle`, TILE face | 3046-3048 | `tile_key` | | `set_key`, `_t` |
| `_render_idle`, DEV RELOAD face | 3052-3054 | `dev_reload_key` | | `set_key` |
| `_render_idle`, LAYOUT face | 3058-3060 | `layout_key` | | `set_key`, `_t` |
| `_render_idle`, shortcut face | 3076-3078 | local `shortcut_slots` | | `set_key` |
| `_render_layout` | 3113-3161 | `layout_keys`, `total_keys` | | `_layouts_load`, `_draw_layout_preview`, `set_key`, `_t` |
| `_render_layout_delete_confirm` | 3163-3178 | `layout_delete_pending`, `total_keys`, `cols` | | `set_key`, `_t` |
| `_render_tiling` | 3380-3393 | `corner1`, `cols`, `total_keys` | | `set_key` |
| `loop`, tiling timeout branch | 3483-3494 | `mode`, `_tiling_last_touch` | `mode`, `corner1`, `corner2`, `_tiling_last_touch` | `render` |
| `handle_key` dispatch | 1987-1988, 1995-1998 | `mode` | | kernel |
| `_render_mode` dispatch | 2708-2709, 2716-2719 | `mode` | | kernel |
| `__init__` call | 1595 -> 1597-1642 (`_compute_layout_buttons` call 1635) | | | kernel |

`_flag_err` (1763-1769) = `ctx.flash(False, reason)`. The direct
`last_result = "ok"; result_time = time.monotonic()` pairs (2130-2131,
2165-2166, 2243-2244, 2316-2317, 2326-2327, 2358-2359) = `ctx.flash(True)`.

## 3. Per-plugin state (`ctx.state(<id>)`)

| Plugin | Attribute today | Init (line) | New name | Note |
|---|---|---|---|---|
| tiling | `corner1` | `None` (1531) | `st.corner1` | `(col, row)` |
| tiling | `corner2` | `None` (1532) | drop | written 2235, read only on 2236-2239 in the same call, reset 2253/2220/3492: a local |
| tiling | `_tiling_last_touch` | `0.0` (1544) | `st.last_touch` | monotonic seconds |
| tiling | `grid_cols`, `grid_rows` | `cols`, `rows` (1526-1528) | drop | always equal to `ctx.geo.cols/rows` |
| layouts | `layout_delete_pending` | `None` (1556-1557) | `st.delete_pending` | int slot 1..3 |
| layouts | `layout_keys` | computed (1933-1947) | not state | `Page.keys(geo)` (see T2) |
| layouts | `layout_shortcut_keys` | computed (1619-1627) | not state | `Fixture.place` |
| dev_reload | none | | | |

## 4. Pages

| Page id | keys | render | handle | tick / period | Loop branch |
|---|---|---|---|---|---|
| `"tiling"` | none named; `lambda geo: {}` | `_render_tiling` 3380-3393 | `_handle_tiling_key` 2225-2254 | `tick` = timeout 3483-3494, `period=0.0` (each 0.3 s loop pass) | 3483-3494 |
| `"layout"` | `_compute_layout_buttons` 1933-1947: `None` when `cols < 4 or rows < 3`, else `{"back": 0, "save": [cols+1+i], "load": [2*cols+1+i], "delete": [3*cols+1+i] if rows >= 4 else []}`, i in 0..2 | `_render_layout` 3113-3161 | `_handle_layout_key` 2304-2341 | none | none |
| `"layout_delete_confirm"` | none named (0, `total-1`, `mid = total//2`, `mid-1`) | `_render_layout_delete_confirm` 3163-3178 | `_handle_layout_delete_confirm_key` 2343-2363 | none | none |

Behaviour to pin, per page:

- `tiling` render: key `(c, r)`: `corner1` -> `COLOR_SELECTED "1"`;
  else `COLOR_GRID f"{c},{r}"`. Handle: any key; first press sets
  `corner1`, renders; second press computes the min/max box, calls
  `TileWindow(cols, rows, c1, r1, c2, r2)`, flash ok / err with reason
  `f"TileWindow({cols}x{rows} {c1},{r1}-{c2},{r2}) failed via D-Bus"`,
  resets, goes home (one render). Tick: if `last_touch > 0` and
  `now - last_touch >= 5.0`: reset `corner1`, `last_touch = 0.0`, home.
- `layout` render: `layout_keys is None` -> key 0 `COLOR_BACK t("BACK")`,
  key `total//2` `COLOR_ERR t("DECK\nTOO\nSMALL")`, rest `COLOR_EMPTY ""`.
  Else back `COLOR_BACK t("BACK")`; save i `COLOR_SAVE f"{t('SAVE')}\n{i+1}"`;
  load i filled -> `COLOR_LOAD_FILLED ""` + `extra_draw` preview of
  `slot["windows"]` with `slot_num=i+1`; empty ->
  `COLOR_LOAD_EMPTY f"LOAD {i+1}\n{t('EMPTY')}"`; delete i filled ->
  `COLOR_CANCEL f"DEL {i+1}"`, empty -> `COLOR_EMPTY ""`; rest empty.
  Handle: keys None -> home on any key; back -> home; save -> ListWindows
  + write, flash ok / `f"layout save slot {slot} failed"`, render; load
  -> ApplyLayout, flash ok / `f"layout load slot {slot} failed"`, render;
  delete on empty slot -> nothing (no render); delete on filled ->
  `delete_pending = slot`, goto `layout_delete_confirm`; other keys ->
  nothing.
- `layout_delete_confirm` render: `slot = pending or "?"`; key 0
  `COLOR_CANCEL t("CANCEL")`; `total-1` `COLOR_CONFIRM t("OK")`;
  `mid-1` (cols >= 3) `COLOR_EMPTY t("DELETE")`; `mid` (cols >= 3)
  `COLOR_EMPTY f"SLOT\n{slot}?"`; `mid` (cols < 3) `f"DEL\n{slot}?"`;
  rest empty. The elif order (0, total-1 first) wins on tiny decks.
  Handle: 0 -> pending None, goto `layout`; `total-1` -> delete, pending
  None, flash ok / `f"layout delete slot {slot} failed"`, goto `layout`
  (one render); other keys ignored (no render).

Reachability at the four test geometries (home order tile 0, timer 1,
dev_reload 2, sound 3, layout 4, ...): LAYOUT has no key at 3x2 and 4x2
(rows < 3, no overflow) and `layout_keys` is `None` at those sizes and at
any `cols < 4`; at 5x3 LAYOUT is key 4, page dict without delete row;
8x4 has the delete row. Characterization must `goto("layout")` directly
at 3x2 / 4x2 to pin the DECK TOO SMALL page.

## 5. Home contributions

| Plugin | Kind | Order / place | Face | Press | Source lines |
|---|---|---|---|---|---|
| tiling | HomeButton | 10 | `KeyFace(COLOR_TITLE, t("TILE"), icon="tile")` | `corner1=None`, `last_touch=time.monotonic()`, `goto("tiling")` | face 3046-3048, press 2217-2223 |
| dev_reload | HomeButton | 30 | `KeyFace(COLOR_DEV_RELOAD, "DEV\nRELOAD", icon="dev_reload")` (not translated) | `ok = hot_reload(ctx)`; `ctx.flash(ok)` with no reason; `ctx.render()` | face 3052-3054, press 2128-2133 |
| layouts | HomeButton | 50 | `KeyFace(COLOR_LAYOUT_TITLE, t("LAYOUT"), icon="layout")` | `goto("layout")` | face 3058-3060, press 2138-2141 |
| layouts | Fixture | place: `lk = home_keys["layouts"]`; if `lk >= 0 and rows >= 2 and lk + 3 <= cols`: `[(rows-1)*cols + lk + i for i in 0..2]` else `[]` | slot `i+1` filled in `layouts.json` -> `KeyFace(COLOR_LOAD_FILLED, f"*\n{slot}")`; empty -> `None` (kernel paints `COLOR_EMPTY ""`, as the monolith's fall-through does) | empty slot -> nothing (no render, no flash); else `ApplyLayout`, flash ok / `f"layout shortcut load slot {slot} failed"`, render | place 1619-1627, face 3000-3005 + 3076-3078, press 2161-2173 |

No TileProvider in these three plugins. The fixture keys stay out of the
dashboard even when the face is `None` (today `used.update(...)` at 1874
reserves them whatever the slot state).

Placement at the four geometries: shortcut keys exist only at 8x4
(`[28, 29, 30]`); at 5x3 `4 + 3 > 5`.

## 6. External side effects to stub

| Effect | Lines | Detail |
|---|---|---|
| `subprocess.run` gdbus TileWindow | 557-567 | argv `["gdbus","call","--session","--dest","org.gnome.Shell","--object-path","/org/gnome/Shell/Extensions/ERPLibreHome","--method","org.gnome.Shell.Extensions.ERPLibreHome.TileWindow", str(cols), str(rows), str(c1), str(r1), str(c2), str(r2)]`, `capture_output=True, text=True, timeout=3`; success iff `returncode == 0 and "true" in stdout.lower()` |
| gdbus ListWindows | 1016-1024 | argv `[... "--method", f"{IFACE}.ListWindows"]`, timeout 3; `returncode != 0` -> `[]`; stdout `('<json>',)` -> `_parse_gdbus_string_tuple` -> `json.loads`; any exception -> `[]` |
| gdbus ApplyLayout | 1039-1047 | argv `[... f"{IFACE}.ApplyLayout", json.dumps(windows)]`, timeout 10; count from `re.search(r"\((\d+),\)", stdout.strip())`, else 0; success iff count > 0 |
| gdbus HotReload | 1095-1103 | argv `[... f"{IFACE}.HotReload"]`, timeout 10; ok iff `returncode == 0` and `bool(_parse_gdbus_string_tuple(stdout))` (a non-empty string) |
| read `~/.config/erplibre-home/layouts.json` | 956-961 | called by: idle render when shortcut keys exist (3002), idle shortcut press (2163), layout render (3125), layout delete press (2336), save/load/delete (1063, 1074, 1083); missing / bad JSON -> `{"slots": {}}` |
| write `layouts.json` | 964-967 | `os.makedirs(dir, exist_ok=True)`, `json.dump(indent=2)`; from save (1069) and delete (1088) |
| `datetime.now().strftime("%H:%M")` | 1065 | `saved_at` of a saved slot; not displayed, only written |
| `time.monotonic()` | 2131, 2166, 2222, 2228, 2244, 2317, 2327, 2359 (+ `_flag_err` 1769) | tiling `last_touch` and flash times |
| loop `now` | 3472, 3485-3486 | tiling timeout compares `now - last_touch >= 5.0` |
| `_t` calls | 3047, 3059, 3118, 3120, 3128, 3131, 3149, 3168, 3170, 3172 | `TILE`, `LAYOUT`, `BACK`, `DECK\nTOO\nSMALL`, `SAVE`, `EMPTY`, `CANCEL`, `OK` (not in the table, stays `OK`), `DELETE`; untranslated literals: `DEV\nRELOAD`, `LOAD n\n…`, `DEL n`, `SLOT\nn?`, `DEL\nn?`, `*\nn`, `1`, `c,r` |
| font | 1444 | `_load_label_font(14)` inside the preview `extra_draw` |
| stderr lines | 570, 573, 1026, 1031, 1050, 1055, 1105-1107, 1112-1113, 1767 | `Tiler dbus: …`, `Tiler dbus error: …`, `ListWindows dbus: …`, `ListWindows error: …`, `ApplyLayout dbus: …`, `ApplyLayout error: …`, `[erplibre-home] HotReload dbus: …`, `[erplibre-home] HotReload error: …`, `[erplibre-home] <reason>`; no test pins them (grep of `test/` and `test_erplibre_streamdeck_chunks.py`) |

Translator calls: none in these domains.

## 7. Draft plugin modules

Assumed `ctx.dbus.call(method, *args, timeout=3)` builds the argv above
(`str()` on each arg) and returns the `subprocess.CompletedProcess`,
letting `subprocess`/`OSError` exceptions propagate; `dbus.parse_string_
tuple` is the moved `_parse_gdbus_string_tuple`. `ctx.flash` only records
the flash; the caller renders (see T3). `ctx.home_keys` is the gap of T4.

`plugins/tiling.py`:

```python
"""Tiling: pick two corners on the deck grid, the focused window is
tiled to that box by the extension's TileWindow method."""

import time

from erplibre_streamdeck.plugin import HomeButton, KeyFace, Page, Plugin
from erplibre_streamdeck.ui import colors

# A half-started selection drops back home after this much inactivity.
IDLE_TIMEOUT_SEC = 5.0


def _st(ctx):
    return ctx.state("tiling")


def _setup(ctx):
    st = _st(ctx)
    st.corner1 = None
    st.last_touch = 0.0


def _reset(st):
    st.corner1 = None
    st.last_touch = 0.0


def _tile(ctx, c1, r1, c2, r2):
    cols, rows = ctx.geo.cols, ctx.geo.rows
    try:
        r = ctx.dbus.call("TileWindow", cols, rows, c1, r1, c2, r2)
    except Exception as e:
        ctx.log(f"Tiler dbus error: {e}")
        return False
    if r.returncode == 0 and "true" in r.stdout.lower():
        return True
    ctx.log(f"Tiler dbus: {r.stdout} {r.stderr}")
    return False


def _render(ctx):
    st = _st(ctx)
    cols = ctx.geo.cols
    for key in range(ctx.geo.total_keys):
        c, r = key % cols, key // cols
        if (c, r) == st.corner1:
            ctx.set_key(key, KeyFace(colors.COLOR_SELECTED, "1"))
        else:
            ctx.set_key(key, KeyFace(colors.COLOR_GRID, f"{c},{r}"))


def _handle(ctx, key):
    st = _st(ctx)
    st.last_touch = time.monotonic()
    cols = ctx.geo.cols
    corner = (key % cols, key // cols)
    if st.corner1 is None:
        st.corner1 = corner
        ctx.render()
        return
    (a, b), (x, y) = st.corner1, corner
    c1, r1, c2, r2 = min(a, x), min(b, y), max(a, x), max(b, y)
    if _tile(ctx, c1, r1, c2, r2):
        ctx.flash(True)
    else:
        ctx.flash(False, f"TileWindow({ctx.geo.cols}x{ctx.geo.rows} "
                         f"{c1},{r1}-{c2},{r2}) failed via D-Bus")
    _reset(st)
    ctx.home()


def _tick(ctx, now):
    st = _st(ctx)
    if st.last_touch > 0 and now - st.last_touch >= IDLE_TIMEOUT_SEC:
        _reset(st)
        ctx.home()


def _face(ctx):
    return KeyFace(colors.COLOR_TITLE, ctx.t("TILE"), icon="tile")


def _press(ctx):
    st = _st(ctx)
    st.corner1 = None
    st.last_touch = time.monotonic()
    ctx.goto("tiling")


PLUGIN = Plugin(
    api=1,
    setup=_setup,
    pages=[Page(id="tiling", keys=lambda geo: {}, render=_render,
                handle=_handle, tick=_tick, period=0.0)],
    home_buttons=[HomeButton(order=10, face=_face, press=_press)],
)
```

`plugins/layouts.py`:

```python
"""Window layouts: three slots saved from and applied to the extension
(ListWindows / ApplyLayout), stored in layouts.json."""

import json
import os
import re
from datetime import datetime

from erplibre_streamdeck import dbus, paths
from erplibre_streamdeck.plugin import (
    Fixture, HomeButton, KeyFace, Page, Plugin)
from erplibre_streamdeck.ui import colors
from erplibre_streamdeck.ui.render import load_label_font

NUM_SLOTS = 3
LAYOUT_FILE = os.path.join(paths.CONFIG_DIR, "layouts.json")


def _load():
    try:
        with open(LAYOUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"slots": {}}


def _save(data):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    with open(LAYOUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _list_windows(ctx):
    try:
        r = ctx.dbus.call("ListWindows")
        if r.returncode != 0:
            ctx.log(f"ListWindows dbus: {r.stderr}")
            return []
        payload = dbus.parse_string_tuple(r.stdout)
        return json.loads(payload) if payload else []
    except Exception as e:
        ctx.log(f"ListWindows error: {e}")
        return []


def _apply(ctx, windows):
    try:
        r = ctx.dbus.call("ApplyLayout", json.dumps(windows), timeout=10)
        if r.returncode != 0:
            ctx.log(f"ApplyLayout dbus: {r.stderr}")
            return 0
        m = re.search(r"\((\d+),\)", r.stdout.strip())
        return int(m.group(1)) if m else 0
    except Exception as e:
        ctx.log(f"ApplyLayout error: {e}")
        return 0


def _save_slot(ctx, slot):        # was _save_layout_slot 1059-1070
    ...


def _load_slot(ctx, slot):        # was _load_layout_slot 1073-1079
    ...


def _delete_slot(slot):           # was _delete_layout_slot 1082-1089
    ...


def _draw_preview(draw, w, h, windows, slot_num=None):
    ...                           # 1411-1445 verbatim, load_label_font


def _page_keys(geo):
    if geo.cols < 4 or geo.rows < 3:
        return None
    c = geo.cols
    return {
        "back": 0,
        "save": [c + 1 + i for i in range(NUM_SLOTS)],
        "load": [2 * c + 1 + i for i in range(NUM_SLOTS)],
        "delete": ([3 * c + 1 + i for i in range(NUM_SLOTS)]
                   if geo.rows >= 4 else []),
    }


def _render_layout(ctx):
    lk = _page_keys(ctx.geo)
    ...                           # 3113-3161 with ctx.set_key / ctx.t


def _handle_layout(ctx, key):
    lk = _page_keys(ctx.geo)
    ...                           # 2304-2341; flash then ctx.render()


def _render_confirm(ctx):
    ...                           # 3163-3178, slot from state


def _handle_confirm(ctx, key):
    ...                           # 2343-2363; flash then goto("layout")


def _shortcut_keys(geo, home_keys):
    lk = home_keys.get("layouts", -1)
    if lk < 0 or geo.rows < 2 or lk + NUM_SLOTS > geo.cols:
        return []
    base = (geo.rows - 1) * geo.cols + lk
    return [base + i for i in range(NUM_SLOTS)]


def _slot_of(ctx, key):
    return _shortcut_keys(ctx.geo, ctx.home_keys).index(key) + 1


def _shortcut_face(ctx, key):
    slot = _slot_of(ctx, key)
    if str(slot) not in _load().get("slots", {}):
        return None
    return KeyFace(colors.COLOR_LOAD_FILLED, f"*\n{slot}")


def _shortcut_press(ctx, key):
    slot = _slot_of(ctx, key)
    if str(slot) not in _load().get("slots", {}):
        return
    if _load_slot(ctx, slot):
        ctx.flash(True)
    else:
        ctx.flash(False, f"layout shortcut load slot {slot} failed")
    ctx.render()


def _setup(ctx):
    ctx.state("layouts").delete_pending = None


PLUGIN = Plugin(
    api=1,
    setup=_setup,
    pages=[
        Page(id="layout", keys=_page_keys, render=_render_layout,
             handle=_handle_layout),
        Page(id="layout_delete_confirm", keys=lambda geo: {},
             render=_render_confirm, handle=_handle_confirm),
    ],
    home_buttons=[HomeButton(
        order=50,
        face=lambda ctx: KeyFace(colors.COLOR_LAYOUT_TITLE,
                                 ctx.t("LAYOUT"), icon="layout"),
        press=lambda ctx: ctx.goto("layout"),
    )],
    fixtures=[Fixture(place=_shortcut_keys, face=_shortcut_face,
                      press=_shortcut_press)],
)
```

`plugins/dev_reload.py`:

```python
"""DEV RELOAD: ask the GNOME extension to reload itself (HotReload)."""

from erplibre_streamdeck import dbus
from erplibre_streamdeck.plugin import HomeButton, KeyFace, Plugin
from erplibre_streamdeck.ui import colors


def _hot_reload(ctx):
    try:
        r = ctx.dbus.call("HotReload", timeout=10)
        if r.returncode != 0:
            ctx.log(f"HotReload dbus: {r.stderr.strip()}")
            return False
        return bool(dbus.parse_string_tuple(r.stdout))
    except Exception as e:
        ctx.log(f"HotReload error: {e}")
        return False


def _press(ctx):
    ctx.flash(_hot_reload(ctx))
    ctx.render()


PLUGIN = Plugin(
    api=1,
    home_buttons=[HomeButton(
        order=30,
        face=lambda ctx: KeyFace(colors.COLOR_DEV_RELOAD, "DEV\nRELOAD",
                                 icon="dev_reload"),
        press=_press,
    )],
)
```

## 8. Traps

- **T1 Tick precedence.** The monolith's loop (3478-3494) runs the tiling
  timeout only when `last_result` is falsy: a pending flash, expired or
  not, skips the tick for that pass. Kernel rule 1 must be "if a flash is
  recorded: render if expired, and do nothing else this pass", not "if
  expired". Tiling's `period=0.0` means "every pass"; the timeout is
  measured from `last_touch`, not from the last tick, so the plugin keeps
  its own clock and `period` must not be 5.0.
- **T2 Page keys reach.** The spec gives `Page.keys(geo)` but no
  `ctx` member to read the computed dict. The draft recomputes
  `_page_keys(ctx.geo)` (pure, cheap). If the kernel exposes the cached
  dict (`ctx.keys`), swap. `keys` must be allowed to return `None`
  (layout page on decks < 4x3, which renders DECK TOO SMALL and sends
  any key home) or the plugin maps `{}` to that case.
- **T3 Flash does not render.** Every caller sets the flash then changes
  page and renders once (2243-2254, 2352-2362). `ctx.flash` must only
  record (`last_result`, `result_time`, journal line when `reason`), and
  `ctx.goto` / `ctx.home` / `ctx.render` render once, with the overlay.
  A flash that renders itself would record extra `set_key` calls of the
  old page in characterization.
- **T4 Fixture face/press need the slot index.** `Fixture.face(ctx, key)`
  receives only the key; the slot is its position in the `place()`
  result, which depends on the LAYOUT home key. Proposal: `Context` gains
  read-only `home_keys` (plugin id -> key or -1, the dict given to
  `place`), or the kernel passes the index. The `home_keys` dict must be
  keyed by plugin id (one home button per plugin today); `place()` reads
  `home_keys.get("layouts", -1)`, so the fixture vanishes when the
  LAYOUT button gets no key or overflows to row 1 (`lk + 3 <= cols` is
  false for any key on row 1).
- **T5 Fixture with an empty face still reserves its key.** An empty slot
  shortcut paints `COLOR_EMPTY ""` and is never a dashboard tile
  (1874). `home.py` must exclude all placed fixture keys from the
  dashboard and paint `COLOR_EMPTY ""` for a `None` face. A press on it
  is a silent no-op (no render, no flash).
- **T6 Fixture placement order.** Discovery order is file stem order:
  `layouts` < `sound`, the reverse of the monolith's render precedence
  (mic 3073 before shortcuts 3076). They never collide: the mic is key
  `(rows-1)*cols`, the shortcuts start at `(rows-1)*cols + lk` with
  `lk >= 1` whenever `sound` is on (order 40 < 50). With `sound` off the
  mic disappears. `home.py` should still skip a key already taken by an
  earlier fixture, and the test of each-plugin-off covers it.
- **T7 Dead code to clean (own commit, step 0).** In `_render_tiling`
  the `preview` set only ever holds `corner1`, which the first branch
  already catches, so the `COLOR_PREVIEW` branch (3381-3383 build `preview`, 3389-3390 the branch)
  never runs; `COLOR_PREVIEW` (49) is then unused. `corner2` is a local
  (T-state table). `grid_cols/grid_rows` (1526-1528) equal `cols/rows`.
  `self.last_result = None` on TILE (2221) is redundant: `handle_key`
  refuses presses during a live flash, and `render()` (2696-2703) drops
  an expired one before drawing, so the screen is the same without it.
- **T8 `timer_key != tile_key`.** The guards at 2214 and 3049 never
  matter: `tile_key` is always 0 and `timer_key` never 0 (it is 1, or
  `cols` on the overflow row when `cols == 1`). With one HomeButton per
  plugin and unique keys from `home.py`, the guard disappears; when
  `tiling` is off, TIMER takes key 0 and works, which the monolith never
  had to handle.
- **T9 DEV RELOAD has no journal reason.** It sets `last_result` directly
  (2130), not via `_flag_err`; only `_hot_reload_extension`'s own lines
  reach stderr. Keep `ctx.flash(ok)` without reason. It stays on the deck
  when the extension is missing (no `dbus_ok` check), as today.
- **T10 Journal text changes.** `ctx.log` prefixes the plugin id, so
  `Tiler dbus: …` / `[erplibre-home] HotReload …` change wording. No test
  pins them; only the screen must stay identical.
- **T11 D-Bus call shapes differ.** Timeouts 3 (TileWindow, ListWindows)
  and 10 (ApplyLayout, HotReload); success tests differ (`"true" in
  stdout.lower()`, string tuple + JSON, `\((\d+),\)` count, non-empty
  string). `ctx.dbus.call` should return the raw `CompletedProcess` and
  take `timeout=`; parsing stays in the plugin, the tuple parser in
  `dbus.py`. Args go through `str()` (ints of TileWindow); the
  ApplyLayout JSON is one argv element, unquoted.
- **T12 Preview invisible to the recorder.** A `(key, color, text, icon)`
  recorder sees a filled load slot as `COLOR_LOAD_FILLED ""`; the
  preview lives in `extra_draw`. Characterization should call
  `extra_draw` on a recording `ImageDraw` stub and freeze its
  `rectangle` / `text` calls, or at least record `extra_draw is not
  None`. The preview needs `ImageFont.truetype` / `load_default`
  stubbed.
- **T13 Paths.** `layouts.json` lives under literal
  `~/.config/erplibre-home` (88), not `$XDG_CONFIG_HOME`; keep it so the
  on-disk contract holds. Tests must point `paths.CONFIG_DIR` (patched in
  `paths`, Risk 3) at a temp dir; `_save_slot` writes `saved_at` from
  `datetime.now()`, which is not displayed, so tests either stub it or
  never compare the file.
- **T14 Tiling timestamp source.** `handle` and home `press` use
  `time.monotonic()`; `tick` uses the loop's `now`, taken before the
  D-Bus recheck (3472) which can block up to 3 s. The kernel keeps
  passing that same `now`. Tests patch `time.monotonic` (module `time`,
  shared) and pass `now` explicitly to `tick`.
- **T15 Layout page unreachable on small decks.** At 3x2 and 4x2 LAYOUT
  has no home key, so neither the page nor the fixture exist through
  taps; parity tests set the page directly.
