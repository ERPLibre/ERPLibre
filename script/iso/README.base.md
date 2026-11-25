<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# ERPLibre Arch Linux ISO (x86_64)

`archlinux/build_iso.py` builds a custom Arch Linux ISO with
[archiso](https://wiki.archlinux.org/title/Archiso), starting from its
`releng` profile. The image boots in BIOS and UEFI mode, can be written as is
to a USB key (hybrid image), and opens an installer on the first console
that installs **Arch Linux + GNOME (gdm) + ERPLibre**, with an ERPLibre
profile chosen during installation.

The target machine needs network access: packages and the ERPLibre
repository are downloaded during installation.

<!-- [fr] -->
# ISO ERPLibre Arch Linux (x86_64)

`archlinux/build_iso.py` construit une ISO Arch Linux personnalisée avec
[archiso](https://wiki.archlinux.org/title/Archiso), à partir de son profil
`releng`. L'image démarre en BIOS comme en UEFI, s'écrit telle quelle sur une
clé USB (image hybride) et ouvre, sur la première console, un installateur
qui pose **Arch Linux + GNOME (gdm) + ERPLibre**, avec un profil ERPLibre
choisi pendant l'installation.

La machine cible doit avoir accès au réseau : les paquets et le dépôt
ERPLibre sont téléchargés pendant l'installation.

<!-- [en] -->
## Build

By default the ISO is built **in an up-to-date Arch Linux container**
(`--builder container`): the host needs only Podman (preferred) or Docker,
neither `archiso` nor an up-to-date pacman database, nor even Arch Linux.
The image `erplibre-isobuilder:<YYYYMMDD>` (also tagged `latest`) is built
from `archlinux/container/Containerfile` (`pacman -Syu archiso archinstall`)
on first use, when it is more than 14 days old, or with `--refresh-image`;
older dated tags are removed after a rebuild. Inside, `build_iso.py` runs
again with `--builder host`; the repository is mounted read-only, the output
directory and a persistent pacman cache (`~/.erplibre/iso/pkgcache`, never
purged by the script) read-write.

| Engine | How mkarchiso runs | Extra flags |
|---|---|---|
| Podman without root | as a regular user (UID 1000 = caller, `--userns=keep-id`), through `unshare` like on a host | `--security-opt unmask=/proc/*` (a masked `/proc` forbids mounting a new one in a nested user namespace) |
| Docker, or Podman run by root | as root | `--cap-add SYS_ADMIN` (mounts of the build chroot); files are then given back to the caller (`--chown`) |

`--privileged` is never used. Rootless Podman cannot run mkarchiso as root
(devtmpfs cannot be mounted in a user namespace), and rootless Docker is
refused for the same reason. The rootless Podman mode needs the usual
65,536-ID `/etc/subuid` range for the account.

`--builder host` uses the host's `archiso` (Arch Linux host). Since archiso
89, `mkarchiso` runs as a regular user (user namespaces, with a
`/etc/subuid` range for the account); older versions are run through `sudo`.
`--builder auto` uses a container when an engine answers, the host
otherwise.

<!-- [fr] -->
## Construction

Par défaut, l'ISO se construit **dans un conteneur Arch Linux à jour**
(`--builder container`) : l'hôte n'a besoin que de Podman (préféré) ou de
Docker, ni d'`archiso`, ni d'une base pacman à jour, ni même d'être une Arch.
L'image `erplibre-isobuilder:<AAAAMMJJ>` (aussi étiquetée `latest`) est
construite depuis `archlinux/container/Containerfile` (`pacman -Syu archiso
archinstall`) au premier usage, quand elle a plus de 14 jours, ou sur
`--refresh-image` ; les étiquettes datées plus anciennes sont retirées après
une reconstruction. Dedans, `build_iso.py` se relance en `--builder host` ;
le dépôt est monté en lecture seule, le répertoire de sortie et un cache
pacman persistant (`~/.erplibre/iso/pkgcache`, jamais purgé par le script)
en lecture-écriture.

| Moteur | Comment tourne mkarchiso | Options ajoutées |
|---|---|---|
| Podman sans root | en simple utilisateur (UID 1000 = l'appelant, `--userns=keep-id`), par `unshare` comme sur un hôte | `--security-opt unmask=/proc/*` (un `/proc` masqué interdit d'en monter un nouveau dans un espace de noms utilisateur imbriqué) |
| Docker, ou Podman lancé par root | en root | `--cap-add SYS_ADMIN` (montages du chroot de construction) ; les fichiers sont ensuite rendus à l'appelant (`--chown`) |

`--privileged` n'est jamais employé. Podman sans root ne peut pas lancer
mkarchiso en root (devtmpfs ne se monte pas dans un espace de noms
utilisateur), et Docker sans root est refusé pour la même raison. Le mode
Podman sans root exige la plage `/etc/subuid` usuelle de 65 536 identifiants
pour le compte.

`--builder host` emploie l'`archiso` de l'hôte (hôte Arch Linux). Depuis
archiso 89, `mkarchiso` tourne en simple utilisateur (espaces de noms
utilisateur, avec une plage `/etc/subuid` pour le compte) ; les versions plus
anciennes passent par `sudo`. `--builder auto` prend un conteneur si un
moteur répond, l'hôte sinon.

<!-- [common] -->
```bash
./script/iso/archlinux/build_iso.py --dry-run          # plan only
./script/iso/archlinux/build_iso.py                    # container, master
./script/iso/archlinux/build_iso.py --refresh-image --branch develop
sudo pacman -S --needed archiso                        # --builder host only
./script/iso/archlinux/build_iso.py --builder host --keep-work
```

<!-- [en] -->
Result: `~/.erplibre/iso/erplibre-archlinux-<YYYY.MM.DD>-x86_64.iso` and its
`.sha256` file (`sha256sum -c` format). The work directory
(`~/.erplibre/iso/work/<date>`) is removed after a successful build, unless
`--keep-work` is given; it is kept after a failure. A failed build leaves
neither a partial ISO nor an outdated `.sha256` under the ISO's name.
`--dry-run` refuses the same things as a real build: an unexpected releng
profile, an existing work directory. In container mode the work directory
lives inside the container and disappears with it, unless `--work-dir` or
`--keep-work` puts it on the host; its `build/` tree then belongs to the
container's IDs, and the script prints the command that removes it
(`podman unshare rm -rf …` or `sudo rm -rf …`). The container-mode
`--dry-run` prints the exact `build` and `run` commands without starting
anything; the releng checks happen inside the container.

| Option | Default | Effect |
|---|---|---|
| `--branch` | `master` | ERPLibre branch cloned on the target |
| `--git-url` | `https://github.com/erplibre/erplibre` | ERPLibre repository |
| `--output-dir` | `~/.erplibre/iso` (`~/.erplibre/iso/autotest` with `--auto-default`) | ISO and checksum |
| `--work-dir` | `~/.erplibre/iso/work/<date>` | archiso profile and build tree |
| `--lang` | `EL_LANG`, else `fr` | installer language |
| `--auto-default <profile>` | — | **tests only**, see below |
| `--builder` | `container` | `container`, `host` or `auto` |
| `--runtime` | `podman`, else `docker` | engine of the container mode |
| `--refresh-image` | — | rebuild the builder image even if recent |
| `--pkg-cache` | `~/.erplibre/iso/pkgcache` | pacman cache of the container mode |
| `--source-date-epoch` | now | date of the ISO (file name, label) |

<!-- [fr] -->
Résultat : `~/.erplibre/iso/erplibre-archlinux-<AAAA.MM.JJ>-x86_64.iso` et son
fichier `.sha256` (format de `sha256sum -c`). Le répertoire de travail
(`~/.erplibre/iso/work/<date>`) est effacé après une construction réussie,
sauf avec `--keep-work` ; il est gardé après un échec. Une construction
échouée ne laisse au nom de l'ISO ni ISO tronquée ni `.sha256` périmé.
`--dry-run` refuse ce que refuserait une vraie construction : un profil
releng inattendu, un répertoire de travail existant. En mode container, le
répertoire de travail vit dans le conteneur et disparaît avec lui, sauf si
`--work-dir` ou `--keep-work` le place sur l'hôte ; son arbre `build/`
appartient alors aux identifiants du conteneur, et le script affiche la
commande qui l'efface (`podman unshare rm -rf …` ou `sudo rm -rf …`). Le
`--dry-run` du mode container affiche les commandes `build` et `run` exactes
sans rien démarrer ; les vérifications de releng ont lieu dans le conteneur.

| Option | Défaut | Effet |
|---|---|---|
| `--branch` | `master` | branche ERPLibre clonée sur la cible |
| `--git-url` | `https://github.com/erplibre/erplibre` | dépôt ERPLibre |
| `--output-dir` | `~/.erplibre/iso` (`~/.erplibre/iso/autotest` avec `--auto-default`) | ISO et empreinte |
| `--work-dir` | `~/.erplibre/iso/work/<date>` | profil archiso et arbre de construction |
| `--lang` | `EL_LANG`, sinon `fr` | langue de l'installateur |
| `--auto-default <profil>` | — | **tests seulement**, voir plus bas |
| `--builder` | `container` | `container`, `host` ou `auto` |
| `--runtime` | `podman`, sinon `docker` | moteur du mode container |
| `--refresh-image` | — | reconstruire l'image de construction même récente |
| `--pkg-cache` | `~/.erplibre/iso/pkgcache` | cache pacman du mode container |
| `--source-date-epoch` | maintenant | date de l'ISO (nom du fichier, étiquette) |

<!-- [en] -->
## Writing to a USB key

The ISO is a hybrid image: copy it to the whole device (not a partition).
**Everything on the key is erased.**

<!-- [fr] -->
## Écriture sur une clé USB

L'ISO est une image hybride : la copier sur le périphérique entier (pas sur
une partition). **Tout le contenu de la clé est effacé.**

<!-- [common] -->
```bash
sha256sum -c erplibre-archlinux-*-x86_64.iso.sha256
sudo dd if=erplibre-archlinux-<date>-x86_64.iso of=/dev/sdX bs=4M \
    conv=fsync oflag=direct status=progress
```

<!-- [en] -->
## Installing

The default boot entry starts the live system; root is logged in
automatically on `tty1` and the ERPLibre installer screen opens
(`erplibre-installer-ui`, a [Textual](https://textual.textualize.io/)
application). On a serial console, with `TERM=dumb`, without a terminal, or
with `--plain`, the same questions are asked line by line instead. The
language comes from `erplibre.lang=fr|en`, else from `profiles.json`; `L`
switches it on the home screen.

The home screen offers three choices:

1. **Install ERPLibre**, driven by the machine profile
   (`/erplibre/machine.json` on the key, else the `generic` profile, shown as
   *guided*). The form asks, in this order:
   - the **keyboard layout** first: `loadkeys` applies it as soon as the
     field is left, because the LUKS passphrases that follow are typed with
     the console layout, and the installed system's console gets the same
     layout;
   - every `ask` field of the resolved profile (time zone, host name,
     locales, layout, secret volume…), then the user name;
   - the user password and its confirmation, the root policy (locked, with
     administration through sudo, or its own password), the LUKS passphrase
     and its confirmation when the layout is `lvm_on_luks`, the secret volume
     passphrase when there is one;
   - the disk, when `auto` cannot decide (no candidate, or several);
   - the ERPLibre profile: **ERPLibre + Odoo 18**
     (`make install_os && make install_odoo_18`, then `erplibre.service`,
     Odoo on port 8069), **ERPLibre Home**, **ERPLibre Dev**
     (`make install_dev`, no service) or **GNOME only**.

   A **summary** follows: the resolved plan, the hardware facts, the
   warnings, the commands of the disk stage and the disk that will be
   **erased**, whose name must be typed to go on. The installation then runs
   on the same screen, with the core's output and the ERPLibre stage log; the
   last screen offers to reboot, to quit to the shell or to go back home.
2. **Start ERPLibre TODO**: the TODO of this repository, embedded in the
   key under `/opt/erplibre` and run with the live Python, for instance to
   write another key (see *ERPLibre TODO on the key* below). Quitting it
   brings the home screen back.
3. **Run archinstall (guided, pre-filled)**: the previous path. After the
   ERPLibre profile is chosen, archinstall opens with GNOME, gdm,
   NetworkManager and pipewire already set; it asks the disk, **a user
   account** (ERPLibre is installed for it), the language and the time zone.

Passwords and passphrases are never written to the key: they are typed at
installation, stay in memory, and reach the core through a 0600 file on
`/run/erplibre-install` (tmpfs) that is overwritten and deleted when the
core returns. `erplibre-installer-ui --dry-run` asks everything and shows
the summary and the plan, but erases nothing.

The ERPLibre profiles and their commands come from the same table as the
QEMU deployment (`QemuInstallMixin._qemu_install_profiles` in
`script/todo/qemu_install.py`).

ERPLibre is installed inside archinstall's chroot, at the end of the
installation, by `erplibre-stage.sh` (archinstall `custom_commands`): it
clones the repository as the user into `~/git/erplibre`, starts PostgreSQL
with `pg_ctl` (services cannot be started in a chroot), runs the profile
command with temporary passwordless sudo, then removes that sudo rule. The
log is `/var/log/erplibre-install.log` on the installed system. If this
stage fails, the system and GNOME still boot; rerun it with
`sudo /usr/local/sbin/erplibre-stage`.

Quitting the installer leaves a root shell; `erplibre-install` relaunches
it.

<!-- [fr] -->
## Installation

L'entrée de démarrage par défaut lance le système live ; root est connecté
automatiquement sur `tty1` et l'écran de l'installateur ERPLibre s'ouvre
(`erplibre-installer-ui`, une application
[Textual](https://textual.textualize.io/)). Sur une console série, avec
`TERM=dumb`, sans terminal ou avec `--plain`, les mêmes questions sont
posées ligne à ligne. La langue vient de `erplibre.lang=fr|en`, sinon de
`profiles.json` ; `L` la change sur l'écran d'accueil.

L'écran d'accueil propose trois choix :

1. **Installer ERPLibre**, piloté par le profil machine
   (`/erplibre/machine.json` sur la clé, sinon le profil `generic`, affiché
   *guidé*). Le formulaire demande, dans cet ordre :
   - la **disposition du clavier** d'abord : `loadkeys` l'applique dès qu'on
     quitte le champ, car les phrases LUKS qui suivent se tapent avec la
     disposition de la console, et la console du système installé reçoit
     la même ;
   - chaque champ `ask` du profil résolu (fuseau, nom d'hôte, locales,
     disposition du disque, volume secret…), puis le nom du compte ;
   - le mot de passe du compte et sa confirmation, la politique root
     (verrouillé, l'administration passant par sudo, ou son propre mot de
     passe), la phrase LUKS et sa confirmation quand la disposition est
     `lvm_on_luks`, la phrase du volume secret s'il y en a un ;
   - le disque, quand `auto` ne tranche pas (aucun candidat, ou plusieurs) ;
   - le profil ERPLibre : **ERPLibre + Odoo 18**
     (`make install_os && make install_odoo_18`, puis `erplibre.service`,
     Odoo sur le port 8069), **ERPLibre Home**, **ERPLibre Dev**
     (`make install_dev`, sans service) ou **GNOME seul**.

   Un **récapitulatif** suit : le plan résolu, les faits du matériel, les
   mises en garde, les commandes de l'étape disque et le disque qui sera
   **effacé**, dont il faut taper le nom pour continuer. L'installation se
   déroule ensuite sur le même écran, avec la sortie du cœur et le journal
   de l'étape ERPLibre ; le dernier écran propose de redémarrer, de quitter
   vers le shell ou de revenir à l'accueil.
2. **Démarrer le TODO d'ERPLibre** : le TODO de ce dépôt, embarqué sur la
   clé sous `/opt/erplibre` et exécuté par le Python du live, par exemple
   pour écrire une autre clé (voir *Le TODO d'ERPLibre sur la clé*
   ci-dessous). En le quittant, on revient à l'écran d'accueil.
3. **Lancer archinstall (guidé, pré-rempli)** : la voie précédente. Une
   fois le profil ERPLibre choisi, archinstall s'ouvre avec GNOME, gdm,
   NetworkManager et pipewire déjà réglés ; il demande le disque, **un
   compte utilisateur** (ERPLibre est installé pour lui), la langue et le
   fuseau.

Les mots de passe et phrases secrètes ne sont jamais écrits sur la clé : ils
se tapent à l'installation, restent en mémoire, et arrivent au cœur par un
fichier 0600 sur `/run/erplibre-install` (tmpfs), écrasé puis effacé quand
le cœur rend la main. `erplibre-installer-ui --dry-run` pose toutes les
questions et montre le récapitulatif et le plan, mais n'efface rien.

Les profils ERPLibre et leurs commandes viennent de la même table que le
déploiement QEMU (`QemuInstallMixin._qemu_install_profiles` dans
`script/todo/qemu_install.py`).

ERPLibre est installé dans le chroot d'archinstall, à la fin de
l'installation, par `erplibre-stage.sh` (`custom_commands` d'archinstall) :
il clone le dépôt en tant que l'utilisateur dans `~/git/erplibre`, démarre
PostgreSQL par `pg_ctl` (un chroot ne démarre pas de service), lance la
commande du profil avec un sudo sans mot de passe temporaire, puis retire
cette règle sudo. Le journal est `/var/log/erplibre-install.log` sur le
système installé. Si cette étape échoue, le système et GNOME démarrent quand
même ; la relancer par `sudo /usr/local/sbin/erplibre-stage`.

Quitter l'installateur laisse un shell root ; `erplibre-install` le relance.

<!-- [en] -->
## ERPLibre TODO on the key

`/opt/erplibre` holds a checkout of the repository as it stands when the
ISO is built, chosen by git rather than by walking the disk:

- tracked files (`git ls-files --cached`), copied from the working tree,
  so uncommitted changes are included;
- untracked files that `.gitignore` does not exclude
  (`git ls-files --others --exclude-standard`): the new files of a branch,
  except those whose name looks like a secret or a data dump (`.env`,
  `*.pem`, `*.key`, `id_rsa*`, `*credential*`, `*token*`, `*.sql`,
  archives… see `CHECKOUT_UNTRACKED_DENIED` in `build_iso.py`);
- never `private/` (except its `.gitignore` and `__init__.py`), `tasks/`,
  `.git`, Python caches, symbolic links, nested repositories, or what
  `.gitignore` excludes (virtualenvs, addons, built ISOs).

The build plan prints the number of files, how many are untracked, and
their size, then names every untracked file kept and every untracked file
left out. In container mode git runs on the host and hands the list to
the container in a temporary file of the output directory, deleted after
the run: the builder image needs no git, and a git worktree works too.
Outside a git checkout, the build stops.

The TODO runs with the live Python and Arch packages rather than a
`pip install --target` of `requirement/erplibre_require-ments.txt`:
Arch packages are built for that exact Python, and only what the TODO
imports at start-up goes into the ISO (`EXTRA_LIVE_PACKAGES` in
`build_iso.py`). The full requirements weigh about 480 MiB installed and
87 MiB once compressed; the checkout adds about 7 MiB to the ISO.

`erplibre-todo` writes the live Python version into the copied `conf/`,
passes the home screen language, and enlarges the live's writable layer
(`/run/archiso/cowspace`, 256 MiB by default) to 75 % of the memory
(`EL_COW_SIZE`), so that the **System › Bootable USB key** menu can keep an
ISO of more than 1 GiB under `~/.erplibre/iso`. That menu works in the live
session: it detects the keys, never offers the key the live booted from
(mounted on `/run/archiso/bootmnt`), and writes an ISO picked with the file
browser, with or without a machine profile (`xorriso` is on the key).
Building an ISO from the live is refused with its reason (the copy on the
key is not a git checkout, and the live has no container engine), and the
menus that need an installed ERPLibre (Odoo, databases, virtualenvs) report
their error.

<!-- [fr] -->
## Le TODO d'ERPLibre sur la clé

`/opt/erplibre` porte un checkout du dépôt tel qu'il est au moment de
construire l'ISO, choisi par git plutôt que par un parcours du disque :

- les fichiers suivis (`git ls-files --cached`), copiés depuis l'arbre de
  travail, donc avec les modifications non commitées ;
- les fichiers non suivis que `.gitignore` n'écarte pas
  (`git ls-files --others --exclude-standard`) : les nouveaux fichiers
  d'une branche, sauf ceux dont le nom a la forme d'un secret ou d'un
  vidage de données (`.env`, `*.pem`, `*.key`, `id_rsa*`, `*credential*`,
  `*token*`, `*.sql`, archives… voir `CHECKOUT_UNTRACKED_DENIED` dans
  `build_iso.py`) ;
- jamais `private/` (sauf son `.gitignore` et son `__init__.py`), `tasks/`,
  `.git`, les caches Python, les liens symboliques, les dépôts imbriqués ni
  ce que `.gitignore` écarte (venvs, addons, ISO construites).

Le plan de construction affiche le nombre de fichiers, combien sont non
suivis, et leur poids, puis nomme chaque fichier non suivi retenu et chaque
fichier non suivi écarté. En mode container, git tourne sur l'hôte et passe
la liste au conteneur dans un fichier temporaire du répertoire de sortie,
effacé après le run : l'image n'a pas besoin de git, et un worktree git
fonctionne aussi. Hors d'un checkout git, la construction s'arrête.

Le TODO tourne avec le Python du live et des paquets Arch plutôt qu'un
`pip install --target` de `requirement/erplibre_require-ments.txt` : les
paquets Arch sont construits pour ce Python précis, et seul ce que le TODO
importe au démarrage entre dans l'ISO (`EXTRA_LIVE_PACKAGES` de
`build_iso.py`). Les requirements entiers pèsent environ 480 Mio installés
et 87 Mio compressés ; le checkout ajoute environ 7 Mio à l'ISO.

`erplibre-todo` écrit la version du Python du live dans la copie de
`conf/`, transmet la langue de l'écran d'accueil et agrandit la couche
écrite du live (`/run/archiso/cowspace`, 256 Mio par défaut) à 75 % de la
mémoire (`EL_COW_SIZE`), pour que le menu **Système › Clé USB amorçable**
puisse garder une ISO de plus d'un Gio sous `~/.erplibre/iso`. Ce menu
fonctionne dans la session live : il détecte les clés, ne propose jamais la
clé d'où le live a démarré (montée sur `/run/archiso/bootmnt`) et écrit une
ISO choisie avec le navigateur de fichiers, avec ou sans profil machine
(`xorriso` est sur la clé). Construire une ISO depuis le live est refusé, raison
à l'appui (la copie de la clé n'est pas un checkout git, et le live n'a
aucun moteur de conteneur), et les menus qui demandent un ERPLibre
installé (Odoo, bases, venvs) rapportent leur erreur.

<!-- [en] -->
## Automatic installation (tests)

The boot entry **ERPLibre automatic install (erases first disk)** exists
only on the test variant (`--auto-default`, below): the installation ISO
has no such entry, and `erplibre.auto=` typed by hand on its kernel command
line is refused (code `22`), since the ISO lacks the test marker
`/usr/local/share/erplibre-install/autotest`. The entry installs without
any question on the first disk that is not the boot medium, with the user
`erplibre`, then powers off. The password reaches the configuration tool
through the environment, never its arguments, and the `--creds` file lives
on the tmpfs `/run/erplibre-install`, overwritten and deleted as soon as
archinstall returns. Progress and the
final line `__ERPLIBRE_EXIT__ <code>` go to the serial console `ttyS0`, the
convention of `script/todo/qemu_install_monitor.py`.

It erases nothing until it has identified the boot medium, by the ISO's UUID
or by the `/run/archiso` mount: on a key written with `dd` the UUID always
matches. A key whose ISO files were copied onto a FAT32 partition carries
neither once `copytoram` has unmounted it, so the installer stops with code
`21`. It runs once per boot: relaunching `erplibre-install` afterwards is
refused rather than erasing the freshly installed disk again.

| Kernel parameter | Effect |
|---|---|
| `erplibre.auto=<profile>` | `odoo18`, `home`, `dev`, `gnome`; `1` = default profile |
| `erplibre.password=<pw>` | password of the `erplibre` user (default `erplibre`, for test machines only) |
| `erplibre.lang=fr\|en` | installer language |
| `erplibre.nopoweroff` | stay on at the end |
| `erplibre.ssh` | install `openssh` and enable `sshd` on the target |

`build_iso.py --auto-default <profile>` builds a **test variant**,
`erplibre-archlinux-autotest-<date>-x86_64.iso`, whose default boot entry
(3 s timeout, BIOS and UEFI) is the automatic install of `<profile>` with
`erplibre.ssh`: a virtual machine booted on it installs unattended, and the
installed system can then be checked over SSH. Its default output directory,
`~/.erplibre/iso/autotest`, keeps it out of the TODO USB catalogue, which
looks only at `~/.erplibre/iso`; `--output-dir ~/.erplibre/iso` is refused.
Never write it to a key meant for a real installation.

<!-- [fr] -->
## Installation automatique (tests)

L'entrée de démarrage **ERPLibre automatic install (erases first disk)**
n'existe que sur la variante de test (`--auto-default`, plus bas) : l'ISO
d'installation n'a pas cette entrée, et `erplibre.auto=` tapé à la main sur
sa ligne de commande du noyau est refusé (code `22`), faute de la marque de
test `/usr/local/share/erplibre-install/autotest`. L'entrée installe sans
aucune question sur le premier disque qui n'est pas le support de
démarrage, avec le compte `erplibre`, puis éteint la machine. Le mot de
passe arrive à l'outil de configuration par l'environnement, jamais par
ses arguments, et le fichier `--creds` vit sur le tmpfs
`/run/erplibre-install`, écrasé puis effacé dès qu'archinstall rend la
main. La progression et la ligne finale
`__ERPLIBRE_EXIT__ <code>` vont sur la console série `ttyS0`, la convention
de `script/todo/qemu_install_monitor.py`.

Elle n'efface rien tant qu'elle n'a pas reconnu le support de démarrage,
par l'UUID de l'ISO ou par le montage `/run/archiso` : sur une clé écrite
par `dd`, l'UUID correspond toujours. Une clé dont les fichiers de l'ISO ont
été copiés sur une partition FAT32 ne porte ni l'un ni l'autre une fois
démontée par `copytoram` : l'installateur s'arrête alors avec le code `21`.
Elle ne tourne qu'une fois par démarrage : relancer `erplibre-install`
ensuite est refusé plutôt que d'effacer de nouveau le disque installé.

| Paramètre noyau | Effet |
|---|---|
| `erplibre.auto=<profil>` | `odoo18`, `home`, `dev`, `gnome` ; `1` = profil par défaut |
| `erplibre.password=<mdp>` | mot de passe du compte `erplibre` (défaut `erplibre`, pour machines de test seulement) |
| `erplibre.lang=fr\|en` | langue de l'installateur |
| `erplibre.nopoweroff` | rester allumé à la fin |
| `erplibre.ssh` | installer `openssh` et activer `sshd` sur la cible |

`build_iso.py --auto-default <profil>` construit une **variante de test**,
`erplibre-archlinux-autotest-<date>-x86_64.iso`, dont l'entrée de démarrage
par défaut (délai de 3 s, BIOS et UEFI) est l'installation automatique de
`<profil>` avec `erplibre.ssh` : une machine virtuelle qui démarre dessus
s'installe seule, et le système installé s'inspecte ensuite par SSH. Son
répertoire de sortie par défaut, `~/.erplibre/iso/autotest`, la tient hors
du catalogue USB du TODO, qui ne regarde que `~/.erplibre/iso` ;
`--output-dir ~/.erplibre/iso` est refusé. Ne jamais l'écrire sur une clé
destinée à une vraie installation.

<!-- [en] -->
## Installation driven by the machine profile

`erplibre-installer` is the installer core that follows the machine profile
(`/erplibre/machine.json` on the key, else the `generic` profile). It asks
nothing: everything comes from an **answers document** (JSON) that the
screen fills in, or that a test passes on the kernel command line. It
resolves the profile against the hardware, refuses while a question, a
blocking warning, a secret or the typed confirmation of the erased disk is
missing, then:

1. **disk stage** (`erplibre_disk.py`): GPT (ESP, or `bios_grub` + `/boot`
   in BIOS), LUKS2 with the resolved sector size, iteration time and
   persistent discards, LVM (swap, optional nested-LUKS secret volume,
   root minus the free space kept for e2scrub), mounted on
   `/mnt/archinstall`. The disk is re-read just before it is erased, and
   refused if its size or model differs from the summary, if anything is
   stacked on it (LVM, LUKS, RAID, multipath), or, when an NVMe reformat
   is confirmed, if another namespace shares its controller (the 4 KiB
   reformat is then not even offered). An interrupted disk stage closes
   what it opened. If the boot medium is not identified, no disk is chosen
   automatically: the screen asks for it;
2. **archinstall** `--silent` in pre-mounted mode with the **ERPLibre
   plugin** (`erplibre_plugin.py`): systemd initramfs hooks (`sd-encrypt`,
   `lvm2`), systemd-boot entries and fallback entries or GRUB, UKI,
   locales, zram, e2scrub, AppArmor, shell, swap line in fstab. The plugin
   refuses any archinstall other than 4.5;
3. the ERPLibre stage, unchanged, then unmount.

Secrets are never stored. They are accepted only from
`erplibre.answers=b64:<base64>` (automatic tests) or from a file under
`/run/erplibre-install` (tmpfs). LUKS passphrases reach `cryptsetup` on its
standard input; account passwords reach archinstall through a `--creds`
file (0600, tmpfs) that is overwritten and deleted as soon as archinstall
returns.

```
erplibre-installer --answers /run/erplibre-install/answers.json [--dry-run]
erplibre-installer --auto --serial /dev/ttyS0   # reads erplibre.answers=
```

The kernel parameter `erplibre.answers=` makes `erplibre-install` hand the
automatic installation to this core. Exit codes: `0`, the ERPLibre stage
codes, `21` answers, `22` profile, `23` disk refused, `24` disk stage
failed (or a UUID missing after it), `25` archinstall version, `26`
archinstall, `27` plugin, `130` interrupted.

<!-- [fr] -->
## Installation pilotée par le profil machine

`erplibre-installer` est le cœur de l'installateur qui suit le profil
machine (`/erplibre/machine.json` sur la clé, sinon le profil `generic`). Il
ne pose aucune question : tout vient d'un **document de réponses** (JSON)
que l'écran remplit, ou qu'un test passe sur la ligne de commande du noyau.
Il résout le profil sur le matériel, refuse tant qu'il manque une réponse,
qu'une mise en garde bloque, qu'un secret ou la confirmation tapée du
disque effacé manque, puis :

1. **étape disque** (`erplibre_disk.py`) : GPT (ESP, ou `bios_grub` +
   `/boot` en BIOS), LUKS2 avec la taille de secteur, le temps d'itération
   et les discards persistants résolus, LVM (swap, volume secret en LUKS
   imbriqué, racine moins l'espace libre gardé pour e2scrub), monté sur
   `/mnt/archinstall`. Le disque est relu juste avant d'être effacé, et
   refusé si sa taille ou son modèle diffère du récapitulatif, si quoi que
   ce soit s'y empile (LVM, LUKS, RAID, multipath), ou, quand un
   reformatage NVMe est confirmé, si un autre espace de noms partage son
   contrôleur (le reformatage 4 Kio n'est alors même pas proposé). Une
   étape disque interrompue referme ce qu'elle a ouvert. Si le support de
   démarrage n'est pas reconnu, aucun disque n'est choisi
   automatiquement : l'écran le demande ;
2. **archinstall** `--silent` en mode pré-monté avec le **greffon
   ERPLibre** (`erplibre_plugin.py`) : HOOKS systemd (`sd-encrypt`,
   `lvm2`), entrées systemd-boot et de secours ou GRUB, UKI, locales,
   zram, e2scrub, AppArmor, shell, ligne de swap dans fstab. Le greffon
   refuse tout archinstall autre que 4.5 ;
3. l'étape ERPLibre, inchangée, puis le démontage.

Les secrets ne sont jamais stockés. Ils ne sont acceptés que de
`erplibre.answers=b64:<base64>` (tests automatiques) ou d'un fichier sous
`/run/erplibre-install` (tmpfs). Les phrases LUKS arrivent à `cryptsetup`
sur son entrée standard ; les mots de passe des comptes arrivent à
archinstall par un fichier `--creds` (0600, tmpfs) écrasé puis effacé dès
qu'archinstall rend la main.

```
erplibre-installer --answers /run/erplibre-install/answers.json [--dry-run]
erplibre-installer --auto --serial /dev/ttyS0   # lit erplibre.answers=
```

Le paramètre noyau `erplibre.answers=` fait passer l'installation
automatique de `erplibre-install` à ce cœur. Codes de sortie : `0`, ceux de
l'étape ERPLibre, `21` réponses, `22` profil, `23` disque refusé, `24` étape
disque en échec (ou UUID manquant après elle), `25` version d'archinstall,
`26` archinstall, `27` greffon, `130` interrompu.

<!-- [en] -->
## Files

<!-- [fr] -->
## Fichiers

<!-- [common] -->
```
script/iso/archlinux/
├── build_iso.py                         releng + overlay -> mkarchiso
├── container_build.py                   container mode: engine, image, argv
├── container/Containerfile              builder image (archiso, archinstall)
└── profile/airootfs/usr/local/
    ├── bin/erplibre-install             tty1 entry: screen or automatic
    ├── bin/erplibre-installer-ui        installer screen (Textual / text)
    ├── bin/erplibre-install-config      archinstall user_configuration.json
    ├── bin/erplibre-installer           profile-driven installer core
    ├── bin/erplibre-todo                TODO embedded in the key
    └── share/erplibre-install/
        ├── erplibre-stage.sh            ERPLibre stage (archinstall chroot)
        ├── erplibre_ui.py               screen: mode, home actions
        ├── erplibre_ui_flow.py          fields, checks, summary, core run
        ├── erplibre_ui_tui.py           Textual screens
        ├── erplibre_ui_plain.py         line-by-line text mode
        ├── erplibre_ui_i18n.py          fr / en (messages.fr.json)
        ├── erplibre_installer.py        core: answers, prepare, run
        ├── erplibre_disk.py             disk stage: plan, preflight, run
        ├── erplibre_archinstall.py      pre-mounted config, --creds
        ├── erplibre_plugin.py           archinstall plugin (4.5)
        └── user_configuration.template.json
```

<!-- [en] -->
`profiles.json` (profiles, network source, `erplibre.service` template) and
`messages.fr.json` (the French of every phrase of the screen, taken from
`script/todo/todo_i18n.py`) are generated into the same directory at build
time, and `machine/` (`machine_profile.py`, `facts.py`,
`profile_messages.py`, `profiles/*.json`) is copied there from
`script/iso/archlinux/machine/`. The network source — the
cloned repository and branch — is set in one place: `network_source` in
`profiles.json`, read by `el_network_source_prepare` in
`erplibre-stage.sh`.

Tests: `./script/test/run_unit_test.sh test/test_iso_archlinux_build.py`
(no archiso nor container engine needed), `test/test_iso_container_build.py`,
and `test/test_iso_installer_{disk,plugin,core,ui}.py` (no archinstall
needed; the screen tests need `textual`, else they are skipped).

<!-- [fr] -->
`profiles.json` (profils, source réseau, gabarit de `erplibre.service`) et
`messages.fr.json` (le français de chaque phrase de l'écran, tiré de
`script/todo/todo_i18n.py`) sont générés dans le même répertoire à la
construction, et `machine/` (`machine_profile.py`, `facts.py`,
`profile_messages.py`, `profiles/*.json`) y est copié depuis
`script/iso/archlinux/machine/`. La source réseau — dépôt
cloné et branche — se règle en un seul endroit : `network_source` dans
`profiles.json`, lu par `el_network_source_prepare` dans
`erplibre-stage.sh`.

Tests : `./script/test/run_unit_test.sh test/test_iso_archlinux_build.py`
(sans archiso ni moteur de conteneur), `test/test_iso_container_build.py`,
et `test/test_iso_installer_{disk,plugin,core,ui}.py` (sans archinstall ;
les tests de l'écran demandent `textual`, sinon ils sont sautés).
