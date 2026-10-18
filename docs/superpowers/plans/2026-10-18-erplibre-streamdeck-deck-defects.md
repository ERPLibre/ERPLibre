# ERPLibre Stream Deck deck defects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slow key actions run off the kernel lock, renders read caches
filled by polls, the deck's JSON files are replaced atomically, recycled
pids no longer keep sessions alive, and the Claude/mpv session pages
refresh every `DECK_SESSION_REFRESH_SEC`.

**Architecture:** The kernel gains a job runner (`ctx.run_blocking`) with a
per-plugin busy mark, and polls (`Plugin.polls`) whose `read` runs in the
loop thread outside the lock. Plugins move their slow calls and their
render-time processes onto these. Two small modules (`jsonfile`,
`liveness`) serve the files and the session loaders. A new setting is read
at start with the existing one.

**Tech Stack:** Python 3 stdlib, bash (`erplibre_home_settings.sh`),
unittest via `./script/test/run_unit_test.sh`, mmg for docs.

**Spec:** `docs/superpowers/specs/2026-10-18-erplibre-streamdeck-deck-defects-design.md`
(builds on `2026-10-18-erplibre-streamdeck-plugin-package-design.md`).

## Global Constraints

- Python lines ≤ 79 columns. Never run black on a whole file. No flake8 is
  installed: check with `awk 'length>79' <file>`.
- Every new file starts with the repo header (`# © 2026 TechnoLibre
  (http://www.technolibre.ca)` / `# License AGPL-3.0 or later
  (http://www.gnu.org/licenses/agpl)`).
- Comments describe how the code works, in the present; no incident,
  date, machine or person. Run
  `python3 script/analyse/check_comment_hygiene.py <files>` before each
  commit.
- Commit message: `[TAG] scope: subject` in English ≤ 72 chars; English
  body, `--- FR ---`, French subject under the same tag, French body; ≤ 8
  lines per language; `Assisted-by: <model>` last; never a Co-Authored-By
  naming an AI. Validate with `python3 script/git/hooks/commit-msg <f>`;
  commit with `git -c user.name="Mathieu Benoit"
  -c user.email="mathben@technolibre.ca" commit --no-verify -F <f>`.
- Stage files by name; never `git add -A`; never push.
- Docs: edit `.base.md`, then `mmg --yes <files>`; the extension's
  `ARCHITECTURE.md`/`DEBUG.md` are edited directly.
- Every module calls `subprocess.run`, `time.monotonic`, `threading.Thread`,
  `shutil.which`, `os.replace` through the module attribute (the test
  harness patches modules).
- A golden rewritten by this plan is rewritten only with
  `STREAMDECK_GOLDEN=update-from-package`, and the commit body lists each
  rewritten golden with its reason (spec "Tests").
- A recorded flash ends a loop pass before any job drain, poll or tick
  (B2 amendment 1, kept).
- `work()` given to `run_blocking` runs without the lock: it may use only
  values captured before the call, plus `ctx.dbus` and `ctx.log` (both
  stateless); never `ctx.state()`, `ctx.set_key`, `ctx.goto`, settings.
- `Poll.read()` takes no argument and never touches `ctx`.

## Review Focus

1. Two quick presses on a slow key (e.g. DEV RELOAD twice): the second
   flashes ERR, the plugin runs once, the result shows once (Task 3
   `test_second_press_on_busy_plugin_flashes_err`).
2. Leaving the page while its job runs (press TILE corner then BACK): the
   result's flash lands, but no "…" is painted on a key of another page
   (Task 3 `test_busy_mark_only_on_its_page`).
3. A poll whose `read` raises every time (wpctl missing): the cache keeps
   its last value, one journal line, the page still renders (Task 4
   `test_failing_read_keeps_cache_and_logs_once`).
4. A session file written while the clock jumped: the 5 s slack keeps a
   live session (Task 2 `test_alive_within_slack`).
5. `DECK_SESSION_REFRESH_SEC=0.1` typed in the TODO entry: refused with
   the range, file unchanged (Task 8 `test_entry_refuses_out_of_range`).

---

### Task 1: B2 leftovers

**Files:**
- Modify: `test/test_erplibre_streamdeck_loader.py` (E303 before `SHAPED`)
- Modify: `script/stream_deck/erplibre_streamdeck/kernel.py`
  (`guard` catches SystemExit; `paint`/`render` draw nothing once
  `running` is false)
- Modify: `script/stream_deck/erplibre_streamdeck/home.py` (face labels
  carry the key)
- Modify: `docs/superpowers/specs/2026-10-18-erplibre-streamdeck-plugin-package-design.md`
  (amendment 20 wording)
- Test: `test/test_erplibre_streamdeck_kernel.py`,
  `test/test_erplibre_streamdeck_home.py`

**Interfaces:** Produces `Kernel.guard` catching `(Exception, SystemExit)`
(never `KeyboardInterrupt`); `Kernel.paint` and `Kernel.render` return
without drawing when `self.running` is false.

- [ ] **Step 1: Failing tests** in `test/test_erplibre_streamdeck_kernel.py`:

```python
class LeftoverTest(KernelCase):
    def test_system_exit_in_handle_is_isolated(self):
        def bye(ctx, key):
            raise SystemExit(3)

        k = self.kernel(self.page_plugin(handle=bye))
        k.goto("pg")
        k.handle_key(1, True)
        self.assertEqual("idle", k.page_id)
        self.assertIn("handle failed", self.journal.getvalue())

    def test_keyboard_interrupt_still_propagates(self):
        def stop(ctx, key):
            raise KeyboardInterrupt

        k = self.kernel(self.page_plugin(handle=stop))
        k.goto("pg")
        with self.assertRaises(KeyboardInterrupt):
            k.handle_key(1, True)

    def test_nothing_painted_after_running_is_false(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        self.deck.screen.clear()
        k.running = False
        k.render()
        self.assertEqual({}, self.deck.screen)
```

  and in `test/test_erplibre_streamdeck_home.py`, a provider whose face
  raises for one item and succeeds for another, rendered three times:
  the journal holds exactly one `tile face <key>` line.

- [ ] **Step 2: Run** both files; expected FAIL on the new tests.
- [ ] **Step 3: Implement.** `guard`: `except (Exception, SystemExit) as
  exc:`. `paint` and `render` start with `if not self.running: return`.
  In `home.py`, the guard labels become `f"home face {key}"`,
  `f"fixture face {key}"`, `f"tile face {key}"`. Remove the extra blank
  line before `SHAPED` in the loader test. In the B2 spec, amendment 20
  reads: "`shutdown(ctx)` runs with the kernel lock held when the app
  takes it within 5 s, and without it otherwise; it never takes
  `ctx.locked()` nor waits for a thread that does."
- [ ] **Step 4: Run** the two files and the full suite; PASS.
- [ ] **Step 5: Commit** `[FIX] stream_deck kernel: SystemExit isolated,
  no paint after stop, keyed face logs`.

### Task 2: Atomic JSON files and process liveness

**Files:**
- Create: `script/stream_deck/erplibre_streamdeck/jsonfile.py`
- Create: `script/stream_deck/erplibre_streamdeck/liveness.py`
- Modify: `settings.py` (`save`), `plugins/layouts.py` (the layouts
  writer), `plugins/todo_terminals.py` (the registry writer),
  `plugins/claude_sessions.py` and `plugins/mpv_sessions.py`
  (`load_sessions`)
- Test: `test/test_erplibre_streamdeck_files.py` (new)

**Interfaces:** Produces `jsonfile.write_atomic(path, data, indent=2)`;
`liveness.started_ms(pid) -> int | None`,
`liveness.alive(pid, born_by_ms, slack_ms=5000) -> bool`,
`liveness.parse_start_ticks(stat_line) -> int`.

- [ ] **Step 1: Failing tests** `test/test_erplibre_streamdeck_files.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Atomic JSON writes and process liveness of the deck package."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import jsonfile, liveness  # noqa: E402


class WriteAtomicTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name, "sub")
        self.path = self.dir / "settings.json"

    def test_writes_and_creates_the_directory(self):
        jsonfile.write_atomic(self.path, {"a": 1})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))

    def test_failure_keeps_old_file_and_no_temp(self):
        jsonfile.write_atomic(self.path, {"a": 1})
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                jsonfile.write_atomic(self.path, {"a": 2})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))
        self.assertEqual(["settings.json"], os.listdir(self.dir))

    def test_unserialisable_data_keeps_old_file(self):
        jsonfile.write_atomic(self.path, {"a": 1})
        with self.assertRaises(TypeError):
            jsonfile.write_atomic(self.path, {"a": object()})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))
        self.assertEqual(["settings.json"], os.listdir(self.dir))


class LivenessTest(unittest.TestCase):
    LINE = ("4242 (a b) c (d)) S 1 4242 4242 0 -1 4194560 100 0 0 0 "
            "1 2 0 0 20 0 1 0 987654 1000 100")

    def test_parse_after_last_paren(self):
        self.assertEqual(987654, liveness.parse_start_ticks(self.LINE))

    def test_this_process_started_in_the_past(self):
        ms = liveness.started_ms(os.getpid())
        self.assertIsNotNone(ms)
        self.assertLess(ms, time.time() * 1000 + 1000)

    def test_missing_pid(self):
        self.assertIsNone(liveness.started_ms(4194304))
        self.assertFalse(liveness.alive(4194304, 0))

    def test_alive_within_slack(self):
        with mock.patch.object(liveness, "started_ms", return_value=10_000):
            self.assertTrue(liveness.alive(7, 9_000))      # 1 s late: slack
            self.assertTrue(liveness.alive(7, 20_000))     # born before
            self.assertFalse(liveness.alive(7, 4_000))     # 6 s younger
```

  Plus, in the same file, loader tests: a Claude state file
  (`$XDG_STATE_HOME/erplibre-home/claude/s.json`, use the harness sandbox
  or a temp `XDG_STATE_HOME`) with `pid` 7 and `ts_active` 1000 is
  dropped when `liveness.started_ms` (patched) answers 9000, kept when it
  answers 500; a file with no `ts_*` keeps today's `/proc` existence
  check; an mpv file with `started_at` follows the same rule; pid 0 is
  kept. And: `settings.save`, the layouts writer and the TODO registry
  writer call `jsonfile.write_atomic` (patch it and assert the call).

- [ ] **Step 2: Run** the new file; FAIL (`No module named ...jsonfile`).
- [ ] **Step 3: Implement** `jsonfile.py`:

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Atomic replacement of the JSON files the deck writes."""

import json
import os
import tempfile


def write_atomic(path, data, indent=2):
    """Write `data` as JSON to `path` through a temporary file in the
    same directory, flushed and fsynced, then os.replace: a reader sees
    the old file or the new one, never a truncated one. The directory is
    created when missing; the temporary file is removed on failure."""
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    text = json.dumps(data, indent=indent)
    fd, tmp = tempfile.mkstemp(
        prefix=".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _umask():
    """The process umask (read by setting it and restoring it)."""
    mask = os.umask(0)
    os.umask(mask)
    return mask
```

  and `liveness.py`:

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Whether a session's pid still belongs to the session's process.

A pid number is reused once its process dies; a process that started
after the session's first timestamp is another program. The start time
comes from /proc/<pid>/stat (clock ticks since boot, field 22) and the
boot time `btime` of /proc/stat."""

import os


def parse_start_ticks(stat_line):
    """Field 22 of a /proc/<pid>/stat line. The command name (field 2)
    may hold spaces and parentheses: the fields are counted after the
    last ')'."""
    rest = stat_line[stat_line.rindex(")") + 2:].split()
    # rest[0] is field 3 (state): field 22 is rest[19].
    return int(rest[19])


def _boot_time():
    with open("/proc/stat", encoding="utf-8") as f:
        for line in f:
            if line.startswith("btime "):
                return int(line.split()[1])
    raise OSError("no btime in /proc/stat")


def started_ms(pid):
    """Start time of `pid` in epoch milliseconds; None when the process
    is gone or its files cannot be read."""
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as f:
            ticks = parse_start_ticks(f.read())
        hz = os.sysconf("SC_CLK_TCK")
        return int((_boot_time() + ticks / hz) * 1000)
    except (OSError, ValueError, IndexError):
        return None


def alive(pid, born_by_ms, slack_ms=5000):
    """True when `pid` runs and started no later than `born_by_ms` plus
    `slack_ms`: btime has a one-second resolution, and a writer may
    stamp its file just before the process starts."""
    start = started_ms(pid)
    return start is not None and start <= born_by_ms + slack_ms
```

  Writers: `settings.save(data)` becomes
  `jsonfile.write_atomic(paths.SETTINGS_FILE, data)`; the layouts and
  registry writers keep their indent (read the current `json.dump` call
  and pass the same `indent`). Loaders: in `claude_sessions.load_sessions`
  replace `if pid > 0 and not os.path.exists(f"/proc/{pid}"): continue`
  with: compute `stamps = [t for t in (ts_active, ts_stop, ts_notif,
  ts_tool) if t > 0]` first; then `if pid > 0: if stamps: if not
  liveness.alive(pid, min(stamps)): continue` `elif not
  os.path.exists(f"/proc/{pid}"): continue`. In `mpv_sessions`: when
  `started_at > 0` use `liveness.alive(pid, started_at)`, else the
  existence check.
- [ ] **Step 4: Run** the new file, the pages file (goldens use pid 1 and
  pid 0: pid 1 started at boot, before every stamp, so they stay green)
  and the full suite.
- [ ] **Step 5: Commit** two commits: `[FIX] stream_deck: JSON files
  replaced atomically` and `[FIX] stream_deck sessions: recycled pids
  dropped by start time`.

### Task 3: Kernel job runner (`run_blocking`)

**Files:**
- Modify: `script/stream_deck/erplibre_streamdeck/kernel.py`,
  `context.py`, `home.py` (owner lookup), `ui/colors.py` (`BUSY`)
- Modify: `test/streamdeck_stubs.py` (`check_golden` update mode)
- Test: `test/test_erplibre_streamdeck_kernel.py`

**Interfaces:**
- Produces: `Kernel.run_blocking(plugin_id, work, then=None) -> bool`;
  `Kernel.busy` (dict plugin id → `(page_id, key)`);
  `Kernel.drain_jobs() -> bool`; `Context.run_blocking(work, then=None)
  -> bool`; `Home.owner(key) -> str | None`; `colors.BUSY`;
  `check_golden` writing from the package when
  `STREAMDECK_GOLDEN=update-from-package`.

- [ ] **Step 1: Failing tests** in the kernel test file (FakeThread is
  installed by the harness: `S.FakeThread.queue` holds started jobs; run
  them with a small helper `run_jobs()` that pops and calls each target):

```python
class JobTest(KernelCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch("threading.Thread", S.FakeThread)
        patch.start()
        self.addCleanup(patch.stop)
        S.FakeThread.queue.clear()

    def run_jobs(self):
        while S.FakeThread.queue:
            job = S.FakeThread.queue.pop(0)
            job.target(*job.args, **job.kwargs)

    def slow_plugin(self, work, then=None, calls=None):
        def handle(ctx, key):
            (calls if calls is not None else []).append(key)
            ctx.run_blocking(work, then)

        return self.page_plugin(handle=handle)

    def test_busy_mark_then_result_on_next_pass(self):
        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        k.handle_key(3, True)
        self.assertEqual("…", self.deck.screen[3][1])
        self.assertIn("p", k.busy)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertNotIn("p", k.busy)
        self.assertEqual("ok", k.flash_result)

    def test_error_reaches_then(self):
        seen = []
        k = self.kernel(self.slow_plugin(
            lambda: 1 / 0, lambda ctx, r, e: seen.append(type(e))))
        k.goto("pg")
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual([ZeroDivisionError], seen)

    def test_second_press_on_busy_plugin_flashes_err(self):
        calls = []
        k = self.kernel(self.slow_plugin(lambda: True, calls=calls))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.handle_key(4, True)
        self.assertEqual([3], calls)          # plugin not called again
        self.assertEqual("err", k.flash_result)
        self.assertEqual(1, len(S.FakeThread.queue))

    def test_busy_mark_only_on_its_page(self):
        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        k.handle_key(3, True)
        k.goto("idle")
        self.assertNotEqual("…", (self.deck.screen.get(3) or [0, ""])[1])

    def test_results_dropped_after_stop(self):
        seen = []
        k = self.kernel(self.slow_plugin(
            lambda: True, lambda ctx, r, e: seen.append(r)))
        k.goto("pg")
        k.handle_key(3, True)
        k.running = False
        self.run_jobs()
        k.drain_jobs()
        self.assertEqual([], seen)

    def test_page_tick_skipped_while_busy(self):
        ticks = []
        k = self.kernel(self.page_plugin(
            handle=lambda ctx, key: ctx.run_blocking(lambda: True),
            tick=lambda ctx, now: ticks.append(now)))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertEqual([], ticks)
```

- [ ] **Step 2: Run**; FAIL.
- [ ] **Step 3: Implement** in `kernel.py` (and `colors.BUSY = (90, 90,
  40)`):

```python
    # in __init__, before setup:
        self.busy = {}
        self._finished = []
        self._finished_lock = threading.Lock()

    # -- slow actions

    def run_blocking(self, plugin_id, work, then=None):
        """Run work() in a thread, outside the lock; the plugin is busy
        until the next loop pass hands the result to then(ctx, result,
        error) under the lock. False (and an ERR flash) when the plugin
        already has a job."""
        if plugin_id in self.busy:
            self.set_flash(False)
            self.render()
            return False
        self.busy[plugin_id] = (self.page_id, self.last_press_key)
        self._paint_busy()

        def runner():
            try:
                result, error = work(), None
            except (Exception, SystemExit) as exc:
                result, error = None, exc
            with self._finished_lock:
                self._finished.append((plugin_id, then, result, error))

        threading.Thread(target=runner, daemon=True).start()
        return True

    def _paint_busy(self):
        for page_id, key in self.busy.values():
            if key is not None and page_id == self.page_id:
                self.paint(key, KeyFace(colors.BUSY, "…"))

    def drain_jobs(self):
        """Hand finished jobs to their plugins; True when one ran."""
        with self._finished_lock:
            finished, self._finished = self._finished, []
        for plugin_id, then, result, error in finished:
            self.busy.pop(plugin_id, None)
            if not self.running:
                continue
            if then is None:
                self.set_flash(error is None and bool(result))
                self.render()
                continue
            ok, _ = self.guard(
                plugin_id, "job result", then, self.ctx(plugin_id),
                result, error,
            )
            if not ok:
                self.set_flash(False)
                self.render()
        return bool(finished)
```

  `render()` calls `self._paint_busy()` after `_render_page()` and before
  `_overlay_flash()`. `handle_key`: after recording `last_press_key`,
  find the target owner (`self.home.owner(key)` on the home screen, the
  page's owner otherwise); if it is in `self.busy`, `set_flash(False)`,
  `render()`, return. `step`: after the flash check, call
  `self.drain_jobs()`; a page tick or home tick of a busy plugin is
  skipped. `Home.owner(key)` returns the plugin id of the button, fixture
  or last-render tile at `key`, else None. `Context.run_blocking(work,
  then=None)` returns `self._kernel.run_blocking(self.plugin_id, work,
  then)`. Import `KeyFace` in kernel.py from `erplibre_streamdeck.plugin`.

  In `test/streamdeck_stubs.py`, `check_golden` writes the golden from
  the run (same JSON format as the existing files: `{"format": 1,
  "inputs": inputs, "geometries": runs}`, `indent=1`, `sort_keys=True`,
  `ensure_ascii=False`, trailing newline) when
  `os.environ.get("STREAMDECK_GOLDEN") == "update-from-package"`, and
  compares otherwise.
- [ ] **Step 4: Run** the kernel, home, pages files and the full suite.
- [ ] **Step 5: Commit** `[ADD] stream_deck kernel: slow actions off the
  lock with a busy key`.

### Task 4: Kernel polls

**Files:**
- Modify: `plugin.py` (`Poll`, `Plugin.polls`), `loader.py` (shape check
  of polls), `kernel.py` (`step`)
- Test: `test/test_erplibre_streamdeck_kernel.py`,
  `test/test_erplibre_streamdeck_loader.py`

**Interfaces:** Produces `plugin.Poll(period, active, read, store)` and
`Plugin.polls: list` (default empty).

- [ ] **Step 1: Failing tests** (kernel): a poll is not read while
  `active` is false; it is read once per `period`; `read` runs outside the
  lock (assert `k.lock.locked()` is False inside `read`); `store` returning
  True on the home screen makes exactly one render that pass; a `read`
  that raises every pass keeps the stored value and writes one journal
  line (`test_failing_read_keeps_cache_and_logs_once`); a busy plugin's
  poll is skipped; while a flash is recorded no poll is read. Loader:
  `polls=[object()]` and `polls=[Poll("1", ...)]` are refused with a
  reason; a valid `Poll` loads.
- [ ] **Step 2: Run**; FAIL.
- [ ] **Step 3: Implement.** `plugin.py`:

```python
@dataclass
class Poll:
    """Data a render needs, read away from the lock. active(ctx) says,
    under the lock, whether it is needed now; read() runs in the loop
    thread without the lock and must not touch a Context; store(ctx,
    data) keeps it, under the lock, and returns True when what the deck
    shows changed."""

    period: float
    active: Callable
    read: Callable
    store: Callable
```

  and `polls: list = field(default_factory=list)` in `Plugin`. The loader
  shape check accepts `polls` as a list of `Poll` with a number `period`
  (bool refused) and three callables. `kernel.step` becomes:

```python
    def step(self, now):
        """One loop pass. Under the lock: a recorded flash ends the pass
        (rendered once expired); finished jobs are handed back; the due
        polls are chosen. Outside it: the D-Bus recheck and the polls'
        read(). Under it again: their store(), then the page tick or the
        home step, with at most one render for the polls."""
        with self.lock:
            if self.flash_result:
                if not self._flash_live():
                    self.render()
                return
            self.drain_jobs()
            due = self._due_polls(now)
        if self.recheck_dbus(now):
            with self.lock:
                self.render()
        reads = [
            (lp, i, poll, self.guard(lp.id, f"poll {i} read", poll.read))
            for lp, i, poll in due
        ]
        with self.lock:
            if not self.running or self.flash_result:
                return
            want = False
            for lp, i, poll, (ok, data) in reads:
                if not ok:
                    continue
                ok, changed = self.guard(
                    lp.id, f"poll {i} store", poll.store, self.ctx(lp.id),
                    data,
                )
                want = want or bool(ok and changed)
            if self.page_id not in self.pages:
                self.page_id = HOME
            if self.page_id == HOME:
                self._home_step(now, want)
                return
            if want:
                self.render()
            self._page_tick(now)

    def _due_polls(self, now):
        due = []
        for lp in self.plugins:
            if lp.id in self.busy:
                continue
            for i, poll in enumerate(lp.plugin.polls):
                ok, active = self.guard(
                    lp.id, f"poll {i} active", poll.active, self.ctx(lp.id)
                )
                if ok and active and self._due(
                    f"poll:{lp.id}:{i}", poll.period, now
                ):
                    due.append((lp, i, poll))
        return due
```

  `_page_tick(now)` is today's page-tick block (skipped when the owner is
  busy). `_home_step(now, want=False)` starts with the given `want`.
- [ ] **Step 4: Run** kernel, loader, pages files and the full suite.
- [ ] **Step 5: Commit** `[ADD] stream_deck kernel: polls read outside
  the lock`.

### Task 5: Slow actions moved — timers, dev_reload, layouts, tiling

**Files:**
- Modify: `plugins/timers.py`, `plugins/dev_reload.py`,
  `plugins/layouts.py`, `plugins/tiling.py`
- Modify: `test/test_erplibre_streamdeck_pages.py` (scenarios that press
  a slow key add `h.run_threads()` then `h.loop(1)` before the result
  step) and the goldens they rewrite
- Test: backends tests for each converted handler

Pattern (dev_reload, complete):

```python
def _hot_reload(dbus, log):
    """HotReload on the extension; True on exit 0 with a non-empty
    answer. Runs outside the lock: only `dbus` and `log`."""
    try:
        r = dbus.call("HotReload", timeout=10)
        if not r.ok:
            log(f"HotReload dbus: {r.stderr.strip()}")
            return False
        return bool(r.string)
    except Exception as e:
        log(f"HotReload error: {e}")
        return False


def _press(ctx):
    dbus, log = ctx.dbus, ctx.log
    ctx.run_blocking(lambda: _hot_reload(dbus, log))
```

  (no `then`: the kernel flashes OK on a truthy result, ERR otherwise,
  and renders — what `_press` did before.)

For each other call of the spec's table owned by these plugins:
capture the inputs the call needs (window list, slot id, timer id,
corners, CSV rows) before `run_blocking`; pass a `then(ctx, result,
error)` that does what the handler did after the call (flash, page
change, state update, render). Timers: the zenity dialog and the CSV write
run in one job; toggle/add/reset run as jobs whose `then` refreshes the
list and renders. Layouts: save (ListWindows + write) and load
(read + ApplyLayout) are jobs, also from the home shortcut fixture.
Tiling: TileWindow is a job; the corner/timeout state is reset when the
job is started, as today before the call.

- [ ] **Step 1:** For each plugin, write the backend test first: the
  handler starts exactly one job (`S.FakeThread.queue` length 1), the
  page shows "…" on the pressed key, and after running the job and one
  loop pass the screen and the effects match what the handler produced
  before (use the existing golden steps as the expected values).
- [ ] **Step 2:** Convert the plugin; run its backend tests.
- [ ] **Step 3:** Adjust the page scenarios that press these keys (add the
  `run_threads()` + `loop(1)` steps), regenerate only their goldens with
  `STREAMDECK_GOLDEN=update-from-package .venv.erplibre/bin/python
  test/test_erplibre_streamdeck_pages.py PackagePages.<test>`, read each
  diff (`git diff --stat` + one geometry in full), and check that the only
  differences are: the "…" step, the result one step later, effects moved
  from the press step to the threads/loop steps.
- [ ] **Step 4:** Full suite; commit one per plugin, `[FIX] stream_deck
  <plugin>: <call> off the lock`, body listing every rewritten golden and
  why.

### Task 6: Slow actions moved — bluetooth, sessions, TODO terminals

Same pattern and steps as Task 5, for:

- `bluetooth`: power on/off, connect, disconnect (each a job; `then`
  flashes like today — power keeps no flash on failure, as today —
  and renders);
- `claude_sessions`: Focus/Accept/SetWindow/Kill (job returns
  `Reply.true`; `then` flashes and goes home, as today);
- `mpv_sessions`: MpvSendCommand (volume keys stay on the page; other keys
  go home after the flash, as today);
- `todo_terminals`: the terminal launch (job: `which` + Popen; `then`
  arms the pending capture as today), SendKeysToWindow and FocusWindowById
  (job; `then` flashes/renders as today).

Commits one per plugin, `[FIX] stream_deck <plugin>: <calls> off the
lock`, each listing its rewritten goldens.

### Task 7: Renders read caches (polls)

**Files:** `plugins/sound.py`, `plugins/bluetooth.py`, `plugins/timers.py`,
`plugins/todo_terminals.py`, their tests, the scenarios and goldens they
change.

- `sound`: `Poll(1.0, active=ctx.page == "sound", read=` sink/source
  volumes + `wpctl status` devices`, store=` into `state().audio`, True
  when it changed`)`; a second `Poll(2.0, active=` home shown and the mic
  key placed`, read=` source volume/mute`, store=` `state().mic``)`. The
  page render and the mic face read only the state; with no data yet
  they show what `wpctl` failing showed before (N/A).
- `bluetooth`: `Poll(2.0, active=page == "bluetooth", read=` powered +
  paired/connected`, store=` `state().bt``)`; render reads the state.
- `timers`: the 2 s home tick and the timer page tick become one `Poll(2.0,
  active=` home shown or `timer_list` shown`, read=ListTrackerTimers,
  store=` `state().timers` + key map`)`; `enter(ctx)` becomes
  `ctx.goto("timer_list")` alone (the page shows the cached timers and the
  poll, active as soon as the page shows, refreshes them on the next
  pass); the harness's `ENTRIES` keeps calling it. The tile provider
  reads the state.
- `todo_terminals`: the registry refresh (`ListWindows` + prune) becomes
  `Poll(2.0)` on home and `Poll(1.0)` on `todo_session`; the pending
  capture becomes a poll active only when `capture_at` is due; the session
  page's auto-return moves into the poll's `store` (window gone → home).

- [ ] **Step 1:** Per plugin, backend tests: render makes no
  `subprocess.run` call (patch it to raise); the poll's `read` returns the
  data the render used to fetch; `store` returns True only when it
  changed.
- [ ] **Step 2:** Convert; run.
- [ ] **Step 3:** Regenerate the affected goldens (update-from-package),
  checking the diffs show only effects moving from render steps to loop
  steps and the first frame of a page before its first poll.
- [ ] **Step 4:** Full suite; one commit per plugin, `[FIX] stream_deck
  <plugin>: render reads a polled cache`, listing the rewritten goldens.

### Task 8: `DECK_SESSION_REFRESH_SEC`

**Files:** `script/install/erplibre_home_settings.sh`,
`script/todo/erplibre_home_service.py`, `script/todo/streamdeck_menu.py`
(entry [13]), `script/todo/erplibre_home_status.py`,
`script/todo/todo_i18n.py`, `script/stream_deck/erplibre_streamdeck/app.py`
(`read_deck_settings`), `__main__.py`, `kernel.py` (`settings`),
`context.py` (`setting`), and their tests.

**Interfaces:** shell `deck_session_refresh_sec` (prints the valid value,
`1` otherwise); Python `DEFAULTS["DECK_SESSION_REFRESH_SEC"] = "1"`,
`SESSION_REFRESH_RANGE = (0.5, 60.0)`, `session_refresh_sec(settings) ->
float`; `app.read_deck_settings() -> {"plugins_off": [...],
"session_refresh_sec": float}` (one bash call:
`. lib && deck_plugins_off | sed 's/^/off=/' && echo
"refresh=$(deck_session_refresh_sec)"`), replacing `read_plugins_off`
everywhere; `app.build(deck, *, plugins_off=(), user_dir=None,
settings=None)`; `Kernel(deck, plugins, settings=None)` with
`kernel.settings` a dict; `Context.setting(name, default=None)`.

- [ ] **Step 1:** Tests: shell/Python parity on `""`, `"1"`, `"0.5"`,
  `"60"`, `"0.4"`, `"61"`, `"abc"`, `"2\r"` (→ 1, 1, 0.5, 60, 1, 1, 1, 2
  — a trailing `\r` is stripped as white space, like `deck_plugins_off`);
  `read_deck_settings` on a real `streamdeck.conf` in a temp
  `XDG_CONFIG_HOME`; TODO entry [13] in fr and en: shows the value,
  accepts `2`, refuses `0.1` and `abc` with the range and leaves the file
  unchanged (`test_entry_refuses_out_of_range`), offers the restart only
  when the unit is active (template: entry [12]); Status line
  `Session refresh: N s` when not the default; diagnosis for an invalid
  value naming the menu path.
- [ ] **Step 2:** Implement following the `DECK_PLUGINS_OFF` code of B2
  (Task 15) as the template in every file.
- [ ] **Step 3:** Full suite; commit `[ADD] stream_deck: DECK_SESSION_REFRESH_SEC
  setting, TODO entry and status`.

### Task 9: Session pages refresh

**Files:** `plugins/claude_sessions.py`, `plugins/mpv_sessions.py`, tests,
scenarios/goldens if a scenario's loop now ticks these pages.

- The `claude_session` and `mpv_session` pages get `tick=_tick` with
  `period=` the value of `ctx.setting("session_refresh_sec", 1.0)` —
  since `Page.period` is fixed at declaration, the plugin's `setup`
  replaces its page's period from the setting
  (`PLUGIN.pages[0].period = ctx.setting(...)`), before the kernel reads
  it.
- `_tick(ctx, now)`: reload the shown session (`load_sessions()` +
  find by sid/pid); gone → `ctx.home()`; else compare a signature (status,
  colour, notification_message, description; mpv: title) with
  `state().shown` and `ctx.render()` only when it changed.

- [ ] **Step 1:** Tests: unchanged session → no render on tick; changed
  status → one render; file removed → home; the period follows
  `settings={"session_refresh_sec": 2.5}` given to the kernel.
- [ ] **Step 2:** Implement; regenerate any golden whose loop now ticks
  these pages (update-from-package, listed in the body).
- [ ] **Step 3:** Full suite; commit `[FIX] stream_deck sessions: pages
  refresh and go home when the session ends`.

### Task 10: Docs and spec amendments

- `script/stream_deck/README.base.md`, "Writing a plugin": `ctx.run_blocking`
  (what `work` may touch, the busy key, `then`), `Poll`, `ctx.setting`;
  `INSTALL.base.md`: `DECK_SESSION_REFRESH_SEC`; `CHANGELOG.base.md`:
  the four fixes and the setting; regenerate with mmg.
- The B3 spec gains "Amendments from the plan" with every ruling the
  execution ledger records.
- [ ] Full suite + node tests; commit `[UPD] doc: deck slow actions,
  polls, atomic files, session refresh`.
