# Architecture

How the GNOME extension, the Stream Deck driver and Claude Code hooks
talk to each other. Everything is local: no daemons, no network, no
persistent storage outside `$XDG_STATE_HOME/streamdeck-tiler/`.

## Process map

```
+-------------------+    JSONL files     +---------------------+
|  Claude Code      | -----------------> |  $XDG_STATE_HOME/   |
|  (claude binary)  |                    |  streamdeck-tiler/  |
|                   |     fires hooks    |  claude/{sid}.json  |
+--------+----------+                    +---------+-----------+
         |                                          |
         | gdbus call                               | Gio.FileMonitor
         v                                          v
+--------+----------+                    +---------+-----------+
|  GNOME Shell      |                    |  ClaudeStateWatcher |
|  (gjs / mutter)   | <----------------- |  (lib/claude-state) |
|  extension.js     |   indexed sessions +---------------------+
+--------+----------+
         |
         | adds indicators
         v
+--------+----------+      D-Bus      +---------------------+
|  Top-bar buttons  | <-------------> |  game_tiler.py      |
|  (indicators/*)   |                 |  (Stream Deck       |
|                   |                 |   physical hardware)|
+-------------------+                 +---------------------+
```

## Data flow: Claude session → coloured badge

1. **`claude` runs a hook**. `hooks/streamdeck-tiler-hook.py` wakes
   on every `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `Stop`,
   `Notification`, `SessionEnd` event.
2. **Hook writes state**. The hook stamps the matching field
   (`ts_active`, `ts_tool`, `ts_stop`, `ts_notification`) in
   `$XDG_STATE_HOME/streamdeck-tiler/claude/{session_id}.json`.
3. **Hook captures the focused window id** (when SessionStart /
   UserPromptSubmit fires) by calling the extension's
   `GetFocusedWindowId` D-Bus method, so the row "Click to focus
   terminal" later resolves to the right Mutter window.
4. **`ClaudeStateWatcher` notices**. A `Gio.FileMonitor` plus a 2 s
   poll timer reload every changed file, derive `status` from the
   max timestamp (`notify > stop > tool > active`) and rebuild a
   subscriber index `{byPath, totalAlive, totalAwaitStop, …}`.
5. **`PencilIndicator` re-renders**. The indicator subscribes to the
   watcher, calls `_refreshBadge()` (paths + most-severe secondary
   slot) and `_rebuildMenu()` if the dropdown is open.
6. **Optional desktop notification**. When a session transitions to
   `awaiting_notification` the extension fires `Main.notify(...)`
   once per `ts_notification` value (throttled).
7. **Deck mirror**. `game_tiler.py` reads the same state files in
   its render loop and shows a coloured per-session button (green /
   cyan / yellow / red) on its idle layout.

## Key surfaces

| Layer | Code | Notes |
| --- | --- | --- |
| Hooks | `hooks/streamdeck-tiler-hook.py` | One Python script, six events. Idempotent per `(session_id, event)`. |
| State | `$XDG_STATE_HOME/streamdeck-tiler/claude/{sid}.json` | Plain JSON, atomic writes. |
| Watcher | `lib/claude-state.js` | `parseStateEntry`, `indexSessions`. Pure helpers, unit-tested. |
| Indicator | `indicators/pencil.js` | Lazy import so node tests can read `lib/`. |
| D-Bus | `extension.js` | Interface `org.gnome.Shell.Extensions.StreamDeckTiler` exposes `FocusClaudeSession`, `GetFocusedWindowId`, `AcceptClaudeSession`, `SetClaudeSessionWindow`, `KillClaudeSession`, `RenameClaudeSession`, `DebugClaudeIndex`, `ListMpvSessions`, `MpvSendCommand`, `TileWindow`, `OpenPath`, `OpenMedia`, etc. |
| Driver | `script/stream_deck/game_tiler.py` | Python streamdeck library, reads the same state directories, calls back into the extension over D-Bus. |

## D-Bus interface

```
gdbus introspect --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler
```

Used by:
- the Claude hooks (`GetFocusedWindowId`),
- the deck driver (`FocusClaudeSession`, `AcceptClaudeSession`,
  `SetClaudeSessionWindow`, `KillClaudeSession`,
  `MpvSendCommand`, `TileWindow`),
- developers (`HotReload`, `DebugClaudeIndex`, `ListWindows`).

## Hot reload

`HotReload` clones the source folder under
`streamdeck-tiler-reload-{ts}@technolibre.ca`, calls
`gnome-extensions enable` on the new UUID and disables the old one.
Each indicator class registers a per-process random `GTypeName`
suffix so the second load does not collide with GObject's
process-wide type table.

## Settings + migrations

- `Gio.Settings(schema_id='org.gnome.shell.extensions.streamdeck-tiler')`.
- Schema in `schemas/*.gschema.xml`, compiled at install via
  `glib-compile-schemas`.
- Migrations in `lib/migrations.js`, runner exits on first failed
  step so the next launch retries.

## Translations

- Source strings in JS through `_()` (`lib/i18n.js` thin wrapper
  over the GNOME extension's `gettext`).
- Catalogues under `po/{lang}.po`, compiled to
  `locale/{lang}/LC_MESSAGES/streamdeck-tiler.mo` at install.
- Locale resolution comes from the system `LANG`; the
  `gettext-domain` field in `metadata.json` ties it together.

## Tests

- `test/unit/*.test.js` — Node tests covering pure helpers.
- `test/e2e_nested.sh` — opt-in nested gnome-shell smoke test.
- `test/manual.md` — checklist for shell-only behaviours.
