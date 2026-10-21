
# ERPLibre sur IBM Z (s390x)

Ce guide explique comment ERPLibre s'installe sur l'architecture s390x
(mainframe IBM Z, LinuxONE), ce que l'installation fait autrement que sur
amd64, et pourquoi. Il s'adresse autant à la personne qui installe qu'au
développeur qui maintient les scripts.

## En une phrase

PyPI ne publie presque aucun paquet précompilé (roue, *wheel*) pour s390x : là
où pip télécharge un binaire tout prêt sur amd64, il **compile depuis les
sources** sur s390x. Tout ce qui est propre à s390x dans ERPLibre en découle :
plus de paquets système, plus de mémoire, plus de temps, et quelques
fonctions laissées de côté.

## Systèmes pris en charge

| Système | Versions sur s390x | Installation de la VM | Remarques |
|---|---|---|---|
| Ubuntu | 24.04, 25.10, 26.04 | image cloud | 24.04 compile qpdf depuis les sources |
| Debian | 12, 13 | debian-installer (aucune image cloud s390x) | 12 compile qpdf et PROJ depuis les sources |
| Fedora | 43 seulement | image cloud (*fedora-secondary*) | s390x est une architecture secondaire de Fedora : seule la version courante est construite |
| AlmaLinux | 9, 10 | image cloud | Rust sous 1.95 (1.92 en 10) → complété par rustup ; qpdf compilé depuis les sources (EL9 livre 10.3, EL10 11.9) |
| Rocky Linux | 9, 10 | image cloud | comme AlmaLinux |
| openSUSE | Leap 16.0, Tumbleweed | image cloud | Leap 16.0 compile qpdf (11.10 livré) ; le qpdf de Tumbleweed est assez récent ; Python de la distribution utilisé |

**Non pris en charge sur s390x :** Arch Linux (aucune image s390x officielle,
le projet vise x86_64), NixOS (la seule image cloud, construite par un tiers,
n'existe qu'en x86_64), Proxmox VE (son dépôt n'a aucun index s390x). Ubuntu
20.04 et 22.04 sont refusés sur toutes les architectures : pikepdf exige
qpdf 12.2 compilé en C++20, et focal livre GCC 9, sans g++-10 pour s390x.

## Installer

L'ordre compte : **`make install_os` d'abord**. Il pose les paquets système
dont les compilations ont besoin. Sur amd64, les paquets précompilés masquent
ce besoin ; sur s390x, un `make` seul sur une machine nue s'arrête sur des
en-têtes manquants.

- `make install_os` : paquets système, swap, Rust, et qpdf ou PROJ au besoin ;
- `make` : ouvre TODO et propose de construire `.venv.erplibre` ;
- `make install_odoo_18` : venv d'Odoo (`poetry install`) et sources d'Odoo
  (`repo sync`).

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
make install_os
make
make install_odoo_18
```

Ordres de grandeur sur une VM s390x native (KVM) de 4 Gio de RAM : environ
5 minutes pour `make install_os`, environ 25 minutes pour
`make install_odoo_18`. En émulation sur un hôte x86, comptez à peu près dix
fois plus.

Si `make` est lancé avant `make install_os`, l'installation n'échoue plus
après de longues minutes de compilation : elle vérifie d'abord les prérequis
de compilation (en-têtes C, compilateur, pkg-config, cargo) et nomme ce qui
manque, avec la commande apt pour l'installer, ou apt ou dnf pour le contrôle
pyenv (`script/install/S390x/build_check.sh` et
`script/install/lib_python_provider.sh`).

## Ce qu'ERPLibre ajoute sur s390x, et pourquoi

| Ajout | Pourquoi | Où |
|---|---|---|
| Fichier d'échange temporaire, jusqu'à 8 Gio de RAM + swap | un seul `cc1plus` peut prendre 2,5 Gio (matplotlib) ; le noyau le tue et le compilateur n'affiche que `Killed signal terminated program cc1plus`, sans nommer la mémoire | `S390x/lib_lowmem.sh` (`el_swap_ensure`) |
| Limite des compilations parallèles : une par 2 Gio de RAM + swap | chaque moteur de build lance autant de compilateurs que de cœurs | `S390x/lib_lowmem.sh` (`el_build_limit_jobs`) |
| Rust ≥ 1.95, par rustup si la distribution est plus ancienne | orjson 3.13 (Odoo 18) exige rustc 1.95 ; cryptography et bcrypt portent des extensions Rust | `S390x/lib_rust.sh` |
| qpdf 12.3.2 compilé depuis les sources si le système a < 12.2 | pikepdf compile contre le qpdf du système | `S390x/lib_qpdf.sh` |
| PROJ 9.6.2 compilé depuis les sources si le système a < 9.4 (famille apt) | pyproj compile contre le PROJ du système (ses roues amd64 et arm64 embarquent le leur) | `S390x/lib_proj.sh` |
| Paquets de compilation : tbb, cmake, ninja, geos, proj, krb5, clang… | manifold3d, pyproj, pymupdf et d'autres se compilent | `S390x/debian.sh`, `fedora.sh`, `suse.sh` |
| Lien symbolique `libclang.so` | pymupdf charge `libclang.so` par son nom nu ; les distributions ne livrent que des noms versionnés | mêmes fichiers |
| `cryptography<47` pour l'amorçage de Poetry si OpenSSL < 3 | sur s390x seulement, cryptography compile contre l'OpenSSL du système, et la version 47 a abandonné OpenSSL 1.1.1 | `install_locally.sh` |
| Node.js de la distribution, ou de nodejs.org si sa version est antérieure à la 18 | NodeSource ne publie rien pour s390x | `install_debian_dependency.sh` |

Le fichier d'échange n'est **pas** inscrit dans `/etc/fstab` : il ne sert que
pendant l'installation et n'est plus actif après un redémarrage. Le fichier
lui-même reste sur le disque, et une exécution suivante le réactive ;
supprimez-le à la main pour récupérer la place. Sur btrfs
(Fedora, openSUSE), il vit dans un sous-volume dédié `/.erplibre-swap`,
marqué `+C` (sans copie sur écriture ni compression), faute de quoi `swapon`
le refuse.

## Ce qui manque par rapport à amd64

| Manque | Conséquence | Raison |
|---|---|---|
| **wkhtmltopdf** | pas de rapports PDF (factures, soumissions) ; Odoo affiche le rapport en HTML à la place | aucun paquet s390x en amont ; l'installation l'ignore sur toute architecture autre que x86_64 |
| **PyMuPDF** | exclu des dépendances d'Odoo 18 sur s390x ; les fonctions PDF qui en dépendent (OCA edi) sont indisponibles | MuPDF ne se construit pas sur s390x |
| **factur-x ≥ 4** | factur-x 3.x est utilisé à la place, sans la validation Schematron | factur-x ≥ 4 dépend de saxonche, sans roue s390x |
| **mise** | `make install_mise` ne fait rien ; Python vient de la distribution ou est compilé par pyenv | mise ne publie aucun binaire s390x |
| **Forgejo** (option QEMU) | l'option est grisée | aucun binaire s390x |
| **Écran virtuel** des VM de bureau | le bureau s'atteint par le réseau | le noyau s390x ne garantit pas le pilote virtio-gpu |
| **PostGIS** sur openSUSE Tumbleweed | installé au mieux, absent des dépôts s390x | non empaqueté |
| **GeographicLib C++** sur openSUSE | non installé | openSUSE n'empaquette que la liaison Python |

## Avantages et inconvénients par rapport à amd64

| | s390x | amd64 |
|---|---|---|
| Paquets Python | compilés depuis les sources (numpy, pandas, pillow, matplotlib, cryptography, orjson, pikepdf, pyproj, manifold3d…) | roues précompilées |
| Durée d'installation d'Odoo | des dizaines de minutes, surtout dans le compilateur | quelques minutes |
| Mémoire pendant l'installation | 4 Gio de RAM recommandés, swap ajouté automatiquement | le minimum du catalogue suffit |
| Interpréteur Python | Python de la distribution, ou CPython compilé par pyenv | Python de la distribution, ou CPython précompilé par mise en quelques secondes |
| `uv` | disponible, mais gain quasi nul : le temps est dans le compilateur | gain sensible |
| Fonctions d'Odoo | sans wkhtmltopdf ni PyMuPDF, factur-x 3.x | complètes |
| Matériel | fiabilité, entrées-sorties et virtualisation d'IBM Z ; ERPLibre tourne là où vivent déjà les données de l'organisation | répandu, moins coûteux pour tester |
| Reproductibilité | le verrou est neutre vis-à-vis de l'architecture : le même verrou (`requirement/poetry.odoo18.0_python3.12.10.lock`) sert aux deux, les différences étant des marqueurs de plateforme | — |

## Par système

### Debian, Ubuntu, Linux Mint (apt)

- La partie s390x vit dans `script/install/S390x/debian.sh`, sourcé par
  `install_debian_dependency.sh`.
- Les noms de paquets changent d'une version à l'autre : `apt_pick` demande à
  apt quel nom est installable (GeographicLib), pour qu'un nom périmé ne fasse
  pas refuser tout le lot.
- Seuls build-essential, pkg-config, libssl-dev, zlib1g-dev, libjpeg-dev et
  cmake arrêtent l'installation s'ils manquent ; les autres servent des
  modules Odoo facultatifs.
- Ubuntu est une architecture *ports* sur s390x : les paquets viennent des
  miroirs ubuntu-ports, pas d'archive.ubuntu.com.
- Ubuntu 24.04 et Debian 12 compilent qpdf (environ une demi-heure en
  émulation) ; Debian 12 compile aussi PROJ. Ubuntu 26.04 et Debian 13
  livrent un Rust sous 1.95, complété par rustup.

### Fedora, AlmaLinux, Rocky (dnf)

- La partie s390x vit dans `script/install/S390x/fedora.sh`.
- Sur AlmaLinux et Rocky, EPEL et CRB sont activés : la plupart des paquets
  `-devel` s'y trouvent.
- `qpdf-devel` n'est installé que s'il atteint 12.2 ; sinon qpdf est compilé
  dans `/usr/local`. L'éditeur de liens de RHEL cherche `/usr/lib64` avant
  `/usr/local/lib64` : un vieux `qpdf-devel` ferait lier pikepdf contre
  l'ancienne bibliothèque malgré les nouveaux en-têtes.
- AlmaLinux et Rocky 10 livrent Rust 1.92 : rustup le complète.
- Fedora installe un swap zram égal à la RAM : avec 4 Gio de RAM, la cible est
  presque atteinte et aucun fichier d'échange n'est ajouté.

### openSUSE Leap 16.0 et Tumbleweed (zypper)

- La partie s390x vit dans `script/install/S390x/suse.sh`.
- Un `cargo` absent est fatal sur s390x : bcrypt et cryptography ne
  pourraient pas compiler, et l'échec n'apparaîtrait qu'une heure plus tard.
- Le Python 3.12 de la distribution est installé et préféré : compiler
  CPython 3.12.10 avec gcc 15.2 sur s390x s'arrête sur une erreur interne du
  compilateur.
- qpdf passe par le même contrôle de 12.2 qu'avec apt et dnf : Leap 16.0
  livre 11.10 et le compile ; la version de Tumbleweed le satisfait, et rien
  n'y est compilé.
- Leap est la version à choisir pour une installation durable ; Tumbleweed
  bouge tous les jours et son arbre s390x retarde sur celui de x86_64.

## Déployer des VM s390x avec les outils QEMU

Depuis TODO : **Exécuter › Déployer › QEMU/KVM**, puis choisir
l'architecture s390x. En ligne de commande :

```bash
sudo ./script/qemu/deploy_qemu.py --setup-host --assume-yes
sudo ./script/qemu/deploy_qemu.py --name erplibre-ubuntu-2604-s390x \
    --distro ubuntu --version 26.04 --arch s390x \
    --ssh-key ~/.ssh/id_ed25519.pub -y
```

- **Toujours passer `--arch s390x`** : la valeur par défaut est amd64, même sur
  un hôte s390x.
- **KVM ou émulation.** Sur un hôte s390x (une LPAR ou un invité z/VM avec
  KVM), les VM s390x tournent en natif et démarrent en une vingtaine de
  secondes. Sur un hôte x86, elles sont émulées (TCG ; paquet
  `qemu-system-s390x` sous apt et dnf, `qemu-s390` sous zypper,
  `qemu-emulators-full` sous pacman), environ dix fois plus lentes. Dans une VM sans
  virtualisation imbriquée, libvirt se replie en silence sur l'émulation même
  quand les architectures concordent.
- **Mémoire.** Une VM s390x reçoit au moins 4 Gio par défaut ; les autres
  architectures gardent le minimum de la version au catalogue (1 à 3 Gio).
- **Machine.** `s390-ccw-virtio`, démarrage depuis le disque (IPL/zipl) : ni
  BIOS ni UEFI. La console est SCLP (`ttysclp0`), journalisée dans
  `/var/log/libvirt/qemu/<nom>-console.log`.
- **Debian** n'a pas d'image cloud s390x : la VM est installée par
  debian-installer, piloté par un preseed embarqué dans l'initrd. Son adresse
  est **fixe** (choisie dans .200–.249 du réseau libvirt), et non donnée par
  DHCP ; sa carte réseau s'appelle `enc1`.
- **Cache de téléchargement QEMU.** Quand le cache est actif, il intercepte le
  HTTPS des VM et le re-signe avec sa propre autorité ; le déploiement pose
  cette autorité dans chaque VM, par cloud-init ou, pour Debian, par
  l'installateur. Une VM déployée alors que le cache était arrêté, puis
  interceptée une fois le cache relancé, échoue sur tout téléchargement
  HTTPS : la redéployer.
- **Clé SSH.** Un déploiement qui installe ERPLibre exige une clé dans
  `~/.ssh` ; TODO en génère une au besoin, avant de créer la moindre VM.

## Réglages

| Variable | Défaut | Effet |
|---|---|---|
| `EL_SWAP_TARGET_GIB` | `8` | RAM + swap visés, en Gio ; `0` désactive le fichier d'échange |
| `EL_SWAP_FILE` | `/swapfile.erplibre` | chemin du fichier d'échange ; sur btrfs, le fichier va dans un sous-volume `.erplibre-swap` de son répertoire (`/.erplibre-swap/swapfile.erplibre` par défaut) |
| `EL_MEM_PER_JOB_MB` | `2048` | mémoire réservée par compilation parallèle |
| `EL_RUST_MIN_MINOR` | `95` | Rust minimal (1.95) sous lequel rustup est installé |
| `EL_PYTHON_PROVIDER` | `auto` | `auto`, `mise` ou `pyenv` ; `auto` prend un Python compatible de la distribution avant de rien installer, ce qui évite sur s390x de compiler CPython |
| `EL_PIP_PROVIDER` | `auto` | `auto`, `uv` ou `pip` |

## Dépannage

| Symptôme | Cause | Que faire |
|---|---|---|
| `zlib not available` à la fin d'une compilation pyenv | CPython compilé sans ses en-têtes `-dev` | `make install_os`, puis relancer |
| `Killed signal terminated program cc1plus` | mémoire insuffisante | 4 Gio de RAM ; vérifier que `el_swap_ensure` a ajouté du swap |
| `certificate signer not trusted` au `git clone` | VM interceptée par le cache QEMU sans son autorité | redéployer la VM avec le cache actif |
| `rustc 1.9x is not supported … requires rustc 1.95` | Rust trop ancien pour orjson | `make install_os` (rustup) ; vérifier l'accès à sh.rustup.rs |
| L'installation QEMU attend 20 minutes, puis `Permission denied (publickey)` | VM créée sans clé SSH | fournir une clé dans `~/.ssh` et redéployer |
| `run.sh` : `can't open file … odoo-bin` | sources d'Odoo non récupérées (`repo sync` interrompu) | relancer `make install_odoo_18` : il détecte les sources manquantes |
| `No module named 'babel'` pendant la phase de préparation | `config_update` tourne avant que Poetry ait posé les paquets | sans conséquence, l'installation continue |

## Pour les développeurs : où vit le code

Tout ce qui est **dédié** à s390x se trouve dans `script/install/S390x/` ; ce
qui sert toutes les architectures reste à sa place.

| Fichier | Rôle |
|---|---|
| `S390x/debian.sh` | partie s390x de l'installation apt |
| `S390x/fedora.sh` | partie s390x de l'installation dnf |
| `S390x/suse.sh` | partie s390x de l'installation zypper |
| `S390x/build_check.sh` | vérification des prérequis de compilation avant le venv d'outillage, sur toute architecture autre qu'amd64 et arm64 |
| `S390x/lib_lowmem.sh` | swap et limite des compilations parallèles |
| `S390x/lib_rust.sh` | version minimale de Rust, repli rustup |
| `S390x/lib_qpdf.sh` | qpdf compilé depuis les sources si trop ancien |
| `S390x/lib_proj.sh` | PROJ compilé depuis les sources si trop ancien |

Les fichiers `S390x/*.sh` sont **sourcés**, jamais exécutés : ils héritent des
variables et fonctions de l'appelant (`APT_GET`, `DNF`, `zyp_soft`), et un `exit` y arrête
toute l'installation, comme il le ferait dans l'appelant. Un script global
charge son fragment ainsi :

```bash
if [ "$(uname -m)" = "s390x" ]; then
  . ./script/install/S390x/debian.sh
fi
```

Ce qui reste global bien que s390x en dépende beaucoup :
`script/install/lib_python_provider.sh` (choix de l'interpréteur Python),
`script/install/swig_compat.h` (inclus dans chaque compilation de
`poetry install`), et `install_locally.sh`, qui n'appelle les limites s390x
qu'après avoir testé l'architecture. Les dépendances Python sont neutres
vis-à-vis de l'architecture : les marqueurs `platform_machine` (PyMuPDF exclu
sur s390x ; factur-x ≥ 6.8 ailleurs, < 4 sur s390x) sont conservés dans
l'unique verrou de chaque version d'Odoo
(`requirement/poetry.odoo18.0_python3.12.10.lock`).