
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

## With the Docker compose

The ERPLibre image has no browser and no display.
`docker/docker-compose_odoo_18.0_selenium.yml` starts Odoo next to a Selenium
grid, and the scripts run from the host's checkout, in its `.venv.erplibre`,
never in the ERPLibre container: the account that runs Odoo must read
neither the KeePass vault nor its password, so the compose does not mount
`private/` there.

The scripts drive the grid through its router, published on
`127.0.0.1:8075`. The browser runs in a node, headless as the nodes have no
display: pass `--headless`, without which the session does not start. It
reaches Odoo by its service name: give `--url http://ERPLibre:8069`, as the
default, `http://127.0.0.1:8069`, names the node itself, where no Odoo
answers. Some scripts also call Odoo from the host with the same URL,
`run_requirement_tours.py` among them, which lists the databases by
XML-RPC; Odoo is published on the host's `127.0.0.1:8069`, so one line in
the host's `/etc/hosts` makes `http://ERPLibre:8069` work on both sides. The
nodes send the downloads back to the script on the host (managed downloads,
on by default in their images).

```bash
grep -qw ERPLibre /etc/hosts || echo "127.0.0.1 ERPLibre" | sudo tee -a /etc/hosts
```

Three networks keep the grid out of Odoo's reach. The hub and the nodes
share `grid`, which ERPLibre is not on: neither the router, nor the event
bus, nor a node's Selenium server answers it. The nodes join ERPLibre on
`web` to load its pages, and their Selenium server does not listen there.
PostgreSQL is on `backend`, with ERPLibre alone. The nodes run neither an X
display, whose server would accept any client of `web`, nor a VNC server,
whose password is a public default in the image.

The router asks for a user and a password (basic authentication) on every
request, `/status` included, which lists the sessions: with the network
split, they guard the sessions and what the scripts type. The registration
secret guards something else: the hub accepts a node only when it carries
the same secret, so no other container can register one and receive the
sessions.

Neither travels through an environment variable. The image's start scripts
turn `SE_ROUTER_USERNAME`, `SE_ROUTER_PASSWORD` and `SE_REGISTRATION_SECRET`
into arguments of the `java` command, which any account of the host reads
with `ps`: with rootless Docker, the processes of a container are processes
of the host. The compose sets none of the three; Selenium reads them from
two TOML files that it mounts read-only and passes with `--config`:

- `selenium-hub.toml`, for the hub: `[router]` `username` and `password`,
  `[server]` `registration-secret`;
- `selenium-node.toml`, for each node: `[server]` `registration-secret`
  alone. Selenium merges it with the configuration the image generates at
  each start from the `SE_NODE_*` variables.

`selenium.env`, the file to pass with `--env-file` to every compose command,
names the two files and holds no secret: without it, `up`, `create` and
`config` stop before touching anything, and a path where no file exists
stops the container's creation. After the secrets are generated again, `up`
recreates the hub and the nodes so they read the new files. A `.env` at the
checkout root would be read without the option, but git does not ignore it.
`selenium-router.env` holds the router's credentials for the scripts, and
nothing else.

The four files live outside the checkout, in `~/.config/erplibre`, mode 700.
In the container, Selenium runs as `seluser`, uid 1200, group 1201: the two
TOML files keep you as owner and take the container's group 1201, mode 640.
A throwaway container of the hub image applies that group, as the ids must
be the container's: with rootless Docker, group 1201 maps to a sub-gid of
`/etc/subgid`, which no account of the host carries, so only you and the
grid read them. With a Docker daemon run by root, the same command gives the
files to root and to the host's group 1201: `getent group 1201` must answer
nothing first, and a later rewrite goes through `sudo`.

```bash
mkdir -p ~/.config/erplibre && chmod 700 ~/.config/erplibre
(umask 077 && cd ~/.config/erplibre && python3 - <<'EOF'
import os, secrets
secret, password = secrets.token_hex(32), secrets.token_hex(32)
files = {
    "selenium-hub.toml": f'[router]\nusername = "erplibre"\n'
    f'password = "{password}"\n\n[server]\nregistration-secret = "{secret}"\n',
    "selenium-node.toml": f'[server]\nregistration-secret = "{secret}"\n',
    "selenium-router.env": "SELENIUM_ROUTER_USERNAME=erplibre\n"
    f"SELENIUM_ROUTER_PASSWORD={password}\n",
    "selenium.env": f"SELENIUM_HUB_CONFIG={os.getcwd()}/selenium-hub.toml\n"
    f"SELENIUM_NODE_CONFIG={os.getcwd()}/selenium-node.toml\n",
}
for name, text in files.items():
    with open(name, "w") as f:
        f.write(text)
EOF
)
docker run --rm --network none -u 0 --entrypoint sh \
  -v ~/.config/erplibre/selenium-hub.toml:/s/hub.toml \
  -v ~/.config/erplibre/selenium-node.toml:/s/node.toml \
  selenium/hub:4.34.0-20250707 \
  -c 'chown 0:1201 /s/hub.toml /s/node.toml && chmod 640 /s/hub.toml /s/node.toml'
```

The scripts read the router's credentials from `SELENIUM_ROUTER_USERNAME`
and `SELENIUM_ROUTER_PASSWORD`; the subshell below exports
`selenium-router.env`, which holds these two and nothing else, for the
script alone. `--use_network http://USER:PASSWORD@127.0.0.1:8075` works too,
but puts the password in the process list and the shell history.

The grid trusts the pages its browsers load. A page served by a compromised
Odoo runs in the node's browser, next to the node's own Selenium server:
through the browser, by DNS rebinding for instance, it can reach that server
and read what the session's GET endpoints return. Do not mix third-party
credentials, those of the KeePass vault among them, with an Odoo you do not
trust in one session.

`.venv.erplibre` does not pin `selenium`: a 4.x client drives the 4.34 grid
of the compose, and a command the grid does not know yet fails on its own.
Raise the grid's release when a script needs a newer command.

```bash
docker compose --project-directory . --env-file "$HOME/.config/erplibre/selenium.env" \
  -f docker/docker-compose_odoo_18.0_selenium.yml up -d
(set -a && . ~/.config/erplibre/selenium-router.env && set +a &&
  exec .venv.erplibre/bin/python script/selenium/SCRIPT.py --headless \
    --use_network http://127.0.0.1:8075 --url http://ERPLibre:8069)
```

A script that logs in with the KeePass vault finds it at `kdbx.path` in
`private/todo/todo_override_private.json`. `KDBX_PASSWORD_FILE` names a file
that holds the password; the value itself stays out of the environment and of
the JSON. Once set, the variable wins over `kdbx.password` and over the
prompt, terminal or not, which lets a script run unattended; an unreadable
file, like a vault that does not open, stops the script with its cause.

The file lies outside the checkout, `~/.config/erplibre/kdbx_password` for
instance, belongs to you, with mode 600. Never in `private/`: that directory
can be committed or backed up next to the vault, and the password would then
travel with the vault it opens. The path is read as written, without `~`
expansion: give it through `$HOME`.

```bash
mkdir -p ~/.config/erplibre && chmod 700 ~/.config/erplibre
(umask 077 && IFS= read -rs -p "Vault password: " pw && echo &&
  printf '%s\n' "$pw" >~/.config/erplibre/kdbx_password)
chmod 600 ~/.config/erplibre/kdbx_password
export KDBX_PASSWORD_FILE="$HOME/.config/erplibre/kdbx_password"
```