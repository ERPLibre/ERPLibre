# ERPLibre Stream Deck: games apart, deck program renamed

**Status:** design, awaiting review.
**Sub-project:** B1 of the `game_tiler.py` project. B2 (split of the deck
program into a plugin package) and B3 (defects: blocking calls under the
lock, atomic `settings.json`, Claude and mpv liveness, refresh of their
pages) get their own specs once this one lands.
**Builds on:** `2026-10-14-erplibre-home-deck-service-menu-design.md`
(deck service, `streamdeck.conf`, deck lock, hand-over, Stream Deck
submenu).

## Goal

`script/stream_deck/` mixes two things that the name `game` confuses:

- the **deck program**, `game_tiler.py`: a desktop tool that tiles windows
  through the ERPLibre Home extension and drives sound, Bluetooth, timers,
  terminals and sessions. It runs as the `erplibre-home-streamdeck`
  service. It is not a game;
- the **game library**: 45 `game_*.py` files and the gallery that lists
  and launches them.

After B1:

- the deck program is `script/stream_deck/erplibre_streamdeck.py`;
- the games and the gallery live in `script/stream_deck/games/`;
- a setting `GAMES=on|off` turns the game library off while the deck
  program, the controller and the service stay installed and working.

A user who never plays sees no game anywhere once `GAMES=off`. A user who
runs `make streamdeck_tiler`, or whose settings say `DECK_PROGRAM=tiler`,
notices nothing.

## Out of scope

- Splitting the deck program into modules (B2) and its defects (B3). The
  file is renamed and loses `GAME_META` and `--meta`; nothing else in it
  changes.
- An installer flag for `GAMES`: the setting is set in `streamdeck.conf`
  or from the TODO Stream Deck submenu only.
- The extension reading `GAMES`: it keeps its Games submenu, and a refused
  launch shows in the terminal it opens. A follow-up may hide the submenu.
- Moving `Assets/`: its only user is `erplibre_controller.py`, which stays
  in `script/stream_deck/`.
- A compatibility `game_tiler.py`: there is none. Old paths break; the
  CHANGELOG lists them and the make target names keep working.
- `docs/superpowers/*` from earlier dates: they keep the names they were
  written with.

## Global constraints

- `DECK_PROGRAM=tiler` keeps its value and its meaning. No settings file is
  rewritten.
- The rename of `game_tiler.py` and the change of the `tiler` mapping in
  `script/install/erplibre_home_settings.sh` land in the same commit: in
  between, `erplibre_home_deck.sh` finds no script and the service fails.
- Moves use `git mv` and keep mode 100755.
- No game imports a sibling module, before or after (0 of 45 today); no
  `sys.path` code is added to `games/`.
- Every new user-facing TODO string has `fr` and `en` entries in
  `script/todo/todo_i18n.py`.
- Documentation changes go in `.base.md` files, regenerated with mmg.
  `script/gnome-extension/erplibre_home/ARCHITECTURE.md` and `DEBUG.md`
  have no `.base.md` and are edited directly.

## Layout

| Before | After |
|---|---|
| `script/stream_deck/game_<id>.py` (45) | `script/stream_deck/games/game_<id>.py` |
| `script/stream_deck/gallery_server.py` | `script/stream_deck/games/gallery_server.py` |
| `script/stream_deck/index.html` | `script/stream_deck/games/index.html` |
| `script/stream_deck/save/.gitkeep` | `script/stream_deck/games/save/.gitkeep` |
| `script/stream_deck/game_tiler.py` | `script/stream_deck/erplibre_streamdeck.py` |
| `script/stream_deck/test_game_tiler_chunks.py` | `script/stream_deck/test_erplibre_streamdeck_chunks.py` |

Unchanged: `Assets/`, `deck_lock.py`, `erplibre_controller.py`,
`translator.py`, `translator_stream.py`, `requirements.txt`. The deck
program stays in `script/stream_deck/`, so its `import deck_lock`,
`import translator`, its sibling path to `translator_stream.py` and its
`../..` repository root keep working.

### The deck program

- `erplibre_streamdeck.py` drops `GAME_META` and the `--meta` handler. It
  is no longer listed by the gallery, the TODO games menu or the
  extension's ERPLibre submenu: it is started as the service, or from the
  `device` indicator's "Start deck program".
- Its docstring and comments stop calling it a game.
- `script/install/erplibre_home_settings.sh` maps `tiler` to
  `script/stream_deck/erplibre_streamdeck.py`.

### The gallery

- `SCRIPT_DIR` is `games/`: discovery globs `games/game_*.py`, launches
  `games/game_<id>.py`, serves `games/index.html`, saves to `games/save/`.
- The repository root becomes `SCRIPT_DIR/../../..`; the hand-over path and
  the working directory follow it.
- `/api/restart` re-executes its own path. A gallery started before a
  `git pull` that moves it loses that path and must be started again; the
  CHANGELOG says so.

### The extension

- `lib/project-root.js` `GALLERY_SERVER_REL` becomes
  `script/stream_deck/games/gallery_server.py`, with its unit test.
- The ERPLibre submenu of the `controller` indicator lists the gallery
  entries whose `section` is `erplibre`. No game has that section once the
  tiler leaves the list, so the submenu is hidden when it is empty.
  `test/manual.md` no longer expects "Window Tiler" there.
- A GNOME Shell session that loaded the old path keeps it until the next
  login.

### Make

In `conf/make.streamdeck.Makefile`:

- the 45 `streamdeck_<id>` recipes run `script/stream_deck/games/game_<id>.py`;
- `streamdeck_erplibre` runs `script/stream_deck/erplibre_streamdeck.py`;
  `streamdeck_tiler` is an alias of it; both are in `.PHONY`;
- `streamdeck_gallery` runs `games/gallery_server.py`;
- `streamdeck_tiler_unittest` keeps its name; its pattern becomes
  `test_erplibre_streamdeck*.py`.

### Other

- `script/todo/todo.py` scans `script/stream_deck/games/game_*.py`. The
  `game_<id>` i18n keys come from the file name and do not change.
- `.gitignore` keeps `script/stream_deck/save/` and adds
  `script/stream_deck/games/save/`: `git mv` leaves ignored files behind,
  and the old line keeps them out of `git status`.
- Documentation: `script/stream_deck/README.base.md` (paths, the tree, the
  game count), `INSTALL.base.md` (tiler path, the `GAMES` key in en and
  fr), `gpt.base.md`, and a `CHANGELOG.base.md` entry with the old → new
  paths, the gallery restart note, and
  `mv script/stream_deck/save/* script/stream_deck/games/save/` for
  djscratch's saved loops. In the extension: `ARCHITECTURE.md`,
  `DEBUG.md`, the comment in `lib/mpv-state.js`.

## The `GAMES` setting

### Value

`GAMES` lives in `~/.config/erplibre-home/streamdeck.conf` (or under
`$XDG_CONFIG_HOME`), next to `DECK_PROGRAM` and `RESTART_AFTER_GAME`.

| Value | Meaning |
|---|---|
| `on`, or no `GAMES` line | games enabled (default) |
| `off` | games disabled |
| anything else, `GAMES=` included | games disabled, and the diagnosis names the value |

An unknown value fails closed, as an unknown `DECK_PROGRAM` does. The
installer neither writes nor rewrites `GAMES`: a missing key reads as `on`
everywhere.

### Readers

- Shell: `script/install/erplibre_home_settings.sh` gains
  `deck_games_enabled`, modelled on `deck_program_path`: it returns 0 for
  `on`, 1 for `off`, 2 for an unknown value.
- Python: `script/todo/erplibre_home_service.py` adds `"GAMES": "on"` to
  `DEFAULTS` and `GAMES_VALUES = ("on", "off")`. The shell/Python parity
  test over `DEFAULTS` covers the new key.

### Where `off` refuses

Every place that starts a game refuses, each with a message that names the
setting and how to turn it back on (the TODO Stream Deck submenu, or
`GAMES=on` in the file):

| Entry point | Refusal |
|---|---|
| TODO games menu (`prompt_execute_streamdeck_games`) | prints the message after the venv check, returns to the menu; no scan, no launch |
| Gallery `main()` | prints the message on stderr, exits 1, does not listen |
| Gallery `/launch/<id>` | 403 with a JSON `{"error": ...}`, for a gallery started while `on` |
| `make streamdeck_<id>` (45 targets) | a guard prerequisite prints the message and exits 1 |
| `erplibre_home_handover.sh` | after the usage check and before stopping the service: one line on stderr, exit 4, nothing stopped, nothing run |

Never gated: the deck service, `erplibre_streamdeck.py`, `streamdeck`
(the controller), `streamdeck_erplibre` / `streamdeck_tiler`, the
translator targets, `RESTART_AFTER_GAME`.

The hand-over passes a game's own exit code through, so exit 4 can also
come from a game. Its tests check the stderr line, not only the code.

### TODO

- The Stream Deck submenu gains an entry "Games: enabled / disabled",
  modelled on the deck program entry: it shows the current value (an
  unknown value is shown as invalid and needs an explicit choice), writes
  `GAMES` with `write_settings`, and restarts nothing. It does not need the
  unit to be installed.
- Status shows a `Games: on|off` line, even without a unit; an unknown
  value shows as `Games: unknown value "<v>"`.
- Diagnosis adds `Unknown GAMES value` with the menu path as the fix.

## Migration

- A settings file without `GAMES` reads as `on`: nothing changes for an
  existing install.
- The unit stores no script path: `erplibre_home_deck.sh` resolves the
  new one at the next start. A deck program running during the pull keeps
  running from memory.
- User scripts or aliases that call `script/stream_deck/game_*.py`,
  `game_tiler.py` or `gallery_server.py` by path break; the make target
  names keep working.
- Stale `__pycache__/game_*.pyc` files are harmless.
- `long_test/install_erplibre_home.py` only uses `--deck-program=tiler`
  and needs no change.

## Testing

Existing tests that change:

- `test/test_streamdeck_entry_points.py`:
  - `GAMES_DIR`; `jeux()` globs it, so the tiler is no longer required
    to have a game target;
  - expected recipes `games/game_<id>.py`;
  - `SHEBANG_DECK` widened from `\w+` to `[\w/]+`, without which the
    shebang guard stops covering the moved games without failing;
  - the tiler targets in `attendus`;
  - `charger_galerie()` loads `games/gallery_server.py`; the hand-over
    path check catches a wrong repository-root depth.
- `test/test_deck_lock.py`: the source-text checks read
  `erplibre_streamdeck.py`; the docstring "tiler launched as a game" is
  reworded.
- `test/test_erplibre_home_deck.py`: the new path, and the `assertNotIn`
  at its end names `erplibre_streamdeck.py` (with the old name it would
  pass for nothing).
- `script/stream_deck/test_erplibre_streamdeck_chunks.py`: loads the
  renamed file.
- `test/unit/project-root.test.js` (extension): the gallery path.
- `test/test_erplibre_home_service.py`: the exact `DEFAULTS` dict.

New tests:

1. The real scans, without mocks: `todo._scan_streamdeck_games` and the
   gallery's `_scan_games` find exactly `games/game_*.py`, and neither
   returns `tiler`. Today a wrong path only shows "No Stream Deck games
   found." and fails nothing.
2. Layout: no `game_*.py` left in `script/stream_deck/`; every game in
   `games/` is 100755, has the deck shebang, answers `--meta`, and imports
   no sibling module; `Assets/` sits next to `erplibre_controller.py`.
3. `deck_program_path tiler` and `deck_program_path controller` name files
   that exist.
4. `GAMES=off` and an unknown value at each entry point of the table above:
   the TODO message in fr and en with no scan and no launch; the gallery
   `main()` exit and the `/launch` 403; the make guard on a game target and
   its absence on the tiler, controller and translator targets; the
   hand-over's stderr line, exit 4, no `systemctl stop`, no command run.
5. `read_settings` gives `on` when the key is missing; `write_settings`
   round-trips `GAMES`.
6. The TODO entry: current value, invalid value, writing `on`/`off`, no
   restart, works without the unit.
7. Status and diagnosis lines, with and without a unit.
8. The ERPLibre submenu is hidden when no entry has `section: erplibre`
   (extension unit test).

The full unit suite (`./script/test/run_unit_test.sh`), the extension's
node tests and `make streamdeck_tiler_unittest` pass at every commit.

## Open risks

- A missed path shows an empty list rather than an error; new test 1 is
  the guard.
- A gallery or a GNOME Shell started before the pull points at the old
  gallery path until it is restarted or the user logs in again.
- Exit 4 of the hand-over overlaps a game's own exit code; the stderr line
  is the reliable signal.
- `GAMES=` (empty) or a typo disables the games; the Status line and the
  diagnosis make it visible.
