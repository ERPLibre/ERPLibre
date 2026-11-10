<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# ERPLibre - Docker

Those images are prepared to permit better portability and reproducibility of ERPLibre release.

Due the growing code of ERPLibre, it could also simplify development.

NOTE: Those Dockerfiles themselves are in heavy development for now. Incompatibilities between releases are normal until the interface is stabilized.

## Pre-requirements

- Basic knowledge with Docker, Linux and bash
- Latest Docker version

## Files representations

- Dockerfile.base: This Dockerfile represents the base Docker image layer reused by other child layers.
- Dockerfile.dev: This Dockerfile is specialized in development.
- Dockerfile.prod{pkg,src}: Dockerfile.prod.\* is a Docker image specialized for production systems. Dockerfile.prod.pkg reuses official Debian files from Odoo.com. Dockerfile.prod.src fetches the Odoo source code as the ERPLibre runtime.

## Getting started

Be sure to start daemon docker

<!-- [fr] -->
# ERPLibre - Docker

Ces images sont préparées pour permettre une meilleure portabilité et reproductibilité des versions d'ERPLibre.

En raison du code croissant d'ERPLibre, cela pourrait aussi simplifier le développement.

NOTE : Ces Dockerfiles sont en développement actif pour le moment. Les incompatibilités entre les versions sont normales jusqu'à ce que l'interface soit stabilisée.

## Prérequis

- Connaissances de base avec Docker, Linux et bash
- Dernière version de Docker

## Représentation des fichiers

- Dockerfile.base : Ce Dockerfile représente la couche d'image Docker de base réutilisée par les autres couches enfants.
- Dockerfile.dev : Ce Dockerfile est spécialisé pour le développement.
- Dockerfile.prod{pkg,src} : Dockerfile.prod.\* est une image Docker spécialisée pour les systèmes de production. Dockerfile.prod.pkg réutilise les fichiers Debian officiels d'Odoo.com. Dockerfile.prod.src récupère le code source d'Odoo comme environnement d'exécution ERPLibre.

## Démarrage

Assurez-vous de démarrer le démon docker

<!-- [common] -->
```bash
systemctl start docker
```

<!-- [en] -->
### Building the docker images

<!-- [fr] -->
### Construire les images docker

<!-- [common] -->
```bash
cd docker
docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
docker build -f Dockerfile.prod.pkg -t technolibre/erplibre:12.0-pkg .
```

<!-- [en] -->

`.venv.erplibre` is built on the image's own Python, Odoo's, without mise or
pyenv. The build stops when that Python cannot parse `script/`, which happens
with a deprecated Odoo version.

### Debian base and architectures

`script/docker/docker_build.sh --odoo_<N>` builds Odoo 16 to 18 on Debian
trixie and Odoo 12 to 15 on bookworm, which is the last Debian with a Python
3.7 or 3.8 image. Each image comes for amd64, arm64 and s390x:

- `--platform=amd64,arm64,s390x` names the architectures, the host's by
  default. A foreign one runs under QEMU emulation, which
  `sudo bash script/install/install_container.sh --multiarch` installs with
  buildx; the script refuses an architecture that is not emulated or that the
  Python image does not publish, and `--print-platforms` lists the ones it
  publishes;
- the host's architecture keeps the tag without suffix, the one
  `docker-compose.yml` runs, and the others take `-<arch>`; `--push` pushes
  every architecture with its suffix, then turns the tag without suffix into
  a manifest that joins them, after a `docker login`;
- **TODO › Execute › Docker / Podman › Build an image for an Odoo version**
  asks for the version, the architectures and the output, and offers the
  emulation when it is missing.

wkhtmltopdf with patched Qt, the only one that prints headers and footers in
Odoo's PDF, exists for amd64 and arm64 only; Debian trixie no longer packages
wkhtmltopdf at all. An s390x image prints its reports as HTML. Its PostgreSQL
client is Debian's, 17 on trixie, the PostgreSQL repository publishing no
s390x: its `pg_dump` refuses a PostgreSQL 18 server, so a backup from Odoo
needs a server of version 17 at most.

### Frozen code

The image clones each repository on the commit of its `freeze-revision`, not
on the head of its branch: two builds of the same ERPLibre commit hold the
same code. The freezes of the active Odoo version's manifests apply, and
those of the common fragments that `conf/git_manifest*.csv` lists, such as
`image_db` and the tools; a project without a `freeze-revision` stops the
build before anything is synchronised, and is named. Move a freeze forward,
then commit and push it, to bring newer code into an image.
`docker_build.sh --branches` builds a development image on the branches.

The image holds the extra modules too, CybroOdoo and the rest of the
version's extra manifest, as the production install of TODO with extra
modules does. `docker_build.sh --without_extra`, or the standard install in
the build menu of TODO, leaves them out.

### Running ERPLibre using Docker-Compose

Go at the root of this git project.

<!-- [fr] -->

`.venv.erplibre` est bâti sur le Python de l'image, celui d'Odoo, sans mise ni
pyenv. La construction s'arrête quand ce Python ne sait pas lire `script/`, ce
qui arrive avec une version d'Odoo dépréciée.

### Base Debian et architectures

`script/docker/docker_build.sh --odoo_<N>` construit Odoo 16 à 18 sur Debian
trixie et Odoo 12 à 15 sur bookworm, la dernière Debian qui ait une image
Python 3.7 ou 3.8. Chaque image existe pour amd64, arm64 et s390x :

- `--platform=amd64,arm64,s390x` nomme les architectures, celle de l'hôte par
  défaut. Une architecture étrangère tourne sous émulation QEMU, que
  `sudo bash script/install/install_container.sh --multiarch` installe avec
  buildx ; le script refuse une architecture non émulée ou que l'image Python
  ne publie pas, et `--print-platforms` liste celles qu'elle publie ;
- l'architecture de l'hôte garde l'étiquette sans suffixe, celle que lance
  `docker-compose.yml`, et les autres prennent `-<arch>` ; `--push` pousse
  chaque architecture avec son suffixe, puis fait de l'étiquette sans suffixe
  un manifeste qui les réunit, après un `docker login` ;
- **TODO › Exécution › Docker / Podman › Construire l'image d'une version
  d'Odoo** demande la version, les architectures et la sortie, et propose
  l'émulation quand elle manque.

wkhtmltopdf au Qt patché, le seul qui imprime en-tête et pied de page dans les
PDF d'Odoo, n'existe que pour amd64 et arm64 ; Debian trixie n'empaquette plus
du tout wkhtmltopdf. Une image s390x imprime ses rapports en HTML. Son client
PostgreSQL est celui de Debian, 17 sur trixie, le dépôt de PostgreSQL ne
publiant pas s390x : son `pg_dump` refuse un serveur PostgreSQL 18, si bien
qu'une sauvegarde depuis Odoo demande un serveur en version 17 au plus.

### Code gelé

L'image clone chaque dépôt sur le commit de son `freeze-revision`, et non sur
la tête de sa branche : deux constructions du même commit d'ERPLibre portent
le même code. Les gels des manifestes de la version d'Odoo active
s'appliquent, et ceux des fragments communs que liste `conf/git_manifest*.csv`,
comme `image_db` et les outils ; un projet sans `freeze-revision` arrête la
construction avant toute synchronisation, et il est nommé. Avancer un gel,
puis le commiter et le pousser, fait entrer un code plus récent dans une
image. `docker_build.sh --branches` construit une image de développement sur
les branches.

L'image porte aussi les modules extra, CybroOdoo et le reste du manifeste
extra de la version, comme l'installation de production du TODO avec modules
extra. `docker_build.sh --without_extra`, ou l'installation standard dans le
menu de construction du TODO, les laisse de côté.

### Exécuter ERPLibre avec Docker-Compose

Allez à la racine de ce projet git.

<!-- [common] -->
```bash
cd ERPLibre
docker compose -f docker-compose.yml up -d
```

<!-- [en] -->
### Exposure

The compose files publish Odoo on the host's loopback only, `127.0.0.1:8069`
and `127.0.0.1:8072`: a browser on the host reaches it, the network does not.
That holds with rootless Docker, and with a Docker daemon run by root from
release 28.0 on. An older daemon run by root lets a host of the same local
network route its packets straight to the container and reach Odoo despite
the loopback binding: upgrade it, or drop that forwarding in the
`DOCKER-USER` chain of iptables. Port 8071 is not published, as no Odoo from
12.0 on serves XML-RPC over TLS.
The Selenium compose publishes its grid's router on `127.0.0.1:8075` only,
behind a user and a password, and keeps the grid on a network ERPLibre is not
on, see `script/selenium/install.md`.

To serve the network, put a reverse proxy on the host in front of
`127.0.0.1:8069` and `8072`, with Odoo in `--proxy-mode`, or change the bind
address in `ports`. With a Docker daemon run by root, a published port
bypasses the host firewall: Docker inserts its own iptables rules ahead of
those of ufw or firewalld, so a port bound on `0.0.0.0` is open to the whole
network whatever the firewall says.

Before any exposure, set two options of `/etc/odoo/odoo.conf`:

- `admin_passwd`, a long random value. Unset, Odoo takes `admin` as its master
  password, and whoever knows it can back up, restore, duplicate or drop
  every database from `/web/database/manager`;
- `list_db = False`, which turns off that manager and the listing of the
  databases, master password or not.

<!-- [fr] -->
### Exposition

Les fichiers compose ne publient Odoo que sur la boucle locale de l'hôte,
`127.0.0.1:8069` et `127.0.0.1:8072` : un navigateur sur l'hôte l'atteint, le
réseau non. C'est vrai avec Docker sans root, et avec un démon Docker lancé
par root à partir de la version 28.0. Un démon plus ancien lancé par root
laisse un hôte du même réseau local router ses paquets directement vers le
conteneur et atteindre Odoo malgré la liaison sur la boucle locale :
mettez-le à jour, ou rejetez ce transfert dans la chaîne `DOCKER-USER`
d'iptables. Le port 8071 n'est pas publié, aucun Odoo depuis la 12.0 ne servant
XML-RPC sur TLS. Le compose Selenium ne publie le routeur de sa grille que sur
`127.0.0.1:8075`, derrière un utilisateur et un mot de passe, et tient la
grille sur un réseau où ERPLibre n'est pas, voir
`script/selenium/install.fr.md`.

Pour servir le réseau, placez un proxy inverse sur l'hôte devant
`127.0.0.1:8069` et `8072`, avec Odoo en `--proxy-mode`, ou changez l'adresse
d'écoute dans `ports`. Avec un démon Docker lancé par root, un port publié
contourne le pare-feu de l'hôte : Docker insère ses propres règles iptables
avant celles d'ufw ou de firewalld, si bien qu'un port lié sur `0.0.0.0` est
ouvert à tout le réseau quoi qu'en dise le pare-feu.

Avant toute exposition, réglez deux options de `/etc/odoo/odoo.conf` :

- `admin_passwd`, une longue valeur aléatoire. Sans elle, Odoo prend `admin`
  pour mot de passe maître, et qui le connaît peut sauvegarder, restaurer,
  dupliquer ou supprimer toutes les bases depuis `/web/database/manager` ;
- `list_db = False`, qui coupe ce gestionnaire et la liste des bases, mot de
  passe maître ou non.

<!-- [en] -->
The file lives in the project's `erplibre_conf` volume, belongs to `odoo` and
outlives a recreated container. The image carries no text editor: the
commands below set both options as `odoo`, print the new master password once,
then restart Odoo; like them, `make docker_exec_erplibre_gen_config`
rewrites the file without its comments, and changes `addons_path` only.
`make docker_show_odoo_conf` shows the result.

<!-- [fr] -->
Le fichier vit dans le volume `erplibre_conf` du projet, appartient à `odoo`
et survit à un conteneur recréé. L'image n'a pas d'éditeur de texte : les
commandes ci-dessous règlent les deux options sous `odoo`, affichent une fois
le nouveau mot de passe maître, puis redémarrent Odoo ; comme elles,
`make docker_exec_erplibre_gen_config` réécrit le fichier sans ses
commentaires, et ne change que `addons_path`.
`make docker_show_odoo_conf` montre le résultat.

<!-- [common] -->
```bash
docker compose exec -T -u odoo ERPLibre python3 - <<'EOF'
import configparser, secrets
path = "/etc/odoo/odoo.conf"
conf = configparser.ConfigParser(interpolation=None)
conf.read(path)
conf["options"]["admin_passwd"] = secrets.token_urlsafe(32)
conf["options"]["list_db"] = "False"
with open(path, "w") as f:
    conf.write(f)
print("admin_passwd =", conf["options"]["admin_passwd"])
EOF
docker compose restart ERPLibre
```

<!-- [en] -->
### Extra Python packages for the addons

An addon, or an ERPLibre script, can need a Python package the image does not
carry. List them separated by spaces or newlines, with a version when it
matters; a constraint holds neither a space nor a quote. Each venv of the image
has its own list: `PIP_EXTRA_REQUIREMENTS_ODOO` for Odoo's venv, the one the
addons import, and `PIP_EXTRA_REQUIREMENTS_ERPLIBRE` for `.venv.erplibre`, the
one of the tools in `script/`:

<!-- [fr] -->
### Paquets Python supplémentaires pour les addons

Un addon, ou un script d'ERPLibre, peut demander un paquet Python que l'image
n'a pas. Listez-les séparés par des espaces ou des sauts de ligne, avec une
version quand elle compte ; une contrainte ne contient ni espace ni guillemet. Chaque
venv de l'image a sa liste : `PIP_EXTRA_REQUIREMENTS_ODOO` pour le venv d'Odoo,
celui qu'importent les addons, et `PIP_EXTRA_REQUIREMENTS_ERPLIBRE` pour
`.venv.erplibre`, celui des outils de `script/` :

<!-- [common] -->
```yaml
    environment:
      PIP_EXTRA_REQUIREMENTS_ODOO: "humanize pyotp==2.9.0 phonenumbers>=8.13,<9"
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: ""
```

<!-- [en] -->
At each start, `docker/entrypoint_pip_extra.sh` installs each list with the
pip of its venv, then runs Odoo as `odoo`: the container starts as root so
that each pip runs as the owner of its venv, `odoo`. A satisfied requirement
downloads nothing. A requirement pip cannot install stops the container before
Odoo, with pip's error in `docker compose logs`.

In an image built with `ERPLIBRE_CODE_OWNER=root`, the venvs belong to root
but `/ERPLibre`, which holds them, stays `odoo`'s: Odoo could swap a venv for
one of its own before root runs its pip. The entrypoint therefore refuses any
`PIP_EXTRA_REQUIREMENTS_*` list there and stops the container before Odoo;
such an image takes its packages at build time, in an image derived from it.

<!-- [fr] -->
À chaque démarrage, `docker/entrypoint_pip_extra.sh` installe chaque liste
avec le pip de son venv, puis lance Odoo sous `odoo` : le conteneur démarre en
root pour que chaque pip tourne sous le propriétaire de son venv, `odoo`. Une
exigence déjà satisfaite ne télécharge rien. Une exigence que pip ne peut pas
installer arrête le conteneur avant Odoo, avec l'erreur de pip dans
`docker compose logs`.

Dans une image construite avec `ERPLIBRE_CODE_OWNER=root`, les venvs
appartiennent à root, mais `/ERPLibre`, qui les contient, reste à `odoo` :
Odoo pourrait substituer un venv à lui avant que root n'y lance pip.
L'entrypoint y refuse donc toute liste `PIP_EXTRA_REQUIREMENTS_*` et arrête le
conteneur avant Odoo ; une telle image reçoit ses paquets à la construction,
dans une image qui en dérive.

<!-- [en] -->
Root keeps only the two capabilities setpriv needs (`cap_drop`, `cap_add`), and
`no-new-privileges` stops Odoo from ever regaining one. Since the container
starts as root, `docker exec` opens a root shell by default: a file it writes in
the filestore or in `/etc/odoo` belongs to root, and Odoo can no longer change
it. Pass the account:

<!-- [fr] -->
Root ne garde que les deux capacités dont setpriv a besoin (`cap_drop`,
`cap_add`), et `no-new-privileges` empêche Odoo d'en regagner une. Comme le
conteneur démarre en root, `docker exec` ouvre un shell root par défaut : un
fichier qu'il écrit dans le filestore ou dans `/etc/odoo` appartient à root, et
Odoo ne peut plus le modifier. Passez le compte :

<!-- [common] -->
```bash
docker compose exec -u odoo ERPLibre bash
```

<!-- [en] -->
`make docker_exec_erplibre`, that is `script/docker/docker_exec.sh`, and the
TODO menu entry "Enter the ERPLibre container" open a plain root shell: it
keeps only the `SETUID` and `SETGID` capabilities, whatever `cap_add` the
compose grants for apt, under `no-new-privileges`, so root there neither
reads nor writes what the file permissions refuse it, and apt installs
nothing. It starts in `/`, with a system-only `PATH` and no profile
nor bashrc, reading nothing that `odoo` can rewrite. A Debian package goes in
`APT_EXTRA_PACKAGES`, below; work in `/ERPLibre`, which `odoo` owns, goes
through the `docker compose exec -u odoo` above.

<!-- [fr] -->
`make docker_exec_erplibre`, soit `script/docker/docker_exec.sh`, et l'entrée
« Entrer dans le conteneur ERPLibre » du menu TODO ouvrent un simple shell
root : il ne garde que les capacités `SETUID` et `SETGID`, quel que soit le
`cap_add` que le compose accorde pour apt, sous `no-new-privileges`, si bien
que root n'y lit ni n'écrit ce que les permissions des fichiers lui refusent,
et qu'apt n'y installe rien. Il démarre dans `/`, avec un `PATH` réduit aux
répertoires système et sans profil ni bashrc, et ne lit rien que `odoo` puisse
réécrire. Un paquet Debian va dans `APT_EXTRA_PACKAGES`, ci-dessous ; le
travail dans `/ERPLibre`, qui appartient à `odoo`, passe par le
`docker compose exec -u odoo` ci-dessus.

<!-- [en] -->
### Extra system packages

A pip package can load a system library the image does not carry —
`python-magic` loads `libmagic`. `APT_EXTRA_PACKAGES` lists Debian packages,
one name per word, that `docker/entrypoint_pip_extra.sh` installs with apt, as
root, at each start, before the pip lists and before handing over to `odoo`.
Root receives names only, checked against Debian's naming rules, never a
command nor a file of the code, which Odoo can rewrite. A package already
installed, or provided by an installed one (`libmagic1` is provided by
`libmagic1t64` on trixie), is skipped without network, so a restart stays
offline; a recreated container installs it again.

apt needs four more capabilities than the compose grants by default. Without
`CHOWN`, `DAC_OVERRIDE` or `FOWNER`, apt fails, the last as soon as a package
ships a file another account owns; without `FSETID`, it succeeds, and a
setgid binary loses its bit with no error. The script checks the four before
apt and stops the container when one is missing. They serve root only:
`setpriv` drops them when it hands over to `odoo`, and `no-new-privileges`
keeps Odoo from regaining them.

<!-- [fr] -->
### Paquets système supplémentaires

Un paquet pip peut charger une bibliothèque système que l'image n'a pas —
`python-magic` charge `libmagic`. `APT_EXTRA_PACKAGES` liste des paquets
Debian, un nom par mot, que `docker/entrypoint_pip_extra.sh` installe avec
apt, en root, à chaque démarrage, avant les listes pip et avant de passer la
main à `odoo`. Root ne reçoit que des noms, vérifiés selon les règles de
nommage de Debian, jamais une commande ni un fichier du code, qu'Odoo peut
réécrire. Un paquet déjà installé, ou fourni par un paquet installé
(`libmagic1` l'est par `libmagic1t64` sous trixie), est sauté sans réseau : un
redémarrage reste hors ligne, et un conteneur recréé l'installe de nouveau.

apt demande quatre capacités de plus que celles du compose par défaut. Sans
`CHOWN`, `DAC_OVERRIDE` ou `FOWNER`, apt échoue, la dernière dès qu'un paquet
livre un fichier qui appartient à un autre compte ; sans `FSETID`, il réussit,
et un binaire setgid perd son bit sans erreur. Le script vérifie les quatre
avant apt et arrête le conteneur s'il en manque une. Elles ne servent qu'à
root : `setpriv` les retire en passant la main à `odoo`, et
`no-new-privileges` empêche Odoo de les regagner.

<!-- [common] -->
```yaml
    environment:
      APT_EXTRA_PACKAGES: "libmagic1"
    cap_add: [SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER, FSETID]
```

<!-- [en] -->
A large package, a browser for Selenium for instance, is better built into an
image derived from ERPLibre's: as a start-time install it is downloaded again
at each recreation.

<!-- [fr] -->
Un gros paquet, un navigateur pour Selenium par exemple, gagne à être
construit dans une image dérivée de celle d'ERPLibre : installé au démarrage,
il se télécharge de nouveau à chaque recréation.

<!-- [en] -->
### A command at each start

`INIT_CMD` holds a shell command that `docker/entrypoint.sh` runs in a bash
login shell at each start, once PostgreSQL answers and before Odoo, in
`/ERPLibre`, as the account that runs Odoo. A command that fails stops the
container before Odoo, with its error in `docker compose logs`; the log names
the step, never the command. A Python package belongs in the
`PIP_EXTRA_REQUIREMENTS_*` lists instead, whose pip runs as `odoo`, the owner
of the venvs (an image whose venvs belong to root refuses these lists), and a
Debian package in `APT_EXTRA_PACKAGES`, which apt installs as root: `INIT_CMD`
runs as `odoo`, which cannot run apt, nor pip in a venv the build gave to root.

<!-- [fr] -->
### Une commande à chaque démarrage

`INIT_CMD` porte une commande shell que `docker/entrypoint.sh` lance dans un
bash de connexion à chaque démarrage, une fois que PostgreSQL répond et avant
Odoo, dans `/ERPLibre`, sous le compte qui fait tourner Odoo. Une commande qui
échoue arrête le conteneur avant Odoo, avec son erreur dans `docker compose
logs` ; le journal nomme l'étape, jamais la commande. Un paquet Python va
plutôt dans les listes `PIP_EXTRA_REQUIREMENTS_*`, dont le pip tourne sous le
propriétaire des venvs, `odoo` (une image dont les venvs appartiennent à root
refuse ces listes), et un paquet Debian dans `APT_EXTRA_PACKAGES`, qu'apt
installe en root : `INIT_CMD` tourne sous `odoo`, qui ne peut lancer ni apt,
ni pip dans un venv que la construction a donné à root.

<!-- [common] -->
```yaml
    environment:
      INIT_CMD: "./script/my_startup.sh"
```

<!-- [en] -->
### The checkout's entrypoint

`docker-compose.yml` and the 18.0 compose files of `docker/` mount the
checkout's `docker/` read-only at `/opt/erplibre/docker` and start
`entrypoint_pip_extra.sh` from there. A directory rather than the single
file: the container sees the file that git replaces on a pull, where a
single-file mount keeps serving the replaced copy until the container
restarts. Two commented lines of `docker-compose.yml` and of
`docker/docker-compose_odoo_18.0.yml` run the checkout's `entrypoint.sh`, and
so `INIT_CMD`, on an image built before it: `ERPLIBRE_ENTRYPOINT`, and a
second read-only mount of `docker/` over the image's `/ERPLibre/docker`, a
copy of that directory where `entrypoint.sh` finds `odoo_rc_db.py` and
`wait-for-psql.py`.

With rootless Docker, `docker cp` fails with `remount-ro ... operation not
permitted` as soon as the container has a read-only bind mount whose source
lies on a filesystem mounted `nosuid`, `nodev` or `noexec`, such as a tmpfs
`/tmp`; a directory and a file fail alike. `script/docker/docker_copy_file.sh`
goes through `docker exec` instead, and so does `docker compose exec -T -u
odoo ERPLibre sh -c 'cat > DEST' < FILE`.

<!-- [fr] -->
### L'entrypoint du checkout

`docker-compose.yml` et les fichiers compose 18.0 de `docker/` montent le
`docker/` du checkout en lecture seule sur `/opt/erplibre/docker` et y
lancent `entrypoint_pip_extra.sh`. Un
répertoire plutôt que le fichier seul : le conteneur voit le fichier que git
remplace lors d'un tirage, là où un montage de fichier seul sert encore la
copie remplacée jusqu'au redémarrage du conteneur. Deux lignes commentées de
`docker-compose.yml` et de `docker/docker-compose_odoo_18.0.yml` lancent
l'`entrypoint.sh` du checkout, et donc `INIT_CMD`, sur une image construite
avant lui : `ERPLIBRE_ENTRYPOINT`, et un second montage en lecture seule de
`docker/` par-dessus le `/ERPLibre/docker` de l'image, une copie de ce
répertoire où `entrypoint.sh` trouve `odoo_rc_db.py` et `wait-for-psql.py`.

Avec Docker sans root, `docker cp` échoue sur `remount-ro ... operation not
permitted` dès que le conteneur a un montage lié en lecture seule dont la
source se trouve sur un système de fichiers monté `nosuid`, `nodev` ou
`noexec`, comme un `/tmp` en tmpfs ; un répertoire échoue comme un fichier.
`script/docker/docker_copy_file.sh` passe plutôt par `docker exec`, tout comme
`docker compose exec -T -u odoo ERPLibre sh -c 'cat > DEST' < FILE`.

<!-- [en] -->
### Pulling the code from Odoo

`erplibre_info_git_fetch` fetches and pulls the git clones from Odoo, which
asks two things of the container:

- the code and its git repositories belong to the account that runs Odoo. The
  image is built with `ERPLIBRE_CODE_OWNER=odoo`, the default; `root` builds an
  image Odoo cannot rewrite, and `script/git/repo_pull.py` refuses its clones,
  naming their owner. The images of ERPLibre 1.6.0 and earlier leave the clone
  to root. `script/update/docker_fix_erplibre_info_docker_erplibre_160.sh`
  updates the ERPLibre root of a running container and readies it for the
  snapshots of `erplibre_info_git`; it runs git as the owner of `/ERPLibre`,
  never as root, so on such an image it stops before git, at step 2 at the
  latest, and names the first path that owner cannot write. It supports an
  image whose code belongs to its owner, an account other than root, and its
  last message names what the pull still lacks;
- Odoo runs with a value of `--dev`:

<!-- [fr] -->
### Tirer le code depuis Odoo

`erplibre_info_git_fetch` fait le fetch et le tirage des clones git depuis
Odoo, ce qui demande deux choses au conteneur :

- le code et ses dépôts git appartiennent au compte qui fait tourner Odoo.
  L'image se construit avec `ERPLIBRE_CODE_OWNER=odoo`, la valeur par défaut ;
  `root` construit une image qu'Odoo ne peut pas réécrire, et
  `script/git/repo_pull.py` refuse ses clones en nommant leur propriétaire. Les
  images d'ERPLibre 1.6.0 et antérieures laissent le clone à root.
  `script/update/docker_fix_erplibre_info_docker_erplibre_160.sh` met à jour
  la racine ERPLibre d'un conteneur en marche et la prépare pour les
  instantanés d'`erplibre_info_git` ; il lance git sous le propriétaire de
  `/ERPLibre`, jamais sous root, si bien que sur une telle image il s'arrête
  avant git, à l'étape 2 au plus tard, et nomme le premier chemin que ce
  propriétaire ne peut pas écrire. Il prend en charge une image dont le code
  appartient à son propriétaire, un compte autre que root, et son dernier
  message nomme ce qui manque encore au tirage ;
- Odoo tourne avec une valeur de `--dev` :

<!-- [common] -->
```yaml
    command: odoo --dev=all
```

<!-- [en] -->
Write the `=`: the entrypoint appends its database arguments after the
command, and a bare `--dev` takes the next one, `--db_host`, as its value.
Odoo 18 reads `--dev` from the command line only, a `dev_mode` line of
`odoo.conf` is ignored. `all` turns on `reload`, `qweb` and `xml`, which slows
the server down.

A clone mounted from the host brings its files, not its git: the `.git` of a
git-repo project is a relative link into `.repo/projects`, which resolves to
the container's own `.repo`. Odoo loads the mounted modules, but a snapshot
reads that repository from the image.

<!-- [fr] -->
Écrivez le `=` : l'entrée de l'image ajoute ses arguments de base de données
après la commande, et un `--dev` seul prend le suivant, `--db_host`, pour
valeur. Odoo 18 ne lit `--dev` que sur la ligne de commande, une ligne
`dev_mode` d'`odoo.conf` est ignorée. `all` active `reload`, `qweb` et `xml`,
ce qui ralentit le serveur.

Un clone monté depuis l'hôte apporte ses fichiers, pas son git : le `.git`
d'un projet git-repo est un lien relatif vers `.repo/projects`, qui mène au
`.repo` du conteneur lui-même. Odoo charge les modules montés, mais un
instantané lit ce dépôt depuis l'image.

<!-- [en] -->
### Diagnostic Docker-Compose

Show docker-compose information

<!-- [fr] -->
### Diagnostic Docker-Compose

Afficher les informations docker-compose

<!-- [common] -->
```bash
docker compose ps
docker compose logs IMAGE_NAME
```

<!-- [en] -->
Show docker information

<!-- [fr] -->
Afficher les informations docker

<!-- [common] -->
```bash
docker ps -a
docker volume ls
docker inspect DOCKER_NAME
```

<!-- [en] -->
Connect to a running docker: a shell as `odoo`, for work in `/ERPLibre`,
then the reduced root shell, see "Extra Python packages for the addons"

<!-- [fr] -->
Se connecter à un docker en cours d'exécution : un shell sous `odoo`, pour
travailler dans `/ERPLibre`, puis le shell root réduit, voir « Paquets Python
supplémentaires pour les addons »

<!-- [common] -->
```bash
docker compose exec -u odoo ERPLibre bash
make docker_exec_erplibre
```

<!-- [en] -->
Show the container's `/etc/odoo/odoo.conf`, read from the project's
`erplibre_conf` volume: the project need not run, nor its container exist.
A throwaway container of the ERPLibre image, already on the host, reads the
volume read-only, with no network; the file goes to the screen only, as it
carries the passwords. An account outside the `docker` group goes through
`sudo`.

<!-- [fr] -->
Afficher le `/etc/odoo/odoo.conf` du conteneur, lu dans le volume
`erplibre_conf` du projet : le projet n'a pas à tourner, ni son conteneur à
exister. Un conteneur jetable de l'image ERPLibre, déjà sur l'hôte, lit le
volume en lecture seule, sans réseau ; le fichier ne va qu'à l'écran, car il
porte les mots de passe. Un compte hors du groupe `docker` passe par `sudo`.

<!-- [common] -->
```bash
make docker_show_odoo_conf
```

<!-- [en] -->
Commands for debugging

<!-- [fr] -->
Commandes pour le débogage

<!-- [common] -->
```bash
docker run -p 127.0.0.1:8069:8069 --entrypoint bash -ti DOCKER_NAME
docker compose exec -u odoo ERPLibre bash
make docker_exec_erplibre
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres postgre

export
db_host = "host.docker.internal"

docker stats erplibre_ERPLibre_1
```

<!-- [en] -->
### Cleaning

Delete all system

<!-- [fr] -->
### Nettoyage

Supprimer tout le système

<!-- [common] -->
```bash
docker system prune -a
```

<!-- [en] -->
Delete docker image

<!-- [fr] -->
Supprimer une image docker

<!-- [common] -->
```bash
docker image prune
docker rmi $(docker images -q)
```

<!-- [en] -->
Delete the volumes of this project: every database, the Odoo filestore and
its configuration, for good. The command lists them, then asks for a `y` and
for the project name typed again; any other answer deletes nothing.

<!-- [fr] -->
Supprimer les volumes de ce projet : toutes les bases, le filestore d'Odoo et
sa configuration, sans retour. La commande les liste, puis demande un `y` et
le nom du projet retapé ; toute autre réponse n'efface rien.

<!-- [common] -->
```bash
make docker_volume_clean
```

<!-- [en] -->
Delete containers

<!-- [fr] -->
Supprimer les conteneurs

<!-- [common] -->
```bash
docker rm $(docker ps -a | grep -v IMAGE | awk '{print $1}')
```

<!-- [en] -->
Delete volume

<!-- [fr] -->
Supprimer un volume

<!-- [common] -->
```bash
docker volume prune
```

<!-- [en] -->
# Change docker directory
You can change the docker directory by editing file `/etc/docker/daemon.json`

<!-- [fr] -->
# Changer le répertoire docker
Vous pouvez changer le répertoire docker en modifiant le fichier `/etc/docker/daemon.json`

<!-- [common] -->
```json
{
  "data-root": "/home/docker"
}
```

<!-- [en] -->
And restart docker service. You can delete or move all older locations of docker.

Or

Add `--data-root /second_drive/docker` like example following into file `/lib/systemd/system/docker.service` :

<!-- [fr] -->
Et redémarrez le service docker. Vous pouvez supprimer ou déplacer tous les anciens emplacements de docker.

Ou

Ajoutez `--data-root /second_drive/docker` comme dans l'exemple suivant dans le fichier `/lib/systemd/system/docker.service` :

<!-- [common] -->
```
ExecStart=/usr/bin/dockerd --data-root /second_drive/docker -H fd:// --containerd=/run/containerd/containerd.sock
```

<!-- [en] -->
# Update docker
When building your docker with script
> make docker_build_odoo_18

List your docker version
> docker images

You need to push your docker image and update your tag, like 1.0.1:
> docker push technolibre/erplibre:VERSION

# Diagnostic
When getting and error about missing module, or after an upgrade, you need to update config file.
> make docker_exec_erplibre_gen_config

<!-- [fr] -->
# Mettre à jour docker
Lors de la construction de votre docker avec le script
> make docker_build_odoo_18

Listez vos versions docker
> docker images

Vous devez pousser votre image docker et mettre à jour votre tag, comme 1.0.1 :
> docker push technolibre/erplibre:VERSION

# Diagnostic
Lorsque vous obtenez une erreur de module manquant, ou après une mise à jour, vous devez mettre à jour le fichier de configuration.
> make docker_exec_erplibre_gen_config
