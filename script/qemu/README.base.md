<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [fr] -->
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

<!-- [fr] -->
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
not assumed), or too many asset files for one APK — a ZIP holds 65535 entries
and the mobile repo ships 122 684, which only that repo can fix. The heavy
output goes to `~/erplibre-mobile-build.log` inside the VM so the install log
stays readable.

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

<!-- [fr] -->
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
ou trop de fichiers d'assets pour un APK — un ZIP tient 65535 entrées et le
dépôt mobile en embarque 122 684, ce que lui seul peut corriger. Le détail va
dans `~/erplibre-mobile-build.log`, dans la VM, pour que le journal
d'installation reste lisible.

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
On **s390x and arm64** the parameter lives on the `kvm` module itself, not on
`kvm_intel` / `kvm_amd` — and `/sys/module/kvm/parameters/nested` does not even
exist on x86. Reading the wrong file returns a reassuring `0` that commands
nothing:

<!-- [fr] -->
Sur **s390x et arm64**, le paramètre vit sur le module `kvm` lui-même, et non
sur `kvm_intel` / `kvm_amd` — et `/sys/module/kvm/parameters/nested` n'existe
même pas sur x86. Lire le mauvais fichier renvoie un `0` rassurant qui ne
commande rien :

<!-- [common] -->
```bash
echo "options kvm nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
sudo modprobe -r kvm && sudo modprobe kvm               # ou / or reboot
```

<!-- [en] -->
`nested` on a machine means « let MY guests run VMs ». To accelerate a VM
created on host H, the setting belongs to the hypervisor **above** H, not to H
itself. The one command that settles it, run on H:

<!-- [fr] -->
`nested` sur une machine signifie « j'autorise MES invités à faire tourner des
VM ». Pour accélérer une VM créée sur l'hôte H, le réglage appartient à
l'hyperviseur **au-dessus** de H, pas à H. La commande qui tranche, sur H :

<!-- [common] -->
```bash
ls -l /dev/kvm     # absent -> pas d'imbrication, tout sera émulé
```

<!-- [en] -->
Measured on an s390x host that was itself a KVM guest without nesting:
`/dev/kvm` absent, `virsh dumpxml` showing `<domain type='qemu'>`, and a
7 min 30 boot instead of well under a minute. `systemd-detect-virt` inside the
VM is **not** proof of acceleration — on s390x, QEMU fabricates the STSI answer
and reports `kvm` even under TCG. Only `<domain type=…>` on the host is
conclusive.

If nesting is unavailable, QEMU still runs via software emulation (TCG) — it
works but is slow.

<!-- [fr] -->
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
