
# QEMU/KVM — Déploiement de VM Ubuntu

`deploy_qemu.py` déploie une VM Ubuntu (libvirt/KVM) à partir d'une image
cloud Ubuntu officielle, via `qemu-img` + `cloud-init` + `virt-install`. Il :

1. **Télécharge lui-même l'image cloud Ubuntu** (mise en cache, sans double
   téléchargement).
2. La convertit en un disque de travail qcow2 dédié et le redimensionne.
3. Génère `user-data` / `meta-data` et construit le `seed.iso` (cloud-init).
4. Lance `virt-install` en important le disque + le seed en CD-ROM.
5. Attend le bail DHCP et affiche la commande SSH.

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

```bash
sudo apt install qemu-utils virtinst libvirt-clients cloud-image-utils \
    libvirt-daemon-system qemu-system-x86
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt,kvm "$USER"   # re-login / reconnectez-vous
```

`libvirt-daemon-system` fournit le démon `libvirtd` (et le socket
`/var/run/libvirt/libvirt-sock`) et `qemu-system-x86` l'émulateur — sans eux
`virt-install` échoue avec *« Failed to connect socket to
'/var/run/libvirt/libvirt-sock' »*. Le script les installe et les démarre pour
vous ; cette commande manuelle n'est utile que si vous préférez préparer
l'hôte vous-même ou utiliser `--no-install-deps`.

## Utilisation

Forme la plus simple — l'image est téléchargée automatiquement (chemin déduit
de `--version`, mis en cache dans `/var/lib/libvirt/images/iso`) :

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub
```

Télécharger (et vérifier) une image sans créer de VM :

```bash
sudo ./script/qemu/deploy_qemu.py --download-only --version 24.04 --verify
```

Déployer avec un mot de passe interactif au lieu d'une clé SSH :

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 --ask-password
```

VM plus grande (8 Go RAM, 8 vCPU, disque 120 Go), en écrasant un disque
existant :

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --memory 8192 --vcpus 8 --disk-size 120G --ask-password --force
```

Prévisualiser ce qui serait fait, sans rien exécuter (sans sudo, sans
téléchargement) :

```bash
./script/qemu/deploy_qemu.py --name test-vm --version 24.04 --dry-run
```

Déploiement non interactif (accepte automatiquement l'installation des
dépendances) :

```bash
sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub -y
```

Versions Ubuntu supportées : `20.04`, `22.04`, `24.04` (défaut), `24.10`,
`25.04`, `25.10`. Fournissez un chemin d'image en argument positionnel pour
surcharger l'emplacement de téléchargement automatique.

## Après le déploiement

```bash
virsh list --all
virsh console test-vm                    # Ctrl+] to quit / pour quitter
virsh domifaddr test-vm --source lease   # find the IP / trouver l'IP
ssh erplibre@<IP>
```

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

## Gestion des VM

Lister, arrêter et supprimer les VM (le disque qcow2 sous
`/var/lib/libvirt/images` est conservé tant que vous ne le supprimez pas) :

```bash
sudo virsh list --all          # toutes les VM et leur état / all VMs and state
sudo virsh shutdown <nom-vm>   # arrêt propre ACPI / graceful shutdown
sudo virsh destroy <nom-vm>    # arrêt forcé / force off (pull the plug)
sudo virsh undefine <nom-vm>   # supprime la définition / remove definition
sudo virsh domifaddr <nom-vm>  # adresse IP de la VM / VM IP address
```

`destroy` ne fait qu'éteindre la VM (disque conservé) ; `undefine` supprime sa
définition. Pour recréer proprement une VM du même nom, faites `destroy` +
`undefine` d'abord, ou redéployez avec `--force`.

## Accès SSH depuis une autre machine (ProxyJump)

Avec le réseau NAT par défaut, la VM n'est joignable que **depuis l'hôte
KVM**. Pour l'atteindre depuis une autre machine **sans toucher au réseau**,
utilisez l'hôte comme rebond (il joint déjà la VM). Récupérez l'IP de la VM
avec `sudo virsh domifaddr <nom-vm>`, puis depuis l'autre machine :

```bash
# Rebond SSH vers la VM / jump through the KVM host
ssh -J user@<ip-hote> erplibre@<ip-vm>

# Tunnel d'un service, ex. Odoo 8069 / tunnel a service, then http://localhost:8069
ssh -L 8069:<ip-vm>:8069 user@<ip-hote>
```

Pour le rendre permanent, ajoutez ceci à `~/.ssh/config` sur l'autre machine
(ensuite `ssh myvm` suffit) :

```text
Host myvm
    HostName <ip-vm>            # ex. 192.168.122.50 (reseau NAT)
    User erplibre
    ProxyJump user@<ip-hote>    # IP LAN de l'hote KVM
```

Ça marche en Wi-Fi et sans arrêter la VM — l'option la plus simple pour un
accès personnel. Préférez un pont (ci-dessous) si la VM doit être un serveur
à part entière exposé sur le LAN.

## QEMU dans QEMU (imbriqué) & exposer la VM via un pont

Si l'hôte KVM est **lui-même une VM** (QEMU dans QEMU), le déploiement ne
fonctionne que si la **virtualisation imbriquée** est activée sur l'hôte
physique et que la VM intermédiaire utilise le mode CPU `host-passthrough`.
Vérifiez depuis l'hôte KVM (la première commande doit être non vide) :

```bash
grep -E -o '(vmx|svm)' /proc/cpuinfo | sort -u   # extensions visibles / visible
# Sur l'hote PHYSIQUE / on the PHYSICAL host:
cat /sys/module/kvm_intel/parameters/nested      # Intel -> Y/1
cat /sys/module/kvm_amd/parameters/nested        # AMD   -> Y/1
```

Pour activer l'imbrication sur l'hôte physique (Intel montré ; `kvm_amd` sur
AMD), puis recréer la VM intermédiaire en `host-passthrough` :

```bash
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel   # ou / or reboot
```

Si l'imbrication est indisponible, QEMU tourne quand même en émulation
logicielle (TCG) — ça marche mais c'est lent.

### Pont pour l'accès externe

Une VM en NAT est isolée ; une VM **pontée** obtient une IP directement sur le
LAN, joignable par n'importe quelle machine. Sur l'hôte KVM, créez un pont
`br0` sur la carte physique (**filaire uniquement** — le Wi-Fi ne se ponte
pas). netplan (Ubuntu serveur) — remplacez `enp3s0` par votre interface :

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

Appliquez avec filet de sécurité (annulation auto en cas de coupure) et
vérifiez — ou via NetworkManager (Ubuntu bureau) :

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

Rattachez ensuite la VM au pont — **soit à la création** :

```bash
sudo ./script/qemu/deploy_qemu.py --name <nom-vm> --version 24.04 \
    --ssh-key ~/.ssh/id_ed25519.pub --network bridge=br0,model=virtio -y --force
```

**soit par édition d'une VM déjà créée** : arrêtez-la, remplacez son bloc
`<interface>` (`type='network'` / `<source network='default'/>` →
`type='bridge'` / `<source bridge='br0'/>`), puis redémarrez-la :

```bash
sudo virsh shutdown <nom-vm>
sudo virsh edit <nom-vm>        # mettre l'interface en bridge=br0
sudo virsh start <nom-vm>
sudo virsh domifaddr <nom-vm>   # nouvelle IP LAN / new LAN IP
```

La VM obtient maintenant une IP LAN de votre routeur, joignable par les autres
machines. Depuis Internet, il faut en plus une redirection de port sur votre
routeur (ou un VPN) ; en configuration imbriquée, l'hôte externe doit aussi
rediriger/exposer la VM intermédiaire.