<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Guide to install

ERPLibre Home installs in two levels, on Debian, Ubuntu, Fedora, AlmaLinux,
Rocky Linux, openSUSE and Arch Linux, with GNOME Shell 45 to 51, without
Odoo. The base is the GNOME extension, its schemas and its translations,
enabled: it needs no device access and no venv. The Stream Deck level adds
what the deck programs need, and installs the base too when it is missing.
Both run as your user and call `sudo` only for the system packages and the
udev rule.

<!-- [fr] -->
# Guide d'installation

ERPLibre Home s'installe en deux niveaux, sur Debian, Ubuntu, Fedora,
AlmaLinux, Rocky Linux, openSUSE et Arch Linux, avec GNOME Shell 45 à 51,
sans Odoo. La base est l'extension GNOME, ses schémas et ses traductions,
activée : elle ne demande ni accès au périphérique ni venv. Le niveau Stream
Deck ajoute ce dont les programmes du deck ont besoin, et installe aussi la
base quand elle manque. Les deux tournent sous ton compte et n'appellent
`sudo` que pour les paquets système et la règle udev.

<!-- [end] -->
<!-- [common] -->
```
./script/install/install_erplibre_home.sh
./script/install/install_erplibre_home.sh --stream-deck
```

<!-- [end] -->
<!-- [en] -->
Run them from the checkout. The first command installs the base: the system
packages of the base, `make` among them, then it links the GNOME extension
into `~/.local/share/gnome-shell/extensions/`, compiles its schemas and its
translations (with `msgfmt`), and enables it. The second one, for a
workstation with a Stream Deck, adds the Stream Deck packages, writes the
udev rule, creates `.venv.streamdeck` from
`script/stream_deck/requirements.txt`, and clones the games (see below).
Then log out and back in: under
Wayland, GNOME Shell loads a new extension only at session start. A second
run changes nothing. Without the Stream Deck level, the extension's
`device` and `controller` indicators say that ERPLibre Home Stream Deck is
not installed and name `make erplibre_home_streamdeck_install`.

A fresh desktop does not always have `make`, so the script comes first. Once
the base is installed, `make erplibre_home_install` and
`make erplibre_home_streamdeck_install` run the same two commands. The
script takes these options:

<!-- [fr] -->
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

<!-- [end] -->
<!-- [en] -->
| Option | Effect |
|---|---|
| `--stream-deck` | add the Stream Deck level: USB packages, udev rule, `.venv.streamdeck`; the base installs too when missing |
| `--no-enable` | install without enabling the extension; a workstation where the former extension was enabled keeps that state under the new name |
| `--extension-only` | migrate from the former extension, link the extension and compile its schemas and translations only; no `sudo`, no system check; not with `--stream-deck` nor `--uninstall` |
| `--with-extras` | also install `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` and the Python `lz4` module, at either level, one package manager command each; a missing one is skipped with a warning |
| `--deck-program=tiler\|controller\|none` | with `--stream-deck`: the program the deck service runs (default `tiler`) |
| `--autostart` | with `--stream-deck`: enable the deck service at login and when a deck is plugged in (default: not enabled) |
| `--restart-after-game`, `--no-restart-after-game` | with `--stream-deck`: the deck service comes back after a game, or not (default: it does); the two exclude each other |
| `--uninstall` | remove everything: disable the extension, remove its link, the deck service and its settings, the udev rule and `.venv.streamdeck`; with `--stream-deck`, everything but the extension, which stays enabled; system packages and the games always stay |
| `--dry-run` | print what would be done, change nothing |

Exit code `0` means done, `2` an unsupported system (one line on stderr
starting with `UNSUPPORTED:`), `1` any other failure, including an
`--uninstall` that removed the rest but could not read or write
`enabled-extensions`.
`make erplibre_home_uninstall` runs `--uninstall`, and
`make erplibre_home_streamdeck_uninstall` runs `--uninstall --stream-deck`.

<!-- [fr] -->
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

<!-- [end] -->
<!-- [en] -->
### The games

The games and their gallery are a separate repository,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloned
at `script/stream_deck/games/` from the `main` branch that
`manifest/git_manifest_streamdeck_game.xml` names. `--stream-deck` clones
them when they are missing, moves a clone it made to the last commit of
`main` at each run, installs their `requirements.txt` in
`.venv.streamdeck`, and leaves anything else in `games/`, naming it in the
summary. `--uninstall` never removes them. Their saves live in
`$XDG_DATA_HOME/erplibre-home/streamdeck/save/` (`~/.local/share` when
`XDG_DATA_HOME` is unset). How Google Repo checkouts
get them, and how to change them, is in
[doc/streamdeck_game.md](../../doc/streamdeck_game.md).

A game file edited in the checkout before the games left ERPLibre blocks
the `git pull`: copy the edit elsewhere, `git checkout -- <file>`, pull,
then carry the edit over to the streamdeck_game repository.

Without the games, the deck program, the controller and the service work;
the TODO games menu, the gallery, `make streamdeck_<game>` and the hand-over
refuse with one line naming `make erplibre_home_streamdeck_install`.

<!-- [fr] -->
### Les jeux

Les jeux et leur galerie sont un dépôt à part,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloné
dans `script/stream_deck/games/` depuis la branche `main` que nomme
`manifest/git_manifest_streamdeck_game.xml`. `--stream-deck` les clone
quand ils manquent, amène un clone qu'il a fait au dernier commit de `main`
à chaque exécution, installe leur
`requirements.txt` dans `.venv.streamdeck`, et laisse tout autre contenu de
`games/` en le nommant dans le bilan. `--uninstall` ne les retire jamais.
Leurs sauvegardes vivent dans
`$XDG_DATA_HOME/erplibre-home/streamdeck/save/` (`~/.local/share` par
défaut). Comment un checkout géré
par Google Repo les reçoit, et comment les modifier, est
dans [doc/streamdeck_game.fr.md](../../doc/streamdeck_game.fr.md).

Un fichier de jeu modifié dans le checkout avant le départ des jeux bloque
le `git pull` : copie la modification ailleurs, `git checkout -- <fichier>`,
tire, puis reporte la modification dans le dépôt streamdeck_game.

Sans les jeux, le programme du deck, le contrôleur et le service
fonctionnent ; le menu des jeux de TODO, la galerie,
`make streamdeck_<jeu>` et la passation refusent, en une ligne qui nomme
`make erplibre_home_streamdeck_install`.

<!-- [end] -->
<!-- [en] -->
### System packages, for reference

The installer picks the column of your distribution family: the base rows
always, the Stream Deck rows with `--stream-deck`. On AlmaLinux and Rocky
Linux, `--stream-deck` first enables EPEL (`dnf install -y epel-release`),
where `wmctrl` comes from; the base does not touch EPEL.

<!-- [fr] -->
### Paquets système, pour référence

L'installateur prend la colonne de ta famille de distribution : les lignes
de la base toujours, celles du Stream Deck avec `--stream-deck`. Sur
AlmaLinux et Rocky Linux, `--stream-deck` active d'abord EPEL
(`dnf install -y epel-release`), d'où vient `wmctrl` ; la base ne touche
pas à EPEL.

<!-- [end] -->
<!-- [common] -->
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

<!-- [end] -->
<!-- [en] -->
### Device access: the udev rule

With `--stream-deck`, the installer writes
`/etc/udev/rules.d/70-streamdeck.rules`:

<!-- [fr] -->
### Accès au périphérique : la règle udev

Avec `--stream-deck`, l'installateur écrit
`/etc/udev/rules.d/70-streamdeck.rules` :

<!-- [end] -->
<!-- [common] -->
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0fd9", TAG+="systemd", ENV{SYSTEMD_ALIAS}="/sys/subsystem/erplibre/streamdeck"
```

<!-- [end] -->
<!-- [en] -->
`0fd9` is Elgato's USB vendor id, so the rule covers every Stream Deck model.
`uaccess` gives the user logged in at the seat access to the device, on every
distribution family; no group membership is needed, unlike the `plugdev`
group, which exists only on Debian and Ubuntu. The `70-` prefix orders the
rule before `73-seat-late.rules`, where `uaccess` is applied. The third
line names the plugged deck `sys-subsystem-erplibre-streamdeck.device` in
the user's systemd manager; the deck service is wanted by that unit, so an
enabled service starts when a deck is plugged in after login. To diagnose a
device that is not seen, or to add new hardware, watch the events while you
plug it in:

<!-- [fr] -->
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

<!-- [end] -->
<!-- [common] -->
```
sudo udevadm monitor
```

<!-- [end] -->
<!-- [en] -->
### The deck service

A Stream Deck is driven by one program at a time. With `--stream-deck`, the
installer writes the `systemd --user` unit
`~/.config/systemd/user/erplibre-home-streamdeck.service`, which runs that
program from this checkout, and its settings
`~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` honoured):

<!-- [fr] -->
### Le service du deck

Un Stream Deck est piloté par un seul programme à la fois. Avec
`--stream-deck`, l'installateur écrit l'unité `systemd --user`
`~/.config/systemd/user/erplibre-home-streamdeck.service`, qui lance ce
programme depuis ce dépôt, et ses réglages
`~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` respecté) :

<!-- [end] -->
<!-- [common] -->
```
DECK_PROGRAM=tiler
RESTART_AFTER_GAME=yes
```

<!-- [end] -->
<!-- [en] -->
`DECK_PROGRAM` is `tiler` (the package `script/stream_deck/erplibre_streamdeck`),
`controller` (`script/stream_deck/erplibre_controller.py`) or `none`. An
option given writes its key; an option left out keeps the value already in
the file, and the default applies only to a missing key, so a reinstall
keeps a program chosen in TODO. Any other line stays. The unit starts only
when a program is chosen, `.venv.streamdeck` exists, a deck is plugged in
and the graphical session is up; otherwise systemd skips it. Once started, the deck program
outlives its deck: unplugged, it writes one journal line, keeps the deck
lock and looks for a deck every 2 seconds; the deck plugged back in comes
up on the home screen. A deck found but refused at its opening (its device
node not accessible) writes one more line, naming the error. A deck that
vanishes again within 10 seconds of coming back is looked for half as
often each time, down to every 30 seconds. The installer never starts
it: the program needs the extension, which a fresh install loads at the
next login. With `--autostart` the unit is enabled and starts at login, or
when a deck is plugged in later.
Without a reachable user manager (an install over ssh with no session), the
summary names the command to run after the next login.

`GAMES=on|off` turns the Stream Deck game library on or off. `on`, or no
`GAMES` line, enables it; `off` disables it; any other value disables it
too and TODO › Stream Deck › Diagnosis names it. With the games off, the
TODO games menu, the gallery, `make streamdeck_<game>` and the hand-over
refuse to start a game and say how to enable them; the deck program, the
controller and the service are never affected. Set it from
TODO › Stream Deck › Games on/off, or by hand in this file.

`DECK_PLUGINS_OFF=<id>,<id>` lists the deck program plugins that are not
loaded (empty or absent: all load). Set it from TODO › Stream Deck ›
Plugins on/off, or by hand in this file; TODO › Stream Deck › Diagnosis
names an id that matches no plugin. User plugins live in
`$XDG_CONFIG_HOME/erplibre-home/deck-plugins/`. `python
script/stream_deck/erplibre_streamdeck --list-plugins` prints each plugin
the loader finds and its status, without opening the deck.

`DECK_SESSION_REFRESH_SEC=<seconds>` sets how often the Claude and mpv
session pages refresh: a number from 0.5 to 60, 1 when absent. A value that
is not a number, or out of range, gives 1, and TODO › Stream Deck ›
Diagnosis names it. Set it from TODO › Stream Deck › [13] Session refresh
(which offers to restart the deck service), or by hand in this file.

Games take the deck over: TODO's games menu and the gallery run each game
through `script/install/erplibre_home_handover.sh`, which stops the service,
runs the game, and starts the service again when the game ends, unless
`RESTART_AFTER_GAME=no`. The deck has a lock,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock`: the window tiler and the
controller take it, and the hand-over takes it as `game` and passes it to
the game, so it stays held while any process of the game runs. A second
holder exits with code 2 and names the program and PID that hold the deck,
so the service, or **Start deck program** in the panel, stays down while a
game runs. Inside a game, one deck program runs at a time: a second one
exits with code 2 and names the first. To free the deck, close the game.
As a last resort, TODO's Stream Deck diagnosis names every process that
holds the lock, the whole game, for one `kill`; a `kill` on the PID the
lock names also reaches every process of the game. A game started by `make streamdeck_<game>` skips the
hand-over and takes no lock. `systemctl --user` controls the service:

<!-- [fr] -->
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

<!-- [end] -->
<!-- [common] -->
```
systemctl --user status erplibre-home-streamdeck.service
systemctl --user enable erplibre-home-streamdeck.service
journalctl --user -u erplibre-home-streamdeck.service -f
```

<!-- [end] -->
<!-- [en] -->
The installer, TODO and the extension find the unit and the settings
under `$XDG_CONFIG_HOME`; the user manager and the service read their own
environment. Set `XDG_CONFIG_HOME` in `~/.config/environment.d/*.conf`,
which both the session and the user manager read, not only in the shell's
rc file: otherwise the unit is written where systemd does not look, and the
service reads its default settings instead of the saved ones.

<!-- [fr] -->
L'installateur, TODO et l'extension trouvent l'unité et les réglages sous
`$XDG_CONFIG_HOME` ; le gestionnaire de l'utilisateur et le service lisent
leur propre environnement. Poser `XDG_CONFIG_HOME` dans
`~/.config/environment.d/*.conf`, que lisent la session et le gestionnaire
de l'utilisateur, et pas seulement dans le fichier rc du shell : sinon
l'unité s'écrit là où systemd ne regarde pas, et le service lit ses
réglages par défaut au lieu de ceux enregistrés.

<!-- [end] -->
<!-- [en] -->
TODO's **Execute › Stream Deck** menu gathers the games, both local
installs, the service, the deck program, autostart, a status view, a
diagnosis that names the command fixing each problem, both uninstalls, and
the extension's reload and preferences. Its Stream Deck install asks for
the program, autostart, the restart after a game and the optional tools,
the program and the restart defaulting to the current settings, then
prints the installer command before running it.

<!-- [fr] -->
Le menu **Exécution › Stream Deck** de TODO réunit les jeux, les deux
installations locales, le service, le programme du deck, le démarrage
automatique, un état, un diagnostic qui nomme la commande corrigeant chaque
problème, les deux désinstallations, et le rechargement et les préférences
de l'extension. Son installation Stream Deck demande le programme, le
démarrage automatique, la relance après un jeu et les outils facultatifs,
le programme et la relance proposant par défaut les réglages en place, puis
affiche la commande de l'installateur avant de la lancer.

<!-- [end] -->

<!-- [en] -->
## mpv film launcher — yt-dlp backend
<!-- [fr] -->
## Lecteur film mpv — backend yt-dlp
<!-- [end] -->

<!-- [en] -->
The film indicator's `mpv` launcher passes URLs to mpv, which
delegates stream extraction to a `youtube-dl` backend. Legacy
`youtube-dl` is unmaintained on Debian 13 / Ubuntu 24.04+; install
`yt-dlp` and the extension's
`--script-opts=ytdl_hook-ytdl_path=yt-dlp` arg picks it up
automatically — no per-user `mpv.conf` needed.
<!-- [fr] -->
Le lanceur `mpv` de l'indicateur film passe les URL à mpv, qui
délègue l'extraction du flux à un backend `youtube-dl`. Le
`youtube-dl` historique n'est plus maintenu sur Debian 13 /
Ubuntu 24.04+ ; installe `yt-dlp` et l'extension transmet
`--script-opts=ytdl_hook-ytdl_path=yt-dlp` automatiquement — pas
besoin de `mpv.conf` per-user.
<!-- [end] -->

<!-- [common] -->
```
sudo apt install -y mpv yt-dlp
# Verify:
yt-dlp --version
```
<!-- [end] -->

<!-- [en] -->
Errors like "youtube-dl failed: not found" surface in the prefs
Log page when yt-dlp is missing.
<!-- [fr] -->
Les erreurs du type « youtube-dl failed: not found » apparaissent
dans l'onglet Log des préférences quand yt-dlp manque.
<!-- [end] -->

<!-- [en] -->
### Import YouTube tabs from Firefox

The prefs Film page has an "Import" button that scans every running
Firefox profile's open tabs and adds any YouTube URL as a new film
entry. The helper reads `recovery.jsonlz4` from each profile so it
needs Mozilla's lz4 codec:
<!-- [fr] -->
### Importer les onglets YouTube depuis Firefox

L'onglet Film des préférences expose un bouton « Import » qui scanne
les onglets ouverts de chaque profil Firefox et ajoute toute URL
YouTube comme nouvelle entrée film. Le helper lit
`recovery.jsonlz4` de chaque profil et nécessite le codec lz4 de
Mozilla :
<!-- [end] -->

<!-- [common] -->
```
sudo apt install -y python3-lz4
```
<!-- [end] -->

<!-- [en] -->
### mpv keyboard shortcuts (default bindings)
<!-- [fr] -->
### Raccourcis clavier mpv (bindings par défaut)
<!-- [end] -->

<!-- [common] -->
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
<!-- [end] -->

<!-- [en] -->
The film launcher passes `--save-position-on-quit=yes`, so quitting
mpv (any of the keys above, or closing the window) writes
`start=<seconds>` to `~/.config/mpv/watch_later/<MD5_OF_URL>`. The
extension reads that file when mpv exits and updates the entry's
`position` field — the next launch (mpv, browser or VLC) honours
that timestamp.
<!-- [fr] -->
Le lanceur film passe `--save-position-on-quit=yes` ; quitter mpv
(une des touches ci-dessus, ou fermer la fenêtre) écrit
`start=<secondes>` dans `~/.config/mpv/watch_later/<MD5_DE_URL>`.
L'extension relit ce fichier à la sortie de mpv et met à jour le
champ `position` de l'entrée — le prochain lancement (mpv, browser
ou VLC) honore ce timestamp.
<!-- [end] -->

<!-- [en] -->
## Auto-accept Claude prompts (Wayland)
<!-- [fr] -->
## Auto-accepter les invites Claude (Wayland)
<!-- [end] -->

<!-- [en] -->
The pencil indicator's "Accept response" action and the deck's red
session button synthesise an Enter keystroke into the focused Claude
terminal so a `Notification` permission prompt can be cleared without
leaving the launcher. The keystroke is generated **inside the GNOME
extension** through Clutter's virtual input device — no external
helper is needed and no group/permission change is required.
<!-- [fr] -->
L'action « Accept response » de l'indicateur crayon et le bouton
rouge sur le deck synthétisent une frappe Entrée dans le terminal
Claude focalisé pour acquitter un `Notification` sans quitter le
lanceur. La frappe est générée **directement par l'extension GNOME**
via le périphérique d'entrée virtuel de Clutter — aucun outil
externe n'est requis et aucun changement de groupe n'est nécessaire.
<!-- [end] -->

<!-- [en] -->
External tools like `wtype` (which requires `zwp_virtual_keyboard_v1`,
not exposed to arbitrary clients by Mutter) or `ydotool` (which is
not packaged on Debian 13) are therefore **not** prerequisites.
<!-- [fr] -->
Les outils externes comme `wtype` (qui requiert
`zwp_virtual_keyboard_v1`, non exposé aux clients arbitraires par
Mutter) ou `ydotool` (non packagé sur Debian 13) ne sont **pas**
des prérequis.
<!-- [end] -->

<!-- [en] -->
## ERPLibre Home GNOME extension hooks
<!-- [fr] -->
## Hooks de l'extension GNOME ERPLibre Home
<!-- [end] -->

<!-- [en] -->
The pencil badge needs Claude Code to write a small JSON state file
on every session event. Wire the hook (idempotent, safe to re-run):
<!-- [fr] -->
La pastille du crayon a besoin que Claude Code écrive un petit
fichier JSON d'état à chaque événement de session. Branche le hook
(idempotent, peut être relancé) :
<!-- [end] -->

<!-- [common] -->
```
make claude_install_hooks
```
<!-- [end] -->

<!-- [en] -->
Run `make claude_uninstall_hooks` to remove. Existing Claude
sessions reload `~/.claude/settings.json` only at SessionStart, so
restart any open `claude` after the install for the badge to start
tracking them.
<!-- [fr] -->
`make claude_uninstall_hooks` pour retirer. Les sessions Claude en
cours ne relisent `~/.claude/settings.json` qu'au SessionStart ;
relance les `claude` ouverts pour que la pastille les suive.
<!-- [end] -->

