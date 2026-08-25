
# Deploying VMs on a Proxmox VE host

Two different things live in this directory:

- `install_proxmox.sh` turns a Debian into a Proxmox hypervisor. See
  `script/qemu/README.md`, which documents the `proxmox` distro of the
  deployment catalog.
- `proxmox_deploy.py` deploys VMs **on** such a host, from
  `TODO › Execute › Deploy › Proxmox VE`, right under `QEMU/KVM`.

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
[5] Lister (qm list)       [12] Statistiques
[6] Adresse IP d'une VM    [13] Configuration SSH
[7] Console d'une VM       [14] Tunnel bureau distant *
                                        * code partagé avec le menu QEMU/KVM
```

## Verified

Deploying a VM inside a Proxmox that itself runs in a libvirt VM: image
downloaded on the host, internal bridge created, static address, cloud-init
user and key, disk resized, `qm start`. Then `ssh vm-essai` from the outside
reaches it through the jump — three nested levels. Resize `12G → 16G`, delete
with `--purge`, orphan scan: all checked against Proxmox VE 9.2.11.
