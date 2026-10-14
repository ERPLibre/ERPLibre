# ERPLibre Home: renaming the GNOME extension

**Status:** design, awaiting review.
**Follows:** `2026-10-13-streamdeck-deployment-design.md`, whose plan has
not started. This rename lands first; the deployment spec and plan are
amended to the new names before any of their tasks run.

## Goal

The GNOME extension shipped as "Stream Deck Tiler" has grown past window
tiling: it carries six panel indicators (device, network, ERPLibre,
media, pencil, controller), a D-Bus interface and Claude Code hooks. It
becomes **ERPLibre Home**, the desktop sibling of ERPLibre Home Mobile
(`mobile/erplibre_home_mobile`). The Stream Deck becomes one input device
of that product among others.

Success means:

- every identifier of the extension carries the new name;
- a workstation that runs the old extension keeps its settings and data
  after one `make erplibre_home_install_extension` and a relog;
- the deployment plan builds its installer directly under the new names.

## Out of scope

- **Splitting `script/stream_deck/game_tiler.py`.** The file keeps its name
  here and only follows the new D-Bus names and data paths. Its split into
  `stream_deck_game.py` plus one module per domain (tiling with the
  extension, timers with the Tracker extension, sound/Bluetooth/
  accessibility/translator/terminals with the desktop environment, mpv
  sessions with `erplibre_home_media`, Claude sessions to be placed) is a
  separate project with its own spec, written after this one lands.
- The Stream Deck games (`game_*.py`) and their `make streamdeck_<game>`
  targets, including `make streamdeck_tiler`, which runs `game_tiler.py`,
  and `make streamdeck_tiler_unittest`, which runs `game_tiler.py`'s
  tests and not the extension's.
- The April 2026 specs and plans under `docs/superpowers/`: they record
  past designs and keep the names they were written with.
- `script/stream_deck/screenshots/`: it documents the whole Stream Deck
  project and stays where it is.

## Names

| Element | Before | After |
|---|---|---|
| Directory | `script/stream_deck/gnome-extension/` | `script/gnome-extension/erplibre_home/` |
| UUID | `streamdeck-tiler@technolibre.ca` | `erplibre-home@technolibre.ca` |
| `metadata.json` name | `Stream Deck Tiler` | `ERPLibre Home` |
| `metadata.json` description | `D-Bus interface for window tiling from Stream Deck` | `ERPLibre for personal environment` |
| GSettings schema id | `org.gnome.shell.extensions.streamdeck-tiler` | `org.gnome.shell.extensions.erplibre-home` |
| dconf path | `/org/gnome/shell/extensions/streamdeck-tiler/` | `/org/gnome/shell/extensions/erplibre-home/` |
| Schema file | `schemas/org.gnome.shell.extensions.streamdeck-tiler.gschema.xml` | `schemas/org.gnome.shell.extensions.erplibre-home.gschema.xml` |
| D-Bus object path | `/org/gnome/Shell/Extensions/StreamDeckTiler` | `/org/gnome/Shell/Extensions/ERPLibreHome` |
| D-Bus interface | `org.gnome.Shell.Extensions.StreamDeckTiler` | `org.gnome.Shell.Extensions.ERPLibreHome` |
| Journal prefix | `[StreamDeckTiler]` | `[ERPLibreHome]` |
| gettext domain, `.pot`, `.mo` | `streamdeck-tiler` | `erplibre-home` |
| Config data | `~/.config/streamdeck-tiler/` | `~/.config/erplibre-home/` |
| State data | `$XDG_STATE_HOME/streamdeck-tiler/` | `$XDG_STATE_HOME/erplibre-home/` |
| Cache data | `~/.cache/streamdeck-tiler/` | `~/.cache/erplibre-home/` |
| Nested-shell runtime dir | `$XDG_RUNTIME_DIR/streamdeck-tiler-nested` | `$XDG_RUNTIME_DIR/erplibre-home-nested` |
| Claude hook script | `hooks/streamdeck-tiler-hook.py` | `hooks/erplibre-home-hook.py` |
| Claude hook tag in `settings.json` | `streamdeck-tiler` | `erplibre-home` |
| Hot-reload copy prefix | `streamdeck-tiler-reload-` | `erplibre-home-reload-` |
| Make variables | `STREAMDECK_TILER_EXT_*` | `ERPLIBRE_HOME_EXT_*` |
| Make targets | `streamdeck_tiler_{install,enable,uninstall}_extension`, `streamdeck_tiler_uninstall`, `streamdeck_tiler_reload`, `streamdeck_tiler_reload_clean`, `streamdeck_tiler_dev_nested`, `streamdeck_tiler_e2e_nested`, `streamdeck_tiler_compile_locale` | `erplibre_home_` with the same suffixes |
| Git sync file in the user's sync repository | `streamdeck-tiler.json` | `erplibre-home.json` |
| CSS classes | `streamdeck-tiler-dialog`, `streamdeck-tiler-btn` | `erplibre-home-dialog`, `erplibre-home-btn` |

Capitalisation: `ERPLibre` wherever the name carries capitals
(`ERPLibreHome`, "ERPLibre Home"); all lower case with a hyphen where
the identifier is lower case (`erplibre-home`), and with an underscore
in a Python or make name (`erplibre_home`).

Every file that names one of these identifiers follows: the extension's
JS, its tests, `po/`, its docs (`README.base.md`, `hooks/README.base.md`,
`ARCHITECTURE.md`, `DEBUG.md`, `CHANGELOG.md`), `game_tiler.py`,
`erplibre_controller.py`, `translator.py`, `gpt.base.md`,
`requirements.txt`, `screenshots/capture.sh`,
`conf/make.streamdeck.Makefile`, `conf/make.installation.Makefile` and
`conf/make.test.Makefile`. Generated `.md`/`.fr.md` files are rebuilt with
`mmg`, never edited.

## The directory move

`script/stream_deck/gnome-extension` and `script/gnome-extension/erplibre_home`
sit at the same depth under the checkout, so paths that climb to the
checkout root keep working. Paths that reach a sibling of the old
directory do not, and change with the move:

- `indicators/device.js` derives the checkout root by stripping
  `/script/stream_deck/gnome-extension` from the extension path; it
  strips `/script/gnome-extension/erplibre_home` instead.
- `README.base.md` links `../screenshots/`, which becomes
  `../../stream_deck/screenshots/`.
- `CONTROLLER_REL` and every other path given relative to the checkout
  root (`script/stream_deck/...`) is unchanged.

The installed symlink keeps its role: `~/.local/share/gnome-shell/
extensions/erplibre-home@technolibre.ca` points at the checkout's
`script/gnome-extension/erplibre_home`.

## Migration of an existing installation

A workstation that ran the old extension holds its state in five places:
the enabled-extensions list, the extension symlink (plus any hot-reload
copies), the dconf path, three XDG data directories, and possibly Claude
hook entries in `~/.claude/settings.json`. After the move, the old
symlink points at a directory that no longer exists.

`script/gnome-extension/erplibre_home/tools/migrate_legacy.py` moves that
state over. Pure functions decide each step from what they are given;
a thin `main()` gathers the facts and applies the decisions. Every step
is idempotent, so running it twice changes nothing the second time.

1. **Extension.** In `org.gnome.shell enabled-extensions`, replace
   `streamdeck-tiler@technolibre.ca` with `erplibre-home@technolibre.ca`
   in place, keeping every other entry and their order; when the new UUID
   is already listed, drop the old one instead. Leaving the list is what
   disables the old extension. A list without the old UUID is not
   touched. Then remove the old symlink and every
   `streamdeck-tiler-reload-*@technolibre.ca` entry under the extensions
   directory; this part needs no session bus.
2. **dconf.** When `/org/gnome/shell/extensions/erplibre-home/` holds no
   key and the old path holds at least one, copy the old dump into the
   new path (`dconf dump` / `dconf load`). The old path is left as is:
   it costs nothing and lets a rollback find its settings.
3. **Data directories.** For each of config, state and cache, rename
   `<base>/streamdeck-tiler` to `<base>/erplibre-home` when the source
   exists and the destination does not. When both exist, touch neither
   and print one line naming both paths. The rename is a single
   `os.rename` within the same parent, hence atomic.
4. **Claude hooks.** An installed hook is a `settings.json` entry whose
   command is the absolute path of the hook script, so the move leaves it
   pointing at a file that no longer exists. When `~/.claude/settings.json`
   holds an entry whose command ends in `/streamdeck-tiler-hook.py`, the
   migration removes every such entry and installs the new hook through
   the functions of `install_claude_hooks.py` (backup, atomic write). A
   workstation that never installed the hooks does not get them.
5. **No session bus.** The list edit of step 1 and step 2 need the live session bus (the
   deployment spec explains how it is found from ssh). Without it, they
   are skipped with one line saying so, and the script exits 0: nothing
   was copied, so the next run performs them.

6. **Git sync file.** The extension's optional git sync writes its
   settings to a file in a repository shared between workstations, which
   may still run the old extension. The export writes `erplibre-home.json`;
   the import reads `erplibre-home.json`, and `streamdeck-tiler.json` only
   when the new file is absent. This fallback lives in `lib/git-sync.js`.

The script prints one line per action taken and nothing for a step with
nothing to do. A failing command prints a warning on stderr and the
script goes on with the next step and exits 0: a migration that cannot
finish must not block the installation it precedes. `make erplibre_home_install_extension` runs it before
creating the new symlink; the deployment plan's installer runs the same
target. The script and its tests are the only places in the tree that
still name the legacy identifiers, together with the extension
`CHANGELOG.md` entry and the sync-file fallback of `lib/git-sync.js`. It is removed in a later release, once no
development workstation runs the old extension.

On Wayland the shell loads a new UUID only at login: the install target
already says to log out and back in, and still does.

## Deployment spec and plan

Both are amended in their own commit, before any of their tasks runs.
The rule: what installs or tests the **product** takes the product name;
what belongs to the **Stream Deck hardware or its Python programs** keeps
`streamdeck`.

| Becomes `erplibre_home` | Keeps `streamdeck` |
|---|---|
| `script/install/install_streamdeck.sh` → `install_erplibre_home.sh` | `.venv.streamdeck` (the venv of the deck programs) |
| `make streamdeck_install` / `streamdeck_uninstall` → `erplibre_home_install` / `erplibre_home_uninstall` | `make streamdeck_<game>`, `streamdeck_gallery`, `streamdeck_translator_*` |
| `long_test/install_streamdeck.py` → `long_test/install_erplibre_home.py` | `test/test_streamdeck_entry_points.py` |
| `qemu_streamdeck*` → `qemu_erplibre_home*` | the "Stream Deck games" TODO menu |
| `_streamdeck_install_local` → `_erplibre_home_install_local`, menu text "ERPLibre Home install" | udev rules for the deck |
| every extension path, UUID, target and journal line from the table above | |

The spec and plan files keep their file names; their titles and body
follow the rule. Task 2's `project-root.js` strips the new directory
suffix. The `extension-indicators` check of the long test greps
`\[ERPLibreHome\] (mount [^ ]+ failed|enabled)`.

## Verification

- `git grep` finds no legacy identifier (`streamdeck-tiler`,
  `StreamDeckTiler`, `streamdeck_tiler_`, `STREAMDECK_TILER_`,
  `stream_deck/gnome-extension`) outside: `tools/migrate_legacy.py` and
  its test, the extension `CHANGELOG.md`, the April 2026 docs, and the
  `streamdeck_tiler` and `streamdeck_tiler_unittest` game targets with
  `game_tiler.py`'s file name, and the `lib/git-sync.js` fallback.
- `make test_gnome_extension` passes (212 tests, none removed).
- `./script/test/run_unit_test.sh` passes, including the new migration
  tests: each step's decision for "nothing to do", "old only", "new
  only", "both present", and "no bus".
- `make erplibre_home_e2e_nested` passes headless on GNOME 51: the shell
  reports `erplibre-home@technolibre.ca` ACTIVE, `ERPLibreHome` answers
  `DebugClaudeIndex`, the journal has `[ERPLibreHome] enabled` and no
  `mount … failed`.
- **The migration runs for real on a workstation that has the old
  extension installed and enabled**, with a state directory present:
  after `make erplibre_home_install_extension` and a relog, the old UUID
  is gone from `enabled-extensions`, the new one is ACTIVE, the old
  symlink is gone, `$XDG_STATE_HOME/erplibre-home/` holds what the old
  directory held, and a second run prints nothing.

## Commits

1. `git mv` of the directory with the path-only fixes that keep every
   target working (make variables, the three places that strip the
   directory suffix, the screenshots link), so `git log --follow` and
   blame keep the history and the commit builds on its own.
2. The identifier rename across the tree, with the regenerated docs.
3. The migration script, its tests, and its call from the install target.
4. The git sync file fallback.
5. The amended deployment spec and plan.

Commit 2 changes more than 500 lines, which `AI_POLICY.md` submits to
the maintainer's agreement before it is made.
