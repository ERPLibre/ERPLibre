
# Selenium Installation

The scripts run in the tooling venv, `.venv.erplibre`, which already holds
`selenium` and `pykeepass`. `requirements.txt` adds the rest, none of which
needs a system library; `requirements-video.txt` adds the video recorder,
PyGObject, built against the system libraries below.
`script/install/install_debian_dependency.sh` installs them on Debian and
Ubuntu.

```bash
.venv.erplibre/bin/pip install -r script/selenium/requirements.txt

sudo apt install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository-2.0-dev ffmpeg
.venv.erplibre/bin/pip install -r script/selenium/requirements-video.txt
```

PyGObject, which pulls pycairo, builds from 3.50 on against girepository-2.0
and requires GLib 2.80: Debian 13 and Ubuntu 24.04 have it, Debian 12 does
not, and there video recording is not available. `ffmpeg` converts the
recordings to MP4.

geckodriver needs no installation: Selenium Manager, shipped with `selenium`,
downloads it into `~/.cache/selenium` on first use. The Firefox driven is the
Ubuntu snap, else `firefox`, else `firefox-esr`, Debian's name.

Video recorder: https://github.com/szemate/pyselenium-video-recorder

## In the ERPLibre container

The image has no browser and no display. The scripts drive a node of the
Selenium grid that `docker/docker-compose_odoo_18.0_selenium.yml` starts; the
node sends the downloads back to the script. Give `--url` too: the default,
`http://127.0.0.1:8069`, is read by the browser, on its node, where no Odoo
answers. The scripts run as `odoo`: the compose starts the container as root,
so `exec` opens root by default, and that root cannot read the password file
below.

```bash
docker compose --project-directory . -f docker/docker-compose_odoo_18.0_selenium.yml \
  exec -u odoo ERPLibre .venv.erplibre/bin/python script/selenium/SCRIPT.py \
  --use_network http://selenium-hub:4444 --url http://ERPLibre:8069
```

An ERPLibre image built from this version carries in `.venv.erplibre` the
packages the scripts import, listed in
`requirement/erplibre_require-ments-docker.txt`. The 1.8.0 image lacks them
and predates `KDBX_PASSWORD_FILE`: the compose can add the packages at each
start, but the scripts stay the image's older copies. Pin them, `selenium` on
the grid's 4.34 so that client and grid run the same release: a bare name
installs the latest one.

```yaml
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: "selenium==4.34.2 pykeepass==4.2.0 python-randomword-fr==1.0.0"
```

A script that logs in with the KeePass vault finds it at `kdbx.path` in
`private/todo/todo_override_private.json`. `KDBX_PASSWORD_FILE` names a file
that holds the password; the value itself stays out of the environment and of
the JSON. Once set, the variable wins over `kdbx.password` and over the
prompt, terminal or not, which lets a script run unattended; an unreadable
file, like a vault that does not open, stops the script with its cause. A
commented line of the compose sets the variable; the file reaches the
container through the compose's `./private` mount, with no mount of its own:

```yaml
      KDBX_PASSWORD_FILE: /ERPLibre/private/kdbx_password
```

The file belongs to uid 101, the image's `odoo` account, with mode 400. With a
Docker daemon run by root:

```bash
sudo chown 101:101 private/kdbx_password && sudo chmod 400 private/kdbx_password
```

Rootless Docker maps the container's uid 101 to a host uid of its own: the
owner changes from a container of the compose's image, `IMAGE` below, as its
root.

```bash
chmod 400 private/kdbx_password
docker run --rm -u root -v "$PWD/private:/p" --entrypoint chown IMAGE 101:101 /p/kdbx_password
```