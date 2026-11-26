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
**Everything on the key is erased.** The TODO menu `Bootable USB key` does
the same after three confirmations, and can add a machine profile and an
offline payload first (see « Writing a key with a payload »).

<!-- [fr] -->
## Écriture sur une clé USB

L'ISO est une image hybride : la copier sur le périphérique entier (pas sur
une partition). **Tout le contenu de la clé est effacé.** Le menu
`Clé USB amorçable` du TODO fait de même après trois confirmations, et peut
d'abord ajouter un profil machine et un paquet hors ligne (voir « Écrire
une clé avec un paquet »).

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
archinstall, `27` plugin, `28` offline install refused, `29` the
installed system still trusts the offline payload authority, `130`
interrupted.

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
`26` archinstall, `27` greffon, `28` installation hors ligne refusée,
`29` le système installé approuve encore l'autorité du paquet hors ligne,
`130` interrompu.

<!-- [en] -->
## Offline installation (payload on the key)

A key can carry an **offline payload**: a third partition, ext4,
`LABEL=ERPLIBRE_DATA`, added to the ISO by `xorriso -append_partition 3`
when the key is written (never by editing the key after `dd`). It holds one
payload for one ERPLibre profile:

```
manifest.json   schema, ERPLibre profile, git source (url, branch, commit),
                creation date, archinstall version, Arch snapshot date,
                sizes, sha256 of the small parts
repo/           pacman repository: <repo>/os/x86_64/<repo>.db + packages
store/          store of the Go caching proxy (script/qemu_cache), git
                mirrors under store/git/
bin/            the proxy, built static (CGO_ENABLED=0)
ca/             a certificate authority of this payload only (named
                « ERPLibre offline payload », valid two years from a week
                before its creation)
```

When a valid payload is found, the screen offers its profile by default,
labelled « offline install (payload <profile>, <date>) »; choosing it needs
no network. Another profile stays possible online, network required.

In automatic mode (`erplibre.answers`), the answers' `"offline"` alone
decides: `true` waits for neither the network nor `pacman-init`, and a
missing or unreadable payload is refused at once (code `28`); `false`
waits for both, even when the key carries a payload.

Before anything is erased, the core checks that the payload exists, is of
the chosen profile, that the profile command of this ISO is the one the
payload recorded (`erplibre.profile_command_sha256`; a payload without it
only gets a warning), and that its repository serves every package the
archinstall configuration asks for (exit code `28` otherwise). It then
starts `erplibre-offline start --profile <key>`:

- the clock is moved forward to the payload creation date when it is
  behind (a hardware clock kept in local time): the authority and the
  snapshot signatures would otherwise be « not yet valid »;

- the pacman keyring is initialised: without network, releng's
  `pacman-init` waits forever for a synchronised clock, so the wait is
  lifted (as `archinstall --skip-ntp` does for itself);
- the partition is mounted read-only (`ro,noload,nodev,nosuid,noexec`:
  `noload` keeps even a pending ext4 journal from being replayed);
- the proxy and the authority are copied to `/run/erplibre-offline`, their
  sha256 checked, and the proxy runs `--hors-ligne` on 127.0.0.1 under an
  unprivileged UID: it serves the store, and the local pacman repository
  for **every** Arch mirror URL, never contacts upstream, never writes;
- dnsmasq answers 198.18.0.1 to every name, systemd-resolved asks only it;
  that address sits on a dummy interface with a low-priority default route,
  without which `connect()` fails before the nft rule and systemd-resolved
  answers « Network is down »;
- nft redirects TCP 80/443 output of every process but the proxy to it
  (IPv6 to 80/443 is rejected so that clients fall back to IPv4);
- the live trusts the authority (anchor + `trust extract-compat`);
- the live mirrorlist gets a server if it has none: pacstrap copies it into
  the target, which keeps a real mirror;
- a self-test fetches `core.db` through the whole path;
- the live keyring is updated from the payload repository when the
  snapshot's `archlinux-keyring` is newer (`pacman -Sy`, `pacman -Qu`,
  `pacman -S`, signature checked by the current keyring): it replaces the
  WKD sync that `--skip-wkd` skips, so that a packager key added or
  extended after the ISO was built refuses before the erase, not after.

archinstall runs with `--offline --skip-ntp --skip-wkd`. The archinstall
chroot shares the live network, so the ERPLibre stage reaches the proxy as
well; inside the target it trusts the authority (anchor, `SSL_CERT_FILE`,
`REQUESTS_CA_BUNDLE`, `PIP_CERT`, `UV_NATIVE_TLS`, `NODE_EXTRA_CA_CERTS`, a
global `npmrc` for `sudo npm -g`) and removes all of it at the end. The core
then checks the target (`erplibre-offline clean-target`): it always
regenerates the target bundles (`trust extract-compat` in the chroot),
then searches them for the authority itself, not only its anchor, since
a removed anchor whose extract failed (full disk, killed stage) leaves it
trusted. If the authority is still there the install fails with code `29`.
It then stops the service, which undoes each step in reverse order; any
exception during `start`, Ctrl-C included, undoes it as well. The installed system is
normal: regular mirrorlist, no proxy authority, no proxy service.

The payload is built on the host by `archlinux/offline_payload.py`
(`build-proxy`, `manifest`, `image`); the proxy is compiled there with the
Go toolchain of the repository, because its store format belongs to the
version that filled it. The repository must carry each package's `.sig`:
pacman downloads it, the databases no longer embed signatures. The image
makes every file readable (the proxy runs under its own account), except
the authority's key.

### Building a payload

```bash
./script/iso/archlinux/offline_payload.py build --profile gnome \
    --iso ~/.erplibre/iso/erplibre-archlinux-<date>-x86_64.iso --dry-run
./script/iso/archlinux/offline_payload.py build --profile odoo18 \
    --iso <iso> --seed-git-mirrors /var/cache/erplibre_go_qemu_cache/git
```

`build` makes a **reference install** of the profile in QEMU (KVM, no
root): the static proxy runs on the host in record mode, on 127.0.0.1 and
two free ports, with an empty store; the VM boots the ISO as a USB key by
its kernel (answers in `erplibre.answers`, generic machine profile, UEFI
when OVMF is present) with a second key `LABEL=ERPLIBRE_DATA` that holds
only a **record manifest** (`"mode": "record"`, the proxy address and
ports, the authority's certificate). The installer then takes its offline
path, except that nft sends 80/443 to the host proxy through the QEMU
user-network gateway (10.0.2.2) and the live keeps its network and DNS:
the reference install fetches exactly what the offline install will ask.
Running the proxy on the host rather than in the live writes the store
straight into the build directory (nothing to extract from a VM disk) and
needs no root. It runs with `--sans-tunnel`: reached through the QEMU
gateway, without a kernel redirect on the host, it has no original
destination to tunnel to, so it always decrypts. `--seed-git-mirrors` first copies the profile's bare git
mirrors from an existing store (reflink on btrfs/XFS, read only on the
source); the install still goes through the proxy, which updates them.

The packages a machine profile can ask for but the VM did not (kernels,
both microcodes, open GPU drivers, power, shells, AppArmor, LUKS/LVM,
GRUB, sound firmware) are then fetched through the proxy from the host,
their closure computed by `pacman -Sp` on the recorded databases.

`assemble <build dir>` (also run by `build`) turns the store into the
payload: pacman files become `repo/` — the recorded official database is
kept when it names a present file for every recorded package, otherwise
the repository is rebuilt by `repo-add` on the newest recorded version
(unsigned database, accepted by Arch's `SigLevel = Required
DatabaseOptional`; packages keep their `.sig`); the rest of the store is
kept (hard links), and only the git mirrors the access log shows served.
Then `manifest.json`, the ext4 image and its `.sha256`, and `report.json`
(sizes, times, packages the pre-erase check would miss: must be empty),
all under `~/.erplibre/iso/offline/<profile>-<stamp>/`.

### Writing a key with a payload

In the TODO, `System › Bootable USB key › Write an ISO to a USB key`: after
the machine profile, an ERPLibre ISO asks « Offline installation »:

- `[0]` no: the key installs online, network required;
- one line per payload found under `~/.erplibre/iso/offline/`: profile,
  date, image size and the advised key size. A payload is listed with
  `✗` and cannot be chosen when its `.sha256` is missing, its manifest
  (read from the image by `debugfs`, without root) is missing or refused by
  the live's own check, or `report.json` says a required package is
  missing or unsigned;
- a last entry runs the factory (`offline_payload.py build`) for a chosen
  ERPLibre profile, after showing its duration, the free space it needs
  (refused below it) and the command; the git mirrors of the host cache
  are seeded when present. The list is read again afterwards.

Choosing a payload warns when nothing says which ISO recorded it, when it
was recorded with another ISO (only an ISO with the offline mode uses the
partition; an older one ignores it and installs online), when the ISO's
archinstall differs from the payload's, or when no plugged-in key is large
enough; each warning asks before keeping the payload.

The payload then goes into a derived ISO, with the machine profile if one
was chosen, under `~/.erplibre/iso/derived/<base>-<profile|none>-<payload>.iso`
(0700 folder, 0600 file: the payload holds its authority's key):

```bash
xorriso -indev <base.iso> -outdev <derived.iso> \
    -boot_image any replay -boot_image any gpt_disk_guid=volume_date_uuid \
    -volume_date uuid <date of the base> [-map <profile.json> /erplibre/machine.json] \
    -append_partition 3 0x83 <payload.img> -commit
```

Before xorriso, the free space is checked (base + image; outdated derived
ISOs are removed first if that is enough), and the image's sha256 is
checked against its `.sha256`. After it, the derived ISO is checked with
`sfdisk -J`, `xorriso -report_el_torito` and `blkid`: BIOS and UEFI El
Torito images, EFI partition, same UUID as the base (archiso finds its
medium by it), partition 3 of type Linux at least as large as the image;
otherwise it is removed. The key is then written as usual (`dd`, `cmp`): a
key smaller than the derived ISO is refused, with the advised key size —
an Odoo 18 payload (about 26 GB) needs a key of 32 GB or more. Writing and
reading back such an image takes tens of minutes on a slow key.

On the live, archiso mounts partition 1 (ISO 9660) of the key, so
partition 3 stays free for `erplibre-offline`, which finds it by its label.
`Detect USB keys and show their information` shows when a key carries a payload, with its profile and
date when the device is readable without sudo; `Supported ISO list` lists
the payloads of `~/.erplibre/iso/offline/`.

<!-- [fr] -->
## Installation hors ligne (paquet sur la clé)

Une clé peut porter un **paquet hors ligne** : une troisième partition,
ext4, `LABEL=ERPLIBRE_DATA`, ajoutée à l'ISO par `xorriso
-append_partition 3` à l'écriture de la clé (jamais en modifiant la clé
après `dd`). Elle tient un paquet pour un profil ERPLibre :

```
manifest.json   schéma, profil ERPLibre, source git (url, branche, commit),
                date de création, version d'archinstall, date de
                l'instantané Arch, tailles, sha256 des petites pièces
repo/           dépôt pacman : <dépôt>/os/x86_64/<dépôt>.db + paquets
store/          magasin du mandataire Go (script/qemu_cache), miroirs git
                sous store/git/
bin/            le mandataire, compilé statique (CGO_ENABLED=0)
ca/             une autorité propre à ce paquet (nommée « ERPLibre offline
                payload », valide deux ans à partir d'une semaine avant
                sa création)
```

Quand un paquet valide est trouvé, l'écran propose son profil par défaut,
avec la mention « installation hors ligne (paquet <profil>, <date>) » ; le
choisir ne demande aucun réseau. Un autre profil reste possible en ligne,
réseau requis.

En mode automatique (`erplibre.answers`), seul le `"offline"` des réponses
décide : `true` n'attend ni le réseau ni `pacman-init`, et un paquet absent
ou illisible est refusé aussitôt (code `28`) ; `false` attend les deux,
même si la clé porte un paquet.

Avant tout effacement, le cœur vérifie que le paquet existe, qu'il est du
profil choisi, que la commande du profil sur cette ISO est celle que le
paquet a enregistrée (`erplibre.profile_command_sha256` ; un paquet qui ne
la porte pas n'en reçoit qu'une mise en garde) et que son dépôt sert chaque
paquet que la configuration archinstall demande (code de sortie `28`
sinon). Il lance ensuite `erplibre-offline start --profile <clé>` :

- l'horloge est avancée à la date de création du paquet si elle est en
  retard (horloge matérielle tenue à l'heure locale) : l'autorité et les
  signatures de l'instantané seraient sinon « pas encore valides » ;

- le trousseau pacman est initialisé : sans réseau, le `pacman-init` de
  releng attend sans fin une heure synchronisée ; l'attente est donc levée
  (comme `archinstall --skip-ntp` le fait pour lui-même) ;
- la partition est montée en lecture seule (`ro,noload,nodev,nosuid,noexec`
  : `noload` empêche même le rejeu d'un journal ext4 en attente) ;
- le mandataire et l'autorité sont copiés dans `/run/erplibre-offline`,
  sha256 vérifié, et le mandataire tourne `--hors-ligne` sur 127.0.0.1 sous
  un UID sans privilège : il sert le magasin, et le dépôt pacman local pour
  **toute** URL de miroir Arch, sans jamais joindre l'amont ni écrire ;
- dnsmasq répond 198.18.0.1 à tout nom, systemd-resolved n'interroge que
  lui ; l'adresse vit sur une interface factice qui porte une route par
  défaut de faible priorité, sans quoi `connect()` échoue avant la règle
  nft et systemd-resolved répond « Network is down » ;
- nft détourne la sortie TCP 80/443 de tout processus, sauf le mandataire,
  vers lui (l'IPv6 vers 80/443 est refusée pour que les clients retombent
  sur l'IPv4) ;
- le live approuve l'autorité (ancre + `trust extract-compat`) ;
- la liste de miroirs du live reçoit un serveur si elle n'en a aucun :
  pacstrap la recopie dans la cible, qui garde un vrai miroir ;
- un essai demande `core.db` au travers de tout le chemin ;
- le trousseau du live est mis à jour depuis le dépôt du paquet quand
  l'`archlinux-keyring` de l'instantané est plus récent (`pacman -Sy`,
  `pacman -Qu`, `pacman -S`, signature vérifiée par le trousseau actuel) :
  il remplace la synchronisation WKD que `--skip-wkd` saute, pour qu'une
  clé d'empaqueteur ajoutée ou prolongée après la construction de l'ISO
  refuse avant l'effacement, et non après.

archinstall tourne avec `--offline --skip-ntp --skip-wkd`. Le chroot
d'archinstall partage le réseau du live : l'étape ERPLibre joint donc aussi
le mandataire ; dans la cible, elle fait approuver l'autorité (ancre,
`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `PIP_CERT`, `UV_NATIVE_TLS`,
`NODE_EXTRA_CA_CERTS`, un `npmrc` global pour `sudo npm -g`) et retire tout
à la fin. Le cœur vérifie ensuite la cible (`erplibre-offline
clean-target`) : il régénère toujours ses faisceaux (`trust extract-compat`
dans le chroot), puis y cherche l'autorité elle-même et pas seulement son
ancre, car une ancre effacée dont l'extraction a échoué (disque plein,
étape tuée) la laisse approuvée. Si elle y est encore, l'installation
échoue avec le code `29`. Il arrête ensuite le service, qui défait chaque
geste en ordre inverse ; toute exception pendant `start`, Ctrl-C compris,
le défait aussi. Le système installé est normal : liste de miroirs ordinaire,
aucune autorité du mandataire, aucun service du mandataire.

Le paquet se fabrique sur l'hôte par `archlinux/offline_payload.py`
(`build-proxy`, `manifest`, `image`) ; le mandataire y est compilé avec la
chaîne Go du dépôt, parce que le format de son magasin appartient à la
version qui l'a rempli. Le dépôt doit porter le `.sig` de chaque paquet :
pacman le télécharge, les bases n'embarquent plus les signatures. L'image
rend chaque fichier lisible (le mandataire tourne sous son propre compte),
sauf la clé de l'autorité.

### Fabriquer un paquet

```bash
./script/iso/archlinux/offline_payload.py build --profile gnome \
    --iso ~/.erplibre/iso/erplibre-archlinux-<date>-x86_64.iso --dry-run
./script/iso/archlinux/offline_payload.py build --profile odoo18 \
    --iso <iso> --seed-git-mirrors /var/cache/erplibre_go_qemu_cache/git
```

`build` fait une **installation de référence** du profil en QEMU (KVM,
sans root) : le mandataire statique tourne sur l'hôte en mode
enregistrement, sur 127.0.0.1 et deux ports libres, magasin vide ; la VM
démarre l'ISO en clé USB par son noyau (réponses dans `erplibre.answers`,
profil machine generic, UEFI quand OVMF est présent) avec une 2e clé
`LABEL=ERPLIBRE_DATA` qui ne porte qu'un **manifeste d'enregistrement**
(`"mode": "record"`, l'adresse et les ports du mandataire, le certificat de
l'autorité). L'installateur suit alors son chemin hors ligne, sauf que nft
envoie 80/443 au mandataire de l'hôte par la passerelle du réseau « user »
de QEMU (10.0.2.2) et que le live garde son réseau et son DNS :
l'installation de référence tire exactement ce que l'installation hors
ligne demandera. Le mandataire tourne sur l'hôte plutôt que dans le live :
le magasin s'écrit directement dans le répertoire de fabrication (rien à
extraire d'un disque de VM), sans root. Il tourne avec `--sans-tunnel` : joint par la
passerelle de QEMU, sans détournement noyau sur l'hôte, il n'a aucune
destination d'origine vers laquelle ouvrir un tunnel, et déchiffre donc
toujours. `--seed-git-mirrors` copie d'abord
les miroirs git nus du profil depuis un magasin existant (reflink sur
btrfs/XFS, la source n'est que lue) ; l'installation passe quand même par
le mandataire, qui les met à jour.

Les paquets qu'un profil machine peut demander mais que la VM n'a pas tirés
(noyaux, deux microcodes, pilotes graphiques libres, alimentation, shells,
AppArmor, LUKS/LVM, GRUB, micrologiciels son) sont ensuite tirés au travers
du mandataire depuis l'hôte, leur fermeture calculée par `pacman -Sp` sur
les bases enregistrées.

`assemble <répertoire>` (lancé aussi par `build`) fait du magasin le
paquet : les fichiers pacman deviennent `repo/` — la base officielle
enregistrée est gardée si elle désigne un fichier présent pour chaque
paquet enregistré, sinon le dépôt est reconstruit par `repo-add` sur la
version enregistrée la plus récente (base non signée, que le `SigLevel =
Required DatabaseOptional` d'Arch accepte ; les paquets gardent leur
`.sig`) ; le reste du magasin est gardé (liens physiques), et seuls les
miroirs git que le journal d'accès montre servis. Puis `manifest.json`,
l'image ext4 et son `.sha256`, et `report.json` (tailles, durées, paquets
que le contrôle d'avant l'effacement ne trouverait pas : doit être vide),
le tout sous `~/.erplibre/iso/offline/<profil>-<horodatage>/`.

### Écrire une clé avec un paquet

Dans le TODO, `Système › Clé USB amorçable › Écrire un ISO sur une clé
USB` : après le profil machine, une ISO ERPLibre demande « Installation
hors ligne » :

- `[0]` non : la clé installe en ligne, réseau requis ;
- une ligne par paquet trouvé sous `~/.erplibre/iso/offline/` : profil,
  date, taille de l'image et taille de clé conseillée. Un paquet est
  listé avec `✗` et ne peut pas être choisi quand son `.sha256` manque,
  que son manifeste (lu dans l'image par `debugfs`, sans root) manque ou
  est refusé par le contrôle même du live, ou que `report.json` signale un
  paquet requis absent ou non signé ;
- une dernière entrée lance la fabrique (`offline_payload.py build`) pour
  un profil ERPLibre choisi, après avoir montré sa durée, la place libre
  qu'elle demande (refus en dessous) et la commande ; les miroirs git du
  cache de l'hôte sont amorcés s'ils sont là. La liste est relue ensuite.

Choisir un paquet met en garde quand rien ne dit quelle ISO l'a enregistré,
quand il l'a été avec une autre ISO (seule une ISO qui a le mode hors ligne
se sert de la partition ; une plus ancienne l'ignore et installe en ligne),
quand l'archinstall de l'ISO diffère de celui du paquet, ou quand aucune
clé branchée n'est assez grande ; chaque mise en garde demande avant de
garder le paquet.

Le paquet part ensuite dans une ISO dérivée, avec le profil machine s'il y
en a un, sous
`~/.erplibre/iso/derived/<base>-<profil|none>-<paquet>.iso` (dossier en
0700, fichier en 0600 : le paquet porte la clé de son autorité) :

```bash
xorriso -indev <base.iso> -outdev <dérivée.iso> \
    -boot_image any replay -boot_image any gpt_disk_guid=volume_date_uuid \
    -volume_date uuid <date de la base> [-map <profil.json> /erplibre/machine.json] \
    -append_partition 3 0x83 <paquet.img> -commit
```

Avant xorriso, la place libre est vérifiée (base + image ; les ISO
dérivées périmées sont retirées d'abord si cela suffit), et la somme
sha256 de l'image comparée à son `.sha256`. Après lui, l'ISO dérivée est
contrôlée par `sfdisk -J`, `xorriso -report_el_torito` et `blkid` : images
El Torito BIOS et UEFI, partition EFI, même UUID que la base (archiso
retrouve son support par lui), partition 3 de type Linux au moins aussi
grande que l'image ; sinon elle est retirée. La clé s'écrit ensuite comme
d'habitude (`dd`, `cmp`) : une clé plus petite que l'ISO dérivée est
refusée, avec la taille de clé conseillée — un paquet Odoo 18 (environ
26 Go) demande une clé de 32 Go ou plus. Écrire puis relire une telle
image prend des dizaines de minutes sur une clé lente.

Sur le live, archiso monte la partition 1 (ISO 9660) de la clé : la
partition 3 reste libre pour `erplibre-offline`, qui la trouve par son
étiquette. `Détecter les clés USB et afficher leurs informations`
dit quand une clé porte un paquet, avec
son profil et sa date si le périphérique est lisible sans sudo ; `Liste des
ISO prises en charge` liste les paquets de `~/.erplibre/iso/offline/`.

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
├── offline_payload.py                   offline payload: reference install, image
└── profile/airootfs/usr/local/
    ├── bin/erplibre-install             tty1 entry: screen or automatic
    ├── bin/erplibre-installer-ui        installer screen (Textual / text)
    ├── bin/erplibre-install-config      archinstall user_configuration.json
    ├── bin/erplibre-installer           profile-driven installer core
    ├── bin/erplibre-todo                TODO embedded in the key
    ├── bin/erplibre-offline             offline payload service
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
        ├── erplibre_offline.py          offline: probe, start, stop, checks
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
`test/test_iso_installer_{disk,plugin,core,ui}.py` (no archinstall
needed; the screen tests need `textual`, else they are skipped), and
`test/test_iso_offline.py` (offline service, stage, payload tool).

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
`test/test_iso_installer_{disk,plugin,core,ui}.py` (sans archinstall ;
les tests de l'écran demandent `textual`, sinon ils sont sautés), et
`test/test_iso_offline.py` (service hors ligne, étape, fabrique du paquet).
