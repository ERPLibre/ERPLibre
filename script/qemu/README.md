
# QEMU/KVM — Linux VM deployment (Ubuntu / Debian / Fedora)

`deploy_qemu.py` deploys a Linux VM (libvirt/KVM) from an official cloud
image, using `qemu-img` + `cloud-init` + `virt-install`. Pick the
distribution with `--distro` (`ubuntu` default, `debian`, `fedora`) and the
release with `--version`; run `--list-images` to see the full catalogue with
minimum specs. It:

1. **Downloads the cloud image by itself** (cached, no double download).
2. Converts it to a dedicated qcow2 working disk and resizes it.
3. Generates `user-data` / `meta-data` and builds the `seed.iso` (cloud-init).
4. Runs `virt-install` importing the disk + the seed as a CD-ROM.
5. Waits for the DHCP lease and prints the SSH command.

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

```bash
sudo apt install qemu-utils virtinst libvirt-clients cloud-image-utils \
    libvirt-daemon-system qemu-system-x86
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt,kvm "$USER"   # re-login / reconnectez-vous
```

`libvirt-daemon-system` provides the `libvirtd` daemon (and the
`/var/run/libvirt/libvirt-sock` socket) and `qemu-system-x86` the emulator —
without them `virt-install` fails with *"Failed to connect socket to
'/var/run/libvirt/libvirt-sock'"*. The script installs and starts them for
you; this manual command is only needed if you prefer to prepare the host
yourself or run with `--no-install-deps`.

## Usage

Simplest form — the image is downloaded automatically (path derived from
`--version`, cached in `/var/lib/libvirt/images/iso`):

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub
```

Download (and verify) an image without creating a VM:

```bash
sudo ./script/qemu/deploy_qemu.py --download-only --version 24.04 --verify
```

Deploy with an interactive password instead of an SSH key:

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 --ask-password
```

Larger VM (8 GB RAM, 8 vCPU, 120 GB disk), overwriting an existing disk:

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --memory 8192 --vcpus 8 --disk-size 120G --ask-password --force
```

Preview what would happen, without doing anything (no sudo, no download):

```bash
./script/qemu/deploy_qemu.py --name test-vm --version 24.04 --dry-run
```

Non-interactive deployment (accept dependency install automatically):

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub -y
```

Catalog, per architecture (`deploy_qemu.py` is the source of truth):

| Distro | Versions | amd64 | arm64 | s390x |
|---|---|:-:|:-:|:-:|
| ubuntu | `24.04` (default), `25.10`, `26.04` | ✔ | ✔ | ✔ |
| debian | `11`, `12` (default), `13` | ✔ | ✔ | — |
| fedora | `41`, `42` (default), `43`, `44` | ✔ | ✔ | `43` only |
| almalinux | `9` (default), `10` | ✔ | ✔ | ✔ |
| rocky | `9`, `10` (default) | ✔ | ✔ | ✔ |
| opensuse | `16.0` (default), `tumbleweed` | ✔ | ✔ | ✔ |
| arch | `latest` | ✔ | — | — |

Fedora builds s390x only for the current release, and on a separate tree
(`fedora-secondary`) — hence the single version there.

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

```bash
virsh list --all
virsh console test-vm                    # Ctrl+] to quit / pour quitter
virsh domifaddr test-vm --source lease   # find the IP / trouver l'IP
ssh erplibre@<IP>
```

The default user is `erplibre` (change it with `--user`).

## Via the TODO menu

The script is integrated into the interactive assistant. Run `make todo` (or
`./script/todo/todo.py`), then go to **Execute → Deploy → QEMU/KVM - Deploy an
Ubuntu VM (libvirt)**. From there you can deploy a VM, preview a dry-run,
download an image, list VMs and show a VM IP address — the menu asks for the
parameters and builds the command for you.

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

Each tool is filtered per VM — by architecture, desktop flavour and package
family — and its disk cost is added to the plan before anything is created.

## Main options

- `--distro` — `ubuntu` (default), `debian` or `fedora`.
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

## Login guide (`/etc/motd`)

Every VM greets you, at each interactive SSH login, with the commands of
**its own** distribution — `apt`, `dnf`, `zypper` or `pacman` — plus the
ERPLibre ones (edit the server, restart it, update modules, update Odoo,
inspect the instance, open the TODO menu). It is written by cloud-init, so
it is there from the first boot: before ERPLibre is installed, and still
there if that installation fails, which is exactly when you log in by hand.

`--dry-run` prints the generated guide along with the rest of the user-data.
The guide is not shown to `ssh host 'command'`, so it never pollutes an
installation log.

The host's git identity travels with it, into the VM's `~/.gitconfig`: a
commit made in the VM then carries your name instead of
`erplibre@<vm-name>`. The editor follows the same route — `core.editor`, the
`config.conf` line of the guide, and the package installed in the VM all
come from one table, so the guide never names a command the VM does not
have.

## Managing VMs

List, stop and remove VMs (the qcow2 disk under `/var/lib/libvirt/images`
is kept unless you delete it):

```bash
sudo virsh list --all          # toutes les VM et leur état / all VMs and state
sudo virsh shutdown <nom-vm>   # arrêt propre ACPI / graceful shutdown
sudo virsh destroy <nom-vm>    # arrêt forcé / force off (pull the plug)
sudo virsh undefine <nom-vm>   # supprime la définition / remove definition
sudo virsh domifaddr <nom-vm>  # adresse IP de la VM / VM IP address
```

`destroy` only powers the VM off (disk kept); `undefine` removes its
definition. To fully recreate a VM with the same name, `destroy` + `undefine`
it first, or redeploy with `--force`.

## SSH access from another machine (ProxyJump)

With the default NAT network the VM is reachable **only from the KVM host**.
To reach it from another machine **without changing the network**, use the
host as a jump host (it already reaches the VM). Get the VM IP with
`sudo virsh domifaddr <nom-vm>`, then from the other machine:

```bash
# Rebond SSH vers la VM / jump through the KVM host
ssh -J user@<ip-hote> erplibre@<ip-vm>

# Tunnel d'un service, ex. Odoo 8069 / tunnel a service, then http://localhost:8069
ssh -L 8069:<ip-vm>:8069 user@<ip-hote>
```

To make it permanent, add this to `~/.ssh/config` on the other machine (then
just `ssh myvm`):

```text
Host myvm
    HostName <ip-vm>            # ex. 192.168.122.50 (reseau NAT)
    User erplibre
    ProxyJump user@<ip-hote>    # IP LAN de l'hote KVM
```

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

```bash
grep -E -o '(vmx|svm)' /proc/cpuinfo | sort -u   # extensions visibles / visible
# Sur l'hote PHYSIQUE / on the PHYSICAL host:
cat /sys/module/kvm_intel/parameters/nested      # Intel -> Y/1
cat /sys/module/kvm_amd/parameters/nested        # AMD   -> Y/1
```

To enable nesting on the physical host (Intel shown; use `kvm_amd` on AMD),
then recreate the middle VM with `host-passthrough`:

```bash
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel   # ou / or reboot
```

On **s390x and arm64** the parameter lives on the `kvm` module itself, not on
`kvm_intel` / `kvm_amd` — and `/sys/module/kvm/parameters/nested` does not even
exist on x86. Reading the wrong file returns a reassuring `0` that commands
nothing:

```bash
echo "options kvm nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm && sudo modprobe kvm               # ou / or reboot
```

`nested` on a machine means « let MY guests run VMs ». To accelerate a VM
created on host H, the setting belongs to the hypervisor **above** H, not to H
itself. The one command that settles it, run on H:

```bash
ls -l /dev/kvm     # absent -> pas d'imbrication, tout sera émulé
```

Measured on an s390x host that was itself a KVM guest without nesting:
`/dev/kvm` absent, `virsh dumpxml` showing `<domain type='qemu'>`, and a
7 min 30 boot instead of well under a minute. `systemd-detect-virt` inside the
VM is **not** proof of acceleration — on s390x, QEMU fabricates the STSI answer
and reports `kvm` even under TCG. Only `<domain type=…>` on the host is
conclusive.

If nesting is unavailable, QEMU still runs via software emulation (TCG) — it
works but is slow.

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

Apply safely (auto-reverts if you lose the connection) and verify — or use
NetworkManager (Ubuntu desktop):

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

Then attach the VM to the bridge — **either at creation**:

```bash
sudo ./script/qemu/deploy_qemu.py --name <nom-vm> --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub --network bridge=br0,model=virtio -y --force
```

**or by editing a VM already created**: stop it, replace its `<interface>`
block (`type='network'` / `<source network='default'/>` → `type='bridge'` /
`<source bridge='br0'/>`), then start it again:

```bash
sudo virsh shutdown <nom-vm>
sudo virsh edit <nom-vm>        # mettre l'interface en bridge=br0
sudo virsh start <nom-vm>
sudo virsh domifaddr <nom-vm>   # nouvelle IP LAN / new LAN IP
```

The VM now gets a LAN IP from your router, reachable by other machines. From
the Internet you additionally need a port-forward on your router (or a VPN);
in a nested setup the outer host must also forward/expose the middle VM.
