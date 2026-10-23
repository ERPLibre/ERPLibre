
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
| `upgrade.py` | Upgrade an instance to the pinned version, rollback on failure |
| `debug.py` | Debug profile of an instance `on`/`off`, `status`, `tail` of its log |
| `module.py` | `create`, `link`, `enable`, `disable` the modules of a development instance |
| `package.py` | `check` a module against DoliStore's rules, `build` its zip |
| `quality.py` | phpcs and PHPStan on a module, with Dolibarr's own rules |
| `hooks_index.py` | Hooks, contexts and triggers at a version, and the diff between two |
| `core.py` | Core changes: `status`, `start` a work branch, `check` against CONTRIBUTING, `patches` |
| `api.py` | REST API: `enable` (module, read-only user, key), `status`, `disable` |
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
./script/dolibarr/upgrade.py --instance erp        # after pin.py update --apply
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
- `upgrade.py` brings an instance to the pinned version after `pin.py
  update --apply`: backup first, one major version at a time, success
  judged by `MAIN_VERSION_LAST_UPGRADE` and not by exit codes alone, and on
  failure the old code (or image) and the backup come back. A new commit
  of the same version is upgraded too: its schema can differ. The full
  output of each upgrade goes to `private/dolibarr/upgrades/`, and
  `doctor.py` warns when an instance is behind the pin.

## Development tools

```bash
./script/dolibarr/debug.py on --instance erp       # off puts everything back
./script/dolibarr/debug.py on --instance erp --xdebug    # native development
./script/dolibarr/debug.py tail --instance erp --filter ERR
./script/dolibarr/module.py create --instance erp --name Zorglub --enable
./script/dolibarr/module.py link --instance erp --path ~/src/zorglub
./script/dolibarr/module.py enable --instance erp --name Stock
./script/dolibarr/package.py check --instance erp --name Zorglub
./script/dolibarr/package.py build --instance erp --name Zorglub --dolistore
./script/dolibarr/quality.py --instance erp --name Zorglub [--only phpstan]
./script/dolibarr/hooks_index.py list --kind context --filter '^thirdparty'
./script/dolibarr/hooks_index.py diff --from 23.0.4       # to the pinned commit
./script/dolibarr/core.py start --topic fix-invoice-total
./script/dolibarr/core.py check && ./script/dolibarr/core.py patches
```

- `debug.py on` shows development features (`MAIN_FEATURES_LEVEL=2`),
  enables DebugBar and Syslog at level 7 (every SQL query), and on a native
  development instance sets `conf.php` to prod=0 and strict mode. The
  previous state is saved once; `off` puts it back row for row. A production
  needs its name retyped: level 7 logs session ids.
- `--xdebug`, on a native development instance, loads Xdebug 3 into that
  instance's PHP-FPM only (an ini under its `run/php.d`, nothing in
  `/etc`), in trigger mode on port 9003: add `?XDEBUG_TRIGGER=1` to the
  address or use the browser's Xdebug helper. The package is installed if
  PHP-FPM cannot load it; a host that already loads it everywhere (Debian
  and Fedora do on install) is not made to load it twice. VS Code gets a
  configuration in the checkout's `.vscode/launch.json`, which Dolibarr's
  `.gitignore` ignores; PhpStorm's settings are printed. The paths are the
  same on both sides, so no mapping is needed.
- `module.py create` does what the ModuleBuilder's "New module" does, from
  the instance's own template, so the module goes on in the ModuleBuilder.
  It lands in `custom/` (the checkout's `htdocs/custom`, or the host
  directory mounted in the container) with the first free ID from 500000;
  IDs from 100000 to 499999 are reserved on the Dolibarr wiki. The author
  comes from `--author` or git.
- `module.py link` symlinks a module kept in its own repository into
  `htdocs/custom` (native only: a container sees only its `custom/`).
  `enable` and `disable` go through Dolibarr, dependencies and permissions
  included. A production is refused: it receives a package.
- `package.py build` writes `<module>/bin/module_<name>-<version>.zip` as
  the ModuleBuilder's "Generate package" does; Dolibarr's "Deploy an
  external module" page takes it as is. A broken descriptor, a version
  that is not numeric or a PHP syntax error blocks the zip. `check` also
  applies DoliStore's rules: an ID from 95000 to 499999 (500000 and up is
  never distributed), a complete en_US, pages that try `main.inc.php` in
  several places, `#!/usr/bin/env php` on scripts, no copy of a core file;
  `--dolistore` makes them block the zip. "Dolibarr" as a word of the name
  and an empty editor are warnings.
- `quality.py` runs phpcs with Dolibarr's ruleset and PHPStan with its
  `phpstan.neon.dist` (the core scanned for symbols, the CI's bootstrap)
  from the pinned composer image: Docker or Podman, nothing installed on
  the host, the tools cached in a volume named after their versions.
  PHPStan follows the version of Dolibarr's CI; phpcs is the last 3.x,
  which Dolibarr's own sniffs target. The ModuleBuilder template's PHPStan
  baseline follows the renamed module, so a fresh module comes out clean.
  Exit 0 clean, 1 findings, 2 a tool that could not finish. A container
  instance needs the pinned checkout, fetched by
  `script/manifest/update_manifest_local_dolibarr.sh`.
- `hooks_index.py` reads, with `git grep` and without checking anything
  out, the hook names passed to `executeHooks`, the literal contexts of
  `initHooks`, the trigger codes passed to `call_trigger` and the agenda
  codes of `llx_c_action_trigger.sql`; `diff` says what appeared or
  vanished between two versions, what a module must look at before an
  upgrade. The pinned commit is read from the checkout; any other tag,
  branch or commit is fetched once, at depth 1, into
  `~/.erplibre/dolibarr_index.git`, which borrows the checkout's objects:
  the checkout that Google Repo manages is never written.
- `core.py` works on the pinned checkout and nothing leaves this machine:
  no push, no pull request. `start` opens a work branch at the pinned
  commit (`repo start`) and deepens the shallow history; it needs a git
  identity, since `repo sync` silently resets a branch none of whose
  commits carries it (`status` warns about it). `check` applies Dolibarr's
  `CONTRIBUTING.md`: the author's `Signed-off-by` (DCO), a title keyword
  (FIX, CLOSE, NEW, PERF, DOC, QUAL, SEC, in capitals for the ChangeLog),
  neither `ChangeLog` nor a language other than en_US, one fix per pull
  request on a stable branch. `patches` exports the series under
  `private/dolibarr/patches/`. The `ERPLibre/dolibarr` fork does not exist
  yet; `status` says when it answers.

## Integration

```bash
./script/dolibarr/api.py enable --instance erp     # --rotate for a new key
./script/dolibarr/api.py status --instance erp
```

- `api.py enable` turns the REST API module on and creates a technical
  user, `erplibre_api`, holding every read right and nothing else. Its
  `DOLAPIKEY` is drawn by ERPLibre, reaches PHP on stdin only, is stored
  encrypted by Dolibarr and kept in `private/dolibarr/api/<instance>.key`
  (0600). Run again, `enable` keeps the key; `--rotate` draws another one
  and the old one stops working.
- `status` calls `/api/index.php/status` with the key: only the status
  answer counts, since a disabled module answers 200 in plain text. The
  explorer (swagger) is at `/api/index.php/explorer/`. A production needs
  its name retyped to turn the API on or off. Dolibarr 24's MCP server,
  still experimental, comes later.

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
