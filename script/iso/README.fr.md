
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
une partition). **Tout le contenu de la clé est effacé.** Le menu
`Clé USB amorçable` du TODO fait de même après trois confirmations, et peut
d'abord ajouter un profil machine et un paquet hors ligne (voir « Écrire
une clé avec un paquet »).

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
`26` archinstall, `27` greffon, `28` installation hors ligne refusée,
`29` le système installé approuve encore l'autorité du paquet hors ligne,
`130` interrompu.

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
                payload », valide un an à partir d'une semaine avant
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

## Fichiers

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