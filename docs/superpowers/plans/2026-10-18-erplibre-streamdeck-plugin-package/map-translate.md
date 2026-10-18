# B2 map — plugin `translate`

Source: `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD
b61156bf). Every range below was read with the Read tool / `sed -n` /
`grep -n`. Target plugin file: `erplibre_streamdeck/plugins/translate.py`
(id `translate`, pages `translator` and `translator_history`).

## 1. Module-level names owned by the domain

| Name | Lines | Target |
|---|---|---|
| `import tempfile` | 27 | plugin (only user: 2490) |
| `import threading` | 28 | plugin keeps its own import (also used by kernel 1524, app 3593) |
| `import translator as _translator` | 44 | plugin, top-level import (no attribute touched at import) |
| `COLOR_TR_TITLE = (160, 90, 200)` | 78 | `ui/colors.py` |
| `COLOR_REC_ON = (200, 30, 30)` | 79 | `ui/colors.py` |
| `COLOR_REC_OFF = (60, 60, 60)` | 80 | `ui/colors.py` |
| `COLOR_BACKEND = (90, 130, 80)` | 81 | `ui/colors.py` |
| `COLOR_OUTPUT = (50, 110, 150)` | 82 | `ui/colors.py` |
| `COLOR_LLM_OFF = (60, 60, 60)` | 83 | `ui/colors.py` |
| `COLOR_LLM_ON = (140, 60, 160)` | 84 | `ui/colors.py` |
| label `'TRANSL': 'TRADUC'` in `_DECK_LABELS` | 148 | `ui/i18n.py` (the dict stays whole) |
| `MODE_TRANSLATOR = "translator"` | 537 | page id string in the plugin |
| `MODE_TRANSLATOR_HISTORY = "translator_history"` | 538 | page id string in the plugin |
| `_icon_translator(draw, w, h)` | 1318-1338 | `ui/icons.py` |
| `_ICONS["translator"]` entry | 1406 | `ui/icons.py` |

Shared names the domain READS but does not own (stay in `ui/colors.py`,
`ui/i18n.py`, `settings.py`): `COLOR_EMPTY` 46, `COLOR_BACK` 54,
`COLOR_CANCEL` 59, `COLOR_VOL` 63 (the idle STR key colour, a sound
colour), `COLOR_LOAD_FILLED` 69 (history entries), `COLOR_ERR` 104;
labels `BACK` 127, `CLEAR` 131, `DECK\nTOO\nSMALL` 161; icons `mic_on` /
`mic_off` 1397-1398 (REC key, shared with sound); `_settings_load`
970-975, `_settings_save` 978-981 (`settings.py`); `_t` 181-184.

Plain labels NOT passed through `_t` (must stay untranslated): `REC`,
`STOP`, `STR`, `STR\nON`, `STT\n<name[:6]>`, `OUT\nTYPE`, `OUT\nCLIP`,
`LLM\nOFF`, `LLM\nTRSL`, `LLM\nCHAT`, `LLM\n<name[:6]>`, `NONE`.

## 2. Tiler methods owned

| Method | Lines | Reads | Writes | Other-domain / kernel calls |
|---|---|---|---|---|
| `__init__` translator block | 1558-1593 | — | `_stt_backends, _stt_index, _output_methods, _output_index, _llm_backends, _llm_index, _llm_mode_index, _record_proc, _record_path, _record_started_at, _vad_should_stop, _streaming_proc` | `_settings_load()` 1575 |
| `_compute_translator_buttons` | 1882-1900 | `cols, rows` | `translator_keys` | called from `_compute_idle_buttons` 1638 |
| `_handle_translator_key` | 2365-2425 | `translator_keys, _record_proc, _stt_backends, _stt_index, _output_methods, _output_index, _llm_mode_index, _llm_backends, _llm_index` | `mode, _record_proc, _stt_index, _output_index, _llm_mode_index, _llm_index` | `render()`, `_settings_load/_save`, `_toggle_record`, `_toggle_streaming` |
| `_handle_translator_history_key` | 2427-2446 | `total_keys, _output_methods, _output_index` | `mode, last_result, result_time` | `render()` |
| `_on_vad_silence` | 2448-2450 | — | `_vad_should_stop` | runs on the ffmpeg stderr reader thread, no lock |
| `_toggle_streaming` | 2452-2480 | `_streaming_proc` | `_streaming_proc` | `_flag_err` 2479, `render()` |
| `_toggle_record` | 2482-2520 | `_record_proc, _stt_backends, _record_path` | `_record_proc, _record_path, _vad_should_stop, _record_started_at` | `_flag_err` 2485/2501, `render()`, starts thread 2516-2520 |
| `_finish_transcription` | 2522-2554 | `_stt_backends, _stt_index, _llm_mode_index, _llm_backends, _llm_index, _output_methods, _output_index, mode` | `last_result, result_time` (2551-2552, under `self.lock` 2550) | `render()` 2554 only if `mode == MODE_TRANSLATOR` |
| `_render_translator_history` | 3180-3195 | `total_keys` | — | `set_key` |
| `_render_translator` | 3197-3259 | `translator_keys, total_keys, _record_proc, _stt_backends, _stt_index, _output_methods, _output_index, _llm_mode_index, _llm_backends, _llm_index, _streaming_proc` | — | `set_key`; `_streaming_proc.poll()` 3248 |

Kernel lines that reference the domain and disappear into the generic
dispatch:
- `handle_key` branches 2003-2006;
- `_render_mode` branches 2724-2727;
- `_handle_idle_key` TRANSL branch 2150-2153;
- `_render_idle` TRANSL branch 3066-3070;
- `_compute_idle_buttons` order list 1602-1605 (`"translator"` at index 7)
  and the call 1638;
- `_compute_claude_buttons` used-set, `self.translator_key` at 1870;
- `loop` translator branch 3532-3542;
- `main` streaming cleanup 3603-3611.

Kernel helper used: `_flag_err` 1763-1770 (prints
`[erplibre-home] {reason}` to stderr, sets `last_result="err"`,
`result_time=time.monotonic()`, does NOT render).

## 3. Per-plugin state (`ctx.state("translate")`)

All set in `Tiler.__init__` 1558-1593 (setup):

| Attribute (state name) | Initial value | Lines |
|---|---|---|
| `stt_backends` | `_translator.detect_stt_backends()` | 1559 |
| `stt_index` | `0`, then restored from `prefs["translator_stt"]` by `b.name` | 1560, 1576-1580 |
| `output_methods` | `_translator.detect_output_methods() or [_translator.OUTPUT_CLIP]` | 1561-1564 |
| `output_index` | `0`, then `output_methods.index(prefs["translator_output"])` if present | 1565, 1581-1584 |
| `llm_backends` | `_translator.detect_llm_backends()` | 1566 |
| `llm_index` | `0`, then restored from `prefs["translator_llm"]` by `b.name` | 1567, 1585-1589 |
| `llm_mode_index` | `0`, then `LLM_MODES.index(prefs["translator_llm_mode"])` if in `LLM_MODES` | 1568, 1590-1593 |
| `record_proc` | `None` | 1569 |
| `record_path` | `None` | 1570 |
| `record_started_at` | `0.0` | 1571 |
| `vad_should_stop` | `False` | 1572 |
| `streaming_proc` | `None` | 1573 |
| `keys` (new, cache) | `_translator_keys(ctx.geo)` (was `self.translator_keys`, 1882-1900) | — |

`prefs = _settings_load()` 1575 becomes `ctx.settings.load()`. Settings
keys written: `translator_stt` 2384, `translator_output` 2393,
`translator_llm_mode` 2404, `translator_llm` 2415 (each a full
load-modify-save, non-atomic, kept for B3).

## 4. Pages

### `translator`
- keys: `_compute_translator_buttons` 1882-1900. `None` when
  `cols < 4 or rows < 2`; else `back 0`, `stream cols+0`, `record cols+1`,
  `backend cols+2`, `output cols+3`; `cols >= 6` adds `llm_mode cols+4`,
  `llm_backend cols+5`; `cols >= 7` adds `history cols+6`.
  At the reference geometries: 3x2 → None, 4x2 → base 5 keys,
  5x3 → base 5 keys, 8x4 → all 8 keys.
- render: `_render_translator` 3197-3259. Too-small branch 3199-3207
  (key 0 BACK, key `total//2` ERR `DECK\nTOO\nSMALL`, rest empty).
- handle: `_handle_translator_key` 2365-2425. Too-small → home
  (2367-2370). Order of tests: back 2371, record 2378, backend (only if
  `_stt_backends`) 2381, output 2388, llm_mode 2399, llm_backend (only
  if `_llm_backends`) 2410, history 2419, stream 2423.
- tick: loop branch 3532-3542 (`mode == translator and _record_proc is
  not None and _record_started_at > 0`): VAD flag first, else timeout.
- period: `0.0` (runs on every 0.3 s loop pass).
- → `Page("translator", _translator_keys, _render_main, _handle_main,
  tick=_tick_main, period=0.0)`.

### `translator_history`
- keys: none computed today; derived from `total_keys`: `back 0`,
  `clear total-1`, entries `1..total-2` (2428-2439, 3182-3193).
- render: `_render_translator_history` 3180-3195 (entries
  `reversed(load_history())`, snippet `text[:8]`, colour
  `COLOR_LOAD_FILLED`).
- handle: `_handle_translator_history_key` 2427-2446 (key 0 →
  `translator` page; `total-1` → `clear_history()` + render; else
  `output_text(entry.text, method)` + flash ok/err + render).
- tick: none. Reachable only from the `history` key (cols >= 7).
- → `Page("translator_history", _history_keys, _render_history,
  _handle_history)`.

## 5. Home contributions

- HomeButton: `order=80`. Face `KeyFace(COLOR_TR_TITLE, ctx.t("TRANSL"),
  icon="translator")` from 3066-3070. Press `ctx.goto("translator")` from
  2150-2153. Position index 7 in the order list 1602-1605. At 3x2 and
  4x2 the button gets no key (row 0 full, rows < 3); 5x3 → key 7 (row 1
  overflow); 8x4 → key 7.
- Fixture: none.
- TileProvider: none.
- home_tick: none (the loop branch only runs on the `translator` page).
- shutdown: streaming cleanup 3603-3611.

## 6. External side effects to stub

| Effect | Lines | Detail |
|---|---|---|
| `_translator.detect_stt_backends()` | 1559 | real impl probes binaries/paths; objects need `.name`, `.transcribe(path)` |
| `_translator.detect_output_methods()` | 1562 | `shutil.which` ydotool/xdotool/wl-copy/xclip; returns list of `"type"`/`"clip"` |
| `_translator.OUTPUT_CLIP` | 1563 | only read when detection returned empty (short-circuit `or`) |
| `_translator.detect_llm_backends()` | 1566 | real impl does `urlopen` on localhost:11434 and :8080 (1 s timeout each) — MUST be stubbed |
| `_translator.LLM_MODES` | 1590-1591, 2401, 2405, 2527, 3218 | always read in setup (the `in` test at 1590 runs every time) |
| `_translator.LLM_MODE_OFF/TRANSLATE/CHAT` | 3220-3222, 3225 | render only |
| `_translator.OUTPUT_TYPE` | 3214 | render only |
| `_settings_load()` / `_settings_save()` | 1575, 2383-2385, 2392-2396, 2403-2407, 2414-2416 | `~/.config/erplibre-home/settings.json` (`SETTINGS_FILE` 90, `LAYOUT_DIR` 88) |
| `_translator.stop_recording(proc)` | 2373, 2510 | terminate+wait(3)+kill |
| `tempfile.mkstemp(prefix="sttrec_", suffix=".wav")`, `os.close(fd)` | 2490-2491 | temp file in `$TMPDIR` |
| `_translator.vad_enabled()` | 2494 | reads settings.json itself |
| `_translator.start_recording_vad(path, on_silence=cb)` | 2495-2497 | ffmpeg + daemon stderr reader thread calling `cb` |
| `_translator.start_recording(path)` | 2499 | parecord/arecord/ffmpeg Popen; `None` on failure |
| `os.unlink(path)` | 2503 (start failed), 2547 (after transcription) | |
| `time.monotonic()` | 2506 (`_record_started_at`), 2445, 2552 (`result_time`), 1770 (`_flag_err`) | plus the loop's `now` 3472 passed to tick |
| `threading.Thread(target=_finish_transcription, args=(path,), daemon=True).start()` | 2516-2520 | stub: capture target/args, run AFTER the lock is released (running it inline under the lock deadlocks at 2550) |
| `backend.transcribe(wav_path)` | 2526 | |
| `_translator.llm_postprocess(raw, llm_mode, llm_backend)` | 2532 | real impl may call `focused_window_class()` (gdbus) and `backend.chat` |
| `_translator.output_text(text, method)` | 2443, 2535 | real impl runs ydotool/xdotool or wl-copy/xclip; returns bool |
| `_translator.append_history(text, llm_mode=, language=, wm_class=)` | 2537-2542 | writes `~/.config/erplibre-home/translator-history.json` |
| `_translator.stt_language()` | 2540 | reads settings.json |
| `_translator.focused_window_class()` | 2541 | gdbus `GetFocusedWindowClass` |
| `print("history append error: ...", stderr)` | 2544 | |
| `_translator.load_history()` | 2437, 3181 | reads translator-history.json; list oldest first |
| `_translator.clear_history()` | 2434 | unlinks translator-history.json |
| `_translator.recording_timeout_seconds()` | 3539 | reads settings.json on every tick |
| `subprocess.Popen([sys.executable, <dir>/translator_stream.py], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)` | 2466-2476 | path `os.path.join(os.path.dirname(os.path.abspath(__file__)), "translator_stream.py")` |
| `proc.poll()`, `terminate()`, `wait(timeout=2)`, `kill()` | 2453-2462, 3248, 3603-3611 | streaming proc |

Translator stub, import vs call: at import (line 44) nothing is touched,
so an empty `types.ModuleType("translator")` (as in
`script/stream_deck/test_erplibre_streamdeck_chunks.py:79`) imports
fine. At construction / `setup`: `detect_stt_backends`,
`detect_output_methods`, `detect_llm_backends`, `LLM_MODES` always;
`OUTPUT_CLIP` only when detection is empty. At render: `LLM_MODES`,
`LLM_MODE_OFF/TRANSLATE/CHAT`, `OUTPUT_TYPE`, `load_history`. At handle
/ tick / thread: the rest. Consequence: with the empty stub,
`Tiler(deck)` raises `AttributeError`, and in the package `setup` raises
→ the loader REFUSES `translate` → the home row loses TRANSL and `todo`
closes up. The shared test helper must install a fake translator with
the full surface above (fixed backends, e.g. STT `whisper.cpp`,
outputs `["type", "clip"]`, LLM `ollama`, `LLM_MODES` copied from the
real values `["off", "translate", "chat"]`, `OUTPUT_TYPE="type"`,
`OUTPUT_CLIP="clip"`, `load_history` returning fixed entries).

## 7. Draft plugin module

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Translator plugin: speech-to-text, LLM post-processing, history.

Pages `translator` and `translator_history`; a home button at order 80.
The transcription runs on a worker thread and takes the kernel lock
only to set the flash and redraw.
"""

import os
import subprocess
import sys
import tempfile
import threading

import translator as _translator

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors as C

_ID = "translate"
PAGE = "translator"
PAGE_HISTORY = "translator_history"


def _translator_keys(geo):
    """Named keys of the main page, or None below 4x2."""
    if geo.cols < 4 or geo.rows < 2:
        return None
    c = geo.cols
    keys = {"back": 0, "stream": c, "record": c + 1,
            "backend": c + 2, "output": c + 3}
    if c >= 6:
        keys["llm_mode"] = c + 4
        keys["llm_backend"] = c + 5
    if c >= 7:
        keys["history"] = c + 6
    return keys


def _history_keys(geo):
    return {"back": 0, "clear": geo.total_keys - 1}


def _index_by_name(items, name):
    for i, b in enumerate(items):
        if b.name == name:
            return i
    return 0


def _setup(ctx):
    st = ctx.state(_ID)
    st.keys = _translator_keys(ctx.geo)
    st.stt_backends = _translator.detect_stt_backends()
    st.output_methods = (_translator.detect_output_methods()
                         or [_translator.OUTPUT_CLIP])
    st.llm_backends = _translator.detect_llm_backends()
    st.stt_index = st.output_index = 0
    st.llm_index = st.llm_mode_index = 0
    st.record_proc = st.record_path = None
    st.record_started_at = 0.0
    st.vad_should_stop = False
    st.streaming_proc = None
    prefs = ctx.settings.load()
    if prefs.get("translator_stt"):
        st.stt_index = _index_by_name(
            st.stt_backends, prefs["translator_stt"])
    if prefs.get("translator_output") in st.output_methods:
        st.output_index = st.output_methods.index(
            prefs["translator_output"])
    if prefs.get("translator_llm"):
        st.llm_index = _index_by_name(
            st.llm_backends, prefs["translator_llm"])
    if prefs.get("translator_llm_mode") in _translator.LLM_MODES:
        st.llm_mode_index = _translator.LLM_MODES.index(
            prefs["translator_llm_mode"])


def _save_pref(ctx, key, value):
    data = ctx.settings.load()
    data[key] = value
    ctx.settings.save(data)


def _streaming_active(st):
    p = st.streaming_proc
    return p is not None and p.poll() is None


def _stop_proc(proc):
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _render_too_small(ctx):
    total = ctx.geo.total_keys
    for key in range(total):
        if key == 0:
            ctx.set_key(key, C.COLOR_BACK, ctx.t("BACK"))
        elif key == total // 2:
            ctx.set_key(key, C.COLOR_ERR, ctx.t("DECK\nTOO\nSMALL"))
        else:
            ctx.set_key(key, C.COLOR_EMPTY, "")


def _render_main(ctx):
    st = ctx.state(_ID)
    tk = st.keys
    if not tk:
        _render_too_small(ctx)
        return
    # body of 3208-3259, self.* -> st.*, set_key(self.deck, ...) ->
    # ctx.set_key(...), _t -> ctx.t, colours from C.
    ...


def _handle_main(ctx, key):
    st = ctx.state(_ID)
    tk = st.keys
    if not tk:
        ctx.home()
        return
    if key == tk["back"]:
        if st.record_proc is not None:
            _translator.stop_recording(st.record_proc)
            st.record_proc = None
        ctx.home()
        return
    if key == tk["record"]:
        _toggle_record(ctx)
        return
    if key == tk["backend"] and st.stt_backends:
        st.stt_index = (st.stt_index + 1) % len(st.stt_backends)
        _save_pref(ctx, "translator_stt",
                   st.stt_backends[st.stt_index].name)
        ctx.render()
        return
    # output 2388-2398, llm_mode 2399-2409, llm_backend 2410-2418:
    # same shape.
    if key == tk.get("history"):
        ctx.goto(PAGE_HISTORY)
        return
    if key == tk.get("stream"):
        _toggle_streaming(ctx)


def _toggle_streaming(ctx):
    st = ctx.state(_ID)
    if _streaming_active(st):
        _stop_proc(st.streaming_proc)
        st.streaming_proc = None
        ctx.render()
        return
    script = os.path.join(paths.STREAM_DECK_DIR, "translator_stream.py")
    try:
        st.streaming_proc = subprocess.Popen(
            [sys.executable, script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        st.streaming_proc = None
        ctx.flash(False, f"streaming start failed: {e}")
    ctx.render()


def _toggle_record(ctx):
    st = ctx.state(_ID)
    if st.record_proc is None:
        if not st.stt_backends:
            ctx.flash(False, "translator: no STT backend available "
                             "(install whisper-cpp or vosk)")
            ctx.render()
            return
        fd, path = tempfile.mkstemp(prefix="sttrec_", suffix=".wav")
        os.close(fd)
        st.record_path = path
        st.vad_should_stop = False
        if _translator.vad_enabled():
            st.record_proc = _translator.start_recording_vad(
                path, on_silence=lambda: setattr(
                    st, "vad_should_stop", True))
        else:
            st.record_proc = _translator.start_recording(path)
        if st.record_proc is None:
            ctx.flash(False,
                      f"translator: failed to start recording at {path}")
            os.unlink(path)
            st.record_path = None
        else:
            st.record_started_at = ctx.monotonic()
        ctx.render()
        return
    _translator.stop_recording(st.record_proc)
    st.record_proc = None
    st.record_started_at = 0.0
    path, st.record_path = st.record_path, None
    ctx.render()
    threading.Thread(target=_finish_transcription,
                     args=(ctx, path), daemon=True).start()


def _finish_transcription(ctx, wav_path):
    st = ctx.state(_ID)
    ok = False
    try:
        ...  # 2525-2544 unchanged, self.* -> st.*
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass
    with ctx.locked():
        ctx.flash(ok)
        if ctx.page == PAGE:
            ctx.render()


def _tick_main(ctx, now):
    st = ctx.state(_ID)
    if st.record_proc is None or st.record_started_at <= 0:
        return
    if st.vad_should_stop:
        st.vad_should_stop = False
        _toggle_record(ctx)
        return
    timeout = _translator.recording_timeout_seconds()
    if timeout > 0 and now - st.record_started_at >= timeout:
        _toggle_record(ctx)


def _render_history(ctx):
    ...  # 3181-3195


def _handle_history(ctx, key):
    st = ctx.state(_ID)
    total = ctx.geo.total_keys
    if key == 0:
        ctx.goto(PAGE)
        return
    if key == total - 1:
        _translator.clear_history()
        ctx.render()
        return
    entries = list(reversed(_translator.load_history()))
    idx = key - 1
    if 0 <= idx < len(entries):
        method = st.output_methods[st.output_index]
        ok = _translator.output_text(
            entries[idx].get("text", ""), method)
        ctx.flash(ok)
        ctx.render()


def _shutdown(ctx):
    st = ctx.state(_ID)
    if st.streaming_proc is not None:
        _stop_proc(st.streaming_proc)


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[
        Page(PAGE, _translator_keys, _render_main, _handle_main,
             tick=_tick_main, period=0.0),
        Page(PAGE_HISTORY, _history_keys, _render_history,
             _handle_history),
    ],
    home_buttons=[HomeButton(
        order=80,
        face=lambda ctx: KeyFace(C.COLOR_TR_TITLE, ctx.t("TRANSL"),
                                 icon="translator"),
        press=lambda ctx: ctx.goto(PAGE),
    )],
    setup=_setup,
    shutdown=_shutdown,
)
```

`ctx.monotonic()` is shorthand for `time.monotonic()` (either import
`time` in the plugin and let tests patch `time.monotonic`, or add it to
the Context; see trap 3).

## 8. Traps

1. **Worker thread needs the kernel lock and the current page.**
   `_finish_transcription` 2550-2554 takes `self.lock`, sets the flash
   and redraws only if `mode == MODE_TRANSLATOR`. The spec's Context has
   neither a lock nor the current page id. Proposal: add
   `ctx.locked()` (context manager on the kernel lock, for threads the
   plugin starts itself) and a read-only `ctx.page` (current page id).
   A "post to next loop" alternative shifts the flash by up to 0.3 s and
   is not identical. The flash is set even when the user left the page
   (it then blocks input 0.5 s and suppresses ticks, invisibly) — keep.
2. **`ctx.flash` must not render and must not log on `ok`/no-reason.**
   `_flag_err` 1763-1770 never renders; callers render after. The
   history tap 2444-2446 and the thread 2551-2552 set the flash with no
   journal line. `ctx.flash(False)` without `reason` must stay silent.
   The journal prefix changes from `[erplibre-home]` to the plugin-id
   prefix if `flash` routes through `ctx.log` (journal only, not screen).
   The `history append error` print 2544 has no prefix today.
3. **Tick gating by the flash.** The loop's `if self.last_result:` 3479
   swallows every branch while a flash is set, even unexpired; the
   expired case renders (which clears `last_result` at 2702) and also
   skips the tick on that pass. The kernel precedence must be: flash
   set → (render if expired) and NO tick on this pass; tick only when no
   flash is set. Period `0.0` must mean "every pass".
   `time.monotonic` is read in the plugin (2506) and compared with the
   kernel's `now`; tests must patch the same clock for both.
4. **Tick only on `translator`, not on `translator_history`.** Recording
   continues while the user is on the history page (the `history` key
   does not stop it); VAD and timeout are processed only after coming
   back. Mapping the tick to the `translator` page reproduces this.
5. **BACK leaks state.** 2371-2377 stops the recorder but leaves
   `_record_path` (the temp WAV is never unlinked), `_record_started_at`
   and `_vad_should_stop` set, and never transcribes. Keep as-is for
   parity (B3 candidate); harmless because the tick checks
   `record_proc is None` first.
6. **Thread exceptions.** If `transcribe`, `llm_postprocess` or
   `output_text` raises, `finally` unlinks the WAV and the exception
   kills the thread before 2550: no flash, no redraw. The kernel's error
   isolation does not cover plugin threads; keep identical.
7. **Shutdown stops only streaming.** 3603-3611 terminates
   `_streaming_proc`; an active `_record_proc` is not stopped. Order
   today: `running = False`, streaming cleanup, `deck.reset/close`. The
   plugin `shutdown` runs before reset/close.
8. **translator.py reads settings.json itself** (`_load_settings`
   translator.py:648-657, used by `vad_enabled`, `stt_language`,
   `recording_timeout_seconds`, `llm_model_preference`), bypassing
   `settings.py`. translator.py is out of scope; tests must point HOME
   (or the fake module) at the fixture, not only `settings.py`.
9. **Setup is slow and networked.** `detect_llm_backends` opens
   localhost:11434 and :8080 with 1 s timeouts (translator.py:401-466);
   today it runs in `Tiler.__init__`, before the first render. In the
   loader it runs in `setup`, before the kernel's first render: same
   start-up delay. Tests must stub it.
10. **Empty stub refuses the plugin.** See section 6: with the empty
    `translator` module of the chunk tests, `setup` raises and the loader
    refuses `translate`, which changes the home allocation (TRANSL gone,
    TODO moves left). The home characterization must use the full fake.
11. **`__file__` path.** 2466-2469 uses `os.path.abspath(__file__)`;
    `paths.STREAM_DECK_DIR` uses `Path(__file__).resolve()`. They differ
    only if the directory is reached through a symlink; recorded argv in
    tests should compare `os.fspath(paths.STREAM_DECK_DIR /
    "translator_stream.py")`, passed as a `str` to Popen so argv stays a
    list of strings.
12. **Keys cache vs geometry.** `translator_keys` is computed once in
    `_compute_idle_buttons` 1638; the geometry never changes at run time,
    so caching `_translator_keys(ctx.geo)` in `setup` (or calling it in
    render/handle) is identical. `Page.keys` returns `None` below 4x2;
    the kernel/home must accept a `None`/`{}` result for a page.
13. **Home allocation.** The TRANSL button is index 7 of 9; with every
    plugin on, order 80 between bluetooth 70 and todo_terminals 90
    reproduces 1602-1617. Its key enters the dashboard's used set (1870)
    through home.py generically, no translate-specific code.
14. **Handle test order.** `backend` and `llm_backend` taps with no
    backend fall through the remaining tests and do nothing (no render).
    Keep the guard inside the same `if` so the fall-through is
    preserved.
15. **History tap reads the file again** (2437) rather than the render's
    list: a history append between render and tap shifts the entries.
    This is page-internal, not the dashboard change the spec announces;
    keep.
