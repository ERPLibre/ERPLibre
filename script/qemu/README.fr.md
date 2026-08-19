
# QEMU/KVM — Déploiement de VM Linux (Ubuntu / Debian / Fedora)

`deploy_qemu.py` déploie une VM Linux (libvirt/KVM) à partir d'une image
cloud officielle, via `qemu-img` + `cloud-init` + `virt-install`. Choisissez
la distribution avec `--distro` (`ubuntu` par défaut, `debian`, `fedora`) et
la version avec `--version` ; `--list-images` affiche tout le catalogue avec
les specs minimales. Il :

1. **Télécharge lui-même l'image cloud** (mise en cache, sans double
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

Catalogue, par architecture (`deploy_qemu.py` fait autorité) :

| Distro | Versions | amd64 | arm64 | s390x |
|---|---|:-:|:-:|:-:|
| ubuntu | `24.04` (défaut), `25.10`, `26.04` | ✔ | ✔ | ✔ |
| debian | `11`, `12` (défaut), `13` | ✔ | ✔ | — |
| fedora | `41`, `42` (défaut), `43`, `44` | ✔ | ✔ | `43` seule |
| almalinux | `9` (défaut), `10` | ✔ | ✔ | ✔ |
| rocky | `9`, `10` (défaut) | ✔ | ✔ | ✔ |
| opensuse | `16.0` (défaut), `tumbleweed` | ✔ | ✔ | ✔ |
| arch | `latest` | ✔ | — | — |

Fedora ne construit s390x que pour la version courante, et sur une
arborescence à part (`fedora-secondary`) — d'où la version unique.

`opensuse` recouvre deux produits distincts, pas deux versions du même. Leap
`16.0` est numérotée et stable (base SLE) : c'est le défaut. `tumbleweed` est
la rolling, gardée comme banc d'essai des ruptures à venir — sa dérive
d'instantanés est réelle, et elle impose un `zypper dup` complet avant toute
installation.

Les deux livrent un qpdf au-dessus du seuil de pikepdf : la compilation de
qpdf, une demi-heure, ne s'y déclenche jamais — ce qui compte sous émulation
s390x.

Fournissez un chemin d'image en argument positionnel pour surcharger
l'emplacement de téléchargement automatique.

Les Ubuntu `20.04` et `22.04` sont **abandonnées sur toutes les
architectures** : pikepdf réclame qpdf 12.2, dont la compilation exige C++20,
et focal livre GCC 9 — elle ne publie même pas de `g++-10` pour s390x. Python
3.8, node 10, cargo 0.67 et OpenSSL 1.1.1 avaient chacun leur contournement ;
leur accumulation, non.

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

Cette dernière cause n'arrête plus la compilation. Le dépôt mobile empaquette
les dépôts du manifeste dans ses assets — 122 684 fichiers, pour 337 qui sont
l'application — et un APK est un ZIP, borné à 65535 entrées :
`Too many zip entries 123678`. La compilation pointe donc
`ERPLIBRE_MANIFEST_PATH`, le levier que ce dépôt documente, sur un manifeste
vide, et le plugin l'annonce : `0 repos`. Mesuré : `dist` passe de 123 019
fichiers à 336, et l'APK sort à 59 Mo et 2 472 entrées. Posez la variable
vous-même et les dépôts reviennent — le défaut est une mesure d'attente, le
temps qu'ils tiennent sous le plafond du ZIP.

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

Chaque outil est filtré VM par VM — architecture, saveur de bureau et famille
de paquets — et sa place disque s'ajoute au plan avant que rien ne soit créé.

## Principales options

- `--distro` — `ubuntu` (défaut), `debian` ou `fedora`.
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

## Guide de connexion (`/etc/motd`)

Chaque VM accueille celui qui s'y connecte en SSH avec les commandes de **sa**
distribution — `apt`, `dnf`, `zypper` ou `pacman` — et celles d'ERPLibre :
éditer le serveur, le redémarrer, mettre à jour des modules, mettre à jour
Odoo, inspecter l'instance, ouvrir le menu TODO. Il est écrit par cloud-init,
donc présent dès le premier démarrage : avant l'installation d'ERPLibre, et
encore là si elle échoue — le moment où l'on se connecte justement à la main.

`--dry-run` affiche le guide généré avec le reste du user-data. Il ne
s'affiche PAS pour un `ssh hôte 'commande'` : les journaux d'installation
restent nets.

L'identité git de l'hôte voyage avec lui, dans le `~/.gitconfig` de la VM :
un commit fait dans la VM porte alors votre nom plutôt que
`erplibre@<nom-de-vm>`. L'éditeur suit le même chemin — `core.editor`, la
ligne `config.conf` du guide et le paquet installé dans la VM viennent d'une
seule table, de sorte que le guide ne nomme jamais une commande absente.

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

Sur **s390x et arm64**, le paramètre vit sur le module `kvm` lui-même, et non
sur `kvm_intel` / `kvm_amd` — et `/sys/module/kvm/parameters/nested` n'existe
même pas sur x86. Lire le mauvais fichier renvoie un `0` rassurant qui ne
commande rien :

```bash
echo "options kvm nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm && sudo modprobe kvm               # ou / or reboot
```

`nested` sur une machine signifie « j'autorise MES invités à faire tourner des
VM ». Pour accélérer une VM créée sur l'hôte H, le réglage appartient à
l'hyperviseur **au-dessus** de H, pas à H. La commande qui tranche, sur H :

```bash
ls -l /dev/kvm     # absent -> pas d'imbrication, tout sera émulé
```

Mesuré sur un hôte s390x lui-même invité KVM sans imbrication : `/dev/kvm`
absent, `virsh dumpxml` affichant `<domain type='qemu'>`, et un démarrage de
7 min 30 au lieu de bien moins d'une minute. `systemd-detect-virt` dans la VM
ne prouve **pas** l'accélération — sur s390x, QEMU fabrique la réponse STSI et
annonce `kvm` même en TCG. Seul `<domain type=…>` sur l'hôte fait foi.

### Bridge for external access

A NAT VM is isolated; a **bridged** VM gets an IP directly on the LAN,
reachable by any machine. On the KVM host, create a bridge `br0` over the
physical NIC (**wired only** — Wi-Fi cannot be bridged). netplan (Ubuntu
server) — replace `enp3s0` with your interface:

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