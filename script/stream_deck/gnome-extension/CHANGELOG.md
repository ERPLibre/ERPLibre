# Changelog

All notable changes to the ERPLibre Stream Deck GNOME extension. Format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project loosely follows semver — major bumps reserved for schema
migrations that are not auto-applied.

## [Unreleased]

### Added
- Help and About pages in the prefs window covering badge colours,
  Claude hooks, indicator interactions and project links.
- Hover tooltips on every top-bar indicator with a per-kind breakdown.
- Click on a pencil count badge filters the dropdown by kind
  (active / awaiting / notify) plus a Clear-filter row.
- `badge-orientation` GSetting (vertical default, horizontal opt-in)
  with a Theming-page combo that flips the layout live.
- Nested gnome-shell smoke test (`test/e2e_nested.sh` + Makefile
  target) that boots the extension on an isolated session bus and
  verifies the D-Bus interface answers.
- Auto-cancel for tiling mode after 5 s of inactivity so a half-picked
  TILE selection no longer locks the deck.
- Full French translations for indicators, prefs window, modal
  dialogs and notify body messages (264 catalogue entries total).
- Locale catalogues compile automatically as part of
  `make streamdeck_tiler_install_extension`.

### Changed
- Count badges sit beside the icon in a vertical stack capped at two
  slots with an 11 px font instead of overlaying the icon corner.
- Pencil collapses alive / awaiting / notify into a single
  severity-ranked secondary badge so the urgent state still wins.
- About link moved from the Controller dropdown into a dedicated
  About page in prefs with project, docs, contact and license links.
- Buttons toggle list, button-order and Theming icon overrides now
  reference `media` (the live indicator id) instead of the dead
  `film` toggle that did nothing post-migration.

### Fixed
- French accents and other non-ASCII glyphs render correctly on the
  deck buttons (DejaVu / Noto / Liberation TrueType fallback).
- HotReload UUID-rename clones the source folder instead of mutating
  metadata.json in place — fewer accidental git diffs.

## [0.x] — pre-1.0

### Indicators
- Controller (gallery server, ERPLibre tools, Games sections).
- Pencil (paths, Claude session rows with Set window / Accept /
  Rename / Kill, badge dropdown for active vs awaiting counts).
- Media (video + audio sections, Spotify launcher heuristic, mpv
  resume + IPC tracking, VLC bash wrapper, Firefox YouTube tab
  importer).
- ERPLibre (local detection + remote instances, KeePassXC unlock,
  auto-login via Selenium / xdotool, copy attribute toasts).
- Network (configured ssh hosts + nmap/nc subnet scan, sftp open,
  show details).
- Device (Stream Deck enumeration via lsusb, restart deck, status).

### Claude integration
- Hooks (`hooks/streamdeck-tiler-hook.py`) for SessionStart,
  UserPromptSubmit, PreToolUse, Stop, Notification and SessionEnd
  write JSONL state files under
  `$XDG_STATE_HOME/streamdeck-tiler/claude/`.
- Pencil indicator badges: catalogue blue, alive green, awaiting
  yellow / red with desktop notification on red transitions.
- Per-session deck action page (Focus / Accept / Set window /
  Kill / Back).
- Ctrl+C interrupt detection (Stop hook fires) treated as awaiting.

### Tiling on the deck
- TILE corner-pick mode with 2-press selection wired to Mutter's
  `org.gnome.Shell.Extensions.WindowTiler` D-Bus method.
- Auto-cancel after 5 s idle.

### Prefs window
- Buttons (toggle + drag-and-drop order in panel).
- Per-indicator pages (Pencil, Media, ERPLibre, Network, Device).
- Theming (badges + per-icon overrides).
- Sync (Git-backed settings sync), Advanced (export / import /
  reset), Log (last 200 activity entries).
- Help and About pages.

### Hot reload
- HotReload D-Bus method clones the source under a temporary UUID
  (`streamdeck-tiler-reload-<ts>@technolibre.ca`) and re-enables it
  without a session restart.

### Schema migrations
- v1 → v2: rename `enable-film` / `films` to `enable-media` /
  `media` (legacy keys kept readable for downgrade safety).

### Tests
- Node unit tests under `test/unit/` cover badges, pencil helpers,
  claude-state parsing, migrations, media helpers, settings
  serialisation, network parsing, log JSONL, mpv state.
- `test/manual.md` checklist for behaviours that need a running
  shell.
- Nested gnome-shell E2E smoke test (`test/e2e_nested.sh`).

[Unreleased]: https://github.com/ERPLibre/ERPLibre/tree/master/script/stream_deck/gnome-extension
