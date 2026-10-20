# ERPLibre Stream Deck: blocking calls, atomic files, live sessions

**Status:** design, awaiting review.
**Sub-project:** B3 of the `game_tiler.py` project. B1 (games apart) and B2
(the deck program as the plugin package `script/stream_deck/erplibre_streamdeck/`)
have landed.
**Builds on:** `2026-10-18-erplibre-streamdeck-plugin-package-design.md`
(kernel, plugins, context, goldens, amendments 1-22).

## Goal

Four defects of the deck program, and the five points B2 left over.

1. **Blocking calls under the lock.** A key press runs its work while the
   kernel lock is held: the zenity export dialog blocks every key up to
   180 s; HotReload, ApplyLayout and a Bluetooth connect up to 10 s. The
   Sound and Bluetooth pages, and the home screen's microphone key, run
   `wpctl` and `bluetoothctl` on every render; the timers and TODO home
   refreshes run `gdbus` under the lock every 2 s.
2. **`settings.json` written in place.** A crash or a full disk during the
   write leaves a truncated file; `layouts.json` and `todo_terminals.json`
   have the same weakness.
3. **Recycled pids.** A Claude or mpv session file whose process died is
   kept as long as any process holds the same pid number.
4. **Session pages never refresh.** The Claude and mpv session pages show
   what they read when opened; a session that ends leaves its page open.

After B3:

- a slow action runs off the lock; its key shows "…", the rest of the deck
  stays usable, and the result flashes when it is done;
- renders never start a process: they read caches that background polls
  fill outside the lock;
- every JSON file the deck writes is replaced atomically;
- a session whose pid now belongs to a younger process is dropped;
- the session pages refresh every `DECK_SESSION_REFRESH_SEC` (1 s by
  default) and go home when their session is gone.

## Out of scope

- The extension's own readers (`lib/claude-state.js`, `lib/mpv-state.js`)
  and the writers (the Claude hook, the extension's mpv state): the
  liveness check is the deck's alone.
- Lost updates between the deck and the extension writing
  `todo_terminals.json` at the same moment: each write is atomic, the
  last one wins, as today.
- The volume-setting `wpctl` calls of the Sound page (`set-volume`,
  `set-mute`, `set-default`): they return in well under a second and stay
  under the lock.
- New hardware testing: still none on this host.

## Decisions taken in the brainstorm

| Fork | Decision |
|---|---|
| Blocking calls | `ctx.run_blocking(work, then)` plus render caches filled by polls |
| A press on a busy plugin | flashes ERR; the plugin is not called |
| Liveness | reader only: process start time against the session's oldest timestamp |
| Atomic writes | every JSON file the deck writes |
| Session page refresh | tick, back home when the session is gone; period configurable |
| Where the period lives | `DECK_SESSION_REFRESH_SEC` in `streamdeck.conf`, edited from TODO |

## 0. What B2 left over

The B2 ledger parked five points; they are fixed first.

- `test/test_erplibre_streamdeck_loader.py`: the extra blank line before
  `SHAPED` (E303).
- Spec amendment 20 of the B2 spec says `shutdown(ctx)` always runs with
  the kernel lock held. It now reads: `shutdown` runs with the lock held
  when the app can take it within 5 s, and without it otherwise; it must
  never take `ctx.locked()` nor wait for a thread that does.
- The journal labels of the home faces (`home face`, `fixture face`,
  `tile face`) carry the key (`tile face 12`), so a provider failing on one
  item and succeeding on another logs once per key, not every refresh.
- `Kernel.guard` also catches `SystemExit` (never `KeyboardInterrupt`): a
  plugin calling `sys.exit()` from a callable is isolated like any other
  exception instead of ending its thread. The SystemExit a SIGTERM raises
  (`deck_lock.SigtermExit`) is the service's stop and passes, in the
  guard and in the loader's import alike.
- Once `kernel.running` is false, `Kernel.paint` and `Kernel.render` draw
  nothing, so a callback still finishing after the 5 s shutdown bound
  cannot repaint a deck that was just reset.

## 1. Slow actions off the lock

### Interface

`Context.run_blocking(work, then=None)`:

- `work()` takes no argument and must not touch `ctx` (it runs without
  the lock); it captures what it needs before the call.
- The kernel marks the calling plugin busy, paints the last pressed key
  "…" (colour `colors.BUSY`, new) and starts `work` in a thread created
  through `threading.Thread` (module attribute, daemon).
- When `work` returns or raises, the kernel queues
  `(plugin_id, then, result, error)`.
- At the start of the next loop pass, under the lock, the kernel drains
  the queue: it clears the busy mark, then calls `then(ctx, result,
  error)` through `guard`. Without `then`, the kernel flashes OK when
  `error` is None and the result is truthy, ERR otherwise, and renders.
- `then` renders itself, like a handler.
- One job per plugin: `run_blocking` while the plugin is busy returns
  False and flashes ERR; otherwise it returns True.

### A press on a busy plugin

While a plugin is busy, any press that would reach it (its page's
`handle`, its home button, its fixtures, its tiles) flashes ERR on the
pressed key without calling the plugin. Presses on other plugins and on
other pages work as usual. A page tick of a busy plugin is skipped.

### Shutdown

`app.main` sets `running` false first; the kernel then drops queued
results without calling `then`. Worker threads are daemons and are not
joined.

### Which calls move

| Plugin | Call | Timeout today |
|---|---|---|
| timers | zenity save dialog + CSV write | 180 s |
| timers | ToggleTrackerTimer, AddTrackerTimer, ResetAllTrackerTimers | 3 s |
| dev_reload | HotReload | 10 s |
| layouts | ListWindows + save, ApplyLayout (page and shortcut keys) | 3 s / 10 s |
| tiling | TileWindow | 3 s |
| bluetooth | power on/off, connect, disconnect | up to 10 s |
| claude_sessions | Focus/Accept/SetWindow/Kill session | 2 s |
| mpv_sessions | MpvSendCommand | 2 s |
| todo_terminals | terminal launch, SendKeysToWindow, FocusWindowById | 2 s |
| translate | none: recording and transcription already run in their own thread | — |

Each move keeps the page transition the handler does today: the page
changes (or not) when `then` runs, after the result is known.

## 2. Renders read caches

### Interface

`Plugin.polls`: a list of `Poll(period, active, read, store)`.

- `active(ctx) -> bool`, under the lock: whether the data is needed now
  (the plugin's page shows, or the home screen shows one of its keys).
- `read()`, outside the lock, in the loop thread, like the D-Bus recheck:
  runs the processes and returns the data. It must not touch `ctx`.
- `store(ctx, data) -> bool`, under the lock: keeps the data in
  `ctx.state()` and returns True when what the deck shows changed, which
  asks for one render.
- Each poll has its own stamp (amendment 3 of B2); the first pass runs
  every active poll. A poll whose plugin is busy is skipped.
- `read` and `store` go through `guard`; a failing read keeps the old
  cache.

The kernel's loop pass becomes: drain the job queue (lock), D-Bus
recheck (no lock), due polls' `read` (no lock), then under the lock their
`store`, the flash precedence, page tick or home step, and at most one
render.

### Which renders change

| Plugin | Today in render or tick | After |
|---|---|---|
| sound | `wpctl get-volume` sink and source, `wpctl status` | poll 1 s while the Sound page shows; the mic key's poll 2 s on home |
| bluetooth | `bluetoothctl show`, `devices Paired/Connected` | poll 2 s while the Bluetooth page shows |
| timers | `ListTrackerTimers` in the page tick and the home tick | poll 2 s on the timer page and on home |
| todo_terminals | `ListWindows` refresh, pending capture `GetFocusedWindowId` | poll 1 s on the session page, 2 s on home; the capture becomes a poll due once at its time |

The page renders and the home faces read only `ctx.state()`. The Claude
and mpv loaders read small local files and stay in the render and the
tick.

## 3. Atomic JSON files

`erplibre_streamdeck/jsonfile.py`:

```python
def write_atomic(path, data, indent=2):
    """Write `data` as JSON to `path` through a temporary file in the
    same directory, flushed and fsynced, then os.replace: a reader sees
    the old file or the new one, never a truncated one. The directory is
    created when missing; the temporary file is removed on failure."""
```

`settings.save`, the layouts store and the TODO registry write through it.
The read side does not change. The file mode stays the default `0o644`
under the user's umask, as today.

## 4. Live sessions

`erplibre_streamdeck/liveness.py`:

- `started_ms(pid) -> int | None`: the process start time in epoch
  milliseconds, from field 22 of `/proc/<pid>/stat` (clock ticks since
  boot, `os.sysconf("SC_CLK_TCK")`) and `btime` of `/proc/stat`; None
  when the process is gone or the file unreadable. The comm field may hold
  spaces and parentheses: the fields are read after the last `)`.
- `alive(pid, born_by_ms, slack_ms=5000) -> bool`: True when the process
  exists and started no later than `born_by_ms + slack_ms`. The slack
  covers `btime`'s one-second resolution and the delay between the writer
  stamping the file and the process starting.

Rules:

- **Claude:** `born_by_ms` is the oldest non-zero `ts_*` of the session
  file (the process existed before its first hook ran). A file with no
  timestamp keeps today's existence check.
- **mpv:** `born_by_ms` is `started_at`.
- **pid 0 or absent:** kept, as today.

A process younger than its session is a recycled pid: the session is
dropped from the dashboard and from its page.

## 5. Session pages refresh

- The `claude_session` and `mpv_session` pages get a `tick` with
  `period = DECK_SESSION_REFRESH_SEC`.
- The tick reloads the shown session. If it is gone (file removed, pid
  dead or recycled), it goes home. Otherwise it renders when what the page
  shows changed (status, colour, message or description; title for mpv).

### The `DECK_SESSION_REFRESH_SEC` setting

- Key in `streamdeck.conf`; a number of seconds from 0.5 to 60; default
  `1`. A value that is not a number, or out of range, gives 1 and the
  TODO diagnosis names it.
- Shell (`erplibre_home_settings.sh`): `deck_session_refresh_sec` prints
  the valid value.
- Python (`script/todo/erplibre_home_service.py`): `DEFAULTS` gains
  `"DECK_SESSION_REFRESH_SEC": "1"`, plus `session_refresh_sec(settings)
  -> float`, in parity with the shell.
- The deck reads the setting at start through the settings library, in the
  same `bash` call that reads `DECK_PLUGINS_OFF`; `app.build` takes it as
  `session_refresh_sec=` and plugins read it from `ctx.setting(name)`
  (new, read-only dict of the deck settings).
- TODO › Stream Deck gains entry [13] "Session refresh": it shows the
  value, asks a new one, validates it, writes it, and offers to restart the
  deck service when it is active. fr and en strings.
- TODO › Status shows `Session refresh: N s` when it is not the default;
  the diagnosis names an invalid value and how to fix it.

## Amendments from the plan

Where a rule below differs from the text above, this section wins.

1. **Setting channel.** `app.build` takes `settings=`, a dict of deck
   settings (key `"session_refresh_sec"`), not `session_refresh_sec=`: one
   channel for every deck setting. `ctx.setting(name, default=None)` reads
   it and returns `default` when the kernel was not given the key.
2. **Session pages' period.** `Page.period` stays a float. The session
   pages' tick has period 0.0 and gates itself: it compares
   `state().last_check` with `ctx.setting("session_refresh_sec", 1.0)`. A
   plugin's `setup` never mutates its module-level `PLUGIN`, since that
   object is shared by every kernel in one process. `PLUGIN_API` stays 1.
3. **Deck settings reader.** `read_deck_settings` replaces
   `read_plugins_off`: one `bash` call returns `DECK_PLUGINS_OFF` and the
   refresh period.
4. **Umask.** `write_atomic` reads the process umask once, at import: the
   set-and-restore pair is not thread-safe, and the layouts writer runs in
   a job thread.
5. **Busy plugin and key 0.** While a page's owner is busy, key 0 of that
   page (BACK on most pages, a grid cell on `tiling`, CANCEL on
   `timer_reset_confirm`) sends the deck home through the kernel without calling the plugin; the other
   keys flash ERR. A user plugin whose page uses key 0 for something else
   cannot use it while busy.
6. **Starting a job.** The plugin is marked busy only once its thread has
   started; a thread that cannot start raises to the caller and leaves the
   plugin free. The runner catches `BaseException`, so every job queues a
   result. `run_blocking` is called with the lock held and does not take
   it.
7. **Failed jobs are journaled by the kernel.** The runner keeps the
   traceback text with the error. The drain writes
   `[erplibre-home] <plugin>: job failed: <exc!r>` and the traceback once
   per (plugin, error) through `ErrorLog`, before calling `then` or the
   default flash, for every plugin. A job that ends without raising clears
   the entry.
8. **Flashes around jobs.** A drained job's `then` may flash, and a flash
   it records ends the loop pass. A job press right after an expired flash
   renders the page first, so the expired flash is cleared before "…" is
   painted.
9. **A job's post-action read.** When a job changes what a poll shows,
   `work` returns the post-action read and `then` stores it in the
   plugin's cache before rendering, so the render shows the new state
   without waiting for the next poll.
10. **Cached state in handlers.** The Bluetooth handlers act on the cached
    state (powered flag for the toggle direction, paired list for the
    slot); with no data yet they behave as "not available" does: ERR
    flash. No D-Bus or `wpctl` call remains in a timers handler: the
    refresh key and the export read inside their job. The Sound page's
    mute stores the microphone state too. The volume and mute presses of
    the Sound page re-read `wpctl` under the lock: they are fast, as in
    the out-of-scope list above.
11. **Capture poll.** The TODO terminals' capture poll runs on any page,
    since a pending capture is due at its own time.
12. **Links and mode in `write_atomic`.** The path is resolved with
    `os.path.realpath` first: the temporary file lives next to the real
    file and replaces it, so a symbolic link stays a link. An existing
    file keeps its permission bits; a new one gets 0o666 minus the umask.
    A link into a directory that cannot be written raises `OSError`, which
    the kernel's guard turns into an ERR flash and a journal line.
13. **Decimal comma.** The TODO "Session refresh" entry reads the first
    comma as a dot ("0,5" is 0.5) before the range check, and writes the
    value with a dot; the shell and the deck read only the dot. An
    English "1,000" is therefore read as 1 s.

## Contracts that stay

Everything B2 lists under "Contracts that stay", the plugin interface
(`PLUGIN_API = 1`: the additions are optional fields and new context
methods, so existing user plugins keep loading), and the on-disk formats.

## Tests

- **Kernel:** `run_blocking` (busy mark and "…", one job per plugin,
  `then` under the lock on the next pass, default flash, error passed to
  `then`, queue dropped after `running` is false), presses on a busy
  plugin flash ERR without a call, page tick skipped while busy, polls
  (`active` gating, own stamps, `read` outside the lock, failing read keeps
  the cache, `store` asking one render), `SystemExit` isolated, no paint
  after `running` is false.
- **The harness** runs worker threads deterministically (`FakeThread`
  queue and `Harness.run_threads()`, already present) and polls inside the
  loop pass; scenarios that press a slow key add a `run_threads()` and a
  loop pass before the result step.
- **Goldens:** B3 changes what some goldens pin on purpose (the "…" key,
  effects moving from renders to polls, the result arriving one pass
  later). `check_golden` gains a `STREAMDECK_GOLDEN=update-from-package`
  mode that rewrites the named goldens from the package; every commit that
  rewrites a golden lists, in its body, each golden and the reason. A
  golden that changes without its plugin's behaviour changing is a bug.
- **Atomic writes:** a write that raises midway leaves the old file and no
  temporary file; the three writers go through `write_atomic`.
- **Liveness:** `started_ms` on the test process itself and on a pid that
  does not exist; `alive` with a born-by stamp older and younger than the
  process; a comm with spaces and parentheses (parser test on a fixed
  `/proc/<pid>/stat` line); the Claude and mpv loaders dropping a recycled
  pid (patched `started_ms`).
- **Session pages:** tick renders on change, not when unchanged, goes home
  when the session file disappears, honours the configured period.
- **Setting:** shell and Python parity (`""`, `"1"`, `"0.5"`, `"60"`,
  `"0.4"`, `"61"`, `"abc"`, a value with `\r`), the TODO entry in fr and
  en, the Status line and the diagnosis.

## Risks

1. **Ordering after a slow action.** The page change happens when `then`
   runs, one loop pass (≤ 0.3 s) after the work ends. A user pressing
   another key meanwhile acts on the old page. The "…" key and the busy
   rule keep it explicit.
2. **Stale caches.** A render shows data up to one poll period old. Polls
   run on the first pass after a page opens, so a page shows fresh data
   within one pass.
3. **Clock and `btime`.** A changed wall clock after boot shifts the
   computed start times. The 5 s slack absorbs NTP adjustments; a large
   manual clock change can drop or keep a session wrongly until the next
   write of its file.
4. **Goldens rewritten from the package.** They no longer come from the
   single file. The per-commit list of rewritten goldens and their reasons
   is the review surface; the final review reads them all.
