
# ERPLibre production guide

## Requirement

- 5Go of disk space

## Production installation procedure

### 1. Clone the project:

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

### 2. Modify the parameters

Modify the file env_var.sh for production installation. Enable nginx if you need a proxy with `EL_INSTALL_NGINX` at
True. Redirect your DNS to the proxy's ip and add your A and AAAA into `EL_WEBSITE_NAME` with space between.

### 3. Execute the scripts:

#### With proxy nginx production, install certbot before for SSL

```bash
# Snap installation
# https://snapcraft.io/docs/installing-snap-on-debian
sudo apt install -y snapd
sudo snap install core
sudo snap refresh core

# https://certbot.eff.org/lets-encrypt/debianbuster-nginx
# Certbot
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

#### Ubuntu server (24.04, 25.10, 26.04)

```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

A service is running by SystemD, you can access it with the DNS name found in `env_var.sh`

### 4. SSL:

Generate a ssl certificate

```bash
sudo certbot --nginx
```

## Watch log

```bash
sudo systemctl -feu [EL_USER]
```

## Run by address ip

Comment the following line in `/[EL_USER]/erplibre/config.conf`

```
xmlrpc_interface = 0.0.0.0
proxy_mode = True
```

Add your address ip server_name in nginx config `/etc/nginx/sites-available/[EL_WEBSITE_NAME]`

Restart daemon:

```bash
sudo systemctl restart nginx
sudo systemctl restart [EL_USER]
```

## Production execution

```bash
cd /[EL_USER]/erplibre
./run.sh -d [DATABASE] --no-database-list
```

## Move prod database to dev

When moving prod database to your dev environment, you want to remove email servers and install user test to test the
database. WARNING, this is not safe for production, you will expose all data.

1. Copy your database image to directory image_db, exemple the image name is `my_db.zip`
1. Run

```bash
./script/database/db_restore.py --clean_cache --database test_my_db --image my_db
./script/addons/update_prod_to_dev.sh test_my_db
```

## Update production

Update all features.

```bash
./run.sh --limit-time-real 99999 --no-http --stop-after-init -u all -d DATABASE
```

### Update modules of an instance run by systemd

`script/odoo/update_module.py` stops the unit, backs the database up,
updates the modules, restarts the unit and checks its log. The unit is only
read, never modified, and a unit that was running is restarted whatever
happens. Always simulate first:

```bash
./script/odoo/update_module.py --module 'my_module_*' --db DATABASE --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db DATABASE
```

Before anything is stopped, the tool reads the Odoo configuration file the
way Odoo will read it at the restart: a key given twice, a comment after a
number (`workers = 4 # four`) or a memory limit written in MB instead of
bytes refuses the update (code 2), since the stopped unit would not come
back. See "Validate odoo.conf" below.

After a verified restart, the tool checks the health of the local instance
(see below; findings are warnings, never a failure of the update), and
`--warmup-deep` first warms up the public pages and their asset bundles.

With `--warmup-login` and `--warmup-key-file`, or the `login` and
`api_key_file` of the profile group `warmup`, the deep warm-up also loads
the read-only views; the key is read before anything is stopped, and the
production menu hands a KeePass key over as a 0600 file. The menu proposes
the deep warm-up by default. `--i18n-overwrite` lets the translations of
the modules' `.po` files replace those of the database, edited ones
included; the menu asks for it, No by default. After a success, the report
compares the versions of the installed modules before and after the
update.

`--restart-only` restarts the unit with the same guards, without `-u` or
backup, for example after a change to `odoo.conf`. `--update-list` updates
the apps list through an `odoo shell` built from the unit's `ExecStart`
(its `--addons-path` included), Odoo left running, and lists the modules
not installed whose code is missing; `--remove-missing` then removes them
from the list, after a backup and a confirmation on the terminal (or
`--yes`).

`--restart-postgresql` also restarts the PostgreSQL server while Odoo is
stopped, then waits until it accepts connections. Every database of the
server loses its sessions: they are listed before anything is stopped and
confirmed on the terminal (or `--yes`); without either, another database
with sessions refuses (code 2). `--zip ARCHIVE` brings the code of the
modules for a server without git: the archive is checked before the stop
(no path leaving the addons directory, no symbolic link), and each module
folder replaces the one of the addons directory after a tar copy of it.
`--rollback git` notes the commits of the repositories of the
`addons_path` instead. With either, a failure of `-u` or of the restart
puts the code back and restores the database from the backup taken
before; the database left by the update is kept aside. `--no-backup` is
refused with them.

A requested module that the database has not installed is listed as a
warning, since `-u` ignores it; the update is refused before the stop when
none is installed. After the stop, an Odoo without `-d` whose configuration
serves this database, or a PostgreSQL session still connected to it,
refuses the update unless `--force`. The journal is read a second time
after the warm-up and the health check. The report ends with the duration
of each phase and how long the site stayed down. Old update logs of the
database are removed after each real run (`--log-keep-days`, 180 days by
default, the 10 most recent kept), a value also editable in `TODO ›
Execute › Production › Settings`.

The same is reachable from `make todo`: `TODO › Execute › Production ›
Update`. Options, detection order and exit codes:
[script/odoo/README.md](../script/odoo/README.md).

### Verified backups

`script/database/odoo_backup.py` backs a database up in Odoo's own zip
format, verifies the file, keeps a daily, weekly and monthly retention,
reports the age of the last success, test-restores into a temporary
database and restores into a new database only. `update_module.py` uses it
for its backup before an update, under the same database lock.

```bash
./script/database/odoo_backup.py --db DATABASE --dry-run
sudo ./script/database/odoo_backup.py --db DATABASE
./script/database/odoo_backup.py --status
sudo ./script/database/odoo_backup.py --test-restore --db DATABASE
```

The scheduled backup is a systemd service and timer written by
`script/systemd/install_backup_timer.py`. The service runs the backup as
the account of the Odoo unit, never as root, with every option in its
`ExecStart`; the timer runs daily at 03:00 by default (`--on-calendar`),
with `RandomizedDelaySec` and `Persistent=true`. A tmpfiles.d entry
creates the shared lock file `/run/lock/erplibre-db-DATABASE.lock` at
boot, so the account can take the lock where `/run/lock` belongs to root.
Before writing anything, the script checks as that account that it can
run the interpreter and read the tool and the Odoo configuration. It
refuses to replace a file it did not write, and `--uninstall` keeps the
backups:

```bash
sudo ./script/systemd/install_backup_timer.py --db DATABASE --dry-run
sudo ./script/systemd/install_backup_timer.py --db DATABASE --copy-to backup@backup.example.org:/srv/backups
systemctl list-timers 'erplibre-backup-*'
sudo ./script/systemd/install_backup_timer.py --db DATABASE --uninstall
```

`--copy-to` adds an off-site copy (rsync over ssh with the account's key;
the remote side has no retention and grows). Monitor `--status`: it exits
with code 1 when the last success is older than `--max-age` hours (26).
All of it is also in `make todo`: `TODO › Execute › Production › Backups`
and `› systemd timers`. Details,
retention rules and exit codes:
[script/database/README.md](../script/database/README.md).

### Per-instance settings (profile)

Every production tool reads the lasting settings of an instance from one
JSON profile, `private/production/<unit>.json` of the tool's checkout
(`--profile FILE` names another one). It holds, per tool, the values its
command line would receive: `instance` (the database, shared),
`update_module`, `backup`, `backup_timer`, `log_check`, `mail_retry`,
`health_check` and `warmup`. The performance audit has a profile per
host, `private/production/host/local.json` or `host/pve-<target>.json`.
The directory is not versioned (`private/.gitignore`), and the file holds
no secret: a secret is a KeePass reference or an absolute path.

- The command line always wins: `--profile-unset NAME` drops one value,
  `--no-profile` ignores the file, `--profile-required` refuses to run
  without it. `--no-profile` makes the abbreviation `--no` ambiguous:
  spell options in full.
- Paths are absolute; the retention keeps at least one daily backup and
  two in all, `--max-age` stays at most 168 h; a journal pattern that
  matches any error line is refused.
- Under root, a profile that is a symbolic link, writable by its group or
  by all, or owned by another account, is refused (code 2).
- A value in conflict with the command line (`--namespace` with `--file`)
  is set aside with an ATTN, never an error.

`TODO › Execute › Production › Settings` edits it, as a Textual form or
line by line (`Production settings interface` in `TODO › Configuration`),
shows each value with its default and origin, checks it with this
checkout's tools before saving, previews how many backups a retention
change would delete, and offers to reinstall a timer whose unit uses the
profile when a value fixed at installation changes. A refused save returns
to the editor with every change kept; removing a secret deletes its
KeePass entry only when asked, once the profile is written.

Each command of the menu carries `--service` when the tool targets a unit
and `--profile <absolute path>`: the tool applies the profile itself, and
the simulation lists the values that come from it. Before a gesture that
writes, the question names the instance, the database and the profile
values that decide what is deleted, copied or ignored; the real run
carries `--profile-sha256`, refused when the profile changed since the
simulation.

```text
TODO › Execute › Production
🏭 Instance: <unit> · profile: private/production/<unit>.json (n value(s))
[1] Choose the instance
── Operate ──
[2] Update              update, simulate only, restart (with PostgreSQL),
                        apps list, zip archive, git rollback
[3] Backups             now, status, test restore, restore into a new database
[4] Journal and mail    Odoo errors (since the last check, last hours, per hour),
                        failed outgoing mail (list, retry)
[5] Health and warm-up  this instance, public URLs, deep warm-up
[6] Host audit          audit of this machine, its settings
── Configure ──
[7] systemd timers      status and credentials, install or update, remove
[8] Settings            edit, show, check, KeePass secrets, delete,
                        host audit settings
```

### Secrets and timers

A scheduled unit receives its secrets as systemd credentials, never on a
command line nor in the environment. The deployer (`--credential
NAME=PATH` of `install_backup_timer.py`) reads the file as root and
stores it according to the systemd version, checked before anything is
written. From the menu, todo checks this version itself, without sudo,
before asking for a secret:

- 250 and later, with `systemd-creds`: encrypted by `systemd-creds encrypt
  --with-key=host` (the secret on its standard input) into
  `/etc/credstore.encrypted/<unit>.<NAME>`, unit line
  `LoadCredentialEncrypted=`. A host key rather than the TPM, so that the
  file survives the migration or the restore of a VM; it is only readable
  with the host's `/var/lib/systemd/credential.secret`, so restoring
  `/etc` alone leaves the unit unable to start;
- 247 to 249, or without `systemd-creds`: in clear at rest, 0600 root in
  `/etc/credstore/<unit>.<NAME>`, unit line `LoadCredential=`, with a
  warning. Only a missing `systemd-creds` (code 127) leads here: any other
  failure of `systemd-creds --version` on 250+ is refused (code 2);
- before 247: refused (code 2).

The tool reads `$CREDENTIALS_DIRECTORY/<NAME>` first: inside the unit, the
credential wins over the file option and over the profile, the one
exception to "the command line wins". `warmup_http.py --deep` takes its
API key from the `warmup.api_key` credential this way, says where the key
comes from, and then also keeps the profile's `login`, even when the
profile only holds a KeePass reference.

A secret of the profile lives in KeePass, under
`ERPLibre/Production/<unit>/<name>`: `TODO › Execute › Production ›
Settings › Secrets in KeePass` asks for it with a hidden prompt, never in
the Textual form. For a run from the menu, todo writes it to a 0600 file
of a tmpfs (`$XDG_RUNTIME_DIR`, else `/dev/shm`; without either, the
secret is left out) and passes only its path. The file is removed when the
gesture ends, Ctrl-C and the retry under sudo included, and the leftovers
of a todo that no longer runs are purged when the Production menu opens. Without a KeePass file, todo asks
whether to continue without the authenticated warm-up, and the tool sets
the `login` aside.

The scheduled backup reads the instance profile at each run ("profile
mode": `--profile <path> --profile-required` in `ExecStart`) when its
account can read it and its checkout's tool supports it; otherwise every
value is written in `ExecStart` ("frozen mode") and a warning says that an
edit of the profile needs a reinstall. The database, the backup and state
directories, `--copy-to`, the calendar and the random delay are fixed at
installation either way: reinstall after changing them. Details:
[script/database/README.md](../script/database/README.md).

### Odoo journal

`script/odoo/log_check.py` reads the journal of the instance and says what
needs a look: Python tracebacks grouped by their final exception, other
`ERROR`/`CRITICAL` records, refused SQL queries, and mail sending failures
classified as transient or PERMANENT with the Odoo setting to check. It
reads the unit's `logfile` when its configuration sets one, otherwise
`journalctl` for the unit; `--file` reads any Odoo log file. Known harmless
messages are counted apart, and `--ignore REGEX` adds local ones.

```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --since-last --json
```

`--since-last` remembers where it stopped (journal cursor, or file inode
and offset) in `/var/lib/erplibre-logcheck/<unit>.json` (`--state-dir`),
only after a complete read; the first run covers the last 24 h. Without a
window option it reads the last 24 h. If the state folder is not writable
the report is still printed and says that the position was not saved; run
it with sudo, or point `--state-dir` to a folder the account can write. An
account in the `systemd-journal` (or `adm`) group reads the journal without
sudo; otherwise the tool exits with code 2 instead of reporting nothing.
Exit codes: 0 nothing to review, 1 something to review, 2 could not read.
It writes nothing but its state file. Details:
[script/odoo/README.md](../script/odoo/README.md).

### Failed outgoing mail

`script/odoo/mail_retry.py` lists the mails Odoo could not send in the last
`--days` (30), read-only, as the unit's account: date, subject, recipients
masked unless `--details`, and the cause, transient or PERMANENT. A
PERMANENT cause (authentication, sender, relay, TLS, invalid address) fails
again on resend until the named setting is fixed. Resending puts the chosen
mails back in the queue through the unit's Odoo shell and the ORM
(`action_retry`, or `state = outgoing` where that method does not exist);
the scheduled action "Mail: Email Queue Manager" sends them at its next
run.

```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
```

On a terminal, without `--resend`, a menu asks which ones to resend (all,
the oldest batch, chosen ids, none — the default). Without a terminal,
`--resend all | oldest N | ids LIST` needs `--yes`. Exit codes: 0 nothing
failed or every chosen mail requeued, 1 failures left or part of the
selection skipped, 2 refused or impossible. Both tools are in `make todo`:
`TODO › Execute › Production › Journal and mail`. Details and the Odoo 12
to 18 matrix:
[script/odoo/README.md](../script/odoo/README.md).

### Health check and cache warm-up

`script/odoo/health_check.py` checks, read-only, that an instance answers
and exposes nothing it should not. `--url https://host` probes through the
reverse proxy, as a browser would; `--local` probes the instance of the
detected systemd unit where Odoo listens. Each check says OK, ATTN, FAIL or
SKIP with a one-line hint: login page, `/web/health` (SKIP where the route
does not exist), TLS certificate (ATTN under 21 days, FAIL under 7),
HTTP to HTTPS redirect, HSTS, database manager and selector, bus path
behind the proxy (`/websocket` from Odoo 16, `/longpolling/poll` before),
robots.txt, and with `--mail-domain` the SPF, DMARC (and `--dkim-selector`
DKIM) records, read by `dig` or `host`. No credential, no cookie, no
third-party service.

```bash
./script/odoo/health_check.py --url https://odoo.example.org --mail-domain example.org
./script/odoo/health_check.py --local --json
./script/odoo/warmup_http.py --deep --local
```

A default deployment exposes the database manager: Odoo keeps
`list_db = True` when the configuration does not set it, and the nginx
templates do not block `/web/database`. The check rightly reports FAIL on
`--url`; set `list_db = False` in the Odoo configuration, or deny
`/web/database` in nginx. Exit codes: 0 no FAIL (ATTN are listed), 1 at
least one FAIL, 2 could not check (usage, detection, unreadable
configuration: run with sudo).

`script/odoo/warmup_http.py --deep` fetches `/web/login`, `/` and up to
`--max-pages` (20) pages of `/sitemap.xml`, then the asset bundles they
reference, each `--repeat` (4) times at once to reach several workers. With
`--login` and `--api-key-file` (an Odoo API key read from a file, never on
the command line), it also loads menus and views through read-only RPC
calls. It prints a summary and exits 0, or 1 with `--strict` when a request
failed. All three are in `make todo`: `TODO › Execute › Production ›
Health and warm-up`. Details and the Odoo 12 to 18 matrix:
[script/odoo/README.md](../script/odoo/README.md).

**Validate odoo.conf.** Odoo has no command that only checks its
configuration file, and configparser keeps a comment written after a value
inside the value: only a line that starts with `#` or `;` is a comment.
`script/odoo/odoo_conf_check.py` reads the file the unit uses (or
`--file PATH`) the way Odoo will read it at its next start, without
starting anything: repeated keys and sections, lines outside a section,
values of typed and choice options refused by optparse, comments after a
connection value, memory limits in bytes, soft
limit above the hard one, `gevent` limits, old option names, with the
types of the Odoo version of the checkout. It adds workers and memory
advice from the processors and memory of the machine. Exit codes: 0 no
error, 1 Odoo would refuse the file, 2 could not check. `health_check.py
--local` reports the same as `odoo_conf`, and it is in `make todo`: `TODO ›
Execute › Production › Health and warm-up › Validate odoo.conf`.

### Host performance audit

`script/proxmox/host_perf_audit.py` measures, read-only, what limits the
performance of the host — processor, memory, disks, network, ZFS and, on
Proxmox VE, each guest — over a chosen duration, and prints a verdict per
resource, the answer to "are SSD disks justified?" and the settings to
consider as commands, never run. It is in `make todo`:
`TODO › Execute › Production › Host audit` for this host, and the Proxmox
VE menu for the remembered hypervisor. The target is chosen first, then
its host profile (`private/production/host/local.json` or
`host/pve-<target>.json`) gives the default duration and the other
settings; a remote host does not have the file, so its values are sent as
validated options. `TODO › Execute › System › Performance audit of this
machine` runs the same audit of this host, with the same profile; next to
it, `TODO › Execute › System › System diagnostic` describes the machine at
one instant, and `TODO › Execute › System › Swap memory` applies the swap
and `vm.swappiness` settings that the audit only prints. Details:
[script/proxmox/README.md](../script/proxmox/README.md).

# Postgresql

To show config files:
> psql -U postgres -c 'SHOW config_file'

Edit this file to accept interface from all networks:
> /var/lib/postgres/data/postgresql.conf

# Delete an instance in production

CAUTION, this will delete user's home, it's irrevocable.

```bash
./script/database/delete_production.sh
```

# Update ip when public ip change with CloudFlare and crontab

First you need a valid python3 interpreter running with cloudflare module installed: (make sure your pip3 pointing the right python3)

```bash
pip3 install cloudflare==2.20.0
```

Then you need to create the cfg files with credentials for your cloudflare account.

```bash
mkdir ~/.cloudflare
```

Edit ~/.cloudflare/cloudflare.cfg

```
[PROFILE_NAME]
email=EMAIL
token=TOKEN (Use the global API key so that it works)
```

Add your cron and specify the python3 you want to use with it.
- USER is the local user with permissions to execute the script
- PATH is path to inside of ERPLibre/deployment/ folder
- PROFILE_NAME must match the PROFILE_NAME in cloudflare.cfg
- CLOUDFLARE_ZONE_NAME is the name of the website zone on cloudflare
- DNS_NAME is the name of one DNS A record name available on that zone

Notes:
- Only one crontab is required because the script will automatically research all available zones with outdated ip and update them on all A records.
- For each crontab run, if public IP did not change compared to what is on cloudflare, the script will not do unnecessary changes and let everything as is.

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync
```

Check log with

```bash
sudo journalctl -feu cron
```

If you want to log what is happening and when the script is run, like logging when ip changes, you can add a logging part to your cron

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync > /home/USER/logs/update_dns_ZONE_NAME.log 2>&1

```

You can then read all logs with this command (Need to have ts installed: sudo apt install moreutils)

```bash
tail -f /home/USER/logs/update_dns_ZONE_NAME.log | ts
```

# Docker

## Update

When update a docker, you need to update the list of module.

Run script to update configuration :

```bash
./script/docker/docker_gen_config.sh
```

Edit the docker-compose.yml and update the command line (change DATABASE) to :

```yaml
    command: odoo --workers 2 -u erplibre_info -d DATABASE
```

Note, the goal is to call `env['ir.module.module'].update_list()`.

Restart the docker :

```bash
docker compose down
docker compose up -d
```

Revert the command in docker-compose.yml.

You can validate in log the update, you need to find `odoo.modules.loading: updating modules list`, check

```bash
docker compose logs -f
```

## Update all

Do a backup on url https://HOST/web/database/manager

Edit the docker-compose.yml and update the command line (change DATABASE) to :

```yaml
    command: odoo --workers 2 -u all -d DATABASE
```

Watch log to see error, if you got error, you need to do some code to migrate your data, depend the case.

```bash
make docker_show_logs_live
```