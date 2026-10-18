# ERPLibre Stream Deck: the deck program as a plugin package

**Status:** design, awaiting review.
**Sub-project:** B2 of the `game_tiler.py` project. B1 (games apart,
`erplibre_streamdeck.py`, `GAMES`) has landed. B3 (blocking calls under
the lock, atomic `settings.json`, Claude and mpv liveness, refresh of
their pages) gets its own spec after this one.
**Builds on:** `2026-10-17-erplibre-streamdeck-games-split-design.md`.

## Goal

`script/stream_deck/erplibre_streamdeck.py` is one 3618-line file: one
`Tiler` class with 66 methods, 75 module functions, fourteen-branch `if`
chains in `handle_key` and `_render_mode`, the dashboard order written
twice (`_handle_idle_key` and `_render_idle`), and a `loop` that knows
every domain.

After B2:

- the deck program is the package `script/stream_deck/erplibre_streamdeck/`,
  run as a directory (`python script/stream_deck/erplibre_streamdeck`);
- a small kernel owns the deck, the lock, the flash, the home screen and
  the dispatch; every feature (tiling, layouts, timers, sound, Bluetooth,
  accessibility, translator, TODO terminals, Claude sessions, mpv
  sessions, extension reload) is a plugin discovered in a directory;
- plugins come from the repository and from a user directory, and any of
  them can be turned off by the setting `DECK_PLUGINS_OFF`;
- a plugin that raises is isolated: the deck keeps running.

What the user sees on the deck does not change, at any geometry, with one
deliberate exception (dashboard taps, below).

## Out of scope

- The four B3 defects. B2 moves the blocking calls with their pages and
  keeps them under the lock; it moves `settings.json` behind one module
  and keeps the non-atomic write.
- `deck_lock.py`, `translator.py`, `translator_stream.py`: they stay
  siblings of the package. `translator_stream.py` is still started by
  path.
- `erplibre_controller.py`, `Assets/`, the games and the gallery.
- A published, versioned plugin API for third parties beyond
  `PLUGIN_API = 1` and the guide in the README.
- Any change to the on-disk formats or to the extension's D-Bus methods.

## Decisions taken in the brainstorm

| Fork | Decision |
|---|---|
| Entry point | Package only, run as a directory. `erplibre_streamdeck.py` disappears; `__main__.py` replaces it. |
| Discovery | Directory scan; each module exposes `PLUGIN`. |
| Enable/disable | `DECK_PLUGINS_OFF` in `streamdeck.conf`, edited from TODO. |
| D-Bus transport | Kernel service, injectable (`ctx.dbus`); not a plugin. |
| External plugins | Two directories: the repository's and a user directory. |
| Runtime errors | Isolate the plugin, log, flash, go home; the service stays up. |
| Tests | `test/test_erplibre_streamdeck_*.py`, PIL and StreamDeck stubbed, run by `run_unit_test.sh`. |
| Dashboard taps | A tap reads the allocation of the last render. |
| Same id in both directories | The user plugin replaces the repository plugin, logged. |

## Layout

```
script/stream_deck/
  deck_lock.py  translator.py  translator_stream.py     (unchanged)
  erplibre_streamdeck/
    __main__.py      sys.path, lock, SIGTERM, app.main(); --list-plugins
    app.py           device, kernel, key callback, loop thread, shutdown
    kernel.py        Kernel: page, lock, flash, dispatch, error isolation
    context.py       Context handed to plugins
    plugin.py        Plugin, Page, HomeButton, Fixture, TileProvider,
                     KeyFace, PLUGIN_API
    loader.py        discovery, DECK_PLUGINS_OFF, API check, duplicates
    home.py          home allocation, fixtures, dashboard
    dbus.py          the one gdbus client and the tuple parser
    settings.py      the one reader/writer of settings.json
    paths.py         STREAM_DECK_DIR, REPO_ROOT, config/state dirs
    ui/
      render.py      set_key, font discovery, Style (font scale, labels)
      icons.py       the icon painters
      text.py        chunk/wrap helpers
      colors.py      the colour constants
      i18n.py        _t and the deck labels
    plugins/
      tiling.py  layouts.py  timers.py  sound.py  bluetooth.py  a11y.py
      translate.py  todo_terminals.py  claude_sessions.py
      mpv_sessions.py  dev_reload.py
```

- `__main__.py` runs with `sys.path[0]` set to the package directory. Its
  first statements insert `script/stream_deck/` at the front of
  `sys.path` and remove the package directory, so that `import
  erplibre_streamdeck.app`, `import deck_lock` and `import translator`
  resolve, and no package module shadows a top-level name.
- `main()` in `__main__.py` keeps the shape `test_deck_lock` pins:
  `body[0]` is `deck_lock.acquire_or_exit("tiler")`, `body[1]` is
  `deck_lock.exit_on_sigterm()`. The "No visual Stream Deck found." block
  and `sys.exit(deck_lock.NO_DECK_EXIT)` move to `app.py`; the test reads
  them there.
- `paths.py` anchors every path on `Path(__file__).resolve()`:
  `STREAM_DECK_DIR` (parent of the package) and `REPO_ROOT` (two levels
  above it). Today's `__file__`-relative paths (repository root for the
  TODO terminals, `translator_stream.py`) read these constants; a deeper
  module never recomputes them.
- The plugin `translate.py` is not named `translator.py`, so that
  `import translator` inside it reaches the sibling module.
- No package module is named `game_*.py`, and no class takes a TODO mixin
  name (`test/test_todo.py` walks every `*.py`).

## Plugin interface

`plugin.py` defines plain dataclasses and `PLUGIN_API = 1`.

```python
@dataclass(frozen=True)
class KeyFace:
    color: tuple
    text: str = ""
    icon: str | None = None
    extra_draw: Callable | None = None

@dataclass
class Page:
    id: str                                   # today's mode string
    keys: Callable[[Geometry], dict]          # named key indexes
    render: Callable[[Context], None]
    handle: Callable[[Context, int], None]
    tick: Callable[[Context, float], None] | None = None
    period: float = 0.0                       # seconds between ticks

@dataclass
class HomeButton:
    order: int
    face: Callable[[Context], KeyFace]
    press: Callable[[Context], None]

@dataclass
class Fixture:
    place: Callable[[Geometry, dict], list]   # (geo, home keys) -> keys
    face: Callable[[Context, int], KeyFace | None]
    press: Callable[[Context, int], None]

@dataclass
class TileProvider:
    order: int
    items: Callable[[Context], list]
    face: Callable[[Context, object], KeyFace]
    press: Callable[[Context, object], None]

@dataclass
class Plugin:
    api: int
    pages: list = field(default_factory=list)
    home_buttons: list = field(default_factory=list)
    fixtures: list = field(default_factory=list)
    tiles: list = field(default_factory=list)
    home_tick: Callable[[Context, float], None] | None = None
    home_period: float = 0.0
    setup: Callable[[Context], None] | None = None
    shutdown: Callable[[Context], None] | None = None
```

- A plugin's **id is its file stem**. The loader sets it; a plugin does
  not declare it. TODO lists plugins by file name without importing them
  (it runs in `.venv.erplibre`, without PIL).
- A plugin keeps its own state in `ctx.state(<id>)`, a per-plugin
  namespace object created by the kernel. `setup` fills it (for example
  the translator's backend detection and the restore from
  `settings.json`, today in `Tiler.__init__`).
- Page ids are today's mode strings (`"tiling"`, `"timer_list"`,
  `"timer_reset_confirm"`, `"sound"`, `"layout"`,
  `"layout_delete_confirm"`, `"a11y"`, `"bluetooth"`, `"translator"`,
  `"translator_history"`, `"claude_session"`, `"mpv_session"`,
  `"todo_session"`). `"idle"` is the kernel's home page.

### Context

`Context` is the only object a plugin receives. It offers:

| Member | Meaning |
|---|---|
| `geo` | `cols`, `rows`, `total_keys` |
| `set_key(key, face_or_args...)` | paint one key through `ui.render` |
| `flash(ok, reason=None)` | set the result flash on the pressed key and its neighbours; `reason` goes to the journal on error (today's `_flag_err`) |
| `goto(page_id)` / `home()` | change page and render |
| `render()` | redraw the current page |
| `state(plugin_id)` | the plugin's namespace |
| `dbus` | the D-Bus client (`call`, `available`) |
| `settings` | `load()` / `save(data)` of `settings.json` |
| `style` | the display style (font scale, labels) |
| `t(label)` | the deck label translation |
| `log(msg)` | one journal line prefixed with the plugin id |

Every `render`, `handle`, `tick`, `home_tick` and tile/fixture callback is
called **with the kernel lock held**, as today. The D-Bus recheck while
the extension is missing stays in the kernel, outside the lock.

## Kernel

- `Kernel.handle_key(key, pressed)`: ignores releases and presses during
  a flash, records `last_press_key`, then dispatches to the home screen
  or to the current page's `handle`.
- `Kernel.render()`: renders the page, then overlays the flash while it
  lasts, as today (`RESULT_FLASH_SEC`, pressed key and its four
  neighbours, whole deck when no key is recorded).
- `Kernel.loop()`: every 0.3 s, outside the lock, the D-Bus recheck; then
  under the lock, in this precedence:
  1. a flash that has expired → render;
  2. on a page with a `tick`, call it when `period` has elapsed;
  3. on the home screen, call every plugin's `home_tick` whose
     `home_period` has elapsed, then render once if any ran.

  Today's `elif` chain maps onto it: the tiling timeout, the timer list
  refresh (2 s), the TODO session poll (1 s), the translator VAD and
  recording timeout are page ticks; the pending TODO capture, the timers
  and the TODO registry refresh (2 s) are home ticks.
- `app.main()` builds the kernel, renders, installs the key callback that
  takes the lock, starts the loop thread, and on exit calls every
  plugin's `shutdown` (the translator terminates its streaming process,
  today in `main`), then resets and closes the deck.
- `main` stops probing D-Bus a second time: it prints from the kernel's
  first check.

### Error isolation

Every call into a plugin goes through one wrapper that knows the plugin
id.

| Where it raises | What the kernel does |
|---|---|
| import or `setup` | the plugin is refused (see Loader) |
| page `handle` | log with traceback, flash ERR on the pressed key, go home |
| page `render` | log, render the home screen instead |
| page `tick` | log, go home |
| `home_tick`, tile `items`/`face`, fixture `face` | log; that provider's tiles or that fixture stay empty this render |
| `press` of a home button, fixture or tile | log, flash ERR |
| `shutdown` | log, continue with the next plugin |

A failure is logged once per `(plugin id, exception type, message)` and
logged again only after the same call has succeeded once, so a provider
that fails every 2 s does not flood the journal.

## Home screen

`home.py` computes the allocation once per geometry and set of plugins,
and the dashboard once per render.

1. **Home buttons**, sorted by `order`, take row 0 left to right; when the
   deck has at least three rows, the overflow takes row 1 from column 0
   until the row is full; the rest get no key. This is today's
   `_compute_idle_buttons`. The repository plugins use the orders that
   reproduce today's row: `tiling` 10 (TILE), `timers` 20 (TIMER),
   `dev_reload` 30, `sound` 40, `layouts` 50, `a11y` 60, `bluetooth` 70,
   `translate` 80, `todo_terminals` 90.
2. **Fixtures** are placed next, given the geometry and the home keys
   already allocated: `sound`'s microphone indicator at the bottom-left
   key on decks with two rows or more; `layouts`' shortcut keys on the
   last row under the LAYOUT key, one per slot, when they fit.
3. **The dashboard** takes every remaining key from row 1 on, in reading
   order. Providers fill it in `order`: `mpv_sessions` 10,
   `claude_sessions` 20, `timers` 30 (running timers not dismissed),
   `todo_terminals` 40. The render stores the `key → (provider, item)`
   map; a tap reads that map.
4. Key 0 shows "NO EXT" when the extension is missing and nothing else
   took key 0. That stays in the kernel.

**The one change in behaviour.** Today a tap re-reads the session lists
and recomputes the offsets, so a session that appeared since the last
render shifts the tiles and the tap can open a neighbour. After B2 the
tap opens what the key showed. The render that happens every 2 s on the
home screen keeps the map fresh.

A plugin turned off loses its home button, fixtures and tiles; the rest
are allocated by the same rules, so the remaining buttons close up.

## Loader

- Directories, in this order:
  1. `erplibre_streamdeck/plugins/*.py`;
  2. `$XDG_CONFIG_HOME/erplibre-home/deck-plugins/*.py`, with
     `XDG_CONFIG_HOME` defaulting to `~/.config`, the directory that
     already holds `streamdeck.conf`.
- Files whose name starts with `_` are skipped. The id is the file stem
  and must match `[a-z][a-z0-9_]*`; another stem is refused.
- Repository plugins are imported as `erplibre_streamdeck.plugins.<id>`;
  user plugins by path, as `erplibre_streamdeck_user.<id>`.
- `DECK_PLUGINS_OFF` is read once at start through the shell settings
  library, as the gallery reads `GAMES`, so the shell and Python agree on
  the file format. An id listed there is not imported at all.
- A user plugin with the id of a repository plugin replaces it; one
  journal line says so. Turning the id off turns off both.
- A plugin is **refused**, with one journal line giving the reason, when
  its import raises, it has no `PLUGIN`, `PLUGIN.api != PLUGIN_API`, its
  `setup` raises, or one of its page ids is already taken by a plugin
  loaded before it. The deck starts with the others.
- `python script/stream_deck/erplibre_streamdeck --list-plugins` prints
  one line per plugin found (`active`, `off`, `refused: <reason>`,
  `replaced by user`) and exits 0. It does not open the deck and does not
  take the lock. The `if __name__ == "__main__"` block calls
  `list_plugins()` when the option is given and `main()` otherwise, so
  `main.body[0]` stays `acquire_or_exit`.

## The `DECK_PLUGINS_OFF` setting

- Key in `streamdeck.conf`; value: plugin ids separated by commas, spaces
  allowed around them; empty by default. Unknown ids have no effect.
- Shell (`erplibre_home_settings.sh`): `deck_plugins_off` prints the
  normalised list, one id per line.
- Python (`script/todo/erplibre_home_service.py`): `DEFAULTS` gains
  `"DECK_PLUGINS_OFF": ""`, plus `plugins_off(settings) -> list` and
  `deck_plugin_ids(repo_root, config_home) -> list` (file stems of both
  directories, sorted, without import).
- TODO › Stream Deck gains entry [12] "Plugins on/off": it lists the
  plugin ids with their state, toggles the chosen one, writes the
  setting, and offers to restart the deck service when it is active.
  fr and en strings in `todo_i18n.py`.
- TODO › Status: a `Plugins off:` line when the list is not empty; the
  diagnosis names every id in the list that matches no plugin file.
- The installer gets no flag (as for `GAMES`).

## Contracts that stay

- `DECK_PROGRAM=tiler`, the service unit, exit codes 2 (busy lock), 3 (no
  visual deck), 143 (SIGTERM).
- `deck_program_path tiler` → `script/stream_deck/erplibre_streamdeck`
  (a directory with `__main__.py`); `erplibre_home_deck.sh` keeps
  `exec "$VENV_PYTHON" "$RACINE/$SCRIPT"`, which runs a directory.
- `make streamdeck_erplibre` and its alias `streamdeck_tiler` run the
  directory; `make streamdeck_tiler_unittest` runs the new tests.
- `settings.json`, `layouts.json`, `todo_terminals.json`, the
  `todo/todo-<epoch>.log` files, the Claude and mpv state directories,
  the D-Bus method names.

## Migration order

Each step leaves the suite green and the service startable.

0. **Safety net, against the monolith.** Characterization tests with a
   fake deck (`key_layout`, `key_image_format`, `set_key_image`) and
   `set_key` patched to record `(key, color, text, icon)`:
   - every page at 3×2, 4×2, 5×3 and 8×4, with fixed inputs (stubbed
     D-Bus, wpctl, bluetoothctl, tracker, state directories, clock);
   - the home screen with a full dashboard, the main transitions, the
     flash overlay;
   - the outputs are frozen as reference files in
     `test/fixtures/erplibre_streamdeck/`.
   Dead code goes in its own commit before the move (the `urllib`
   imports, `GALLERY_RESTART_URL`, `COLOR_ACTIVE`, `_wpctl_available`,
   `_enter_claude_session_mode`, `_focus_claude_for_key`, the
   `last_prompt` read).
1. **Kernel, `ui/`, `dbus.py`, `settings.py`, `paths.py`, `plugin.py`,
   `loader.py`, `home.py`**, built next to the monolith, with unit tests.
2. **Plugins, one per commit**, simplest first: `a11y`, `bluetooth`,
   `sound`, `layouts`, `timers`, `tiling`, `dev_reload`, `translate`,
   `mpv_sessions`, `claude_sessions`, `todo_terminals`. After each, the
   package reproduces the reference files of the pages it owns.
3. **Switch, in one commit**: `__main__.py`, `deck_program_path`, the
   Makefile, `test_deck_lock`, `test_erplibre_home_deck`,
   `test_streamdeck_entry_points`; `erplibre_streamdeck.py` and
   `script/stream_deck/test_erplibre_streamdeck_chunks.py` are deleted
   (its 26 tests now live in `test/`). One commit, so that no commit has
   a service whose program path points at nothing.
4. **`DECK_PLUGINS_OFF`**: shell, Python, TODO menu, Status, i18n.
5. **Docs**: `README.base.md` (package layout, "Writing a plugin"),
   `INSTALL.base.md`, `gpt.base.md`, `CHANGELOG.base.md`, then mmg;
   `ARCHITECTURE.md`, `DEBUG.md` and `lib/mpv-state.js:15` directly.

## Tests

- New files `test/test_erplibre_streamdeck_*.py`. A shared helper module
  in `test/` installs stub `PIL`, `StreamDeck` and `translator` modules
  in `sys.modules` before importing the package, and provides the fake
  deck and the `set_key` recorder.
- Characterization (step 0) then parity: the package must reproduce
  every reference file.
- Kernel: dispatch, flash precedence, the tick schedule, error isolation
  for each row of the table, the once-per-failure journal rule.
- Home: allocation at the four geometries with every plugin, with each
  plugin turned off, and with a user plugin added; tap and render agree
  for every dashboard key.
- Loader: both directories, `_`-prefixed files, a bad stem, a missing
  `PLUGIN`, a wrong `api`, an import that raises, a `setup` that raises,
  a duplicate page id, a user plugin replacing a repository plugin,
  `DECK_PLUGINS_OFF` with spaces and unknown ids, `--list-plugins`
  output.
- Backends: parsers that have no test today (`wpctl status`,
  `bluetoothctl`, the gdbus tuple, the Claude status derivation, the
  TODO registry pruning, `_label_for_timer`).
- Contracts: `test_deck_lock` on `__main__.py` and `app.py`;
  `deck_program_path tiler` names a directory holding `__main__.py`;
  the Make recipes; no `game_*.py` in the package.
- Setting: shell and Python parity on `DECK_PLUGINS_OFF`, the TODO entry
  in fr and en, the Status line and diagnosis.
- `make streamdeck_tiler_unittest` runs the same `test/` files.

## Risks

1. **Characterization blind spots.** A page whose inputs the fake cannot
   reproduce is not pinned. Each reference file names its inputs; the
   final review lists the pages without one.
2. **Import-time PIL use.** The stubs cover only what the monolith uses
   today; a plugin that touches PIL at import breaks the test load.
   Plugins import PIL lazily or through `ui.render`.
3. **Monkeypatch namespaces.** Tests patch the module that owns a name
   (`erplibre_streamdeck.dbus`), never a copy imported elsewhere.
4. **Style read at call time.** `set_key` reads `ctx.style` on every
   call; a module-level copy would freeze the font scale.
5. **User plugins run in the service.** They are code under the user's
   own configuration directory, with the same trust as their shell
   profile. The README says so.
6. **Path depth.** Every path goes through `paths.py`; a test checks that
   `REPO_ROOT / "script/todo/todo.py"` and
   `STREAM_DECK_DIR / "translator_stream.py"` exist.
7. **Formatting churn.** Moves and reformatting go in separate commits;
   black is never run on whole files (it uses 88 columns; the repository
   uses 79).
