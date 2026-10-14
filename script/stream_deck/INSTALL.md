
# Guide to install

ERPLibre Home installs in two levels, on Debian, Ubuntu, Fedora, AlmaLinux,
Rocky Linux, openSUSE and Arch Linux, with GNOME Shell 45 to 51, without
Odoo. The base is the GNOME extension, its schemas and its translations,
enabled: it needs no device access and no venv. The Stream Deck level adds
what the deck programs need, and installs the base too when it is missing.
Both run as your user and call `sudo` only for the system packages and the
udev rule.

```
./script/install/install_erplibre_home.sh
./script/install/install_erplibre_home.sh --stream-deck
```

Run them from the checkout. The first command installs the base: the system
packages of the base, `make` among them, then it links the GNOME extension
into `~/.local/share/gnome-shell/extensions/`, compiles its schemas and its
translations (with `msgfmt`), and enables it. The second one, for a
workstation with a Stream Deck, adds the Stream Deck packages, writes the
udev rule and creates `.venv.streamdeck` from
`script/stream_deck/requirements.txt`. Then log out and back in: under
Wayland, GNOME Shell loads a new extension only at session start. A second
run changes nothing. Without the Stream Deck level, the extension's
`device` and `controller` indicators say that ERPLibre Home Stream Deck is
not installed and name `make erplibre_home_streamdeck_install`.

A fresh desktop does not always have `make`, so the script comes first. Once
the base is installed, `make erplibre_home_install` and
`make erplibre_home_streamdeck_install` run the same two commands. The
script takes these options:

| Option | Effect |
|---|---|
| `--stream-deck` | add the Stream Deck level: USB packages, udev rule, `.venv.streamdeck`; the base installs too when missing |
| `--no-enable` | install without enabling the extension; a workstation where the former extension was enabled keeps that state under the new name |
| `--extension-only` | migrate from the former extension, link the extension and compile its schemas and translations only; no `sudo`, no system check; not with `--stream-deck` nor `--uninstall` |
| `--with-extras` | also install `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` and the Python `lz4` module, at either level, one package manager command each; a missing one is skipped with a warning |
| `--deck-program=tiler\|controller\|none` | with `--stream-deck`: the program the deck service runs (default `tiler`) |
| `--autostart` | with `--stream-deck`: enable the deck service at login (default: not enabled) |
| `--restart-after-game`, `--no-restart-after-game` | with `--stream-deck`: the deck service comes back after a game, or not (default: it does); the two exclude each other |
| `--uninstall` | remove everything: disable the extension, remove its link, the deck service and its settings, the udev rule and `.venv.streamdeck`; with `--stream-deck`, everything but the extension, which stays enabled; system packages always stay |
| `--dry-run` | print what would be done, change nothing |

Exit code `0` means done, `2` an unsupported system (one line on stderr
starting with `UNSUPPORTED:`), `1` any other failure, including an
`--uninstall` that removed the rest but could not read or write
`enabled-extensions`.
`make erplibre_home_uninstall` runs `--uninstall`, and
`make erplibre_home_streamdeck_uninstall` runs `--uninstall --stream-deck`.

### System packages, for reference

The installer picks the column of your distribution family: the base rows
always, the Stream Deck rows with `--stream-deck`. On AlmaLinux and Rocky
Linux, `--stream-deck` first enables EPEL (`dnf install -y epel-release`),
where `wmctrl` comes from; the base does not touch EPEL.

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
```

`0fd9` is Elgato's USB vendor id, so the rule covers every Stream Deck model.
`uaccess` gives the user logged in at the seat access to the device, on every
distribution family; no group membership is needed, unlike the `plugdev`
group, which exists only on Debian and Ubuntu. The `70-` prefix orders the
rule before `73-seat-late.rules`, where `uaccess` is applied. To diagnose a
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

`DECK_PROGRAM` is `tiler` (`script/stream_deck/game_tiler.py`),
`controller` (`script/stream_deck/erplibre_controller.py`) or `none`. An
option given writes its key; an option left out keeps the value already in
the file, and the default applies only to a missing key, so a reinstall
keeps a program chosen in TODO. Any other line stays. The unit starts only
when a program is chosen, `.venv.streamdeck` exists and a deck is plugged
in; otherwise systemd skips it. The installer never starts
it: the program needs the extension, which a fresh install loads at the
next login. With `--autostart` the unit is enabled and starts at login.
Without a reachable user manager (an install over ssh with no session), the
summary names the command to run after the next login.

Games take the deck over: TODO's games menu and the gallery run each game
through `script/install/erplibre_home_handover.sh`, which stops the service,
runs the game, and starts the service again when the game ends, unless
`RESTART_AFTER_GAME=no`. Each deck program takes a lock,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock`; a second one exits with code 2
and names the program and PID that hold the deck. `systemctl --user`
controls the service:

```
systemctl --user status erplibre-home-streamdeck.service
systemctl --user enable erplibre-home-streamdeck.service
journalctl --user -u erplibre-home-streamdeck.service -f
```

TODO's **Execute › Stream Deck** menu gathers the games, both local
installs, the service, the deck program, autostart, a status view, a
diagnosis that names the command fixing each problem, both uninstalls, and
the extension's reload and preferences. Its Stream Deck install asks for
the program, autostart, the restart after a game and the optional tools,
then prints the installer command before running it.

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