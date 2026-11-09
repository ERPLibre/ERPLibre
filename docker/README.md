
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

The file lives in the project's `erplibre_conf` volume, belongs to `odoo` and
outlives a recreated container. The image carries no text editor: the
commands below set both options as `odoo`, print the new master password once,
then restart Odoo; like them, `make docker_exec_erplibre_gen_config`
rewrites the file without its comments, and changes `addons_path` only.
`make docker_show_odoo_conf` shows the result.

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

### Extra Python packages for the addons

An addon, or an ERPLibre script, can need a Python package the image does not
carry. List them separated by spaces or newlines, with a version when it
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
that each pip runs as the owner of its venv, `odoo`. A satisfied requirement
downloads nothing. A requirement pip cannot install stops the container before
Odoo, with pip's error in `docker compose logs`.

In an image built with `ERPLIBRE_CODE_OWNER=root`, the venvs belong to root
but `/ERPLibre`, which holds them, stays `odoo`'s: Odoo could swap a venv for
one of its own before root runs its pip. The entrypoint therefore refuses any
`PIP_EXTRA_REQUIREMENTS_*` list there and stops the container before Odoo;
such an image takes its packages at build time, in an image derived from it.

Root keeps only the two capabilities setpriv needs (`cap_drop`, `cap_add`), and
`no-new-privileges` stops Odoo from ever regaining one. Since the container
starts as root, `docker exec` opens a root shell by default: a file it writes in
the filestore or in `/etc/odoo` belongs to root, and Odoo can no longer change
it. Pass the account:

```bash
docker compose exec -u odoo ERPLibre bash
```

`make docker_exec_erplibre`, that is `script/docker/docker_exec.sh`, and the
TODO menu entry "Enter the ERPLibre container" open a plain root shell: it
keeps only the `SETUID` and `SETGID` capabilities, whatever `cap_add` the
compose grants for apt, under `no-new-privileges`, so root there neither
reads nor writes what the file permissions refuse it, and apt installs
nothing. It starts in `/`, with a system-only `PATH` and no profile
nor bashrc, reading nothing that `odoo` can rewrite. A Debian package goes in
`APT_EXTRA_PACKAGES`, below; work in `/ERPLibre`, which `odoo` owns, goes
through the `docker compose exec -u odoo` above.

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

```yaml
    environment:
      APT_EXTRA_PACKAGES: "libmagic1"
    cap_add: [SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER, FSETID]
```

A large package, a browser for Selenium for instance, is better built into an
image derived from ERPLibre's: as a start-time install it is downloaded again
at each recreation.

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

```yaml
    environment:
      INIT_CMD: "./script/my_startup.sh"
```

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

Connect to a running docker: a shell as `odoo`, for work in `/ERPLibre`,
then the reduced root shell, see "Extra Python packages for the addons"

```bash
docker compose exec -u odoo ERPLibre bash
make docker_exec_erplibre
```

Show the container's `/etc/odoo/odoo.conf`, read from the project's
`erplibre_conf` volume: the project need not run, nor its container exist.
A throwaway container of the ERPLibre image, already on the host, reads the
volume read-only, with no network; the file goes to the screen only, as it
carries the passwords. An account outside the `docker` group goes through
`sudo`.

```bash
make docker_show_odoo_conf
```

Commands for debugging

```bash
docker run -p 127.0.0.1:8069:8069 --entrypoint bash -ti DOCKER_NAME
docker compose exec -u odoo ERPLibre bash
make docker_exec_erplibre
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

Delete the volumes of this project: every database, the Odoo filestore and
its configuration, for good. The command lists them, then asks for a `y` and
for the project name typed again; any other answer deletes nothing.

```bash
make docker_volume_clean
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
