# B2 map: TEST HARNESS (characterization + parity)

Read-only map. All line numbers verified with `sed -n` / `grep -n` / `ast`
on `script/stream_deck/erplibre_streamdeck.py` (3618 lines, HEAD b61156bf).
The draft helper at the end was **run against the monolith** at the four
geometries (home, full dashboard, sound, translator REC/STOP + transcription
thread, timer list, TODO launch + capture, layout previews, a11y, golden
write/read roundtrip): green, `ruff --select E,F,W,B --line-length 79`
clean. Copy kept at
`streamdeck_stubs.draft.txt` (beside this file).

## 0. Facts about the runners (drive every decision below)

| Fact | Source |
|---|---|
| `run_unit_test.sh` runs every `test/test_*.py` (glob, `ls test/test_*.py`), one **process per file**, `--jobs` = cpu count by default (`UNIT_JOBS`), with `.venv.erplibre/bin/python -u <file>`, cwd = repo root, `PYTHONPATH=.`, own `TMPDIR` per file, `start_new_session`, stdin `/dev/null` | `script/test/run_unit_test.sh:65-78`, `script/test/run_unit_test.py:26-45, 274-317` |
| The runner does **not** isolate HOME / XDG; its PATH doubles only refuse sudo, pkexec, doas, virsh, ssh, adb. `gdbus`, `wpctl`, `bluetoothctl`, `zenity`, `gnome-terminal` reach the host if not faked | `run_unit_test.py:31-40, 203-245` |
| `sys.path[0]` = `test/` (script run by path) -> `import streamdeck_stubs` works directly; the house style still does `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` before `from async_case import ...` | `test/test_mail_compose.py:27-28`, `test/async_case.py:15` (helper without `test_` prefix is not picked up) |
| `.venv.erplibre` (Python 3.14.8) **has Pillow** -> stubs must be FORCED into `sys.modules`, not `setdefault` (the current chunks test uses `setdefault`, `script/stream_deck/test_erplibre_streamdeck_chunks.py:44-47,67-73`) | `.venv.erplibre/bin/python -c "import PIL"` OK |
| `make streamdeck_tiler_unittest` = `$(STREAMDECK_PY) -m unittest discover -s ./script/stream_deck -p "test_erplibre_streamdeck*.py" -v`: **one process for all files** -> helper must be idempotent and reset per scenario | `conf/make.streamdeck.Makefile:229-232` |
| `.flake8`: max 80 (B950), `select = C,E,F,W,B,B9` -> **E402 is active** | `.flake8` |
| No `test/__init__.py`, no `script/stream_deck/__init__.py` | `ls` |
| `deck.key_layout()` returns **(rows, cols)** | monolith 1520 `rows, cols = deck.key_layout()`; controller 867; every game |

## 1. Module-level names the harness touches (monolith -> package seam)

Nothing of the deck program "belongs" to this domain; these are the names
the harness patches, stubs or resets. Package column = seam the harness
needs (name may follow the kernel map: `kernel.md` proposes `ui/render.STYLE`,
`Kernel.page_id`, `Kernel.pages`, `Kernel.state`).

| Name | Lines | What the harness does | Package seam |
|---|---|---|---|
| top imports `PIL`, `StreamDeck.*` | 34-41 | stub modules forced in `sys.modules` (PIL.Image.new, ImageDraw.Draw, ImageFont.truetype/load_default, DeviceManager, PILHelper.to_native_key_format/create_image, TransportError) | same imports, lazily or via `ui/render.py` (spec Risk 2) |
| `import deck_lock` | 43 | real module (stdlib only), via `script/stream_deck` on `sys.path` | same |
| `import translator as _translator` | 44 | stub module `translator` with every attribute used: `OUTPUT_TYPE/CLIP`, `LLM_MODE_OFF/TRANSLATE/CHAT`, `LLM_MODES`, `detect_stt_backends`, `detect_output_methods`, `detect_llm_backends`, `load_history`, `clear_history`, `output_text`, `vad_enabled`, `start_recording`, `start_recording_vad`, `stop_recording`, `recording_timeout_seconds`, `llm_postprocess`, `append_history`, `stt_language`, `focused_window_class` (grep `_translator\.` = 21 names) | `plugins/translate.py` does `import translator` and calls `translator.X` (attribute lookup) |
| `LAYOUT_DIR`, `LAYOUT_FILE`, `SETTINGS_FILE` | 88-90 | computed at import from `~` (`expanduser`, NOT `XDG_CONFIG_HOME`) -> HOME set before load | `settings.py` / `paths.py`; harness sets `XDG_CONFIG_HOME=$HOME/.config` so both agree |
| `_font_scale`, `_show_labels` | 98-99 | reset each boot | `ui/render.STYLE.font_scale/.show_labels` |
| `_DECK_LANG` | 123 | computed at import from `LANG`; harness sets `LANG=en_US.UTF-8` before load and assigns `mod._DECK_LANG` per boot (en / fr) | `ui/i18n.LANG`, read by `t()` at call time |
| `_DECK_LABELS`, `_t` | 124-178, 181-184 | read only (goldens hold translated text) | `ui/i18n.py` |
| `CLAUDE_STATE_DIR`, `MPV_STATE_DIR`, `TODO_TERMINALS_PATH` | 192-195, 196-199, 200-203 | computed at import from `XDG_STATE_HOME` -> set before load | `paths.py` |
| `_init_font_scale` | 984-993 | called by `MonolithTarget.boot` (main calls it at 3561, `Tiler.__init__` does not) | `STYLE.load(settings.load())` in `app.build` |
| `_FONT_PATH` loop | 1463-1467 | real `os.path.isfile` at import; harmless: `ImageFont.truetype` is stubbed (the old stub lacks it, so `_draw_layout_preview` 1443-1445 would raise when DejaVu is installed) | `ui/render.py` |
| `set_key` | 1483-1514 | **replaced** by the recorder (`mock.patch.object(mod, "set_key", rec)`): every call site is `set_key(self.deck, ...)` = module global lookup | `ui/render.set_key`, called by `Context.set_key` through `render.set_key(...)`, never `from .ui.render import set_key` |
| module `__file__` | used 1650-1651 (`_launch_todo_terminal` root), 2466-2469 (`_toggle_streaming` script) | patched to `<SANDBOX>/repo/script/stream_deck/erplibre_streamdeck.py` (a fake tree with `script/todo/todo.py`, `.venv.erplibre/bin/activate`, `script/stream_deck/translator_stream.py`) | `paths.REPO_ROOT`, `paths.STREAM_DECK_DIR` read at call time (`paths.REPO_ROOT`, not a from-import copy) |
| `_label_for_timer` | 3546-3555 | pure, called by renders | timers plugin |
| `main` | 3558-3614 | **not** called; `MonolithTarget.boot` mirrors it: `_init_font_scale()` then `Tiler(deck)` then `render()`, skipping main's second `_check_dbus_available` (3574, the spec drops it) | `app.build(deck, plugins_off=(), user_dir=...)` |

## 2. Tiler entry points the harness drives (and their effects)

| Method | Lines | Harness use | Reads/writes |
|---|---|---|---|
| `__init__` | 1518-1595 | `boot` | `deck.key_layout`; `_load_todo_terminals` (file); `_check_dbus_available` (gdbus introspect) 1545; `time.monotonic` 1546; 3 translator detects 1559-1566; `_settings_load` 1575 (translator restore 1575-1593); `_compute_idle_buttons` 1595 |
| `handle_key` | 1971-2012 | `press(key)` = `handle_key(k, True)` then `handle_key(k, False)` | ignores release 1972; flash lockout via `time.monotonic` 1976-1978; `last_press_key` 1983 |
| `render` | 2692-2703 | after boot, `goto` | flash overlay 2696-2701 (`time.monotonic`) |
| `loop` | 3467-3543 | `loop(n)`: `FakeDeck.is_open()` lets n passes through; `time.sleep(0.3)` 3543 advances the fake clock | locals `last_timer_refresh`, `last_idle_refresh` = 0 at **each call** (3469-3470) |
| `_recheck_dbus` | 3455-3465 | through `loop` | gdbus introspect every `DBUS_RECHECK_SEC` (551) |
| attribute `mode` | 1530 | `page()` | page id string |
| seeds for `goto` | see §3 | `goto(page, **seed)` sets the attribute then `mode` then `render()` | — |

## 3. State the harness seeds (`goto`) — monolith attribute -> package state

Used only where a page cannot be reached by presses at a geometry (e.g.
DECK TOO SMALL pages at 3x2), or to pin a state directly.

| Seed | Monolith attr, init line | Init value | Package (`kernel.state(<plugin>)`) |
|---|---|---|---|
| `tiling corner1` | `corner1` 1531 | `None` | `tiling.corner1` |
| `claude_session sid` | `_claude_session_sid` 1536 | `None` | `claude_sessions.sid` |
| `mpv_session pid` | `_mpv_session_pid` 1537 | `None` | `mpv_sessions.pid` |
| `todo_session window_id` | `_todo_session_window_id` 1538 | `None` | `todo_terminals.window_id` |
| `layout_delete_confirm slot` | `layout_delete_pending` 1557 | `None` | `layouts.pending` |
| (not seeded; reached by presses) `timers`, `timer_key_map`, `_dashboard_hidden_timer_ids`, `_record_proc`, `_streaming_proc`, indexes | 1548, 1550, 1555, 1569, 1573, 1560-1568 | `[]`, `{}`, `set()`, `None`, `0` | owned by their plugins |

The package names in the last column are proposals; each plugin commit
fills `PackageTarget.SEEDS` with its real names.

## 4. Scenarios per page (what gets frozen), geometries 3x2 4x2 5x3 8x4

Geometry facts (computed by the draft against the monolith, not guessed):

| | 3x2 (Mini) | 4x2 (Plus/Neo) | 5x3 (Original/MK.2) | 8x4 (XL) |
|---|---|---|---|---|
| home buttons | TILE 0, TIMER 1, DEV 2 | + SOUND 3 | TILE..LAYOUT 0-4, A11Y 5, BT 6, TRANSL 7, TODO 8 (overflow row 1, rows>=3) | TILE..TRANSL 0-7, TODO 8 |
| mic fixture | 3 | 4 | 10 | 24 |
| layout shortcuts | none (no LAYOUT) | none | none (4+3 > 5) | 28, 29, 30 |
| dashboard pool | 4, 5 | 5, 6, 7 | 9, 11-14 | 9-23, 25-27, 31 |
| sound / layout / a11y / bt / translator pages | unreachable by press | sound reachable -> DECK TOO SMALL (rows<3) | all full | all full; layout delete row (rows>=4); translator history key (cols>=7) |
| timer list slots `range(1, total-5)` (2684) | none (CLEAN DASH sits on key 1) | 1, 2 | 1-9 | 1-26 |

Worlds (fixed inputs; each golden's `inputs` names one): `EMPTY` (D-Bus ok,
nothing running, wpctl `rc=1`, bluetooth off), `FULL` (1 mpv pid 1, 1-2
Claude sessions with each status, 3 timers 2 running, 1-2 TODO terminals,
layout slot 1 filled, sink 40 %, source muted, `wpctl status` with 2 sinks
1 source, bluetooth powered 2 paired 1 connected), `NOEXT` (introspect
without `TileWindow`). All names, MACs (`00:00:5E:00:53:xx`, the
documentation range), titles invented.

| Golden (`test/fixtures/erplibre_streamdeck/<name>.json`) | Steps | Pins |
|---|---|---|
| `home__empty`, `home__full`, `home__full_fr` | boot, loop 1 | allocation, dashboard order mpv/claude/timers/todo (3006-3099), mic face (3101-3111), shortcut `*\nN` |
| `home__noext` | boot, loop 18 with `on_poll` flipping introspect at ~5 s | "NO EXT" never shows while TILE holds key 0 (trap 9), recheck cadence 5 s |
| `flash` | press DEV (HotReload ok), press within 0.5 s (ignored), loop 2 | overlay on key+4 neighbours (2735-2764), lockout 1976-1978, expiry render 3479-3482 |
| `tiling__select`, `tiling__timeout` | TILE, corner, corner (TileWindow argv); TILE, corner, loop 18 | 2225-2254, 3483-3494 |
| `timer_list__*` | TIMER, toggle, loop 7, CLEAN DASH, NEW, EXPT CSV (zenity -> sandbox path), RESET ALL -> confirm -> OK / CANCEL | 2256-2302, 2640-2688, 3395-3453, 3495-3500 |
| `sound__*` | SOUND, each of 8 keys, goto at 3x2 | 2609-2638, 3334-3378, 843-953 |
| `layout__*` | LAYOUT, SAVE 1, LOAD 1/2, DEL 1 -> confirm (8x4), home shortcut (8x4) | 2304-2362, 3113-3178, 1059-1089, preview ops 1411-1445 |
| `a11y` | A11Y, FONT+ x2, FONT-, RESET, LABELS | 2587-2607, 3302-3332, settings.json writes 996-1010 |
| `bluetooth__on`, `__off`, `__na` | BT, toggle, device keys; `which` without bluetoothctl -> rfkill path | 2556-2585, 3261-3300, 703-815 |
| `translator__*` | TRANSL, REC, STOP, `run_threads`, STT/OUT/LLM cycles, STR on/off, BACK while recording; VAD: call `TRANSLATOR.on_silence()` then loop 1; timeout: `TRANSLATOR.timeout=1`, loop 4 | 2365-2554, 3197-3259, 3532-3542 |
| `translator_history` | goto (or key at 8x4), entry, CLEAR | 2427-2446, 3180-3195 |
| `claude_session__*` | tap dashboard tile, FOCUS / ACCEPT / SET WIN / KILL (check_output), notification text variant | 2083-2125, 2950-2997, 1792-1817 |
| `mpv_session` | tap tile, PLAY/QUIT/VOL- /VOL+ | 2014-2081, 2916-2948 |
| `todo_session__menu`, `__numpad`, `__closed` | tap tile; log with `[N] label` block vs none; ENTER, FOCUS, item, FORGET; loop with ListWindows lacking the id | 2766-2914, 3501-3515, 353-391 |
| `todo_launch__*` | TODO, loop 5 (capture at +1 s), variants without `script`, without any terminal | 1643-1761, 3522-3526 |

Every golden step stores `{do, page, screen, effects, files}`; see §6.

## 5. Home contributions

Not owned by this domain. The harness pins them through `home__*`
goldens and adds a package-only test for the deliberate change (trap 3).

## 6. External effects, per page, and the cheapest seam

One global seam covers almost everything, for **both** implementations:
`mock.patch("subprocess.run")`, `("subprocess.check_output")`,
`("subprocess.Popen")`, `("shutil.which")`, `("time.monotonic")`,
`("time.time")`, `("time.sleep")`, `mock.patch.object(threading, "Thread")`,
`mock.patch.object(tempfile, "tempdir")`. It works because every call site
does `module.attr(...)`; the package must keep that (no `from subprocess
import run`, no `clock=time.monotonic` default argument — see trap 6).

| Page / path | Effect (argv / call) | Lines | Seam |
|---|---|---|---|
| boot | `gdbus introspect --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Extensions/ERPLibreHome` | 577-590 via 1545 | subprocess.run |
| boot | read `todo_terminals.json`, `settings.json`; translator detects | 236-248, 970-975, 1559-1566 | sandbox files; translator stub |
| any | `time.monotonic` | 1546, 1976, 2697, 3471 and every flash | fake clock |
| loop | `time.sleep(0.3)` | 3543 | fake clock (advances) |
| loop | `deck.is_open()` | 3470 | `FakeDeck.polls` + `on_poll` hook |
| home render | `wpctl get-volume @DEFAULT_AUDIO_SOURCE@` (always, even without mic key) | 3006 -> 822-840 | run |
| home render | read `layouts.json` (only when shortcut keys exist), `os.listdir` of mpv/claude dirs + `/proc/<pid>` | 3001-3005, 3008-3009, 208-233, 394-437 | sandbox; pid 1 (alive), 0 (no check), 4194304 (never alive: pids are < pid_max <= 2^22) |
| home loop (2 s) | `gdbus ListTrackerTimers`, `gdbus ListWindows` (+ write `todo_terminals.json` when pruned) | 3527-3531 -> 611-632, 263-291, 1742-1761 | run; sandbox |
| home tap DEV | `gdbus HotReload` | 1092-1114 | run |
| home tap mic | `wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle` | 2157-2160 | run |
| home tap shortcut | read layouts, `gdbus ApplyLayout '<json>'` -> `(N,)` | 2161-2173, 1035-1056 | run |
| home tap TODO | `which script/gnome-terminal/kgx/xterm`; `os.path.exists` of todo.py/venv under the fake repo; `os.makedirs(<STATE>/erplibre-home/todo)`; `Popen(["gnome-terminal","--working-directory",<REPO>,"--","bash","-lc","script -fqc ... todo-<int(time.time())>.log"])` | 1643-1709 | which, Popen, `__file__`, time.time |
| home loop capture | `gdbus GetFocusedWindowId`, `gdbus ListWindows`, write `todo_terminals.json` (`opened_at=time.time()`) | 1711-1740, 3522-3526 | run, time.time |
| tiling | `gdbus TileWindow <cols> <rows> c1 r1 c2 r2` | 554-574 | run |
| timer list | `gdbus ListTrackerTimers` / `ToggleTrackerTimer <id>` / `AddTrackerTimer` / `ResetAllTrackerTimers`; `zenity --file-selection --save --confirm-overwrite --file-filter=CSV files \| *.csv --filename=timers.csv`; CSV write to the returned path | 611-700, 1117-1160 | run, which; answer zenity with a sandbox path, check the CSV text in the scenario |
| sound | `wpctl get-volume SINK/SOURCE`, `wpctl status` x2, `wpctl set-volume --limit 1.5 <target> 5%+/-`, `set-mute <target> toggle`, `set-default <id>` | 822-953 | run |
| bluetooth | `bluetoothctl show`, `devices Paired`, `devices Connected`, `power on/off`, `connect/disconnect <mac>`; `rfkill list bluetooth`, `rfkill block/unblock bluetooth` | 703-815 | run, which |
| a11y | settings.json read/write | 996-1010 | sandbox |
| layout | `gdbus ListWindows`; `datetime.now().strftime("%H:%M")`; write/read layouts.json; `gdbus ApplyLayout` | 1013-1089 | run; `saved_at` normalized to `<T>` |
| translator | `tempfile.mkstemp(prefix="sttrec_")`, `translator.*` calls, `Popen([sys.executable, <STREAM_DECK_DIR>/translator_stream.py])`, `poll/terminate/wait/kill`, `threading.Thread(target=_finish_transcription)` which takes `self.lock`; settings.json writes | 2365-2554 | tempfile.tempdir -> sandbox, translator stub, Popen, FakeThread queue run by `run_threads()` outside the lock |
| translator loop | `recording_timeout_seconds()`, `_vad_should_stop` | 3532-3542 | translator stub (`timeout`, `on_silence`) |
| translator history | `load_history`, `clear_history`, `output_text` | 2427-2446, 3180-3195 | translator stub |
| claude session | `check_output(["gdbus",...,"<Method>", sid], stderr=STDOUT, timeout=2)` for Focus/Accept/SetClaudeSessionWindow/KillClaudeSession | 1792-1817 | check_output (bytes; rc != 0 -> `CalledProcessError`) |
| mpv session | `check_output([... "MpvSendCommand", str(pid), cmd])` | 2053-2081 | check_output |
| todo session | read log tail (`log_path` in registry, 8192 bytes); `gdbus SendKeysToWindow <wid> <text>`; `gdbus FocusWindowById <wid>`; loop 1 s: reload registry + `ListWindows` | 353-391, 2846-2914, 3501-3515 | sandbox log file; run |
| stdout/stderr | `print(..., file=sys.stderr)` everywhere, `_flag_err` 1763-1770 | — | `redirect_stderr/stdout` into `Harness.journal`; NOT golden (the package prefixes the plugin id) |

`FakeProcesses` writes each call as one effect line: `gdbus <Method> <args>`
after checking dest/path/interface (so `check_output` and `run` give the
same line, and a unified `dbus.py` keeps parity), `popen [json argv]`, or the
shell-quoted argv. Unknown lines are recorded in `unknown` with rc 127;
`Harness.check_clean(test)` asserts the list is empty (tearDown), since the
monolith swallows exceptions in every backend.

## 7. Draft helper `test/streamdeck_stubs.py` (79 col, run against the monolith)

Usage, as the scenario file would write it:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402


class Scenarios:
    """Mixed into one TestCase per target."""

    def run_all(self, world, script):
        runs = {}
        for cols, rows in S.GEOMETRIES:
            with S.Harness(self.make_target(), cols, rows) as h:
                world(h)
                h.boot()
                script(h)
                h.check_clean(self)
                runs[f"{cols}x{rows}"] = h.steps
        return runs

    def test_home_full(self):
        S.check_golden(self, "home__full", "FULL",
                       self.run_all(full_world, lambda h: h.loop(1)))


@unittest.skipUnless(S.MONOLITH.exists(), "single file gone")
class MonolithPages(Scenarios, unittest.TestCase):
    target_kind = "monolith"
    make_target = staticmethod(S.MonolithTarget)


@unittest.skipUnless((S.PACKAGE / "app.py").exists(), "no package yet")
class PackagePages(Scenarios, unittest.TestCase):
    target_kind = "package"
    make_target = staticmethod(S.PackageTarget)
```

A package scenario whose page has no plugin yet is skipped with
`if not target.has_page(page): self.skipTest(...)` after boot.

Golden format (written with `indent=1, sort_keys=True, ensure_ascii=False`,
trailing newline; ~24 kB for 4 steps x 4 geometries):

```json
{"format": 1,
 "inputs": "FULL: 1 mpv, 1 claude awaiting_stop, 3 timers (2 running), ...",
 "geometries": {"3x2": [
   {"do": "boot", "page": "idle",
    "screen": [["0050a0", "TILE", "tile"], ["783c00", "TIMER", "timer"],
               ["009650", "", null, [["rectangle", [7.11, 2.0, 88.89, 94.0],
                 {"fill": [60, 90, 130], "outline": [220, 220, 220],
                  "width": 1}], ["text", [3, 1], "1",
                 {"fill": [255, 220, 0], "font": 14}]]]],
    "effects": ["gdbus introspect", "wpctl get-volume @DEFAULT_AUDIO_SOURCE@"],
    "files": {"CONFIG/erplibre-home/layouts.json": {"slots": {"1": "..."}}}}
 ]}}
```

- `screen[k]` = last face painted on key k (cumulative across steps): a
  key the package forgets to repaint shows a stale face, so it is caught.
  Paint order is not compared (the flash overlay repaints after the page).
- 4th element only when `extra_draw` was given: its draw ops on a
  `FakeDraw` at the deck's key size.
- `effects` sorted (order of independent reads is invisible on the deck);
  `files` = parsed JSON of settings/layouts/todo_terminals after the step,
  `saved_at` -> `<T>`, floats rounded to 3 places, sandbox -> `<SANDBOX>`,
  fake repo -> `<REPO>`, `sys.executable` -> `<PYTHON>`, wav -> `sttrec_<X>.wav`.
- Regeneration: `STREAMDECK_GOLDEN=update` rewrites, **refused unless the
  target is the monolith** (`check_golden` fails otherwise). After the
  switch commit the goldens are frozen; a later deliberate change edits
  the JSON by hand or adds a second value (`update-from-package`) then.
- Missing golden without the variable -> explicit failure naming the
  command, never a silent pass.

Real Stream Deck layouts (python-elgato-streamdeck `KEY_COLS x KEY_ROWS`,
key pixels; from the library's device classes as I know them, the library
is not installed here to re-check): Mini / Mini MK.2 3x2, 80 px; Original,
Original V2, MK.2 5x3, 72 px; XL / XL V2 8x4, 96 px; Plus 4x2, 120 px (+4
dials, touch strip); Neo 4x2, 96 px (+2 touch keys); Pedal 3x1, **not
visual** (`main` exits 3). The spec's four geometries are exactly the
visual families. (Stream Deck Studio exists in recent library versions;
its layout is unverified — not needed.)

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Test harness of the Stream Deck deck program.

Installs stub `PIL`, `StreamDeck` and `translator` modules, loads the deck
program either as the single file `erplibre_streamdeck.py` (the reference
the goldens come from) or as the package `erplibre_streamdeck/`, and drives
it on a `FakeDeck` with every outside effect replaced:

- `subprocess.run`, `subprocess.check_output` and `subprocess.Popen` answer
  from a `FakeProcesses` table and record each call as one effect line;
  a command the table does not know is recorded in `unknown` and gets
  return code 127, so nothing reaches the host;
- `shutil.which` answers from a set of command names;
- `time.monotonic`, `time.time` and `time.sleep` read and advance a
  `FakeClock`, so flashes, ticks and timeouts are exact;
- HOME, XDG_CONFIG_HOME and XDG_STATE_HOME point into a sandbox created
  once per process, BEFORE the deck program is loaded: the single file
  computes its paths at import.

The patches are global (module attributes of `subprocess`, `shutil`,
`time`), so both implementations see them as long as they call
`subprocess.run(...)`, never a name copied by `from subprocess import`.

Without the `test_` prefix, the unit runner does not take this module for
a test file.
"""

import atexit
import contextlib
import importlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DECK_DIR = ROOT / "script" / "stream_deck"
MONOLITH = DECK_DIR / "erplibre_streamdeck.py"
PACKAGE = DECK_DIR / "erplibre_streamdeck"
GOLDEN_DIR = ROOT / "test" / "fixtures" / "erplibre_streamdeck"
# STREAMDECK_GOLDEN=update rewrites the goldens. Only the single file may
# write them: they pin what the deck showed BEFORE the move.
GOLDEN_ENV = "STREAMDECK_GOLDEN"
# Module name of the single file: never "erplibre_streamdeck", which is
# the package's name once both exist side by side.
MONOLITH_NAME = "erplibre_streamdeck_monolith"

# (cols, rows) -> key side in pixels. key_layout() answers (rows, cols).
# 3x2 Mini, 4x2 Plus (the Neo has 96 px keys), 5x3 Original and MK.2,
# 8x4 XL.
GEOMETRIES = {(3, 2): 80, (4, 2): 120, (5, 3): 72, (8, 4): 96}

DBUS_DEST = "org.gnome.Shell"
DBUS_PATH = "/org/gnome/Shell/Extensions/ERPLibreHome"
DBUS_IFACE = "org.gnome.Shell.Extensions.ERPLibreHome"

SANDBOX = None
HOME = CONFIG = STATE = FAKE_REPO = None
_LANG = "en_US.UTF-8"


# ---------------------------------------------------------------- sandbox


def _sandbox():
    """Create the per-process sandbox and point the user directories at
    it. Idempotent; the sandbox is removed at exit."""
    global SANDBOX, HOME, CONFIG, STATE, FAKE_REPO
    if SANDBOX is not None:
        return
    SANDBOX = Path(tempfile.mkdtemp(prefix="streamdeck_sandbox."))
    atexit.register(shutil.rmtree, SANDBOX, True)
    HOME = SANDBOX / "home"
    CONFIG = HOME / ".config"
    STATE = HOME / ".local" / "state"
    FAKE_REPO = SANDBOX / "repo"
    os.environ.update(
        HOME=str(HOME),
        XDG_CONFIG_HOME=str(CONFIG),
        XDG_STATE_HOME=str(STATE),
        LANG=_LANG,
    )
    wipe()


def wipe():
    """Empty the user directories and rebuild the fake repository the
    TODO launcher and the streaming translator resolve their paths in."""
    for path in (HOME, FAKE_REPO, SANDBOX / "tmp"):
        shutil.rmtree(path, ignore_errors=True)
    for path in (
        SANDBOX / "tmp",
        CONFIG / "erplibre-home",
        STATE / "erplibre-home",
        FAKE_REPO / "script" / "todo",
        FAKE_REPO / "script" / "stream_deck",
        FAKE_REPO / ".venv.erplibre" / "bin",
    ):
        path.mkdir(parents=True, exist_ok=True)
    for name in (
        "script/todo/todo.py",
        "script/stream_deck/translator_stream.py",
        ".venv.erplibre/bin/activate",
    ):
        (FAKE_REPO / name).write_text("", encoding="utf-8")


def normalize(text):
    """Replace the run-dependent parts of an effect line or a path."""
    text = str(text)
    if SANDBOX is not None:
        text = text.replace(str(FAKE_REPO), "<REPO>")
        text = text.replace(str(SANDBOX), "<SANDBOX>")
    text = text.replace(sys.executable, "<PYTHON>")
    return re.sub(r"sttrec_\w+\.wav", "sttrec_<X>.wav", text)


# ------------------------------------------------------------------ stubs


class FakeFont:
    def __init__(self, size):
        self.size = size


class FakeImage:
    """What Image.new returns: the key colour and the draw operations."""

    def __init__(self, mode, size, color=0):
        self.mode, self.size, self.color = mode, tuple(size), color
        self.ops = []


def _round(value):
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def _round3(data):
    """Round the floats of a JSON document: clock sums are inexact."""
    if isinstance(data, float):
        return round(data, 3)
    if isinstance(data, list):
        return [_round3(v) for v in data]
    if isinstance(data, dict):
        return {k: _round3(v) for k, v in data.items()}
    return data


class FakeDraw:
    """ImageDraw.Draw: records every call as [name, args..., {kwargs}].
    Fonts are recorded by size; textbbox answers a box proportional to
    the text, enough for the centring arithmetic of set_key."""

    def __init__(self, image=None):
        self.ops = image.ops if image is not None else []

    def textbbox(self, xy, text, font=None, **kw):
        size = getattr(font, "size", 10)
        lines = str(text).split("\n")
        width = max(len(line) for line in lines) * size * 0.6
        return (0, 0, int(width), int(size * 1.2 * len(lines)))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def record(*args, **kw):
            if isinstance(kw.get("font"), FakeFont):
                kw["font"] = kw["font"].size
            op = [name] + [_round(a) for a in args]
            if kw:
                op.append({k: _round(v) for k, v in sorted(kw.items())})
            self.ops.append(op)

        return record


class TransportError(Exception):
    pass


DEVICES = []  # what DeviceManager().enumerate() answers


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_pil():
    image = _module("PIL.Image", new=FakeImage)
    draw = _module("PIL.ImageDraw", Draw=FakeDraw)
    font = _module(
        "PIL.ImageFont",
        truetype=lambda path, size, *a, **kw: FakeFont(size),
        load_default=lambda size=None: FakeFont(size or 10),
    )
    _module("PIL", Image=image, ImageDraw=draw, ImageFont=font)


def _install_streamdeck():
    class DeviceManager:
        def enumerate(self):
            return list(DEVICES)

    pilhelper = _module(
        "StreamDeck.ImageHelpers.PILHelper",
        to_native_key_format=lambda deck, image: image,
        create_image=lambda deck, background="black": FakeImage(
            "RGB", deck.key_image_format()["size"], background
        ),
    )
    helpers = _module("StreamDeck.ImageHelpers", PILHelper=pilhelper)
    devmgr = _module("StreamDeck.DeviceManager", DeviceManager=DeviceManager)
    transport_t = _module(
        "StreamDeck.Transport.Transport", TransportError=TransportError
    )
    transport = _module("StreamDeck.Transport", Transport=transport_t)
    _module(
        "StreamDeck",
        DeviceManager=devmgr,
        ImageHelpers=helpers,
        Transport=transport,
    )


class FakeBackend:
    """An STT or LLM backend: a name, and a fixed transcription."""

    def __init__(self, name, text="bonjour le monde"):
        self.name, self.text = name, text

    def transcribe(self, path):
        TRANSLATOR.calls.append(f"transcribe {self.name}")
        return self.text


class TranslatorScript:
    """The answers of the stub `translator` module, reset per test."""

    def __init__(self):
        self.stt = [FakeBackend("whisper.cpp"), FakeBackend("vosk")]
        self.outputs = ["type", "clip"]
        self.llm = [FakeBackend("ollama")]
        self.history = []
        self.vad = False
        self.timeout = 30
        self.record_ok = True
        self.on_silence = None  # what start_recording_vad was handed
        self.calls = []


TRANSLATOR = TranslatorScript()


def _install_translator():
    t = TRANSLATOR

    def log(name, *args):
        t.calls.append(normalize(" ".join([name] + [str(a) for a in args])))

    def start_recording(path, recorder=None):
        log("start_recording", path)
        return FakePopen(["arecord", path]) if t.record_ok else None

    def start_recording_vad(path, on_silence):
        log("start_recording_vad", path)
        t.on_silence = on_silence
        return FakePopen(["arecord", path]) if t.record_ok else None

    def output_text(text, method):
        log("output_text", repr(text), method)
        return True

    _module(
        "translator",
        OUTPUT_TYPE="type",
        OUTPUT_CLIP="clip",
        LLM_MODE_OFF="off",
        LLM_MODE_TRANSLATE="translate",
        LLM_MODE_CHAT="chat",
        LLM_MODES=["off", "translate", "chat"],
        detect_stt_backends=lambda: list(t.stt),
        detect_output_methods=lambda: list(t.outputs),
        detect_llm_backends=lambda: list(t.llm),
        load_history=lambda: list(t.history),
        clear_history=lambda: (log("clear_history"), t.history.clear()),
        output_text=output_text,
        vad_enabled=lambda: t.vad,
        start_recording=start_recording,
        start_recording_vad=start_recording_vad,
        stop_recording=lambda proc, timeout=3: log("stop_recording"),
        recording_timeout_seconds=lambda: t.timeout,
        llm_postprocess=lambda text, mode, backend: text,
        append_history=lambda text, **kw: log("append_history", repr(text)),
        stt_language=lambda: "fr",
        focused_window_class=lambda: "terminal",
    )


_INSTALLED = False


def install():
    """Sandbox first, then the stub modules, forced: the venv may hold
    the real Pillow, and a real one would make the run depend on fonts."""
    global _INSTALLED
    _sandbox()
    if _INSTALLED:
        return
    _install_pil()
    _install_streamdeck()
    _install_translator()
    if str(DECK_DIR) not in sys.path:
        sys.path.insert(0, str(DECK_DIR))
    _INSTALLED = True


def load_monolith():
    """erplibre_streamdeck.py, loaded by path under MONOLITH_NAME."""
    install()
    if MONOLITH_NAME in sys.modules:
        return sys.modules[MONOLITH_NAME]
    spec = importlib.util.spec_from_file_location(MONOLITH_NAME, MONOLITH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MONOLITH_NAME] = module
    spec.loader.exec_module(module)
    return module


def load_package():
    """The package's app module. The package has an __init__.py: without
    it, the sibling erplibre_streamdeck.py shadows the directory."""
    install()
    return importlib.import_module("erplibre_streamdeck.app")


# ------------------------------------------------------------- the world


class FakeClock:
    def __init__(self, monotonic=1000.0, wall=1_800_000_000.0):
        self.now, self.wall = monotonic, wall

    def monotonic(self):
        return self.now

    def time(self):
        return self.wall

    def sleep(self, seconds):
        self.advance(seconds)

    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds


class FakePopen:
    def __init__(self, argv, **kw):
        self.args = list(argv)
        self.returncode = None
        self.pid = 4194304

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def gvariant_string(payload):
    """gdbus's printing of a ('s',) answer."""
    text = payload.replace("\\", "\\\\").replace("'", "\\'")
    return f"('{text}',)\n"


class FakeProcesses:
    """Answers commands by the longest matching prefix of their effect
    line. A gdbus line is "gdbus <Method> <args...>", once its
    destination, path and interface are checked; any other command is
    its shell-quoted argv."""

    def __init__(self):
        self.answers = {}
        self.calls = []
        self.unknown = []
        self.popens = []

    def answer(self, prefix, stdout="", returncode=0):
        self.answers[prefix] = (returncode, stdout)

    def line(self, argv):
        argv = [str(a) for a in argv]
        if argv[:1] != ["gdbus"]:
            return normalize(shlex.join(argv))
        ok = (
            argv[argv.index("--dest") + 1] == DBUS_DEST
            and argv[argv.index("--object-path") + 1] == DBUS_PATH
        )
        if "--method" in argv:
            at = argv.index("--method") + 1
            iface, _, method = argv[at].rpartition(".")
            ok = ok and iface == DBUS_IFACE
            words = [method] + argv[at + 1 :]
        else:
            words = [argv[1]]
        if not ok:
            self.unknown.append(shlex.join(argv))
        return normalize("gdbus " + shlex.join(words))

    def _lookup(self, line):
        self.calls.append(line)
        for prefix in sorted(self.answers, key=len, reverse=True):
            if line == prefix or line.startswith(prefix + " "):
                return self.answers[prefix]
        self.unknown.append(line)
        return 127, ""

    def run(self, argv, capture_output=False, text=False, **kw):
        code, out = self._lookup(self.line(argv))
        if not text:
            out = out.encode()
        empty = "" if text else b""
        return subprocess.CompletedProcess(argv, code, out, empty)

    def check_output(self, argv, **kw):
        code, out = self._lookup(self.line(argv))
        if code:
            raise subprocess.CalledProcessError(code, argv, out.encode())
        return out.encode()

    def popen(self, argv, **kw):
        words = [normalize(a) for a in argv]
        self.calls.append("popen " + json.dumps(words, ensure_ascii=False))
        proc = FakePopen(argv)
        self.popens.append(proc)
        return proc


class FakeDeck:
    """A visual deck of `cols` x `rows` keys. `screen` holds the last face
    painted on each key; `is_open` lets `polls` loop iterations through,
    calling `on_poll` before each."""

    def __init__(self, cols, rows, pixels=72):
        self.cols, self.rows, self.pixels = cols, rows, pixels
        self.screen = {}
        self.images = []
        self.polls = 0
        self.on_poll = None
        self.callback = None

    def key_layout(self):
        return (self.rows, self.cols)

    def key_count(self):
        return self.rows * self.cols

    def key_image_format(self):
        return {
            "size": (self.pixels, self.pixels),
            "format": "JPEG",
            "flip": (False, False),
            "rotation": 0,
        }

    def is_visual(self):
        return True

    def deck_type(self):
        return f"Fake {self.cols}x{self.rows}"

    def is_open(self):
        if self.polls <= 0:
            return False
        self.polls -= 1
        if self.on_poll is not None:
            self.on_poll()
        return True

    def set_key_image(self, key, image):
        self.images.append((key, image))

    def set_key_callback(self, callback):
        self.callback = callback

    def open(self):
        pass

    def reset(self):
        pass

    def close(self):
        pass

    def set_brightness(self, percent):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def rendering(self):
        return [self.screen.get(k) for k in range(self.key_count())]


def _hex(color):
    return "%02x%02x%02x" % tuple(color)


def recorder():
    """A drop-in `set_key(deck, key, color, text, icon, extra_draw)` that
    writes [colour, text, icon(, extra ops)] into deck.screen. It also
    takes a KeyFace in place of the colour."""

    def set_key(deck, key, color, text="", icon=None, extra_draw=None):
        if hasattr(color, "color"):
            face = color
            color, text = face.color, face.text
            icon, extra_draw = face.icon, face.extra_draw
        entry = [_hex(color), text, icon]
        if extra_draw is not None:
            draw = FakeDraw()
            side = deck.key_image_format()["size"]
            extra_draw(draw, side[0], side[1])
            entry.append(draw.ops)
        deck.screen[key] = entry

    return set_key


class FakeThread:
    """threading.Thread whose start() queues the target: the test runs
    it with Harness.run_threads(), outside any lock."""

    queue = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        FakeThread.queue.append(self)

    def join(self, timeout=None):
        pass


# ---------------------------------------------------------------- targets


class MonolithTarget:
    """The single file. boot() mirrors main() minus its second D-Bus
    probe, which the package drops."""

    kind = "monolith"
    SEEDS = {
        "claude_session": {"sid": "_claude_session_sid"},
        "mpv_session": {"pid": "_mpv_session_pid"},
        "todo_session": {"window_id": "_todo_session_window_id"},
        "layout_delete_confirm": {"slot": "layout_delete_pending"},
        "tiling": {"corner1": "corner1"},
    }

    def __init__(self):
        self.mod = load_monolith()
        self.app = None

    def patches(self, set_key):
        fake_file = FAKE_REPO / "script" / "stream_deck" / MONOLITH.name
        return [
            mock.patch.object(self.mod, "set_key", set_key),
            mock.patch.object(self.mod, "__file__", str(fake_file)),
        ]

    def boot(self, deck, lang="en"):
        self.mod._DECK_LANG = lang
        self.mod._font_scale = self.mod.FONT_SCALE_DEFAULT
        self.mod._show_labels = False
        self.mod._init_font_scale()
        self.app = self.mod.Tiler(deck)

    def has_page(self, page):
        return True

    def page(self):
        return self.app.mode

    def render(self):
        self.app.render()

    def press(self, key, pressed=True):
        self.app.handle_key(key, pressed)

    def loop(self):
        self.app.loop()

    def goto(self, page, **seed):
        for name, value in seed.items():
            setattr(self.app, self.SEEDS[page][name], value)
        self.app.mode = page
        self.app.render()


class PackageTarget:
    """The package. Its names (app.build, kernel.page_id, kernel.pages,
    kernel.state, render.STYLE, i18n.LANG, paths.REPO_ROOT) are the seams
    this harness asks the package to keep, each read at call time."""

    kind = "package"
    # page id -> (plugin id, {seed name: state attribute})
    SEEDS = {
        "claude_session": ("claude_sessions", {"sid": "sid"}),
        "mpv_session": ("mpv_sessions", {"pid": "pid"}),
        "todo_session": ("todo_terminals", {"window_id": "window_id"}),
        "layout_delete_confirm": ("layouts", {"slot": "pending"}),
        "tiling": ("tiling", {"corner1": "corner1"}),
    }

    def __init__(self):
        self.app_mod = load_package()
        self.render_mod = importlib.import_module(
            "erplibre_streamdeck.ui.render"
        )
        self.i18n = importlib.import_module("erplibre_streamdeck.ui.i18n")
        self.paths = importlib.import_module("erplibre_streamdeck.paths")
        self.kernel = None

    def patches(self, set_key):
        deck_dir = FAKE_REPO / "script" / "stream_deck"
        return [
            mock.patch.object(self.render_mod, "set_key", set_key),
            mock.patch.object(self.paths, "REPO_ROOT", FAKE_REPO),
            mock.patch.object(self.paths, "STREAM_DECK_DIR", deck_dir),
        ]

    def boot(self, deck, lang="en"):
        """build() loads the plugins and makes the kernel, without the
        lock file, the signal handler or the loop thread. plugins_off is
        given: the shell read of DECK_PLUGINS_OFF is a subprocess."""
        self.i18n.LANG = lang
        style = self.render_mod.STYLE
        style.font_scale = self.render_mod.FONT_SCALE_DEFAULT
        style.show_labels = False
        user_dir = CONFIG / "erplibre-home" / "deck-plugins"
        self.kernel = self.app_mod.build(
            deck, plugins_off=(), user_dir=user_dir
        )

    def has_page(self, page):
        return page == "idle" or page in self.kernel.pages

    def page(self):
        return self.kernel.page_id

    def render(self):
        self.kernel.render()

    def press(self, key, pressed=True):
        self.kernel.handle_key(key, pressed)

    def loop(self):
        self.kernel.loop()

    def goto(self, page, **seed):
        plugin, names = self.SEEDS.get(page, (None, {}))
        for name, value in seed.items():
            setattr(self.kernel.state(plugin), names[name], value)
        self.kernel.goto(page)


# ----------------------------------------------------------------- driver


# A layout slot stamps its save with the wall clock, in HH:MM.
SAVED_AT = re.compile(r'"saved_at": "[^"]*"')
STATE_FILES = (
    "CONFIG/erplibre-home/settings.json",
    "CONFIG/erplibre-home/layouts.json",
    "STATE/erplibre-home/todo_terminals.json",
)


class Harness:
    """One scenario on one target at one geometry. Every step appends
    {do, page, screen, effects, files} to `steps`; effects are sorted,
    since the order of independent reads is not visible on the deck."""

    def __init__(self, target, cols, rows, lang="en"):
        install()
        wipe()
        self.target = target
        self.deck = FakeDeck(cols, rows, GEOMETRIES.get((cols, rows), 72))
        self.lang = lang
        self.clock = FakeClock()
        self.proc = FakeProcesses()
        self.which = {
            "bluetoothctl",
            "rfkill",
            "wpctl",
            "zenity",
            "script",
            "gnome-terminal",
        }
        self.journal = io.StringIO()
        self.steps = []
        TRANSLATOR.__init__()
        FakeThread.queue.clear()
        self._stack = contextlib.ExitStack()

    def __enter__(self):
        s = self._stack
        for p in self.target.patches(recorder()):
            s.enter_context(p)
        s.enter_context(mock.patch("subprocess.run", self.proc.run))
        s.enter_context(
            mock.patch("subprocess.check_output", self.proc.check_output)
        )
        s.enter_context(mock.patch("subprocess.Popen", self.proc.popen))
        s.enter_context(mock.patch("shutil.which", self._which))
        s.enter_context(mock.patch("time.monotonic", self.clock.monotonic))
        s.enter_context(mock.patch("time.time", self.clock.time))
        s.enter_context(mock.patch("time.sleep", self.clock.sleep))
        s.enter_context(mock.patch.object(threading, "Thread", FakeThread))
        # The recorder's wav files land in the sandbox, not in TMPDIR.
        tmp = str(SANDBOX / "tmp")
        s.enter_context(mock.patch.object(tempfile, "tempdir", tmp))
        s.enter_context(contextlib.redirect_stderr(self.journal))
        s.enter_context(contextlib.redirect_stdout(self.journal))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    def _which(self, name, *args, **kw):
        return f"/usr/bin/{name}" if name in self.which else None

    def check_clean(self, test):
        """Every command the program ran had an answer in the table."""
        test.assertEqual([], self.proc.unknown, self.journal.getvalue())

    # -- inputs

    def write_json(self, where, data):
        path = self._path(where)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _path(self, where):
        head, _, tail = where.partition("/")
        base = {"CONFIG": CONFIG, "STATE": STATE, "SANDBOX": SANDBOX}[head]
        return base / tail

    # -- steps

    def _step(self, do):
        files = {}
        for where in STATE_FILES:
            path = self._path(where)
            if path.exists():
                text = normalize(path.read_text(encoding="utf-8"))
                text = SAVED_AT.sub('"saved_at": "<T>"', text)
                files[where] = _round3(json.loads(text))
        effects = sorted(self.proc.calls + TRANSLATOR.calls)
        self.proc.calls.clear()
        TRANSLATOR.calls.clear()
        self.steps.append(
            {
                "do": do,
                "page": self.target.page(),
                "screen": self.deck.rendering(),
                "effects": effects,
                "files": files,
            }
        )

    def boot(self):
        self.target.boot(self.deck, self.lang)
        self.target.render()
        self._step("boot")
        return self

    def press(self, key):
        self.target.press(key, True)
        self.target.press(key, False)
        self._step(f"press {key}")

    def press_face(self, text):
        """Press the key whose face shows `text` (first in key order)."""
        for key, face in enumerate(self.deck.rendering()):
            if face and face[1] == text:
                return self.press(key)
        raise AssertionError(f"no key shows {text!r}")

    def wait(self, seconds):
        self.clock.advance(seconds)

    def loop(self, iterations=1, on_poll=None):
        """Run the deck loop for `iterations` passes of 0.3 s each."""
        self.deck.polls = iterations
        self.deck.on_poll = on_poll
        self.target.loop()
        self.deck.on_poll = None
        self._step(f"loop {iterations}")

    def goto(self, page, **seed):
        self.target.goto(page, **seed)
        self._step(f"goto {page}")

    def run_threads(self):
        while FakeThread.queue:
            job = FakeThread.queue.pop(0)
            job.target(*job.args, **job.kwargs)
        self._step("threads")


# ----------------------------------------------------------------- golden


def golden_path(name):
    return GOLDEN_DIR / f"{name}.json"


def check_golden(test, name, inputs, runs):
    """Compare `runs` ({"5x3": steps, ...}) to the golden `name`, or
    write it when STREAMDECK_GOLDEN=update and the target is the single
    file. `inputs` names the fixture set the reader needs."""
    path = golden_path(name)
    kind = test.target_kind
    if os.environ.get(GOLDEN_ENV) == "update":
        if kind != "monolith":
            test.fail("goldens are written from erplibre_streamdeck.py only")
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"format": 1, "inputs": inputs, "geometries": runs}
        path.write_text(
            json.dumps(body, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return
    if not path.exists():
        test.fail(f"{path.name} missing: {GOLDEN_ENV}=update on the file")
    expected = json.loads(path.read_text(encoding="utf-8"))["geometries"]
    test.assertEqual(sorted(expected), sorted(runs))
    for geometry, steps in runs.items():
        want = expected[geometry]
        test.assertEqual(
            [s["do"] for s in want], [s["do"] for s in steps], geometry
        )
        for got, ref in zip(steps, want, strict=True):
            with test.subTest(geometry=geometry, step=ref["do"]):
                test.assertEqual(ref, got)
```

## 8. Traps and how the harness keeps the screen identical

1. **The package needs `erplibre_streamdeck/__init__.py`.** Verified in a
   probe: with `script/stream_deck/` on `sys.path`, a directory WITHOUT
   `__init__.py` loses to the sibling `erplibre_streamdeck.py` (FileFinder
   returns the module, `import erplibre_streamdeck.app` ->
   `ModuleNotFoundError: 'erplibre_streamdeck' is not a package`). With an
   empty `__init__.py` the package wins. Steps 1-2 have both side by side,
   so the layout must list `__init__.py` (and `plugins/__init__.py`,
   `ui/__init__.py`).
2. **Never register the single file as `erplibre_streamdeck`.** The
   current chunks test does (`test_erplibre_streamdeck_chunks.py:27-28,
   86-88`); in the same process it would shadow the package. The helper
   loads it as `erplibre_streamdeck_monolith`.
3. **The deliberate dashboard change.** Monolith taps re-read the session
   lists (2174-2213); the package taps the last render's map. Goldens come
   from the monolith, so a scenario must never change the session lists
   between the render and the tap (true of every scenario in §4). The new
   behaviour gets a package-only test: render, add an mpv session file,
   tap the first dashboard key -> the page of what the key SHOWED.
4. **Paths at import.** 88-90 and 192-203 are computed when the module is
   loaded; `_launch_todo_terminal` reads `XDG_STATE_HOME` at call time
   (1672-1675). The helper sets HOME/XDG/LANG once per process BEFORE any
   load and wipes the sandbox per `Harness`. The package must derive the
   same paths from the same variables; `LAYOUT_DIR` uses
   `~/.config/erplibre-home` (88), not `XDG_CONFIG_HOME`: the harness sets
   `XDG_CONFIG_HOME=$HOME/.config`, so a package that switched to
   `XDG_CONFIG_HOME` would pass the goldens while changing behaviour —
   keep `expanduser("~/.config/erplibre-home")` in `paths.py` for
   settings/layouts (on-disk contract), and give that its own test.
5. **Repository-relative paths.** `__file__` 1650-1651, 2466-2469: the
   monolith's module `__file__` is patched to a fake tree, so
   `os.path.exists(script/venv)` and the argv do not depend on the
   checkout. The package must read `paths.REPO_ROOT` /
   `paths.STREAM_DECK_DIR` at call time (`paths.REPO_ROOT / ...` in the
   function body), or the patch is invisible (spec Risk 3).
6. **Bound-early names defeat the global patches.** `def __init__(...,
   clock=time.monotonic)` (as `kernel.md` drafts) binds the real clock at
   import; same for `from subprocess import run`, `from time import
   monotonic`, `dbus=dbus_mod` holding a pre-bound function. The kernel
   must call `time.monotonic()` in the body (or `app.build` must accept and
   forward `clock=`); every backend calls `subprocess.run(...)`.
7. **Loop schedule resets per `loop()` call.** `last_timer_refresh` and
   `last_idle_refresh` are locals set to 0 at entry (3469-3470): the first
   pass of every `loop()` call refreshes at once (2 s/1 s checks against
   0). A kernel keeping `_last_tick` across calls would differ the second
   time the harness calls `loop()`. Fix in the kernel: `loop()` clears its
   schedule at entry (harmless in production, where it runs once), and
   `last_*` start at 0, not `now`.
8. **Flash suppresses ticks.** 3479-3482: while `last_result` is set, the
   whole `elif` chain is skipped, expired or not (the expiry pass only
   renders and clears). Verified with the draft: a timer toggle that fails
   at t, then `loop(3)` -> no `ListTrackerTimers` until the flash expired.
   Goldens pin it; the kernel step must `return` after the flash branch.
9. **"NO EXT" is unreachable today.** 3046 `key == self.tile_key` comes
   before 3096 `key == 0 and not self.dbus_ok`, and `tile_key` is 0 for any
   deck. `home__noext` freezes TILE on key 0. The kernel's rule 4 only
   shows when the `tiling` plugin is off: a package-only test, not parity.
10. **`_init_font_scale` only in `main`** (3561): `Tiler(deck)` alone
    ignores a saved font scale. `MonolithTarget.boot` calls it first, as
    `main` does; main's second D-Bus probe (3574) is skipped because the
    spec removes it, so boot effects hold one `gdbus introspect`.
11. **Two D-Bus call styles.** `_call_claude_dbus` 1792-1817 and
    `_call_mpv_dbus` 2053-2081 use `check_output(..., stderr=STDOUT)` and
    spell dest/path/interface inline; the rest use `run(text=True)` with
    the 546-548 constants. `FakeProcesses` reduces both to `gdbus <Method>
    <args>` after checking dest/path/interface, so `dbus.py` may unify
    them without breaking parity. Timeouts are not recorded.
12. **Threads.** `_finish_transcription` (2522-2554) runs in a
    `threading.Thread` and takes `self.lock` (2550). `FakeThread` queues
    it; `Harness.run_threads()` runs it outside any lock. The harness's
    `press` calls `handle_key` without the lock (the app's key callback
    takes it, 3587-3589), so the package's `Kernel.handle_key` must not
    take the lock itself either, or `run_threads` + press would need it.
13. **`/proc/<pid>` liveness** (222-223, 410-411): fixtures use pid 1
    (always present, also in a PID namespace) for live mpv sessions, pid 0
    for Claude sessions (no check), 4194304 for a dead one (pids stay below
    `pid_max`, at most 2^22).
14. **Fonts.** `_FONT_PATH` is found at import (1463-1467) on hosts with
    DejaVu; then `_draw_layout_preview` (1443-1445) calls
    `ImageFont.truetype`, which the old stub lacks. The new stub defines
    `truetype` and `load_default(size=)`, and records fonts by size.
15. **Global mutable state across scenarios.** `_font_scale`,
    `_show_labels`, `_DECK_LANG` (98-99, 123) are reset at each boot;
    under `make streamdeck_tiler_unittest` all files share one process.
16. **Host safety.** The runner's PATH doubles do not cover gdbus, wpctl,
    bluetoothctl, zenity or terminals; HOME is the real one. Without the
    sandbox, an `a11y` press writes the real `settings.json` (996-1002).
    `check_clean` fails any scenario that ran an unanswered command.
17. **`DECK_PLUGINS_OFF` read via the shell library** (spec Loader) is a
    subprocess: `app.build(deck, plugins_off=(), user_dir=...)` takes the
    list, the shell read stays in `main`.
18. **Golden size.** ~24 kB per 4-step scenario at `indent=1`; ~30
    scenarios = under 1 MB. A writer that keeps each face on one line
    would halve it; not required.

## 9. Existing tests and files that change at the switch commit

| File | Lines | Change |
|---|---|---|
| `test/test_deck_lock.py` | 1068-1075 | read `DECK_DIR / "erplibre_streamdeck/__main__.py"`; `fonction(source, "main")` unchanged. 1075 `assertIn("\nimport deck_lock\n", source)`: `__main__.py` edits `sys.path` before importing, so flake8 E402 fires (`.flake8` selects E); a `# noqa: E402` suffix breaks this exact-substring check -> relax to `assertRegex(source, r"(?m)^import deck_lock\b")` |
| `test/test_deck_lock.py` | 1077-1088 | read `erplibre_streamdeck/app.py` for the `print("No visual Stream Deck found.")\n        sys.exit(deck_lock.NO_DECK_EXIT)` block (8-space indent holds if `app.main` keeps `if not deck:` at function level) |
| `test/test_erplibre_home_deck.py` | 158-168 (165) | expected argv `.../script/stream_deck/erplibre_streamdeck` |
| `test/test_erplibre_home_deck.py` | 170-183 (173) | `"tiler": "script/stream_deck/erplibre_streamdeck"` |
| `test/test_erplibre_home_deck.py` | 206-212 (211) | `assertNotIn("erplibre_streamdeck", ...)` |
| `test/test_erplibre_home_deck.py` | 298-329 (320, 326-329) | `chemin.is_file()` -> `chemin.is_file() or (chemin / "__main__.py").is_file()` (tiler is a directory, controller a file); exact string -> `"script/stream_deck/erplibre_streamdeck"` |
| `test/test_streamdeck_entry_points.py` | 176-195 (180) | `"streamdeck_erplibre": "erplibre_streamdeck"`; the regex `VENV_REF [^;]*fragment` still matches. Add: no `.py` after it. 171-174 alias and 186 `-m unittest` unchanged. Note `APPEL_PYTHON` (64) does not see the new recipe (no `.py`, no `python `): harmless, it has `$(STREAMDECK_PY)` |
| `test/test_streamdeck_games_layout.py` | 50-57 | optional: `voisins` lists `DECK_DIR.glob("*.py")` stems; once the file is a directory, a game importing `erplibre_streamdeck` is no longer caught — add the package directory name |
| `conf/make.streamdeck.Makefile` | 126-128 | `$(STREAMDECK_PY) script/stream_deck/erplibre_streamdeck` |
| `conf/make.streamdeck.Makefile` | 229-232 | `discover -s ./test -p "test_erplibre_streamdeck*.py" -v` (top dir = start dir, so `import streamdeck_stubs` resolves; `test/` has no `__init__.py`, so no `-t .`) |
| `script/install/erplibre_home_settings.sh` | 50 | `tiler) echo "script/stream_deck/erplibre_streamdeck" ;;` |
| `script/stream_deck/test_erplibre_streamdeck_chunks.py` | 1-280 | deleted. Its 26 tests: `RecheckDbusTest` 96-134 (3) -> `test/test_erplibre_streamdeck_kernel.py` on `Kernel.recheck_dbus` with `dbus.available` patched; `ChunkTextForCellsTest` 136-161 (5), `WrapChunkTest` 163-177 (3), `ClaudeColorTest` 179-199 (4), `ClaudeLabelTest` 201-215 (3), `WrapButtonLabelTest` 217-242 (4), `TodoMenuParseTest` 244-277 (4) -> `test/test_erplibre_streamdeck_text.py` against `ui/text.py`, `plugins/claude_sessions.py`, `plugins/todo_terminals.py` |
| `test/test_todo.py` | 1042 | unchanged, constraint: it parses every `*.py` under the repo; no package class may take a TODO mixin name |
| `script/gnome-extension/erplibre_home/lib/mpv-state.js` | 15 | doc comment names `erplibre_streamdeck.py` (spec step 5) |

## 10. Proposed test files

- `test/streamdeck_stubs.py` — the helper above (step 0).
- `test/test_erplibre_streamdeck_pages.py` — §4 scenarios, `MonolithPages`
  (step 0, writes goldens) + `PackagePages` (step 2 on, per page as plugins
  land; deleted monolith class at the switch).
- `test/test_erplibre_streamdeck_text.py` — the 23 pure tests (step 0
  against `load_monolith()`, re-pointed per plugin commit).
- `test/test_erplibre_streamdeck_kernel.py`, `_home.py`, `_loader.py`,
  `_backends.py`, `_contracts.py` — spec "Tests" bullets (step 1+).
- `test/fixtures/erplibre_streamdeck/*.json` — goldens.

## 11. Questions for the plan

1. Move the 26 chunk tests to `test/` already at step 0 (and point the
   Make target at `./test` then), instead of at the switch? It removes the
   `sys.modules["erplibre_streamdeck"]` hazard (trap 2) four steps early
   and avoids running the same tests twice. The spec says "deleted at the
   switch"; moving earlier changes no contract.
2. Is `app.build(deck, *, plugins_off, user_dir) -> Kernel` acceptable as
   the test seam (no lock, no signal, no thread)? The harness needs it.
3. Keep `LAYOUT_DIR` on `~/.config` (today) or align on `XDG_CONFIG_HOME`
   like the loader's user directory? The latter is a visible change for
   users with a custom `XDG_CONFIG_HOME` (trap 4).
