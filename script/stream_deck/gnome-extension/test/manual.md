> **Release gate:** every box in this file must be ticked before tagging a release that touches the stream_deck gnome extension.

# Stream Deck GNOME Extension — Manual Smoke Checklist

Run after each `gnome-extensions enable` cycle.

## Foundation (Plan A)

- [ ] Controller indicator shows in top bar with `input-gaming-symbolic` icon
- [ ] Click → menu: About, Start gallery server… ▶, ERPLibre ▶, Games ▶, "Open prefs…"
- [ ] ERPLibre submenu lists "Window Tiler" (when gallery server is running)
- [ ] Games submenu lists every other game and excludes Window Tiler
- [ ] "Start gallery server…" submenu lists every entry from the `paths` GSetting (label + path)
- [ ] Picking a path opens gnome-terminal in that directory running `source .venv.erplibre/bin/activate && make streamdeck_gallery`
- [ ] If `paths` is empty the submenu shows "(no paths configured — add one in pencil prefs)"
- [ ] Submenu top line shows `○ Offline` when the gallery is not running
- [ ] After launching, re-opening the menu (or waiting ~2.5s + reopening) shows `● Running on http://localhost:8042`, the submenu title becomes "Gallery server (running) …", and an "Open in browser" item appears
- [ ] Path entries show "— port busy" + are insensitive while running
- [ ] After Ctrl-C in the gallery terminal, re-opening the menu shows `○ Offline` again and path entries become clickable
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

## ERPLibre (Plan D)

- [ ] ERPLibre indicator with `network-server-symbolic` icon
- [ ] Local section lists all `~/erplibre*` directories with `.git` + `env_var.sh`
- [ ] Local instance "Open URL" → browser opens `http://localhost:<port>`
- [ ] Local instance "Start server" → terminal opens at the dir running `make run`
- [ ] Add remote instance with valid keepass DB + entry → submenu shows Auto-login, Copy username, Copy password, Open in KeePassXC
- [ ] First Copy username triggers master-pw dialog; correct pw → notify "username copied"
- [ ] Wrong pw → notify "KeePassXC unlock failed", cache invalidated, next click re-prompts
- [ ] Auto-login (selenium) → opens browser + Selenium script logs in (visible in browser)
- [ ] Auto-login (selenium) when `.venv.erplibre/bin/python` missing → falls back to xdotool, notifies
- [ ] Auto-login (xdotool) → browser opens, fields fill in
- [ ] Edit remote instance → dialog pre-filled, Save updates, Delete removes
- [ ] `gsettings set erplibre-auto-detect false` → local section becomes empty
- [ ] Re-scan local item rebuilds the local list

## Network (Plan E)

- [ ] Network indicator with `network-wired-symbolic` icon
- [ ] On open, header shows "Subnet: ? · last scan never"
- [ ] Click "🔄 Refresh scan" → scan runs without crashing the shell
- [ ] After scan: header shows detected /24 + timestamp; scanned hosts listed
- [ ] If `~/.ssh/config` has at least one non-wildcard Host stanza, "Configured" section lists it
- [ ] Configured row "SSH terminal" opens a terminal running ssh by alias
- [ ] Scanned row "SSH terminal" opens a terminal running ssh user@ip; user = `network-ssh-user` or `$USER`
- [ ] Copy IP populates clipboard (paste verifies)
- [ ] Open Files sftp:// item launches Nautilus sftp
- [ ] When nmap missing, scan still runs via nc (slower)
- [ ] Setting `network-auto-refresh-sec` to 60 — wait 60s, scan re-runs (Plan G adds the timer; for Plan E, the SpinRow exists but no timer fires yet)

## Device (Plan F)

- [ ] Device indicator with `input-tablet-symbolic` icon
- [ ] No deck plugged in: "(no Stream Deck found)"
- [ ] Plug deck + click "Re-scan USB" → row appears with product + serial
- [ ] Status item → notification with bus/device/vendor/serial
- [ ] Open controller UI → erplibre_controller.py runs (verify `pgrep -af erplibre_controller`)
- [ ] Pidfile `~/.cache/streamdeck-tiler/controller.pid` exists after launch
- [ ] Restart deck → controller exits + relaunches (PID changes; note: SIGTERM may leave pidfile stale until next launch overwrites it)
- [ ] Show details → notification with truncated `lsusb -v` output

## Cross-cutting (Plan G)

### i18n
- [ ] `LANG=fr_FR.UTF-8 gnome-extensions prefs streamdeck-tiler@technolibre.ca` shows French strings (e.g. "Ajouter un chemin…")
- [ ] `make extension_i18n_compile` succeeds; `.mo` files exist under `locale/`

### Theming
- [ ] Theming page: change pencil icon to `applications-utilities-symbolic` → top-bar icon updates after menu toggle
- [ ] Setting an absolute path to an SVG → top-bar shows that SVG

### Drag-reorder
- [ ] Drag rows in "Order in top bar" → top-bar order matches `gsettings get button-order`
- [ ] Disable an indicator + reorder → re-enable → still in correct position

### Auto-refresh
- [ ] `network-auto-refresh-sec=60` → scan re-runs every minute (timestamp advances)
- [ ] Set back to 0 → timer stops (no further scans)
- [ ] Same for `device-auto-refresh-sec`

### D-Bus
- [ ] `gdbus call … ListPaths` returns the paths JSON
- [ ] `gdbus call … OpenPath '/home/x/proj'` opens a terminal at that path
- [ ] `gdbus call … OpenFilm '<id>' 'mpv'` launches mpv
- [ ] `gdbus call … ListDevices` returns the devices JSON

### Backup/restore
- [ ] Export settings → JSON file with all keys + schema_version
- [ ] Modify keys, Import → settings restored
- [ ] Reset → all keys back to defaults

### Sync
- [ ] Set sync path to a local git repo, enable sync → toggling a setting commits the JSON within 5s
- [ ] Pre-populate the JSON in another machine → first enable() pulls + applies

## Icon badges + Claude session state

### Static count badges
- [ ] After `gnome-extensions enable`, every visible indicator that has data shows a small blue circle with a number on the top-right corner of its panel icon
- [ ] Film indicator badge equals `gsettings get … films` array length
- [ ] Pencil indicator first badge equals `paths` array length
- [ ] ERPLibre indicator badge equals (local detected) + (remote `instances` length)
- [ ] Network indicator badge equals (configured `~/.ssh/config` non-wildcard hosts) + (last scan host count)
- [ ] Device indicator badge equals number of Stream Decks reported by `lsusb -d 0fd9:`
- [ ] Controller indicator badge matches the device count
- [ ] Setting `enable-icon-badges=false` hides every badge live; `true` brings them back
- [ ] When a count exceeds 99 the badge text is `99+`

### Claude session badge
- [ ] Install the hook from `hooks/README.md` into `~/.claude/settings.json` and restart Claude
- [ ] Open `claude --resume` in a path that exists in `paths`; pencil icon now shows a second blue badge with `1`
- [ ] Open a second `claude` instance in the same path; second badge becomes `2`
- [ ] Wait for assistant turn end (Stop hook fires) → third yellow badge appears with `1`
- [ ] Trigger a permission prompt (Notification hook) → third badge turns red
- [ ] Type a new message → third badge disappears (back to two badges)
- [ ] Pencil dropdown row for that path shows the same count + colour next to its label
- [ ] Below each path row, one indented sub-row per running session shows a coloured dot (green = working, yellow = awaiting answer, red = needs attention), the first user prompt as description, and a "Working / Awaiting answer / Needs attention" line plus the 8-char session id
- [ ] Pencil panel badges: 1st = paths (blue), 2nd = active sessions (green), 3rd = awaiting (yellow → red); the green badge flips to yellow/red on the per-row badge as sessions await
- [ ] After the user types another message, `last_prompt` updates but `description` (the very first prompt) stays put as the sticky session topic
- [ ] Quit Claude (`/exit` / `Ctrl-D`) → SessionEnd removes the file → badge count decrements
- [ ] `kill -9` on the claude process → next refresh cleans the stale state file (`/proc` check)

## Release

- [ ] `make test_gnome_extension` passes (currently 62 unit tests)
- [ ] `make test_full_fast` includes the extension target and passes
- [ ] All sections above ticked
- [ ] CHANGELOG.base.md entry present and regenerated
- [ ] README.base.md regenerated for both `script/stream_deck/` and `script/stream_deck/gnome-extension/`
