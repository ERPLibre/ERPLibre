
# Selenium Installation

The scripts run in the tooling venv, `.venv.erplibre`, which already holds
`selenium` and `pykeepass`. `requirements.txt` adds the rest, none of which
builds from source; `requirements-video.txt` adds the video recorder,
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

The image has no browser and no display. The scripts drive a Selenium node
with `--use_network http://selenium-hub:4444`, as
`docker/docker-compose_odoo_18.0_selenium.yml` sets it up; the node sends the
downloads back to the script. `requirements.txt` installs at each start
through the compose:

```yaml
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: "-r /ERPLibre/script/selenium/requirements.txt"
      KDBX_PASSWORD_FILE: /ERPLibre/private/kdbx_password
```

A script that logs in with the KeePass vault finds it at `kdbx.path` in
`private/todo/todo_override_private.json`. With no terminal to type the
password in, `KDBX_PASSWORD_FILE` names a file that holds it, readable by
`odoo` only; the value itself stays out of the environment and of the JSON.
A vault that does not open stops the script with its cause.
