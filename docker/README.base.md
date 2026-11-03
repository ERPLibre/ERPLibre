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
### Extra Python packages for the addons

An addon, or an ERPLibre script, can need a Python package the image does not
carry. List them on one line, separated by spaces, with a version when it
matters; a constraint holds neither a space nor a quote. Each venv of the image
has its own list: `PIP_EXTRA_REQUIREMENTS_ODOO` for Odoo's venv, the one the
addons import, and `PIP_EXTRA_REQUIREMENTS_ERPLIBRE` for `.venv.erplibre`, the
one of the tools in `script/`:

<!-- [fr] -->
### Paquets Python supplémentaires pour les addons

Un addon, ou un script d'ERPLibre, peut demander un paquet Python que l'image
n'a pas. Listez-les sur une ligne, séparés par des espaces, avec une version
quand elle compte ; une contrainte ne contient ni espace ni guillemet. Chaque
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
that each pip runs as the owner of its venv, the `ERPLIBRE_CODE_OWNER` of the
build. A satisfied requirement downloads nothing. A
requirement pip cannot install stops the container before Odoo, with pip's
error in `docker compose logs`.

<!-- [fr] -->
À chaque démarrage, `docker/entrypoint_pip_extra.sh` installe chaque liste
avec le pip de son venv, puis lance Odoo sous `odoo` : le conteneur démarre en
root pour que chaque pip tourne sous le propriétaire de son venv,
l'`ERPLIBRE_CODE_OWNER` de la construction. Une exigence déjà satisfaite ne
télécharge rien. Une exigence que pip ne peut pas installer arrête le conteneur
avant Odoo, avec l'erreur de pip dans `docker compose logs`.

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
### Pulling the code from Odoo

`erplibre_info_git_fetch` fetches and pulls the git clones from Odoo, which
asks two things of the container:

- the code and its git repositories belong to the account that runs Odoo. The
  image is built with `ERPLIBRE_CODE_OWNER=odoo`, the default; `root` builds an
  image Odoo cannot rewrite, and `script/git/repo_pull.py` refuses its clones,
  naming their owner. The images of ERPLibre 1.6.0 and earlier leave the code
  to root: `script/update/docker_fix_erplibre_info_docker_erplibre_160.sh`
  readies such a container for the snapshots of `erplibre_info_git` only, and
  its last message names the condition that is missing;
- Odoo runs with a value of `--dev`:

<!-- [fr] -->
### Tirer le code depuis Odoo

`erplibre_info_git_fetch` fait le fetch et le tirage des clones git depuis
Odoo, ce qui demande deux choses au conteneur :

- le code et ses dépôts git appartiennent au compte qui fait tourner Odoo.
  L'image se construit avec `ERPLIBRE_CODE_OWNER=odoo`, la valeur par défaut ;
  `root` construit une image qu'Odoo ne peut pas réécrire, et
  `script/git/repo_pull.py` refuse ses clones en nommant leur propriétaire. Les
  images d'ERPLibre 1.6.0 et antérieures laissent le code à root :
  `script/update/docker_fix_erplibre_info_docker_erplibre_160.sh` ne prépare un
  tel conteneur que pour les instantanés d'`erplibre_info_git`, et son dernier
  message nomme la condition qui manque ;
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
Connect to a running docker

<!-- [fr] -->
Se connecter à un docker en cours d'exécution

<!-- [common] -->
```bash
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
```

<!-- [en] -->
Commands for debugging

<!-- [fr] -->
Commandes pour le débogage

<!-- [common] -->
```bash
docker run -p 8069:8069 --entrypoint bash -ti DOCKER_NAME
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
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
