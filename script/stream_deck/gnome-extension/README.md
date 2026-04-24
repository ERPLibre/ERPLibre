# Stream Deck Tiler — GNOME Shell Extension

Companion D-Bus extension used by `game_tiler.py` to:

- Tile the focused window via `Meta.Window.move_resize_frame()` — no
  keyboard simulation, no gTile dependency.
- List and toggle timers managed by the
  [tracker](https://github.com/aliakseiz/tracker) extension
  (`tracker@aliakseiz.github.com`), which has no public API of its own.

Works on Wayland and X11, GNOME Shell 45–48.

## D-Bus interface

- Name: `org.gnome.Shell.Extensions.StreamDeckTiler`
- Path: `/org/gnome/Shell/Extensions/StreamDeckTiler`
- Methods:
  - `TileWindow(gridCols, gridRows, col1, row1, col2, row2) -> success`
  - `GetMonitorGeometry() -> (x, y, width, height)`
  - `GetGridSize(gridCols, gridRows) -> (cellW, cellH)`
  - `ListTrackerTimers() -> json` — JSON array of
    `{id, name, running, elapsed}` read from tracker's in-memory state.
    Returns `[]` if tracker is not installed or not enabled.
  - `ToggleTrackerTimer(id) -> success` — start a paused timer or pause
    a running one. Reaches into tracker's private state; may break on
    tracker upgrades.
  - `AddTrackerTimer() -> id` — create a new timer via tracker's
    `_addNewTimer()`, open tracker's panel menu, and enter edit mode on
    the new timer with the name entry focused and empty so the keyboard
    can type the name. Returns the new timer id, or empty string on
    failure.
  - `HotReload() -> newUuid` — copy the extension directory under a
    timestamped temp UUID, load it via `Main.extensionManager`, and
    swap the enabled instance so the new source code runs without a
    session re-login. Returns the new temp UUID, or empty string on
    failure. See "Hot reload" below.
  - `HotExit() -> success` — disable + remove all temp reload instances
    and re-enable the main UUID. Complements `HotReload`.

## Install

UUID: `streamdeck-tiler@technolibre.ca`

### Option A — Makefile (from repo root)

First install and after every edit to `extension.js`:

```bash
make streamdeck_tiler_install_extension
# Wayland: log out / log in
# X11:     Alt+F2, r, Enter
make streamdeck_tiler_enable_extension
```

Uninstall: `make streamdeck_tiler_uninstall_extension`

> Why re-login?
> GNOME Shell 45+ caches imported ES modules for the lifetime of the
> session. `gnome-extensions disable && enable` calls
> `disable()`/`enable()` on the already-loaded module — it does **not**
> re-read `extension.js`. The old `org.gnome.Shell.Extensions.ReloadExtension`
> D-Bus method is deprecated on GNOME 45+ and returns `NotSupported`. On
> Wayland a full shell restart means a session re-login; X11 can use
> `Alt+F2` → `r`. See **Hot reload** below for a dev-loop workaround.

## Hot reload (dev loop)

After the first install + re-login, subsequent edits to `extension.js`
can be loaded without a new re-login via the extension's `HotReload`
D-Bus method. The method duplicates the extension directory under a
fresh UUID (e.g. `streamdeck-tiler-reload-<ts>@technolibre.ca`) so the
GJS module-cache key changes — the new UUID triggers a genuine ESM
re-import. The technique is adapted from
[ExtensionReloader](https://codeberg.org/som/ExtensionReloader).

```bash
# Edit extension.js
make streamdeck_tiler_reload         # hot-reload, no re-login
# Edit again, reload again (previous temp is auto-purged)
make streamdeck_tiler_reload
# When done, restore the main UUID as the running instance:
make streamdeck_tiler_reload_clean
```

Important limits:

- **First use requires one re-login.** The `HotReload` method itself
  only becomes available after the shell has loaded this version of
  `extension.js`. If `streamdeck_tiler_reload` reports
  `UnknownMethod: HotReload`, log out and back in once, then retry.
- After `streamdeck_tiler_reload_clean`, the main UUID runs the **cached
  (old)** source code until the next re-login — because its ES module
  is still in memory. Edits made during the dev loop are picked up the
  next time the shell starts fresh.
- Each reload leaves a `streamdeck-tiler-reload-*@technolibre.ca`
  directory on disk until cleaned up. `_reload_clean` removes them.
- For a fully isolated dev environment (no temp UUIDs in the main
  session), use a nested shell:
  `dbus-run-session -- gnome-shell --nested --wayland`
  (GNOME 48 and older) or `--devkit --wayland` (GNOME 49+).

### Option B — manual

```bash
# From repo root
EXT_UUID=streamdeck-tiler@technolibre.ca
EXT_DIR=~/.local/share/gnome-shell/extensions/$EXT_UUID
mkdir -p "$EXT_DIR"
cp script/stream_deck/gnome-extension/extension.js "$EXT_DIR/"
cp script/stream_deck/gnome-extension/metadata.json "$EXT_DIR/"
```

## Activate

GNOME Shell must reload to see a new extension. On Wayland, only a full
session re-login reloads the shell.

```bash
# 1. Log out of the GNOME session, then log back in.
# 2. Enable the extension:
gnome-extensions enable streamdeck-tiler@technolibre.ca
```

Verify:

```bash
gnome-extensions info streamdeck-tiler@technolibre.ca | grep -i Activ
# Expect: Activé: Oui  (or: Enabled: Yes)

gdbus introspect --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler
# Expect: node containing method TileWindow
```

## Manual test

Tile the focused window to the left half of a 2×1 grid:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.TileWindow \
  2 1 0 0 0 0
```

List tracker timers:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.ListTrackerTimers
```

Toggle a timer (replace `<id>` with an id from the list):

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.ToggleTrackerTimer \
  '<id>'
```

Create a new timer and open edit mode on it:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.AddTrackerTimer
```

Hot-reload the extension (returns the new temp UUID):

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotReload
```

Tear down the reload state:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotExit
```

## Uninstall

```bash
gnome-extensions disable streamdeck-tiler@technolibre.ca
rm -rf ~/.local/share/gnome-shell/extensions/streamdeck-tiler@technolibre.ca
# Log out / log in to fully unload from the shell.
```

## Troubleshooting

- Error `GDBus.Error:org.freedesktop.DBus.Error.UnknownMethod: ... object does not exist at ...StreamDeckTiler`
  → Extension not enabled or shell not reloaded. Run
  `gnome-extensions enable streamdeck-tiler@technolibre.ca` then log out/in
  (Wayland) or press `Alt+F2` → `r` → Enter (X11 only).
- `gnome-extensions info ...` shows `État: INITIALIZED` and `Activé: Non`
  → Same cause, same fix.
- Shell version mismatch → Edit `metadata.json` `shell-version` to include
  your GNOME version (`gnome-shell --version`).

## Logs

```bash
journalctl --user -f /usr/bin/gnome-shell | grep StreamDeckTiler
```
