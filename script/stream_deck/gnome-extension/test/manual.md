# Stream Deck GNOME Extension — Manual Smoke Checklist

Run after each `gnome-extensions enable` cycle.

## Foundation (Plan A)

- [ ] Controller indicator shows in top bar with `input-gaming-symbolic` icon
- [ ] Click → menu: About, Games (loads or "offline"), "Open prefs…"
- [ ] About item launches repo URL in browser
- [ ] Open prefs item opens the preferences window
- [ ] In prefs, "Buttons" page lists 6 indicators with toggles
- [ ] Toggling `enable-controller` off removes the icon; toggling on re-adds it
- [ ] D-Bus: `gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Extensions/StreamDeckTiler --method org.gnome.Shell.Extensions.StreamDeckTiler.GetMonitorGeometry` → 4 ints
- [ ] HotReload via D-Bus does not crash the shell
- [ ] If `~/.config/streamdeck-tiler/extension-settings.json` exists with `erplibre_path`, after first enable: `gsettings get org.gnome.shell.extensions.streamdeck-tiler paths` returns a JSON array containing that path; the legacy file is renamed to `.bak`

## Pencil (Plan B)

- [ ] Pencil indicator in panel with `document-edit-symbolic` icon
- [ ] Empty state shows "(no paths configured — use Add path…)"
- [ ] "+ Add path…" opens a dialog with label, path, file picker, recent suggestions
- [ ] Dialog confirm adds the entry; the menu rebuilds live
- [ ] Per-entry `Resume` opens gnome-terminal in path running `claude --resume`
- [ ] Per-entry `Fresh` runs `claude` (no flag)
- [ ] Per-entry `Custom…` runs the value of `terminal-claude-cmd` GSettings key
- [ ] `✎` opens the dialog pre-filled with the entry; saving updates the entry
- [ ] After a launch, `gsettings get … recent-paths` includes that path (capped at 10)
- [ ] Toggle `enable-pencil` off → button disappears; on → button reappears

## Film (Plan C)

- [ ] Film indicator in panel with `video-x-generic-symbolic` icon
- [ ] Empty state: "(no films — use + Add film)"
- [ ] Add film with name + URL only → entry shows just name
- [ ] Add film with name + URL + episode + position → label "Name · S2E5 · 01:23:45"
- [ ] Position invalid format (e.g. `xx`) → dialog shows "Invalid position format"
- [ ] Click row → sub-menu Browser / mpv / Edit
- [ ] Browser → xdg-open URL
- [ ] mpv → spawns mpv with `--start=<position>` (verify in `pgrep -af mpv`)
- [ ] Edit dialog has Delete button; deleting removes entry

## Future (Plans D–H)

(Sections added by subsequent plans.)
