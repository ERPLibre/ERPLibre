<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Deploying VMs on a Proxmox VE host

<!-- [fr] -->
# Déployer des VM sur un hôte Proxmox VE

<!-- [en] -->
Two different things live in this directory:

- `install_proxmox.sh` turns a Debian into a Proxmox hypervisor. See
  `script/qemu/README.md`, which documents the `proxmox` distro of the
  deployment catalog.
- `proxmox_deploy.py` deploys VMs **on** such a host, from
  `TODO › Execute › Deploy › Proxmox VE`, right under `QEMU/KVM`.

<!-- [fr] -->
Deux choses différentes vivent dans ce répertoire :

- `install_proxmox.sh` transforme une Debian en hyperviseur Proxmox. Voir
  `script/qemu/README.fr.md`, qui documente la distro `proxmox` du catalogue
  de déploiement.
- `proxmox_deploy.py` déploie des VM **sur** un tel hôte, depuis
  `TODO › Execute › Deploy › Proxmox VE`, juste sous `QEMU/KVM`.

<!-- [en] -->
## The whole difference: the hypervisor is elsewhere

With QEMU/KVM, the hypervisor is the machine running the script. With Proxmox
it is somewhere else, so the first question is **which host** — and the answer
is remembered for the session. Three ways, all offered by the menu:

1. **From the local QEMU VMs** — a `proxmox` VM deployed here. Its address
   comes from the DHCP lease, nothing to retype.
2. **By address** — `user@host`, plus an optional SSH jump.
3. **From `~/.ssh/config`** — the alias already carries user, port and
   ProxyJump; nothing else is asked.

<!-- [fr] -->
## Toute la différence : l'hyperviseur est ailleurs

Avec QEMU/KVM, l'hyperviseur est la machine qui exécute le script. Avec
Proxmox il est ailleurs : la première question est donc **quel hôte** — et la
réponse est retenue pour la session. Trois voies, toutes proposées par le menu :

1. **Depuis les VM QEMU locales** — une VM `proxmox` déployée ici. Son adresse
   vient du bail DHCP, rien à retaper.
2. **Par adresse** — `utilisateur@hôte`, plus un rebond SSH facultatif.
3. **Depuis `~/.ssh/config`** — l'alias porte déjà l'utilisateur, le port et le
   ProxyJump ; on ne demande rien d'autre.

<!-- [en] -->
The chosen host is then **checked**, not assumed: `pveversion` proves it is a
Proxmox, `id -u` and `sudo -n true` decide whether commands need `sudo`, and an
unknown SSH host key is offered for recording (with `ssh-keyscan`, never by
disabling the check — a hypervisor is not a throwaway VM).

<!-- [fr] -->
L'hôte choisi est ensuite **vérifié**, pas supposé : `pveversion` prouve que
c'en est un, `id -u` et `sudo -n true` décident s'il faut `sudo`, et une clé
d'hôte inconnue est proposée à l'enregistrement (par `ssh-keyscan`, jamais en
désactivant la vérification — un hyperviseur n'est pas une VM jetable).

<!-- [common] -->
```bash
# Ce que l'outil envoie, et qu'on peut rejouer à la main :
ssh erplibre@pve1 sudo sh -c 'qm list'
ssh erplibre@pve1 sudo sh -c 'pvesm status --content images'
```

<!-- [en] -->
## Why SSH and `qm`, not the REST API

The API needs a token or a ticket to create and renew. `qm` is the path every
Proxmox administrator knows, the repository already manages SSH access
(`~/.ssh/config`, ProxyJump, keys), and the commands stay readable in the log —
so they can be replayed by hand. That is how every failure of this module was
diagnosed.

`sudo sh -c '<whole command>'` and not `sudo <command>`: these commands are
sequences and redirections. Prefixing with sudo would elevate only the first
word, and the redirection would still be the unprivileged shell's.

<!-- [fr] -->
## Pourquoi SSH et `qm`, pas l'API REST

L'API demande un jeton ou un ticket à créer et à renouveler. `qm` est la voie
que tout administrateur Proxmox connaît, le dépôt sait déjà gérer des accès SSH
(`~/.ssh/config`, ProxyJump, clés), et les commandes restent lisibles dans le
journal — donc rejouables à la main. C'est ainsi que chaque panne de ce module
a été diagnostiquée.

`sudo sh -c '<toute la commande>'` et non `sudo <commande>` : ces commandes sont
des suites et des redirections. Préfixer par sudo n'élèverait que le premier
mot, et la redirection resterait celle du shell non privilégié.

<!-- [en] -->
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

<!-- [fr] -->
## Quatre pièges rencontrés sur un hôte réel

Une Proxmox installée **sur Debian** n'a aucun `vmbr0` — l'installateur ISO en
crée un, cette procédure non. Or `qm create` exige un pont.

Le menu propose alors un pont **interne** (`vmbr0`, `10.10.10.1/24`, NAT par la
sortie). Ne jamais ajouter l'interface physique à un pont est un choix : cela
déplace l'adresse de l'hôte et coupe la session SSH en cours — à distance, sans
retour. Pour un pont donnant sur le LAN, la strophe est affichée, à appliquer
depuis une console.

Sur un pont interne, aucun DHCP ne répond : l'adresse est donc **fixe**, dérivée
du VMID — donc connue avant que la VM ne démarre. La chercher ensuite était
absurde.

L'image cloud Debian n'embarque pas `qemu-guest-agent`, et Proxmox ne connaît
pas l'adresse d'un invité en DHCP : il ne distribue pas les baux. Le repli est
le voisinage de l'hôte (`ip neigh`), qui ne demande rien à l'invité.

<!-- [en] -->
## The menu, entry by entry

The seventeen QEMU/KVM entries have their counterpart. Four of them are the
**same code**, because it is the same work: reopening the install monitoring,
the remote desktop tunnel, the Android emulator and the image catalog. They
reach Proxmox guests through the `~/.ssh/config` entries that entry 13 writes,
with the Proxmox host as ProxyJump.

<!-- [fr] -->
## Le menu, entrée par entrée

Les dix-sept entrées de QEMU/KVM ont leur équivalent. Quatre sont le **même
code**, parce que c'est le même travail : rouvrir le suivi d'installation, le
tunnel bureau distant, l'émulateur Android et le catalogue d'images. Elles
atteignent les invités Proxmox par les entrées `~/.ssh/config` que l'entrée 13
écrit, avec l'hôte Proxmox en ProxyJump.

<!-- [common] -->
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

<!-- [en] -->
## Verified

Deploying a VM inside a Proxmox that itself runs in a libvirt VM: image
downloaded on the host, internal bridge created, static address, cloud-init
user and key, disk resized, `qm start`. Then `ssh vm-essai` from the outside
reaches it through the jump — three nested levels. Resize `12G → 16G`, delete
with `--purge`, orphan scan: all checked against Proxmox VE 9.2.11.

<!-- [fr] -->
## Vérifié

Déploiement d'une VM dans une Proxmox qui tourne elle-même dans une VM
libvirt : image téléchargée sur l'hôte, pont interne créé, adresse fixe,
utilisateur et clé par cloud-init, disque redimensionné, `qm start`. Puis
`ssh vm-essai` depuis l'extérieur l'atteint par le rebond — trois niveaux
imbriqués. Redimensionnement `12G → 16G`, effacement avec `--purge`, recherche
d'orphelins : tout contrôlé contre Proxmox VE 9.2.11.
