# Stream Deck GNOME Extension — Multi-Indicator Redesign

- **Status**: Draft
- **Date**: 2026-04-26
- **Author**: Mathieu Benoit (brainstormed with Claude)
- **Target**: `script/stream_deck/gnome-extension/`
- **Scope**: Major refactor — registry-based panel button architecture with 6 indicators

## 1. Goals

Today the extension exposes a single panel button (controller icon, `input-gaming-symbolic`) that combines tiling D-Bus methods, a games gallery menu and an `erplibre_path` setting. This spec replaces it with a registry-based architecture supporting six independent panel buttons:

1. **Controller** — existing manette behaviour (games + about), unchanged semantics
2. **Pencil** — list of project paths, each launches `gnome-terminal` running `claude` (resume / fresh / custom command)
3. **Film** — list of films, each opens via browser or `mpv` with a saved start position
4. **ERPLibre** — list of local + remote ERPLibre instances, with selenium / keepass-driven actions
5. **Network** — async SSH host discovery (`nmap` / `nc` fallback) + `~/.ssh/config` integration
6. **Device** — read-only list of Stream Deck USB devices (vendor `0fd9`)

The D-Bus interface `org.gnome.Shell.Extensions.StreamDeckTiler` (used by Python tilers and `erplibre_controller.py`) is preserved and extended with new methods.

## 2. Non-Goals

- Drag-reorder of indicators is in scope, but per-row drag of legacy menu items (games list) is not.
- Streamdeck **device control** (set buttons, brightness, images) stays in `erplibre_controller.py`. The Device indicator is read-only + launch.
- Auto-discovery of films from a local library is out of scope; films are user-curated.

## 3. Architecture

### 3.1 Approach: Indicator Registry

A central `IndicatorRegistry` exposes `register({id, ctor, defaultEnabled, displayName})`. `extension.js` enable() iterates the registry, instantiates each indicator whose `enable-<id>` GSettings key is true, then watches `changed::enable-<id>` and `changed::button-order` to add/remove/reorder live without full extension reload.

This shape makes future buttons (e.g. a 7th "Snippets" button) a single new file in `indicators/` plus one entry in the registry — no changes to `extension.js`.

### 3.2 File layout

```
script/stream_deck/gnome-extension/
├── extension.js              # entry: registry wiring + D-Bus
├── prefs.js                  # Adwaita prefs window
├── metadata.json             # gettext-domain, settings-schema added
├── schemas/
│   └── org.gnome.shell.extensions.streamdeck-tiler.gschema.xml
├── locale/
│   ├── en/LC_MESSAGES/streamdeck-tiler.mo
│   └── fr/LC_MESSAGES/streamdeck-tiler.mo
├── po/
│   ├── streamdeck-tiler.pot
│   ├── en.po
│   └── fr.po
├── lib/
│   ├── settings.js           # GSettings wrapper, JSON list helpers, schema migration
│   ├── registry.js           # IndicatorRegistry
│   ├── spawn.js              # gnome-terminal/browser/mpv/nmap subprocess helpers + notify
│   ├── keepass.js            # keepassxc-cli wrapper, master-pw cache (5 min TTL)
│   ├── network.js            # nmap -oG + nc fallback parsers, async scan
│   ├── usb.js                # lsusb -d 0fd9: parser
│   ├── ssh-config.js         # ~/.ssh/config parser (Host stanzas)
│   ├── i18n.js               # gettext _() wrapper
│   └── git-sync.js           # git pull/commit/push wrappers
├── indicators/
│   ├── controller.js
│   ├── pencil.js
│   ├── film.js
│   ├── erplibre.js
│   ├── network.js
│   └── device.js
├── ui/
│   ├── path-dialog.js
│   ├── film-dialog.js
│   ├── instance-dialog.js
│   └── master-pw-dialog.js   # modal for keepassxc-cli unlock
├── README.base.md            # mmg source, regenerates README.md + README.fr.md
└── test/
    ├── unit/
    │   ├── spawn.test.js
    │   ├── keepass.test.js
    │   ├── network.test.js
    │   ├── usb.test.js
    │   ├── ssh-config.test.js
    │   └── position-parser.test.js
    └── fixtures/
        ├── nmap-oG.txt
        ├── lsusb-elgato.txt
        ├── ssh-config.txt
        ├── env_var.sh.sample
        └── keepassxc-cli-show.txt
```

### 3.3 Top bar order

Default left → right: `device | network | erplibre | film | pencil | controller`.

Reorder: drag rows in prefs page "Buttons". Stored as `button-order` (`as`). Apply at enable() and on signal `changed::button-order`.

### 3.4 D-Bus interface

The existing iface stays at `/org/gnome/Shell/Extensions/StreamDeckTiler`. New methods are appended:

```xml
<method name="OpenPath">              <arg type="s" direction="in" name="path"/>      <arg type="b" direction="out" name="ok"/></method>
<method name="OpenFilm">               <arg type="s" direction="in" name="film_id"/>   <arg type="s" direction="in" name="player"/>  <arg type="b" direction="out" name="ok"/></method>
<method name="OpenInstance">           <arg type="s" direction="in" name="id"/>        <arg type="s" direction="in" name="action"/>  <arg type="b" direction="out" name="ok"/></method>
<method name="ScanNetwork">            <arg type="s" direction="out" name="json"/></method>
<method name="ListDevices">            <arg type="s" direction="out" name="json"/></method>
<method name="ListPaths">              <arg type="s" direction="out" name="json"/></method>
<method name="ListFilms">              <arg type="s" direction="out" name="json"/></method>
<method name="ListInstances">          <arg type="s" direction="out" name="json"/></method>
```

`OpenInstance` action enum: `url`, `login`, `copy_user`, `copy_pass`, `open_keepass`, `start_server`.

`OpenFilm` player enum: `browser`, `mpv`.

These let `erplibre_controller.py` bind streamdeck physical buttons to indicator actions.

## 4. Data model (GSettings)

Schema id: `org.gnome.shell.extensions.streamdeck-tiler`.

```xml
<!-- Per-indicator toggles (default true) -->
<key name="enable-controller" type="b"><default>true</default></key>
<key name="enable-pencil"     type="b"><default>true</default></key>
<key name="enable-film"       type="b"><default>true</default></key>
<key name="enable-erplibre"   type="b"><default>true</default></key>
<key name="enable-network"    type="b"><default>true</default></key>
<key name="enable-device"     type="b"><default>true</default></key>

<!-- Top-bar ordering -->
<key name="button-order" type="as">
  <default>['device','network','erplibre','film','pencil','controller']</default>
</key>

<!-- Catalogues (JSON serialised in 's' to keep dconf editing manageable) -->
<key name="paths"        type="s"><default>"[]"</default></key>
<key name="films"        type="s"><default>"[]"</default></key>
<key name="instances"    type="s"><default>"[]"</default></key>
<key name="recent-paths" type="s"><default>"[]"</default></key>

<!-- Pencil -->
<key name="terminal-claude-cmd" type="s"><default>"claude --resume"</default></key>

<!-- ERPLibre -->
<key name="erplibre-auto-detect"     type="b"><default>true</default></key>
<key name="erplibre-local-pattern"   type="s"><default>"~/erplibre*"</default></key>

<!-- Network -->
<key name="network-cidrs"             type="as"><default>[]</default></key>
<key name="network-ssh-user"          type="s"><default>""</default></key>
<key name="network-use-nmap"          type="b"><default>true</default></key>
<key name="network-read-ssh-config"   type="b"><default>true</default></key>
<key name="network-auto-refresh-sec"  type="i"><default>0</default></key>

<!-- Device -->
<key name="device-auto-refresh-sec"   type="i"><default>0</default></key>

<!-- Theming -->
<key name="icon-overrides" type="s"><default>"{}"</default></key>

<!-- Sync -->
<key name="enable-git-sync"  type="b"><default>false</default></key>
<key name="git-sync-path"    type="s"><default>""</default></key>

<!-- Migration / schema versioning -->
<key name="schema-version" type="i"><default>1</default></key>
<key name="migration-done" type="b"><default>false</default></key>
```

### 4.1 JSON shapes

```js
// paths[]
{
  id: "uuid-v4",
  label: "ERPLibre Dev",
  path: "/home/leo/erplibre",
  default_cmd: "claude --resume"
}

// films[]
{
  id: "uuid-v4",
  name: "Foundation",
  url: "https://...",
  episode: "S2E5",          // free string
  position: "01:23:45"      // hh:mm:ss OR raw seconds; parser accepts both
}

// instances[]
{
  id: "uuid-v4",
  name: "ERPLibre prod",
  url: "https://erp.example.com",
  type: "remote",                    // "local" | "remote"
  local_path: "",                    // populated when type=local
  port: 8069,
  keepass_db: "/path/to/db.kdbx",
  keepass_keyfile: "",               // optional
  keepass_yubikey_slot: 0,           // 0 = disabled, 1 or 2
  keepass_yubikey_serial: "",        // optional
  keepass_entry: "Odoo prod",        // entry title
  auto_login_method: "selenium"      // "selenium" | "xdotool" | "none"
}

// icon-overrides
{ "controller": "input-gaming-symbolic", "pencil": "/home/leo/icons/claude.svg" }
```

### 4.2 Migration

On first enable() with `migration-done = false`:

1. Read `~/.config/streamdeck-tiler/extension-settings.json` if present.
2. If `erplibre_path` set and `paths` empty, seed `paths` with one entry `{label: "ERPLibre", path: <erplibre_path>}`.
3. Rename JSON file to `extension-settings.json.bak`.
4. Set `migration-done = true`, `schema-version = 1`.

Future schema bumps run incremental migrations from `schema-version` to current.

### 4.3 Master password cache

Implemented in `lib/keepass.js`. In-memory only, never written to disk. Keyed by `(keepass_db, keepass_keyfile, keepass_yubikey_serial)` tuple. TTL 5 min from last successful unlock; reset on prefs change of any of those fields.

## 5. Indicators

### 5.1 Controller (`input-gaming-symbolic`)

Behaviour preserved from the existing extension. Code is extracted into `indicators/controller.js`. Sub-menu items:

- **About Us** — opens project URL.
- **Games** — async fetch from `http://localhost:8042/api/games`, click → `/launch/<id>`.
- **Settings** — single item "Open prefs…" that launches `prefs.js` (replaces the JSON-edit-via-default-app flow). The legacy "Change ERPLibre path" / "Deploy ERPLibre" actions move to the prefs window.

### 5.2 Pencil (`document-edit-symbolic`)

Sub-menu rows for each `paths[]` entry:

```
[Resume] [Fresh] [Custom…] [✎]
  Label
  ~/erplibre
```

Inline buttons built with `St.BoxLayout` inside a `PopupMenu.PopupBaseMenuItem`.

| Button   | Action                                                                                    |
|----------|-------------------------------------------------------------------------------------------|
| Resume   | `gnome-terminal --working-directory=PATH -- bash -lc "claude --resume; exec bash"`        |
| Fresh    | `gnome-terminal --working-directory=PATH -- bash -lc "claude; exec bash"`                 |
| Custom…  | Modal text dialog (`master-pw-dialog.js` style) → run user-supplied command in terminal   |
| ✎        | Open path-dialog (edit + delete)                                                           |

Below entries: separator + `+ Add path…` + `⚙ Open prefs`.

`+ Add path…` opens `path-dialog.js` with: label field, path field + `📁` file chooser button, list of `recent-paths` as clickable suggestions.

Every launch pushes the path to `recent-paths` (FIFO, cap 10).

`gnome-terminal` absent → fall back to `xterm`. Both absent → notify.

### 5.3 Film (`video-x-generic-symbolic`)

Each row: `Name · episode · position` → click expands sub-menu:

| Item            | Action                                                  |
|-----------------|---------------------------------------------------------|
| ▶ Browser       | `xdg-open URL`                                          |
| ▶ mpv           | `mpv --start=<position> URL` (yt-dlp dependency)        |
| ✎ Edit          | film-dialog                                             |

Position parser accepts `H:M:S`, `M:S`, raw seconds. Internally normalised to mpv-friendly `HH:MM:SS`. Fallback to `0` on parse failure with a logged warning (no error popup).

`+ Add film…` at bottom opens film-dialog: name (required), URL (required), episode (free string), position (validated regex `^\d+(:\d+){0,2}$`).

DRM sites (Netflix etc.) → only Browser works. README documents the limitation.

### 5.4 ERPLibre (`network-server-symbolic`)

Two sections:

**Local instances** (auto-detected via glob on `erplibre-local-pattern`, parses each `env_var.sh` for `ERPLIBRE_PORT_HTTP` etc.):

For each detected dir, sub-menu:

| Item                    | Action                                                                                           |
|-------------------------|--------------------------------------------------------------------------------------------------|
| Open URL                | `xdg-open http://localhost:<port>` (default 8069 if parse fails)                                |
| Start server            | `gnome-terminal --working-directory=DIR -- bash -lc "make run; exec bash"`                       |
| Auto-login              | spawns `python script/selenium/web_login.py --url URL --user U --pass P` (U/P from keepass)      |
| Copy username           | keepass + clipboard (St.Clipboard)                                                               |
| Copy password           | keepass + clipboard                                                                              |
| Open in KeepassXC       | `keepassxc DB --keyfile K`                                                                       |
| Edit instance           | instance-dialog (configure keepass + login method)                                               |

**Remote instances** (manual, from `instances[]` where `type=remote`): identical sub-menu minus `Start server`.

Bottom: separator + `+ Add remote instance…` + `🔄 Re-scan local`.

KeepassXC unlock flow (`lib/keepass.js`):

1. Resolve `(db, keyfile, yubikey)` tuple.
2. If cached and fresh → use cached master pw via `keepassxc-cli show DB ENTRY -a username` with pw on stdin.
3. If not cached → open `master-pw-dialog.js` (modal `St.PasswordEntry` in a `ModalDialog`). User enters master pw → spawn `keepassxc-cli` with pw on stdin + `--key-file K --yubikey SLOT:SERIAL` if configured.
4. Wrong pw (`keepassxc-cli` exit 1) → notify + clear cache + re-prompt once.
5. Cache populated on success with TTL 5 min.

Auto-login methods:

- **selenium** (default) — invokes existing `script/selenium/web_login.py`. Requires Python venv `.venv.erplibre`.
- **xdotool** (experimental, marked in dialog) — `xdg-open URL` → `sleep 2` → `xdotool type USER` → `key Tab` → `type PASS` → `key Return`. Fragile; doc warning.
- **none** — Auto-login item hidden from sub-menu.

### 5.5 Network (`network-wired-symbolic`)

Two sections:

**Configured hosts** (parsed from `~/.ssh/config` if `network-read-ssh-config = true`):

Each `Host` stanza (skipping wildcards) → row with sub-menu:

| Item                  | Action                                                              |
|-----------------------|---------------------------------------------------------------------|
| SSH terminal          | `gnome-terminal -- ssh <Host alias>` (auto identity from config)    |
| Copy hostname         | resolves `HostName` from config                                     |
| Open Files (sftp://)  | `xdg-open sftp://<alias>`                                           |
| Show details          | modal listing all key=value from the Host stanza                    |

**Scanned hosts** (async scan on menu open + manual refresh):

Engine selection at scan time:

1. If `network-use-nmap = true` and `which nmap` succeeds → `nmap -p22 --open -oG - <CIDR>`.
2. Fallback: bash loop `for ip in CIDR; do nc -z -w1 $ip 22 && echo $ip; done`.

Subnet auto-detection: parse `ip -4 -j route` JSON, take default gateway interface, derive `/24` (configurable in prefs to override).

Per discovered host, sub-menu:

| Item                  | Action                                                              |
|-----------------------|---------------------------------------------------------------------|
| SSH terminal          | `gnome-terminal -- ssh <user>@<ip>` (`user` from `network-ssh-user` or `$USER`) |
| Copy IP               | clipboard                                                           |
| Open Files (sftp://)  | `xdg-open sftp://<user>@<ip>`                                       |
| Show details          | modal: hostname (reverse DNS via `getent hosts`), latency, ports     |

Header: `Subnet: 192.168.1.0/24 · last scan 2 min ago` + animated 🔄 button (spinner during scan).

Auto-refresh: if `network-auto-refresh-sec > 0` → `GLib.timeout_add_seconds` triggers re-scan.

Concurrency: only one scan in flight; second click is debounced. Cancellation via `Gio.Cancellable` on disable().

### 5.6 Device (`input-tablet-symbolic`)

Source: `lsusb -d 0fd9: -v` parsed for product / serial / bus / device-num.

Per device, sub-menu:

| Item                  | Action                                                                |
|-----------------------|-----------------------------------------------------------------------|
| Status                | modal: bus, device num, serial, product string                        |
| Open controller UI    | `python script/stream_deck/erplibre_controller.py` (bg, pidfile-aware) |
| Restart deck          | kill controller pid (from pidfile) + relaunch                         |
| Show details          | modal: full `lsusb -v` for the device                                 |

Empty list → non-clickable item `(no Stream Deck found)`.

Bottom: `🔄 Re-scan USB`. Auto-refresh via `device-auto-refresh-sec` if >0.

`erplibre_controller.py` is expected to write its PID to `~/.cache/streamdeck-tiler/controller.pid` on launch and remove it on exit. The Restart action reads this pidfile.

## 6. Prefs window (`prefs.js`)

`Adw.PreferencesWindow` with one page per concern. All widgets bound to GSettings keys via `Gio.Settings.bind()` where possible; JSON-list keys use custom widgets.

### 6.1 Page "Buttons"

- 6 `Adw.SwitchRow` (one per indicator) — toggle live.
- Drag-orderable rows below: `Adw.PreferencesGroup` titled "Order in top bar" with 6 rows. Drag updates `button-order`.

### 6.2 Page "Pencil"

- `Adw.EntryRow` "Default claude command" → `terminal-claude-cmd`.
- `Adw.PreferencesGroup` "Paths": list rows `[label, path, ✎, 🗑]` with drag handle. `+ Add` opens path-dialog.

### 6.3 Page "Film"

- `Adw.PreferencesGroup` "Films": list rows `[name, episode, position, ✎, 🗑]` with drag handle. `+ Add` opens film-dialog with regex-validated position field.

### 6.4 Page "ERPLibre"

- `Adw.SwitchRow` "Auto-detect local instances" → `erplibre-auto-detect`.
- `Adw.EntryRow` "Local search pattern" → `erplibre-local-pattern`.
- `Adw.PreferencesGroup` "Remote instances": list rows + drag, edit via instance-dialog.

### 6.5 Page "Network"

- `Adw.EntryRow` "SSH user" (placeholder `$USER`).
- `Adw.SwitchRow` "Read ~/.ssh/config".
- `Adw.SwitchRow` "Use nmap if available".
- `Adw.SpinRow` "Auto-refresh (seconds, 0 = off)" → `network-auto-refresh-sec`.
- `Adw.PreferencesGroup` "CIDR ranges" — empty list = auto-detect; user adds custom strings.

### 6.6 Page "Device"

- `Adw.SpinRow` "Auto-refresh (seconds, 0 = off)" → `device-auto-refresh-sec`.
- Read-only list of currently detected decks (refresh button).

### 6.7 Page "Theming"

- For each indicator: `Adw.ComboRow` of common symbolic icons + `Browse SVG…` button writing to `icon-overrides`.

### 6.8 Page "Sync"

- `Adw.SwitchRow` "Enable git sync" → `enable-git-sync`.
- `Adw.EntryRow` "Sync repo path" → `git-sync-path`.
- `Adw.ActionRow` "Sync now" button — manual trigger.
- Warning label: "Last write wins on conflict."

### 6.9 Page "Advanced"

- `Adw.ActionRow` "Export settings…" → file chooser → JSON dump.
- `Adw.ActionRow` "Import settings…" → file chooser → validate schema-version → apply via `set_value`.
- `Adw.ActionRow` "Reset to defaults" (confirms via dialog).

### 6.10 Page "About"

- Version (read from `metadata.json`), repo link, doc link, license.

## 7. Cross-cutting concerns

### 7.1 Sub-process plumbing (`lib/spawn.js`)

Single helper `spawn(argv, {captureStdout=false, captureStderr=true, onError=notifyOnError})`.

- All sub-process failures route through `_notify(title, body)` + `console.log("[StreamDeckTiler] ...")` with consistent prefix.
- Missing binaries (`gnome-terminal`, `mpv`, `nmap`, `nc`, `keepassxc-cli`, `keepassxc`, `lsusb`, `xdotool`, `git`) detected via `GLib.find_program_in_path`. Missing → notify "Install package X" once + disable feature in current session.
- `gnome-terminal` fallback: try `xterm`, then `kgx` (GNOME Console).

### 7.2 i18n

- gettext-domain: `streamdeck-tiler` (declared in metadata.json).
- `lib/i18n.js` exports `_()` wrapper.
- All UI + notify strings wrapped. Log strings stay English.
- `po/streamdeck-tiler.pot` generated by `xgettext`.
- Initial translations: `po/en.po`, `po/fr.po`. Compiled to `locale/<lang>/LC_MESSAGES/streamdeck-tiler.mo` at build time.
- Makefile target `extension_i18n_compile` runs `msgfmt` for each `.po`.

### 7.3 Hot-reload safety

The existing UUID-rename hot-reload pattern is preserved. Each indicator must implement `destroy()` that:

- Cancels in-flight `Gio.Cancellable`s (network scan, keepass spawn).
- Removes `GLib.timeout_*` ids.
- Disconnects `Gio.Settings` signal handlers.
- Calls `super.destroy()` to free St actors.

`extension.disable()` calls `destroy()` on every active indicator and clears the registry.

### 7.4 Permissions

Network scan uses `nmap -p22 --open` (no `-sS`) so does not require root. SSH itself uses user keys via OpenSSH config — no extension-level secret storage.

### 7.5 Sync (`lib/git-sync.js`)

When `enable-git-sync = true` and `git-sync-path` is a git repo:

- On extension `enable()`: `git -C path pull --rebase` (best-effort, swallow errors with notify).
- After settings changed (debounce 5s, single timer): write all GSettings to `<path>/streamdeck-tiler.json` (same shape as Export), `git add + commit -m "auto sync $(hostname) $(date)" + push` if a remote is configured.
- Conflicts: last-write-wins via `--strategy-option theirs` on rebase; if rebase still fails, abort + notify "Manual merge required". Documented limitation.

### 7.6 Backup / restore (`lib/settings.js`)

- Export: serialise every key in the schema → `{schema_version, settings: {key: value}}` JSON.
- Import: validate `schema_version`, run migrations if older, apply each key via `Gio.Settings.set_value` matching its `Variant` type.
- Reset: enumerate schema keys, call `reset(key)`.

## 8. Errors & edge cases

| Subsystem    | Failure mode                          | Handling                                                       |
|--------------|---------------------------------------|----------------------------------------------------------------|
| spawn        | binary missing                        | notify once per session, disable feature, suggest install      |
| spawn        | gnome-terminal missing                | xterm fallback, then kgx                                       |
| keepass      | wrong master pw                       | notify, clear cache, re-prompt once                            |
| keepass      | DB / entry missing                    | notify, hide keepass-dependent items in sub-menu               |
| network      | no network / no default route         | dropdown shows "(no network detected)"                         |
| network      | scan timeout (>30 s)                  | kill subprocess, notify, leave previous results                |
| network      | invalid CIDR                          | skip + notify                                                  |
| network      | concurrent scan                       | debounce; ignore second click                                  |
| films        | URL malformed                         | spawn anyway, error visible in player                          |
| films        | position parse fails                  | normalise to `0`, log warning                                  |
| ERPLibre     | env_var.sh parse fails                | show entry without port, fall back to `:8069`                  |
| ERPLibre     | `make run` fails                      | error visible in launched terminal (no capture)                |
| device       | lsusb missing                         | notify "install usbutils"                                      |
| device       | no decks                              | non-clickable "(no Stream Deck found)"                         |
| device       | multiple identical decks              | differentiate by serial in label                               |
| migration    | corrupted JSON                        | log + skip, settings remain default                            |
| sync         | rebase conflict                       | abort + notify "Manual merge required"                         |
| hot-reload   | indicator left subprocess running     | indicator's destroy() must cancel; otherwise leak logged       |

## 9. Testing

### 9.1 Unit tests (Node `node --test`)

Pure-logic modules only — `lib/` files that don't import GJS. Run via `node --test test/unit/*.test.js`.

Coverage targets:

- `lib/spawn.js`: `buildClaudeCmd(path, cmd)`, `buildMpvCmd(url, position)`, `parsePosition()`.
- `lib/keepass.js`: `parseShowOutput(stdout, attribute)`.
- `lib/network.js`: `parseNmapOG(stdout)`, `expandCidr("192.168.1.0/24")`, `parseIpRouteJson(json)`.
- `lib/usb.js`: `parseLsusbVerbose(stdout)`.
- `lib/ssh-config.js`: `parseSshConfig(text)` (Host stanzas, Include directive ignored).
- `lib/i18n.js`: smoke test — `_()` returns input when no .mo loaded.

Fixtures under `test/fixtures/` capture real-world outputs of `nmap -oG`, `lsusb -d 0fd9: -v`, `keepassxc-cli show`, `~/.ssh/config`, `env_var.sh`.

### 9.2 Schema validation

`glib-compile-schemas --strict --dry-run schemas/` runs as part of CI build. Failure = build break.

### 9.3 Manual integration checklist

`script/stream_deck/gnome-extension/test/manual.md` documents per-indicator manual smoke tests:

- Toggle each `enable-<id>` via `gsettings set` → button appears/disappears live.
- Pencil: add path, click Resume → terminal opens with `claude --resume`.
- Film: add film, mpv → mpv launches at start position.
- ERPLibre: auto-detect lists locals, remote opens URL, keepass auto-login completes.
- Network: scan returns hosts, SSH opens terminal.
- Device: 1 deck plugged in → appears, unplug + refresh → disappears.
- Migration: with old `extension-settings.json`, first launch migrates, JSON renamed `.bak`.
- Hot-reload (`HotReload` D-Bus): no shell crash, indicators rebuild cleanly.

### 9.4 CI integration

Makefile target:

```make
test_gnome_extension:
	node --test script/stream_deck/gnome-extension/test/unit/*.test.js
	glib-compile-schemas --strict --dry-run \
	    script/stream_deck/gnome-extension/schemas/
```

## 10. Documentation

All multilingual sources live under `script/stream_deck/gnome-extension/README.base.md` and `script/stream_deck/README.base.md`. Regenerated via `make doc_markdown`.

Sections to add to `gnome-extension/README.base.md`:

- Per-indicator behaviour
- Prefs window walkthrough
- Full GSettings key reference
- D-Bus method reference (with `gdbus call` examples for the new methods)
- KeepassXC setup (how to create the entries, keyfile + YubiKey support, master pw cache TTL)
- Selenium vs xdotool auto-login trade-offs
- Limitations: DRM sites for film, no merge in git-sync

`doc/CHANGELOG.base.md` adds an entry under 1.6.x: *"stream_deck: multi-indicator GNOME extension (registry, pencil, film, ERPLibre, network, device)"*.

## 11. Implementation phasing

The mega-spec is intended for parallel implementation across multiple agents/PRs. Suggested partition (each independently mergeable behind a registry toggle):

1. **Foundation** — registry, settings module, gschema, prefs skeleton, JSON migration, controller extracted to `indicators/controller.js`. No behaviour change visible to users.
2. **Pencil + Film** — both rely only on `lib/spawn.js`, simplest indicators. Implement together.
3. **ERPLibre + KeepassXC + Selenium fallback** — heaviest single chunk; depends on `lib/keepass.js`.
4. **Network + ssh-config** — independent of (3).
5. **Device** — independent.
6. **Theming + Drag-reorder + Auto-refresh + DBus method extensions** — cross-cutting polish.
7. **i18n + Backup/restore + Git-sync** — cross-cutting infra.
8. **Documentation + tests** — the mmg regeneration, the README rewrites, the Makefile target.

Each phase has its own implementation plan (output of `writing-plans`).

## 12. Open questions

- Hot-reload of the gschema (after schema changes) requires re-running `glib-compile-schemas` and an extension reload. The README must call this out for developers.
- Selenium fallback assumes `.venv.erplibre` exists; if not, the Auto-login button should be disabled. To confirm on implementation.
- `erplibre_controller.py` does not currently write a pidfile. Restart-deck depends on this; the controller script must be patched, or Restart-deck silently degrades to "kill any process matching `erplibre_controller.py`" (less safe). Design choice deferred to plan.

## 13. References

- Existing extension: `script/stream_deck/gnome-extension/extension.js`
- Existing selenium login: `script/selenium/web_login.py`
- Streamdeck controller: `script/stream_deck/erplibre_controller.py`
- Migration source: `~/.config/streamdeck-tiler/extension-settings.json`
- GNOME Shell extension docs: <https://gjs.guide/extensions/>
- Adwaita preferences: <https://gnome.pages.gitlab.gnome.org/libadwaita/doc/>
- KeepassXC CLI: `man keepassxc-cli`
