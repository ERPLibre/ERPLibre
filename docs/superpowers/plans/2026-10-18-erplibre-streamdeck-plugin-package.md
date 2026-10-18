# ERPLibre Stream Deck plugin package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3618-line `script/stream_deck/erplibre_streamdeck.py`
with the package `script/stream_deck/erplibre_streamdeck/`: a kernel plus
eleven directory-discovered plugins, user plugins, `DECK_PLUGINS_OFF`, and
per-plugin error isolation, with the deck screen unchanged.

**Architecture:** Characterization tests freeze what the single file
paints (golden JSON files) before anything moves. The package is built
next to the file, plugin by plugin, each one proved against the goldens.
One switch commit points `DECK_PROGRAM=tiler` at the package directory and
deletes the file. The setting and the docs come last.

**Tech Stack:** Python 3 (stdlib, Pillow, python-elgato-streamdeck),
bash (`erplibre_home_settings.sh`), unittest via
`./script/test/run_unit_test.sh`, mmg for the docs.

**Spec:** `docs/superpowers/specs/2026-10-18-erplibre-streamdeck-plugin-package-design.md`

**Appendices** (read-only maps of the single file at commit `b61156bf`,
line ranges verified there; they shift after Task 2, so search by name):
`docs/superpowers/plans/2026-10-18-erplibre-streamdeck-plugin-package/`
`map-kernel.md`, `map-tests.md`, `map-a11y_bt_sound.md`,
`map-layouts_tiling_reload.md`, `map-timers.md`, `map-translate.md`,
`map-todo_terminals.md`, `map-sessions.md`, and the tested harness draft
`streamdeck_stubs.draft.txt`.

## Global Constraints

- Python lines ≤ 79 columns. Never run black on a whole file (it uses 88
  and re-joins lines); format only the lines you write.
- Every new file starts with the repo header:
  `# © 2026 TechnoLibre (http://www.technolibre.ca)` and
  `# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)`.
- Comments say how the code works, in the present; no incident, date,
  machine or person (`.claude/rules/04-code-conventions.md`). Run
  `python3 script/analyse/check_comment_hygiene.py <files>` before each
  commit.
- Commit message: `[TAG] scope: subject` in English, ≤ 72 chars; body
  English, then `--- FR ---`, the French subject under the same tag, the
  French body; ≤ 8 lines per language; `Assisted-by: <model>` as the LAST
  line; no `Co-authored-by` naming an AI. Validate with
  `python3 script/git/hooks/commit-msg <file>`, commit with
  `git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F <file>`.
- Stage files by name; never `git add -A` (`private/` and `tasks/` are
  untracked on purpose).
- Docs: edit `.base.md`, then
  `source .venv.erplibre/bin/activate && mmg --yes`; never edit the
  generated `.md` / `.fr.md`. `ARCHITECTURE.md` and `DEBUG.md` of the
  extension have no `.base.md` and are edited directly.
- Full suite: `./script/test/run_unit_test.sh` (one process per
  `test/test_*.py`). One file: `./script/test/run_unit_test.sh test/<f>.py`.
- No package module named `game_*.py`; no class named like a TODO mixin
  (`test/test_todo.py` walks every `*.py`).
- Every module calls `subprocess.run(...)`, `time.monotonic()`,
  `shutil.which(...)` through the module attribute, never a name bound by
  `from x import y` or a default argument: the harness patches the
  modules `subprocess`, `time`, `shutil`, `threading`.
- Plugins import shared names from `erplibre_streamdeck.ui.*`,
  `erplibre_streamdeck.paths`, `erplibre_streamdeck.plugin`; never from
  another plugin.
- On-disk formats and D-Bus method names do not change.
  `settings.json` and `layouts.json` stay under the literal
  `~/.config/erplibre-home` (not `XDG_CONFIG_HOME`), as today.

## Spec amendments (rulings from the mapping, binding for every task)

The mapping found points the spec's interface leaves open. These rulings
complete it; Task 16 copies them into the spec's text.

1. **Flash precedence.** In a loop pass, a recorded flash (expired or not)
   blocks every tick: if expired, render (which clears it); then the pass
   ends. Ticks run only when no flash is recorded.
2. **Home refresh.** The kernel re-renders the home screen every
   `HOME_REFRESH_SEC = 2.0` on its own (the mic indicator and the
   session tiles have no tick). `home_tick(ctx, now) -> bool` returns
   true to ask for a render; the kernel renders at most once per pass.
   `home_period = 0.0` means every pass.
3. **Schedules.** Each page tick and each home tick has its own
   last-run stamp, starting at 0.0, cleared when `loop()` starts; the
   first pass runs every due tick at once, as today.
4. **One home button per plugin:** `Plugin.home_button` (singular,
   optional), not a list.
5. **Fixtures** gain `order` (sound mic 10, layouts shortcuts 20);
   `place(geo, home_keys)` gets `{plugin_id: key or -1}`; `face(ctx, key,
   index)` and `press(ctx, key, index)` get the key's index in the list
   `place` returned. A key already taken (button or earlier fixture) is
   skipped. Every placed key is reserved, even when its face is `None`
   (painted empty), and a press on it is passed to the fixture.
6. **`Page.keys` may return `None`** (deck too small). The kernel
   computes it once per page at start; `ctx.keys` gives the current
   page's value. Pages whose keys change at run time pass `keys=None`
   and compute their own.
7. **Context additions:** `ctx.page` (current page id), `ctx.keys`,
   `ctx.home_keys`, `ctx.locked()` (the kernel lock, for threads a plugin
   starts), `ctx.state()` without argument = the calling plugin's
   namespace.
8. **`ctx.flash(ok, reason=None)` only records** (and writes one journal
   line `[erplibre-home] <plugin>: <reason>` when `ok` is false and a
   reason is given). It never renders; `goto`, `home` and `render` do.
9. **`dbus.call(method, *args, timeout=3)` returns a `Reply`**
   (`returncode`, `stdout`, `stderr`; `.ok`, `.true`, `.string`) and never
   raises; parsing stays in the plugins.
10. **`Kernel.handle_key` does not take the lock**; the app's key callback
    does, as today.
11. **Test seam:** `app.build(deck, *, plugins_off=(), user_dir=None)`
    restores the style from `settings.json`, loads the plugins and returns
    the kernel, without lock file, signal handler or thread.
12. **Errors in home providers:** an `items()` that raises contributes no
    tiles this render (the next providers fill the keys); a `face` that
    raises paints its key empty.
13. **Font scale restore** is the kernel's (`app.build`), not the a11y
    plugin's: turning a11y off keeps the last chosen style.
14. **Tests that load the single file** load it as module
    `erplibre_streamdeck_monolith`, never `erplibre_streamdeck`, and the
    package has `__init__.py` files (without them the sibling `.py` file
    shadows the directory).
15. **`--list-plugins`** reports the import-level result (import, `PLUGIN`,
    `api`, duplicate page id); a `setup` failure shows only in the
    journal of a real start.

## Review Focus

1. A user plugin with a syntax error, or one whose import raises, in
   `~/.config/erplibre-home/deck-plugins/`: the deck starts, the journal
   names the file and the reason, the other plugins work (Task 7 test
   `test_broken_user_plugin_is_refused`).
2. `DECK_PLUGINS_OFF=tiling,sound` (the first home button and the mic
   owner off): the remaining buttons close up from key 0, the layout
   shortcuts follow LAYOUT, "NO EXT" shows on key 0 only when nothing
   took it (Task 6 `test_allocation_with_each_plugin_off`).
3. A Claude state file with `"pid": "abc"` read on every home render:
   one journal line, not one every 2 s; the other tiles still paint
   (Task 5 `test_repeated_failure_logged_once`, Task 12
   `test_bad_pid_file_is_skipped_or_isolated`).
4. Starting the deck as `python script/stream_deck/erplibre_streamdeck`
   from another working directory: imports and repository paths resolve
   (Task 7 `test_list_plugins_from_another_cwd`).
5. a11y saving the font scale while the translator keys are in
   `settings.json`: the translator keys survive, and the other way round
   (Task 8 `test_font_scale_save_keeps_other_keys`).

---

### Task 1: Test harness, chunk tests moved to `test/`

**Files:**
- Create: `test/streamdeck_stubs.py` (from the appendix draft)
- Create: `test/test_erplibre_streamdeck_text.py`
- Delete: `script/stream_deck/test_erplibre_streamdeck_chunks.py`
- Modify: `conf/make.streamdeck.Makefile` (target
  `streamdeck_tiler_unittest`)

**Interfaces:**
- Produces: module `streamdeck_stubs` with `install()`,
  `load_monolith()`, `load_package()`, `GEOMETRIES`, `FakeDeck`,
  `FakeClock`, `FakeProcesses`, `FakeThread`, `TRANSLATOR`, `recorder()`,
  `MonolithTarget`, `PackageTarget`, `Harness`, `check_golden(test, name,
  inputs, runs, partial=False)`, `MONOLITH`, `PACKAGE`, `REPO_PLUGINS`.

- [ ] **Step 1: Copy the harness.** Copy
  `docs/superpowers/plans/2026-10-18-erplibre-streamdeck-plugin-package/streamdeck_stubs.draft.txt`
  to `test/streamdeck_stubs.py`. Then add, after `MONOLITH_NAME`:

```python
# The plugins of the repository. The home screen of the package matches
# the goldens only once all of them load.
REPO_PLUGINS = frozenset(
    {
        "a11y", "bluetooth", "claude_sessions", "dev_reload", "layouts",
        "mpv_sessions", "sound", "timers", "tiling", "todo_terminals",
        "translate",
    }
)
```

  add to `PackageTarget`:

```python
    def complete(self):
        """Every repository plugin is loaded: the home screen can be
        compared with the goldens."""
        return REPO_PLUGINS <= {lp.id for lp in self.kernel.plugins}
```

  add to `MonolithTarget`:

```python
    def complete(self):
        return True
```

  and replace `check_golden` by this version, which compares, while the
  package is incomplete, only the steps shown on a page other than home:

```python
def check_golden(test, name, inputs, runs, partial=False):
    """Compare `runs` ({"5x3": steps, ...}) to the golden `name`, or
    write it when STREAMDECK_GOLDEN=update and the target is the single
    file. With `partial`, the boot step and every step shown on the home
    screen are left out: an incomplete package allocates the home screen
    differently, while a page repaints every key."""
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
            if partial and (ref["do"] == "boot" or ref["page"] == "idle"):
                continue
            with test.subTest(geometry=geometry, step=ref["do"]):
                test.assertEqual(ref, got)
```

- [ ] **Step 2: Move the 26 chunk tests.** Create
  `test/test_erplibre_streamdeck_text.py` with the six test classes of
  `script/stream_deck/test_erplibre_streamdeck_chunks.py`
  (`RecheckDbusTest`, `ChunkTextForCellsTest`, `WrapChunkTest`,
  `ClaudeColorTest`, `ClaudeLabelTest`, `WrapButtonLabelTest`,
  `TodoMenuParseTest`), unchanged in their assertions, with this header
  in place of the old stub block:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Pure helpers of the deck program: text cutting, Claude tile colour and
label, the TODO menu parser, the D-Bus recheck. They run against the
single file until the module that owns each helper exists."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

GT = S.load_monolith()
```

  Keep every `GT.<name>` reference as it is. Delete
  `script/stream_deck/test_erplibre_streamdeck_chunks.py` with `git rm`.

- [ ] **Step 3: Point the Make target at `test/`.** In
  `conf/make.streamdeck.Makefile`, target `streamdeck_tiler_unittest`,
  replace `discover -s ./script/stream_deck -p "test_erplibre_streamdeck*.py" -v`
  with `discover -s ./test -p "test_erplibre_streamdeck*.py" -v`. If
  `test/test_streamdeck_entry_points.py` pins that recipe text, update
  its expectation in the same commit.

- [ ] **Step 4: Run.**
  `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_text.py test/test_streamdeck_entry_points.py`
  Expected: 26 tests in the first file pass; the second passes.
  Then the full suite: `./script/test/run_unit_test.sh`, all green.

- [ ] **Step 5: Commit** `[REF] stream_deck tests: harness, chunk tests
  moved to test/` (files: the two new test files, the deleted file, the
  Makefile, and `test/test_streamdeck_entry_points.py` if touched).

### Task 2: Dead code out of the single file

**Files:**
- Modify: `script/stream_deck/erplibre_streamdeck.py`

The items are listed with evidence in `map-kernel.md` § "Dead code" and
`map-layouts_tiling_reload.md` T7. Remove exactly:

- `import urllib.error`, `import urllib.request`;
- `GALLERY_RESTART_URL`, `COLOR_ACTIVE`;
- `_wpctl_available`;
- `Tiler._enter_claude_session_mode`, `Tiler._focus_claude_for_key`;
- in `_render_claude_session`, the `or (session or {}).get('last_prompt')`
  part (the loader already folds `last_prompt` into `description`);
- in `_render_tiling`, the `preview` set and its `COLOR_PREVIEW` branch,
  then the unused constant `COLOR_PREVIEW`;
- in `_compute_sound_buttons`, the always-true `if self.cols >= 4:`
  (dedent its body).

- [ ] **Step 1:** `grep -n` each name first; each must have no use other
  than the one removed. Remove them.
- [ ] **Step 2:** `python3 -m py_compile script/stream_deck/erplibre_streamdeck.py`
  and `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_text.py test/test_deck_lock.py`.
  Expected: pass.
- [ ] **Step 3: Commit** `[REM] stream_deck: dead code of the deck program`.

### Task 3: Characterization goldens from the single file

**Files:**
- Create: `test/test_erplibre_streamdeck_pages.py`
- Create: `test/fixtures/erplibre_streamdeck/*.json` (generated)

**Interfaces:**
- Consumes: Task 1 harness.
- Produces: one scenario method per golden, run by `MonolithPages`
  (always, until Task 14) and `PackagePages` (skipped until the package
  has `app.py`; partial until complete).

The file holds world builders, the `Scenarios` mixin and the two
`TestCase` classes. Worlds (all names, titles and MAC addresses
invented; MACs in `00:00:5E:00:53:xx`, the documentation range):

- `EMPTY`: introspect lists `TileWindow`; `ListTrackerTimers` →
  `('[]',)`; `ListWindows` → `('[]',)`; `wpctl get-volume` rc 1;
  `bluetoothctl show` → `Powered: no`; no state files.
- `FULL`: one mpv session file (pid 1, title `Demo stream`); two Claude
  session files (pid 0, statuses `awaiting_stop` and `working`, one
  with `notification_message`); tracker timers: 3, 2 running; one TODO
  terminal in `todo_terminals.json` with a log whose tail holds a
  `[1] First\n[2] Second` menu; layout slot 1 filled; sink 40 %,
  source muted; `wpctl status` with 2 sinks and 1 source;
  `bluetoothctl` powered, 2 paired, 1 connected.
- `NOEXT`: introspect without `TileWindow`.

Every page scenario REACHES ITS PAGE WITH `h.goto(page, **seed)` right
after boot (never by a home press), so the package can be compared
before its home screen is complete. Home-to-page transitions are pinned
by the `home__*` scenarios.

| Golden | Steps after `boot` (each step recorded) |
|---|---|
| `home__empty` (EMPTY) | `loop(1)` |
| `home__full` (FULL) | `loop(1)`, `wait(2.1)`, `loop(1)` |
| `home__full_fr` (FULL, lang `fr`) | `loop(1)` |
| `home__noext` (NOEXT) | `loop(18)` with `on_poll` switching introspect to OK after 5 s |
| `home__presses` (FULL) | press each home button key in turn by `press_face` of its label, then `goto("idle")`; press the mic key; press the shortcut key at 8x4 |
| `flash` (FULL) | press DEV RELOAD (HotReload answers `('reloaded',)`: success is exit 0 and a non-empty string), press it again within 0.5 s, `wait(0.6)`, `loop(2)` |
| `tiling__select` (EMPTY) | `goto("tiling")`, press corner 0, press the last key (TileWindow → `(true,)`) |
| `tiling__timeout` (EMPTY) | `goto("tiling")`, press 0, `wait(5.1)`, `loop(1)` |
| `timer_list__actions` (FULL) | `goto("timer_list")`, press the first timer key (toggle), `loop(7)`, press CLEAN, press NEW, press EXPT (zenity answers a sandbox path), press RESET ALL, press OK; again RESET ALL then CANCEL |
| `sound__actions` (FULL) | `goto("sound")`, press each of its keys once |
| `layout__actions` (FULL) | `goto("layout")`, SAVE 1, LOAD 1, LOAD 2, DEL 1, then on the confirm page OK |
| `a11y__actions` (EMPTY) | `goto("a11y")`, FONT+, FONT+, FONT-, RESET, LABELS |
| `bluetooth__on` / `__off` / `__na` | `goto("bluetooth")`, toggle, each device key; `__na` with `bluetoothctl` absent from `which` |
| `translator__record` (EMPTY) | `goto("translator")`, REC, STOP, `run_threads()`, cycle STT, OUT, LLM, LLM mode, STR on, STR off |
| `translator__vad_timeout` (EMPTY) | `goto("translator")`, REC with `TRANSLATOR.vad=True`, call `TRANSLATOR.on_silence()`, `loop(1)`; REC, `TRANSLATOR.timeout=1`, `wait(1.1)`, `loop(1)` |
| `translator_history` (EMPTY, history of 2 entries) | `goto("translator_history")`, press the first entry, CLEAR |
| `claude_session__actions` (FULL) | `goto("claude_session", sid=<first sid>)`, FOCUS; again ACCEPT; SET WIN; KILL |
| `mpv_session__actions` (FULL) | `goto("mpv_session", pid=1)`, each action key |
| `todo_session__menu` (FULL) | `goto("todo_session", window_id=<id>)`, press item 1, ENTER, FOCUS, `loop(4)`, FORGET |
| `todo_session__closed` (FULL) | `goto("todo_session", window_id=<id>)`, ListWindows without the id, `loop(4)` |
| `todo_launch` (EMPTY) | press the TODO home key by `press_face("TODO")`, `wait(1.1)`, `loop(5)` (home-based: compared only once complete) |

Steps a geometry cannot show (a key absent at 3x2) are skipped by the
scenario for that geometry with `if key is None: continue`, and the
golden records what was done.

- [ ] **Step 1: Write the scenario file** following the usage block of
  `map-tests.md` §7: one `Scenarios` method per row above. `run_all`
  takes the pages the scenario shows and whether it starts from home
  presses, skips what the target cannot show yet, and tells
  `check_golden` whether the comparison is partial:

```python
class Scenarios:
    """Mixed into one TestCase per target."""

    def run_all(self, name, inputs, world, script, pages=(),
                home_based=False):
        runs, complete = {}, True
        for cols, rows in S.GEOMETRIES:
            with S.Harness(self.make_target(), cols, rows) as h:
                world(h)
                h.boot()
                missing = [p for p in pages if not h.target.has_page(p)]
                if missing:
                    self.skipTest(f"no plugin yet for {missing}")
                complete = complete and h.target.complete()
                if home_based and not complete:
                    self.skipTest("home screen incomplete")
                script(h)
                h.check_clean(self)
                runs[f"{cols}x{rows}"] = h.steps
        S.check_golden(self, name, inputs, runs, partial=not complete)


@unittest.skipUnless(S.MONOLITH.exists(), "single file gone")
class MonolithPages(Scenarios, unittest.TestCase):
    target_kind = "monolith"
    make_target = staticmethod(S.MonolithTarget)


@unittest.skipUnless((S.PACKAGE / "app.py").exists(), "no package yet")
class PackagePages(Scenarios, unittest.TestCase):
    target_kind = "package"
    make_target = staticmethod(S.PackageTarget)
```

  A scenario reads, for example:

```python
    def test_sound_actions(self):
        def script(h):
            h.goto("sound")
            for key in sound_keys(h):  # from the screen: non-empty faces
                h.press(key)
                h.goto("sound")

        self.run_all("sound__actions", "FULL", full_world, script,
                     pages=("sound",))
```

- [ ] **Step 2: Generate the goldens from the single file.**
  `STREAMDECK_GOLDEN=update .venv.erplibre/bin/python test/test_erplibre_streamdeck_pages.py MonolithPages`
  Expected: one JSON file per row in `test/fixtures/erplibre_streamdeck/`.

- [ ] **Step 3: Check them.** Read three goldens (home__full 5x3,
  sound__actions 8x4, todo_session__menu 4x2) against the code: the
  screen arrays show the expected labels, colours and keys
  (`map-tests.md` §4 table "Geometry facts"). Run without the variable:
  `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_pages.py`
  Expected: MonolithPages all pass, PackagePages skipped.
  Run it twice more: identical results (no flakiness, no host effect;
  `check_clean` passes).

- [ ] **Step 4: Commit** `[ADD] stream_deck tests: goldens of every deck
  page` (scenario file + fixtures).

### Task 4: Package base — paths, settings, D-Bus client, `ui/`

**Files:**
- Create: `script/stream_deck/erplibre_streamdeck/__init__.py` (empty but
  for the header and a one-line docstring)
- Create: `.../erplibre_streamdeck/paths.py`, `settings.py`, `dbus.py`
- Create: `.../erplibre_streamdeck/ui/__init__.py`, `ui/colors.py`,
  `ui/i18n.py`, `ui/text.py`, `ui/icons.py`, `ui/render.py`
- Create: `test/test_erplibre_streamdeck_base.py`
- Modify: `test/test_erplibre_streamdeck_text.py` (chunk/wrap tests now
  import `erplibre_streamdeck.ui.text`)

**Interfaces:**
- Produces: `paths.STREAM_DECK_DIR`, `paths.REPO_ROOT`,
  `paths.CONFIG_DIR`, `paths.SETTINGS_FILE`, `paths.LAYOUTS_FILE`,
  `paths.state_dir()`, `paths.user_plugin_dir()`; `settings.load()`,
  `settings.save(data)`; `dbus.Reply`, `dbus.call`, `dbus.available`,
  `dbus.parse_string_tuple`, `dbus.DEST/PATH/IFACE`;
  `colors.<NAME>` (each `COLOR_<NAME>` of the file without the prefix:
  `colors.EMPTY`, `colors.OK`, `colors.ERR`, `colors.CLAUDE_ACTIVE`…);
  `i18n.LANG`, `i18n.LABELS`, `i18n.t(label)`;
  `text.chunk_text_for_cells`, `text.wrap_chunk`,
  `text.wrap_button_label`; `icons.ICONS` (name → painter);
  `render.STYLE`, `render.Style`, `render.FONT_SCALE_*`,
  `render.load_label_font(fs)`, `render.set_key(deck, key, color,
  text="", icon=None, extra_draw=None)`, `render.too_small(ctx)`.

- [ ] **Step 1: Write the failing tests** in
  `test/test_erplibre_streamdeck_base.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Base modules of the deck package: paths, settings, D-Bus client,
display style."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import dbus, paths, settings  # noqa: E402
from erplibre_streamdeck.ui import render  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_repository_files_exist(self):
        self.assertTrue((paths.REPO_ROOT / "script/todo/todo.py").exists())
        self.assertTrue(
            (paths.STREAM_DECK_DIR / "translator_stream.py").exists()
        )

    def test_settings_stay_under_dot_config(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/elsewhere"}):
            self.assertNotIn("/elsewhere", str(paths.SETTINGS_FILE))
        self.assertTrue(
            str(paths.SETTINGS_FILE).endswith(
                "/.config/erplibre-home/settings.json"
            )
        )

    def test_user_plugin_dir_follows_xdg_config_home(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/conf"}):
            self.assertEqual(
                "/x/conf/erplibre-home/deck-plugins",
                str(paths.user_plugin_dir()),
            )


class DbusTest(unittest.TestCase):
    def run_with(self, **kw):
        done = subprocess.CompletedProcess([], **kw)
        return mock.patch("subprocess.run", return_value=done)

    def test_call_argv_and_true(self):
        with self.run_with(returncode=0, stdout="(true,)\n", stderr="") as r:
            reply = dbus.call("TileWindow", 4, 2, 0, 0, 1, 1, timeout=3)
        argv = r.call_args.args[0]
        self.assertEqual(
            argv[:8],
            [
                "gdbus", "call", "--session", "--dest", dbus.DEST,
                "--object-path", dbus.PATH, "--method",
            ],
        )
        self.assertEqual(argv[8], f"{dbus.IFACE}.TileWindow")
        self.assertEqual(argv[9:], ["4", "2", "0", "0", "1", "1"])
        self.assertTrue(reply.true)

    def test_call_never_raises(self):
        for exc in (
            FileNotFoundError(2, "gdbus"),
            subprocess.TimeoutExpired(["gdbus"], 3),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        ):
            with mock.patch("subprocess.run", side_effect=exc):
                reply = dbus.call("HotReload")
            self.assertIsNone(reply.returncode)
            self.assertFalse(reply.ok)
            self.assertFalse(reply.true)
            self.assertIsNone(reply.string)

    def test_string_tuple(self):
        self.assertEqual(
            "a'b\\c", dbus.parse_string_tuple("('a\\'b\\\\c',)\n")
        )
        self.assertIsNone(dbus.parse_string_tuple("(true,)"))


class StyleTest(unittest.TestCase):
    def test_restore_clamps_and_survives_garbage(self):
        style = render.Style()
        style.restore({"font_scale": 9, "show_labels": 1})
        self.assertEqual(render.FONT_SCALE_MAX, style.font_scale)
        self.assertTrue(style.show_labels)
        style.restore({"font_scale": "big"})
        self.assertEqual(render.FONT_SCALE_DEFAULT, style.font_scale)

    def test_set_font_scale_keeps_other_keys(self):
        with mock.patch.object(
            settings, "load", return_value={"translator_stt": "vosk"}
        ), mock.patch.object(settings, "save") as save:
            render.Style().set_font_scale(1.234, settings)
        self.assertEqual(
            {"translator_stt": "vosk", "font_scale": 1.23},
            save.call_args.args[0],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run** `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_base.py`
  Expected: FAIL (`ModuleNotFoundError: erplibre_streamdeck`).

- [ ] **Step 3: Write `paths.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Every path of the deck program, anchored on this file.

settings.json and layouts.json live under the literal
~/.config/erplibre-home, the location the deck has always written; the
user plugin directory follows $XDG_CONFIG_HOME, like streamdeck.conf.
The state directory is read at call time from $XDG_STATE_HOME."""

import os
from pathlib import Path

STREAM_DECK_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = STREAM_DECK_DIR.parent.parent
CONFIG_DIR = Path(os.path.expanduser("~/.config/erplibre-home"))
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LAYOUTS_FILE = CONFIG_DIR / "layouts.json"
SETTINGS_LIB = REPO_ROOT / "script/install/erplibre_home_settings.sh"


def state_dir():
    """$XDG_STATE_HOME/erplibre-home, ~/.local/state when unset."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state"
    )
    return Path(base) / "erplibre-home"


def user_plugin_dir():
    """$XDG_CONFIG_HOME/erplibre-home/deck-plugins, ~/.config when
    unset or empty."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config"
    )
    return Path(base) / "erplibre-home" / "deck-plugins"
```

  Note: `CONFIG_DIR` is computed at import, like the single file's
  `LAYOUT_DIR`; the harness sets `HOME` before any import.

- [ ] **Step 4: Write `settings.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The one reader and writer of settings.json.

Each writer reloads the file right before saving and changes only its
own keys, so a11y and the translator keep each other's values. The
write is not atomic."""

import json
import os

from erplibre_streamdeck import paths


def load():
    """settings.json as a dict; {} when missing or not JSON."""
    try:
        with open(paths.SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(data):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
```

- [ ] **Step 5: Write `dbus.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The one client of the ERPLibre Home extension's D-Bus interface.

call() runs `gdbus call` and returns a Reply; it never raises: a
missing gdbus, a timeout or undecodable output give returncode None.
The callers read the reply the way their method answers."""

import subprocess
from dataclasses import dataclass

DEST = "org.gnome.Shell"
PATH = "/org/gnome/Shell/Extensions/ERPLibreHome"
IFACE = "org.gnome.Shell.Extensions.ERPLibreHome"


def parse_string_tuple(output):
    """The string of a gdbus answer of the form ('...',), or None.

    GVariant single-quoted strings escape only backslash and single
    quote; double quotes from JSON content pass through."""
    s = output.strip()
    if not (s.startswith("('") and s.endswith("',)")):
        return None
    inner = s[2:-3]
    # \x00 holds the place of \\ so it is not unescaped twice.
    return (
        inner.replace("\\\\", "\x00")
        .replace("\\'", "'")
        .replace("\x00", "\\")
    )


@dataclass(frozen=True)
class Reply:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def true(self):
        """Exit 0 and a `true` in the answer, as `(true,)`."""
        return self.ok and "true" in self.stdout.lower()

    @property
    def string(self):
        return parse_string_tuple(self.stdout) if self.ok else None


def call(method, *args, timeout=3):
    argv = [
        "gdbus", "call", "--session",
        "--dest", DEST,
        "--object-path", PATH,
        "--method", f"{IFACE}.{method}",
    ] + [str(a) for a in args]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return Reply(None, "", str(exc))
    return Reply(done.returncode, done.stdout or "", done.stderr or "")


def available():
    """The extension is loaded: introspection lists TileWindow."""
    try:
        done = subprocess.run(
            [
                "gdbus", "introspect", "--session",
                "--dest", DEST,
                "--object-path", PATH,
            ],
            capture_output=True, text=True, timeout=3,
        )
        return "TileWindow" in done.stdout
    except Exception:
        return False
```

- [ ] **Step 6: Write `ui/colors.py`, `ui/i18n.py`, `ui/text.py`,
  `ui/icons.py` by copying from the single file:**
  - `colors.py`: every `COLOR_*` constant (see `map-kernel.md` §1b),
    renamed without the `COLOR_` prefix (`COLOR_EMPTY` → `EMPTY`), plus
    `ICON_WHITE`, `ICON_RED` from `_ICON_WHITE`/`_ICON_RED`. A colour
    defined only for one plugin may stay in that plugin; every colour
    read by two domains (list in `map-a11y_bt_sound.md` T11 and
    `map-kernel.md` §1b) lives here.
  - `i18n.py`: the comment block, `_DECK_LANG` as `LANG`, `_DECK_LABELS`
    as `LABELS`, `_t` as `t` (body unchanged: it reads `LANG` at call
    time). Drop the `'OK!'`/`'ERR'` entries only if no call passes them
    to `_t` (`map-kernel.md` trap 14 says none does).
  - `text.py`: `_chunk_text_for_cells`, `_wrap_chunk`,
    `_wrap_button_label`, without the leading underscore, bodies
    unchanged.
  - `icons.py`: the `_icon_*` painters (names without the underscore)
    and `ICONS` (from `_ICONS`), using `colors.ICON_WHITE/ICON_RED`.

- [ ] **Step 7: Write `ui/render.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Painting one key, and the display style every key follows.

set_key reads STYLE at each call: a change of font scale or labels shows
on the next paint. The font is looked up on first use."""

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

from erplibre_streamdeck.ui import colors, i18n, icons

FONT_SCALE_MIN = 0.6
FONT_SCALE_MAX = 2.5
FONT_SCALE_STEP = 0.1
FONT_SCALE_DEFAULT = 1.0


class Style:
    """Font scale and label visibility of every key."""

    def __init__(self):
        self.font_scale = FONT_SCALE_DEFAULT
        self.show_labels = False

    def restore(self, data):
        """Take font_scale (clamped) and show_labels from a settings
        dict; a value that is not a number gives the default."""
        try:
            val = float(data.get("font_scale", FONT_SCALE_DEFAULT))
            self.font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, val))
        except (ValueError, TypeError):
            self.font_scale = FONT_SCALE_DEFAULT
        self.show_labels = bool(data.get("show_labels", False))

    def set_font_scale(self, scale, settings):
        """Clamp and keep the scale; settings.json stores it rounded to
        two places, the value in memory stays exact."""
        self.font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))
        data = settings.load()
        data["font_scale"] = round(self.font_scale, 2)
        settings.save(data)

    def toggle_labels(self, settings):
        self.show_labels = not self.show_labels
        data = settings.load()
        data["show_labels"] = self.show_labels
        settings.save(data)


STYLE = Style()

```

  then append, copied from the single file: `_FONT_CANDIDATES` (with its
  comment), a lazily cached `_font_path()` replacing the import-time
  `_FONT_PATH` loop, `load_label_font(fs)` (from `_load_label_font`,
  using `_font_path()`), and `set_key` with its body unchanged except:
  `_ICONS` → `icons.ICONS`, `_show_labels` → `STYLE.show_labels`,
  `_font_scale` → `STYLE.font_scale`, `_load_label_font` →
  `load_label_font`. Finally:

```python
def too_small(ctx):
    """The page a deck too small for it shows: BACK on key 0, the
    warning in the middle key, the rest empty."""
    total = ctx.geo.total_keys
    for key in range(total):
        if key == 0:
            ctx.set_key(key, colors.BACK, ctx.t("BACK"))
        elif key == total // 2:
            ctx.set_key(key, colors.ERR, ctx.t("DECK\nTOO\nSMALL"))
        else:
            ctx.set_key(key, colors.EMPTY, "")
```

- [ ] **Step 8: Re-point the text tests.** In
  `test/test_erplibre_streamdeck_text.py`, `ChunkTextForCellsTest`,
  `WrapChunkTest` and `WrapButtonLabelTest` call
  `erplibre_streamdeck.ui.text` (`from erplibre_streamdeck.ui import
  text`, `text.chunk_text_for_cells` …). Other classes stay on `GT`.

- [ ] **Step 9: Run** `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_base.py test/test_erplibre_streamdeck_text.py test/test_erplibre_streamdeck_pages.py test/test_todo.py`
  Expected: all pass (pages: PackagePages still skipped — no `app.py`).

- [ ] **Step 10: Commit** `[ADD] stream_deck: package base, paths,
  settings, D-Bus client, ui`.

### Task 5: Plugin interface, context, kernel

**Files:**
- Create: `.../erplibre_streamdeck/plugin.py`, `context.py`, `kernel.py`
- Create: `test/test_erplibre_streamdeck_kernel.py`
- Modify: `test/test_erplibre_streamdeck_text.py` (`RecheckDbusTest`
  moves to the kernel test file, on `Kernel.recheck_dbus`)

**Interfaces:**
- Consumes: Task 4 modules.
- Produces: `plugin.PLUGIN_API`, `Geometry(cols, rows, total_keys)`,
  `KeyFace(color, text="", icon=None, extra_draw=None)`,
  `Page(id, keys, render, handle, tick=None, period=0.0)`,
  `HomeButton(order, face, press)`, `Fixture(order, place, face, press)`,
  `TileProvider(order, items, face, press)`, `Plugin(api, pages=[],
  home_button=None, fixtures=[], tiles=[], home_tick=None,
  home_period=0.0, setup=None, shutdown=None)`,
  `plugin.LoadedPlugin(id, plugin, origin, path)`;
  `context.Context(kernel, plugin_id)`;
  `kernel.HOME = "idle"`, `RESULT_FLASH_SEC = 0.5`,
  `DBUS_RECHECK_SEC = 5.0`, `HOME_REFRESH_SEC = 2.0`, `LOOP_SEC = 0.3`,
  `kernel.Kernel(deck, plugins)` with `geo`, `lock`, `running`,
  `page_id`, `pages`, `page_keys`, `plugins`, `refused`, `dbus_ok`,
  `state(pid)`, `ctx(pid)`, `guard(pid, what, fn, *args) -> (ok, result)`,
  `paint(key, face)`, `set_flash(ok)`, `goto(page_id)`, `render()`,
  `handle_key(key, pressed)`, `recheck_dbus(now)`, `step(now)`, `loop()`,
  `shutdown()`. `home.Home` comes in Task 6: until then `kernel.py`
  imports it lazily (`from erplibre_streamdeck import home` inside
  `__init__`) and the Task 5 tests give plugins with no home
  contribution.

- [ ] **Step 1: Write `plugin.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""What a deck plugin declares.

A plugin module exposes PLUGIN = Plugin(api=PLUGIN_API, ...). Its id is
its file name; the loader sets it. Every callable receives a Context,
and is called with the kernel lock held, except threads the plugin
starts itself (they take ctx.locked())."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PLUGIN_API = 1


@dataclass(frozen=True)
class Geometry:
    cols: int
    rows: int
    total_keys: int


@dataclass(frozen=True)
class KeyFace:
    color: tuple
    text: str = ""
    icon: str | None = None
    extra_draw: Callable | None = None


@dataclass
class Page:
    """A deck page. `keys(geo)` names the page's key indexes, once per
    start, or None when the deck is too small; pass keys=None when the
    page computes its keys itself. `tick(ctx, now)` runs every `period`
    seconds while the page shows (0.0: every loop pass)."""

    id: str
    keys: Callable[[Geometry], Any] | None
    render: Callable
    handle: Callable
    tick: Callable | None = None
    period: float = 0.0


@dataclass
class HomeButton:
    """A key on the home rows; `order` places it (lower first)."""

    order: int
    face: Callable
    press: Callable


@dataclass
class Fixture:
    """Keys a plugin places itself on the home screen.
    `place(geo, home_keys)` returns the keys, given each plugin's home
    button key (-1 when it has none); face(ctx, key, index) returns a
    KeyFace or None (painted empty); press(ctx, key, index)."""

    order: int
    place: Callable
    face: Callable
    press: Callable


@dataclass
class TileProvider:
    """Dashboard tiles: items(ctx) once per home render, face(ctx, item),
    press(ctx, item) with the item the key showed."""

    order: int
    items: Callable
    face: Callable
    press: Callable


@dataclass
class Plugin:
    api: int
    pages: list = field(default_factory=list)
    home_button: HomeButton | None = None
    fixtures: list = field(default_factory=list)
    tiles: list = field(default_factory=list)
    home_tick: Callable | None = None
    home_period: float = 0.0
    setup: Callable | None = None
    shutdown: Callable | None = None


@dataclass
class LoadedPlugin:
    id: str
    plugin: Plugin
    origin: str  # "repo" or "user"
    path: Path
```

- [ ] **Step 2: Write `context.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The one object a plugin receives: the deck, the kernel's services,
and the plugin's own state namespace."""

import sys

from erplibre_streamdeck import settings as settings_mod
from erplibre_streamdeck.plugin import KeyFace
from erplibre_streamdeck.ui import i18n, render


class Context:
    def __init__(self, kernel, plugin_id):
        self._kernel = kernel
        self.plugin_id = plugin_id
        self.geo = kernel.geo
        self.dbus = kernel.dbus
        self.settings = settings_mod
        self.style = render.STYLE

    @property
    def page(self):
        """The id of the page shown; "idle" on the home screen."""
        return self._kernel.page_id

    @property
    def keys(self):
        """keys(geo) of the page shown, as computed at start."""
        return self._kernel.page_keys.get(self._kernel.page_id)

    @property
    def home_keys(self):
        """Plugin id -> its home button key, -1 when it has none."""
        return dict(self._kernel.home.home_keys)

    def t(self, label):
        return i18n.t(label)

    def set_key(self, key, color, text="", icon=None, extra_draw=None):
        """Paint one key; `color` may be a KeyFace."""
        if isinstance(color, KeyFace):
            color, text, icon, extra_draw = (
                color.color, color.text, color.icon, color.extra_draw
            )
        render.set_key(
            self._kernel.deck, key, color, text, icon, extra_draw
        )

    def flash(self, ok, reason=None):
        """Record the OK/ERR flash on the last pressed key; a reason for
        a failure goes to the journal. Does not render."""
        if not ok and reason:
            self.log(reason)
        self._kernel.set_flash(ok)

    def goto(self, page_id):
        self._kernel.goto(page_id)

    def home(self):
        self._kernel.goto("idle")

    def render(self):
        self._kernel.render()

    def state(self, plugin_id=None):
        return self._kernel.state(plugin_id or self.plugin_id)

    def locked(self):
        """The kernel lock, for a thread the plugin started:
        `with ctx.locked(): ...`."""
        return self._kernel.lock

    def log(self, msg):
        print(
            f"[erplibre-home] {self.plugin_id}: {msg}",
            file=sys.stderr,
            flush=True,
        )
```

- [ ] **Step 3: Write the failing kernel tests**
  `test/test_erplibre_streamdeck_kernel.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck kernel: dispatch, flash, ticks, error isolation."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck.plugin import (  # noqa: E402
    LoadedPlugin,
    Page,
    Plugin,
    PLUGIN_API,
)
from erplibre_streamdeck.ui import render  # noqa: E402


class FakeDbus:
    def __init__(self, ok=True):
        self.ok = ok
        self.checks = 0

    def available(self):
        self.checks += 1
        return self.ok


def loaded(pid, plugin):
    return LoadedPlugin(pid, plugin, "repo", Path(f"{pid}.py"))


class KernelCase(unittest.TestCase):
    def setUp(self):
        self.clock = S.FakeClock()
        self.journal = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch("time.monotonic", self.clock.monotonic)
        )
        stack.enter_context(mock.patch("time.sleep", self.clock.sleep))
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(contextlib.redirect_stderr(self.journal))
        self.deck = S.FakeDeck(5, 3)
        self.calls = []

    def kernel(self, *plugins, dbus=None):
        with mock.patch.object(K, "dbus_mod", dbus or FakeDbus()):
            return K.Kernel(self.deck, list(plugins))

    def page_plugin(self, pid="p", page_id="pg", **page_kw):
        def render_(ctx):
            self.calls.append(("render", page_id))
            ctx.set_key(0, (1, 2, 3), "X")

        def handle(ctx, key):
            self.calls.append(("handle", key))

        kw = dict(keys=None, render=render_, handle=handle)
        kw.update(page_kw)
        return loaded(pid, Plugin(api=PLUGIN_API, pages=[Page(page_id, **kw)]))


class DispatchTest(KernelCase):
    def test_release_is_ignored_and_press_goes_to_page(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        k.handle_key(3, False)
        k.handle_key(3, True)
        self.assertEqual([("render", "pg"), ("handle", 3)], self.calls)
        self.assertEqual(3, k.last_press_key)

    def test_press_during_flash_is_ignored(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        k.set_flash(True)
        k.handle_key(1, True)
        self.clock.advance(K.RESULT_FLASH_SEC)
        k.handle_key(2, True)
        self.assertEqual([("render", "pg"), ("handle", 2)], self.calls)

    def test_flash_overlays_pressed_key_and_neighbours(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        k.handle_key(7, True)
        k.set_flash(False)
        k.render()
        screen = self.deck.rendering()
        for key in (2, 6, 7, 8, 12):
            self.assertEqual("ERR", screen[key][1], key)
        self.assertEqual("X", screen[0][1])


class IsolationTest(KernelCase):
    def boom(self, *a):
        raise ValueError("bad")

    def test_handle_error_flashes_and_goes_home(self):
        k = self.kernel(self.page_plugin(handle=self.boom))
        k.goto("pg")
        k.handle_key(4, True)
        self.assertEqual("idle", k.page_id)
        self.assertEqual("err", k.flash_result)
        self.assertIn("p: page pg handle failed", self.journal.getvalue())

    def test_render_error_shows_home(self):
        k = self.kernel(self.page_plugin(render=self.boom))
        k.goto("pg")
        self.assertEqual("idle", k.page_id)

    def test_repeated_failure_logged_once(self):
        k = self.kernel(self.page_plugin(handle=self.boom))
        for _ in range(3):
            k.goto("pg")
            self.clock.advance(1)
            k.handle_key(4, True)
        self.assertEqual(
            1, self.journal.getvalue().count("page pg handle failed")
        )

    def test_logged_again_after_a_success(self):
        state = {"fail": True}

        def handle(ctx, key):
            if state["fail"]:
                raise ValueError("bad")

        k = self.kernel(self.page_plugin(handle=handle))
        for fail in (True, False, True):
            state["fail"] = fail
            k.goto("pg")
            self.clock.advance(1)
            k.handle_key(4, True)
        self.assertEqual(
            2, self.journal.getvalue().count("page pg handle failed")
        )

    def test_setup_error_refuses_the_plugin(self):
        bad = loaded(
            "bad",
            Plugin(api=PLUGIN_API, pages=[Page("b", None, print, print)],
                   setup=self.boom),
        )
        k = self.kernel(bad, self.page_plugin())
        self.assertEqual(["p"], [lp.id for lp in k.plugins])
        self.assertEqual("bad", k.refused[0][0])
        self.assertNotIn("b", k.pages)


class TickTest(KernelCase):
    def test_flash_blocks_every_tick(self):
        ticks = []
        k = self.kernel(
            self.page_plugin(tick=lambda ctx, now: ticks.append(now))
        )
        k.goto("pg")
        k.set_flash(True)
        k.step(self.clock.now)          # flash live: nothing
        self.clock.advance(K.RESULT_FLASH_SEC)
        k.step(self.clock.now)          # expired: render only
        self.assertEqual([], ticks)
        self.assertIsNone(k.flash_result)
        k.step(self.clock.now)
        self.assertEqual(1, len(ticks))

    def test_period_and_first_pass(self):
        ticks = []
        k = self.kernel(
            self.page_plugin(
                tick=lambda ctx, now: ticks.append(now), period=2.0
            )
        )
        k.goto("pg")
        k.step(self.clock.now)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertEqual(2, len(ticks))

    def test_tick_error_goes_home(self):
        k = self.kernel(self.page_plugin(tick=lambda c, n: 1 / 0))
        k.goto("pg")
        k.step(self.clock.now)
        self.assertEqual("idle", k.page_id)

    def test_home_ticks_and_refresh(self):
        renders = []
        asks = {"n": 0}

        def home_tick(ctx, now):
            asks["n"] += 1
            return False

        p = loaded("h", Plugin(api=PLUGIN_API, home_tick=home_tick))
        k = self.kernel(p)
        with mock.patch.object(k, "render", lambda: renders.append(1)):
            k.step(self.clock.now)       # first pass: refresh renders
            self.clock.advance(0.3)
            k.step(self.clock.now)       # tick ran, no render asked
        self.assertEqual(2, asks["n"])
        self.assertEqual(1, len(renders))

    def test_loop_clears_schedules(self):
        ticks = []
        k = self.kernel(
            self.page_plugin(
                tick=lambda ctx, now: ticks.append(now), period=2.0
            )
        )
        k.goto("pg")
        self.deck.polls = 1
        k.loop()
        self.deck.polls = 1
        k.loop()
        self.assertEqual(2, len(ticks))


class RecheckDbusTest(KernelCase):
    def test_rechecks_while_missing_then_stops(self):
        dbus = FakeDbus(ok=False)
        k = self.kernel(dbus=dbus)
        self.assertEqual(1, dbus.checks)
        self.assertFalse(k.recheck_dbus(self.clock.now + 1))
        self.assertEqual(1, dbus.checks)
        dbus.ok = True
        self.assertTrue(k.recheck_dbus(self.clock.now + K.DBUS_RECHECK_SEC))
        self.assertFalse(k.recheck_dbus(self.clock.now + 100))
        self.assertEqual(2, dbus.checks)


if __name__ == "__main__":
    unittest.main()
```

  Delete `RecheckDbusTest` from `test/test_erplibre_streamdeck_text.py`.

- [ ] **Step 4: Run** `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_kernel.py`
  Expected: FAIL (`No module named 'erplibre_streamdeck.kernel'`).

- [ ] **Step 5: Write `kernel.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck kernel: the page shown, the OK/ERR flash, the dispatch of
keys, renders and ticks to the plugins, and their isolation.

Every plugin call goes through guard(): an exception is written to the
journal once per (plugin, call, error) until that call succeeds again,
and the kernel recovers (flash ERR, home screen, empty key) instead of
dying. handle_key, render and step's locked part expect the caller to
hold `lock`; the app's key callback and loop() take it."""

import sys
import threading
import time
import traceback
import types

from erplibre_streamdeck import dbus as dbus_mod
from erplibre_streamdeck.context import Context
from erplibre_streamdeck.plugin import Geometry
from erplibre_streamdeck.ui import colors, render

HOME = "idle"
# How long the OK/ERR feedback stays on the pressed key and its four
# neighbours; key presses are ignored meanwhile.
RESULT_FLASH_SEC = 0.5
# While the extension's D-Bus interface is missing, look for it again
# this often: the service can start before GNOME Shell exports it.
DBUS_RECHECK_SEC = 5.0
# The home screen redraws this often: the mic and the session tiles
# follow the system without a tick of their own.
HOME_REFRESH_SEC = 2.0
LOOP_SEC = 0.3


class ErrorLog:
    """Which (plugin, call) last failed with which error."""

    def __init__(self):
        self._last = {}

    def failed(self, plugin_id, what, exc):
        """True when this failure must be written: a new error for this
        call, or the first since it last succeeded."""
        sig = (type(exc).__name__, str(exc))
        if self._last.get((plugin_id, what)) == sig:
            return False
        self._last[(plugin_id, what)] = sig
        return True

    def succeeded(self, plugin_id, what):
        self._last.pop((plugin_id, what), None)


class Kernel:
    def __init__(self, deck, plugins):
        from erplibre_streamdeck import home

        self.deck = deck
        rows, cols = deck.key_layout()
        self.geo = Geometry(cols, rows, cols * rows)
        self.lock = threading.Lock()
        self.running = True
        self.page_id = HOME
        self.flash_result = None
        self.flash_time = 0.0
        self.last_press_key = None
        self.dbus = dbus_mod
        self.errors = ErrorLog()
        self._states = {}
        self._contexts = {}
        self._schedule = {}
        self.refused = []
        self.plugins = []
        self.pages = {}
        self.page_keys = {}
        self.home = home.Home(self.geo, [])
        self.plugins = self._setup(list(plugins))
        for lp in self.plugins:
            for page in lp.plugin.pages:
                self.pages[page.id] = (lp.id, page)
                self.page_keys[page.id] = (
                    page.keys(self.geo) if page.keys else None
                )
        self.home = home.Home(self.geo, self.plugins)
        self.dbus_ok = self.dbus.available()
        self._dbus_checked_at = time.monotonic()

    # -- plugin plumbing

    def _setup(self, plugins):
        kept = []
        for lp in plugins:
            if lp.plugin.setup is not None:
                ok, _ = self.guard(
                    lp.id, "setup", lp.plugin.setup, self.ctx(lp.id)
                )
                if not ok:
                    self.refused.append((lp.id, "setup raised"))
                    continue
            kept.append(lp)
        return kept

    def state(self, plugin_id):
        if plugin_id not in self._states:
            self._states[plugin_id] = types.SimpleNamespace()
        return self._states[plugin_id]

    def ctx(self, plugin_id):
        if plugin_id not in self._contexts:
            self._contexts[plugin_id] = Context(self, plugin_id)
        return self._contexts[plugin_id]

    def guard(self, plugin_id, what, fn, *args):
        """Call fn(*args); (True, result), or (False, None) after
        writing the error to the journal (see ErrorLog)."""
        try:
            result = fn(*args)
        except Exception as exc:
            if self.errors.failed(plugin_id, what, exc):
                print(
                    f"[erplibre-home] {plugin_id}: {what} failed: "
                    f"{exc!r}\n{traceback.format_exc()}",
                    file=sys.stderr,
                    flush=True,
                )
            return False, None
        self.errors.succeeded(plugin_id, what)
        return True, result

    def paint(self, key, face):
        render.set_key(
            self.deck, key, face.color, face.text, face.icon,
            face.extra_draw,
        )

    # -- pages and flash

    def set_flash(self, ok):
        self.flash_result = "ok" if ok else "err"
        self.flash_time = time.monotonic()

    def _flash_live(self):
        return (
            self.flash_result is not None
            and time.monotonic() - self.flash_time < RESULT_FLASH_SEC
        )

    def goto(self, page_id):
        self.page_id = page_id
        self.render()

    def render(self):
        if self.flash_result:
            if self._flash_live():
                self._render_page()
                self._overlay_flash()
                return
            self.flash_result = None
        self._render_page()

    def _render_page(self):
        if self.page_id != HOME:
            owner, page = self.pages[self.page_id]
            ok, _ = self.guard(
                owner, f"page {page.id} render", page.render,
                self.ctx(owner),
            )
            if ok:
                return
            self.page_id = HOME
        self.home.render(self)

    def _overlay_flash(self):
        color = colors.OK if self.flash_result == "ok" else colors.ERR
        label = "OK!" if self.flash_result == "ok" else "ERR"
        if self.last_press_key is None:
            # No key pressed yet (a flash raised by a tick): the whole
            # deck shows it.
            keys = range(self.geo.total_keys)
        else:
            keys = self._key_neighbors(self.last_press_key)
            keys.add(self.last_press_key)
        for k in keys:
            if 0 <= k < self.geo.total_keys:
                render.set_key(self.deck, k, color, label)

    def _key_neighbors(self, key):
        cols, rows = self.geo.cols, self.geo.rows
        if key is None or cols <= 0 or rows <= 0:
            return set()
        col, row = key % cols, key // cols
        out = set()
        for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nc, nr = col + dc, row + dr
            if 0 <= nc < cols and 0 <= nr < rows:
                out.add(nr * cols + nc)
        return out

    def handle_key(self, key, pressed):
        if not pressed or self._flash_live():
            return
        self.last_press_key = key
        if self.page_id == HOME:
            self.home.press(self, key)
            return
        owner, page = self.pages[self.page_id]
        ok, _ = self.guard(
            owner, f"page {page.id} handle", page.handle,
            self.ctx(owner), key,
        )
        if not ok:
            self.set_flash(False)
            self.goto(HOME)

    # -- loop

    def recheck_dbus(self, now):
        """While the extension is missing, look for it again every
        DBUS_RECHECK_SEC; True when it has just appeared, so the caller
        redraws. Once found it is never checked again."""
        if self.dbus_ok or now - self._dbus_checked_at < DBUS_RECHECK_SEC:
            return False
        self._dbus_checked_at = now
        self.dbus_ok = self.dbus.available()
        return self.dbus_ok

    def _due(self, name, period, now):
        if now - self._schedule.get(name, 0.0) >= period:
            self._schedule[name] = now
            return True
        return False

    def step(self, now):
        """One loop pass. Outside the lock: the D-Bus recheck (gdbus may
        take its 3 s timeout). Under it: a recorded flash ends the pass
        (rendered once expired); otherwise the page's tick, or on the
        home screen the due home ticks and at most one render."""
        if self.recheck_dbus(now):
            with self.lock:
                self.render()
        with self.lock:
            if self.flash_result:
                if not self._flash_live():
                    self.render()
                return
            if self.page_id == HOME:
                self._home_step(now)
                return
            owner, page = self.pages[self.page_id]
            if page.tick is None:
                return
            if not self._due(f"page:{page.id}", page.period, now):
                return
            ok, _ = self.guard(
                owner, f"page {page.id} tick", page.tick,
                self.ctx(owner), now,
            )
            if not ok:
                self.goto(HOME)

    def _home_step(self, now):
        want = False
        for lp in self.plugins:
            tick = lp.plugin.home_tick
            if tick is None:
                continue
            if not self._due(f"home:{lp.id}", lp.plugin.home_period, now):
                continue
            ok, asked = self.guard(lp.id, "home tick", tick, self.ctx(lp.id),
                                   now)
            want = want or bool(ok and asked)
        if self._due("home-refresh", HOME_REFRESH_SEC, now):
            want = True
        if want:
            self.render()

    def loop(self):
        self._schedule.clear()
        while self.running and self.deck.is_open():
            self.step(time.monotonic())
            time.sleep(LOOP_SEC)

    def shutdown(self):
        for lp in self.plugins:
            if lp.plugin.shutdown is not None:
                self.guard(
                    lp.id, "shutdown", lp.plugin.shutdown, self.ctx(lp.id)
                )
```

  Note `self.dbus = dbus_mod` resolves the module attribute at
  construction; the tests patch `K.dbus_mod`. Wrap the
  `ok, asked = self.guard(...)` line to 79 columns when formatting.

- [ ] **Step 6: Add a minimal `home.py` so the kernel imports** (Task 6
  replaces it entirely):

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The home screen (completed by the next task)."""


class Home:
    def __init__(self, geo, plugins):
        self.geo = geo
        self.home_keys = {}

    def render(self, kernel):
        pass

    def press(self, kernel, key):
        pass
```

- [ ] **Step 7: Run** `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_kernel.py test/test_erplibre_streamdeck_text.py`
  Expected: PASS.

- [ ] **Step 8: Commit** `[ADD] stream_deck: deck kernel, plugin
  interface and context`.

### Task 6: Home screen

**Files:**
- Modify (replace): `.../erplibre_streamdeck/home.py`
- Create: `test/test_erplibre_streamdeck_home.py`

**Interfaces:**
- Consumes: Task 5 (`Kernel.ctx/guard/paint/set_flash/render`,
  `dbus_ok`, `HomeButton`, `Fixture`, `TileProvider`, `KeyFace`).
- Produces: `home.Home(geo, plugins)` with `home_keys`
  (`{plugin_id: key or -1}` for every plugin with a home button),
  `buttons` (`{key: (pid, HomeButton)}`), `fixtures`
  (`{key: (pid, Fixture, index)}`), `pool` (dashboard keys),
  `tile_map` (`{key: (pid, TileProvider, item)}` of the last render),
  `render(kernel)`, `press(kernel, key)`; `home.allocate(geo, plugins)`.

- [ ] **Step 1: Write the failing tests** `test/test_erplibre_streamdeck_home.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Home screen allocation, dashboard, and the taps that follow it."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import home  # noqa: E402
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck.plugin import (  # noqa: E402
    Fixture,
    Geometry,
    HomeButton,
    KeyFace,
    LoadedPlugin,
    Plugin,
    PLUGIN_API,
    TileProvider,
)
from erplibre_streamdeck.ui import render  # noqa: E402

# The repository's home buttons, by order, as the single file lays them.
ORDERS = {
    "tiling": 10, "timers": 20, "dev_reload": 30, "sound": 40,
    "layouts": 50, "a11y": 60, "bluetooth": 70, "translate": 80,
    "todo_terminals": 90,
}


def face(label):
    return lambda ctx: KeyFace((1, 1, 1), label)


def plugins(off=()):
    out = []
    for pid, order in ORDERS.items():
        if pid in off:
            continue
        fixtures = []
        if pid == "sound":
            fixtures.append(Fixture(
                10,
                lambda geo, hk: (
                    [(geo.rows - 1) * geo.cols] if geo.rows >= 2 else []
                ),
                lambda ctx, key, i: KeyFace((2, 2, 2), "MIC"),
                lambda ctx, key, i: None,
            ))
        if pid == "layouts":
            def place(geo, hk):
                lk = hk.get("layouts", -1)
                if lk < 0 or geo.rows < 2 or lk + 3 > geo.cols:
                    return []
                base = (geo.rows - 1) * geo.cols + lk
                return [base + i for i in range(3)]
            fixtures.append(Fixture(
                20, place, lambda ctx, key, i: None, lambda c, k, i: None,
            ))
        button = HomeButton(order, face(pid), lambda ctx: None)
        out.append(LoadedPlugin(
            pid,
            Plugin(api=PLUGIN_API, home_button=button, fixtures=fixtures),
            "repo",
            Path(f"{pid}.py"),
        ))
    return out


class AllocationTest(unittest.TestCase):
    """The single file's facts (map-tests.md §4 "Geometry facts")."""

    EXPECT = {
        (3, 2): ({"tiling": 0, "timers": 1, "dev_reload": 2}, [3], [4, 5]),
        (4, 2): ({"sound": 3}, [4], [5, 6, 7]),
        (5, 3): (
            {"layouts": 4, "a11y": 5, "bluetooth": 6, "translate": 7,
             "todo_terminals": 8},
            [10],
            [9, 11, 12, 13, 14],
        ),
        (8, 4): (
            {"translate": 7, "todo_terminals": 8},
            [24, 28, 29, 30],
            list(range(9, 24)) + [25, 26, 27, 31],
        ),
    }

    def test_geometries(self):
        for (cols, rows), (keys, fixed, pool) in self.EXPECT.items():
            geo = Geometry(cols, rows, cols * rows)
            alloc = home.allocate(geo, plugins())
            for pid, key in keys.items():
                self.assertEqual(key, alloc.home_keys[pid], (cols, pid))
            self.assertEqual(fixed, sorted(alloc.fixtures), (cols, rows))
            self.assertEqual(pool, alloc.pool, (cols, rows))

    def test_tile_and_timer_never_share_a_key(self):
        for cols, rows in S.GEOMETRIES:
            geo = Geometry(cols, rows, cols * rows)
            hk = home.allocate(geo, plugins()).home_keys
            self.assertNotEqual(hk["tiling"], hk["timers"])

    def test_allocation_with_each_plugin_off(self):
        for off in ORDERS:
            for cols, rows in S.GEOMETRIES:
                geo = Geometry(cols, rows, cols * rows)
                alloc = home.allocate(geo, plugins(off=(off,)))
                used = [k for k in alloc.home_keys.values() if k >= 0]
                self.assertEqual(len(used), len(set(used)))
                self.assertEqual(
                    sorted(used)[: min(cols, len(used))],
                    list(range(min(cols, len(used)))),
                    (off, cols, rows),
                )
                taken = set(used) | set(alloc.fixtures)
                self.assertFalse(taken & set(alloc.pool))

    def test_layout_shortcuts_follow_layout_key(self):
        geo = Geometry(8, 4, 32)
        alloc = home.allocate(geo, plugins(off=("tiling", "sound")))
        self.assertEqual(2, alloc.home_keys["layouts"])
        self.assertEqual([26, 27, 28], sorted(alloc.fixtures))


class DashboardTest(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.deck = S.FakeDeck(5, 3)
        self.pressed = []
        self.items = {"a": ["a1", "a2"], "b": ["b1"]}

    def kernel(self, extra=()):
        tiles = []
        for order, pid in ((10, "a"), (20, "b")):
            tiles.append(LoadedPlugin(pid, Plugin(
                api=PLUGIN_API,
                tiles=[TileProvider(
                    order,
                    lambda ctx, pid=pid: list(self.items[pid]),
                    lambda ctx, item: KeyFace((3, 3, 3), item),
                    lambda ctx, item: self.pressed.append(item),
                )],
            ), "repo", Path(f"{pid}.py")))
        with mock.patch.object(K, "dbus_mod", mock.Mock(available=bool)):
            return K.Kernel(self.deck, plugins() + tiles + list(extra))

    def test_order_and_tap_reads_last_render(self):
        k = self.kernel()
        k.render()
        screen = self.deck.rendering()
        self.assertEqual(["a1", "a2", "b1"],
                         [screen[key][1] for key in (9, 11, 12)])
        self.items["a"].insert(0, "a0")  # appears after the render
        k.handle_key(9, True)
        self.assertEqual(["a1"], self.pressed)

    def test_items_error_leaves_keys_to_next_provider(self):
        def boom(ctx):
            raise OSError("state dir")

        bad = LoadedPlugin("z", Plugin(api=PLUGIN_API, tiles=[
            TileProvider(5, boom, None, None)]), "repo", Path("z.py"))
        k2 = self.kernel(extra=[bad])
        k2.render()
        screen = self.deck.rendering()
        self.assertEqual("a1", screen[9][1])

    def test_no_ext_on_key_zero_only_when_free(self):
        k = self.kernel()
        k.dbus_ok = False
        k.render()
        self.assertEqual("tiling", self.deck.rendering()[0][1])
        with mock.patch.object(K, "dbus_mod", mock.Mock(available=bool)):
            k2 = K.Kernel(self.deck, [])
        k2.dbus_ok = False
        k2.render()
        self.assertEqual("NO\nEXT", self.deck.rendering()[0][1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run** the file. Expected: FAIL (`home.allocate` missing).

- [ ] **Step 3: Write `home.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The home screen: home buttons, fixtures, and the dashboard.

Home buttons take row 0 in their order, left to right; on a deck of
three rows or more the overflow takes row 1 from column 0 until it is
full; the rest get no key. Fixtures are then placed in their order,
skipping keys already taken. The dashboard is every other key from row
1 on, in reading order, filled by the tile providers in their order.
A render stores which item each dashboard key shows, and a tap reads
that: it opens what the key showed."""

from dataclasses import dataclass, field

from erplibre_streamdeck.plugin import KeyFace
from erplibre_streamdeck.ui import colors, i18n

EMPTY = KeyFace(colors.EMPTY, "")


@dataclass
class Allocation:
    home_keys: dict = field(default_factory=dict)
    buttons: dict = field(default_factory=dict)
    fixtures: dict = field(default_factory=dict)
    pool: list = field(default_factory=list)


def allocate(geo, plugins):
    alloc = Allocation()
    with_button = sorted(
        (lp for lp in plugins if lp.plugin.home_button is not None),
        key=lambda lp: (lp.plugin.home_button.order, lp.id),
    )
    for i, lp in enumerate(with_button):
        alloc.home_keys[lp.id] = i if i < geo.cols else -1
    if geo.rows >= 3:
        nxt, end = geo.cols, geo.cols * 2
        for lp in with_button:
            if alloc.home_keys[lp.id] >= 0:
                continue
            if nxt >= end:
                break
            alloc.home_keys[lp.id] = nxt
            nxt += 1
    for lp in with_button:
        key = alloc.home_keys[lp.id]
        if key >= 0:
            alloc.buttons[key] = (lp.id, lp.plugin.home_button)
    taken = set(alloc.buttons)
    fixtures = sorted(
        (
            (fx.order, lp.id, fx)
            for lp in plugins
            for fx in lp.plugin.fixtures
        ),
        key=lambda t: (t[0], t[1]),
    )
    for _, pid, fx in fixtures:
        for index, key in enumerate(fx.place(geo, dict(alloc.home_keys))):
            if 0 <= key < geo.total_keys and key not in taken:
                alloc.fixtures[key] = (pid, fx, index)
                taken.add(key)
    alloc.pool = [
        k for k in range(geo.cols, geo.total_keys) if k not in taken
    ]
    return alloc


class Home:
    def __init__(self, geo, plugins):
        self.geo = geo
        alloc = allocate(geo, plugins)
        self.home_keys = alloc.home_keys
        self.buttons = alloc.buttons
        self.fixtures = alloc.fixtures
        self.pool = alloc.pool
        self.providers = sorted(
            (
                (tp.order, lp.id, tp)
                for lp in plugins
                for tp in lp.plugin.tiles
            ),
            key=lambda t: (t[0], t[1]),
        )
        self.tile_map = {}

    def _fill(self, kernel):
        """items() of every provider, every render, even with no free
        key: a provider may prune its own state there."""
        tile_map = {}
        cursor = 0
        for _, pid, tp in self.providers:
            ok, items = kernel.guard(pid, "tiles", tp.items, kernel.ctx(pid))
            for item in (items or []) if ok else []:
                if cursor >= len(self.pool):
                    break
                tile_map[self.pool[cursor]] = (pid, tp, item)
                cursor += 1
        self.tile_map = tile_map

    def _face(self, kernel, key):
        if key in self.buttons:
            pid, button = self.buttons[key]
            ok, face = kernel.guard(
                pid, "home face", button.face, kernel.ctx(pid)
            )
        elif key in self.fixtures:
            pid, fx, index = self.fixtures[key]
            ok, face = kernel.guard(
                pid, "fixture face", fx.face, kernel.ctx(pid), key, index
            )
        elif key in self.tile_map:
            pid, tp, item = self.tile_map[key]
            ok, face = kernel.guard(
                pid, "tile face", tp.face, kernel.ctx(pid), item
            )
        elif key == 0 and not kernel.dbus_ok:
            return KeyFace(colors.ERR, i18n.t("NO\nEXT"))
        else:
            return EMPTY
        return face if ok and face is not None else EMPTY

    def render(self, kernel):
        self._fill(kernel)
        for key in range(self.geo.total_keys):
            kernel.paint(key, self._face(kernel, key))

    def press(self, kernel, key):
        """The press of what `key` showed; the callee renders. A press
        that raises flashes ERR."""
        if key in self.buttons:
            pid, button = self.buttons[key]
            call = (pid, "home press", button.press, kernel.ctx(pid))
        elif key in self.fixtures:
            pid, fx, index = self.fixtures[key]
            call = (pid, "fixture press", fx.press, kernel.ctx(pid), key,
                    index)
        elif key in self.tile_map:
            pid, tp, item = self.tile_map[key]
            call = (pid, "tile press", tp.press, kernel.ctx(pid), item)
        else:
            return
        ok, _ = kernel.guard(*call)
        if not ok:
            kernel.set_flash(False)
            kernel.render()
```

- [ ] **Step 4: Run** `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_home.py test/test_erplibre_streamdeck_kernel.py`
  Expected: PASS. Fix any expectation in `AllocationTest.EXPECT` only
  against the goldens of Task 3 (`home__full` screens), never by guess.

- [ ] **Step 5: Commit** `[ADD] stream_deck: home screen allocation and
  dashboard`.

### Task 7: Loader, app, `__main__`, `--list-plugins`

**Files:**
- Create: `.../erplibre_streamdeck/loader.py`, `app.py`, `__main__.py`,
  `plugins/__init__.py`
- Create: `test/test_erplibre_streamdeck_loader.py`

**Interfaces:**
- Consumes: Tasks 4-6.
- Produces: `loader.ID_RE`, `loader.REPO_DIR`,
  `loader.parse_off(text) -> list`, `loader.load(off=(), repo_dir=None,
  user_dir=None) -> (list[LoadedPlugin], Report)`, `Report.entries`
  (`[(id, status, detail)]`, status in `active`, `off`, `refused`,
  `replaced by user`), `Report.lines()`; `app.build(deck, *,
  plugins_off=(), user_dir=None) -> Kernel`, `app.read_plugins_off()`,
  `app.main()`; `__main__.main()`, `__main__.list_plugins()`.

- [ ] **Step 1: Write the failing tests**
  `test/test_erplibre_streamdeck_loader.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Plugin discovery: both directories, refusals, DECK_PLUGINS_OFF."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import loader  # noqa: E402

GOOD = (
    "from erplibre_streamdeck.plugin import Page, Plugin, PLUGIN_API\n"
    "PLUGIN = Plugin(api=PLUGIN_API, pages=[Page({page!r}, None, "
    "print, print)])\n"
)


class LoaderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name, "repo")
        self.user = Path(tmp.name, "user")
        self.repo.mkdir()
        self.user.mkdir()

    def put(self, where, name, text):
        (where / name).write_text(text, encoding="utf-8")

    def load(self, off=()):
        return loader.load(off=off, repo_dir=self.repo, user_dir=self.user)

    def status(self, report):
        return {e[0]: (e[1], e[2]) for e in report.entries}


class LoaderTest(LoaderCase):
    def test_both_directories_sorted(self):
        self.put(self.repo, "beta.py", GOOD.format(page="b"))
        self.put(self.user, "alpha.py", GOOD.format(page="a"))
        plugins, _ = self.load()
        self.assertEqual(["alpha", "beta"], [p.id for p in plugins])
        self.assertEqual(["user", "repo"], [p.origin for p in plugins])

    def test_skips_underscore_and_refuses_bad_stem(self):
        self.put(self.repo, "_helper.py", "raise SystemExit\n")
        self.put(self.repo, "Bad-Name.py", GOOD.format(page="x"))
        plugins, report = self.load()
        self.assertEqual([], plugins)
        self.assertEqual("refused", self.status(report)["Bad-Name"][0])
        self.assertNotIn("_helper", self.status(report))

    def test_broken_user_plugin_is_refused(self):
        self.put(self.user, "broken.py", "def (:\n")
        self.put(self.repo, "fine.py", GOOD.format(page="f"))
        plugins, report = self.load()
        self.assertEqual(["fine"], [p.id for p in plugins])
        status, detail = self.status(report)["broken"]
        self.assertEqual("refused", status)
        self.assertIn("SyntaxError", detail)

    def test_missing_plugin_and_wrong_api(self):
        self.put(self.repo, "none.py", "X = 1\n")
        self.put(
            self.repo,
            "old.py",
            "from erplibre_streamdeck.plugin import Plugin\n"
            "PLUGIN = Plugin(api=0)\n",
        )
        _, report = self.load()
        st = self.status(report)
        self.assertEqual(("refused", "no PLUGIN"), st["none"])
        self.assertEqual("refused", st["old"][0])
        self.assertIn("api 0", st["old"][1])

    def test_duplicate_page_id(self):
        self.put(self.repo, "a.py", GOOD.format(page="same"))
        self.put(self.repo, "b.py", GOOD.format(page="same"))
        plugins, report = self.load()
        self.assertEqual(["a"], [p.id for p in plugins])
        self.assertIn("same", self.status(report)["b"][1])

    def test_user_replaces_repo_and_off_turns_both_off(self):
        self.put(self.repo, "dup.py", GOOD.format(page="r"))
        self.put(self.user, "dup.py", GOOD.format(page="u"))
        plugins, report = self.load()
        self.assertEqual("user", plugins[0].origin)
        self.assertIn("replaced by user", [e[1] for e in report.entries])
        plugins, report = self.load(off=["dup"])
        self.assertEqual([], plugins)
        self.assertEqual("off", self.status(report)["dup"][0])

    def test_parse_off(self):
        self.assertEqual(
            ["a", "b_c"], loader.parse_off(" a , ,b_c,\n")
        )


class ListPluginsTest(unittest.TestCase):
    def test_list_plugins_from_another_cwd(self):
        """Run through the real interpreter in a scratch cwd: the
        package's own sys.path setup must find everything. Skipped
        without the Stream Deck venv (Pillow, StreamDeck)."""
        python = S.ROOT / ".venv.streamdeck" / "bin" / "python"
        if not python.exists():
            self.skipTest("no .venv.streamdeck")
        with tempfile.TemporaryDirectory() as cwd:
            done = subprocess.run(
                [str(python), str(S.PACKAGE), "--list-plugins"],
                cwd=cwd, capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(0, done.returncode, done.stderr)
        for path in loader.REPO_DIR.glob("*.py"):
            if not path.name.startswith("_"):
                self.assertIn(f"{path.stem}: active", done.stdout)


if __name__ == "__main__":
    unittest.main()
```

  (Without `.venv.streamdeck` the last test is skipped.)

- [ ] **Step 2: Run** the loader tests. Expected: FAIL (no `loader`).

- [ ] **Step 3: Write `loader.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Discovery of the deck plugins.

Two directories: the package's plugins/, then the user's
$XDG_CONFIG_HOME/erplibre-home/deck-plugins/. A plugin's id is its file
stem ([a-z][a-z0-9_]*); files starting with "_" are skipped. A user
plugin replaces a repository plugin of the same id. An id listed in
DECK_PLUGINS_OFF is not imported. A plugin is refused, with its reason
in the report, when its import raises, it has no PLUGIN, its api is not
PLUGIN_API, or one of its pages is already taken; the others load."""

import importlib
import importlib.util
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import LoadedPlugin, Plugin, PLUGIN_API

ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
REPO_DIR = Path(__file__).resolve().parent / "plugins"
USER_PACKAGE = "erplibre_streamdeck_user"


@dataclass
class Report:
    entries: list = field(default_factory=list)

    def add(self, pid, status, detail=""):
        self.entries.append((pid, status, detail))

    def lines(self):
        out = []
        for pid, status, detail in self.entries:
            out.append(f"{pid}: {status}" + (f": {detail}" if detail else ""))
        return out


def parse_off(text):
    return [part.strip() for part in text.split(",") if part.strip()]


def _files(directory):
    if directory is None or not Path(directory).is_dir():
        return []
    return sorted(
        p for p in Path(directory).glob("*.py")
        if not p.name.startswith("_")
    )


def _import(pid, path, by_name):
    """The package's own plugins import by module name, so they share
    the package's module identity; any other file imports by path."""
    if by_name:
        return importlib.import_module(f"erplibre_streamdeck.plugins.{pid}")
    if USER_PACKAGE not in sys.modules:
        sys.modules[USER_PACKAGE] = types.ModuleType(USER_PACKAGE)
    name = f"{USER_PACKAGE}.{pid}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load(off=(), repo_dir=None, user_dir=None):
    repo_dir = REPO_DIR if repo_dir is None else repo_dir
    user_dir = paths.user_plugin_dir() if user_dir is None else user_dir
    report = Report()
    chosen = {}
    for origin, directory in (("repo", repo_dir), ("user", user_dir)):
        for path in _files(directory):
            pid = path.stem
            if not ID_RE.match(pid):
                report.add(pid, "refused", "file name is not a plugin id")
                continue
            if pid in chosen and origin == "user":
                report.add(pid, "replaced by user", str(chosen[pid][1]))
            chosen[pid] = (origin, path)
    off = set(off)
    loaded, pages = [], {}
    for pid in sorted(chosen):
        origin, path = chosen[pid]
        if pid in off:
            report.add(pid, "off")
            continue
        by_name = origin == "repo" and Path(repo_dir) == REPO_DIR
        try:
            module = _import(pid, path, by_name)
        except Exception as exc:
            report.add(pid, "refused", f"import: {type(exc).__name__}: {exc}")
            continue
        plugin = getattr(module, "PLUGIN", None)
        if not isinstance(plugin, Plugin):
            report.add(pid, "refused", "no PLUGIN")
            continue
        if plugin.api != PLUGIN_API:
            report.add(
                pid, "refused", f"api {plugin.api} != {PLUGIN_API}"
            )
            continue
        clash = [p.id for p in plugin.pages if p.id in pages]
        if clash:
            report.add(
                pid,
                "refused",
                f"page {clash[0]} already taken by {pages[clash[0]]}",
            )
            continue
        for page in plugin.pages:
            pages[page.id] = pid
        loaded.append(LoadedPlugin(pid, plugin, origin, path))
        report.add(pid, "active", origin)
    return loaded, report
```

- [ ] **Step 4: Write `app.py`:**

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Start of the deck program: find the deck, build the kernel, run.

build() is what a test drives: the style restored from settings.json,
the plugins loaded, the kernel made, without the lock file, the signal
handler or the loop thread."""

import subprocess
import sys
import threading
import time

try:
    from StreamDeck.DeviceManager import DeviceManager
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

import deck_lock

from erplibre_streamdeck import loader, paths, settings
from erplibre_streamdeck.kernel import Kernel
from erplibre_streamdeck.ui import render


def read_plugins_off():
    """DECK_PLUGINS_OFF from streamdeck.conf, read by the settings
    library the installer and the service use; [] when it cannot be
    read (one journal line)."""
    try:
        done = subprocess.run(
            ["bash", "-c", '. "$0" && deck_plugins_off',
             str(paths.SETTINGS_LIB)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[erplibre-home] DECK_PLUGINS_OFF unreadable: {exc}",
              file=sys.stderr, flush=True)
        return []
    return [line for line in done.stdout.splitlines() if line]


def build(deck, *, plugins_off=(), user_dir=None):
    render.STYLE.restore(settings.load())
    plugins, report = loader.load(off=plugins_off, user_dir=user_dir)
    for pid, status, detail in report.entries:
        if status != "active":
            print(f"[erplibre-home] plugin {pid}: {status}: {detail}",
                  file=sys.stderr, flush=True)
    kernel = Kernel(deck, plugins)
    for pid, reason in kernel.refused:
        print(f"[erplibre-home] plugin {pid}: refused: {reason}",
              file=sys.stderr, flush=True)
    return kernel


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(deck_lock.NO_DECK_EXIT)
    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Window Tiler on {deck.deck_type()} ({cols}x{rows})")

    kernel = build(deck, plugins_off=read_plugins_off())
    if kernel.dbus_ok:
        print("D-Bus tiler extension detected!")
    else:
        print("WARNING: erplibre-home extension not found.",
              file=sys.stderr, flush=True)
        print("Install: re-login to GNOME to activate the extension.")
    print("Press TILE to enter tiling mode (first corner, second corner).")
    print("Press TIMER to list and toggle tracker timers.")

    kernel.render()

    def key_cb(d, k, s):
        with kernel.lock:
            kernel.handle_key(k, s)

    deck.set_key_callback(key_cb)
    threading.Thread(target=kernel.loop, daemon=True).start()
    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        kernel.running = False
        kernel.shutdown()
        with deck:
            deck.reset()
            deck.close()
```

- [ ] **Step 5: Write `__main__.py`:**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Stream Deck — the deck program of ERPLibre Home.

Run as a directory: python script/stream_deck/erplibre_streamdeck. It is
the erplibre-home-streamdeck user service (DECK_PROGRAM=tiler) and
`make streamdeck_erplibre`. --list-plugins prints what the loader finds,
without opening the deck or taking its lock.

Python puts this directory first on sys.path; it is replaced by its
parent, script/stream_deck/, where the package, deck_lock and
translator live."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [
    p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE
]
sys.path.insert(0, os.path.dirname(_HERE))

import deck_lock  # noqa: E402

from erplibre_streamdeck import app, loader  # noqa: E402


def main():
    deck_lock.acquire_or_exit("tiler")
    deck_lock.exit_on_sigterm()
    app.main()


def list_plugins():
    _, report = loader.load(off=app.read_plugins_off())
    for line in report.lines():
        print(line)
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--list-plugins"]:
        sys.exit(list_plugins())
    main()
```

  and `plugins/__init__.py` (header + docstring "The repository's deck
  plugins; one file per plugin, the file name is the id.").

- [ ] **Step 6: Make the harness boot the package.** With `app.py`
  present, `PackagePages` stops skipping: every page scenario skips on
  `has_page` (no plugin yet). Run
  `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_loader.py test/test_erplibre_streamdeck_pages.py test/test_erplibre_streamdeck_kernel.py test/test_erplibre_streamdeck_home.py`
  Expected: loader tests pass (ListPluginsTest per its note);
  PackagePages all skipped; others pass.

- [ ] **Step 7: Commit** `[ADD] stream_deck: plugin loader, app and
  package entry point`.

### Task 8: Plugins `a11y`, `bluetooth`, `sound`

**Files:**
- Create: `.../plugins/a11y.py`, `bluetooth.py`, `sound.py`
- Create: `test/test_erplibre_streamdeck_backends.py`

Source map: `map-a11y_bt_sound.md` (sections 1-7 give every function,
line range, key layout and the draft modules; section 8 the traps).
Rules for the port, every plugin task:

- move the module functions of the domain into the plugin module
  (private names keep a leading underscore), bodies unchanged except
  the renames of the ui/paths/dbus modules and `self.X` → the plugin's
  state (`ctx.state().X`) or `ctx.geo`/`ctx.keys`;
- each `_compute_*_buttons` becomes the page's `keys(geo)`, pure;
- each `_render_*` becomes `render(ctx)`, each `_handle_*_key` becomes
  `handle(ctx, key)`: `self.mode = X; self.render()` → `ctx.goto(X)`;
  `self.mode = MODE_IDLE; self.render()` → `ctx.home()`;
  `self.last_result = ...; self.result_time = ...` → `ctx.flash(ok)`;
  `self._flag_err(reason)` → `ctx.flash(False, reason)`; a plain
  `self.render()` → `ctx.render()`;
  `set_key(self.deck, ...)` → `ctx.set_key(...)`; `_t` → `ctx.t`;
- the DECK TOO SMALL block → `render.too_small(ctx)`;
- one commit per plugin, each green on its page goldens.

Plugin declarations:

- `a11y`: page `a11y` (keys from `_compute_a11y_buttons`, render
  `_render_a11y`, handle `_handle_a11y_key` using `ctx.style.
  set_font_scale(.., ctx.settings)` / `toggle_labels(ctx.settings)`);
  `home_button=HomeButton(60, face=KeyFace(colors.A11Y_TITLE, "A11Y",
  icon="a11y"), press=ctx.goto("a11y"))`. Keep the key insertion order
  (back, down, up, reset, scale, labels): at 5x3 the scale label lands
  on FONT+ (`map-a11y_bt_sound.md` T4), as today.
- `bluetooth`: page `bluetooth`; home button order 70, `KeyFace(colors.
  BT_TITLE, "BT", icon="bt")`; the `bluetoothctl`/`rfkill` helpers.
- `sound`: page `sound`; home button order 40 (`colors.SOUND_TITLE`,
  `ctx.t("SOUND")`, `icon="sound"`); fixture order 10 for the mic:
  place `[(rows-1)*cols]` when `rows >= 2`, face from `_mic_indicator`,
  press `_wpctl_mute_toggle(WPCTL_SOURCE)` then `ctx.render()`; the
  `wpctl` helpers, `VOL_STEP_PCT`, `WPCTL_SINK/SOURCE`.

- [ ] **Step 1: Write the failing backend tests** (parsers that have no
  test today) in `test/test_erplibre_streamdeck_backends.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Parsers of the system tools the deck plugins read."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import settings  # noqa: E402
from erplibre_streamdeck.plugins import bluetooth, sound  # noqa: E402
from erplibre_streamdeck.ui import render  # noqa: E402

WPCTL_STATUS = """\
Audio
 ├─ Devices:
 │      40. Built-in Audio                      [alsa]
 │
 ├─ Sinks:
 │  *   51. Built-in Audio Analog Stereo        [vol: 0.40]
 │      62. Demo Headset                        [vol: 0.70]
 │
 ├─ Sources:
 │  *   52. Built-in Audio Analog Stereo        [vol: 1.00 MUTED]
 │
 ├─ Filters:
"""


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


class WpctlTest(unittest.TestCase):
    def test_get_volume_and_mute(self):
        with mock.patch(
            "subprocess.run", return_value=done("Volume: 0.50 [MUTED]\n")
        ):
            self.assertEqual((50, True), sound._wpctl_get("@X@"))

    def test_get_malformed(self):
        with mock.patch("subprocess.run", return_value=done("garbage")):
            vol, muted = sound._wpctl_get("@X@")
        self.assertIsNone(vol)

    def test_list_devices(self):
        with mock.patch("subprocess.run", return_value=done(WPCTL_STATUS)):
            sinks = sound._wpctl_list_devices("Sinks")
        self.assertEqual([51, 62], [d[0] for d in sinks])
        self.assertEqual([True, False], [d[2] for d in sinks])


class BluetoothTest(unittest.TestCase):
    def test_powered_from_bluetoothctl(self):
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch(
                    "subprocess.run",
                    return_value=done("Controller 00:00:5E:00:53:01\n"
                                      "\tPowered: yes\n"),
                ):
            self.assertIs(True, bluetooth._bt_powered())


class SettingsKeepTest(unittest.TestCase):
    def test_font_scale_save_keeps_other_keys(self):
        stored = {"translator_llm": "ollama", "font_scale": 1.0}

        def save(data):
            stored.clear()
            stored.update(data)

        with mock.patch.object(settings, "load", lambda: dict(stored)), \
                mock.patch.object(settings, "save", save):
            render.Style().set_font_scale(1.2, settings)
        self.assertEqual("ollama", stored["translator_llm"])
        self.assertEqual(1.2, stored["font_scale"])


if __name__ == "__main__":
    unittest.main()
```

  Before writing the assertions on `_wpctl_get` and
  `_wpctl_list_devices`, read their bodies (`map-a11y_bt_sound.md` §1)
  and set the expected tuple shapes to what they return today; the test
  must pin today's behaviour, not a wished one.

- [ ] **Step 2:** Port `a11y` → run
  `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_pages.py`
  (Expected: `a11y__actions` package parity passes, others skipped) →
  commit `[REF] stream_deck: a11y page as a deck plugin`.
- [ ] **Step 3:** Port `bluetooth` → run pages + backends → commit
  `[REF] stream_deck: Bluetooth page as a deck plugin`.
- [ ] **Step 4:** Port `sound` → run pages + backends → commit
  `[REF] stream_deck: sound page and mic key as a deck plugin`.

### Task 9: Plugins `layouts`, `tiling`, `dev_reload`

Source map: `map-layouts_tiling_reload.md`. Same port rules as Task 8.

- `layouts`: pages `layout` and `layout_delete_confirm`; state
  `pending` (from `layout_delete_pending`); home button order 50
  (`colors.LAYOUT_TITLE`, `ctx.t("LAYOUT")`, `icon="layout"`); fixture
  order 20: place `[(rows-1)*cols + lk + i for i in range(3)]` when
  `lk = home_keys.get("layouts", -1) >= 0`, `rows >= 2` and
  `lk + NUM_LAYOUT_SLOTS <= cols`; face `KeyFace(colors.LOAD_FILLED,
  f"*\n{index+1}")` when slot `index+1` is filled, else `None`; press:
  empty slot → return (no render, no flash); `_load_layout_slot` ok →
  `ctx.flash(True)`, else `ctx.flash(False, f"layout shortcut load slot
  {slot} failed")`; then `ctx.render()`. `layouts.json` through
  `paths.LAYOUTS_FILE`; D-Bus `ListWindows` (3 s) and `ApplyLayout`
  (10 s) through `ctx.dbus.call`, parsing as today (`Reply.string`,
  `re.search(r"\((\d+),\)", reply.stdout)`).
- `tiling`: page `tiling` with `tick` (period 0.0) for the 5 s timeout
  measured from `state().last_touch`; state `corner1`, `last_touch`;
  home button order 10 (`colors.TITLE`, `ctx.t("TILE")`, `icon="tile"`)
  whose press sets `corner1=None`, `last_touch=time.monotonic()`,
  `ctx.goto("tiling")`; `TileWindow` (3 s) via `ctx.dbus.call(...).true`.
- `dev_reload`: home button order 30 (`colors.DEV_RELOAD`,
  `"DEV\nRELOAD"`, `icon="dev_reload"`), press: HotReload (10 s) →
  `ctx.flash(ok)` (no reason), `ctx.render()`.

- [ ] **Step 1:** Port `layouts`; test: add to
  `test/test_erplibre_streamdeck_backends.py` a test that
  `_save_layout_slot` then `_load_layout_slot` round-trips through a
  temporary `paths.LAYOUTS_FILE` (patch `paths.LAYOUTS_FILE` and
  `paths.CONFIG_DIR`) with `ListWindows` answering
  `('[{"id": "1", "x": 0}]',)` and `ApplyLayout` answering `(1,)`;
  run pages + backends; commit `[REF] stream_deck: layouts as a deck
  plugin`.
- [ ] **Step 2:** Port `tiling`; run pages; commit `[REF] stream_deck:
  window tiling as a deck plugin`.
- [ ] **Step 3:** Port `dev_reload`; run pages; commit `[REF]
  stream_deck: extension reload key as a deck plugin`.

### Task 10: Plugin `timers`

Source map: `map-timers.md`. Same port rules.

- pages `timer_list` (keys=None: the key map comes from `_refresh_timers`
  into `state().key_map`; tick period 2.0: refresh then `ctx.render()`)
  and `timer_reset_confirm`;
- state `timers` (`[]`), `key_map` (`{}`), `hidden` (`set()`), set in
  `setup` without any D-Bus call;
- home button order 20 (`colors.TIMER_TITLE`, `ctx.t("TIMER")`,
  `icon="timer"`), press = refresh + `ctx.goto("timer_list")`;
- tile provider order 30: `items` prunes `hidden &= running ids` then
  returns the running timers not hidden (called every home render);
  face `KeyFace(colors.TIMER_RUNNING, _label_for_timer(t),
  icon="timer")`; press = refresh + `ctx.goto("timer_list")`;
- `home_tick` with `home_period=2.0`: refresh, return False (the
  kernel's home refresh renders);
- export: `zenity` and the CSV writer unchanged; failure
  `ctx.flash(False)` with no reason; reset confirm calls `ctx.flash`
  then `ctx.goto("timer_list")`.

- [ ] **Step 1:** Add to the backends test: `_label_for_timer({"name":
  "Write report", "elapsed": 125})` → `"Write\n02:05"`; a tracker answer
  `('[{"id": "t1", "running": true}]',)` gives one timer.
- [ ] **Step 2:** Port; run pages + backends; commit `[REF] stream_deck:
  tracker timers as a deck plugin`.

### Task 11: Plugin `translate`

Source map: `map-translate.md`. Same port rules, plus:

- module `plugins/translate.py` does `import translator` at top and calls
  `translator.X` at call time;
- pages `translator` (tick period 0.0: VAD flag or
  `translator.recording_timeout_seconds()` → `_toggle_record`) and
  `translator_history`;
- home button order 80 (`colors.TR_TITLE`, `ctx.t("TRANSL")`,
  `icon="translator"`);
- `setup`: backend detection and the restore from
  `ctx.settings.load()` (the four `translator_*` keys), into `state()`;
- `shutdown`: terminate the streaming process as `main` does today
  (terminate, wait 2 s, kill);
- the transcription thread ends with `with ctx.locked(): ctx.flash(ok);
  if ctx.page == "translator": ctx.render()`;
- `translator_stream.py` through `os.fspath(paths.STREAM_DECK_DIR /
  "translator_stream.py")`, read inside the function.

- [ ] **Step 1:** Port; run pages (`translator__record`,
  `translator__vad_timeout`, `translator_history`) + the full suite;
  commit `[REF] stream_deck: translator pages as a deck plugin`.

### Task 12: Plugins `mpv_sessions`, `claude_sessions`

Source map: `map-sessions.md` (draft modules in §7). Same port rules:

- tile providers order 10 (mpv) and 20 (claude); pages `mpv_session`
  and `claude_session`; state `pid` / `sid`;
- state directories from `paths.state_dir() / "mpv"` and `/ "claude"`,
  read at call time;
- D-Bus calls `ctx.dbus.call(method, ..., timeout=2).true`;
- `claude_sessions` exports `session_color` and `session_label` (from
  `_claude_color`, `_claude_label`) and the colours stay
  `colors.CLAUDE_*`.

- [ ] **Step 1:** Re-point `ClaudeColorTest` and `ClaudeLabelTest` in
  `test/test_erplibre_streamdeck_text.py` to
  `erplibre_streamdeck.plugins.claude_sessions`. Add to the backends
  test `test_bad_pid_file_is_skipped_or_isolated`: a claude state file
  with `"pid": "abc"` → `load_sessions()` raises or skips it; then a
  `Kernel` built with the plugin renders home twice and the journal
  holds at most one `claude_sessions` line.
- [ ] **Step 2:** Port `mpv_sessions`; run pages; commit `[REF]
  stream_deck: mpv sessions as a deck plugin`.
- [ ] **Step 3:** Port `claude_sessions`; run pages + text + backends;
  commit `[REF] stream_deck: Claude sessions as a deck plugin`.

### Task 13: Plugin `todo_terminals`, home parity

Source map: `map-todo_terminals.md`. Same port rules, plus:

- home button order 90 (`colors.TIMER_TITLE`, `ctx.t("TODO")`, no
  icon), press = `_launch_todo_terminal`;
- page `todo_session` (keys=None, computed per call; tick period 1.0:
  refresh the registry, `ctx.home()` when the window is gone, else
  `ctx.render()`);
- tile provider order 40 over `state().terminals` (memory, never read
  from disk at render);
- `home_tick` with `home_period=0.0`: the pending capture when due
  (returns True when it ran), and the registry refresh every 2 s gated
  by `state().last_refresh` (returns False);
- repository root from `paths.REPO_ROOT`, read inside
  `_launch_todo_terminal`; `FocusWindowById`, `ListWindows`,
  `GetFocusedWindowId`, `SendKeysToWindow` through `ctx.dbus.call`
  (timeout 2).

- [ ] **Step 1:** Re-point `TodoMenuParseTest` to
  `erplibre_streamdeck.plugins.todo_terminals`.
- [ ] **Step 2:** Port. Now every repository plugin loads: the
  `home__*`, `flash` and `todo_launch` package scenarios run in full,
  and `partial` turns off. Run
  `./script/test/run_unit_test.sh test/test_erplibre_streamdeck_pages.py`
  Expected: MonolithPages and PackagePages all pass, nothing skipped.
- [ ] **Step 3:** Add the package-only test of the deliberate change
  (`test/test_erplibre_streamdeck_home.py` or the pages file): render
  home with the FULL world, add a second mpv session file, tap the first
  dashboard key → page `mpv_session` with the pid the key SHOWED.
- [ ] **Step 4:** Commit `[REF] stream_deck: TODO terminals as a deck
  plugin`.

### Task 14: Switch — the package becomes the deck program

**Files:**
- Modify: `script/install/erplibre_home_settings.sh` (`deck_program_path`)
- Modify: `conf/make.streamdeck.Makefile` (`streamdeck_erplibre` recipe)
- Modify: `test/test_deck_lock.py`, `test/test_erplibre_home_deck.py`,
  `test/test_streamdeck_entry_points.py`,
  `test/test_streamdeck_games_layout.py` (optional line),
  `test/test_erplibre_streamdeck_pages.py`, `test/test_erplibre_streamdeck_text.py`,
  `test/streamdeck_stubs.py`
- Delete: `script/stream_deck/erplibre_streamdeck.py`

Exact line changes: `map-tests.md` §9. In short:

- `deck_program_path`: `tiler) echo "script/stream_deck/erplibre_streamdeck" ;;`
- Makefile: `$(STREAMDECK_PY) script/stream_deck/erplibre_streamdeck`
- `test_deck_lock.py`: read `erplibre_streamdeck/__main__.py` for
  `main.body[0..1]`, with `assertRegex(source, r"(?m)^import deck_lock\b")`
  in place of the exact `"\nimport deck_lock\n"`; read
  `erplibre_streamdeck/app.py` for the no-deck block.
- `test_erplibre_home_deck.py`: the expected argv and mapping use
  `script/stream_deck/erplibre_streamdeck`; the "names a file" test
  accepts `chemin.is_file() or (chemin / "__main__.py").is_file()`.
- `test_streamdeck_entry_points.py`: `"streamdeck_erplibre":
  "erplibre_streamdeck"`, and assert no `.py` follows it.
- Pages: delete `MonolithPages`; `PackagePages` stays and is the guard.
- `streamdeck_stubs.py`: remove `MonolithTarget`, `load_monolith`,
  `MONOLITH`, `MONOLITH_NAME`, and the `update` branch of
  `check_golden` (goldens are frozen; a later deliberate change edits
  the JSON).
- `test_erplibre_streamdeck_text.py`: no `GT` left (all classes point at
  package modules by now); drop `load_monolith`.

- [ ] **Step 1:** Make every change above in the working tree, `git rm`
  the single file.
- [ ] **Step 2: Run** the full suite `./script/test/run_unit_test.sh`.
  Expected: all green. Then
  `grep -rn "erplibre_streamdeck\.py" --include=*.py --include=*.sh --include=Makefile --include=*.js . | grep -v docs/superpowers`
  Expected: no hit outside the docs Task 16 updates.
- [ ] **Step 3:** If `.venv.streamdeck` exists:
  `.venv.streamdeck/bin/python script/stream_deck/erplibre_streamdeck --list-plugins`
  Expected: 11 lines `<id>: active: repo`.
- [ ] **Step 4: Commit** (one commit) `[REF] stream_deck: deck program
  runs from the erplibre_streamdeck package`.

### Task 15: `DECK_PLUGINS_OFF`

**Files:**
- Modify: `script/install/erplibre_home_settings.sh` (`deck_plugins_off`)
- Modify: `script/todo/erplibre_home_service.py`
- Modify: `script/todo/streamdeck_menu.py` (entry [12])
- Modify: `script/todo/erplibre_home_status.py`
- Modify: `script/todo/todo_i18n.py`
- Tests: `test/test_erplibre_home_service.py`,
  `test/test_todo_streamdeck_menu.py`, `test/test_erplibre_home_status.py`,
  a shell test in `test/test_erplibre_home_deck.py` (or the file that
  tests `erplibre_home_settings.sh`)

**Interfaces:**
- Produces: shell `deck_plugins_off` (one normalised id per line);
  Python `DEFAULTS["DECK_PLUGINS_OFF"] = ""`,
  `plugins_off(settings) -> list`, `deck_plugin_ids(repo_root,
  environ=None) -> list` (stems of `script/stream_deck/
  erplibre_streamdeck/plugins/*.py` and of the user directory, no `_`
  files, sorted, unique).

- [ ] **Step 1: Failing tests.** Shell/Python parity on these values:
  `""` → `[]`; `"tiling"` → `["tiling"]`; `" a , ,b_c,"` →
  `["a", "b_c"]`; a value with `\r` → the `\r` is stripped as
  whitespace. `deck_plugin_ids` on a temporary repository and user dir
  returns the merged sorted stems. Menu: entry [12] lists ids with
  `on`/`off`, toggling writes `DECK_PLUGINS_OFF` with
  `settings_text`, and offers the restart only when the unit is active
  (template: the Games entry [11] tests). Status: `Plugins off: a, b`
  line when non-empty; diagnosis line `Unknown plugin in
  DECK_PLUGINS_OFF: x` for an id with no file. i18n: fr and en for
  every new string (the existing completeness test enforces it).
- [ ] **Step 2: Implement.** Shell:

```bash
# deck_plugins_off écrit, un par ligne, les identifiants de plugins que
# DECK_PLUGINS_OFF coupe : la valeur se coupe aux virgules, chaque
# morceau perd ses blancs, un morceau vide est ignoré.
deck_plugins_off() {
    local value part
    value="$(deck_setting DECK_PLUGINS_OFF "")"
    IFS=',' read -r -a parts <<<"${value}"
    for part in "${parts[@]}"; do
        part="${part//[[:space:]]/}"
        [ -n "${part}" ] && echo "${part}"
    done
    return 0
}
```

  Python in `erplibre_home_service.py`:

```python
def plugins_off(settings):
    """The ids DECK_PLUGINS_OFF turns off, as deck_plugins_off of the
    shell: split on commas, white space dropped, empty parts ignored."""
    value = settings.get("DECK_PLUGINS_OFF", "")
    return [
        "".join(part.split())
        for part in value.split(",")
        if "".join(part.split())
    ]


def deck_plugin_ids(repo_root, environ=None):
    """Ids of the deck plugins on disk: the repository's and the
    user's, without importing them (their imports need the Stream
    Deck venv)."""
    dirs = [
        os.path.join(
            repo_root, "script", "stream_deck", "erplibre_streamdeck",
            "plugins",
        ),
        os.path.join(config_home(environ), "erplibre-home", "deck-plugins"),
    ]
    ids = set()
    for directory in dirs:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.endswith(".py") and not name.startswith("_"):
                ids.add(name[:-3])
    return sorted(ids)
```

  Menu, status, i18n: follow the Games entry ([11],
  `_streamdeck_games_setting`) and the `Games:` status line added by B1
  as templates.
- [ ] **Step 3: Run** the touched test files, then the full suite.
- [ ] **Step 4: Commit** `[ADD] stream_deck: DECK_PLUGINS_OFF setting,
  TODO entry and status`.

### Task 16: Docs and spec amendments

**Files:**
- Modify: `script/stream_deck/README.base.md` (package layout, "Writing a
  plugin" with a 20-line example plugin, user directory, trust note:
  user plugins run in the deck service with the user's rights),
  `INSTALL.base.md` (path, `DECK_PLUGINS_OFF`, `--list-plugins`),
  `gpt.base.md`, `CHANGELOG.base.md` (old → new path, the setting, the
  user directory, the deliberate tap change); regenerate with mmg
- Modify: `script/gnome-extension/erplibre_home/ARCHITECTURE.md`,
  `DEBUG.md`, `lib/mpv-state.js:15` (reader is now
  `erplibre_streamdeck/plugins/mpv_sessions.py`)
- Modify: the spec — add a section "Amendments from the plan" copying
  the 15 rulings above.

- [ ] **Step 1:** Write the docs; `source .venv.erplibre/bin/activate && mmg --yes`.
- [ ] **Step 2:** `grep -rn "erplibre_streamdeck\.py" script/ conf/ *.md | grep -v CHANGELOG`
  Expected: no hit (the CHANGELOG names the old path on purpose).
- [ ] **Step 3:** Full suite + `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js`.
- [ ] **Step 4: Commit** `[UPD] doc: deck program as a plugin package,
  DECK_PLUGINS_OFF, user plugins`.
