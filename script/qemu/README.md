
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
| opensuse | `tumbleweed` | ✔ | ✔ | ✔ |
| arch | `latest` | ✔ | — | — |

Fedora builds s390x only for the current release, and on a separate tree
(`fedora-secondary`) — hence the single version there.

`opensuse` is openSUSE Tumbleweed, the only entry whose qpdf (12.3.2) already
clears the pikepdf threshold: the half-hour qpdf build never runs there, which
matters under s390x emulation.

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

Run `./script/qemu/deploy_qemu.py --help` for the full list.

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
