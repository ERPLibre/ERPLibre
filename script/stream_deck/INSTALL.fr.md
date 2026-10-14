
# Guide d'installation

ERPLibre Home s'installe en deux niveaux, sur Debian, Ubuntu, Fedora,
AlmaLinux, Rocky Linux, openSUSE et Arch Linux, avec GNOME Shell 45 à 51,
sans Odoo. La base est l'extension GNOME, ses schémas et ses traductions,
activée : elle ne demande ni accès au périphérique ni venv. Le niveau Stream
Deck ajoute ce dont les programmes du deck ont besoin, et installe aussi la
base quand elle manque. Les deux tournent sous ton compte et n'appellent
`sudo` que pour les paquets système et la règle udev.

```
./script/install/install_erplibre_home.sh
./script/install/install_erplibre_home.sh --stream-deck
```

Lance-les depuis le dépôt. La première commande installe la base : les
paquets système de la base, `make` compris, puis elle lie l'extension GNOME
dans `~/.local/share/gnome-shell/extensions/`, compile ses schémas et ses
traductions (avec `msgfmt`), et l'active. La seconde, pour un poste qui a un
Stream Deck, ajoute les paquets du Stream Deck, écrit la règle udev et crée
`.venv.streamdeck` depuis `script/stream_deck/requirements.txt`. Ferme
ensuite ta session et rouvre-la : sous Wayland, GNOME Shell ne charge une
nouvelle extension qu'à l'ouverture de session. Une seconde exécution ne
change rien. Sans le niveau Stream Deck, les indicateurs `device` et
`controller` de l'extension disent qu'ERPLibre Home Stream Deck n'est pas
installé et nomment `make erplibre_home_streamdeck_install`.

Un bureau neuf n'a pas toujours `make`, d'où le script en premier. Une fois
la base installée, `make erplibre_home_install` et
`make erplibre_home_streamdeck_install` lancent les deux mêmes commandes. Le
script accepte ces options :

| Option | Effet |
|---|---|
| `--stream-deck` | ajoute le niveau Stream Deck : paquets USB, règle udev, `.venv.streamdeck` ; la base s'installe aussi quand elle manque |
| `--no-enable` | installe sans activer l'extension ; un poste où l'ancienne extension était active garde cet état sous le nouveau nom |
| `--extension-only` | migre depuis l'ancienne extension, lie l'extension et compile ses schémas et ses traductions, rien d'autre ; ni `sudo` ni vérification du système ; ni avec `--stream-deck` ni avec `--uninstall` |
| `--with-extras` | installe aussi `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` et le module Python `lz4`, à l'un ou l'autre niveau, une commande du gestionnaire de paquets chacun ; un paquet absent est sauté avec un avertissement |
| `--deck-program=tiler\|controller\|none` | avec `--stream-deck` : le programme que lance le service du deck (défaut `tiler`) |
| `--autostart` | avec `--stream-deck` : active le service du deck à l'ouverture de session (défaut : non activé) |
| `--restart-after-game`, `--no-restart-after-game` | avec `--stream-deck` : le service du deck revient après un jeu, ou non (défaut : il revient) ; les deux s'excluent |
| `--uninstall` | retire tout : désactive l'extension, retire son lien, le service du deck et ses réglages, la règle udev et `.venv.streamdeck` ; avec `--stream-deck`, tout sauf l'extension, qui reste active ; les paquets système restent toujours |
| `--dry-run` | affiche ce qui serait fait, ne change rien |

Le code de sortie `0` veut dire fait, `2` un système non supporté (une
ligne sur stderr qui commence par `UNSUPPORTED:`), `1` tout autre échec, y
compris un `--uninstall` qui a retiré le reste mais n'a pu ni lire ni écrire
`enabled-extensions`.
`make erplibre_home_uninstall` lance `--uninstall`, et
`make erplibre_home_streamdeck_uninstall` lance `--uninstall --stream-deck`.

### Paquets système, pour référence

L'installateur prend la colonne de ta famille de distribution : les lignes
de la base toujours, celles du Stream Deck avec `--stream-deck`. Sur
AlmaLinux et Rocky Linux, `--stream-deck` active d'abord EPEL
(`dnf install -y epel-release`), d'où vient `wmctrl` ; la base ne touche
pas à EPEL.

| Level | Role | apt | dnf | zypper | pacman |
|---|---|---|---|---|---|
| base | schemas | `libglib2.0-bin` | `glib2` | `glib2-tools` | `glib2` |
| base | gettext (`msgfmt`) | `gettext` | `gettext` | `gettext-tools` | `gettext` |
| base | system python | `python3` | `python3` | `python3` | `python` |
| base | `make` targets | `make` | `make` | `make` | `make` |
| Stream Deck | hidapi + libusb | `libhidapi-libusb0 libusb-1.0-0` | `hidapi libusb1` | `libhidapi-libusb0 libusb-1_0-0` | `hidapi libusb` |
| Stream Deck | venv | `python3-venv` | `python3` | `python3` | `python` |
| Stream Deck | opencv runtime (`import cv2`) | - | - | `libgthread-2_0-0` | - |
| Stream Deck | window control | `wmctrl` | `wmctrl` | `wmctrl` | `wmctrl` |

### Accès au périphérique : la règle udev

Avec `--stream-deck`, l'installateur écrit
`/etc/udev/rules.d/70-streamdeck.rules` :

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
```

`0fd9` est l'identifiant de fabricant USB d'Elgato : la règle couvre tous les
modèles de Stream Deck. `uaccess` donne l'accès au périphérique à
l'utilisateur assis devant le poste, sur toutes les familles de distribution ;
aucun groupe n'est requis, contrairement au groupe `plugdev`, qui n'existe que
sur Debian et Ubuntu. Le préfixe `70-` place la règle avant
`73-seat-late.rules`, qui applique `uaccess`. Pour diagnostiquer un
périphérique qui n'est pas vu, ou ajouter du nouveau matériel, observer les
événements en le branchant :

```
sudo udevadm monitor
```

### Le service du deck

Un Stream Deck est piloté par un seul programme à la fois. Avec
`--stream-deck`, l'installateur écrit l'unité `systemd --user`
`~/.config/systemd/user/erplibre-home-streamdeck.service`, qui lance ce
programme depuis ce dépôt, et ses réglages
`~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` respecté) :

```
DECK_PROGRAM=tiler
RESTART_AFTER_GAME=yes
```

`DECK_PROGRAM` vaut `tiler` (`script/stream_deck/game_tiler.py`),
`controller` (`script/stream_deck/erplibre_controller.py`) ou `none`. Une
option donnée écrit sa clé ; une option absente garde la valeur déjà dans
le fichier, et le défaut ne vaut que pour une clé absente : une
réinstallation garde un programme choisi dans TODO. Toute autre ligne
reste. L'unité ne démarre que si un programme est choisi, que
`.venv.streamdeck` existe et qu'un deck est branché ; sinon systemd la saute.
L'installateur ne la démarre jamais : le programme a besoin de l'extension,
qu'une installation neuve charge à la prochaine ouverture de session. Avec
`--autostart`, l'unité est activée et démarre à l'ouverture de session. Sans
gestionnaire utilisateur joignable (une installation par ssh sans session),
le bilan nomme la commande à lancer après la prochaine connexion.

Les jeux prennent le deck : le menu des jeux de TODO et la galerie lancent
chaque jeu par `script/install/erplibre_home_handover.sh`, qui arrête le
service, lance le jeu, puis relance le service à la fin du jeu, sauf si
`RESTART_AFTER_GAME=no`. Chaque programme du deck prend un verrou,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock` ; un second sort avec le code 2
et nomme le programme et le PID qui tiennent le deck. `systemctl --user`
pilote le service :

```
systemctl --user status erplibre-home-streamdeck.service
systemctl --user enable erplibre-home-streamdeck.service
journalctl --user -u erplibre-home-streamdeck.service -f
```

Le menu **Exécution › Stream Deck** de TODO réunit les jeux, les deux
installations locales, le service, le programme du deck, le démarrage
automatique, un état, un diagnostic qui nomme la commande corrigeant chaque
problème, les deux désinstallations, et le rechargement et les préférences
de l'extension. Son installation Stream Deck demande le programme, le
démarrage automatique, la relance après un jeu et les outils facultatifs,
puis affiche la commande de l'installateur avant de la lancer.

## Lecteur film mpv — backend yt-dlp
Le lanceur `mpv` de l'indicateur film passe les URL à mpv, qui
délègue l'extraction du flux à un backend `youtube-dl`. Le
`youtube-dl` historique n'est plus maintenu sur Debian 13 /
Ubuntu 24.04+ ; installe `yt-dlp` et l'extension transmet
`--script-opts=ytdl_hook-ytdl_path=yt-dlp` automatiquement — pas
besoin de `mpv.conf` per-user.
```
sudo apt install -y mpv yt-dlp
# Verify:
yt-dlp --version
```
Les erreurs du type « youtube-dl failed: not found » apparaissent
dans l'onglet Log des préférences quand yt-dlp manque.
### Importer les onglets YouTube depuis Firefox

L'onglet Film des préférences expose un bouton « Import » qui scanne
les onglets ouverts de chaque profil Firefox et ajoute toute URL
YouTube comme nouvelle entrée film. Le helper lit
`recovery.jsonlz4` de chaque profil et nécessite le codec lz4 de
Mozilla :
```
sudo apt install -y python3-lz4
```
### Raccourcis clavier mpv (bindings par défaut)
| Key            | Action                                       |
|----------------|----------------------------------------------|
| `Space` / `p`  | Pause / play toggle                          |
| `q`            | Quit (saves position via watch-later)        |
| `Shift-Q`      | Quit and save explicitly                     |
| `←` / `→`      | Seek -5 s / +5 s                             |
| `↑` / `↓`      | Seek +1 min / -1 min                         |
| `Page Up/Down` | Seek ±10 min                                 |
| `m`            | Mute toggle                                  |
| `f`            | Fullscreen toggle                            |
| `XF86AudioPlay`| Play / pause (multimedia keyboard)           |
Le lanceur film passe `--save-position-on-quit=yes` ; quitter mpv
(une des touches ci-dessus, ou fermer la fenêtre) écrit
`start=<secondes>` dans `~/.config/mpv/watch_later/<MD5_DE_URL>`.
L'extension relit ce fichier à la sortie de mpv et met à jour le
champ `position` de l'entrée — le prochain lancement (mpv, browser
ou VLC) honore ce timestamp.
## Auto-accepter les invites Claude (Wayland)
L'action « Accept response » de l'indicateur crayon et le bouton
rouge sur le deck synthétisent une frappe Entrée dans le terminal
Claude focalisé pour acquitter un `Notification` sans quitter le
lanceur. La frappe est générée **directement par l'extension GNOME**
via le périphérique d'entrée virtuel de Clutter — aucun outil
externe n'est requis et aucun changement de groupe n'est nécessaire.
Les outils externes comme `wtype` (qui requiert
`zwp_virtual_keyboard_v1`, non exposé aux clients arbitraires par
Mutter) ou `ydotool` (non packagé sur Debian 13) ne sont **pas**
des prérequis.
## Hooks de l'extension GNOME ERPLibre Home
La pastille du crayon a besoin que Claude Code écrive un petit
fichier JSON d'état à chaque événement de session. Branche le hook
(idempotent, peut être relancé) :
```
make claude_install_hooks
```
`make claude_uninstall_hooks` pour retirer. Les sessions Claude en
cours ne relisent `~/.claude/settings.json` qu'au SessionStart ;
relance les `claude` ouverts pour que la pastille les suive.