
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

```bash
systemctl start docker
```

### Building the docker images

```bash
cd docker
docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
docker build -f Dockerfile.prod.pkg -t technolibre/erplibre:12.0-pkg .
```


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

```bash
cd ERPLibre
docker compose -f docker-compose.yml up -d
```

### Extra Python packages for the addons

An addon, or an ERPLibre script, can need a Python package the image does not
carry. List them on one line, separated by spaces, with a version when it
matters; a constraint holds neither a space nor a quote. Each venv of the image
has its own list: `PIP_EXTRA_REQUIREMENTS_ODOO` for Odoo's venv, the one the
addons import, and `PIP_EXTRA_REQUIREMENTS_ERPLIBRE` for `.venv.erplibre`, the
one of the tools in `script/`:

```yaml
    environment:
      PIP_EXTRA_REQUIREMENTS_ODOO: "humanize pyotp==2.9.0 phonenumbers>=8.13,<9"
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: ""
```

At each start, `docker/entrypoint_pip_extra.sh` installs each list with the
pip of its venv, then runs Odoo as `odoo`: the container starts as root so
that each pip runs as the owner of its venv, the `ERPLIBRE_CODE_OWNER` of the
build. A satisfied requirement downloads nothing. A
requirement pip cannot install stops the container before Odoo, with pip's
error in `docker compose logs`.

Root keeps only the two capabilities setpriv needs (`cap_drop`, `cap_add`), and
`no-new-privileges` stops Odoo from ever regaining one. Since the container
starts as root, `docker exec` opens a root shell by default: a file it writes in
the filestore or in `/etc/odoo` belongs to root, and Odoo can no longer change
it. Pass the account:

```bash
docker compose exec -u odoo ERPLibre bash
```

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

```yaml
    command: odoo --dev=all
```

Write the `=`: the entrypoint appends its database arguments after the
command, and a bare `--dev` takes the next one, `--db_host`, as its value.
Odoo 18 reads `--dev` from the command line only, a `dev_mode` line of
`odoo.conf` is ignored. `all` turns on `reload`, `qweb` and `xml`, which slows
the server down.

A clone mounted from the host brings its files, not its git: the `.git` of a
git-repo project is a relative link into `.repo/projects`, which resolves to
the container's own `.repo`. Odoo loads the mounted modules, but a snapshot
reads that repository from the image.

### Diagnostic Docker-Compose

Show docker-compose information

```bash
docker compose ps
docker compose logs IMAGE_NAME
```

Show docker information

```bash
docker ps -a
docker volume ls
docker inspect DOCKER_NAME
```

Connect to a running docker

```bash
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
```

Commands for debugging

```bash
docker run -p 8069:8069 --entrypoint bash -ti DOCKER_NAME
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres postgre

export
db_host = "host.docker.internal"

docker stats erplibre_ERPLibre_1
```

### Cleaning

Delete all system

```bash
docker system prune -a
```

Delete docker image

```bash
docker image prune
docker rmi $(docker images -q)
```

Delete volumes

```bash
docker compose rm -v
```

Delete containers

```bash
docker rm $(docker ps -a | grep -v IMAGE | awk '{print $1}')
```

Delete volume

```bash
docker volume prune
```

# Change docker directory
You can change the docker directory by editing file `/etc/docker/daemon.json`

```json
{
  "data-root": "/home/docker"
}
```

And restart docker service. You can delete or move all older locations of docker.

Or

Add `--data-root /second_drive/docker` like example following into file `/lib/systemd/system/docker.service` :

```
ExecStart=/usr/bin/dockerd --data-root /second_drive/docker -H fd:// --containerd=/run/containerd/containerd.sock
```

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
