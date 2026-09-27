
# Dolibarr

ERPLibre installs and runs [Dolibarr](https://www.dolibarr.org/), the PHP
ERP, next to Odoo. The Dolibarr version is pinned: a commit of the official
repository, fetched by Google Repo into `dolibarr/dolibarr`.

From TODO:

- `Installation › Dolibarr` installs an instance;
- `Execute › Dolibarr` starts, stops and follows development instances, and
  moves the pinned commit.

Each TODO entry runs a script of this directory with its parameters; every
script also runs on its own.

## Scripts

| Script | Role |
|--------|------|
| `install_native.py` | Installs an instance with nginx, PHP-FPM and MariaDB or PostgreSQL |
| `install_container.py` | Installs a development instance in Docker or Podman containers |
| `native_prod.py` | Production steps, played by `install_native.py --mode prod` |
| `run.py` | `start`, `stop`, `status`, `logs` of a development instance |
| `pin.py` | `show` the pinned commit, `update` it (dry run unless `--apply`) |
| `detect.py` | Find Dolibarr installations on this machine or over SSH |
| `doctor.py` | Health, security and integrity of each registered instance |
| `backup.py` | `create`, `list` and `restore` backups (restore: `restore.py`) |
| `fleet.py` | `list` the instances, `remove` one |
| `lib_dolibarr.py` | Pure decisions: pin, names, what the host allows |
| `packages.py` | Package names and paths per distribution family |
| `web_config.py`, `units.py`, `install_files.py` | Pure rendering of the nginx, PHP-FPM, systemd and install files |
| `container_plan.py` | Pure rendering of the Docker/Podman commands of an instance |
| `integrity.py` | Installed code against the archive of its pinned commit |

Supported families: Debian/Ubuntu (apt), Fedora/EL (dnf), Arch (pacman),
openSUSE (zypper).

## Development

```bash
./script/dolibarr/install_native.py --mode dev --db mariadb --instance erp --port 8080
./script/dolibarr/run.py start --instance erp
./script/dolibarr/run.py status
./script/dolibarr/run.py logs --instance erp --lines 40
./script/dolibarr/run.py stop --instance erp
```

nginx and PHP-FPM run under your own account on `127.0.0.1:<port>`; nothing
goes to `/etc`. The code is the checkout itself, so a change in
`dolibarr/dolibarr/htdocs` shows on the next page load. Everything else of
the instance lives in `~/.local/share/ERPLibre/dolibarr/<instance>`:
documents, `run/` (pid, socket, logs) and `secrets.env` (0600: database and
administrator passwords).

The administrator password is asked by TODO, or generated when left empty.
On the command line it comes from the `EL_DOLIBARR_ADMIN_PASSWORD`
environment variable, never from an argument.

## Containers (development)

```bash
./script/dolibarr/install_container.py --mode dev --instance erp --port 8081 [--engine podman]
```

The official `dolibarr/dolibarr` image on MariaDB, with Docker or Podman,
whichever answers without sudo first; no compose tool is needed. The image
runs the version Docker Hub publishes, which can trail the native pin. Its
data lives in named volumes; `custom/` is a host directory, writable from
the container, for module development. Secrets are files (0600) in
`~/.local/share/ERPLibre/dolibarr/<instance>/secrets`, passed to the
containers read-only. The first start takes about 70 to 100 s.

## Production

```bash
./script/dolibarr/install_native.py --mode prod --db mariadb --instance erp \
    --domain erp.example.org --tls certbot --email ops@example.org
```

Production needs systemd and a domain name. Layout of an instance `<i>`:

- code: `/opt/erplibre-dolibarr/<i>`, exported from the pinned commit,
  owned by root and read-only;
- data: `/var/lib/erplibre-dolibarr/<i>` (documents, sessions), owned by the
  system account `dolibarr_<i>`;
- secrets, cron key, copy of `conf.php`, local certificate:
  `/etc/erplibre-dolibarr/<i>`, root, 0700;
- PHP-FPM: one pool under `dolibarr_<i>`, whose socket only nginx reads;
- nginx: one site where the distribution keeps them;
- scheduled jobs: `erplibre-dolibarr-cron-<i>.timer` runs Dolibarr's jobs
  every 5 minutes.

`conf.php` ends read-only for the instance account, with `prod` on.
`--tls` chooses the certificate: `certbot` (Let's Encrypt, public name;
certbot is installed, from EPEL on EL), `local` (for tests: signed by the
local authority of the reverse proxy, `~/.erplibre/reverse_proxy_tls/ca.crt`,
imported once in the browser) or `none` (HTTP only). Each nginx site closes
the connection on any host name but its own.

Every secret is written to `secrets.env` before the database is touched: an
install stopped by an error resumes with the same passwords when run again.

Known limit: SELinux in enforcing mode is refused until its contexts are
set.

## Operations

```bash
./script/dolibarr/detect.py --local            # or --ssh host (repeatable)
./script/dolibarr/doctor.py --all
./script/dolibarr/backup.py create --instance erp
./script/dolibarr/backup.py restore --instance erp --archive <file> --confirm erp
./script/dolibarr/fleet.py list
./script/dolibarr/fleet.py remove --instance erp --dry-run
```

- `detect.py` sends a read-only POSIX sh probe (one round trip, no
  privilege) and reports each installation and Dolibarr container, never a
  password; reports go to `private/dolibarr/inventory/`.
- `doctor.py` checks what each instance serves, its code (production: every
  file against the pinned archive, where an added PHP file fails), its
  `conf.php`, its install lock, its cron timer and PHP; it changes nothing.
- A backup holds the database, `documents/`, `custom/` and `conf.php`, whose
  instance key encrypts values in the database; 0600, under
  `private/dolibarr/backups/`. Restoring asks for the instance name, takes a
  safety backup first, refuses a backup newer than the code, and also
  clones a backup into a freshly installed instance.
- Removing an instance shows its plan first and asks for its name; a
  container's `custom/` stays.

## Pinned version

```bash
./script/dolibarr/pin.py show
./script/dolibarr/pin.py update                 # dry run: what would change
./script/dolibarr/pin.py update --apply
./script/manifest/update_manifest_local_dolibarr.sh
```

`conf/supported_version_dolibarr.json` and `manifest/git_manifest_dolibarr.xml`
move together. The Docker image tag follows only when Docker Hub publishes
it.

The checkout belongs to Google Repo: a project dropped from the merged
manifest is deleted at the next sync, `conf.php` included. ERPLibre merges
the Dolibarr manifest automatically as soon as `dolibarr/dolibarr` exists,
and keeps a copy of `conf.php` in the instance's state directory.
