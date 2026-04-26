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

## Future (Plans B–H)

(Sections added by subsequent plans.)
