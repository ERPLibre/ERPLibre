# B2 map — KERNEL, `ui/`, `dbus.py`, `settings.py`, `paths.py`, `home.py`

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD
`b61156bf`). Every range below was read with `grep -n` / `awk NR` / `ast`
(`lineno`..`end_lineno`), inclusive.

---

## 1. Module-level names owned by the domain

### 1a. Imports (lines 19-44)

| Line(s) | Name | Fate |
|---|---|---|
| 19 | `import csv` | timers plugin (`_export_timers_csv` 1143) |
| 20 | `json` | settings.py, dbus users, plugins |
| 21 | `os` | everywhere |
| 22 | `re` | dbus users (`ApplyLayout` regex 1052), sound (869), todo (313-314) |
| 23 | `shlex` | todo_terminals (1676-1677) |
| 24 | `shutil` | todo_terminals, sound, timers (`zenity`) |
| 25 | `subprocess` | dbus.py + plugins |
| 26 | `sys` | everywhere |
| 27 | `tempfile` | translate (2490) |
| 28 | `threading` | kernel (`Lock` 1524), app (`Thread` 3593), translate |
| 29 | `time` | kernel + plugins |
| **30-31** | `urllib.error`, `urllib.request` | **DEAD** (no other `urllib` in file) |
| 32 | `datetime` | layouts (1065) |
| 34-41 | `PIL`/`StreamDeck` try-import, prints the pip hint and re-raises | `ui/render.py` (PIL, PILHelper, TransportError) and `app.py` (DeviceManager) |
| 43 | `deck_lock` | `__main__.py` (acquire/sigterm), `app.py` (`NO_DECK_EXIT`) |
| 44 | `translator as _translator` | translate plugin only |

### 1b. Constants

| Lines | Name(s) | Target |
|---|---|---|
| 46-84 | 39 `COLOR_*` (page + home colors) | `ui/colors.py` (all of them: they are shared across domains, e.g. `COLOR_TIMER_TITLE` 3050 timers + 3072 todo, `COLOR_BT_NA` 3108 mic + 3274 bt, `COLOR_MUTE_OFF` 3111 mic + 3325 a11y, `COLOR_VOL` 2982 claude, `COLOR_LAYOUT_TITLE` 2989 claude, `COLOR_CANCEL` 2992 claude, `COLOR_LOAD_FILLED` 3078 home) |
| 86 | `VOL_STEP_PCT` | sound plugin |
| 88 | `LAYOUT_DIR = expanduser("~/.config/erplibre-home")` | `paths.py` as `CONFIG_DIR` |
| 89 | `LAYOUT_FILE` | `paths.py` (`LAYOUTS_FILE`), used by layouts plugin |
| 90 | `SETTINGS_FILE` | `paths.py`, used only by `settings.py` |
| 91 | `NUM_LAYOUT_SLOTS = 3` | layouts plugin (also read by its fixture `place`) |
| 93-96 | `FONT_SCALE_MIN/MAX/STEP/DEFAULT` | `ui/render.py` (`Style`) — a11y reads STEP/DEFAULT |
| 98 | `_font_scale = FONT_SCALE_DEFAULT` (global) | `Style.font_scale` |
| 99 | `_show_labels = False` (global) | `Style.show_labels` |
| **101** | `GALLERY_RESTART_URL` | **DEAD** |
| **102** | `COLOR_ACTIVE` | **DEAD** |
| 103-104 | `COLOR_OK`, `COLOR_ERR` | `ui/colors.py` (kernel flash, many pages) |
| 105-110 | `RESULT_FLASH_SEC = 0.5` (+comment 105-109) | `kernel.py` |
| 112-116 | `TILING_IDLE_TIMEOUT_SEC = 5.0` | tiling plugin |
| 118-123 | `_DECK_LANG = os.environ.get('LANG','en').lower()[:2]` (read at import) | `ui/i18n.py` |
| 124-178 | `_DECK_LABELS` | `ui/i18n.py` |
| 181-184 | `_t(label)` | `ui/i18n.py` (`t`), exposed as `ctx.t` |
| 186-190 | `COLOR_CLAUDE_*` | `ui/colors.py` (tests `ClaudeColorTest` read them) |
| 192-195 | `CLAUDE_STATE_DIR` (XDG_STATE_HOME or ~/.local/state + erplibre-home/claude) | `paths.py` `STATE_DIR` + claude plugin |
| 196-199 | `MPV_STATE_DIR` | `paths.py` + mpv plugin |
| 200-203 | `TODO_TERMINALS_PATH` | `paths.py` + todo plugin |
| 204-205 | `COLOR_MPV_ACTIVE`, `COLOR_TODO_TERMINAL` | `ui/colors.py` |
| 528-541 | `MODE_*` strings | page ids; `MODE_IDLE = "idle"` → `kernel.HOME` |
| 543-544 | `WPCTL_SINK/SOURCE` | sound plugin |
| 546-548 | `DBUS_DEST/PATH/IFACE` | `dbus.py` |
| 549-551 | `DBUS_RECHECK_SEC = 5.0` | `kernel.py` |
| 1163-1164 | `_ICON_WHITE`, `_ICON_RED` | `ui/icons.py` |
| 1396-1408 | `_ICONS` dict (mic_on, mic_off, tile, timer, dev_reload, sound, layout, a11y, bt, translator, robot) | `ui/icons.py` `ICONS` |
| 1448-1462 | `_FONT_CANDIDATES` (+comment 1448-1452) | `ui/render.py` |
| 1463-1467 | `_FONT_PATH` + import-time `for` probing `os.path.isfile` | `ui/render.py` (make it lazy: `_font_path()` cached) |

### 1c. Functions

| Lines | Function | Target |
|---|---|---|
| 464-487 | `_chunk_text_for_cells` | `ui/text.py` `chunk_text_for_cells` |
| 490-499 | `_wrap_chunk` | `ui/text.py` `wrap_chunk` |
| 502-526 | `_wrap_button_label` | `ui/text.py` `wrap_button_label` |
| 554-574 | `_tile_via_dbus` | tiling plugin over `ctx.dbus.call` |
| 577-590 | `_check_dbus_available` | `dbus.py` `available()` |
| 593-608 | `_parse_gdbus_string_tuple` | `dbus.py` `parse_string_tuple()` |
| **818-819** | `_wpctl_available` | **DEAD** |
| 956-967 | `_layouts_load/_layouts_save` | layouts plugin (own file, not settings.json) |
| 970-975 | `_settings_load` | `settings.py` `load()` |
| 978-981 | `_settings_save` | `settings.py` `save(data)` |
| 984-993 | `_init_font_scale` (globals) | `Style.load(settings)` in `ui/render.py` |
| 996-1002 | `_set_font_scale` | `Style.set_font_scale(scale, settings)` |
| 1005-1010 | `_toggle_show_labels` | `Style.toggle_labels(settings)` |
| 1167-1393 | `_icon_mic` 1167-1185, `_icon_mic_off` 1188-1189, `_icon_tile` 1192-1199, `_icon_timer` 1202-1215, `_icon_dev_reload` 1218-1237 (local `import math` 1226), `_icon_sound` 1240-1266, `_icon_layout` 1269-1285, `_icon_a11y` 1288-1315, `_icon_translator` 1318-1338, `_icon_bt` 1341-1354, `_icon_robot` 1357-1393 | `ui/icons.py` (all; keyed by name, plugins pass `icon="..."`) |
| 1411-1445 | `_draw_layout_preview` | layouts plugin (calls `ui.render.load_label_font(14)` at 1444) |
| 1470-1480 | `_load_label_font(fs)` | `ui/render.py` `load_label_font` |
| 1483-1514 | `set_key(deck, key, color, text, icon, extra_draw)` | `ui/render.py`; reads `_ICONS` (1488-1489), `_show_labels` (1495), `_font_scale` (1497) **at call time** |
| 3546-3555 | `_label_for_timer` | timers plugin (not kernel) |
| 3558-3614 | `main()` | split: `__main__.py` (3559-3560), `app.py` (3561-3614) |
| 3617-3618 | `__main__` guard | `__main__.py` (+ `--list-plugins`) |

`__file__`-derived paths (→ `paths.py`):
- 1650-1651 `root = abspath(join(dirname(abspath(__file__)), "..", ".."))` → `paths.REPO_ROOT` (todo_terminals; 1652 venv, 1653 todo.py).
- 2466-2469 `join(dirname(abspath(__file__)), "translator_stream.py")` → `paths.STREAM_DECK_DIR / "translator_stream.py"` (translate).
- XDG state dir is recomputed a 4th time inline at 1669-1672 (todo log dir) → `paths.STATE_DIR / "todo"`.

---

## 2. Tiler methods owned by the kernel

| Lines | Method | Reads | Writes | Calls into other domains |
|---|---|---|---|---|
| 1518-1595 | `__init__` | `deck.key_layout()` 1520 | see §3 | `_load_todo_terminals` 1543, `_check_dbus_available` 1545, translator detection 1559-1593, `_settings_load` 1575, `_compute_idle_buttons` 1595 |
| 1597-1641 | `_compute_idle_buttons` | cols, rows | `tile_key timer_key dev_reload_key sound_key layout_key a11y_key bluetooth_key translator_key todo_key` (setattr 1606-1617), `layout_shortcut_keys` 1620-1627, `mic_status_key` 1630-1632 | every page key compute 1634-1641: sound 1949-1967, layout 1933-1947, a11y 1918-1931, bluetooth 1902-1916, translator 1882-1900, `_compute_claude_buttons` 1864-1880, claude_session 1834-1848, mpv_session 1850-1862 |
| 1763-1770 | `_flag_err(reason)` | — | `last_result="err"`, `result_time` | prints `[erplibre-home] {reason}` to stderr |
| 1864-1880 | `_compute_claude_buttons` (dashboard pool) | the 9 `*_key`, `mic_status_key`, `layout_shortcut_keys`, cols, total_keys | `claude_keys` = `range(cols, total)` minus used | — |
| 1971-2012 | `handle_key(key, state)` | `last_result`, `result_time`, mode | `last_press_key` 1983 | dispatch 1985-2012 |
| 2127-2223 | `_handle_idle_key` | all home keys, `claude_keys`, `timers`, `_dashboard_hidden_timer_ids`, `todo_terminals` | mode, sids, flash, corners, `_tiling_last_touch` | `_hot_reload_extension` 2129, `_launch_todo_terminal` 2155, `_wpctl_mute_toggle` 2158, `_layouts_load` 2163, `_load_layout_slot` 2166, `_load_mpv_sessions` 2180, `_load_claude_sessions` 2187, `_enter_timer_mode` 2203/2215 |
| 2692-2703 | `render` | `last_result`, `result_time` | clears `last_result` 2702 when expired | `_render_mode`, `_overlay_flash` |
| 2705-2733 | `_render_mode` | mode | — | 14 `_render_*` |
| 2735-2751 | `_overlay_flash` | `last_press_key`, `last_result`, total_keys | — | `set_key` with `"OK!"`/`"ERR"` literals (no `_t`) |
| 2753-2764 | `_key_neighbors` | cols, rows | — | — |
| 2999-3099 | `_render_idle` | home keys, `layout_shortcut_keys`, `claude_keys`, `timers`, `todo_terminals`, `dbus_ok` | `_dashboard_hidden_timer_ids &= running_ids` 3014 (side effect) | `_layouts_load` 3002, `_mic_indicator` 3006, `_load_mpv_sessions` 3008, `_load_claude_sessions` 3009, `_wrap_chunk` 3083, `_claude_color`/`_claude_label` 3086-3087, `_label_for_timer` 3091 |
| 3455-3465 | `_recheck_dbus(now)` | `dbus_ok`, `_dbus_checked_at` | both | `_check_dbus_available` 3464 |
| 3467-3543 | `loop` | everything | mode, sids, flash | see §4 loop table |

Not kernel but bound to the home screen: `_mic_indicator` 3101-3111 (sound fixture face), `_launch_todo_terminal` 1643-1709, `_capture_pending_todo_terminal` 1711-1740, `_refresh_todo_terminals` 1742-1761 (todo), `_enter_timer_mode` 2660-2663, `_refresh_timers` 2678-2688 (timers).

---

## 3. State: what stays in the kernel, what moves to `ctx.state(<id>)`

`Tiler.__init__` 1518-1595:

| Line | Attribute = initial | Destination |
|---|---|---|
| 1519 | `deck = deck` | `Kernel.deck` |
| 1520-1523 | `rows, cols = deck.key_layout()`; `cols`, `rows`, `total_keys = cols*rows` | `Kernel.geo = Geometry(cols, rows, total_keys)` (note: `key_layout()` returns `(rows, cols)`) |
| 1524 | `lock = threading.Lock()` | `Kernel.lock` |
| 1525 | `running = True` | `Kernel.running` (app sets False, 3602) |
| 1527-1528 | `grid_cols = cols`, `grid_rows = rows` | **drop**: tiling uses `ctx.geo.cols/rows` (2241, 2248) |
| 1530 | `mode = MODE_IDLE` | `Kernel.page_id = "idle"` |
| 1531-1532 | `corner1 = None`, `corner2 = None` | `state("tiling")` |
| 1533 | `last_result = None` | `Kernel.flash_result` |
| 1534 | `result_time = 0` | `Kernel.flash_time` |
| 1535 | `last_press_key = None` | `Kernel.last_press_key` (never reset) |
| 1536 | `_claude_session_sid = None` | `state("claude_sessions").sid` |
| 1537 | `_mpv_session_pid = None` | `state("mpv_sessions").pid` |
| 1538 | `_todo_session_window_id = None` | `state("todo_terminals").window_id` |
| 1541 | `_pending_todo_capture_at = 0.0` | `state("todo_terminals")` |
| 1542 | `_pending_todo_log_path = ''` | `state("todo_terminals")` |
| 1543 | `todo_terminals = _load_todo_terminals()` | `state("todo_terminals").terms`, filled by its `setup` |
| 1544 | `_tiling_last_touch = 0.0` | `state("tiling")` |
| 1545 | `dbus_ok = _check_dbus_available()` | `Kernel.dbus_ok` (exposed `ctx.dbus.available`) |
| 1546 | `_dbus_checked_at = time.monotonic()` | `Kernel` |
| 1548 | `timers = []` | `state("timers")` |
| 1550 | `timer_key_map = {}` | `state("timers")` |
| 1555 | `_dashboard_hidden_timer_ids = set()` | `state("timers")` |
| 1557 | `layout_delete_pending = None` | `state("layouts")` |
| 1559-1573 | `_stt_backends`, `_stt_index=0`, `_output_methods`, `_output_index=0`, `_llm_backends`, `_llm_index=0`, `_llm_mode_index=0`, `_record_proc=None`, `_record_path=None`, `_record_started_at=0.0`, `_vad_should_stop=False`, `_streaming_proc=None` | `state("translate")`, built by its `setup` |
| 1574-1593 | restore from `_settings_load()` (translator_stt/output/llm/llm_mode) | translate `setup` via `ctx.settings.load()` |
| 1595 | `_compute_idle_buttons()` → `*_key`, `layout_shortcut_keys`, `mic_status_key`, `claude_keys`, `sound_keys`, `layout_keys`, `a11y_keys`, `bluetooth_keys`, `translator_keys`, `claude_session_keys`, `mpv_session_keys` | `home.allocate(geo, plugins)` + `Kernel.page_keys[page_id] = page.keys(geo)` computed once |

Module globals `_font_scale` (98), `_show_labels` (99) → `Style` instance owned by
the kernel, loaded before the first render (today `_init_font_scale()` 3561
runs before the device is even enumerated).

---

## 4. Pages and the loop

Kernel page: `"idle"` (home) — keys from `home.allocate`, render
`_render_idle` 2999-3099, handle `_handle_idle_key` 2127-2223, ticks =
home ticks.

Dispatch table (for the other domains; `handle_key` 1985-2012,
`_render_mode` 2705-2733):

| Page id | handle (call line → def) | render (call line → def) | keys | Loop branch → becomes |
|---|---|---|---|---|
| idle | 1986 → 2127-2223 | 2707 → 2999-3099 | home.py | 3516-3531 → home ticks + kernel 2 s refresh |
| tiling | 1988 → 2225-2254 | 2709 → 3380-3393 | geo only | 3483-3494 → `tiling` page tick, period 0 (guarded by `_tiling_last_touch > 0` and ≥ `TILING_IDLE_TIMEOUT_SEC`) |
| timer_list | 1990 → 2256-2302 | 2711 → 3395-3435 | `timer_key_map` via `_refresh_timers` 2678-2688 | 3495-3500 → `timers` page tick, period 2.0 (`_refresh_timers()` + render) |
| timer_reset_confirm | 1992 → 2640-2657 | 2713 → 3437-3453 | geo | — |
| sound | 1994 → 2609-2638 | 2715 → 3334-3378 | 1949-1967 | — |
| layout | 1996 → 2304-2341 | 2717 → 3113-3161 | 1933-1947 | — |
| layout_delete_confirm | 1998 → 2343-2362 | 2719 → 3163-3178 | geo | — |
| a11y | 2000 → 2587-2607 | 2721 → 3302-3332 | 1918-1931 | — |
| bluetooth | 2002 → 2556-2585 | 2723 → 3261-3300 | 1902-1916 | — |
| translator | 2004 → 2365-2425 | 2725 → 3197-3259 | 1882-1900 | 3532-3542 → `translate` page tick, period 0 (guard: `_record_proc` and `_record_started_at > 0`; VAD flag or `recording_timeout_seconds()` → `_toggle_record`) |
| translator_history | 2006 → 2427-2446 | 2727 → 3180-3195 | geo | — |
| claude_session | 2008 → 2083-2125 | 2729 → 2950-2997 | 1834-1848 | — |
| mpv_session | 2010 → 2014-2051 | 2731 → 2916-2948 | 1850-1862 | — |
| todo_session | 2012 → 2846-2914 | 2733 → 2794-2844 | 2766-2776 (computed per call) | 3501-3515 → `todo_terminals` page tick, period 1.0 (`_refresh_todo_terminals`, go home if window gone, render) |

Loop skeleton (3467-3543): `last_timer_refresh = 0` 3469, `last_idle_refresh = 0`
3470; `while running and deck.is_open()` 3471; `now = monotonic()` 3472;
D-Bus recheck **outside** the lock 3475-3477 (render under lock if it just
appeared); then under the lock 3478: `if last_result:` 3479-3482 (render only
when expired, **no tick in either case**) `elif` tiling 3483 / timer_list 3495
/ todo_session 3501 / idle 3516 (pending capture 3522-3526 every pass, refresh
3527-3531 every 2 s) / translator 3532; `sleep(0.3)` 3543.

---

## 5. Home contributions (from `_compute_idle_buttons` 1597-1641, `_render_idle` 2999-3099, `_handle_idle_key` 2127-2223)

Allocation (1602-1617): fixed order list 1602-1605
`tile, timer, dev_reload, sound, layout, a11y, bluetooth, translator, todo`;
index `i < cols` → key `i` else -1 (1606-1607); if `rows >= 3` the -1 ones take
`cols .. 2*cols-1` in order (1608-1617).

### HomeButtons (order, face, press)

| Order | Plugin | Face (render line) | Press (handler line) |
|---|---|---|---|
| 10 | tiling | 3046-3048 `COLOR_TITLE, _t("TILE"), icon="tile"` | 2217-2223: mode tiling, corners None, `last_result=None`, `_tiling_last_touch=now`, render |
| 20 | timers | 3049-3051 `COLOR_TIMER_TITLE, _t("TIMER"), icon="timer"` (guard `timer_key != tile_key`) | 2214-2216 `_enter_timer_mode()` (= goto timer_list after `_refresh_timers`) |
| 30 | dev_reload | 3052-3054 `COLOR_DEV_RELOAD, "DEV\nRELOAD", icon="dev_reload"` (no `_t`) | 2128-2133 `_hot_reload_extension()`; flash ok/err **without** journal reason; render |
| 40 | sound | 3055-3057 `COLOR_SOUND_TITLE, _t("SOUND"), icon="sound"` | 2134-2137 goto sound |
| 50 | layouts | 3058-3060 `COLOR_LAYOUT_TITLE, _t("LAYOUT"), icon="layout"` | 2138-2141 goto layout |
| 60 | a11y | 3061-3063 `COLOR_A11Y_TITLE, "A11Y", icon="a11y"` (no `_t`) | 2142-2145 goto a11y |
| 70 | bluetooth | 3064-3065 `COLOR_BT_TITLE, "BT", icon="bt"` (no `_t`) | 2146-2149 goto bluetooth |
| 80 | translate | 3066-3070 `COLOR_TR_TITLE, _t("TRANSL"), icon="translator"` | 2150-2153 goto translator |
| 90 | todo_terminals | 3071-3072 `COLOR_TIMER_TITLE, _t("TODO")`, no icon | 2154-2156 `_launch_todo_terminal()` (renders itself, flashes ok or `_flag_err`) |

### Fixtures

| Plugin | place | face | press |
|---|---|---|---|
| sound (mic) | 1629-1632: `(rows-1)*cols` if `rows >= 2` else none | 3073-3075 via `_mic_indicator` 3101-3111 (`_wpctl_get(WPCTL_SOURCE)` → N/A `COLOR_BT_NA, _t("MIC\nN/A"), None` / muted `COLOR_MUTE_ON, _t("MIC\nOFF"), "mic_off"` / `COLOR_MUTE_OFF, _t("MIC\nON"), "mic_on"`) | 2157-2160 `_wpctl_mute_toggle(WPCTL_SOURCE)`; render; no flash |
| layouts (shortcuts) | 1618-1627: if `layout_key >= 0 and rows >= 2 and layout_key + NUM_LAYOUT_SLOTS <= cols` → `(rows-1)*cols + layout_key + i`, i in 0..2 (needs the LAYOUT home key) | 3000-3005 + 3076-3078: filled slot (from `_layouts_load()["slots"]`) → `COLOR_LOAD_FILLED, f"*\n{slot}"`; empty slot → falls to `COLOR_EMPTY, ""` (face → None) | 2161-2173: empty slot → return (no render, no flash); `_load_layout_slot(slot)` ok → flash ok; else `_flag_err(f"layout shortcut load slot {slot} failed")`; render |

### Dashboard pool and TileProviders

Pool (`_compute_claude_buttons` 1864-1880): every key in `range(cols,
total_keys)` not in {the 9 home keys, mic key} ∪ `layout_shortcut_keys`
(including empty-slot shortcut keys). Fill order at render 3020-3044:
mpv, claude, timers, todo, each until the pool is exhausted.

| Order | Plugin | items | face | press (today by recomputed offset) |
|---|---|---|---|---|
| 10 | mpv_sessions | `_load_mpv_sessions()` 3008 | 3079-3083 `COLOR_MPV_ACTIVE, _wrap_chunk((title or url or 'mpv')[:18])` | 2174-2185 (pool index 2174-2179), 2180-2185: pid → goto mpv_session |
| 20 | claude_sessions | `_load_claude_sessions()` 3009 | 3084-3087 `_claude_color(s), _claude_label(s), icon="robot"` | 2186-2194: sid; empty sid → nothing at all (no render) |
| 30 | timers | 3010-3019: purge `hidden &= running_ids` (3013-3014, side effect), then running not hidden | 3088-3091 `COLOR_TIMER_RUNNING, _label_for_timer(t), icon="timer"` | 2195-2204 (same running-not-hidden filter, no purge) → `_enter_timer_mode()` |
| 40 | todo_terminals | `self.todo_terminals` 3040 | 3092-3095 `COLOR_TODO_TERMINAL, name or "TODO"` | 2205-2213: wid → goto todo_session; empty wid → nothing |

After all: 3096-3097 `key == 0 and not dbus_ok` → `COLOR_ERR, _t("NO\nEXT")`;
3098-3099 `COLOR_EMPTY, ""`.

Render precedence 3046-3099 = tap precedence 2128-2223 except: the tap
checks TIMER (2214) and TILE (2217) **last**, after fixtures/dashboard;
irrelevant since keys are disjoint.

---

## 6. External side effects (kernel tests must stub)

| Effect | Lines | Notes |
|---|---|---|
| `subprocess.run(["gdbus","introspect","--session","--dest",DBUS_DEST,"--object-path",DBUS_PATH], capture_output=True, text=True, timeout=3)` | 580-588 | ok = `"TileWindow" in stdout`; any exception → False. Called at 1545, 3464, 3574 (twice at start today) |
| `time.monotonic()` | 1546, 1702, 1770, 1976, 2697, 3472 (+ every plugin flash site) | inject a clock in `Kernel` |
| `time.sleep(0.3)` | 3543; `time.sleep(0.5)` 3598 | |
| `threading.Lock` / `Thread(target=loop, daemon=True)` | 1524 / 3593-3594 | |
| `os.environ['LANG']` at import | 123 | i18n; tests set it before import or make lang lazy |
| `os.path.isfile` font probe at import | 1464-1467 | |
| `ImageFont.truetype`/`load_default(size=)` (TypeError fallback) | 1470-1480 | |
| `Image.new`, `ImageDraw.Draw`, `draw.textbbox`, `draw.text` | 1486-1510 | |
| `PILHelper.to_native_key_format(deck, img)`; `with deck: deck.set_key_image(key, native)`; `TransportError` swallowed | 1511-1514 | fake deck needs `__enter__/__exit__` |
| `deck.key_format`: `deck.key_image_format()["size"]` | 1484-1485 | |
| `deck.key_layout()` → `(rows, cols)` | 1520, 3571 | |
| `deck.is_open()` | 3471, 3597 | |
| `DeviceManager().enumerate()`, `d.is_visual()` | 3562-3563 | |
| `deck.open/reset/set_brightness(80)/deck_type()/set_key_callback/reset/close` | 3567-3569, 3572, 3591, 3612-3614 | |
| `deck_lock.acquire_or_exit("tiler")`, `exit_on_sigterm()`, `NO_DECK_EXIT` | 3559, 3560, 3566 | test_deck_lock pins `main.body[0..1]` and the 2-line no-deck block |
| settings.json read | 970-975 via 987 (`font_scale`, `show_labels`) and 1575 (translator prefs) | |
| settings.json write | 978-981 via 1001-1002, 1008-1010 (+ translator writes in its handlers) | `os.makedirs(LAYOUT_DIR, exist_ok=True)` first |
| layouts.json read on every home render / shortcut tap | 3002, 2163 | |
| Claude / mpv state dirs read on every home render and every dashboard tap | 3008-3009, 2180, 2187 | `/proc/<pid>` existence check inside `_load_claude_sessions` |
| `wpctl get-volume @DEFAULT_AUDIO_SOURCE@` on every home render (mic) | 3106 → `_wpctl_get` 822-841 | |
| translator detection at construction | 1559-1566 (`detect_stt_backends`, `detect_output_methods`, `OUTPUT_CLIP`, `detect_llm_backends`), 1590 (`LLM_MODES`) | stub module `translator` |
| `_translator.recording_timeout_seconds()` | 3539 | translate tick |
| stdout prints in main | 3572, 3576, 3578-3579, 3581-3582 | 3565 "No visual Stream Deck found." |
| stderr journal | `_flag_err` 1767-1768; `set_key` extra_draw failure 1493-1494 | |

### Every gdbus call site (→ `ctx.dbus.call`)

| Lines | Method (owner) | Args | timeout | API | Success detection |
|---|---|---|---|---|---|
| 267-275 | `ListWindows` (todo `_list_mutter_window_ids`) | — | 2 | run | rc==0, tuple → json list → ids set; else None |
| 297-308 | `GetFocusedWindowId` (todo) | — | 2 | run | rc==0, tuple or "" |
| 373-386 | `SendKeysToWindow` (todo) | wid, text | 2 | run | rc==0 and `"true" in stdout.lower()` |
| 557-570 | `TileWindow` (tiling) | 6 ints as str | 3 | run | rc==0 and `"true"` |
| 580-590 | introspect (kernel) | — | 3 | run | `"TileWindow" in stdout` |
| 614-629 | `ListTrackerTimers` (timers) | — | 3 | run | rc==0, tuple → `json.loads`; else [] |
| 638-651 | `ToggleTrackerTimer` (timers) | timer_id | 3 | run | rc==0 and `"true"` |
| 663-676 | `AddTrackerTimer` (timers) | — | 3 | run | rc==0, tuple or "" |
| 685-697 | `ResetAllTrackerTimers` (timers) | — | 3 | run | rc==0 and `"true"` |
| 1016-1029 | `ListWindows` (layouts `_list_windows_dbus`) | — | 3 | run | rc==0, tuple → json or [] |
| 1039-1053 | `ApplyLayout` (layouts) | json payload | **10** | run | rc==0, `re.search(r"\((\d+),\)")` → int, else 0 |
| 1095-1110 | `HotReload` (dev_reload) | — | **10** | run | rc==0 and `bool(tuple payload)` |
| 1794-1802 | `{method}` (claude `_call_claude_dbus`): `FocusClaudeSession` 2099, `AcceptClaudeSession` 2106, `SetClaudeSessionWindow` 2113, `KillClaudeSession` 2120 (+ dead 1832) | sid | 2 | `check_output(stderr=STDOUT).decode()`, **hard-coded dest/path/iface strings** 1796-1800 | `"true" in out.lower()`; CalledProcessError / SubprocessError / FileNotFoundError → False |
| 2055-2064 | `MpvSendCommand` (mpv `_call_mpv_dbus`) | str(int(pid)), command | 2 | check_output, hard-coded strings 2057-2062 | same as claude |
| 2870-2877 | `FocusWindowById` (todo, inline in `_handle_todo_session_key`) | wid | 2 | run | rc==0 and `"true"`; any exception → False |

Proposed single client: `dbus.call(method, *args, timeout=3) -> Reply` with
`Reply(ok_rc, stdout, stderr)`, `.true` (`rc == 0 and "true" in
stdout.lower()`), `.string` (parsed tuple or None); exceptions folded into
`Reply(returncode=None, ...)`. The claude/mpv sites switch from
`check_output(stderr=STDOUT)` to `run(capture_output=True)`: only their
journal text changes (`out` becomes `stdout + stderr`).

---

## 7. Draft skeletons (79 col)

```python
# paths.py
from pathlib import Path
import os

STREAM_DECK_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = STREAM_DECK_DIR.parent.parent
CONFIG_DIR = Path(os.path.expanduser("~/.config/erplibre-home"))
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LAYOUTS_FILE = CONFIG_DIR / "layouts.json"


def state_dir():
    """XDG_STATE_HOME/erplibre-home, read at call time."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state")
    return Path(base) / "erplibre-home"
```

```python
# settings.py
import json
import os

from erplibre_streamdeck import paths


def load():
    """settings.json as a dict; {} when missing or unparsable."""
    try:
        with open(paths.SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(data):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update(**fields):
    """load(), merge `fields`, save(): the read-modify-write every
    caller does today."""
```

```python
# dbus.py
import subprocess
from dataclasses import dataclass

DEST = "org.gnome.Shell"
PATH = "/org/gnome/Shell/Extensions/ERPLibreHome"
IFACE = "org.gnome.Shell.Extensions.ERPLibreHome"


@dataclass(frozen=True)
class Reply:
    returncode: int | None   # None: gdbus missing, timeout, OSError
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def true(self):
        return self.ok and "true" in self.stdout.lower()

    @property
    def string(self):
        return parse_string_tuple(self.stdout) if self.ok else None


def parse_string_tuple(output):
    """('...',) -> str, unescaping \\\\ and \\'; None otherwise."""


def call(method, *args, timeout=3):
    """gdbus call --session on IFACE.method; never raises."""


def available():
    """gdbus introspect lists TileWindow (timeout 3 s)."""
```

```python
# ui/render.py
FONT_SCALE_MIN, FONT_SCALE_MAX = 0.6, 2.5
FONT_SCALE_STEP, FONT_SCALE_DEFAULT = 0.1, 1.0


class Style:
    def __init__(self):
        self.font_scale = FONT_SCALE_DEFAULT
        self.show_labels = False

    def load(self, data):            # _init_font_scale 984-993
        ...

    def set_font_scale(self, scale, settings):   # 996-1002
        ...

    def toggle_labels(self, settings):           # 1005-1010
        ...


STYLE = Style()   # the one instance; set_key reads it per call


def load_label_font(fs):
    ...


def set_key(deck, key, color, text="", icon=None, extra_draw=None,
            style=STYLE):
    """Today's set_key 1483-1514, reading style at call time."""
```

```python
# context.py
class Context:
    def __init__(self, kernel, plugin_id):
        self._k = kernel
        self.plugin_id = plugin_id
        self.geo = kernel.geo
        self.dbus = kernel.dbus          # module or facade with .call
        self.settings = kernel.settings  # module settings
        self.style = kernel.style
        self.t = i18n.t

    @property
    def page(self):
        """Current page id ("idle" on the home screen)."""
        return self._k.page_id

    def set_key(self, key, face_or_color, text="", icon=None,
                extra_draw=None):
        ...

    def flash(self, ok, reason=None):
        """Today's last_result/result_time (+ _flag_err when not ok and
        reason). Does not render: callers render as today."""

    def goto(self, page_id):
        self._k.goto(page_id)

    def home(self):
        self._k.goto(HOME)

    def render(self):
        self._k.render()

    def state(self, plugin_id=None):
        return self._k.state(plugin_id or self.plugin_id)

    def locked(self):
        """The kernel lock, for plugin worker threads (translate)."""
        return self._k.lock

    def log(self, msg):
        print(f"[erplibre-home] {self.plugin_id}: {msg}",
              file=sys.stderr, flush=True)
```

```python
# kernel.py
HOME = "idle"
RESULT_FLASH_SEC = 0.5
DBUS_RECHECK_SEC = 5.0
HOME_REFRESH_SEC = 2.0
LOOP_SEC = 0.3


class Kernel:
    def __init__(self, deck, plugins, clock=time.monotonic,
                 dbus=dbus_mod, settings=settings_mod, style=STYLE):
        rows, cols = deck.key_layout()
        self.geo = Geometry(cols, rows, cols * rows)
        self.lock = threading.Lock()
        self.running = True
        self.page_id = HOME
        self.flash_result = None
        self.flash_time = 0
        self.last_press_key = None
        self.dbus_ok = dbus.available()
        self._dbus_checked_at = clock()
        self._states = {}
        self.pages = {}       # page id -> (plugin id, Page)
        self.page_keys = {}   # page id -> page.keys(geo), once
        self.home = home.Home(self.geo, plugins)
        self._last_tick = {}  # schedule name -> clock value

    def state(self, plugin_id): ...
    def handle_key(self, key, pressed): ...       # 1971-2012
    def goto(self, page_id): ...                  # mode = x; render()
    def render(self): ...                         # 2692-2703
    def _render_page(self): ...                   # 2705-2733
    def _overlay_flash(self): ...                 # 2735-2751
    def _key_neighbors(self, key): ...            # 2753-2764
    def set_flash(self, ok, reason=None): ...     # 1763-1770
    def recheck_dbus(self, now): ...              # 3455-3465
    def step(self, now): ...                      # one loop pass,
                                                  # 3472-3542, testable
    def loop(self): ...                           # while + step + sleep
    def _guarded(self, plugin_id, what, fn, *a): ...  # error isolation
```

```python
# home.py
@dataclass
class Allocation:
    buttons: dict      # key -> (plugin id, HomeButton)
    fixtures: dict     # key -> (plugin id, Fixture)
    pool: list         # dashboard keys in reading order


def allocate(geo, plugins):
    """_compute_idle_buttons 1597-1632 + _compute_claude_buttons
    1864-1880, generalised to the active plugins."""


class Home:
    def render(self, ctx_for, set_key, dbus_ok): ...   # 2999-3099;
                                                      # stores tile_map
    def press(self, key, ctx_for): ...                 # 2127-2223
```

```python
# app.py
def main():
    style.load(settings.load())                       # 3561
    deck = next((d for d in DeviceManager().enumerate()
                 if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(deck_lock.NO_DECK_EXIT)
    ...                                               # 3567-3614
```

---

## 8. Traps and proposed handling

1. **Flash suppresses ticks.** 3479-3482: while `last_result` is set the
   whole `elif` chain is skipped, expired or not; the expiry pass only
   renders. Kernel step: `if flash: render-if-expired; return` before
   any tick. The spec line "1. a flash that has expired → render" must be
   read that way.
2. **"Render once if any home tick ran" over-renders.** Today the home
   screen renders every 2 s (3527-3531) — that render is what refreshes
   the mic indicator and the Claude/mpv tiles, which have no tick of
   their own — and on the pass where the pending TODO capture fires
   (3522-3526, checked every 0.3 s). If the capture becomes a
   `home_tick` with `home_period = 0`, "ran" is true every pass → a full
   render (wpctl + state-dir reads) every 0.3 s. Proposal: `home_tick`
   returns truthy when it wants a render; the kernel owns a
   `HOME_REFRESH_SEC = 2.0` refresh that runs the 2 s home ticks
   (timers `_refresh_timers`, todo `_refresh_todo_terminals`) and always
   renders, so the mic/sessions refresh does not depend on which plugins
   are on. **Question for the user/plan**: accept the return-value
   convention (spec amendment) or keep "ran" literally.
3. **Shared loop timestamps.** `last_idle_refresh` (3470) is shared by the
   todo_session page tick (1 s, 3506/3515) and the home refresh (2 s,
   3527/3531); `last_timer_refresh` (3469) by timer_list only; both start
   at 0 (first pass fires at once). Per-schedule timestamps in the kernel
   change only *when* the first home refresh after leaving todo_session
   happens (≤ 2 s), never what is drawn. Characterization tests drive
   `Kernel.step(now)` with explicit clock values and do not pin that
   timing.
4. **Fixture order is undefined in the spec.** Plugin load order is file
   order (`layouts` < `sound`), but today the mic wins over a layout
   shortcut on the same key (render 3073 before 3076, tap 2157 before
   2161). They collide when LAYOUT becomes the first home button
   (tile/timer/dev_reload/sound turned off: `layout_key = 0` → shortcut
   base `(rows-1)*cols` = mic key). Proposal: give `Fixture` an `order`
   (sound mic 10, layouts 20), place in that order, and a later fixture
   drops keys already taken; render and tap read the same map.
5. **Fixture `place` needs the owner's home key by id.** Layout shortcuts
   are aligned under the LAYOUT key (1621-1626, `base + layout_key`, and
   `layout_key + 3 <= cols`, which also excludes a LAYOUT key in row 1).
   `place(geo, home_keys)` must receive `{plugin_id: key}`; absent id =
   no button = no shortcuts.
6. **Pool excludes every placed fixture key, even an empty one.** Empty
   shortcut slots render `COLOR_EMPTY` (face → None) but are never in the
   dashboard (1874). `home.allocate` reserves all placed keys.
7. **NO EXT is unreachable today.** `tile_key = 0` whenever `cols >= 1`
   (1606-1607), so key 0 is always TILE and 3096 never fires. The spec's
   rule ("nothing else took key 0") reproduces this exactly; it shows
   only when every home-button plugin is off. Flag to the user: keeping
   it identical keeps a warning nobody sees.
8. **Dead guard `timer_key != tile_key`** (2214, 3049): both keys are ≥ 0
   and distinct whenever either exists. Drops out naturally with
   HomeButtons.
9. **Timers `items` has a side effect.** The render purges
   `_dashboard_hidden_timer_ids` (3013-3014) before listing; keep it in
   the timers provider's `items` (called once per render), not in `face`.
10. **TILE press clears the flash** (`last_result = None`, 2221). Input is
    blocked during a flash (1976-1978) and an expired flash is cleared by
    the next `render()` (2702), so dropping that line is screen-identical;
    no `ctx.clear_flash` needed.
11. **Handlers render themselves; the kernel must not render after a
    dispatch.** E.g. empty shortcut slot (2164-2165) and Claude tile with
    an empty sid (2190-2194) do *no* render; `_flag_err` does not render
    (callers do). `ctx.flash` therefore does not render; `goto`/`home`
    do.
12. **Background-thread flash.** `_finish_transcription` (2550-2554)
    takes `self.lock`, flashes, and renders only if
    `mode == MODE_TRANSLATOR`. The spec's Context has neither the lock nor
    the current page: add `ctx.locked()` (or `ctx.lock`) and `ctx.page`.
13. **Programmatic flashes reuse a stale key.** `last_press_key` is never
    reset, so loop-originated flashes (capture failure 1714, transcription
    2551) paint around the last pressed key; the whole-deck fallback
    (2736-2743) only happens before the first press ever. Kernel keeps
    that.
14. **`OK!`/`ERR` are not translated.** `_overlay_flash` uses literals
    (2741, 2746); `_DECK_LABELS` has `'OK!'`/`'ERR'` (174-176) with
    identical fr values. Either route through `t()` or drop the two
    entries — no visible change. Likewise `"DEV\nRELOAD"`, `"A11Y"`,
    `"BT"` are never passed to `_t` (3053, 3062, 3065); keep as is.
15. **Journal prefix changes.** `_flag_err` prints `[erplibre-home]
    {reason}`; `ctx.log` adds the plugin id. Characterization tests must
    not pin stderr text, or pin it after the switch.
16. **Two D-Bus probes at start** (3574 in `main`, 1545 in `__init__`).
    App prints from `kernel.dbus_ok`; print order moves after plugin
    setup (translator detection), stdout only.
17. **Style read at call time** (1495, 1497): `set_key` must read
    `STYLE.font_scale` / `show_labels` per call; a11y page (3313-3325) and
    handler (2598-2604) mutate the same instance. `_init_font_scale()`
    runs before deck enumeration (3561): `app.main` loads the style
    first.
18. **Page keys may be `None`** (deck too small: e.g. 1952-1954,
    1885-1887). `Page.keys(geo)` returning None must be legal; the page's
    render shows `DECK TOO SMALL`. Keys are computed once at start
    (1634-1641) except todo_session (2766-2776, per call) and timer_list
    (`timer_key_map` rebuilt by every `_refresh_timers`).
19. **Error handling gap in claude/mpv D-Bus.** `check_output(...).decode()`
    is strict UTF-8 and only `CalledProcessError`, `SubprocessError`,
    `FileNotFoundError` are caught (1810-1817, 2071-2081); a
    `UnicodeDecodeError` or `PermissionError` escapes into the key
    callback. `dbus.call` never raises: strictly safer, same screen.
20. **Module name clash during migration.** Step 1 puts the package
    `script/stream_deck/erplibre_streamdeck/` next to
    `erplibre_streamdeck.py`. `import erplibre_streamdeck` then resolves
    to the package, and the existing test loader registers the monolith
    as `sys.modules["erplibre_streamdeck"]` (85-88 of
    `test_erplibre_streamdeck_chunks.py`), which breaks
    `import erplibre_streamdeck.kernel` in the same process. The step-0
    characterization helper must load the monolith under another name
    (e.g. `erplibre_streamdeck_monolith`), and the chunks test must not
    run in the same process as the package tests (it is discovered from
    `./script/stream_deck` by `make streamdeck_tiler_unittest`, 232 of
    `conf/make.streamdeck.Makefile`).
21. **Import-time environment.** `_DECK_LANG` (123) and `_FONT_PATH`
    (1463-1467) are fixed at import; tests that vary `LANG` must set it
    before import, or `i18n` reads it lazily (preferred).
22. **`key_layout()` returns `(rows, cols)`** (1520, 3571); the fake deck
    must follow that order.
23. **Exceptions today kill the loop thread silently** (daemon, no
    try/except in 3467-3543) and propagate out of the key callback. The
    kernel's isolation changes behaviour only on error; no reference file
    can pin it.

### Dead code (one commit before the move; all confirmed by grep)

| Lines | Item | Evidence |
|---|---|---|
| 30-31 | `import urllib.error`, `import urllib.request` | no other `urllib` |
| 101 | `GALLERY_RESTART_URL` | only its definition |
| 102 | `COLOR_ACTIVE` | only its definition |
| 818-819 (+ blank 820-821) | `_wpctl_available` | only its definition |
| 1772-1790 (+ blank 1791) | `Tiler._enter_claude_session_mode` | only its definition; its logic is inlined at 2186-2194 |
| 1819-1832 (+ blank 1833) | `Tiler._focus_claude_for_key` | only its definition; `_call_claude_dbus` stays (2099-2120) |
| 2973-2974 | `or (session or {}).get('last_prompt')` | session dicts are built at 427-434 with no `last_prompt` key (folded into `description` at 430-431, which stays) → `(session or {}).get('description') or ''` |
| 174-176 | `'OK!'`, `'ERR'` labels | never passed to `_t` (AST check) — optional, see trap 14 |
| 1964 | `if self.cols >= 4:` in `_compute_sound_buttons` | always true after the 1952 guard (sound domain) |
