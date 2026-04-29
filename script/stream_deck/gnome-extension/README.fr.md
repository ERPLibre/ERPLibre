
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


```
gdbus call --session --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotReload
```


## Tests


```
make test_gnome_extension
```


Exécute `glib-compile-schemas --strict --dry-run` puis `node --test test/unit/*.test.js`. La checklist manuelle est dans `test/manual.md`.