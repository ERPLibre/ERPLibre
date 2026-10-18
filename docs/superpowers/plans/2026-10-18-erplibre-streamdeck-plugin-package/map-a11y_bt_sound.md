# B2 map: plugins `a11y`, `bluetooth`, `sound`

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD
`b61156bf`). Every range below was checked with `ast` (`lineno` /
`end_lineno`) or `sed -n`. Ranges are inclusive.

Headline: none of the three plugins owns a `Tiler` instance attribute
that is *state*. Their only `self.*` are geometry results (`*_keys`,
`*_key`, `mic_status_key`). Font scale and labels are module globals
(`_font_scale`, `_show_labels`) read by `set_key`: they become the
kernel's `ctx.style`, not `ctx.state("a11y")`.

---

## 1. Module-level names owned by the domain

### Colours (all go to `ui/colors.py`; several are shared)

| Name | Line | Used by (lines) | Note |
|---|---|---|---|
| `COLOR_SOUND_TITLE` | 62 | idle 3056, sound 3358 | |
| `COLOR_VOL` | 63 | sound 3351-3352; **also** todo 2831, claude 2982, translator 3251 | shared |
| `COLOR_MIC` | 64 | sound 3353-3354, 3361 | |
| `COLOR_MUTE_ON` | 65 | mic 3110, sound 3363, 3368 | |
| `COLOR_MUTE_OFF` | 66 | mic 3111, a11y 3325, sound 3366, 3371 | shared a11y/sound |
| `COLOR_A11Y_TITLE` | 71 | idle 3062 | |
| `COLOR_FONT_STEP` | 72 | a11y 3319-3320 | |
| `COLOR_FONT_RESET` | 73 | a11y 3321 | |
| `COLOR_BT_TITLE` | 74 | idle 3065 | |
| `COLOR_BT_ON` | 75 | bt 3276, 3293 | |
| `COLOR_BT_OFF` | 76 | bt 3278, 3293; **a11y 3325** | shared |
| `COLOR_BT_NA` | 77 | **mic 3108**, bt 3274 | shared |
| `COLOR_BACK` 54, `COLOR_EMPTY` 46, `COLOR_ERR` 104 | | everywhere | kernel/shared |

### Constants

| Name | Lines | Target |
|---|---|---|
| `VOL_STEP_PCT = 5` | 86 | `plugins/sound.py` |
| `FONT_SCALE_MIN/MAX/STEP/DEFAULT` | 93-96 | `ui/render.py` (Style clamps with MIN/MAX; a11y imports STEP/DEFAULT) |
| `_font_scale`, `_show_labels` (globals) | 98-99 | fields of `ui.render.Style`, instance at `ctx.style` |
| `MODE_SOUND` | 532 | page id `"sound"` in `plugins/sound.py` |
| `MODE_A11Y` | 535 | page id `"a11y"` in `plugins/a11y.py` |
| `MODE_BLUETOOTH` | 536 | page id `"bluetooth"` in `plugins/bluetooth.py` |
| `WPCTL_SINK`, `WPCTL_SOURCE` | 543-544 | `plugins/sound.py` |
| `_WPCTL_DEV_RE` | 869-871 | `plugins/sound.py` |

### Functions

| Name | Lines | Target |
|---|---|---|
| `_bt_powered` | 703-729 | `plugins/bluetooth.py` |
| `_bt_list_paired` | 732-763 | `plugins/bluetooth.py` |
| `_bt_connect` | 766-777 | `plugins/bluetooth.py` |
| `_bt_disconnect` | 780-791 | `plugins/bluetooth.py` |
| `_bt_set_power` | 794-815 | `plugins/bluetooth.py` |
| `_wpctl_available` | 818-819 | **dead** (no caller): delete in step 0 (spec lists it) |
| `_wpctl_get` | 822-840 | `plugins/sound.py` |
| `_wpctl_volume_delta` | 843-854 | `plugins/sound.py` |
| `_wpctl_mute_toggle` | 857-866 | `plugins/sound.py` |
| `_wpctl_list_devices` | 874-916 | `plugins/sound.py` |
| `_wpctl_set_default` | 919-928 | `plugins/sound.py` |
| `_wpctl_cycle_default` | 931-943 | `plugins/sound.py` |
| `_wpctl_default_short` | 946-953 | `plugins/sound.py` |
| `_settings_load` / `_settings_save` | 970-975 / 978-981 | `settings.py` (kernel; listed because a11y writes through it) |
| `_init_font_scale` | 984-993 | `ui/render.py`: `Style.restore(data)`, called by `app.main()` (see trap T1) |
| `_set_font_scale` | 996-1002 | `plugins/a11y.py` `_set_scale(ctx, scale)` (clamp via `Style`, persist via `ctx.settings`) |
| `_toggle_show_labels` | 1005-1010 | `plugins/a11y.py` `_toggle_labels(ctx)` |

### Icons (to `ui/icons.py`; registry `_ICONS` 1396-1408)

| Painter | Lines | Key in `_ICONS` | Other users |
|---|---|---|---|
| `_icon_mic` | 1167-1185 | `"mic_on"` (1397) | translator 3217 |
| `_icon_mic_off` | 1188-1189 | `"mic_off"` (1398) | translator 3217 |
| `_icon_sound` | 1240-1266 | `"sound"` (1402) | |
| `_icon_a11y` | 1288-1315 | `"a11y"` (1404) | |
| `_icon_bt` | 1341-1354 | `"bt"` (1405) | |

`_ICON_WHITE` / `_ICON_RED` (1163-1164) go with the painters.

### Labels (`_DECK_LABELS` 124-178 -> `ui/i18n.py`, unchanged)

Domain entries: `'SOUND'` 146, `'MIC\nN/A'` 150, `'MIC\nON'` 151,
`'MIC\nOFF'` 152, `'MIC\nMUTE'` 153, `'OUT\nMUTE'` 154, `'BT\nN/A'` 155.
Shared: `'BACK'` 127, `'RESET'` 137 (a11y font reset),
`'DECK\nTOO\nSMALL'` 161. Untranslated literals the plugins must keep
verbatim: `"A11Y"` (3062), `"BT"` (3065), `"BT\nON"` / `"BT\nOFF"`
(3276/3278), `"FONT\n-"` / `"FONT\n+"` (3319-3320), `f"SCALE\n{x:.1f}x"`
(3313), `"LABELS\nON|OFF"` (3314-3316), `f"VOL\n±{VOL_STEP_PCT}%"`,
`f"MIC\n±{VOL_STEP_PCT}%"` (3351-3354), `f"SINK\n{short}"` (3358),
`f"SRC\n{short}"` (3361), `f"OUT\n{v}%"` / `"OUT"` (3365),
`f"MIC\n{v}%"` / `"MIC"` (3370).

### Kernel-side code these plugins depend on

- `set_key` 1483-1514 reads `_show_labels` at 1495 and `_font_scale` at
  1497 on every call -> must read `ctx.style` at call time (spec risk 4).

---

## 2. Tiler methods owned

| Method | Lines | Reads | Writes | Calls into other domains |
|---|---|---|---|---|
| `_compute_bluetooth_buttons` | 1902-1916 | `cols`, `rows` | `bluetooth_keys` | none |
| `_compute_a11y_buttons` | 1918-1931 | `cols`, `rows` | `a11y_keys` | none |
| `_compute_sound_buttons` | 1949-1967 | `cols`, `rows` | `sound_keys` | none |
| `_handle_bluetooth_key` | 2556-2585 | `bluetooth_keys` | `mode` | `_flag_err` 1763-1770 (kernel flash), `render` |
| `_handle_a11y_key` | 2587-2607 | `a11y_keys`, global `_font_scale` | `mode`, globals via `_set_font_scale`/`_toggle_show_labels` | `render` |
| `_handle_sound_key` | 2609-2638 | `sound_keys` | `mode` | `render` |
| `_render_bluetooth` | 3261-3300 | `bluetooth_keys`, `total_keys`, `deck` | none | `set_key`, `_t` |
| `_render_a11y` | 3302-3332 | `a11y_keys`, `total_keys`, `deck`, globals | none | `set_key`, `_t` |
| `_render_sound` | 3334-3378 | `sound_keys`, `total_keys`, `deck` | none | `set_key`, `_t` |
| `_mic_indicator` | 3101-3111 | none | none | `_wpctl_get`, `_t` |

Fragments inside shared methods (kernel / home after B2):

| Fragment | Lines | Goes to |
|---|---|---|
| idle order list (`"sound"` idx 3, `"a11y"` 5, `"bluetooth"` 6) | 1602-1605 | HomeButton orders 40 / 60 / 70 |
| `mic_status_key` placement | 1629-1632 | sound Fixture `place` |
| calls `_compute_sound/a11y/bluetooth_buttons` | 1634, 1636, 1637 | dropped (pages compute their own keys) |
| `mic_status_key` excluded from dashboard (`used` set) | 1868-1871 | `home.py` (fixture keys are excluded generically) |
| `handle_key` dispatch: sound 1993-1994, a11y 1999-2000, bt 2001-2002 | | kernel dispatch by page id |
| idle press: sound 2134-2137, a11y 2142-2145, bt 2146-2149 | | HomeButton `press` |
| idle press: mic toggle 2157-2160 | | sound Fixture `press` |
| `_render_mode`: sound 2714-2715, a11y 2720-2721, bt 2722-2723 | | kernel render by page id |
| idle render: `_mic_indicator()` call 3006 | | sound Fixture `face` |
| idle render: sound 3055-3057, a11y 3061-3063, bt 3064-3065 | | HomeButton `face` |
| idle render: mic key 3073-3075 | | sound Fixture `face` |
| idle 2 s refresh branch (repaints the mic) | 3516-3531 | see trap T3 |
| `main`: `_init_font_scale()` | 3561 | `app.main()` -> `Style.restore` |

---

## 3. Per-plugin state (`ctx.state(<id>)`)

**Nothing moves.** `Tiler.__init__` (1518-1595) sets no attribute for
these domains; their attributes are created by `_compute_idle_buttons`
(1597-1641) and are pure functions of the geometry:

| Attribute | Set at | Replaced by |
|---|---|---|
| `sound_key`, `a11y_key`, `bluetooth_key` | 1606-1617 (setattr loop) | `home.py` allocation of the HomeButtons |
| `mic_status_key` | 1630-1632 | sound Fixture `place` |
| `sound_keys` | 1949-1967 | `sound._keys(geo)` |
| `a11y_keys` | 1918-1931 | `a11y._keys(geo)` |
| `bluetooth_keys` | 1902-1916 | `bluetooth._keys(geo)` |

Global display state moves to the kernel's `Style` (not `ctx.state`):

| Global | Initial | Restored by |
|---|---|---|
| `_font_scale` | `FONT_SCALE_DEFAULT` = 1.0 (98) | `_init_font_scale` 984-993, from `settings.json` key `font_scale`, clamped to [0.6, 2.5], `ValueError/TypeError` -> 1.0 |
| `_show_labels` | `False` (99) | same, key `show_labels`, `bool(...)` |

`setup` is not needed by any of the three.

---

## 4. Pages

All three: no `tick`, `period = 0.0` (the loop 3467-3543 has no branch for
`sound`, `a11y` or `bluetooth`).

### `"sound"` -> `Page("sound", keys, render, handle)`

- keys `_compute_sound_buttons` 1949-1967: `None` if `cols < 4 or
  rows < 3`; else `back 0`, `vol_down c+1`, `vol_up c+2`,
  `out_mute c+3`, `mic_down 2c+1`, `mic_up 2c+2`, `mic_mute 2c+3`,
  `sink 1`, `source 2` (the `if self.cols >= 4` at 1964 is always true
  there; keep the keys).
- render `_render_sound` 3334-3378. Too-small block 3336-3344. Call order:
  `_wpctl_get(SINK)` 3346, `_wpctl_get(SOURCE)` 3347,
  `_wpctl_default_short("Sinks")` 3357, `("Sources")` 3360. Then a
  `labels` dict, then every key painted (absent -> `COLOR_EMPTY, ""`).
- handle `_handle_sound_key` 2609-2638: falsy keys -> home; `back` ->
  home; each action key -> one wpctl call then render; other key ->
  return without render (2636-2637). No flash on failure.

### `"a11y"` -> `Page("a11y", keys, render, handle)`

- keys `_compute_a11y_buttons` 1918-1931: `None` if `cols < 4 or
  rows < 2`; else `back 0`, `font_down c+1`, `font_up c+2`,
  `font_reset c+3`, plus `labels_toggle c+4` when `cols >= 5`.
- render `_render_a11y` 3302-3332. Too-small 3304-3312. Assignment order
  matters (trap T4): back, font_down, font_up, font_reset,
  `total_keys // 2` (scale), then labels_toggle.
- handle `_handle_a11y_key` 2587-2607: falsy keys -> home; back -> home;
  font_down `_set_font_scale(_font_scale - STEP)`; font_up `+ STEP`;
  font_reset `DEFAULT`; labels_toggle `_toggle_show_labels()`
  (`ak.get(...)` returns None when absent; no key equals None); other
  key -> return without render. No flash.

### `"bluetooth"` -> `Page("bluetooth", keys, render, handle)`

- keys `_compute_bluetooth_buttons` 1902-1916: `None` if `cols < 2 or
  rows < 2`; else `back 0`, `toggle c+1`, `devices
  list(range(c+2, 2c))`.
- render `_render_bluetooth` 3261-3300. Too-small 3263-3271.
  `_bt_powered()` 3272; toggle face None -> `COLOR_BT_NA, t("BT\nN/A")`,
  True -> `COLOR_BT_ON, "BT\nON"`, False -> `COLOR_BT_OFF, "BT\nOFF"`.
  Devices listed only `if powered and device_keys` (3285-3286); label =
  last word of the name, 6 chars (3291-3292).
- handle `_handle_bluetooth_key` 2556-2585: falsy keys -> home; back ->
  home; toggle: `_bt_powered()`; None -> `_flag_err("bluetooth:
  bluetoothctl unavailable or no adapter")` + render; else
  `_bt_set_power(not current)` (result ignored) + render. Device key:
  `_bt_list_paired()` again; if idx in range, disconnect if connected
  else connect, then render; out of range -> no render. Other key -> no
  render.

Geometry table (keys exist / reachable from home):

| Geo | sound page | a11y page | bt page | home buttons (key) | mic fixture |
|---|---|---|---|---|---|
| 3×2 | too small | too small | back 0, toggle 4, dev [5] | none of the three | 3 |
| 4×2 | too small | 0; 5,6,7; scale@4 | back 0, toggle 5, dev [6,7] | SOUND 3 | 4 |
| 5×3 | full | 0; 6,7,8; labels 9; scale@7 (!) | toggle 6, dev [7,8,9] | SOUND 3, A11Y 5, BT 6 | 10 |
| 8×4 | full | 0; 9,10,11; labels 12; scale@16 | toggle 9, dev [10..15] | SOUND 3, A11Y 5, BT 6 | 24 |

---

## 5. Home contributions

| Plugin | Kind | Detail | From |
|---|---|---|---|
| `sound` | HomeButton order 40 | face `KeyFace(COLOR_SOUND_TITLE, t("SOUND"), "sound")`; press `ctx.goto("sound")` | face 3055-3057, press 2134-2137 |
| `a11y` | HomeButton order 60 | face `KeyFace(COLOR_A11Y_TITLE, "A11Y", "a11y")`; press `ctx.goto("a11y")` | 3061-3063, 2142-2145 |
| `bluetooth` | HomeButton order 70 | face `KeyFace(COLOR_BT_TITLE, "BT", "bt")`; press `ctx.goto("bluetooth")` | 3064-3065, 2146-2149 |
| `sound` | Fixture (mic) | place: `[(rows-1)*cols]` if `rows >= 2` else `[]`; face: `_mic_indicator` (vol None -> `COLOR_BT_NA, t("MIC\nN/A"), None`; muted -> `COLOR_MUTE_ON, t("MIC\nOFF"), "mic_off"`; else `COLOR_MUTE_OFF, t("MIC\nON"), "mic_on"`); press: `_wpctl_mute_toggle(WPCTL_SOURCE)` then `ctx.render()`, no flash | place 1629-1632, face 3101-3111 + 3073-3075, press 2157-2160 |

No TileProvider in these three plugins.

---

## 6. External side effects to stub

All `subprocess.run(..., capture_output=True, text=True, timeout=N)`.
Stub by argv (calls are not order-stable across pages). Also stub
`shutil.which` (bluetooth checks it before each call).

| Function | Lines | argv | timeout |
|---|---|---|---|
| `_bt_powered` | 705-729 | `shutil.which("bluetoothctl")`; `["bluetoothctl","show"]` (parses `Powered: yes`); fallback `shutil.which("rfkill")`, `["rfkill","list","bluetooth"]` (parses `Soft blocked: no`) | 2, 2 |
| `_bt_list_paired` | 732-763 | `which bluetoothctl`; `["bluetoothctl","devices","Paired"]`, `["bluetoothctl","devices","Connected"]` (lines `Device <MAC> <name>`) | 2, 2 |
| `_bt_connect` | 766-777 | `["bluetoothctl","connect",mac]` | 10 |
| `_bt_disconnect` | 780-791 | `["bluetoothctl","disconnect",mac]` | 5 |
| `_bt_set_power` | 794-815 | `["bluetoothctl","power","on"/"off"]`; fallback `["rfkill","unblock"/"block","bluetooth"]` | 3, 3 |
| `_wpctl_get` | 822-840 | `["wpctl","get-volume",target]` (`Volume: 0.50 [MUTED]`) | 2 |
| `_wpctl_volume_delta` | 843-854 | `["wpctl","set-volume","--limit","1.5",target,"5%+"/"5%-"]` | 2 |
| `_wpctl_mute_toggle` | 857-866 | `["wpctl","set-mute",target,"toggle"]` | 2 |
| `_wpctl_list_devices` | 874-916 | `["wpctl","status"]` (parses `Audio` section, `├─ Sinks:` / `├─ Sources:`, rows `│  *  48. Name [vol: ...]`) | 2 |
| `_wpctl_set_default` | 919-928 | `["wpctl","set-default",str(id)]` | 2 |

- Files: `settings.json` under `~/.config/erplibre-home/` (`LAYOUT_DIR`
  88, `SETTINGS_FILE` 90): read by `_init_font_scale` 987, read+written
  by `_set_font_scale` 1000-1002 and `_toggle_show_labels` 1008-1010
  (read-modify-write of the whole dict, `os.makedirs` + `json.dump(...,
  indent=2)`). Stub through `settings.py` (or `HOME`/tmpdir).
- `time.monotonic`: only through `_flag_err` 1763-1770 (bluetooth toggle
  with no adapter) and the kernel flash; none in the plugins.
- No gdbus, no translator call, no D-Bus in these three domains.
- stderr: error prints in every helper (`print(..., file=sys.stderr)`),
  and `_flag_err` prints `[erplibre-home] <reason>` (1767).
- `_render_idle` calls `_wpctl_get(WPCTL_SOURCE)` unconditionally at 3006,
  even when `mic_status_key == -1` (1-row deck): the characterization
  stub must answer it on every home render (see trap T6).
- Per render, wpctl calls: home 1 (`get-volume SOURCE`); sound page 4
  (`get-volume SINK`, `get-volume SOURCE`, `status` ×2). Bluetooth page:
  `show` (+ `Paired` + `Connected` when powered).

---

## 7. Draft plugin modules (79 cols)

Assumptions on the kernel/ui API (to be fixed by the plan writer):
`ctx.set_key(key, color, text="", icon=None)`, `ctx.geo.cols/rows/
total_keys`, `ui.render.Style` with `.scale`, `.show_labels`,
`.set_scale(x)` (clamps), `ui.render.render_too_small(ctx)` (trap T5),
`Page.keys(geo)` may return `None` (trap T2).

### `plugins/sound.py`

```python
"""Sound page, SOUND home button and the microphone indicator."""

import re
import subprocess
import sys

from erplibre_streamdeck.plugin import (
    PLUGIN_API, Fixture, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors as C
from erplibre_streamdeck.ui.render import render_too_small

VOL_STEP_PCT = 5
WPCTL_SINK = "@DEFAULT_AUDIO_SINK@"
WPCTL_SOURCE = "@DEFAULT_AUDIO_SOURCE@"
_WPCTL_DEV_RE = re.compile(r"^\s*│\s+(\*\s+)?(\d+)\.\s+(.+?)\s+\[vol:")

# _wpctl_get, _wpctl_volume_delta, _wpctl_mute_toggle,
# _wpctl_list_devices, _wpctl_set_default, _wpctl_cycle_default,
# _wpctl_default_short: moved verbatim from lines 822-953.


def _keys(geo):
    if geo.cols < 4 or geo.rows < 3:
        return None
    c = geo.cols
    return {
        "back": 0, "vol_down": c + 1, "vol_up": c + 2,
        "out_mute": c + 3, "mic_down": 2 * c + 1,
        "mic_up": 2 * c + 2, "mic_mute": 2 * c + 3,
        "sink": 1, "source": 2,
    }


def _render(ctx):
    sk = _keys(ctx.geo)
    if not sk:
        render_too_small(ctx)
        return
    out_vol, out_muted = _wpctl_get(WPCTL_SINK)
    mic_vol, mic_muted = _wpctl_get(WPCTL_SOURCE)
    labels = {...}  # lines 3349-3371, `_t` -> `ctx.t`, same order
    for key in range(ctx.geo.total_keys):
        color, label = labels.get(key, (C.COLOR_EMPTY, ""))
        ctx.set_key(key, color, label)


_ACTIONS = (
    ("vol_down", lambda: _wpctl_volume_delta(WPCTL_SINK, -VOL_STEP_PCT)),
    ("vol_up", lambda: _wpctl_volume_delta(WPCTL_SINK, VOL_STEP_PCT)),
    ("out_mute", lambda: _wpctl_mute_toggle(WPCTL_SINK)),
    ("mic_down",
     lambda: _wpctl_volume_delta(WPCTL_SOURCE, -VOL_STEP_PCT)),
    ("mic_up", lambda: _wpctl_volume_delta(WPCTL_SOURCE, VOL_STEP_PCT)),
    ("mic_mute", lambda: _wpctl_mute_toggle(WPCTL_SOURCE)),
    ("sink", lambda: _wpctl_cycle_default("Sinks")),
    ("source", lambda: _wpctl_cycle_default("Sources")),
)


def _handle(ctx, key):
    sk = _keys(ctx.geo)
    if not sk or key == sk["back"]:
        ctx.home()
        return
    for name, action in _ACTIONS:
        if key == sk.get(name):
            action()
            ctx.render()
            return


def _mic_place(geo, home_keys):
    return [(geo.rows - 1) * geo.cols] if geo.rows >= 2 else []


def _mic_face(ctx, key):
    vol, muted = _wpctl_get(WPCTL_SOURCE)
    if vol is None:
        return KeyFace(C.COLOR_BT_NA, ctx.t("MIC\nN/A"))
    if muted:
        return KeyFace(C.COLOR_MUTE_ON, ctx.t("MIC\nOFF"), "mic_off")
    return KeyFace(C.COLOR_MUTE_OFF, ctx.t("MIC\nON"), "mic_on")


def _mic_press(ctx, key):
    _wpctl_mute_toggle(WPCTL_SOURCE)
    ctx.render()


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("sound", _keys, _render, _handle)],
    home_buttons=[HomeButton(
        40,
        lambda ctx: KeyFace(
            C.COLOR_SOUND_TITLE, ctx.t("SOUND"), "sound"),
        lambda ctx: ctx.goto("sound"),
    )],
    fixtures=[Fixture(_mic_place, _mic_face, _mic_press)],
    home_tick=lambda ctx, now: None,  # trap T3: 2 s mic repaint
    home_period=2.0,
)
```

### `plugins/a11y.py`

```python
"""Accessibility page: font scale and labels on icon keys."""

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors as C
from erplibre_streamdeck.ui.render import (
    FONT_SCALE_DEFAULT, FONT_SCALE_STEP, render_too_small,
)


def _keys(geo):
    if geo.cols < 4 or geo.rows < 2:
        return None
    c = geo.cols
    keys = {"back": 0, "font_down": c + 1, "font_up": c + 2,
            "font_reset": c + 3}
    if c >= 5:
        keys["labels_toggle"] = c + 4
    return keys


def _set_scale(ctx, scale):
    ctx.style.set_scale(scale)  # clamps to [MIN, MAX], not rounded
    data = ctx.settings.load()
    data["font_scale"] = round(ctx.style.scale, 2)
    ctx.settings.save(data)


def _toggle_labels(ctx):
    ctx.style.show_labels = not ctx.style.show_labels
    data = ctx.settings.load()
    data["show_labels"] = ctx.style.show_labels
    ctx.settings.save(data)


def _render(ctx):
    ak = _keys(ctx.geo)
    if not ak:
        render_too_small(ctx)
        return
    st = ctx.style
    on = st.show_labels
    assignments = {  # insertion order is load-bearing: trap T4
        ak["back"]: (C.COLOR_BACK, ctx.t("BACK")),
        ak["font_down"]: (C.COLOR_FONT_STEP, "FONT\n-"),
        ak["font_up"]: (C.COLOR_FONT_STEP, "FONT\n+"),
        ak["font_reset"]: (C.COLOR_FONT_RESET, ctx.t("RESET")),
        ctx.geo.total_keys // 2:
            (C.COLOR_EMPTY, f"SCALE\n{st.scale:.1f}x"),
    }
    if "labels_toggle" in ak:
        color = C.COLOR_MUTE_OFF if on else C.COLOR_BT_OFF
        assignments[ak["labels_toggle"]] = (
            color, f"LABELS\n{'ON' if on else 'OFF'}")
    for key in range(ctx.geo.total_keys):
        color, label = assignments.get(key, (C.COLOR_EMPTY, ""))
        ctx.set_key(key, color, label)


def _handle(ctx, key):
    ak = _keys(ctx.geo)
    if not ak or key == ak["back"]:
        ctx.home()
        return
    if key == ak["font_down"]:
        _set_scale(ctx, ctx.style.scale - FONT_SCALE_STEP)
    elif key == ak["font_up"]:
        _set_scale(ctx, ctx.style.scale + FONT_SCALE_STEP)
    elif key == ak["font_reset"]:
        _set_scale(ctx, FONT_SCALE_DEFAULT)
    elif key == ak.get("labels_toggle"):
        _toggle_labels(ctx)
    else:
        return
    ctx.render()


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("a11y", _keys, _render, _handle)],
    home_buttons=[HomeButton(
        60,
        lambda ctx: KeyFace(C.COLOR_A11Y_TITLE, "A11Y", "a11y"),
        lambda ctx: ctx.goto("a11y"),
    )],
)
```

### `plugins/bluetooth.py`

```python
"""Bluetooth page: adapter power and paired devices."""

import shutil
import subprocess
import sys

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors as C
from erplibre_streamdeck.ui.render import render_too_small

# _bt_powered, _bt_list_paired, _bt_connect, _bt_disconnect,
# _bt_set_power: moved verbatim from lines 703-815.


def _keys(geo):
    if geo.cols < 2 or geo.rows < 2:
        return None
    c = geo.cols
    return {"back": 0, "toggle": c + 1,
            "devices": list(range(c + 2, 2 * c))}


def _render(ctx):
    bk = _keys(ctx.geo)
    if not bk:
        render_too_small(ctx)
        return
    powered = _bt_powered()
    ...  # lines 3273-3300, `_t` -> `ctx.t`


def _handle(ctx, key):
    bk = _keys(ctx.geo)
    if not bk or key == bk["back"]:
        ctx.home()
        return
    if key == bk["toggle"]:
        current = _bt_powered()
        if current is None:
            ctx.flash(False, "bluetooth: bluetoothctl unavailable "
                             "or no adapter")
            ctx.render()
            return
        _bt_set_power(not current)
        ctx.render()
        return
    if key in bk["devices"]:
        idx = bk["devices"].index(key)
        devices = _bt_list_paired()
        if idx < len(devices):
            mac, _name, connected = devices[idx]
            (_bt_disconnect if connected else _bt_connect)(mac)
            ctx.render()


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("bluetooth", _keys, _render, _handle)],
    home_buttons=[HomeButton(
        70,
        lambda ctx: KeyFace(C.COLOR_BT_TITLE, "BT", "bt"),
        lambda ctx: ctx.goto("bluetooth"),
    )],
)
```

---

## 8. Traps and proposals

**T1. Font scale restore must not depend on `a11y` being on.** Today
`_init_font_scale()` runs in `main` (3561) for every start. If the
restore moves into `a11y.setup`, turning `a11y` off (DECK_PLUGINS_OFF)
silently resets every key's font to 1.0 and hides labels. Proposal:
`ui/render.py` owns `Style` + `FONT_SCALE_*` and a
`Style.restore(data)` that is lines 987-993 verbatim; `app.main()` calls
it with `settings.load()` before building the kernel. `a11y` only
mutates `ctx.style` and persists. In-memory scale must stay unrounded
(only the stored copy is `round(x, 2)`, 1001) so `int(round(base_fs *
scale))` (1497) gives the same pixel size after repeated ±0.1 steps.
Question for the user/plan: confirm "a11y off = last chosen style stays
applied, frozen".

**T2. `Page.keys` returns `None` for small decks.** All three return
`None` today (1906, 1921, 1953) and render/handle test `if not keys`.
The spec types `keys` as `-> dict`. Either allow `None` in the kernel
contract (the kernel never interprets it) or return `{}` (same
falsiness). The spec's Context has no member exposing the current
page's keys, so the draft has render/handle call `_keys(ctx.geo)`
directly; the plan should state whether the kernel caches `keys` or
whether `Page.keys` exists only for tests/introspection.

**T3. The mic indicator repaint rides on someone else's tick.** The only
thing that repaints the mic every 2 s on the home screen is the idle
branch of `loop` (3516-3531), which today runs `_refresh_timers` +
`_refresh_todo_terminals` + `render`. In B2 those become home ticks of
`timers` and `todo_terminals`. With both turned off, nothing re-renders
home and an external mute no longer shows. Proposal: `sound` declares
`home_tick` as a no-op with `home_period=2.0`; the kernel "renders once
if any ran", so with all plugins on the cadence is still one render per
2 s. The kernel should give each plugin its own last-run timestamp
starting at 0, so the first loop iteration fires all of them together,
as today's `last_idle_refresh = 0` (3470) does.

**T4. a11y scale label overwrites FONT+ on some decks.** The scale cell
is `total_keys // 2` (3322), inserted into the dict after `font_up`. On
5×3 (and 4×3) `total_keys // 2 == cols + 2 == font_up` (15//2 = 7), so
key 7 shows `SCALE\n1.0x` on `COLOR_EMPTY` but a press still does
font-up. On 4×2 it is key 4 and on 8×4 key 16 (no clash). Keep the dict
insertion order exactly (back, down, up, reset, scale, then labels) so
the screen is identical; flag it as a known oddity for a later fix, not
in B2.

**T5. The "DECK TOO SMALL" block is copied six times** (todo 2796-2805,
layout 3115-3123, translator 3199-3207, bt 3263-3271, a11y 3304-3312,
sound 3336-3344): back on 0, `COLOR_ERR t("DECK\nTOO\nSMALL")` on
`total_keys // 2`, empty elsewhere. Proposal: one
`ui.render.render_too_small(ctx)` used by every plugin. In all three
pages the matching handler sends any key home, not only key 0
(2558-2561, 2589-2592, 2611-2615).

**T6. Mic `wpctl` call count on 1-row decks.** `_render_idle` calls
`_wpctl_get(WPCTL_SOURCE)` at 3006 before the key loop, even when
`mic_status_key == -1`. In the package the fixture face is called only
for placed keys, so a 1-row deck makes one subprocess call fewer per
home render. Invisible on the deck; characterization fixtures must not
assert the wpctl call count on the home screen (or assert it only for
rows >= 2).

**T7. Fixture placement and press priority.** `mic_status_key =
(rows-1)*cols` never collides with a HomeButton (overflow uses row 1
only when `rows >= 3`, the mic is on the last row) nor with layout
shortcuts (they start under LAYOUT, col >= 4), and `key 0` (NO EXT) is
never the mic. So the idle press order (mic at 2157 before shortcuts and
dashboard) needs no reproduction. `_mic_place` may still return `[]`
when its key is in `home_keys`, defensively. The mic fixture exists
even when the SOUND button or page does not (3×2, 4×2), as today. The
spec orders fixtures "sound then layouts"; the plan must say where that
order comes from (loader order of files would put `layouts` before
`sound` alphabetically - harmless here since they never collide, but
`home.py` needs a defined rule).

**T8. Bluetooth device keys are live when blank.** When the adapter is
off or unknown, device keys render empty (3285), but a press still runs
`bluetoothctl devices Paired/Connected` and connect/disconnect on the
listed device (2577-2585). Keep as is (no screen change); note for B3.
`_bt_set_power`'s result is ignored (2573): no flash on failure, keep.

**T9. Blocking calls under the lock.** `bluetoothctl connect` (timeout
10 s), the bt page render (up to 3 × 2 s) and the sound page render
(4 × 2 s) run inside `handle`/`render` under the kernel lock, as today.
B3 scope; do not change in B2.

**T10. Journal text of the bt flash.** `_flag_err` prints
`[erplibre-home] bluetooth: bluetoothctl unavailable or no adapter`
(1767). If `ctx.flash` routes `reason` through `ctx.log` with a
plugin-id prefix, the journal line changes (not the screen). Decide in
the kernel task whether the prefix is `[erplibre-home]` or
`[erplibre-home] bluetooth:`; avoid doubling "bluetooth:".

**T11. Shared colours.** `COLOR_VOL`, `COLOR_MUTE_OFF`, `COLOR_BT_OFF`,
`COLOR_BT_NA` are read by other pages (todo, claude, translator, a11y,
mic). They must live in `ui/colors.py`, never be redefined inside a
plugin. Same for the `mic_on`/`mic_off` icons used by the translator
page (3217): they stay in `ui/icons.py`.

**T12. Settings writers race.** a11y and translator both read-modify-write
the whole `settings.json` (1000-1002, 1008-1010, 2383-2416). Through one
`settings.py` this stays non-atomic (B3), but both must use
`ctx.settings.load()` immediately before `save()` as today, never a
cached dict, or one plugin erases the other's keys.

**Dead code (step 0):** `_wpctl_available` 818-819 (no caller).

**Tests to add (backend parsers, spec "Backends"):** `_wpctl_get`
output `Volume: 0.50 [MUTED]` / malformed; `_wpctl_list_devices` on a
sample `wpctl status` with Sinks/Sources and default marker;
`_wpctl_default_short`; `_bt_powered` via bluetoothctl and via rfkill
fallback; `_bt_list_paired` merge of Paired and Connected;
`Style.restore` with bad/missing/out-of-range `font_scale`.
