
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
Stream Deck, ajoute les paquets du Stream Deck, écrit la règle udev, crée
`.venv.streamdeck` depuis `script/stream_deck/requirements.txt` et clone les
jeux (voir plus bas). Ferme ensuite ta session et rouvre-la : sous Wayland, GNOME Shell ne charge une
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
| `--autostart` | avec `--stream-deck` : active le service du deck à l'ouverture de session et au branchement d'un deck (défaut : non activé) |
| `--restart-after-game`, `--no-restart-after-game` | avec `--stream-deck` : le service du deck revient après un jeu, ou non (défaut : il revient) ; les deux s'excluent |
| `--uninstall` | retire tout : désactive l'extension, retire son lien, le service du deck et ses réglages, la règle udev et `.venv.streamdeck` ; avec `--stream-deck`, tout sauf l'extension, qui reste active ; les paquets système et les jeux restent toujours |
| `--dry-run` | affiche ce qui serait fait, ne change rien |

Le code de sortie `0` veut dire fait, `2` un système non supporté (une
ligne sur stderr qui commence par `UNSUPPORTED:`), `1` tout autre échec, y
compris un `--uninstall` qui a retiré le reste mais n'a pu ni lire ni écrire
`enabled-extensions`.
`make erplibre_home_uninstall` lance `--uninstall`, et
`make erplibre_home_streamdeck_uninstall` lance `--uninstall --stream-deck`.

### Les jeux

Les jeux et leur galerie sont un dépôt à part,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloné
dans `script/stream_deck/games/`. `manifest/git_manifest_streamdeck_game.xml`
l'épingle sur une étiquette : Google Repo l'y clone dans un checkout qu'il
gère, et `--stream-deck` le clone à cette même étiquette quand le
répertoire manque. Un répertoire déjà là reste tel quel, sauf celui qui ne
garde que `save/` et `__pycache__/`, ce qu'un checkout garde quand la mise
à jour qui a cessé de suivre les jeux en retire les fichiers :
l'installateur y clone les jeux, sauvegardes comprises. `--uninstall` ne
les retire jamais. `CONTRACT.md`, à la racine des jeux, dit ce que les jeux
et ERPLibre attendent l'un de l'autre ; `script/stream_deck/games_contract`
porte la version du contrat pour laquelle ERPLibre est écrit.

Sans les jeux, le programme du deck, le contrôleur et le service
fonctionnent ; le menu des jeux de TODO, la galerie,
`make streamdeck_<jeu>` et la passation refusent, en une ligne qui nomme
`make erplibre_home_streamdeck_install`.

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
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0fd9", TAG+="systemd", ENV{SYSTEMD_ALIAS}="/sys/subsystem/erplibre/streamdeck"
```

`0fd9` est l'identifiant de fabricant USB d'Elgato : la règle couvre tous les
modèles de Stream Deck. `uaccess` donne l'accès au périphérique à
l'utilisateur assis devant le poste, sur toutes les familles de distribution ;
aucun groupe n'est requis, contrairement au groupe `plugdev`, qui n'existe que
sur Debian et Ubuntu. Le préfixe `70-` place la règle avant
`73-seat-late.rules`, qui applique `uaccess`. La troisième ligne nomme le
deck branché `sys-subsystem-erplibre-streamdeck.device` dans le gestionnaire
systemd de l'utilisateur ; cette unité veut le service du deck, si bien
qu'un service activé démarre quand un deck est branché après l'ouverture de
session. Pour diagnostiquer un périphérique qui n'est pas vu, ou ajouter du
nouveau matériel, observer les événements en le branchant :

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

`DECK_PROGRAM` vaut `tiler` (le paquet `script/stream_deck/erplibre_streamdeck`),
`controller` (`script/stream_deck/erplibre_controller.py`) ou `none`. Une
option donnée écrit sa clé ; une option absente garde la valeur déjà dans
le fichier, et le défaut ne vaut que pour une clé absente : une
réinstallation garde un programme choisi dans TODO. Toute autre ligne
reste. L'unité ne démarre que si un programme est choisi, que
`.venv.streamdeck` existe, qu'un deck est branché et que la session
graphique est ouverte ; sinon systemd la saute.
Une fois lancé, le programme du deck survit à son deck : débranché, il
écrit une ligne au journal, garde le verrou du deck et cherche un deck
toutes les 2 secondes ; le deck rebranché revient sur l'écran d'accueil.
Un deck trouvé mais refusé à l'ouverture (son nœud de périphérique
inaccessible) écrit une ligne de plus, qui nomme l'erreur. Un deck qui
disparaît de nouveau moins de 10 secondes après son retour est cherché deux
fois moins souvent à chaque fois, jusqu'à une fois toutes les 30 secondes.
L'installateur ne la démarre jamais : le programme a besoin de l'extension,
qu'une installation neuve charge à la prochaine ouverture de session. Avec
`--autostart`, l'unité est activée et démarre à l'ouverture de session, ou
au branchement d'un deck par la suite. Sans
gestionnaire utilisateur joignable (une installation par ssh sans session),
le bilan nomme la commande à lancer après la prochaine connexion.

`GAMES=on|off` active ou désactive la bibliothèque de jeux du Stream Deck.
`on`, ou l'absence de ligne `GAMES`, l'active ; `off` la désactive ; toute
autre valeur la désactive aussi et TODO › Stream Deck › Diagnostic la
nomme. Jeux désactivés, le menu des jeux de TODO, la galerie,
`make streamdeck_<jeu>` et le passage de relais refusent de lancer un jeu et
disent comment les activer ; le programme du deck, le contrôleur et le
service ne sont jamais touchés. Se règle dans TODO › Stream Deck › Jeux on/off,
ou à la main dans ce fichier.

`DECK_PLUGINS_OFF=<id>,<id>` liste les plugins du programme du deck qui ne
sont pas chargés (vide ou absent : tous se chargent). Se règle dans TODO ›
Stream Deck › Plugins on/off, ou à la main dans ce fichier ; TODO › Stream
Deck › Diagnostic nomme un identifiant qui ne correspond à aucun plugin. Les
plugins de l'utilisateur vivent dans
`$XDG_CONFIG_HOME/erplibre-home/deck-plugins/`. `python
script/stream_deck/erplibre_streamdeck --list-plugins` affiche chaque plugin
que le chargeur trouve et son état, sans ouvrir le deck.

`DECK_SESSION_REFRESH_SEC=<secondes>` règle la fréquence de rafraîchissement
des pages de session Claude et mpv : un nombre de 0,5 à 60, 1 si absent. Une
valeur qui n'est pas un nombre, ou hors de l'intervalle, donne 1, et TODO ›
Stream Deck › Diagnostic la nomme. Se règle dans TODO › Stream Deck › [13]
Rafraîchissement (qui propose de redémarrer le service du
deck), ou à la main dans ce fichier.

Les jeux prennent le deck : le menu des jeux de TODO et la galerie lancent
chaque jeu par `script/install/erplibre_home_handover.sh`, qui arrête le
service, lance le jeu, puis relance le service à la fin du jeu, sauf si
`RESTART_AFTER_GAME=no`. Le deck a un verrou,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock` : le window tiler et le
contrôleur le prennent, et la passation le prend au nom de `game` et le
passe au jeu : il reste tenu tant qu'un processus du jeu tourne. Un second
détenteur sort avec le code 2 et nomme le programme et le PID qui tiennent
le deck : le service, ou **Démarrer le programme du deck** dans le
panneau, reste arrêté pendant un jeu. Dans un jeu, un seul programme du
deck tourne à la fois : un second sort avec le code 2 et nomme le premier.
Pour libérer le deck, fermer le jeu.
En dernier recours, le diagnostic Stream Deck de TODO nomme chaque
processus qui tient le verrou, le jeu entier, pour un seul `kill` ; un
`kill` sur le PID que nomme le verrou atteint lui aussi chaque processus du
jeu. Un jeu lancé par
`make streamdeck_<jeu>` contourne la passation et ne prend aucun verrou.
`systemctl --user` pilote le service :

```
systemctl --user status erplibre-home-streamdeck.service
systemctl --user enable erplibre-home-streamdeck.service
journalctl --user -u erplibre-home-streamdeck.service -f
```

L'installateur, TODO et l'extension trouvent l'unité et les réglages sous
`$XDG_CONFIG_HOME` ; le gestionnaire de l'utilisateur et le service lisent
leur propre environnement. Poser `XDG_CONFIG_HOME` dans
`~/.config/environment.d/*.conf`, que lisent la session et le gestionnaire
de l'utilisateur, et pas seulement dans le fichier rc du shell : sinon
l'unité s'écrit là où systemd ne regarde pas, et le service lit ses
réglages par défaut au lieu de ceux enregistrés.

Le menu **Exécution › Stream Deck** de TODO réunit les jeux, les deux
installations locales, le service, le programme du deck, le démarrage
automatique, un état, un diagnostic qui nomme la commande corrigeant chaque
problème, les deux désinstallations, et le rechargement et les préférences
de l'extension. Son installation Stream Deck demande le programme, le
démarrage automatique, la relance après un jeu et les outils facultatifs,
le programme et la relance proposant par défaut les réglages en place, puis
affiche la commande de l'installateur avant de la lancer.

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