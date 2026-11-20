
# Guide d'installation

ERPLibre Home s'installe en deux niveaux, sur Debian, Ubuntu, Fedora,
AlmaLinux, Rocky Linux, openSUSE et Arch Linux, avec GNOME Shell 45 à 51,
sans Odoo. La base est l'extension GNOME, ses schémas et ses traductions,
activée : elle ne demande ni accès au périphérique ni venv. Le niveau Stream
Deck ajoute ce dont les programmes du deck ont besoin, et installe aussi la
base quand elle manque. Les deux tournent sous ton compte et n'appellent
`sudo` que pour les paquets système et la règle udev.

```
./script/install/install_erplibre.sh
./script/install/install_erplibre_home.sh
./script/install/install_erplibre_home.sh --stream-deck
```

Lance-les depuis le dépôt. La première commande pose `.venv.erplibre`, le
venv d'outillage d'ERPLibre, qui porte le `repo` de Google Repo :
l'installateur le prend là, et s'arrête en nommant cette commande quand le
venv manque. La deuxième installe la base : Google Repo amène l'extension
GNOME, un dépôt à part, dans `script/gnome-extension/erplibre_home/` (voir
[l'extension dans ERPLibre](../../doc/erplibre_home_gnome_extension.fr.md)),
puis l'installateur installe les paquets système de la base, `make`
compris, lie l'extension dans `~/.local/share/gnome-shell/extensions/`,
compile ses schémas et ses traductions (avec `msgfmt`), et l'active. La
troisième, pour un poste qui a un Stream Deck, ajoute les paquets du Stream
Deck, écrit la règle udev, fait amener par Google Repo le programme du
deck, un dépôt à part, dans `script/stream_deck/deck/` (voir
[le programme du deck dans ERPLibre](../../doc/erplibre_streamdeck_deck.fr.md)),
puis crée `.venv.streamdeck` depuis son `requirements.txt`. Ferme ensuite
ta session et rouvre-la : sous Wayland, GNOME Shell ne charge une nouvelle
extension qu'à l'ouverture de session. Sans le niveau Stream Deck, les
indicateurs `device` et `controller` de l'extension disent qu'ERPLibre Home
Stream Deck n'est pas installé et nomment
`make erplibre_home_streamdeck_install`.

Chaque exécution ajoute l'extension, et avec `--stream-deck` le programme
du deck, à `.repo/local_manifests/erplibre_manifest.xml`, sans rien en
retirer, et lance `repo sync` sur chaque chemin seul : les deux suivent le
dernier commit de leur `main`, et une exécution suivante ne change rien
d'autre. `git` est requis. La pose de `.venv.erplibre/bin/repo` et le
premier `repo init` d'un checkout joignent les hôtes de Google pour `repo`
lui-même (`storage.googleapis.com`, `gerrit.googlesource.com`) ; chaque
sync joint GitHub pour les deux projets. Un répertoire qui n'est pas un checkout repo, un clone git ou une
copie, est mis de côté entier dans `<dir>.avant-repo-<date>`, à côté de
lui, nommé dans le bilan, et remis en place quand le sync échoue. Sur un
checkout repo, un sync en échec, hors ligne par exemple, laisse le projet
tel quel : le bilan dit « NOT updated » et l'installation continue. Pour
modifier l'un des projets, travailler sur une branche que lance
`repo start <branche> <dir>` ; un HEAD détaché passe sur `main` au sync
suivant.

Un bureau neuf n'a pas toujours `make`, d'où le script en premier. Une fois
la base installée, `make erplibre_home_install` et
`make erplibre_home_streamdeck_install` lancent les mêmes commandes de
l'installateur. Le script accepte ces options :

| Option | Effet |
|---|---|
| `--stream-deck` | ajoute le niveau Stream Deck : paquets USB, règle udev, le programme du deck, synchronisé par Google Repo dans `script/stream_deck/deck/`, `.venv.streamdeck` ; la base s'installe aussi quand elle manque |
| `--no-enable` | installe sans activer l'extension ; un poste où l'ancienne extension était active garde cet état sous le nouveau nom |
| `--extension-only` | synchronise l'extension par Google Repo, migre depuis l'ancienne extension, lie l'extension et compile ses schémas et ses traductions, rien d'autre ; ni `sudo` ni vérification du système ; ni avec `--stream-deck` ni avec `--uninstall` |
| `--with-extras` | installe aussi `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` et le module Python `lz4`, à l'un ou l'autre niveau, une commande du gestionnaire de paquets chacun ; un paquet absent est sauté avec un avertissement |
| `--deck-program=tiler\|controller\|none` | avec `--stream-deck` : le programme que lance le service du deck (défaut `tiler`) |
| `--autostart` | avec `--stream-deck` : active le service du deck à l'ouverture de session et au branchement d'un deck (défaut : non activé) |
| `--uninstall` | retire tout : désactive l'extension, retire son lien, le service du deck et ses réglages, la règle udev et `.venv.streamdeck` ; avec `--stream-deck`, tout sauf l'extension, qui reste active ; les paquets système, `.repo`, le manifeste local et les checkouts de l'extension et du deck restent toujours |
| `--dry-run` | affiche ce qui serait fait, ne change rien |

Le code de sortie `0` veut dire fait, `2` un système non supporté (une
ligne sur stderr qui commence par `UNSUPPORTED:`), `1` tout autre échec, y
compris un `--uninstall` qui a retiré le reste mais n'a pu ni lire ni écrire
`enabled-extensions`.
`make erplibre_home_uninstall` lance `--uninstall`, et
`make erplibre_home_streamdeck_uninstall` lance `--uninstall --stream-deck`.

### Paquets système, pour référence

L'installateur prend la colonne de ta famille de distribution : les lignes
de la base toujours, celles du Stream Deck avec `--stream-deck`. Sur la
famille RHEL hors Fedora (RHEL, CentOS Stream, AlmaLinux, Rocky Linux),
`--stream-deck` active d'abord EPEL (`dnf install -y epel-release`), d'où
vient `wmctrl` ; la base ne touche pas à EPEL.

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
```

`DECK_PROGRAM` vaut `tiler` (le paquet `script/stream_deck/deck/erplibre_streamdeck`),
`controller` (`script/stream_deck/deck/erplibre_controller.py`) ou `none`. Une
option donnée écrit sa clé ; une option absente garde la valeur déjà dans
le fichier, et le défaut ne vaut que pour une clé absente : une
réinstallation garde un programme choisi dans TODO. Toute autre ligne
reste. L'unité ne démarre que si un programme est choisi, que
`.venv.streamdeck` et le checkout du deck existent, qu'un deck est branché et que la session
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

`DECK_PLUGINS_OFF=<id>,<id>` liste les plugins du programme du deck qui ne
sont pas chargés (vide ou absent : tous se chargent). Se règle dans TODO ›
ERPLibre Home › Plugins on/off, ou à la main dans ce fichier ; TODO › ERPLibre
Home › Diagnostic nomme un identifiant qui ne correspond à aucun plugin. Les
plugins de l'utilisateur vivent dans
`$XDG_CONFIG_HOME/erplibre-home/deck-plugins/`. `python
script/stream_deck/deck/erplibre_streamdeck --list-plugins` affiche chaque plugin
que le chargeur trouve et son état, sans ouvrir le deck.

`DECK_SESSION_REFRESH_SEC=<secondes>` règle la fréquence de rafraîchissement
des pages de session Claude et mpv : un nombre de 0,5 à 60, 1 si absent. Une
valeur qui n'est pas un nombre, ou hors de l'intervalle, donne 1, et TODO ›
ERPLibre Home › Diagnostic la nomme. Se règle dans TODO › ERPLibre Home ›
Rafraîchissement (qui propose de redémarrer le service du
deck), ou à la main dans ce fichier.

Le deck a un verrou, `$XDG_RUNTIME_DIR/erplibre-home/deck.lock` : le
window tiler et le contrôleur le prennent. Un second détenteur sort avec le
code 2 et nomme le programme et le PID qui tiennent le deck : le service,
ou **Démarrer le programme du deck** dans le panneau, reste arrêté tant
qu'un autre programme du deck tourne. Pour libérer le deck, fermer ce
programme ; en dernier recours, le diagnostic Stream Deck de TODO nomme les
processus qui tiennent le verrou, pour un seul `kill`.
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

Le menu **Exécution › ERPLibre Home** de TODO a quatre sections. Extension
GNOME : son installation locale seule, son rechargement et ses préférences,
et la désinstallation de tout. Stream Deck (outil bureautique) : son
installation, qui ajoute l'extension au besoin, la désinstallation du seul
niveau Stream Deck, et le service. Réglages du deck : programme, démarrage
automatique, plugins et rafraîchissement. État : un état et un diagnostic
qui nomme la commande corrigeant chaque problème. L'installation Stream
Deck demande le programme, le démarrage automatique et les outils
facultatifs, le programme proposant par défaut le réglage en place, puis
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