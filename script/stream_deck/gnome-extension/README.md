# Stream Deck Tiler — GNOME Shell Extension

Companion D-Bus extension used by `game_tiler.py` to tile the focused window
via `Meta.Window.move_resize_frame()`. No keyboard simulation, no gTile
dependency. Works on Wayland and X11, GNOME Shell 45–48.

## D-Bus interface

- Name: `org.gnome.Shell.Extensions.StreamDeckTiler`
- Path: `/org/gnome/Shell/Extensions/StreamDeckTiler`
- Methods:
  - `TileWindow(gridCols, gridRows, col1, row1, col2, row2) -> success`
  - `GetMonitorGeometry() -> (x, y, width, height)`
  - `GetGridSize(gridCols, gridRows) -> (cellW, cellH)`

## Install

UUID: `streamdeck-tiler@technolibre.ca`

### Option A — Makefile (from repo root)

```bash
make streamdeck_tiler_install_extension
# log out / log in
make streamdeck_tiler_enable_extension
```

Uninstall: `make streamdeck_tiler_uninstall_extension`

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
