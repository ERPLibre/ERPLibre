# Screenshots

Visual references for the ERPLibre Stream Deck project. Add `.png`
files to this folder and link them from the parent READMEs. The
`capture.sh` helper grabs the most common views in one shot.

## Expected files

| File | Subject |
| --- | --- |
| `top-bar.png` | All six indicator icons mounted on the GNOME top bar with active count badges. |
| `pencil-dropdown.png` | Pencil indicator dropdown showing per-path Claude session rows + Legend. |
| `pencil-filtered.png` | Same dropdown after clicking the awaiting badge — only the matching sessions visible plus the × Clear-filter row. |
| `media-dropdown.png` | Media indicator dropdown split into Video / Audio sections with mpv / VLC / Browser / Spotify launchers. |
| `prefs-buttons.png` | Prefs window, Buttons page (toggles + drag-and-drop order). |
| `prefs-help.png` | Prefs window, Help page (badge colours + Claude hooks tables). |
| `prefs-about.png` | Prefs window, About page (ERPLibre + TechnoLibre + plugin links). |
| `deck-idle.png` | Stream Deck physical device on its idle layout (tile, sound, layout, A11Y, BT, mic, claude/mpv badges). |
| `deck-tile-grid.png` | Stream Deck on the corner-pick grid after pressing TILE. |
| `deck-claude-session.png` | Stream Deck on the per-Claude-session action page (BACK / FOCUS / ACCEPT / SET WIN / KILL). |

## Capturing

Run `./capture.sh` from this folder while the extension is loaded
and the Stream Deck is plugged in. The script:

1. Captures the GNOME top bar with `grim` (Wayland) or
   `gnome-screenshot` (X11).
2. Opens each indicator dropdown via D-Bus `OpenMenu` and snapshots
   it.
3. Opens the prefs window and snapshots each page.
4. Reads the Stream Deck framebuffer via the `streamdeck` Python
   library (`script/stream_deck/streamdeck_screenshot.py`) for the
   physical-device shots.

The deck snapshots run independently — no display capture required.

## Conventions

- Resolution: capture at the native panel scale, then export at
  `1920×1080` letterboxed when adding to the README.
- File format: PNG, no metadata stripping (gnome-screenshot already
  produces clean output).
- Naming: lowercase, dash-separated, prefix `deck-` for hardware
  shots and `prefs-` for the prefs window.
- Crop tightly to the relevant widget; full-desktop screenshots
  hide the detail.
