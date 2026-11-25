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
- `host_perf_audit.py` measures, read-only, what limits the performance of
  such a host (or of any Linux server). See
  [Host performance audit](#host-performance-audit-read-only).

<!-- [fr] -->
Deux choses différentes vivent dans ce répertoire :

- `install_proxmox.sh` transforme une Debian en hyperviseur Proxmox. Voir
  `script/qemu/README.fr.md`, qui documente la distro `proxmox` du catalogue
  de déploiement.
- `proxmox_deploy.py` déploie des VM **sur** un tel hôte, depuis
  `TODO › Execute › Deploy › Proxmox VE`, juste sous `QEMU/KVM`.
- `host_perf_audit.py` mesure, en lecture seule, ce qui limite les
  performances d'un tel hôte (ou de tout serveur Linux). Voir
  [Audit de performance de l'hôte](#audit-de-performance-de-lhôte-lecture-seule).

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
[2] Prévisualiser          [9]  Effacer des VM             [16] Périphériques USB
[3] Télécharger une image  [10] Nettoyer (orphelins)       [17] Catalogue d'images *
[4] Rouvrir le suivi *     [11] Tester une VM (Odoo)       [18] Exemple (dry-run)
[5] Lister (qm list)       [12] Statistiques               [19] Changer d'hôte
[6] Adresse IP d'une VM    [13] Configuration SSH          [20] Audit de performance
[7] Console d'une VM       [14] Tunnel bureau distant *
                                        * code partagé avec le menu QEMU/KVM
```

<!-- [en] -->
## USB devices (Stream Deck)

Entry 16 passes a USB device plugged into the Proxmox **node** to a VM: it
lists the node's devices with `pvesh get /nodes/<node>/hardware/usb`
(Elgato Stream Decks first), takes the first free `usbN` port and shows the
`qm set` command before running it. The same entry lists and detaches the
`usbN` ports of the VM.

Unlike libvirt, there is no live/config choice: `qm set -usbN` writes the VM
configuration, so the attachment is always persistent. A running VM gets the
device at once when its `hotplug` option includes `usb` (the default),
otherwise at its next start. `host=VID:PID` follows the device across
replugs, so no udev rule is needed on the node; two identical devices are
told apart by their physical port (`host=BUS-PORT`).

A VM gets `usb0` to `usb13` on PVE 8 and later, `usb0` to `usb4` before.

<!-- [fr] -->
## Périphériques USB (Stream Deck)

L'entrée 16 passe à une VM un périphérique USB branché sur le **nœud**
Proxmox : elle liste les périphériques du nœud par
`pvesh get /nodes/<nœud>/hardware/usb` (les Stream Deck d'Elgato en tête),
prend le premier port `usbN` libre et montre la commande `qm set` avant de la
lancer. La même entrée liste et détache les ports `usbN` de la VM.

Contrairement à libvirt, il n'y a pas de choix live/config : `qm set -usbN`
écrit la configuration de la VM, l'attachement est donc toujours persistant.
Une VM en marche reçoit le périphérique tout de suite quand son option
`hotplug` contient `usb` (le défaut), sinon à son prochain démarrage.
`host=VID:PID` suit le périphérique d'un rebranchement à l'autre, donc aucune
règle udev n'est nécessaire sur le nœud ; deux périphériques identiques se
départagent par leur port physique (`host=BUS-PORT`).

Une VM dispose de `usb0` à `usb13` depuis PVE 8, de `usb0` à `usb4` avant.

<!-- [common] -->
```bash
qm set 100 -usb0 host=0fd9:0080,usb3=1   # attacher
qm set 100 -delete usb0                  # détacher
```

<!-- [en] -->
### A deck plugged into the workstation (SPICE)

When the deck is plugged into the workstation that shows the VM rather than
into the node, the same entry redirects it over SPICE, the counterpart of the
libvirt `usbredir`. It gives the VM a SPICE display (`vga: qxl` when the
current one is not `qxl`, `virtio` or `virtio-gl`) and one `usbN: spice` port
per deck plugged in here, in a single confirmed `qm set`. A display change
applies at the next start of the VM: the menu offers `qm reboot`, which
applies the pending configuration (a reboot from inside the guest does not).

It then opens an ssh tunnel to the node's SPICE proxy (port 3128) along the
menu's ssh path, fetches a ticket with `pvesh create
/nodes/<node>/qemu/<vmid>/spiceproxy`, writes it as a private `.vv` file
(mode 0600, deleted as soon as `remote-viewer` has read it) and starts
`remote-viewer` with the filter that redirects every Stream Deck. The ticket's
password expires thirty seconds after `pvesh` returns it. The workstation's
ERPLibre Home deck service is stopped, after confirmation, just before
`remote-viewer` starts; it is restarted if `remote-viewer` cannot start.
Without a display, the menu prints the `remote-viewer` command to run on the
workstation.

<!-- [fr] -->
### Un deck branché sur le poste (SPICE)

Quand le deck est branché sur le poste qui affiche la VM plutôt que sur le
nœud, la même entrée le redirige par SPICE, le pendant du `usbredir` de
libvirt. Elle donne à la VM un affichage SPICE (`vga: qxl` quand l'actuel
n'est ni `qxl`, ni `virtio`, ni `virtio-gl`) et un port `usbN: spice` par deck
branché ici, en un seul `qm set` confirmé. Un changement d'affichage s'applique
au prochain démarrage de la VM : le menu propose `qm reboot`, qui applique la
configuration en attente (un redémarrage depuis l'invité ne le fait pas).

Elle ouvre ensuite un tunnel ssh vers le proxy SPICE du nœud (port 3128) par
le chemin ssh du menu, obtient un billet par `pvesh create
/nodes/<nœud>/qemu/<vmid>/spiceproxy`, l'écrit dans un fichier `.vv` privé
(mode 0600, effacé dès que `remote-viewer` l'a lu) et lance `remote-viewer`
avec le filtre qui redirige tous les Stream Deck. Le mot de passe du billet
expire trente secondes après que `pvesh` l'a rendu. Le service deck ERPLibre
Home du poste est arrêté, après confirmation, juste avant le lancement de
`remote-viewer` ; il est relancé si `remote-viewer` ne démarre pas. Sans
affichage, le menu affiche la commande `remote-viewer` à lancer sur le poste.

<!-- [common] -->
```bash
qm set 100 -vga qxl -usb1 spice          # affichage SPICE, un port redirigé
qm reboot 100                            # applique l'affichage
```

<!-- [en] -->
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
host from Debian 10 on. Entry `[20]` of this menu sends it to the
remembered host over `ssh -T` with the file on stdin, or runs it on this
machine; `TODO › Execute › Production` also runs it locally. Ctrl-C stops
the measurement early and still prints the report when the script runs on
the host itself; over ssh, a local Ctrl-C closes the connection and the
report is lost. `--json` prints a document with stable keys, `--csv FILE`
keeps the raw samples; a write error on it (full disk) disables the file,
not the audit. Each one-time command (`zpool`, `zfs`, `smartctl`) is
abandoned after 20 s, even when stuck on a suspended pool, and `smartctl`
leaves a disk in standby asleep. Exit codes: 0 audit done, 2 could not run
(arguments, refused profile), 130 interrupted before measuring.

**Host profile.** `--profile FILE` reads the measurement settings —
`duration`, `interval`, `no_guests`, `top`, `verbose` — from a JSON
profile, one per host, distinct from the instance profiles:
`private/production/host/local.json` for this machine,
`private/production/host/pve-<target>.json` for a remote host (characters
outside `[A-Za-z0-9_.@-]` become `_`; the prefix keeps a host alias named
`local` apart). Its content is
`{"version": 1, "host": "<local|target>", "host_perf_audit": {...}}`.
Without `--profile`, no profile is looked for: a remote host does not have
the file, and a run over ssh receives explicit arguments. The command line always wins over the
profile; `--csv`, `--json` and `--root` are not profile settings. An unknown
key is reported on stderr and ignored. A profile writable by every account,
a symbolic link, a control character, a version newer than 1 or a value
the option itself would refuse ends with code 2. The values taken from the
profile are announced on stderr before the measurement
(`--duration 600 (profile)`) and noted in the report. The file stays a
single file: it applies the rules of `script/lib_ops/profil.py` without
importing it.

<!-- [fr] -->
## Audit de performance de l'hôte (lecture seule)

`host_perf_audit.py` échantillonne `/proc` et `/sys` toutes les
`--interval` secondes (5 par défaut) pendant `--duration` (`60`, `30s`,
`10m`, `2h`, `1h30m` ; de 1 seconde à 7 jours), puis rend un verdict par
ressource — `ok`, `watch` ou `limiting` — pour le processeur, la mémoire,
les disques et le réseau, la réponse à « des disques SSD sont-ils
justifiés ? », et les réglages à envisager (compression et atime ZFS,
maximum de l'ARC, `vm.swappiness`, options des disques de VM…), chacun
**affiché** avec la commande qui l'appliquerait. Rien n'est jamais modifié.

Il couvre la pression (PSI, `/proc/pressure`), l'utilisation et l'attente
de chaque disque (un disque rotatif est jugé sur son utilisation et son
attente, un SSD ou un NVMe sur son attente seulement), l'activité du swap,
ZFS (taux de succès de l'ARC, remplissage, fragmentation, santé, latence
des pools) et, sur un hôte Proxmox en cgroup v2, chaque conteneur et VM en
marche, nommés d'après `/etc/pve`. Les disques d'un pool sont lus dans ses
propres vdev (`zpool status -P -L`) : un HDD de sauvegarde oisif, hors de
tout pool, ne fait jamais répondre « oui, des SSD ».

C'est un seul fichier, bibliothèque standard seulement, lançable par le
`python3` d'un hôte dès Debian 10. L'entrée `[20]` de ce menu l'envoie à
l'hôte retenu par `ssh -T`, le fichier sur stdin, ou le lance sur ce
poste ; `TODO › Exécuter › Production` le lance aussi en local. Ctrl-C
arrête la mesure plus tôt et donne quand même le rapport quand le script
tourne sur l'hôte lui-même ; par ssh, un Ctrl-C local ferme la connexion
et le rapport est perdu. `--json` produit un document aux clés stables,
`--csv FICHIER` garde les échantillons bruts ; une erreur d'écriture
(disque plein) coupe le fichier, pas l'audit. Chaque commande lancée une
fois (`zpool`, `zfs`, `smartctl`) est abandonnée après 20 s, même bloquée
sur un pool suspendu, et `smartctl` laisse dormir un disque en veille.
Codes de sortie : 0 audit
fait, 2 impossible (arguments, profil refusé), 130 interrompu avant la
mesure.

**Profil d'hôte.** `--profile FICHIER` lit les réglages de la mesure —
`duration`, `interval`, `no_guests`, `top`, `verbose` — dans un profil JSON,
un par hôte, distinct des profils d'instance :
`private/production/host/local.json` pour ce poste,
`private/production/host/pve-<cible>.json` pour un hôte distant (les
caractères hors de `[A-Za-z0-9_.@-]` deviennent `_` ; le préfixe sépare un
alias d'hôte nommé `local`). Son contenu est
`{"version": 1, "host": "<local|cible>", "host_perf_audit": {...}}`. Sans
`--profile`, aucun profil n'est cherché : un hôte distant n'a pas le
fichier, et un lancement par ssh reçoit des arguments explicites. La ligne de commande gagne toujours sur le
profil ; `--csv`, `--json` et `--root` ne sont pas des réglages du profil.
Une clé inconnue est signalée sur stderr puis ignorée. Un profil
inscriptible par tous, un lien symbolique, un caractère de contrôle, une
version plus récente que 1 ou une valeur que l'option refuserait elle-même
finit en code 2. Les valeurs prises du profil sont annoncées sur stderr
avant la mesure (`--duration 600 (profile)`) et notées dans le rapport. Le
fichier reste unique : il applique les règles de `script/lib_ops/profil.py`
sans l'importer.

<!-- [common] -->
```bash
./script/proxmox/host_perf_audit.py --duration 10m
sudo ./script/proxmox/host_perf_audit.py --duration 24h --csv /var/tmp/perf.csv
./script/proxmox/host_perf_audit.py --profile private/production/host/local.json --top 3
ssh -T root@pve.example.org python3 -I - --duration 2h < script/proxmox/host_perf_audit.py
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
