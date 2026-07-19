<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# QEMU/KVM — Ubuntu VM deployment

`deploy_qemu.py` deploys an Ubuntu VM (libvirt/KVM) from an official Ubuntu
cloud image, using `qemu-img` + `cloud-init` + `virt-install`. It:

1. **Downloads the Ubuntu cloud image by itself** (cached, no double download).
2. Converts it to a dedicated qcow2 working disk and resizes it.
3. Generates `user-data` / `meta-data` and builds the `seed.iso` (cloud-init).
4. Runs `virt-install` importing the disk + the seed as a CD-ROM.
5. Waits for the DHCP lease and prints the SSH command.

<!-- [fr] -->
# QEMU/KVM — Déploiement de VM Ubuntu

`deploy_qemu.py` déploie une VM Ubuntu (libvirt/KVM) à partir d'une image
cloud Ubuntu officielle, via `qemu-img` + `cloud-init` + `virt-install`. Il :

1. **Télécharge lui-même l'image cloud Ubuntu** (mise en cache, sans double
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
Supported Ubuntu versions: `20.04`, `22.04`, `24.04` (default), `24.10`,
`25.04`, `25.10`. Provide an explicit image path as a positional argument to
override the automatic download location.

## After deployment

<!-- [fr] -->
Versions Ubuntu supportées : `20.04`, `22.04`, `24.04` (défaut), `24.10`,
`25.04`, `25.10`. Fournissez un chemin d'image en argument positionnel pour
surcharger l'emplacement de téléchargement automatique.

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

## Main options

- `--version` — Ubuntu version (default `24.04`).
- `--image-dir` — image cache directory (default `/var/lib/libvirt/images/iso`).
- `--download-only` — download the image then exit (no VM).
- `--name` — VM name (required for deployment).
- `--memory`, `--vcpus`, `--disk-size` — VM sizing. When omitted, `--memory`
  and `--disk-size` default to the **minimum required by the chosen Ubuntu
  version** (libosinfo values: 20.04 → 2048 MB/5G, 22.04 → 2048 MB/10G,
  24.04+ → 3072 MB/20G); `--vcpus` defaults to 2.
- `--ssh-key`, `--ask-password`, `--password-hash` — authentication.
- `-y` / `--assume-yes` — auto-accept dependency installation.
- `--no-install-deps` — never auto-install dependencies.
- `--dry-run` — show the commands without executing anything.
- `--force` — overwrite the existing working qcow2 disk.

Run `./script/qemu/deploy_qemu.py --help` for the full list.

<!-- [fr] -->
L'utilisateur par défaut est `erplibre` (modifiable avec `--user`).

## Via le menu TODO

Le script est intégré à l'assistant interactif. Lancez `make todo` (ou
`./script/todo/todo.py`), puis allez dans **Execute → Deploy → QEMU/KVM -
Deploy an Ubuntu VM (libvirt)**. De là, vous pouvez déployer une VM,
prévisualiser un dry-run, télécharger une image, lister les VM et afficher
l'IP d'une VM — le menu demande les paramètres et construit la commande pour
vous.

## Principales options

- `--version` — version Ubuntu (défaut `24.04`).
- `--image-dir` — répertoire de cache des images (défaut
  `/var/lib/libvirt/images/iso`).
- `--download-only` — télécharge l'image puis quitte (sans VM).
- `--name` — nom de la VM (requis pour le déploiement).
- `--memory`, `--vcpus`, `--disk-size` — dimensionnement de la VM. Omis,
  `--memory` et `--disk-size` prennent le **minimum requis par la version
  Ubuntu** choisie (valeurs libosinfo : 20.04 → 2048 Mo/5G, 22.04 →
  2048 Mo/10G, 24.04+ → 3072 Mo/20G) ; `--vcpus` vaut 2 par défaut.
- `--ssh-key`, `--ask-password`, `--password-hash` — authentification.
- `-y` / `--assume-yes` — accepte automatiquement l'installation des
  dépendances.
- `--no-install-deps` — n'installe jamais les dépendances automatiquement.
- `--dry-run` — affiche les commandes sans rien exécuter.
- `--force` — écrase le disque de travail qcow2 existant.

Lancez `./script/qemu/deploy_qemu.py --help` pour la liste complète.

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

## SSH access from another machine (ProxyJump)

With the default NAT network the VM is reachable **only from the KVM host**.
To reach it from another machine **without changing the network**, use the
host as a jump host (it already reaches the VM). Get the VM IP with
`sudo virsh domifaddr <nom-vm>`, then from the other machine:

<!-- [fr] -->
`destroy` ne fait qu'éteindre la VM (disque conservé) ; `undefine` supprime sa
définition. Pour recréer proprement une VM du même nom, faites `destroy` +
`undefine` d'abord, ou redéployez avec `--force`.

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

## QEMU inside QEMU (nested) & exposing the VM via a bridge

If the KVM host is **itself a VM** (QEMU-in-QEMU), the deployment works only
when **nested virtualization** is enabled on the outer/physical host and the
middle VM uses CPU mode `host-passthrough`. Check from inside the KVM host
(the first command must be non-empty):

<!-- [fr] -->
Ça marche en Wi-Fi et sans arrêter la VM — l'option la plus simple pour un
accès personnel. Préférez un pont (ci-dessous) si la VM doit être un serveur
à part entière exposé sur le LAN.

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
If nesting is unavailable, QEMU still runs via software emulation (TCG) — it
works but is slow.

### Bridge for external access

A NAT VM is isolated; a **bridged** VM gets an IP directly on the LAN,
reachable by any machine. On the KVM host, create a bridge `br0` over the
physical NIC (**wired only** — Wi-Fi cannot be bridged). netplan (Ubuntu
server) — replace `enp3s0` with your interface:

<!-- [fr] -->
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
