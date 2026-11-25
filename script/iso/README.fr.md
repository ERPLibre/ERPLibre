
# ISO ERPLibre Arch Linux (x86_64)

`archlinux/build_iso.py` construit une ISO Arch Linux personnalisée avec
[archiso](https://wiki.archlinux.org/title/Archiso), à partir de son profil
`releng`. L'image démarre en BIOS comme en UEFI, s'écrit telle quelle sur une
clé USB (image hybride) et ouvre, sur la première console, un installateur
qui pose **Arch Linux + GNOME (gdm) + ERPLibre**, avec un profil ERPLibre
choisi pendant l'installation.

La machine cible doit avoir accès au réseau : les paquets et le dépôt
ERPLibre sont téléchargés pendant l'installation.

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

```bash
./script/iso/archlinux/build_iso.py --dry-run          # plan only
./script/iso/archlinux/build_iso.py                    # container, master
./script/iso/archlinux/build_iso.py --refresh-image --branch develop
sudo pacman -S --needed archiso                        # --builder host only
./script/iso/archlinux/build_iso.py --builder host --keep-work
```

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

## Écriture sur une clé USB

L'ISO est une image hybride : la copier sur le périphérique entier (pas sur
une partition). **Tout le contenu de la clé est effacé.**

```bash
sha256sum -c erplibre-archlinux-*-x86_64.iso.sha256
sudo dd if=erplibre-archlinux-<date>-x86_64.iso of=/dev/sdX bs=4M \
    conv=fsync oflag=direct status=progress
```

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

## Fichiers

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