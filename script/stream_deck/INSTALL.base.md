<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Guide to install

https://github.com/jamesridgway/devdeck/wiki/Installation#pre-requisite-libusb-hidapi-backend

<!-- [fr] -->
# Guide d'installation

https://github.com/jamesridgway/devdeck/wiki/Installation#pre-requisite-libusb-hidapi-backend

<!-- [common] -->
```
# For Ubuntu

sudo apt install -y libudev-dev libusb-1.0-0-dev libhidapi-libusb0

# Add your user to plugdev group
sudo usermod -a -G plugdev `whoami`

# udev rule to allow all users non-root access to Elgato StreamDeck devices:
sudo tee /etc/udev/rules.d/10-streamdeck.rules << EOF
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0060", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0063", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="006c", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="006d", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0080", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0084", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="008f", MODE:="660", GROUP="plugdev"
EOF

# Reload udev rules to ensure the new permissions take effect
sudo udevadm control --reload-rules
```

<!-- [en] -->
To diagnostic or add new material, check with

<!-- [fr] -->
Pour diagnostiquer ou ajouter du nouveau matériel, vérifier avec

<!-- [common] -->
```sudo udevadm monitor```

```
# For Ubuntu to manage windows

sudo apt install -y wmctrl
```

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
## Stream Deck Tiler GNOME extension hooks
<!-- [fr] -->
## Hooks de l'extension GNOME Stream Deck Tiler
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

