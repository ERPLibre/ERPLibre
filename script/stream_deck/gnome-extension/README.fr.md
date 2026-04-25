
# Stream Deck Tiler — Extension GNOME Shell

Extension D-Bus compagnon utilisée par `game_tiler.py` pour:

- Pavager la fenêtre active via `Meta.Window.move_resize_frame()` — sans
  simulation clavier, sans dépendance gTile.
- Lister et basculer les chronos gérés par l'extension
  [tracker](https://github.com/aliakseiz/tracker)
  (`tracker@aliakseiz.github.com`), qui n'a pas d'API publique propre.

Fonctionne sur Wayland et X11, GNOME Shell 45–48.

## Interface D-Bus

- Nom: `org.gnome.Shell.Extensions.StreamDeckTiler`
- Chemin: `/org/gnome/Shell/Extensions/StreamDeckTiler`
- Méthodes:
  - `TileWindow(gridCols, gridRows, col1, row1, col2, row2) -> success`
  - `GetMonitorGeometry() -> (x, y, width, height)`
  - `GetGridSize(gridCols, gridRows) -> (cellW, cellH)`
  - `ListTrackerTimers() -> json` — tableau JSON de
    `{id, name, running, elapsed}` lu depuis l'état mémoire de tracker.
    Retourne `[]` si tracker n'est pas installé ou pas activé.
  - `ToggleTrackerTimer(id) -> success` — démarrer un chrono en pause
    ou mettre en pause un chrono en cours. Accède à l'état privé de
    tracker; peut se casser lors de mises à jour de tracker.
  - `AddTrackerTimer() -> id` — créer un nouveau chrono via la méthode
    `_addNewTimer()` de tracker, ouvrir le menu panel de tracker, et
    entrer en mode édition sur le nouveau chrono avec le champ nom
    focalisé et vide pour que le clavier puisse taper le nom. Retourne
    l'id du nouveau chrono, ou chaîne vide en cas d'échec.
  - `HotReload() -> newUuid` — copier le dossier d'extension sous un
    UUID temporaire horodaté, le charger via `Main.extensionManager`,
    et basculer l'instance activée pour que le nouveau code source
    tourne sans re-login de session. Retourne le nouvel UUID
    temporaire, ou chaîne vide en cas d'échec. Voir « Hot reload »
    ci-dessous.
  - `HotExit() -> success` — désactiver + supprimer toutes les
    instances temporaires de reload et réactiver l'UUID principal.
    Complément de `HotReload`.

## Installation

UUID: `streamdeck-tiler@technolibre.ca`

### Option A — Makefile (depuis la racine du dépôt)

Première installation et après chaque édition de `extension.js`:

```bash
make streamdeck_tiler_install_extension
# Wayland: log out / log in
# X11:     Alt+F2, r, Enter
make streamdeck_tiler_enable_extension
```

Désinstaller: `make streamdeck_tiler_uninstall_extension`

> Pourquoi re-login?
> GNOME Shell 45+ met en cache les modules ES importés pour la durée
> de la session. `gnome-extensions disable && enable` appelle
> `disable()`/`enable()` sur le module déjà chargé — cela **ne**
> relit **pas** `extension.js`. L'ancienne méthode D-Bus
> `org.gnome.Shell.Extensions.ReloadExtension` est dépréciée sur
> GNOME 45+ et retourne `NotSupported`. Sur Wayland, un redémarrage
> complet du shell signifie un re-login de session; X11 peut utiliser
> `Alt+F2` → `r`. Voir **Hot reload** ci-dessous pour un contournement
> de la boucle de dev.

## Hot reload (boucle de dev)

Après la première installation + re-login, les éditions suivantes de
`extension.js` peuvent être chargées sans nouveau re-login via la
méthode D-Bus `HotReload` de l'extension. La méthode duplique le
dossier d'extension sous un UUID frais (ex
`streamdeck-tiler-reload-<ts>@technolibre.ca`) pour que la clé de
cache de module GJS change — le nouvel UUID déclenche une vraie
ré-importation ESM. La technique est adaptée de
[ExtensionReloader](https://codeberg.org/som/ExtensionReloader).

```bash
# Edit extension.js
make streamdeck_tiler_reload         # hot-reload, no re-login
# Edit again, reload again (previous temp is auto-purged)
make streamdeck_tiler_reload
# When done, restore the main UUID as the running instance:
make streamdeck_tiler_reload_clean
```

Limites importantes:

- **Le premier usage demande un re-login.** La méthode `HotReload`
  elle-même ne devient disponible qu'après que le shell ait chargé
  cette version de `extension.js`. Si `streamdeck_tiler_reload`
  rapporte `UnknownMethod: HotReload`, déconnecte-toi et reconnecte
  une fois, puis réessaie.
- Après `streamdeck_tiler_reload_clean`, l'UUID principal tourne le
  code source **caché (ancien)** jusqu'au prochain re-login — parce
  que son module ES reste en mémoire. Les éditions faites pendant la
  boucle de dev sont prises en compte au prochain démarrage propre du
  shell.
- Chaque reload laisse un dossier
  `streamdeck-tiler-reload-*@technolibre.ca` sur le disque jusqu'au
  nettoyage. `_reload_clean` les supprime.
- Pour un environnement de dev complètement isolé (aucun UUID
  temporaire dans la session principale), utilise un shell imbriqué:
  `dbus-run-session -- gnome-shell --nested --wayland`
  (GNOME 48 et antérieur) ou `--devkit --wayland` (GNOME 49+).

### Option B — manuel

```bash
# From repo root
EXT_UUID=streamdeck-tiler@technolibre.ca
EXT_DIR=~/.local/share/gnome-shell/extensions/$EXT_UUID
mkdir -p "$EXT_DIR"
cp script/stream_deck/gnome-extension/extension.js "$EXT_DIR/"
cp script/stream_deck/gnome-extension/metadata.json "$EXT_DIR/"
```

## Activation

GNOME Shell doit se recharger pour voir une nouvelle extension. Sur
Wayland, seul un re-login complet de session recharge le shell.

```bash
# 1. Log out of the GNOME session, then log back in.
# 2. Enable the extension:
gnome-extensions enable streamdeck-tiler@technolibre.ca
```

Vérifier:

```bash
gnome-extensions info streamdeck-tiler@technolibre.ca | grep -i Activ
# Expect: Activé: Oui  (or: Enabled: Yes)

gdbus introspect --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler
# Expect: node containing method TileWindow
```

## Test manuel

Pavager la fenêtre active sur la moitié gauche d'une grille 2×1:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.TileWindow \
  2 1 0 0 0 0
```

Lister les chronos tracker:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.ListTrackerTimers
```

Basculer un chrono (remplacer `<id>` par un id de la liste):

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.ToggleTrackerTimer \
  '<id>'
```

Créer un nouveau chrono et ouvrir le mode édition dessus:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.AddTrackerTimer
```

Hot-reload de l'extension (retourne le nouvel UUID temporaire):

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotReload
```

Démanteler l'état de reload:

```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.HotExit
```

## Désinstallation

```bash
gnome-extensions disable streamdeck-tiler@technolibre.ca
rm -rf ~/.local/share/gnome-shell/extensions/streamdeck-tiler@technolibre.ca
# Log out / log in to fully unload from the shell.
```

## Dépannage

- Erreur `GDBus.Error:org.freedesktop.DBus.Error.UnknownMethod: ... object does not exist at ...StreamDeckTiler`
  → Extension pas activée ou shell pas rechargé. Exécuter
  `gnome-extensions enable streamdeck-tiler@technolibre.ca` puis log
  out/in (Wayland) ou presser `Alt+F2` → `r` → Entrée (X11 seulement).
- `gnome-extensions info ...` affiche `État: INITIALIZED` et
  `Activé: Non` → Même cause, même solution.
- Mauvaise version de shell → Éditer `metadata.json` `shell-version`
  pour inclure ta version GNOME (`gnome-shell --version`).

## Logs

```bash
journalctl --user -f /usr/bin/gnome-shell | grep StreamDeckTiler
```