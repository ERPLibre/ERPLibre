<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [en] -->

## Screenshots

`../screenshots/` holds the canonical screenshots referenced from
this README. Run `../screenshots/capture.sh` while the extension is
loaded (and a Stream Deck is plugged in for the deck shots) to
regenerate them. The folder's own `README.md` lists every expected
file and the conventions for cropping / naming.

<!-- [fr] -->

## Captures d'écran

`../screenshots/` contient les captures d'écran référencées par ce
README. Lancer `../screenshots/capture.sh` quand l'extension est
chargée (et qu'un Stream Deck est branché pour les captures du
boîtier) pour les regénérer. Le `README.md` du dossier liste chaque
fichier attendu ainsi que les conventions de cadrage / nommage.

<!-- [en] -->

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

<!-- [fr] -->
# Stream Deck Tiler — Extension GNOME Shell

Panneau à six indicateurs pour la barre du haut GNOME, plus une interface D-Bus utilisée par les helpers Python Stream Deck.

## Indicateurs

| Id          | Icône par défaut              | Rôle                                                                          |
|-------------|-------------------------------|-------------------------------------------------------------------------------|
| controller  | `input-gaming-symbolic`       | D-Bus de tuilage + sous-menu Games + lien vers les préférences                |
| pencil      | `document-edit-symbolic`      | Ouvre un `gnome-terminal` avec `claude` dans un chemin choisi (Resume / Fresh / Custom) |
| media       | `video-x-generic-symbolic`    | Liste vidéo / audio ouverte via navigateur, `mpv --start=<position>`, VLC ou Spotify |
| erplibre    | `network-server-symbolic`     | Instances ERPLibre locales + distantes ; login Selenium / xdotool via KeepassXC |
| network     | `network-wired-symbolic`      | Découverte SSH (`nmap -p22` ou `nc` en repli) + hôtes de `~/.ssh/config`      |
| device      | `input-tablet-symbolic`       | Liste des Stream Deck USB Elgato, démarrage / redémarrage du daemon contrôleur |

Chaque indicateur peut être activé/désactivé dans la fenêtre de préférences.

## Préférences

`gnome-extensions prefs streamdeck-tiler@technolibre.ca`

Pages : Buttons, Pencil, Media, ERPLibre, Network, Device, Theming, Sync, Advanced, About.

## Clés GSettings

Schéma `org.gnome.shell.extensions.streamdeck-tiler`. Clés notables :

- `enable-controller`, `enable-pencil`, `enable-media`, `enable-erplibre`, `enable-network`, `enable-device` (booléens)
- `button-order` (`as`) — ordre gauche → droite
- `panel-box` (`s`, défaut `left`) — `left` (côté droit de la zone gauche, juste avant l'horloge centrale), `center` ou `right`
- `paths`, `media`, `instances` (`s`, JSON)
- `terminal-claude-cmd` (`s`, défaut `claude --resume`)
- `network-cidrs` (`as`), `network-ssh-user` (`s`), `network-use-nmap` (`b`), `network-read-ssh-config` (`b`), `network-auto-refresh-sec` (`i`)
- `device-auto-refresh-sec` (`i`)
- `icon-overrides` (`s`, JSON)
- `enable-git-sync` (`b`), `git-sync-path` (`s`)
- `enable-icon-badges` (`b`, défaut `true`) — affiche les pastilles de comptage sur les icônes
- `enable-claude-state-watch` (`b`, défaut `true`) — surveille les fichiers d'état Claude pour le badge du crayon

## Pastilles de comptage

Chaque indicateur visible affiche une petite pastille circulaire sur
l'icône de la barre du haut :

- **controller** — nombre de Stream Decks détectés
- **pencil** — première pastille : chemins configurés ; deuxième
  pastille (seulement quand ≥1 session Claude tourne) : nombre de
  sessions vivantes ; troisième pastille (seulement si au moins une
  session attend l'utilisateur) : compte en attente, jaune sur hook
  `Stop` (tour de l'assistant fini), rouge si hook `Notification`
- **media** — nombre d'entrées média
- **erplibre** — instances locales + distantes
- **network** — hôtes `~/.ssh/config` + résultats du dernier scan
- **device** — nombre de Stream Decks

Le menu déroulant du crayon ajoute aussi une pastille par ligne pour
les chemins qui ont des sessions Claude actives.

Le badge des sessions Claude requiert le hook Python
`hooks/streamdeck-tiler-hook.py` branché dans Claude Code ; voir
`hooks/README.fr.md` pour l'extrait `~/.claude/settings.json`.

## D-Bus

Object path `/org/gnome/Shell/Extensions/StreamDeckTiler`, interface `org.gnome.Shell.Extensions.StreamDeckTiler`. Méthodes existantes (tuilage / hot-reload) + extensions :

- `OpenPath(s) -> b`
- `OpenMedia(s, s) -> b  (alias OpenFilm kept)` (player = `browser` | `mpv`)
- `OpenInstance(s, s) -> b` (action = `url` | `login` | `copy_user` | `copy_pass` | `open_keepass` | `start_server`)
- `ScanNetwork() -> s`
- `ListPaths() -> s`, `ListMedia() -> s  (alias ListFilms kept)`, `ListInstances() -> s`, `ListDevices() -> s`

## KeepassXC

Par instance ERPLibre : `keepass_db`, `keepass_keyfile` (optionnel), `keepass_yubikey_slot` / `keepass_yubikey_serial` (optionnel), `keepass_entry`. Le mot de passe maître est gardé en mémoire 5 minutes après le déverrouillage.

## Méthodes d'auto-login

- `selenium` — invoque `script/selenium/web_login.py` via `.venv.erplibre/bin/python`. Repli sur `xdotool` si le venv manque.
- `xdotool` — expérimental. Ouvre l'URL, tape l'utilisateur, Tab, mot de passe, Entrée.
- `none` — masque l'item d'auto-login.

## Limitations

- Les sites de streaming DRM (Netflix, Crunchyroll, etc.) ne fonctionnent que via le navigateur.
- Le scan réseau n'exige pas root mais ne trouve pas SSH sur des ports non standards.
- La sync Git résout les conflits en mode dernier-écrit-gagne ; un merge manuel peut être requis.

## Hot-reload

La technique UUID-rename existante est préservée. Appeler :

<!-- [common] -->

```
gdbus call --session --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotReload
```

<!-- [en] -->

## Tests

<!-- [fr] -->

## Tests

<!-- [common] -->

```
make test_gnome_extension
```

<!-- [en] -->

Runs `glib-compile-schemas --strict --dry-run` plus `node --test test/unit/*.test.js`. The manual smoke checklist lives at `test/manual.md`.

<!-- [fr] -->

Exécute `glib-compile-schemas --strict --dry-run` puis `node --test test/unit/*.test.js`. La checklist manuelle est dans `test/manual.md`.

<!-- [en] -->

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

<!-- [fr] -->

## Internationalisation

L'extension est livrée en anglais (source) et en français. GNOME
shell choisit automatiquement la bonne langue selon `LANG`
(ex. `LANG=fr_CA.UTF-8`).

### Fichiers

- `po/streamdeck-tiler.pot` — gabarit d'extraction ; à régénérer
  après l'ajout de chaînes `_()`.
- `po/en.po`, `po/fr.po` — catalogues par langue.
- `locale/<lang>/LC_MESSAGES/streamdeck-tiler.mo` — catalogues
  binaires lus à l'exécution ; gitignorés, regénérés à
  l'installation.

### Ajouter une nouvelle langue

1. Copier `po/en.po` vers `po/<lang>.po` (ex. `po/de.po`).
2. Traduire chaque `msgstr "…"`.
3. Exécuter `make streamdeck_tiler_compile_locale` pour reconstruire
   les fichiers `.mo`.
4. Recharger l'extension. GNOME choisit `<lang>` automatiquement
   quand la locale système correspond.

### Mettre à jour des traductions existantes

Modifier les lignes `msgstr` dans `po/<lang>.po`, puis relancer
`make streamdeck_tiler_compile_locale`.
