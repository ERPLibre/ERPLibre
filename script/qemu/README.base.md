<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# QEMU/KVM — Linux VM deployment

`deploy_qemu.py` deploys a Linux VM (libvirt/KVM) from an official cloud
image, using `qemu-img` + `cloud-init` + `virt-install`. Pick the
distribution with `--distro` (`ubuntu` default, plus `debian`, `fedora`,
`almalinux`, `rocky`, `opensuse`, `arch`, `nixos` and `proxmox`) and the
release with `--version`; run `--list-images` to see the full catalogue with
minimum specs. It:

1. **Downloads the cloud image by itself** (cached, no double download).
2. Converts it to a dedicated qcow2 working disk and resizes it.
3. Generates `user-data` / `meta-data` and builds the `seed.iso` (cloud-init).
4. Runs `virt-install` importing the disk + the seed as a CD-ROM.
5. Waits for the DHCP lease and prints the SSH command.

<!-- [fr] -->
# QEMU/KVM — Déploiement de VM Linux

`deploy_qemu.py` déploie une VM Linux (libvirt/KVM) à partir d'une image
cloud officielle, via `qemu-img` + `cloud-init` + `virt-install`. Choisissez
la distribution avec `--distro` (`ubuntu` par défaut, puis `debian`,
`fedora`, `almalinux`, `rocky`, `opensuse`, `arch`, `nixos` et `proxmox`) et
la version avec `--version` ; `--list-images` affiche tout le catalogue avec
les specs minimales. Il :

1. **Télécharge lui-même l'image cloud** (mise en cache, sans double
   téléchargement).
2. La convertit en un disque de travail qcow2 dédié et le redimensionne.
3. Génère `user-data` / `meta-data` et construit le `seed.iso` (cloud-init).
4. Lance `virt-install` en important le disque + le seed en CD-ROM.
5. Attend le bail DHCP et affiche la commande SSH.

<!-- [en] -->
## Prerequisites

- A host with KVM available (bare-metal or nested virtualization enabled).
- `sudo` rights (the deployment writes to `/var/lib/libvirt/images` and drives
  libvirt).

## Installation

The script **auto-installs the missing pieces it needs**: on first run it
detects your package manager (apt / dnf / pacman / zypper / brew), lists the
missing components (the client tools, **plus the libvirt daemon and the QEMU
system emulator**), asks for confirmation, installs them with `sudo`, then
enables and starts `libvirtd`. Use `-y` to accept automatically or
`--no-install-deps` to disable this behaviour.

To install everything manually on Ubuntu/Debian (recommended full KVM stack):

<!-- [fr] -->
## Prérequis

- Un hôte disposant de KVM (bare-metal ou virtualisation imbriquée activée).
- Les droits `sudo` (le déploiement écrit dans `/var/lib/libvirt/images` et
  pilote libvirt).

## Installation

Le script **installe automatiquement les composants manquants** : au premier
lancement, il détecte votre gestionnaire de paquets (apt / dnf / pacman /
zypper / brew), liste les composants absents (les outils clients, **ainsi que
le démon libvirt et l'émulateur QEMU système**), demande confirmation, les
installe avec `sudo`, puis active et démarre `libvirtd`. Utilisez `-y` pour
accepter automatiquement ou `--no-install-deps` pour désactiver ce
comportement.

Pour tout installer manuellement sur Ubuntu/Debian (pile KVM complète
recommandée) :

<!-- [common] -->
```bash
sudo apt install qemu-utils virtinst libvirt-clients cloud-image-utils \
    libvirt-daemon-system qemu-system-x86
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt,kvm "$USER"   # re-login / reconnectez-vous
```

<!-- [en] -->
`libvirt-daemon-system` provides the `libvirtd` daemon (and the
`/var/run/libvirt/libvirt-sock` socket) and `qemu-system-x86` the emulator —
without them `virt-install` fails with *"Failed to connect socket to
'/var/run/libvirt/libvirt-sock'"*. The script installs and starts them for
you; this manual command is only needed if you prefer to prepare the host
yourself or run with `--no-install-deps`.

## Usage

Simplest form — the image is downloaded automatically (path derived from
`--version`, cached in `/var/lib/libvirt/images/iso`):

<!-- [fr] -->
`libvirt-daemon-system` fournit le démon `libvirtd` (et le socket
`/var/run/libvirt/libvirt-sock`) et `qemu-system-x86` l'émulateur — sans eux
`virt-install` échoue avec *« Failed to connect socket to
'/var/run/libvirt/libvirt-sock' »*. Le script les installe et les démarre pour
vous ; cette commande manuelle n'est utile que si vous préférez préparer
l'hôte vous-même ou utiliser `--no-install-deps`.

## Utilisation

Forme la plus simple — l'image est téléchargée automatiquement (chemin déduit
de `--version`, mis en cache dans `/var/lib/libvirt/images/iso`) :

<!-- [common] -->
```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub
```

<!-- [en] -->
Download (and verify) an image without creating a VM:

<!-- [fr] -->
Télécharger (et vérifier) une image sans créer de VM :

<!-- [common] -->
```bash
sudo ./script/qemu/deploy_qemu.py --download-only --version 24.04 --verify
```

<!-- [en] -->
Deploy with an interactive password instead of an SSH key:

<!-- [fr] -->
Déployer avec un mot de passe interactif au lieu d'une clé SSH :

<!-- [common] -->
```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 --ask-password
```

<!-- [en] -->
Larger VM (8 GB RAM, 8 vCPU, 120 GB disk), overwriting an existing disk:

<!-- [fr] -->
VM plus grande (8 Go RAM, 8 vCPU, disque 120 Go), en écrasant un disque
existant :

<!-- [common] -->
```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --memory 8192 --vcpus 8 --disk-size 120G --ask-password --force
```

<!-- [en] -->
Preview what would happen, without doing anything (no sudo, no download):

<!-- [fr] -->
Prévisualiser ce qui serait fait, sans rien exécuter (sans sudo, sans
téléchargement) :

<!-- [common] -->
```bash
./script/qemu/deploy_qemu.py --name test-vm --version 24.04 --dry-run
```

<!-- [en] -->
Non-interactive deployment (accept dependency install automatically):

<!-- [fr] -->
Déploiement non interactif (accepte automatiquement l'installation des
dépendances) :

<!-- [common] -->
```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub -y
```

<!-- [en] -->
Catalog, per architecture (`deploy_qemu.py` is the source of truth):

| Distro | Versions | amd64 | arm64 | s390x |
|---|---|:-:|:-:|:-:|
| ubuntu | `24.04` (default), `25.10`, `26.04` | ✔ | ✔ | ✔ |
| debian | `12` (default), `13` | ✔ | ✔ | ✔ (debian-installer) |
| fedora | `44` (default), `45` | ✔ | ✔ | ✔ |
| almalinux | `9` (default), `10` | ✔ | ✔ | ✔ |
| rocky | `9`, `10` (default) | ✔ | ✔ | ✔ |
| opensuse | `16.0` (default), `tumbleweed` | ✔ | ✔ | ✔ |
| arch | `latest` | ✔ | — | — |
| proxmox | `9` | ✔ | ✔ | — |

Fedora publishes s390x on a separate tree (`fedora-secondary`), so its
s390x versions are listed by hand in `ARCH_ONLY_VERSIONS`.

Debian ships two cloud image variants. `genericcloud` runs a kernel built
without any display driver and without USB, so a graphical VM (`--desktop`)
or one that receives a USB device (`--usb-hostdev`, `--spice-usbredir`)
downloads `generic`, whose kernel drives the virtual screen and the USB bus.
Debian 13 publishes only
`generic`; Debian 12 keeps `genericcloud` for servers. Each variant has its
own cache file.

`proxmox` is Proxmox VE, and it deserves a word: it publishes **no cloud
image** — its ISO is an installer that formats the disk. So the deployment
does what upstream itself documents for every other case, *Proxmox VE on
Debian*: it downloads the **Debian trixie** cloud image (the very same file, so
a Debian 13 and a Proxmox deployment share one download) and the `pve`
packages turn it into a hypervisor — Proxmox kernel, web UI on `:8006`.

The version number is Proxmox's, not Debian's: PVE 9 = trixie. arm64 has been
official since PVE 9 (the upstream `trixie` Release announces `amd64 arm64`,
and the arm64 index really serves `proxmox-ve`). s390x is absent and will stay
so by this route: the repository has no `binary-s390x` index at all — the
catalog says it before the deployment rather than failing at the first `apt`.

`opensuse` covers two distinct products, not two versions of one. Leap `16.0`
is numbered and stable (SLE base) and is the default. `tumbleweed` is the
rolling one, kept as a bellwether for breakage to come: its snapshot drift is
real, and it demands a full `zypper dup` before anything can be installed.

Both ship a qpdf above the pikepdf threshold, so the half-hour qpdf build
never runs there — which matters under s390x emulation.

Provide an explicit image path as a positional argument to override the
automatic download location.

Ubuntu `20.04` and `22.04` were **dropped on every architecture**: pikepdf
needs qpdf 12.2, whose build requires C++20, and focal ships GCC 9 — it does
not even publish `g++-10` for s390x. Python 3.8, node 10, cargo 0.67 and
OpenSSL 1.1.1 each had a workaround; the pile of them did not.

## After deployment

<!-- [fr] -->
Catalogue, par architecture (`deploy_qemu.py` fait autorité) :

| Distro | Versions | amd64 | arm64 | s390x |
|---|---|:-:|:-:|:-:|
| ubuntu | `24.04` (défaut), `25.10`, `26.04` | ✔ | ✔ | ✔ |
| debian | `12` (défaut), `13` | ✔ | ✔ | ✔ (debian-installer) |
| fedora | `44` (défaut), `45` | ✔ | ✔ | ✔ |
| almalinux | `9` (défaut), `10` | ✔ | ✔ | ✔ |
| rocky | `9`, `10` (défaut) | ✔ | ✔ | ✔ |
| opensuse | `16.0` (défaut), `tumbleweed` | ✔ | ✔ | ✔ |
| arch | `latest` | ✔ | — | — |
| proxmox | `9` | ✔ | ✔ | — |

Fedora publie s390x sur une arborescence à part (`fedora-secondary`) :
ses versions s390x sont donc tenues à la main dans `ARCH_ONLY_VERSIONS`.

Debian publie deux variantes d'image cloud. `genericcloud` porte un noyau
compilé sans aucun pilote d'affichage et sans USB : une VM graphique
(`--desktop`) ou qui reçoit un périphérique USB (`--usb-hostdev`,
`--spice-usbredir`) télécharge donc `generic`, dont le noyau pilote l'écran
virtuel et le bus USB. Debian 13 ne
publie que `generic` ; Debian 12 garde `genericcloud` pour les serveurs.
Chaque variante a son propre fichier en cache.

`opensuse` recouvre deux produits distincts, pas deux versions du même. Leap
`16.0` est numérotée et stable (base SLE) : c'est le défaut. `tumbleweed` est
la rolling, gardée comme banc d'essai des ruptures à venir — sa dérive
d'instantanés est réelle, et elle impose un `zypper dup` complet avant toute
installation.

Les deux livrent un qpdf au-dessus du seuil de pikepdf : la compilation de
qpdf, une demi-heure, ne s'y déclenche jamais — ce qui compte sous émulation
s390x.

`proxmox`, c'est Proxmox VE, et il mérite un mot : il ne publie **aucune image
cloud** — son ISO est un installateur qui formate le disque. Le déploiement
fait donc ce que l'amont documente lui-même pour tous les autres cas,
*Proxmox VE sur Debian* : il télécharge l'image cloud **Debian trixie** (le
même fichier, si bien qu'un déploiement Debian 13 et un Proxmox se partagent un
seul téléchargement) et les paquets `pve` en font un hyperviseur — noyau
Proxmox, interface web sur `:8006`.

Le numéro de version est celui de Proxmox, pas de Debian : PVE 9 = trixie.
arm64 est officiel depuis PVE 9 (le Release `trixie` de l'amont annonce
`amd64 arm64`, et l'index arm64 sert bien `proxmox-ve`). s390x est absent et le
restera par cette voie : le dépôt n'a aucun index `binary-s390x` — le catalogue
le dit avant le déploiement plutôt que d'échouer au premier `apt`.

Une VM Proxmox est un hyperviseur DANS une VM : ses propres invités demandent
la virtualisation imbriquée à tous les étages. L'installation se fait par le
profil « Hyperviseur Proxmox VE (sans Odoo) » du menu de déploiement, ou à la
main dans la VM :

```bash
sudo ./script/proxmox/install_proxmox.sh --dry-run   # dit ce qu'il ferait
sudo ./script/proxmox/install_proxmox.sh             # puis : sudo reboot
```

Trois pièges de l'image cloud, tous rencontrés sur une VM réelle et traités par
le script : cloud-init tient encore le verrou d'`apt` au premier démarrage ;
`grub-pc`, tiré par les paquets `pve`, demande sur quel disque s'installer et
bloque toute la transaction sans préréponse ; et le chemin de secours UEFI
(`\EFI\BOOT\`) reçoit les binaires GRUB de Proxmox mais pas le `grub.cfg`
qui dit où trouver la configuration — sans quoi la VM s'arrête sur l'invite
`grub>`, sans menu ni noyau.

Fournissez un chemin d'image en argument positionnel pour surcharger
l'emplacement de téléchargement automatique.

Les Ubuntu `20.04` et `22.04` sont **abandonnées sur toutes les
architectures** : pikepdf réclame qpdf 12.2, dont la compilation exige C++20,
et focal livre GCC 9 — elle ne publie même pas de `g++-10` pour s390x. Python
3.8, node 10, cargo 0.67 et OpenSSL 1.1.1 avaient chacun leur contournement ;
leur accumulation, non.

## Après le déploiement

<!-- [common] -->
```bash
virsh list --all
virsh console test-vm                    # Ctrl+] to quit / pour quitter
virsh domifaddr test-vm --source lease   # find the IP / trouver l'IP
ssh erplibre@<IP>
```

<!-- [en] -->
The default user is `erplibre` (change it with `--user`).

## Via the TODO menu

The script is integrated into the interactive assistant. Run `make todo` (or
`./script/todo/todo.py`), then go to **Execute → Deploy → QEMU/KVM - Deploy an
Ubuntu VM (libvirt)**. From there you can deploy a VM, preview a dry-run,
download an image, list VMs and show a VM IP address — the menu asks for the
parameters and builds the command for you.

The desktop step ends by looking for the desktop binary, `gnome-shell` or
`cinnamon`: a package group can report success without bringing it, and the
step then fails on one line naming the missing binary, before the display
manager and the remote access. On AlmaLinux, Rocky Linux, CentOS Stream and
RHEL, the step enables EPEL and CRB before installing anything, since the
Cinnamon group and xrdp come from EPEL; an xrdp that still does not install
only costs the remote access, the desktop stays.

When a VM is graphical, the menu also offers a **check list of development
tools**: PyCharm Community (installed from the official
JetBrains archive into `/opt/pycharm`, its launcher opening the ERPLibre
checkout — the Community line, because the unified 2025.3 build stops on a
licence screen and never opens a project), Android
Studio (`/opt/android-studio`, command `studio` or `android-studio`; x86_64
only — Google publishes no Linux aarch64 build) and a set of suggested GNOME extensions.

The extension packages of the distribution are installed but left disabled —
their UUID is not reliably known, and the Extension Manager is there to pick
from. Three extensions named by UUID are installed **and enabled**, straight
from extensions.gnome.org: **gTile**, **Freon** and **Tracker**. The archive
is fetched for the GNOME Shell version actually running in the VM — the same
endpoint serves gTile v59 for GNOME 46 and v62 for GNOME 48, so a frozen URL
would install a build made for another release. A mismatched build is never
loaded by GNOME anyway: it compares `metadata.json` with its own version and
shows the extension as outdated rather than breaking the session.

The tools are installed **before** the clone and the ERPLibre install, and
the order matters: PyCharm writes the repository's `.idea/` the first time it
opens the project, and the install that follows runs
`pycharm_configuration.py` on it (`update_env_version.pycharm_update()`,
which skips silently when there is no `.idea` yet). That first open is automated: PyCharm runs once under
Xvfb — a virtual framebuffer inside the guest, so the orchestrating host
needs no graphics at all — with the trust, privacy and data-sharing dialogs
answered in advance. Measured on an Ubuntu 26.04 VM with 16 GB: `.idea/` is
written in 195 s, and the install then adds its exclusions to the `.iml`.
When Xvfb is unavailable or the IDE does not get there in five minutes, the
log says so and the install carries on.

A fourth one needs no desktop at all: **ERPLibre mobile (build)**. It adds
the mobile repository to the manifest (which is additive, so it coexists with
an Odoo 18 install), runs the repository's own `install-android.sh` — JDK 17,
command-line tools, SDK licences accepted, NDK, whisper.cpp and sentencepiece
— then builds: `npm ci`, `vite build`, `cap sync`, `gradlew assembleDebug`,
and finally `npm test`. **A failed build fails the VM**: the exit code reaches
the dashboard, and the log names the probable cause instead of leaving a
40 MB Gradle log to read: disk full, missing SDK platform, JDK/Gradle
mismatch, unaccepted licences, a Gradle daemon killed by the kernel (with the
machine's RAM, swap and oom-kill count, because a memory cause is proven and
not assumed), or too many asset files for one APK. The heavy output goes to
`~/erplibre-mobile-build.log` inside the VM so the install log stays readable.

That last cause is fixed rather than avoided. The app carries the manifest
repositories so their code can be browsed offline, and an APK is a ZIP capped at
65535 entries — one file per source asked for 123 678 and the build stopped
there. Those files now enter as **packs**: 4 MB slices, plus an `index.json` per
repository saying which slice holds a file, at which offset and length. The
reader asks for a byte range, and falls back to the whole slice when the WebView
server ignores `Range` — 4 MB at worst, which is why the slices are bounded.
Raster images are left out: addon screenshots, in a browser that shows text.

Images are packed too, and a packed file has no URL of its own: the reader turns
its bytes into a blob URL. Gettext catalogues, on the other hand, are dropped —
41 594 `.po`/`.pot` files weighing 857 MB, 72 % of the payload for content that
Weblate maintains and nobody reads on a phone. `BUNDLE_KEEP_PO=1` brings them
back, `BUNDLE_SKIP_IMG=1` drops the images.

Measured on a VM: 139 repositories, 80 841 files in 233 slices, an APK of 354 MB
with **2 844 entries**, and 20 files read back from the packs identical byte for
byte to their source. The APK does not follow the payload — text compresses,
PNG does not: the code alone is 331 MB of assets for about 130 MB of APK. The
install verifies the transfer with `script/mobile/check_bundle_transfer.py`,
which also runs on its own, and a failed transfer fails the VM — an app that
does not carry the code it is meant to show is not the app that was asked for.

It is bounded to apt-based distributions, because that upstream installer
starts with `sudo apt install openjdk-17-jdk`. It requires no Android Studio
— a plain server VM builds the APK — and when Android Studio is also ticked
they share one SDK through `ANDROID_HOME`. Without Android, the same app runs
in a browser: `npm start`.

A fifth, **Android emulator (Pixel)**, creates an AVD. Drive it from the
QEMU menu, *Android emulator (start, tunnel, scrcpy)*: it starts the emulator
without a window and hands you the adb tunnel and the scrcpy command. Prefer
that to a window over X11 — scrcpy receives H.264 encoded by the device, where
`ssh -X` ships every frame as raw pixels in software rendering. If you do want
the window, the path must be absolute, because `ssh host 'command'` reads
neither `~/.profile` nor `~/.bashrc`:
`ssh -XC erplibre@<ip> '$HOME/android/emulator/emulator -avd erplibre -no-audio'`.

It needs no desktop in the VM, but it does need KVM inside the guest, so
nested virtualisation on the host; the log says so when `/dev/kvm` is missing.
The device is not frozen: the SDK is asked for its profiles and the newest
plain Pixel with the smallest screen wins (no Pro, XL, Fold or tablet).
Rendering is `swangle` in the AVD's own `config.ini` — `auto` would open a
black screen, and `swiftshader_indirect` no longer exists, the emulator
answering `Selected GPU option ... is not valid`.

A sixth, **Forgejo**, installs a self-hosted git forge — the software behind
Codeberg — from the project's official static binary, and leaves it serving on
port 3000 with git-over-SSH on 2222. Like the mobile build it needs no desktop,
and unlike it no package family is excluded: the binary is static, so the same
file serves apt, dnf, pacman and zypper. That is what makes it portable across
the ERPLibre platforms without a branch per distribution. Architectures follow
upstream, which publishes amd64, arm64 and arm-6 — the checkbox greys out on
s390x rather than dropping a binary that cannot run.

The work lives in `script/forgejo/install_forgejo.sh`, callable on its own for
an existing machine: `./script/forgejo/install_forgejo.sh`. It verifies the
published checksum, writes all four secrets itself so the service never needs
to rewrite its own configuration, and stores its data in SQLite so it does not
dispute PostgreSQL with Odoo on the same VM. Replaying it is cheap and safe —
1.5 s measured with everything in place: it skips a binary already at the right
version, never overwrites an existing `app.ini`, and does not recreate the
administrator. `FORGEJO_VERSION`, `FORGEJO_HTTP_PORT`, `FORGEJO_ADMIN_USER` and
a few others tune it; `--help` lists them.

A seventh, **AI coding tools**, pre-configures the shell one works in: tig,
htop and vim, rtk with its global hook, starship, one agent — Claude Code
or opencode — the git settings, the checkout hooks and the Claude commands.
Nothing there fails the VM: each pose is time-bounded and given no standard
input, because a `curl | sh` that asks a question would hang a deployment
that has no terminal to answer it.

An eighth, **nix + nixos-anywhere**, is the reverse of picking NixOS in the
catalogue: it leaves an ordinary VM able to INSTALL NixOS onto another
machine reachable over SSH. The official multi-user installer, flakes
enabled, and `nixos-anywhere` in the user profile. It greys out on NixOS,
where nix already is the system, and outside amd64/arm64.

Each tool is filtered per VM — by architecture, desktop flavour and package
family — and its disk cost is added to the plan before anything is created.

### VM account

One account serves the whole deployment: every VM created by it gets the same
user and password. The defaults are `erplibre` / `erplibre`, a public
password, which suits a disposable development VM and nothing else.

The **VM account** section of the form (QEMU/KVM and Proxmox alike) holds:

- the user — lowercase, `^[a-z_][a-z0-9_-]{0,31}$`, and not a name an
  account or a group of the images already holds (`root`, `ubuntu`, `gdm`,
  `git`, `sudo`, `wheel`…);
- the password, masked, with three buttons: **Generate** (16 characters, no
  `0 O 1 l I`, a letter first), **Copy** (to the clipboard, through OSC 52)
  and **Show/Hide**;
- **Keep the password in the VM**, off by default.

The QEMU/KVM command-line prompts ask the same: Enter keeps `erplibre`, `g`
generates a password and prints it once, anything else asks for it twice
without echo. The Proxmox command-line path asks nothing and uses the
defaults.

The clear password is kept nowhere. The VM receives its SHA-512 crypt hash
(`--password-hash`); the spec, `session.json`, the form history, the logs and
the preview hold none of it. A GNOME desktop needs the clear value for its RDP
login: the host sends it over ssh's standard input to a root-only file,
GNOME Remote Desktop reads it, and the file is deleted once the RDP login is
checked. An install that stops before that point leaves the file for its
relaunch. A server VM never receives it. With **Keep the password in the
VM**, the file stays, and the form shows how to read it:

```bash
sudo cat /etc/erplibre/vm-password
```

A VM created earlier keeps the account it was created with. The menu finds it
in the install monitor's `session.json`, then in `~/.ssh/config`, and falls
back to `erplibre`. A VM recreated from its kept spec gets the same account
back from the stored hash. Once todo has been restarted the clear password is
gone, so recreating a GNOME desktop asks for it again and accepts it only if it
matches the stored hash. Leaving it out recreates the VM without RDP.

GNOME Remote Desktop 47 and later read the password on their standard input.
`grdctl` 46 only takes it as an argument, and `pkexec`, which `grdctl
--system` goes through, logs that command line in the VM's journal.

## Main options

- `--distro` — `ubuntu` (default), `debian`, `fedora`, `almalinux`,
  `rocky`, `opensuse`, `arch`, `nixos` or `proxmox`. NixOS is the one
  image no distribution publishes: it is rebuilt by a third party, so the
  release is pinned and its sha256 verified at every download, and the
  origin is printed before anything is created.
- `--version` — release for the distro (default: the distro's default).
- `--list-images` — print all distros/versions and their specs, then exit.
- `--image-dir` — image cache directory (default `/var/lib/libvirt/images/iso`).
- `--download-only` — download the image then exit (no VM).
- `--name` — VM name (required for deployment).
- `--memory`, `--vcpus`, `--disk-size` — VM sizing. When omitted, `--memory`
  and `--disk-size` default to the **minimum required by the chosen version**
  (libosinfo values, see `--list-images`: Ubuntu 24.04+ → 3072 MB/20G, Debian
  → 1024 MB/10G, Fedora → 2048 MB/15G); `--vcpus` defaults to 2.
- `--ssh-key`, `--ask-password`, `--password-hash` — authentication.
- `-y` / `--assume-yes` — auto-accept dependency installation.
- `--no-install-deps` — never auto-install dependencies.
- `--dry-run` — show the commands without executing anything.
- `--force` — overwrite the existing working qcow2 disk.
- `--gpu` — 3D acceleration by the host GPU: `auto` (default, on when the
  host has a render node), `on` (force), `off` (software rendering).
- `--gpu-node` — which render node to use, on a multi-GPU host.
- `--lang` — language of the SSH login guide, `fr` (default) or `en`. The
  TODO menu passes its own language.
- `--erplibre-dir` — where ERPLibre will live in the VM
  (`~/git/erplibre`, or `/opt/erplibre` in production). Adds the ERPLibre
  section to the login guide; omitted, that section is left out.
- `--erplibre-make` — the make target that installed the VM
  (e.g. `install_odoo_18`), shown in the guide as the way to update it.
- `--no-git-identity` — do not copy the host's `user.name`, `user.email`
  and `core.editor` into the VM's `~/.gitconfig`.

Run `./script/qemu/deploy_qemu.py --help` for the full list.

## Login guide (`/etc/motd` or `profile.d`)

Every VM greets you, at each interactive SSH login, with the commands of
**its own** distribution — `apt`, `dnf`, `zypper` or `pacman` — plus the
ERPLibre ones (edit the server, restart it, update modules, update Odoo,
inspect the instance, open the TODO menu). It is written by cloud-init, so
it is there from the first boot: before ERPLibre is installed, and still
there if that installation fails, which is exactly when you log in by hand.

`--dry-run` prints the generated guide along with the rest of the user-data.
The guide is not shown to `ssh host 'command'`, so it never pollutes an
installation log.

A VM with a desktop (`--desktop`), except on NixOS, does not get `/etc/motd`: `pam_motd` sits in
the generic login PAM stack, so GDM would show the guide as a PAM message and
delay the start of the graphical session in proportion to its length (tens of
seconds). The same text is written to `/etc/erplibre-login-guide`, and
`/etc/profile.d/erplibre-login-guide.sh` prints it in interactive login
shells of an SSH session (a nested login shell that keeps
`SSH_CONNECTION`, such as `bash -l`, shows it again); desktop terminals, `ssh host 'command'`, `scp` and
`sftp` stay silent. A server VM keeps `/etc/motd`, and so does a NixOS VM,
desktop included: its sshd reads `/etc/motd`, it has no `pam_motd` and its
`/etc/profile` does not source `profile.d`.

The host's git identity travels with it, into the VM's `~/.gitconfig`: a
commit made in the VM then carries your name instead of
`erplibre@<vm-name>`. The editor follows the same route — `core.editor`, the
`config.conf` line of the guide, and the package installed in the VM all
come from one table, so the guide never names a command the VM does not
have.

<!-- [fr] -->
L'utilisateur par défaut est `erplibre` (modifiable avec `--user`).

## Via le menu TODO

Le script est intégré à l'assistant interactif. Lancez `make todo` (ou
`./script/todo/todo.py`), puis allez dans **Execute → Deploy → QEMU/KVM -
Deploy an Ubuntu VM (libvirt)**. De là, vous pouvez déployer une VM,
prévisualiser un dry-run, télécharger une image, lister les VM et afficher
l'IP d'une VM — le menu demande les paramètres et construit la commande pour
vous.

L'étape du bureau se termine en cherchant le binaire du bureau, `gnome-shell`
ou `cinnamon` : un groupe de paquets peut dire avoir réussi sans l'apporter,
et l'étape échoue alors sur une ligne qui nomme le binaire absent, avant le
gestionnaire d'affichage et l'accès distant. Sur AlmaLinux, Rocky Linux,
CentOS Stream et RHEL, l'étape active EPEL et CRB avant toute installation,
le groupe Cinnamon et xrdp venant d'EPEL ; un xrdp qui ne s'installe toujours
pas ne coûte que l'accès distant, le bureau reste.

Quand une VM est graphique, le menu propose en plus une **liste à cocher
d'outils de développement** : PyCharm Community (posé depuis l'archive
officielle JetBrains dans `/opt/pycharm`, son lanceur ouvrant le dépôt
ERPLibre — la ligne Community, car le build unifié 2025.3 s'arrête sur un
écran de licence et n'ouvre jamais de projet),
Android Studio (`/opt/android-studio`, commande `studio` ou
`android-studio` ; x86_64 seulement — Google ne publie aucune archive Linux
aarch64) et un jeu
d'extensions GNOME suggérées.

Les extensions empaquetées par la distribution sont installées sans être
activées — leur UUID n'est pas connu de façon fiable, et le gestionnaire
d'extensions est là pour choisir. Trois extensions nommées par leur UUID sont,
elles, installées **et activées**, directement depuis extensions.gnome.org :
**gTile**, **Freon** et **Tracker**. L'archive est prise pour la version de
GNOME Shell qui tourne vraiment dans la VM — le même point d'entrée sert gTile
v59 en GNOME 46 et v62 en GNOME 48, si bien qu'une URL figée poserait une
version faite pour une autre release. Une archive mal appariée n'est de toute
façon jamais chargée par GNOME : il compare `metadata.json` à sa propre
version et affiche l'extension comme obsolète plutôt que de casser la session.

Les outils sont posés **avant** le clone et l'installation d'ERPLibre, et
l'ordre compte : PyCharm écrit le `.idea/` du dépôt à la première ouverture du
projet, et l'installation qui suit y lance `pycharm_configuration.py`
(`update_env_version.pycharm_update()`, qui se tait tant qu'il n'y a pas de
`.idea`). Cette première ouverture est automatisée : PyCharm est lancé une fois sous
Xvfb — un serveur d'affichage virtuel DANS la VM invitée, si bien que l'hôte
qui orchestre n'a besoin d'aucune bibliothèque graphique — avec les fenêtres
de confiance, de confidentialité et de partage de données répondues d'avance.
Mesuré sur une VM Ubuntu 26.04 à 16 Go : le `.idea/` est écrit en 195 s, et
l'installation y ajoute ensuite ses exclusions dans le `.iml`. Sans Xvfb, ou
si l'IDE n'y arrive pas en cinq minutes, le journal le dit et l'installation
continue.

Un quatrième ne demande aucun bureau : **ERPLibre mobile (compilation)**. Il
ajoute le dépôt mobile au manifeste — additif, donc il cohabite avec une
installation Odoo 18 —, lance l'`install-android.sh` du dépôt lui-même (JDK 17,
outils en ligne de commande, licences SDK acceptées, NDK, whisper.cpp et
sentencepiece), puis compile : `npm ci`, `vite build`, `cap sync`,
`gradlew assembleDebug`, et enfin `npm test`. **Une compilation en échec fait
échouer la VM** : le code de sortie remonte au tableau de bord, et le journal
NOMME la cause probable au lieu de laisser 40 Mo de journal Gradle à relire :
disque plein, plateforme SDK absente, JDK et Gradle incompatibles, licences non
acceptées, démon Gradle tué par le noyau (avec la RAM, le swap et le compte de
l'oom-killer, parce qu'une cause « mémoire » se prouve au lieu de s'affirmer),
ou trop de fichiers d'assets pour un APK. Le détail va dans
`~/erplibre-mobile-build.log`, dans la VM, pour que le journal d'installation
reste lisible.

Cette dernière cause est corrigée, et non contournée. L'application embarque les
dépôts du manifeste pour en parcourir le code hors ligne, et un APK est un ZIP
borné à 65535 entrées — un fichier par source en réclamait 123 678, et la
compilation s'arrêtait là. Ces fichiers y entrent désormais en **packs** :
des tranches de 4 Mo, plus un `index.json` par dépôt qui dit dans quelle tranche
se trouve un fichier, à quel offset et sur quelle longueur. La lecture demande
un intervalle d'octets, et retombe sur la tranche entière quand le serveur du
WebView ignore `Range` — 4 Mo au pire, et c'est pour cela que les tranches sont
bornées. Les images matricielles restent dehors : des captures d'écran
d'addons, dans un navigateur qui montre du texte.

Les images sont empaquetées aussi, et un fichier empaqueté n'a pas d'URL propre :
le lecteur fait un blob de ses octets. Les catalogues gettext, en revanche, sont
écartés — 41 594 fichiers `.po`/`.pot` pour 857 Mo, soit 72 % du poids, d'un
contenu que Weblate maintient et que personne ne lit sur un téléphone.
`BUNDLE_KEEP_PO=1` les ramène, `BUNDLE_SKIP_IMG=1` retire les images.

Mesuré sur une VM : 139 dépôts, 80 841 fichiers en 233 tranches, un APK de
354 Mo à **2 844 entrées**, et 20 fichiers relus depuis les packs identiques
octet pour octet à leur source. L'APK ne suit pas la charge — le texte se
compresse, le PNG non : le code seul fait 331 Mo d'assets pour environ 130 Mo
d'APK. L'installation vérifie le transfert avec
`script/mobile/check_bundle_transfer.py`, qui s'exécute aussi seul, et un
transfert manqué fait échouer la VM — une application qui ne porte pas le code
qu'elle est censée montrer n'est pas l'application demandée.

Il est borné aux distributions apt, parce que cet installateur amont commence
par `sudo apt install openjdk-17-jdk`. Il n'exige PAS Android Studio — une
simple VM serveur produit l'APK — et quand Android Studio est aussi coché, les
deux partagent un seul SDK via `ANDROID_HOME`. Sans Android, la même
application tourne dans un navigateur : `npm start`.

Un cinquième, **Émulateur Android (Pixel)**, crée un AVD. Conduisez-le depuis
le menu QEMU, *Émulateur Android (démarrage, tunnel, scrcpy)* : il démarre
l'émulateur sans fenêtre, puis donne le tunnel adb et la commande scrcpy.
Préférez cette voie à une fenêtre par X11 — scrcpy reçoit du H.264 encodé PAR
l'appareil, là où `ssh -X` fait traverser chaque image en pixels bruts, en
rendu logiciel. Si vous voulez la fenêtre, le chemin doit être ABSOLU, car
`ssh hôte 'commande'` ne lit ni `~/.profile` ni `~/.bashrc` :
`ssh -XC erplibre@<ip> '$HOME/android/emulator/emulator -avd erplibre -no-audio'`.

Il ne demande aucun bureau dans la VM, mais il exige KVM dans l'invitée, donc
la virtualisation imbriquée sur l'hôte ; le journal le dit quand `/dev/kvm`
manque. Le modèle n'est pas figé : on demande au SDK ses profils et le Pixel le
plus récent au plus petit écran gagne (ni Pro, ni XL, ni pliant, ni tablette).
Le rendu est « swangle » dans le `config.ini` de l'AVD — « auto » ouvrirait un
écran noir, et « swiftshader_indirect » n'existe plus, l'émulateur répondant
`Selected GPU option ... is not valid`.

Un sixième, **Forgejo**, installe une forge git auto-hébergée — le logiciel
derrière Codeberg — depuis le binaire statique officiel du projet, et la laisse
en service sur le port 3000, avec git par SSH sur 2222. Comme la compilation
mobile, elle n'a besoin d'aucun bureau ; contrairement à elle, aucune famille de
paquets n'est exclue : le binaire est statique, donc le même fichier sert apt,
dnf, pacman et zypper. C'est ce qui la rend portable sur les plateformes
ERPLibre sans une branche par distribution. Les architectures suivent l'amont,
qui publie amd64, arm64 et arm-6 — la case se grise sur s390x plutôt que de
poser un binaire qui ne s'exécutera pas.

Le travail vit dans `script/forgejo/install_forgejo.sh`, appelable seul sur une
machine existante : `./script/forgejo/install_forgejo.sh`. Il vérifie la somme
de contrôle publiée, écrit lui-même les quatre secrets pour que le service n'ait
jamais à réécrire sa propre configuration, et garde ses données en SQLite pour
ne pas disputer PostgreSQL à Odoo sur la même VM. Le rejouer est sans risque et
bon marché — 1,5 s mesuré, tout étant en place : il saute un binaire déjà à la
bonne version, ne réécrit jamais un `app.ini` existant et ne recrée pas
l'administrateur. `FORGEJO_VERSION`, `FORGEJO_HTTP_PORT`, `FORGEJO_ADMIN_USER`
et quelques autres le règlent ; `--help` les énumère.

Un septième, **Outils d'assistance IA**, pré-configure le shell où l'on
travaille : tig, htop et vim, rtk et son hook global, starship, un agent —
Claude Code ou opencode —, les réglages git, les hooks du dépôt et les
commandes Claude. Rien là-dedans ne fait échouer la VM : chaque pose est
bornée dans le temps et privée d'entrée standard, car un « curl | sh » qui
pose une question pendrait un déploiement sans terminal pour lui répondre.

Un huitième, **nix + nixos-anywhere**, est l'inverse de NixOS choisi dans le
catalogue : il laisse une VM ordinaire capable d'INSTALLER NixOS sur une
autre machine joignable en SSH. L'installateur officiel multi-utilisateur,
les flakes activés, et `nixos-anywhere` dans le profil de l'utilisateur.
L'option est grisée sur NixOS, où nix est déjà le système, et hors
amd64/arm64.

Chaque outil est filtré VM par VM — architecture, saveur de bureau et famille
de paquets — et sa place disque s'ajoute au plan avant que rien ne soit créé.

### Compte de la VM

Un seul compte sert tout le déploiement : chaque VM qu'il crée reçoit le même
utilisateur et le même mot de passe. Les défauts sont `erplibre` /
`erplibre`, un mot de passe public, qui convient à une VM de développement
jetable et à rien d'autre.

La section **Compte de la VM** du formulaire (QEMU/KVM comme Proxmox) porte :

- l'utilisateur — en minuscules, `^[a-z_][a-z0-9_-]{0,31}$`, et pas un nom
  que porte déjà un compte ou un groupe des images (`root`, `ubuntu`, `gdm`,
  `git`, `sudo`, `wheel`…) ;
- le mot de passe, masqué, avec trois boutons : **Générer** (16 caractères,
  sans `0 O 1 l I`, une lettre en tête), **Copier** (dans le presse-papier,
  par OSC 52) et **Afficher/Masquer** ;
- **Garder le mot de passe dans la VM**, décoché par défaut.

Les invites en ligne de QEMU/KVM demandent la même chose : Entrée garde
`erplibre`, `g` génère un mot de passe et l'affiche une fois, toute autre
réponse le fait taper deux fois sans écho. La voie en ligne de Proxmox ne
demande rien et prend les défauts.

Le mot de passe en clair n'est gardé nulle part. La VM reçoit son empreinte
SHA-512 crypt (`--password-hash`) ; la spec, `session.json`, l'historique du
formulaire, les journaux et l'aperçu n'en portent rien. Un bureau GNOME a
besoin du clair pour sa connexion RDP : l'hôte l'envoie par l'entrée standard
de ssh dans un fichier lisible par root seul, GNOME Remote Desktop le lit, et
le fichier est supprimé une fois la connexion RDP vérifiée. Une installation
qui s'arrête avant laisse le fichier pour sa relance. Une VM serveur ne le
reçoit jamais. Avec **Garder le mot de passe dans la VM**, le fichier reste,
et le formulaire dit comment le lire :

```bash
sudo cat /etc/erplibre/vm-password
```

Une VM créée auparavant garde le compte de sa création. Le menu le retrouve
dans le `session.json` du suivi d'installation, puis dans `~/.ssh/config`, et
retombe sur `erplibre`. Une VM recréée d'après sa spec gardée retrouve le
même compte grâce à l'empreinte conservée. Une fois todo relancé, le clair
n'existe plus : la recréation d'un bureau GNOME le redemande, et ne l'accepte
que s'il correspond à l'empreinte. S'en passer recrée la VM sans RDP.

GNOME Remote Desktop 47 et suivants lisent le mot de passe sur leur entrée
standard. `grdctl` 46 ne le prend qu'en argument, et `pkexec`, par lequel
passe `grdctl --system`, journalise cette ligne de commande dans la VM.

## Principales options

- `--distro` — `ubuntu` (défaut), `debian`, `fedora`, `almalinux`,
  `rocky`, `opensuse`, `arch`, `nixos` ou `proxmox`. NixOS est la seule
  image qu'aucune distribution ne publie : elle est rebâtie par un tiers,
  donc la version est épinglée, sa somme sha256 vérifiée à chaque
  téléchargement, et l'origine dite avant que rien ne soit créé.
- `--version` — version de la distro (défaut : celle par défaut de la distro).
- `--list-images` — affiche toutes les distros/versions et leurs specs.
- `--image-dir` — répertoire de cache des images (défaut
  `/var/lib/libvirt/images/iso`).
- `--download-only` — télécharge l'image puis quitte (sans VM).
- `--name` — nom de la VM (requis pour le déploiement).
- `--memory`, `--vcpus`, `--disk-size` — dimensionnement de la VM. Omis,
  `--memory` et `--disk-size` prennent le **minimum requis par la version**
  choisie (valeurs libosinfo, voir `--list-images` : Ubuntu 24.04+ →
  3072 Mo/20G, Debian → 1024 Mo/10G, Fedora → 2048 Mo/15G) ; `--vcpus`
  vaut 2 par défaut.
- `--ssh-key`, `--ask-password`, `--password-hash` — authentification.
- `-y` / `--assume-yes` — accepte automatiquement l'installation des
  dépendances.
- `--no-install-deps` — n'installe jamais les dépendances automatiquement.
- `--dry-run` — affiche les commandes sans rien exécuter.
- `--force` — écrase le disque de travail qcow2 existant.
- `--gpu` — accélération 3D par le GPU de l'hôte : `auto` (défaut, activée si
  l'hôte a un nœud de rendu), `on` (forcer), `off` (rendu logiciel).
- `--gpu-node` — quel nœud de rendu utiliser, sur un hôte à plusieurs cartes.
- `--lang` — langue du guide affiché à la connexion SSH, `fr` (défaut) ou
  `en`. Le menu TODO passe la sienne.
- `--erplibre-dir` — où ERPLibre sera installé dans la VM
  (`~/git/erplibre`, ou `/opt/erplibre` en production). Ajoute la section
  ERPLibre au guide de connexion ; omis, cette section est laissée de côté.
- `--erplibre-make` — la cible make qui a installé la VM
  (ex. `install_odoo_18`), reprise dans le guide pour la mettre à jour.
- `--no-git-identity` — ne recopie pas les `user.name`, `user.email` et
  `core.editor` de l'hôte dans le `~/.gitconfig` de la VM.

Lancez `./script/qemu/deploy_qemu.py --help` pour la liste complète.

## Guide de connexion (`/etc/motd` ou `profile.d`)

Chaque VM accueille celui qui s'y connecte en SSH avec les commandes de **sa**
distribution — `apt`, `dnf`, `zypper` ou `pacman` — et celles d'ERPLibre :
éditer le serveur, le redémarrer, mettre à jour des modules, mettre à jour
Odoo, inspecter l'instance, ouvrir le menu TODO. Il est écrit par cloud-init,
donc présent dès le premier démarrage : avant l'installation d'ERPLibre, et
encore là si elle échoue — le moment où l'on se connecte justement à la main.

`--dry-run` affiche le guide généré avec le reste du user-data. Il ne
s'affiche PAS pour un `ssh hôte 'commande'` : les journaux d'installation
restent nets.

Une VM à bureau (`--desktop`), hors NixOS, ne reçoit PAS `/etc/motd` : `pam_motd` figure
dans la pile PAM générique de connexion, donc GDM afficherait le guide comme
message PAM et retarderait l'ouverture de la session graphique en proportion
de sa longueur (des dizaines de secondes). Le même texte est écrit dans
`/etc/erplibre-login-guide`, et `/etc/profile.d/erplibre-login-guide.sh`
l'affiche dans les shells de connexion interactifs d'une session SSH (un
shell de connexion imbriqué qui garde `SSH_CONNECTION`, comme `bash -l`,
l'affiche de nouveau) ; terminaux du bureau, `ssh hôte 'commande'`, `scp` et `sftp`
restent silencieux. Une VM serveur garde `/etc/motd`, NixOS aussi, bureau
compris : son sshd lit `/etc/motd`, il n'a pas de `pam_motd` et son
`/etc/profile` ne source pas `profile.d`.

L'identité git de l'hôte voyage avec lui, dans le `~/.gitconfig` de la VM :
un commit fait dans la VM porte alors votre nom plutôt que
`erplibre@<nom-de-vm>`. L'éditeur suit le même chemin — `core.editor`, la
ligne `config.conf` du guide et le paquet installé dans la VM viennent d'une
seule table, de sorte que le guide ne nomme jamais une commande absente.

<!-- [en] -->
## Managing VMs

List, stop and remove VMs (the qcow2 disk under `/var/lib/libvirt/images`
is kept unless you delete it):

<!-- [fr] -->
## Gestion des VM

Lister, arrêter et supprimer les VM (le disque qcow2 sous
`/var/lib/libvirt/images` est conservé tant que vous ne le supprimez pas) :

<!-- [common] -->
```bash
sudo virsh list --all          # toutes les VM et leur état / all VMs and state
sudo virsh shutdown <nom-vm>   # arrêt propre ACPI / graceful shutdown
sudo virsh destroy <nom-vm>    # arrêt forcé / force off (pull the plug)
sudo virsh undefine <nom-vm>   # supprime la définition / remove definition
sudo virsh domifaddr <nom-vm>  # adresse IP de la VM / VM IP address
```

<!-- [en] -->
`destroy` only powers the VM off (disk kept); `undefine` removes its
definition. To fully recreate a VM with the same name, `destroy` + `undefine`
it first, or redeploy with `--force`.

## The VMs' subnet

Every VM deployed here lives in the libvirt network `default`, which serves a
/24 — `192.168.122.0/24` out of the box. The VMs take an address in it by DHCP
and leave through its `.1`, carried by the bridge. Move that /24 under a
running VM and it keeps a lease that leads nowhere; tear the network down and
its tap is no longer on any bridge, which libvirt does not undo by itself.

`network_qemu.py` reads that state, and puts the subnet back under the VMs:

```bash
# What the network serves, its bridge, its VMs, their leases — reads only
./script/qemu/network_qemu.py --status

# Put the subnet back: stop the attached VMs, redefine, start them again
./script/qemu/network_qemu.py --recreate
./script/qemu/network_qemu.py --recreate --prefix 192.168.140
./script/qemu/network_qemu.py --recreate --force-off   # VMs that ignore ACPI
```

The default prefix is libvirt's own, `192.168.122`: it is what the `.ssh/config`
entries and the notes written before assume. A prefix that overlaps what the
host already routes is refused — a bridge taking the host's gateway address is
how a machine loses its own network. A VM that ignores the shutdown cancels the
redefinition rather than losing its bridge under it.

Both are also at **TODO › Execute › Deploy › QEMU/KVM**, section **Network**.

## USB devices: passthrough and SPICE redirection (Stream Deck)

A USB device reaches a VM by one of two paths, depending on **where it is
plugged in**. Stream Decks (Elgato, vendor `0fd9`) are always listed first and
marked, because ERPLibre Home in the guest drives them.

| Device plugged into… | Path | What it takes |
|---|---|---|
| the **libvirt host** (this machine, or the hypervisor behind a ProxyJump) | `<hostdev>` passthrough, attached by `virsh` | a USB controller in the VM; nothing on the viewer side |
| the **workstation** that opens `virt-viewer` | SPICE USB redirection (`usbredir`) | a SPICE display placed **before** the VNC one, `spicevmc` redirection slots, a viewer session kept open |

Pick passthrough when the deck sits on the machine that runs the VM: it holds
without a viewer, can come back at every start, and can follow a replug.
Pick SPICE redirection when the deck sits on your desk and the VM runs
elsewhere: the deck follows the viewer window and goes back to the workstation
when it closes.

A host USB device serves **one** running domain at a time: libvirt refuses to
start a second VM that holds it, and `startupPolicy='optional'` does not cover
a device already in use.

### The TODO menu

**TODO › Execute › Deploy › QEMU/KVM**, section **USB**, entry **USB devices
(Stream Deck, passthrough, SPICE)**:

- *Device on the libvirt host* — list this machine's USB devices (hubs left
  out); attach a device to a VM; detach it; show the USB devices of a VM
  (each view, USB controllers, display order, redirection slots).
- *Device on this workstation (SPICE)* — open `virt-viewer` with USB
  redirection; enable SPICE USB redirection on a VM.
- *Replug* — auto-reattach on replug (udev rule, device mapping).

The VM is picked among the local libvirt domains, then the hosts of
`~/.ssh/config`: a remote host is reached through its `ProxyJump` as
`qemu+ssh://<jump>/system`, and the device list then comes from **that**
hypervisor. A host without a `ProxyJump` is refused. Every plan is shown —
skipped steps with their reason, then the commands — and runs only once
confirmed. `sudo` precedes `virsh` only for a local `qemu:///system` that the
`libvirt` group does not open, never for `qemu+ssh`.

**Persistence is chosen at every attach**:

- **live and config** — now, and at every start;
- **live only** — until the VM stops;
- **config only** — from the next start.

A view that already holds the device is skipped, so attaching twice changes
nothing. The live view is skipped when the VM is off. A VM without a USB
controller, or with model `none`, is refused. The XML is written with
`startupPolicy='optional'`: the VM still starts when the deck is unplugged.

Two identical devices plugged in make `VID:PID` ambiguous for libvirt: the
device is then pinned by `BUS.DEV`, an address that changes on replug.

### The CLI `script/qemu/usb_qemu.py`

The same plans, without questions — what needs consent goes through `--yes`.
Exit codes: `0` done or nothing to do, `1` failure, `2` usage, `3` consent
required.

```bash
# Host devices, decks first (marked *); --json for a script
./script/qemu/usb_qemu.py list
./script/qemu/usb_qemu.py list --uri qemu+ssh://<jump>/system

# Attach: --live, --config or both; none is implied
./script/qemu/usb_qemu.py attach <vm-name> 0fd9:0080 --live --config
./script/qemu/usb_qemu.py attach <vm-name> 3.5 --live    # BUS.DEV
./script/qemu/usb_qemu.py attach <vm-name> 0fd9:0080 --live \
    --uri qemu+ssh://<jump>/system

# Detach; --yes restarts the host deck service afterwards
./script/qemu/usb_qemu.py detach <vm-name> 0fd9:0080 --live --config --yes

# Common options: --dry-run (commands and XML, nothing changed), --no-sudo
```

The selector is `VID:PID` (`0x` prefixes allowed) or `BUS.DEV` as `list`
prints it. A sysfs name such as `3-5` is refused: its second number is a
port, not a device number. A `VID:PID` that is not plugged in is accepted for
a detach, and for an attach with `--config` only. On a remote URI, `list`
reads the hypervisor through `virsh nodedev-list`, not the local sysfs.

### At install time

The deployment form has the checkbox **Attach the plugged Stream Decks (USB
passthrough + SPICE)**, and the prompts ask the same question; both appear
only when a selected VM has a desktop. Ticking it adds two options to
`deploy_qemu.py`:

```bash
./script/qemu/deploy_qemu.py --name <vm-name> --desktop \
    --usb-hostdev 0fd9:0080 --spice-usbredir --dry-run
```

- `--usb-hostdev VID:PID|BUS.DEV` (repeatable) passes a host device with
  `startupPolicy=optional`. A device absent from the host is skipped with a
  warning and the VM is created anyway; identical devices are each pinned by
  `bus.dev`.
- `--spice-usbredir` adds a SPICE display **before** the VNC one, with its
  redirection slots: `virt-viewer` opens the first display, so it offers its
  *USB device selection* menu. The VNC display stays for the SSH tunnels and
  the console diagnosis. Graphical x86_64 VMs only: a VM without a display,
  or of another architecture, is refused before any download.
  `--usb-hostdev` is refused on s390x, which has no USB bus.

When several VMs are deployed at once, the decks go to the **first** graphical
VM only — the others still get SPICE. A recreated VM gets the decks back only
if it had them at creation. With the `erplibre_home_streamdeck` tool, the guest
install always gets `--stream-deck --autostart`, so the deck service starts in
the guest whichever path brings the deck in.

### SPICE redirection on an existing VM

The entry *Enable SPICE USB redirection on a VM* reads the saved definition and
adds only what is missing: a SPICE display moved or added before the VNC one,
a `qemu-xhci` controller, two `spicevmc` slots, the SPICE agent channel, and —
if you accept — a filter that redirects only vendor `0fd9`. A display change
applies at the next start: a running VM is shut down only with your consent,
redefined, then started again. *Open virt-viewer with USB redirection* then
launches `virt-viewer` with the auto-redirect filter for `0fd9`, so a deck
plugged into the workstation follows the window; other devices are picked by
hand in **File › USB device selection**.

### Auto-reattach on replug

A replug gives the device a new device number, and QEMU loses its own. On the
libvirt host, a udev rule starts a root systemd unit that reads the mapping
*device → VM* and reattaches the device **live** to its running VM. It never
touches the saved definition — persistence was chosen at attach time.

| File | Role |
|---|---|
| `/etc/udev/rules.d/85-erplibre-usb-passthrough.rules` | one line per mapped vendor (deck always) |
| `/etc/systemd/system/erplibre-usb-reattach@.service` | `Type=oneshot`, runs as root |
| `/usr/local/libexec/erplibre-usb/` | a **copy** of `usb_qemu.py` and `qemu_usb.py`: the root unit never runs a file of the checkout |
| `/etc/erplibre/usb-passthrough.json` | the mapping, kept by the removal unless `--purge` |

```bash
# On the libvirt host (re-runs itself under sudo when needed)
./script/qemu/usb_qemu.py install-autoreattach [--vendor VID]...
./script/qemu/usb_qemu.py mapping add <vm-name> 0fd9:0080 [--serial SERIAL]
./script/qemu/usb_qemu.py mapping list
./script/qemu/usb_qemu.py mapping remove 0fd9:0080 --domain <vm-name> [--serial SERIAL]
./script/qemu/usb_qemu.py remove-autoreattach [--purge]

journalctl -u 'erplibre-usb-reattach@*'   # one line per decision
```

The serial only matters for two identical decks going to two VMs: an entry
with a matching serial wins over one without. On removal, no `--serial`
removes every entry of that model for the VM, and `--serial ""` only the
entry without a serial. Installing twice changes nothing.

For a **remote hypervisor**, *Replug* installs from the menu: it copies
`usb_qemu.py` and `qemu_usb.py` into a temporary directory there, runs
`ssh -t <jump> 'sudo python3 -I -B <tmp>/usb_qemu.py install-autoreattach'`, and
deletes the directory. Mappings then go through the installed copy,
`/usr/local/libexec/erplibre-usb/usb_qemu.py`, which must be present.

### Proxmox VE

A Proxmox USB assignment (`qm set <vmid> -usbN host=…`) is **always
persistent**: it is written to the VM configuration and follows a replug by
`VID:PID` without any udev rule. There is no live/config choice and no SPICE
path there. The QEMU USB menu refuses a Proxmox hypervisor and points to
**TODO › Execute › Deploy › Proxmox VE**, entry **USB devices (Stream Deck)**,
described in [`script/proxmox/README.md`](../proxmox/README.md). The
deployment checkbox exists there too, and reads the node's decks when the VM
is created.

### The host's own deck service

A host that runs ERPLibre Home with the Stream Deck holds the deck through its
`erplibre-home-streamdeck.service` user unit; QEMU and spice-gtk take it away
from it. Before a live attach of a deck, or a redirection from this
workstation, the tool **asks**: *no* cancels, *yes* stops the service once the
final confirmation is given; a config-only attach, or one to a stopped VM,
asks nothing. If the attach then fails, it offers to restart the service. A
deployment that passes the decks to a new VM asks the same question before the
VM starts: *no* creates the VM without the passthrough. Detaching a deck live
offers to restart it. The
CLI stops with code `3` instead of asking, and `--yes` gives consent; with
`--config` alone it only prints a note. That service also starts on its own
when the deck is replugged: on a host that maps a deck to a VM, turn its
autostart off (**TODO › Execute › ERPLibre Home**, deck settings).

### Check on real hardware

With a real Stream Deck:

1. `./script/qemu/usb_qemu.py list` on the libvirt host shows the deck first,
   marked `*`.
2. Attach it, then
   `sudo virsh dumpxml <vm-name> | grep -A6 hostdev` shows the device.
3. In the guest, `cat /sys/bus/usb/devices/*/idVendor` lists `0fd9`, and
   `./script/install/erplibre_home_deck.sh --check`, run from the guest's
   ERPLibre checkout, exits 0 once a graphical session is open.
4. The deck's **buttons render** from the guest's ERPLibre Home.
5. Start the VM with the deck unplugged: it still starts.
6. With auto-reattach: unplug and replug the deck on the host; the journal of
   `erplibre-usb-reattach@*` shows the reattach, and the buttons come back.
7. SPICE: open `virt-viewer` from the menu. It opens the SPICE display, not
   the VNC one; **File › USB device selection** lists the workstation's
   devices, and the deck is ticked.
8. Detach: the deck goes back to the host, and the host deck service is
   offered a restart.

## SSH access from another machine (ProxyJump)

With the default NAT network the VM is reachable **only from the KVM host**.
To reach it from another machine **without changing the network**, use the
host as a jump host (it already reaches the VM). Get the VM IP with
`sudo virsh domifaddr <nom-vm>`, then from the other machine:

<!-- [fr] -->
`destroy` ne fait qu'éteindre la VM (disque conservé) ; `undefine` supprime sa
définition. Pour recréer proprement une VM du même nom, faites `destroy` +
`undefine` d'abord, ou redéployez avec `--force`.

## Le sous-réseau des VM

Toute VM déployée ici vit dans le réseau libvirt « default », qui sert un /24 —
`192.168.122.0/24` à l'installation. Les VM y prennent une adresse par DHCP et
en sortent par le `.1`, porté par le pont. Déplacer ce /24 sous une VM allumée
lui laisse un bail qui ne mène nulle part ; abattre le réseau détache son tap
du pont, et libvirt ne l'y remet pas de lui-même.

`network_qemu.py` lit cet état, et remet le sous-réseau sous les VM :

```bash
# Ce que sert le réseau, son pont, ses VM, leurs baux — ne modifie rien
./script/qemu/network_qemu.py --status

# Remettre le sous-réseau : arrêter les VM attachées, redéfinir, relancer
./script/qemu/network_qemu.py --recreate
./script/qemu/network_qemu.py --recreate --prefix 192.168.140
./script/qemu/network_qemu.py --recreate --force-off   # VM sourdes à l'ACPI
```

Le préfixe par défaut est celui de libvirt, `192.168.122` : c'est celui que
supposent les entrées de `.ssh/config` et les notes prises avant. Un préfixe
qui recouvre ce que l'hôte route déjà est refusé — un pont qui prend l'adresse
de la passerelle de l'hôte, c'est ainsi qu'une machine perd son réseau. Une VM
qui n'obéit pas au shutdown annule la redéfinition plutôt que d'y perdre son
pont.

Les deux sont aussi au menu **TODO › Execute › Deploy › QEMU/KVM**, section
**Réseau**.

## Périphériques USB : passage et redirection SPICE (Stream Deck)

Un périphérique USB atteint une VM par l'une de deux voies, selon **l'endroit
où il est branché**. Les Stream Deck (Elgato, vendeur `0fd9`) sont toujours
listés en tête et marqués, parce qu'ERPLibre Home les pilote dans l'invité.

| Périphérique branché sur… | Voie | Ce qu'elle exige |
|---|---|---|
| l'**hôte libvirt** (ce poste, ou l'hyperviseur derrière un ProxyJump) | passage `<hostdev>`, attaché par `virsh` | un contrôleur USB dans la VM ; rien côté visionneuse |
| le **poste** qui ouvre `virt-viewer` | redirection USB SPICE (`usbredir`) | un affichage SPICE placé **avant** le VNC, des emplacements de redirection `spicevmc`, une session de visionneuse ouverte |

Prenez le passage quand le deck est sur la machine qui fait tourner la VM : il
tient sans visionneuse, peut revenir à chaque démarrage et suivre un
rebranchement. Prenez la redirection SPICE quand le deck est sur votre bureau
et la VM ailleurs : le deck suit la fenêtre de la visionneuse et revient au
poste à sa fermeture.

Un périphérique USB de l'hôte ne sert qu'**un** domaine en marche à la fois :
libvirt refuse de démarrer une seconde VM qui le tient, et
`startupPolicy='optional'` ne couvre pas un périphérique déjà pris.

### Le menu TODO

**TODO › Execute › Deploy › QEMU/KVM**, section **USB**, entrée
**Périphériques USB (Stream Deck, passage, SPICE)** :

- *Périphérique sur l'hôte libvirt* — lister les périphériques USB de cette
  machine (concentrateurs exclus) ; attacher un périphérique à une VM ; le
  détacher ; voir les périphériques USB d'une VM (chaque vue, contrôleurs
  USB, ordre des affichages, emplacements de redirection).
- *Périphérique sur ce poste (SPICE)* — ouvrir `virt-viewer` avec la
  redirection USB ; activer la redirection USB SPICE sur une VM.
- *Rebranchement* — rattachement auto au rebranchement (règle udev,
  correspondance).

La VM se choisit parmi les domaines libvirt locaux, puis les hôtes de
`~/.ssh/config` : un hôte distant est joint par son `ProxyJump` en
`qemu+ssh://<saut>/system`, et la liste des périphériques vient alors de
**cet** hyperviseur. Un hôte sans `ProxyJump` est refusé. Chaque plan est
montré — étapes sautées avec leur raison, puis les commandes — et ne s'exécute
qu'après confirmation. `sudo` ne précède `virsh` que pour un `qemu:///system`
local que le groupe `libvirt` n'ouvre pas, jamais pour `qemu+ssh`.

**La persistance se choisit à chaque attachement** :

- **live et config** — maintenant et à chaque démarrage ;
- **live seulement** — jusqu'à l'arrêt de la VM ;
- **config seulement** — à partir du prochain démarrage.

Une vue qui tient déjà le périphérique est sautée : attacher deux fois ne
change rien. La vue live est sautée quand la VM est éteinte. Une VM sans
contrôleur USB, ou au modèle `none`, est refusée. Le XML porte
`startupPolicy='optional'` : la VM démarre même deck débranché.

Deux périphériques identiques branchés rendent `VID:PID` ambigu pour
libvirt : le périphérique est alors épinglé par `BUS.DEV`, une adresse qui
change au rebranchement.

### Le CLI `script/qemu/usb_qemu.py`

Les mêmes plans, sans question — ce qui demande un accord passe par `--yes`.
Codes de sortie : `0` fait ou rien à faire, `1` échec, `2` usage, `3` accord
requis.

```bash
# Périphériques de l'hôte, decks en tête (marqués *) ; --json pour un script
./script/qemu/usb_qemu.py list
./script/qemu/usb_qemu.py list --uri qemu+ssh://<saut>/system

# Attacher : --live, --config ou les deux ; aucune n'est implicite
./script/qemu/usb_qemu.py attach <nom-vm> 0fd9:0080 --live --config
./script/qemu/usb_qemu.py attach <nom-vm> 3.5 --live    # BUS.DEV
./script/qemu/usb_qemu.py attach <nom-vm> 0fd9:0080 --live \
    --uri qemu+ssh://<saut>/system

# Détacher ; --yes relance ensuite le service deck de l'hôte
./script/qemu/usb_qemu.py detach <nom-vm> 0fd9:0080 --live --config --yes

# Options communes : --dry-run (commandes et XML, rien ne change), --no-sudo
```

Le sélecteur est `VID:PID` (préfixes `0x` admis) ou `BUS.DEV` tel que `list`
l'affiche. Un nom sysfs comme `3-5` est refusé : son second nombre est un
port, pas un numéro de périphérique. Un `VID:PID` non branché est admis pour
un détachement, et pour un attachement `--config` seul. Sur une URI distante,
`list` lit l'hyperviseur par `virsh nodedev-list`, pas le sysfs local.

### À l'installation

Le formulaire de déploiement porte la case **Attacher les Stream Deck branchés
(passage USB + SPICE)**, et les invites posent la même question ; les deux
n'apparaissent que si une VM choisie a un bureau. La cocher ajoute deux
options à `deploy_qemu.py` :

```bash
./script/qemu/deploy_qemu.py --name <nom-vm> --desktop \
    --usb-hostdev 0fd9:0080 --spice-usbredir --dry-run
```

- `--usb-hostdev VID:PID|BUS.DEV` (répétable) passe un périphérique de l'hôte
  avec `startupPolicy=optional`. Absent de l'hôte, il est ignoré avec un
  avertissement et la VM est créée quand même ; des périphériques identiques
  sont chacun épinglés par `bus.dev`.
- `--spice-usbredir` ajoute un affichage SPICE **avant** le VNC, avec ses
  emplacements de redirection : `virt-viewer` ouvre le premier affichage, et
  offre donc son menu *USB device selection*. L'affichage VNC reste pour les
  tunnels SSH et le diagnostic de console. VM graphique x86_64 seulement :
  une VM sans affichage, ou d'une autre architecture, est refusée avant tout
  téléchargement. `--usb-hostdev` est refusé sur s390x, qui n'a pas de bus
  USB.

Quand plusieurs VM se déploient d'un coup, les decks vont à la **première** VM
graphique seulement — les autres reçoivent quand même SPICE. Une VM recréée
ne retrouve les decks que si elle les avait à sa création. Avec l'outil
`erplibre_home_streamdeck`, l'installation dans l'invité reçoit toujours
`--stream-deck --autostart` : le service deck y démarre quelle que soit la
voie qui amène le deck.

### Redirection SPICE sur une VM existante

L'entrée *Activer la redirection USB SPICE sur une VM* lit la définition
enregistrée et n'ajoute que ce qui manque : un affichage SPICE déplacé ou
ajouté avant le VNC, un contrôleur `qemu-xhci`, deux emplacements `spicevmc`,
le canal de l'agent SPICE et — si vous l'acceptez — un filtre qui ne redirige
que le vendeur `0fd9`. Un changement d'affichage vaut au démarrage suivant :
une VM en marche n'est arrêtée qu'avec votre accord, redéfinie, puis
relancée. *Ouvrir virt-viewer avec la redirection USB* lance ensuite
`virt-viewer` avec le filtre de redirection automatique de `0fd9` : un deck
branché sur le poste suit la fenêtre ; les autres périphériques se choisissent
à la main dans **File › USB device selection**.

### Rattachement automatique au rebranchement

Un rebranchement donne au périphérique un nouveau numéro, et QEMU perd le
sien. Sur l'hôte libvirt, une règle udev lance une unité systemd root qui lit
la correspondance *périphérique → VM* et rattache le périphérique **en live**
à sa VM en marche. Elle ne touche jamais la définition enregistrée — la
persistance a été choisie à l'attachement.

| Fichier | Rôle |
|---|---|
| `/etc/udev/rules.d/85-erplibre-usb-passthrough.rules` | une ligne par vendeur de la correspondance (deck toujours) |
| `/etc/systemd/system/erplibre-usb-reattach@.service` | `Type=oneshot`, tourne en root |
| `/usr/local/libexec/erplibre-usb/` | une **copie** de `usb_qemu.py` et `qemu_usb.py` : l'unité root n'exécute jamais un fichier du checkout |
| `/etc/erplibre/usb-passthrough.json` | la correspondance, conservée au retrait sauf `--purge` |

```bash
# Sur l'hôte libvirt (se relance sous sudo au besoin)
./script/qemu/usb_qemu.py install-autoreattach [--vendor VID]...
./script/qemu/usb_qemu.py mapping add <nom-vm> 0fd9:0080 [--serial SÉRIE]
./script/qemu/usb_qemu.py mapping list
./script/qemu/usb_qemu.py mapping remove 0fd9:0080 --domain <nom-vm> [--serial SÉRIE]
./script/qemu/usb_qemu.py remove-autoreattach [--purge]

journalctl -u 'erplibre-usb-reattach@*'   # une ligne par décision
```

Le numéro de série ne compte que pour deux decks identiques destinés à deux
VM : une entrée dont la série correspond l'emporte sur une entrée sans. Au
retrait, sans `--serial`, toutes les entrées de ce modèle pour la VM partent,
et `--serial ""` ne retire que l'entrée sans série. Installer deux fois ne
change rien.

Pour un **hyperviseur distant**, *Rebranchement* installe depuis le menu : il
copie `usb_qemu.py` et `qemu_usb.py` dans un répertoire temporaire là-bas,
lance `ssh -t <saut> 'sudo python3 -I -B <tmp>/usb_qemu.py install-autoreattach'`,
puis efface le répertoire. Les correspondances passent ensuite par la copie
installée, `/usr/local/libexec/erplibre-usb/usb_qemu.py`, qui doit être
présente.

### Proxmox VE

Une attribution USB Proxmox (`qm set <vmid> -usbN host=…`) est **toujours
persistante** : elle est écrite dans la configuration de la VM et suit un
rebranchement par `VID:PID` sans règle udev. Il n'y a là ni choix live/config
ni voie SPICE. Le menu USB QEMU refuse un hyperviseur Proxmox et renvoie à
**TODO › Execute › Deploy › Proxmox VE**, entrée **Périphériques USB (Stream
Deck)**, décrite dans [`script/proxmox/README.fr.md`](../proxmox/README.fr.md).
La case du déploiement y existe aussi, et lit les decks du nœud à la création
de la VM.

### Le service deck de l'hôte lui-même

Un hôte qui fait tourner ERPLibre Home avec le Stream Deck tient le deck par
son unité utilisateur `erplibre-home-streamdeck.service` ; QEMU comme
spice-gtk le lui retirent. Avant un attachement live d'un deck, ou une
redirection depuis ce poste, l'outil **demande** : *non* annule, *oui* arrête
le service une fois la confirmation finale donnée ; un attachement config
seul, ou à une VM arrêtée, ne demande rien. Si l'attachement échoue ensuite,
l'outil propose de relancer le service. Un déploiement qui passe les decks à
une nouvelle VM pose la même question avant le démarrage de la VM : *non* crée
la VM sans le passage. Détacher un deck en live propose de le relancer. Le CLI s'arrête en code `3` au lieu de demander, et
`--yes` donne l'accord ; avec `--config` seul, il n'affiche qu'une note. Ce
service redémarre aussi de lui-même au rebranchement du deck : sur un hôte qui
associe un deck à une VM, coupez son démarrage automatique (**TODO › Execute ›
ERPLibre Home**, réglages du deck).

### Vérifier sur du vrai matériel

Avec un vrai Stream Deck :

1. `./script/qemu/usb_qemu.py list` sur l'hôte libvirt montre le deck en
   tête, marqué `*`.
2. Attachez-le, puis
   `sudo virsh dumpxml <nom-vm> | grep -A6 hostdev` montre le périphérique.
3. Dans l'invité, `cat /sys/bus/usb/devices/*/idVendor` liste `0fd9`, et
   `./script/install/erplibre_home_deck.sh --check`, lancé depuis le
   checkout ERPLibre de l'invité, rend 0 une fois une session graphique
   ouverte.
4. Les **boutons du deck s'affichent** depuis l'ERPLibre Home de l'invité.
5. Démarrez la VM deck débranché : elle démarre quand même.
6. Avec le rattachement auto : débranchez puis rebranchez le deck sur
   l'hôte ; le journal de `erplibre-usb-reattach@*` montre le rattachement,
   et les boutons reviennent.
7. SPICE : ouvrez `virt-viewer` depuis le menu. Il ouvre l'affichage SPICE,
   pas le VNC ; **File › USB device selection** liste les périphériques du
   poste, et le deck y est coché.
8. Détachement : le deck revient à l'hôte, et la relance du service deck de
   l'hôte est proposée.

## Accès SSH depuis une autre machine (ProxyJump)

Avec le réseau NAT par défaut, la VM n'est joignable que **depuis l'hôte
KVM**. Pour l'atteindre depuis une autre machine **sans toucher au réseau**,
utilisez l'hôte comme rebond (il joint déjà la VM). Récupérez l'IP de la VM
avec `sudo virsh domifaddr <nom-vm>`, puis depuis l'autre machine :

<!-- [common] -->
```bash
# Rebond SSH vers la VM / jump through the KVM host
ssh -J user@<ip-hote> erplibre@<ip-vm>

# Tunnel d'un service, ex. Odoo 8069 / tunnel a service, then http://localhost:8069
ssh -L 8069:<ip-vm>:8069 user@<ip-hote>
```

<!-- [en] -->
To make it permanent, add this to `~/.ssh/config` on the other machine (then
just `ssh myvm`):

<!-- [fr] -->
Pour le rendre permanent, ajoutez ceci à `~/.ssh/config` sur l'autre machine
(ensuite `ssh myvm` suffit) :

<!-- [common] -->
```text
Host myvm
    HostName <ip-vm>            # ex. 192.168.122.50 (reseau NAT)
    User erplibre
    ProxyJump user@<ip-hote>    # IP LAN de l'hote KVM
```

<!-- [en] -->
This works over Wi-Fi and needs no VM shutdown — the simplest option for
personal access. Prefer a bridge (below) if the VM must be a full server
exposed on the LAN.

## 3D acceleration (host GPU)

A graphical VM without acceleration renders everything on the CPU — the
desktop, and the Android emulator running inside it. The deployment therefore
takes the host GPU **by default** (`--gpu auto`): when the host exposes a
render node, the VM gets a virtio-GPU with `accel3d` plus an `egl-headless`
display that carries the OpenGL context **beside** the VNC console — it opens
no port and replaces nothing. No render node, no 3D, and the deployment says
why instead of quietly falling back.

```bash
ls /dev/dri/renderD*             # the GPU QEMU can use — empty means no 3D
sudo virsh dumpxml <vm-name> | grep -A2 -E "accel3d|egl-headless"
```

An existing VM is adjusted from the TODO menu **while it is shut off**:
libvirt only reads these settings when QEMU starts. `QEMU/KVM › List VMs ›
[2] Change the state`, then either accept *Adjust hardware before starting*,
or take `[3] Adjust hardware only`. In a form when Textual is available, in
prompts otherwise, it sets:

- **vCPU, RAM, autostart** — the plain sizing knobs.
- **CPU mode** — `host-passthrough` (what the fleet uses) hands the host CPU
  instructions over as they are: that is what makes nested virtualization
  possible *inside* the VM. `host-model` describes an equivalent model,
  migratable to another machine.
- **Screens** — the virtio-GPU `heads`, which becomes `max_outputs` on the
  QEMU command line. `vram` is deliberately *not* offered: on a virtio-GPU
  libvirt writes it into the XML and QEMU never receives it (check with
  `virsh domxml-to-native` — only `max_outputs` shows up). Only qxl uses vram.
- **Network** — the libvirt networks and the host bridges, the latter to put
  the VM on the LAN (see the bridge section below). Switching keeps the MAC
  address and the PCI slot, so the guest finds *its* card again — same
  interface name, same DHCP lease.

Two things worth knowing:

- A host that is **itself a VM** has no render node unless a GPU was handed
  down to it. Nested without passthrough, 3D is out of reach: the Android
  emulator then runs on SwiftShader, and no option changes that.
- Once the VM does have 3D, the emulator can be tried with `-gpu host`
  instead of its default `-gpu swangle`: `EL_EMULATOR_GPU=host ./todo.sh`.
  It stays a manual test — an emulator whose GL context fails hangs instead
  of falling back, so `swangle` remains the default.

## QEMU inside QEMU (nested) & exposing the VM via a bridge

If the KVM host is **itself a VM** (QEMU-in-QEMU), the deployment works only
when **nested virtualization** is enabled on the outer/physical host and the
middle VM uses CPU mode `host-passthrough`. Check from inside the KVM host
(the first command must be non-empty):

<!-- [fr] -->
Ça marche en Wi-Fi et sans arrêter la VM — l'option la plus simple pour un
accès personnel. Préférez un pont (ci-dessous) si la VM doit être un serveur
à part entière exposé sur le LAN.

## Accélération 3D (GPU de l'hôte)

Une VM graphique sans accélération rend tout par le processeur — le bureau
comme l'émulateur Android qui tourne dedans. Le déploiement prend donc le GPU
de l'hôte **par défaut** (`--gpu auto`) : si l'hôte expose un nœud de rendu,
la VM reçoit un virtio-GPU avec `accel3d` et un affichage `egl-headless` qui
porte le contexte OpenGL **à côté** de la console VNC — il n'ouvre aucun port
et ne remplace rien. Pas de nœud de rendu, pas de 3D, et le déploiement dit
pourquoi au lieu de retomber en silence.

```bash
ls /dev/dri/renderD*             # le GPU utilisable par QEMU — vide : pas de 3D
sudo virsh dumpxml <nom-vm> | grep -A2 -E "accel3d|egl-headless"
```

Une VM déjà installée se règle depuis le menu TODO **pendant qu'elle est
éteinte** : libvirt ne lit ces réglages qu'au démarrage de QEMU. `QEMU/KVM ›
Liste des VM › [2] Changer l'état`, puis acceptez *Régler le matériel avant de
démarrer*, ou prenez `[3] Régler le matériel seulement`. En formulaire si
Textual est présent, en invites sinon, il règle :

- **vCPU, RAM, démarrage automatique** — le dimensionnement ordinaire.
- **Mode CPU** — `host-passthrough` (celui du parc) donne les instructions du
  processeur hôte telles quelles : c'est lui qui rend la virtualisation
  imbriquée possible *dans* la VM. `host-model` décrit un modèle équivalent,
  migrable vers une autre machine.
- **Écrans** — le `heads` du virtio-gpu, qui devient `max_outputs` sur la
  ligne QEMU. La `vram` n'est délibérément *pas* proposée : sur un virtio-gpu,
  libvirt l'écrit dans le XML et QEMU ne la reçoit jamais (à vérifier avec
  `virsh domxml-to-native` : seul `max_outputs` y apparaît). Seul qxl la
  consomme.
- **Réseau** — les réseaux libvirt et les ponts de l'hôte, ces derniers pour
  poser la VM sur le LAN (voir la section du pont plus bas). Le basculement
  garde l'adresse MAC et l'emplacement PCI : l'invité retrouve *sa* carte,
  donc son nom d'interface et son bail DHCP.

Deux choses à savoir :

- Un hôte qui est **lui-même une VM** n'a aucun nœud de rendu, sauf si un GPU
  lui a été transmis. Imbriqué sans passthrough, la 3D est hors d'atteinte :
  l'émulateur Android tourne alors sur SwiftShader, et aucune option n'y
  change rien.
- Quand la VM a la 3D, l'émulateur peut être essayé en `-gpu host` plutôt
  qu'en `-gpu swangle`, son défaut : `EL_EMULATOR_GPU=host ./todo.sh`. Ça
  reste un essai manuel — un émulateur dont le contexte GL échoue reste pendu
  au lieu de retomber, d'où `swangle` par défaut.

## QEMU dans QEMU (imbriqué) & exposer la VM via un pont

Si l'hôte KVM est **lui-même une VM** (QEMU dans QEMU), le déploiement ne
fonctionne que si la **virtualisation imbriquée** est activée sur l'hôte
physique et que la VM intermédiaire utilise le mode CPU `host-passthrough`.
Vérifiez depuis l'hôte KVM (la première commande doit être non vide) :

<!-- [common] -->
```bash
grep -E -o '(vmx|svm)' /proc/cpuinfo | sort -u   # extensions visibles / visible
# Sur l'hote PHYSIQUE / on the PHYSICAL host:
cat /sys/module/kvm_intel/parameters/nested      # Intel -> Y/1
cat /sys/module/kvm_amd/parameters/nested        # AMD   -> Y/1
```

<!-- [en] -->
To enable nesting on the physical host (Intel shown; use `kvm_amd` on AMD),
then recreate the middle VM with `host-passthrough`:

<!-- [fr] -->
Pour activer l'imbrication sur l'hôte physique (Intel montré ; `kvm_amd` sur
AMD), puis recréer la VM intermédiaire en `host-passthrough` :

<!-- [common] -->
```bash
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel   # ou / or reboot
```

<!-- [en] -->
On **s390x and arm64** the parameter lives on the `kvm` module itself, not on
`kvm_intel` / `kvm_amd` — and `/sys/module/kvm/parameters/nested` does not even
exist on x86. Reading the wrong file returns a reassuring `0` that commands
nothing:

<!-- [fr] -->
Sur **s390x et arm64**, le paramètre vit sur le module `kvm` lui-même, et non
sur `kvm_intel` / `kvm_amd` — et `/sys/module/kvm/parameters/nested` n'existe
même pas sur x86. Lire le mauvais fichier renvoie un `0` rassurant qui ne
commande rien :

<!-- [common] -->
```bash
echo "options kvm nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm && sudo modprobe kvm               # ou / or reboot
```

<!-- [en] -->
`nested` on a machine means « let MY guests run VMs ». To accelerate a VM
created on host H, the setting belongs to the hypervisor **above** H, not to H
itself. The one command that settles it, run on H:

<!-- [fr] -->
`nested` sur une machine signifie « j'autorise MES invités à faire tourner des
VM ». Pour accélérer une VM créée sur l'hôte H, le réglage appartient à
l'hyperviseur **au-dessus** de H, pas à H. La commande qui tranche, sur H :

<!-- [common] -->
```bash
ls -l /dev/kvm     # absent -> pas d'imbrication, tout sera émulé
```

<!-- [en] -->
Measured on an s390x host that was itself a KVM guest without nesting:
`/dev/kvm` absent, `virsh dumpxml` showing `<domain type='qemu'>`, and a
7 min 30 boot instead of well under a minute. `systemd-detect-virt` inside the
VM is **not** proof of acceleration — on s390x, QEMU fabricates the STSI answer
and reports `kvm` even under TCG. Only `<domain type=…>` on the host is
conclusive.

If nesting is unavailable, QEMU still runs via software emulation (TCG) — it
works but is slow.

### Bridge for external access

A NAT VM is isolated; a **bridged** VM gets an IP directly on the LAN,
reachable by any machine. On the KVM host, create a bridge `br0` over the
physical NIC (**wired only** — Wi-Fi cannot be bridged). netplan (Ubuntu
server) — replace `enp3s0` with your interface:

<!-- [fr] -->
Mesuré sur un hôte s390x lui-même invité KVM sans imbrication : `/dev/kvm`
absent, `virsh dumpxml` affichant `<domain type='qemu'>`, et un démarrage de
7 min 30 au lieu de bien moins d'une minute. `systemd-detect-virt` dans la VM
ne prouve **pas** l'accélération — sur s390x, QEMU fabrique la réponse STSI et
annonce `kvm` même en TCG. Seul `<domain type=…>` sur l'hôte fait foi.

Si l'imbrication est indisponible, QEMU tourne quand même en émulation
logicielle (TCG) — ça marche mais c'est lent.

### Pont pour l'accès externe

Une VM en NAT est isolée ; une VM **pontée** obtient une IP directement sur le
LAN, joignable par n'importe quelle machine. Sur l'hôte KVM, créez un pont
`br0` sur la carte physique (**filaire uniquement** — le Wi-Fi ne se ponte
pas). netplan (Ubuntu serveur) — remplacez `enp3s0` par votre interface :

<!-- [common] -->
```yaml
# /etc/netplan/01-br0.yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0: {dhcp4: no, dhcp6: no}
  bridges:
    br0:
      interfaces: [enp3s0]
      dhcp4: yes
      parameters: {stp: false, forward-delay: 0}
```

<!-- [en] -->
Apply safely (auto-reverts if you lose the connection) and verify — or use
NetworkManager (Ubuntu desktop):

<!-- [fr] -->
Appliquez avec filet de sécurité (annulation auto en cas de coupure) et
vérifiez — ou via NetworkManager (Ubuntu bureau) :

<!-- [common] -->
```bash
# netplan
sudo netplan try && sudo netplan apply
ip addr show br0        # br0 porte l'IP du LAN / br0 holds the LAN IP

# NetworkManager (alternative)
nmcli con add type bridge ifname br0 con-name br0
nmcli con add type ethernet ifname enp3s0 master br0 con-name br0-port
nmcli con modify br0 ipv4.method auto
nmcli con down "Wired connection 1" ; nmcli con up br0
```

<!-- [en] -->
Then attach the VM to the bridge — **either at creation**:

<!-- [fr] -->
Rattachez ensuite la VM au pont — **soit à la création** :

<!-- [common] -->
```bash
sudo ./script/qemu/deploy_qemu.py --name <nom-vm> --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub --network bridge=br0,model=virtio -y --force
```

<!-- [en] -->
**or by editing a VM already created**: stop it, replace its `<interface>`
block (`type='network'` / `<source network='default'/>` → `type='bridge'` /
`<source bridge='br0'/>`), then start it again:

<!-- [fr] -->
**soit par édition d'une VM déjà créée** : arrêtez-la, remplacez son bloc
`<interface>` (`type='network'` / `<source network='default'/>` →
`type='bridge'` / `<source bridge='br0'/>`), puis redémarrez-la :

<!-- [common] -->
```bash
sudo virsh shutdown <nom-vm>
sudo virsh edit <nom-vm>        # mettre l'interface en bridge=br0
sudo virsh start <nom-vm>
sudo virsh domifaddr <nom-vm>   # nouvelle IP LAN / new LAN IP
```

<!-- [en] -->
The VM now gets a LAN IP from your router, reachable by other machines. From
the Internet you additionally need a port-forward on your router (or a VPN);
in a nested setup the outer host must also forward/expose the middle VM.

<!-- [fr] -->
La VM obtient maintenant une IP LAN de votre routeur, joignable par les autres
machines. Depuis Internet, il faut en plus une redirection de port sur votre
routeur (ou un VPN) ; en configuration imbriquée, l'hôte externe doit aussi
rediriger/exposer la VM intermédiaire.
