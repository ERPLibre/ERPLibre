
# Stream Deck Tiler — GNOME Shell Extension

Six-indicator panel for the GNOME top bar plus a D-Bus interface used by the
Stream Deck Python helpers.

## Indicators

| Id          | Default icon                  | What it does                                                                 |
|-------------|-------------------------------|------------------------------------------------------------------------------|
| controller  | `input-gaming-symbolic`       | Tiling D-Bus + Games sub-menu + link to prefs                                |
| pencil      | `document-edit-symbolic`      | Open `gnome-terminal` running `claude` in a chosen path (Resume / Fresh / Custom) |
| media       | `video-x-generic-symbolic`    | Curated video / audio list opened via browser, `mpv --start=<position>`, VLC or Spotify |
| erplibre    | `network-server-symbolic`     | Local + remote ERPLibre instances; KeepassXC-driven Selenium / xdotool login |
| network     | `network-wired-symbolic`      | SSH host discovery (`nmap -p22` or `nc` fallback) + `~/.ssh/config` hosts    |
| device      | `input-tablet-symbolic`       | List of Elgato Stream Deck USB devices, launch / restart controller daemon  |

Each indicator can be toggled in the preferences window.


## Screenshots

`../screenshots/` holds the canonical screenshots referenced from
this README. Run `../screenshots/capture.sh` while the extension is
loaded (and a Stream Deck is plugged in for the deck shots) to
regenerate them. The folder's own `README.md` lists every expected
file and the conventions for cropping / naming.


## Preferences

`gnome-extensions prefs streamdeck-tiler@technolibre.ca`

Pages: Buttons, Pencil, Media, ERPLibre, Network, Device, Theming, Sync, Advanced, About.

## GSettings keys

Schema id `org.gnome.shell.extensions.streamdeck-tiler`. Selected keys:

- `enable-controller`, `enable-pencil`, `enable-media`, `enable-erplibre`, `enable-network`, `enable-device` (booleans)
- `button-order` (`as`) — left-to-right ordering
- `panel-box` (`s`, default `left`) — `left` (right edge of the left section, just before the centre clock), `center` or `right`
- `paths`, `media`, `instances` (`s`, JSON arrays)
- `terminal-claude-cmd` (`s`, default `claude --resume`)
- `network-cidrs` (`as`), `network-ssh-user` (`s`), `network-use-nmap` (`b`), `network-read-ssh-config` (`b`), `network-auto-refresh-sec` (`i`)
- `device-auto-refresh-sec` (`i`)
- `icon-overrides` (`s`, JSON object keyed by indicator id)
- `enable-git-sync` (`b`), `git-sync-path` (`s`)
- `enable-icon-badges` (`b`, default `true`) — show count circles on top-bar icons
- `enable-claude-state-watch` (`b`, default `true`) — watch Claude session state files for the pencil badge

## Icon badges

Each visible indicator decorates its top-bar icon with a small circular
count badge:

- **controller** — number of Stream Deck devices currently detected
- **pencil** — first badge: configured paths; second badge (only when
  ≥1 Claude session is running): live session count; third badge
  (only when at least one session awaits user feedback): awaiting
  count, yellow on a `Stop` hook (assistant turn ended), red when a
  `Notification` hook is pending
- **media** — number of media entries in the catalogue
- **erplibre** — local + remote instance count
- **network** — `~/.ssh/config` hosts + last network scan host count
- **device** — number of Stream Deck devices

The pencil dropdown also shows a per-row badge with the same colour for
each path that has running Claude sessions.

The Claude session badge requires the Python hook in
`hooks/streamdeck-tiler-hook.py` to be wired into Claude Code; see
`hooks/README.md` for the `~/.claude/settings.json` snippet.

## D-Bus

Object path `/org/gnome/Shell/Extensions/StreamDeckTiler`, interface `org.gnome.Shell.Extensions.StreamDeckTiler`. Methods include the existing tiling / hot-reload calls plus:

- `OpenPath(s) -> b`
- `OpenMedia(s, s) -> b  (alias OpenFilm kept)` (player = `browser` | `mpv`)
- `OpenInstance(s, s) -> b` (action = `url` | `login` | `copy_user` | `copy_pass` | `open_keepass` | `start_server`)
- `ScanNetwork() -> s`
- `ListPaths() -> s`, `ListMedia() -> s  (alias ListFilms kept)`, `ListInstances() -> s`, `ListDevices() -> s`

## KeepassXC

Per ERPLibre instance: `keepass_db`, `keepass_keyfile` (optional), `keepass_yubikey_slot` / `keepass_yubikey_serial` (optional), `keepass_entry`. Master password is held in memory for 5 minutes after a successful unlock.

## Auto-login methods

- `selenium` — invokes `script/selenium/web_login.py` via `.venv.erplibre/bin/python`. Falls back to `xdotool` if the venv is missing.
- `xdotool` — experimental. Open URL, type user, Tab, type password, Return.
- `none` — hide the auto-login menu item.

## Limitations

- DRM streaming sites (Netflix, Crunchyroll, etc.) only work via the browser launcher.
- Network scan does not require root but cannot find SSH on non-default ports.
- Git sync resolves conflicts as last-write-wins; manual merges may be required.

## Hot-reload

The existing UUID-rename trick is preserved. Call:


```
gdbus call --session --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotReload
```


## Tests


```
make test_gnome_extension
```


Runs `glib-compile-schemas --strict --dry-run` plus `node --test test/unit/*.test.js`. The manual smoke checklist lives at `test/manual.md`.


## Internationalisation

The extension ships English (source) and French translations. GNOME
shell auto-picks the right one based on the system `LANG` (e.g.
`LANG=fr_CA.UTF-8`).

### Files

- `po/streamdeck-tiler.pot` — extraction template; regenerate after
  adding new `_()` strings.
- `po/en.po`, `po/fr.po` — per-language catalogues.
- `locale/<lang>/LC_MESSAGES/streamdeck-tiler.mo` — compiled binary
  catalogues read at runtime; gitignored, regenerated at install.

### Adding a new language

1. Copy `po/en.po` to `po/<lang>.po` (e.g. `po/de.po`).
2. Translate every `msgstr "…"`.
3. Run `make streamdeck_tiler_compile_locale` to rebuild the `.mo`
   files.
4. Reload the extension. GNOME will pick `<lang>` automatically when
   the system locale matches.

### Updating existing translations

Edit `msgstr` lines in `po/<lang>.po`, then re-run
`make streamdeck_tiler_compile_locale`.
