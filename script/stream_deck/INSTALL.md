
# Guide to install

ERPLibre Home installs in two levels, on Debian, Ubuntu, Fedora, AlmaLinux,
Rocky Linux, openSUSE and Arch Linux, with GNOME Shell 45 to 51, without
Odoo. The base is the GNOME extension, its schemas and its translations,
enabled: it needs no device access and no venv. The Stream Deck level adds
what the deck programs need, and installs the base too when it is missing.
Both run as your user and call `sudo` only for the system packages and the
udev rule.

```
./script/install/install_erplibre.sh
./script/install/install_erplibre_home.sh
./script/install/install_erplibre_home.sh --stream-deck
```

Run them from the checkout. The first command lays down `.venv.erplibre`,
ERPLibre's tool venv, which carries Google Repo's `repo`: the installer
takes it from there and stops, naming that command, when the venv is
missing. The second command installs the base: Google Repo brings the GNOME
extension, a repository of its own, into
`script/gnome-extension/erplibre_home/` (see
[the extension in ERPLibre](../../doc/erplibre_home_gnome_extension.md)),
then the installer installs the system packages of the base, `make` among
them, links the extension into `~/.local/share/gnome-shell/extensions/`,
compiles its schemas and its translations (with `msgfmt`), and enables it.
The third one, for a workstation with a Stream Deck, adds the Stream Deck
packages, writes the udev rule, has Google Repo bring the deck program, a
repository of its own, into `script/stream_deck/deck/` (see
[the deck program in ERPLibre](../../doc/erplibre_streamdeck_deck.md)),
and the games (see below), then creates `.venv.streamdeck` from the
`requirements.txt` of the deck program and of the games. Then log out and
back in: under Wayland, GNOME Shell loads a new extension only at session
start. Without the Stream Deck level, the extension's `device` and
`controller` indicators say that ERPLibre Home Stream Deck is not installed
and name `make erplibre_home_streamdeck_install`.

Each run adds the extension, and with `--stream-deck` the deck program and
the games, to `.repo/local_manifests/erplibre_manifest.xml`, removing
nothing from it, and runs `repo sync` on each path alone: each follows the
last commit of its `main`, and a later run changes nothing else. `git` is
required. Laying down `.venv.erplibre/bin/repo` and the first `repo init`
of a checkout reach Google's hosts for `repo` itself
(`storage.googleapis.com`, `gerrit.googlesource.com`); every sync reaches
GitHub for these projects. A directory there that is not a
repo checkout, a plain git clone or a copy, is moved aside whole to
`<dir>.avant-repo-<date>` beside it, named in the summary, and put back
when the sync fails. On a repo checkout, a failed sync, offline for
instance, leaves the project as it is: the summary says "NOT updated" and
the install goes on. To change one of the projects, work on a branch that
`repo start <branch> <dir>` starts; a detached HEAD moves to `main` at the
next sync.

A fresh desktop does not always have `make`, so the script comes first. Once
the base is installed, `make erplibre_home_install` and
`make erplibre_home_streamdeck_install` run the same installer commands. The
script takes these options:

| Option | Effect |
|---|---|
| `--stream-deck` | add the Stream Deck level: USB packages, udev rule, the deck program, synced by Google Repo into `script/stream_deck/deck/`, `.venv.streamdeck`; the base installs too when missing |
| `--no-enable` | install without enabling the extension; a workstation where the former extension was enabled keeps that state under the new name |
| `--extension-only` | sync the extension by Google Repo, migrate from the former extension, link the extension and compile its schemas and translations only; no `sudo`, no system check; not with `--stream-deck` nor `--uninstall` |
| `--with-extras` | also install `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` and the Python `lz4` module, at either level, one package manager command each; a missing one is skipped with a warning |
| `--no-extras` | never ask about the optional tools and install none, for scripts; not with `--with-extras` |
| `--deck-program=tiler\|controller\|none` | with `--stream-deck`: the program the deck service runs (default `tiler`) |
| `--autostart` | with `--stream-deck`: enable the deck service at login and when a deck is plugged in (default: not enabled) |
| `--restart-after-game`, `--no-restart-after-game` | with `--stream-deck`: the deck service comes back after a game, or not (default: it does); the two exclude each other |
| `--uninstall` | remove everything: disable the extension, remove its link, the deck service and its settings, the udev rule and `.venv.streamdeck`; with `--stream-deck`, everything but the extension, which stays enabled; system packages, `.repo`, the local manifest and the checkouts of the extension, of the deck and of the games always stay |
| `--dry-run` | print what would be done, change nothing |

Without `--with-extras` or `--no-extras`, an install run from a terminal
lists the optional tools it cannot find, a command on `PATH` (`keepassxc`
or `keepassxc-cli` for KeePassXC) or the `lz4` module that `python3` cannot
import, prints the package manager command of each for the system, then
asks `Install the optional tools? (y/N)`. `y`, `yes`, `o` or `oui`
installs them as `--with-extras` does; any other answer, Enter alone
included, skips them. Nothing missing, nothing asked. A run without a
terminal (a VM, the long test, a pipe) never asks and installs no optional
tool. Under `--dry-run`, one `offer:` line per missing tool shows the
command the question would offer.

Exit code `0` means done, `2` an unsupported system (one line on stderr
starting with `UNSUPPORTED:`), `1` any other failure, including an
`--uninstall` that removed the rest but could not read or write
`enabled-extensions`.
`make erplibre_home_uninstall` runs `--uninstall`, and
`make erplibre_home_streamdeck_uninstall` runs `--uninstall --stream-deck`.

### The games

The games and their gallery are a separate repository,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), a Google
Repo project at `script/stream_deck/games/` on the `main` branch that
`manifest/git_manifest_streamdeck_game.xml` names. `--stream-deck` adds it
to the local manifest and syncs it like the deck program, then installs
their `requirements.txt` in `.venv.streamdeck`. A `games/` that is not a
repo checkout is set aside whole to `games.avant-repo-<date>`, the saves of
an older layout in its `save/` included. `--uninstall` never removes them.
Their saves live in `$XDG_DATA_HOME/erplibre-home/streamdeck/save/`
(`~/.local/share` when `XDG_DATA_HOME` is unset). How to change them is in
[doc/streamdeck_game.md](../../doc/streamdeck_game.md).

Without the games, the deck program, the controller and the service work;
the TODO games menu, the gallery, `make streamdeck_<game>` and the hand-over
refuse with one line naming `make erplibre_home_streamdeck_install`.

### System packages, for reference

The installer picks the column of your distribution family: the base rows
always, the Stream Deck rows with `--stream-deck`. On the RHEL family
other than Fedora (RHEL, CentOS Stream, AlmaLinux, Rocky Linux),
`--stream-deck` first enables EPEL (`dnf install -y epel-release`), where
`wmctrl` comes from; the base does not touch EPEL.

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

### Device access: the udev rule

With `--stream-deck`, the installer writes
`/etc/udev/rules.d/70-streamdeck.rules`:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0fd9", TAG+="systemd", ENV{SYSTEMD_ALIAS}="/sys/subsystem/erplibre/streamdeck"
```

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

```
sudo udevadm monitor
```

### The deck service

A Stream Deck is driven by one program at a time. With `--stream-deck`, the
installer writes the `systemd --user` unit
`~/.config/systemd/user/erplibre-home-streamdeck.service`, which runs that
program from this checkout, and its settings
`~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` honoured):

```
DECK_PROGRAM=tiler
RESTART_AFTER_GAME=yes
```

`DECK_PROGRAM` is `tiler` (the package `script/stream_deck/deck/erplibre_streamdeck`),
`controller` (`script/stream_deck/deck/erplibre_controller.py`) or `none`. An
option given writes its key; an option left out keeps the value already in
the file, and the default applies only to a missing key, so a reinstall
keeps a program chosen in TODO. Any other line stays. The unit starts only
when a program is chosen, `.venv.streamdeck` and the deck checkout exist, a
deck is plugged in
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
too and TODO › ERPLibre Home › Diagnosis names it. With the games off, the
TODO games menu, the gallery, `make streamdeck_<game>` and the hand-over
refuse to start a game and say how to enable them; the deck program, the
controller and the service are never affected. Set it from
TODO › ERPLibre Home › Games on/off, or by hand in this file.

`DECK_PLUGINS_OFF=<id>,<id>` lists the deck program plugins that are not
loaded (empty or absent: all load). Set it from TODO › ERPLibre Home ›
Plugins on/off, or by hand in this file; TODO › ERPLibre Home › Diagnosis
names an id that matches no plugin. User plugins live in
`$XDG_CONFIG_HOME/erplibre-home/deck-plugins/`. `python
script/stream_deck/deck/erplibre_streamdeck --list-plugins` prints each plugin
the loader finds and its status, without opening the deck.

`DECK_SESSION_REFRESH_SEC=<seconds>` sets how often the Claude and mpv
session pages refresh: a number from 0.5 to 60, 1 when absent. A value that
is not a number, or out of range, gives 1, and TODO › ERPLibre Home ›
Diagnosis names it. Set it from TODO › ERPLibre Home › Session refresh
(which offers to restart the deck service), or by hand in this file.

Games take the deck over: TODO's games menu, the gallery and
`make streamdeck_<game>` run each game through
`script/install/erplibre_home_streamdeck_handover.sh`, which stops
the service, runs the game, and starts the service again when the game
ends, unless `RESTART_AFTER_GAME=no`. The deck has a lock,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock`: the window tiler and the
controller take it, and the hand-over takes it as `game` and passes it to
the game, so it stays held while any process of the game runs. A second
holder exits with code 2 and names the program and PID that hold the deck,
so the service, or **Start deck program** in the panel, stays down while a
game runs. Inside a game, one deck program runs at a time: a second one
exits with code 2 and names the first. To free the deck, close the game.
As a last resort, TODO's Stream Deck diagnosis names every process that
holds the lock, the whole game, for one `kill`; a `kill` on the PID the
lock names also reaches every process of the game. `systemctl --user`
controls the service:

```
systemctl --user status erplibre-home-streamdeck.service
systemctl --user enable erplibre-home-streamdeck.service
journalctl --user -u erplibre-home-streamdeck.service -f
```

The installer, TODO and the extension find the unit and the settings
under `$XDG_CONFIG_HOME`; the user manager and the service read their own
environment. Set `XDG_CONFIG_HOME` in `~/.config/environment.d/*.conf`,
which both the session and the user manager read, not only in the shell's
rc file: otherwise the unit is written where systemd does not look, and the
service reads its default settings instead of the saved ones.

TODO's **Execute › ERPLibre Home** menu has five sections. GNOME
extension: its local install alone, its reload and preferences, and the
uninstall of everything. Stream Deck (office tool): its install, which adds
the extension when missing, the uninstall of the Stream Deck level alone,
and the service. Deck settings: program, autostart, plugins and session
refresh. State: a status view and a diagnosis that names the command
fixing each problem. Games come last. The Stream Deck install asks for
the program, autostart and the restart after a game, the program and the
restart defaulting to the current settings, then prints the installer
command before running it; the installer itself asks about the missing
optional tools, with their command.

## mpv film launcher — yt-dlp backend
The film indicator's `mpv` launcher passes URLs to mpv, which
delegates stream extraction to a `youtube-dl` backend. Legacy
`youtube-dl` is unmaintained on Debian 13 / Ubuntu 24.04+; install
`yt-dlp` and the extension's
`--script-opts=ytdl_hook-ytdl_path=yt-dlp` arg picks it up
automatically — no per-user `mpv.conf` needed.
```
sudo apt install -y mpv yt-dlp
# Verify:
yt-dlp --version
```
Errors like "youtube-dl failed: not found" surface in the prefs
Log page when yt-dlp is missing.
### Import YouTube tabs from Firefox

The prefs Film page has an "Import" button that scans every running
Firefox profile's open tabs and adds any YouTube URL as a new film
entry. The helper reads `recovery.jsonlz4` from each profile so it
needs Mozilla's lz4 codec:
```
sudo apt install -y python3-lz4
```
### mpv keyboard shortcuts (default bindings)
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
The film launcher passes `--save-position-on-quit=yes`, so quitting
mpv (any of the keys above, or closing the window) writes
`start=<seconds>` to `~/.config/mpv/watch_later/<MD5_OF_URL>`. The
extension reads that file when mpv exits and updates the entry's
`position` field — the next launch (mpv, browser or VLC) honours
that timestamp.
## Auto-accept Claude prompts (Wayland)
The pencil indicator's "Accept response" action and the deck's red
session button synthesise an Enter keystroke into the focused Claude
terminal so a `Notification` permission prompt can be cleared without
leaving the launcher. The keystroke is generated **inside the GNOME
extension** through Clutter's virtual input device — no external
helper is needed and no group/permission change is required.
External tools like `wtype` (which requires `zwp_virtual_keyboard_v1`,
not exposed to arbitrary clients by Mutter) or `ydotool` (which is
not packaged on Debian 13) are therefore **not** prerequisites.
## ERPLibre Home GNOME extension hooks
The pencil badge needs Claude Code to write a small JSON state file
on every session event. Wire the hook (idempotent, safe to re-run):
```
make claude_install_hooks
```
Run `make claude_uninstall_hooks` to remove. Existing Claude
sessions reload `~/.claude/settings.json` only at SessionStart, so
restart any open `claude` after the install for the badge to start
tracking them.