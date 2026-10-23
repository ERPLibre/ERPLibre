
# Deploying VMs on a Proxmox VE host

Two different things live in this directory:

- `install_proxmox.sh` turns a Debian into a Proxmox hypervisor. See
  `script/qemu/README.md`, which documents the `proxmox` distro of the
  deployment catalog.
- `proxmox_deploy.py` deploys VMs **on** such a host, from
  `TODO › Execute › Deploy › Proxmox VE`, right under `QEMU/KVM`.
- `host_perf_audit.py` measures, read-only, what limits the performance of
  such a host (or of any Linux server). See
  [Host performance audit](#host-performance-audit-read-only).

## The whole difference: the hypervisor is elsewhere

With QEMU/KVM, the hypervisor is the machine running the script. With Proxmox
it is somewhere else, so the first question is **which host** — and the answer
is remembered for the session. Three ways, all offered by the menu:

1. **From the local QEMU VMs** — a `proxmox` VM deployed here. Its address
   comes from the DHCP lease, nothing to retype.
2. **By address** — `user@host`, plus an optional SSH jump.
3. **From `~/.ssh/config`** — the alias already carries user, port and
   ProxyJump; nothing else is asked.

The chosen host is then **checked**, not assumed: `pveversion` proves it is a
Proxmox, `id -u` and `sudo -n true` decide whether commands need `sudo`, and an
unknown SSH host key is offered for recording (with `ssh-keyscan`, never by
disabling the check — a hypervisor is not a throwaway VM).

```bash
# Ce que l'outil envoie, et qu'on peut rejouer à la main :
ssh erplibre@pve1 sudo sh -c 'qm list'
ssh erplibre@pve1 sudo sh -c 'pvesm status --content images'
```

## Why SSH and `qm`, not the REST API

The API needs a token or a ticket to create and renew. `qm` is the path every
Proxmox administrator knows, the repository already manages SSH access
(`~/.ssh/config`, ProxyJump, keys), and the commands stay readable in the log —
so they can be replayed by hand. That is how every failure of this module was
diagnosed.

`sudo sh -c '<whole command>'` and not `sudo <command>`: these commands are
sequences and redirections. Prefixing with sudo would elevate only the first
word, and the redirection would still be the unprivileged shell's.

## Four traps met on a real host

A Proxmox installed **on Debian** has no `vmbr0` — the ISO installer creates
one, that procedure does not. And `qm create` requires a bridge.

The menu offers an **internal** bridge (`vmbr0`, `10.10.10.1/24`, NAT through
the uplink). Never adding the physical NIC to a bridge is deliberate: that
moves the host address and cuts the SSH session in progress — remotely, there
is no way back. A LAN-facing bridge is printed as a stanza to apply from a
console.

On an internal bridge no DHCP answers, so the address is **static**, derived
from the VMID — and therefore known before the VM boots. Looking for it
afterwards was absurd.

The Debian cloud image does not ship `qemu-guest-agent`, so Proxmox cannot tell
the address of a DHCP guest: it does not hand out the leases. The fallback is
the host's own neighbour table (`ip neigh`), which needs nothing from the guest.

## The menu, entry by entry

The seventeen QEMU/KVM entries have their counterpart. Four of them are the
**same code**, because it is the same work: reopening the install monitoring,
the remote desktop tunnel, the Android emulator and the image catalog. They
reach Proxmox guests through the `~/.ssh/config` entries that entry 13 writes,
with the Proxmox host as ProxyJump.

```text
[1] Déployer une VM        [8]  Redimensionner un disque   [15] Émulateur Android *
[2] Prévisualiser          [9]  Effacer des VM             [16] Catalogue d'images *
[3] Télécharger une image  [10] Nettoyer (orphelins)       [17] Exemple (dry-run)
[4] Rouvrir le suivi *     [11] Tester une VM (Odoo)       [18] Changer d'hôte
[5] Lister (qm list)       [12] Statistiques               [19] Audit de performance
[6] Adresse IP d'une VM    [13] Configuration SSH
[7] Console d'une VM       [14] Tunnel bureau distant *
                                        * code partagé avec le menu QEMU/KVM
```

## Host performance audit (read-only)

`host_perf_audit.py` samples `/proc` and `/sys` every `--interval` seconds
(5 by default) for `--duration` (`60`, `30s`, `10m`, `2h`, `1h30m`; 1 second
to 7 days), then gives a verdict per resource — `ok`, `watch` or
`limiting` — for the processor, memory, disks and network, the answer to
"are SSD disks justified?", and the settings worth considering (ZFS
compression and atime, ARC maximum, `vm.swappiness`, VM disk options…),
each **printed** with the command that would apply it. Nothing is ever
changed.

It covers pressure stall information (`/proc/pressure`), per-disk
utilisation and wait (rotational disks are judged on utilisation and wait,
SSD and NVMe on wait only), swap activity, ZFS (ARC hit ratio, pool fill,
fragmentation, health, latency) and, on a Proxmox host with cgroup v2, each
running container and VM, named from `/etc/pve`. A pool's disks are read
from its own vdevs (`zpool status -P -L`): an idle backup HDD outside any
pool never makes the answer "yes, buy SSD".

It is a single file, standard library only, runnable by the `python3` of a
host from Debian 10 on. Entry `[19]` of this menu sends it to the
remembered host over `ssh -T` with the file on stdin, or runs it on this
machine; `TODO › Execute › Production` also runs it locally. Ctrl-C stops
the measurement early and still prints the report when the script runs on
the host itself; over ssh, a local Ctrl-C closes the connection and the
report is lost. `--json` prints a document with stable keys, `--csv FILE`
keeps the raw samples; a write error on it (full disk) disables the file,
not the audit. Each one-time command (`zpool`, `zfs`, `smartctl`) is
abandoned after 20 s, even when stuck on a suspended pool, and `smartctl`
leaves a disk in standby asleep. Exit codes: 0 audit done, 2 could not run, 130
interrupted before measuring.

```bash
./script/proxmox/host_perf_audit.py --duration 10m
sudo ./script/proxmox/host_perf_audit.py --duration 24h --csv /var/tmp/perf.csv
ssh -T root@pve.example.org python3 -I - --duration 2h < script/proxmox/host_perf_audit.py
```

## Verified

Deploying a VM inside a Proxmox that itself runs in a libvirt VM: image
downloaded on the host, internal bridge created, static address, cloud-init
user and key, disk resized, `qm start`. Then `ssh vm-essai` from the outside
reaches it through the jump — three nested levels. Resize `12G → 16G`, delete
with `--purge`, orphan scan: all checked against Proxmox VE 9.2.11.
