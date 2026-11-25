
# Odoo instance tools

| File | What it does |
|------|--------------|
| `update_module.py` | updates installed modules of an instance run by systemd: stop, back up, update, restart, check |
| `log_check.py` | reads the journal of an instance: tracebacks, errors, refused SQL queries, mail sending failures, to review (read-only) |
| `mail_retry.py` | lists the failed outgoing mails of an instance (read-only), then requeues the chosen ones through the Odoo shell |
| `health_check.py` | checks that an instance answers and exposes nothing it should not: login page, `/web/health`, TLS, HTTPS redirect, HSTS, database manager, bus, robots.txt, mail DNS (read-only) |
| `warmup_http.py` | wakes the registry up as soon as the server listens; launched by `run.sh`. `--deep` warms up public pages, asset bundles and, with an API key, views |
| `odoo_conf_check.py` | checks an Odoo configuration file the way Odoo reads it at its next start: repeated keys, comment after a value, types per version, memory limits; workers and memory advice (read-only) |
| `migration/` | migration tools, see [migration/README.md](migration/README.md) |

## update_module.py

```bash
./script/odoo/update_module.py --module my_module_a --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db demo_db
sudo ./script/odoo/update_module.py --module my_module_a --i18n-overwrite
sudo ./script/odoo/update_module.py --restart-only --warmup-deep
sudo ./script/odoo/update_module.py --update-list
sudo ./script/odoo/update_module.py --remove-missing
sudo ./script/odoo/update_module.py --restart-only --restart-postgresql
sudo ./script/odoo/update_module.py --zip /var/tmp/modules.zip
sudo ./script/odoo/update_module.py --module my_module_a --rollback git
```

It is also reachable from `make todo`: `TODO › Execute › Production ›
Update`, which runs the simulation first and asks before the real run;
its entries 3 to 5 are the restart only, the apps list update and the
removal of the modules without code, 6 to 8 the restart of Odoo with
PostgreSQL, the update from a zip archive and the update with git
rollback.

What it does, in order:

1. **Detection, nothing stopped.** The unit is `--service`, else the
   `erplibre…`/`odoo…` unit whose `WorkingDirectory` is this checkout, else
   the only active one; a unit whose `ExecStart` does not launch Odoo
   (`run.sh`, `odoo-bin`, `odoo_bin.sh`, `odoo`), such as the backup
   timer's `erplibre-backup-<db>.service`, is never a candidate. Its account, directory, command line and
   environment come from `systemctl show`. The Odoo configuration, the
   database (`--db`, else `-d` of the unit, else `db_name`), the HTTP port
   and the modules (patterns expanded over `addons_path`, only folders with
   a `__manifest__.py`) are deduced from them. Anything missing refuses
   with code 2. The configuration is read again the way Odoo will read it
   at the restart (see `odoo_conf_check.py` below, types of the Odoo
   version of the unit's `.odoo-version`), before the database is looked
   up: a repeated key, a comment after a typed or connection value, a value
   optparse refuses or a memory limit written in MB refuses with code 2,
   since the stopped unit would not come back, or not serve. With
   `--odoo-conf`, the unit's own file, the one of the restart, is checked
   too. The warnings are listed in the plan. The installed modules of the
   database come from the backup's read, or from a read-only query with
   `--no-backup`: `-u` silently ignores a module the database has not
   installed, so each one is an ATTN, and the update is refused (code 2)
   when none of the requested modules is installed. A module in state
   `to upgrade` counts as installed: `-u` updates it. A state that cannot
   be read is shown as unknown and removes nothing.
2. **Root and lock.** Root is required (except `--dry-run`); one lock per
   database, shared with the backup tool, code 75 when another update or
   backup holds it.
3. **Stop.** The state before is read from `ActiveState`; without an
   answer from systemctl nothing is stopped (code 2). After `systemctl
   stop`, the unit must be `inactive` or `failed` (not `deactivating`).
   If the port still answers, if an Odoo process runs on the same database
   outside the unit — through its `-d`, or, for an `odoo-bin` server of
   root or of the unit's account, without `-d` with a configuration (`-c`)
   whose `db_name` is this database, or is empty without a `db_user` set to
   another role than this instance's (Odoo lists only the databases its
   role owns) —, or if PostgreSQL sessions are still connected
   to the database in `pg_stat_activity` after 10 s, the update is refused
   unless `--force`.
4. **Backup** (unless `--no-backup`), after the stop so that it is
   consistent: the verified backup of
   [script/database/odoo_backup.py](../database/README.md), called while
   the update already holds the database lock. It is written to
   `--backup-dest/<db>/` (default `/var/backups/erplibre`) and recorded in
   `--state-dir` (default `/var/lib/erplibre-backup`). Before anything is
   stopped, the detection checks that the unit's account can write there
   (missing folders are created for it), that the database can be read and
   that there is enough disk space; otherwise it refuses with code 2. It
   neither copies off-site nor applies retention: the scheduled backup
   does.
5. **Update**: the unit's command line followed by `-c CONFIG -d DB -u
   MODULES --stop-after-init --no-http --workers=0 --max-cron-threads=0
   --limit-memory-hard=0 --log-level=info`, then `--i18n-overwrite` when
   given (the translations of the modules' `.po` files
   replace those of the database, edited ones included), as the unit's
   account — the
   repeated `-c` keeps the update on the file the detection and the
   backup read (`--odoo-conf` included). Odoo keeps the last value of an
   option: the server's memory limit (2560 MiB by default) cannot stop a
   heavy update half-way, and its log keeps the INFO lines. It fails
   on a non-zero code, on `--timeout`, or on an
   `ERROR`/`CRITICAL` record in its output or in what was appended to the
   configured `logfile`. A record is the header line and its continuation
   lines (a traceback); the report groups tracebacks by their final
   exception, like `log_check.py`. `--ignore-error REGEX`, searched in the
   header line and in the final exception, excludes known records.
6. **Restart**, if the unit was running: wait for `active` and the port
   (`--start-wait`), one HTTP request, then the unit's journal and the
   `logfile` are read since the start.
7. **After a verified restart**, lock released: with `--warmup-deep`, the
   deep warm-up of `warmup_http.py` (public pages and asset bundles; with
   `--warmup-login` and `--warmup-key-file`, the read-only views too, the
   key read before anything is stopped — an unreadable file refuses with
   code 2 — and sent only to the loopback address, when root or the
   unit's account alone listens on the port), then the health check of the local instance (`health_check.py`),
   then a second read of the unit's journal and of the `logfile` since the
   same start, after 2 s for journald: an error raised by the first
   rendering of an updated view shows only then. Their findings are
   printed as ATTN at most and never change the exit code; Ctrl-C there
   only stops that step.
8. **End of the report**: the duration of each phase (stop, backup,
   update, start, first answer, warm-up, health check), then how long the
   site stayed down, from the stop to the first HTTP answer below 500,
   then, after a success, the version table: the installed modules read
   before the update (by the detection, else just before `-u`) and again
   after the restart, with one line per module updated, newly installed
   or no longer installed, and the count of unchanged ones.

**Restart only.** `--restart-only` (no `--module`) restarts the unit with
the guards of an update: lock, verified stop, refusal when an Odoo still
holds the database or the port outside the unit (unless `--force`),
verified start, warm-up, health check and journal. No `-u`, no backup, no
update log; the PostgreSQL sessions are not waited for, they only matter
to a `-u`. A unit that was stopped is started.

**Apps list.** `--update-list` (no `--module`) does what Apps › Update Apps
List does, Odoo left running: an `odoo shell` built from the unit's
`ExecStart` — `./odoo_bin.sh shell` behind `run.sh`, `shell` right after
`odoo-bin` otherwise, the unit's options such as `--addons-path` kept and
its database removed, then `-c CONFIG -d DB --no-http --workers=0
--max-cron-threads=0` — runs as the unit's account and reads a script on
its standard input: `update_list()`, commit, then the modules not
installed whose code is missing from that addons_path, and the installed
ones in that case (an ATTN, never removed). The database lock is held,
`--timeout` bounds each shell, and the shell's output goes to the update
log. An `ExecStart` that names no launcher, or a missing `odoo_bin.sh`,
refuses with code 2. `--remove-missing` implies it: after a backup (unless
`--no-backup`) and a `[y/N]` question on the terminal, or `--yes`, a
second shell removes the modules of the first pass that are still
`uninstalled` or `uninstallable` and still without code, with their
`base.module_<name>` record, then commits. Without a terminal and without
`--yes`, nothing is removed (code 1). `--dry-run` shows the shell, its
script and the planned steps without running any shell.

**PostgreSQL restart.** `--restart-postgresql`, with an update or
`--restart-only` (not with the apps list, Odoo keeps running there), also
restarts the PostgreSQL server while Odoo is stopped: after the checks
of the stop, before the backup. The unit is `--pg-service`, else the only
active unit of a cluster or version (`postgresql@<version>-<cluster>`,
`postgresql-<version>`), else `postgresql.service`; several active
clusters, or a `db_host` on another host, refuse with code 2. Every
database of the server loses its sessions: before anything is stopped
their sessions are read and listed, then a `[y/N]` question on the
terminal recalls them (`--yes` skips it). Without a terminal and without
`--yes`, another database with sessions, or sessions that cannot be read,
refuse with code 2; the instance's own sessions alone do not, and they
are read again just before the restart: another database connected
meanwhile skips it (code 1). `--pg-service`, from the command line or the
profile, must name a PostgreSQL unit, never the instance's: any other
name refuses with code 2. After `systemctl restart`, the tool waits for
`pg_isready` (else `SELECT 1`), `--start-wait` seconds at most; a restart
or a wait that fails and leaves the unit `inactive` or `failed` gets one
`systemctl start` and the same wait. A PostgreSQL failure gives code 1,
no `-u`, and the Odoo unit is restarted all the same.

**Zip archive.** `--zip ARCHIVE` brings the code, for servers without
git. The archive is inspected before anything is stopped: an absolute
path, `..`, a backslash, a symbolic link, a special file, a name used
twice, a file at its root or a root folder that is not a module (technical
name and `__manifest__.py`) refuse with code 2. Each module folder of the
archive replaces, as a whole, the one of the addons directory:
`--addons-dir`, else the first `addons_path` directory that already holds
one of its modules; a module of the archive found earlier in the
`addons_path` refuses (Odoo would load that code). The space for the
extraction and for the copy is checked before the stop, with the backup
and the rollback, summed by file system. After the backup,
a tar.gz copy of the replaced folders is written next to it
(`code-<db>-<timestamp>.tar.gz`), then the archive is extracted, both as
the unit's account. Without `--module`, the modules of the archive are
updated.

**Git rollback.** `--rollback git` notes HEAD of each git repository that
holds an `addons_path` directory under the unit's working directory (that
directory itself excluded: it carries the tools). The reference to come
back to is the one of the last successful update with `--rollback git`,
recorded in `<state-dir>/<db>/git_heads.json` with a stamp of the
modules of the database (`ir_module_module`); without it, or when the
modules changed since (another update, the apps list), the HEAD read
before the stop, and a rollback then restores the database only. A
repository that must move back and has modified tracked files, or lacks
the reference commit, refuses before the stop.

**Rollback.** With `--zip` or `--rollback git`, when `-u` fails
(interruption included), or when the restart after a successful `-u`
fails (the unit is then stopped again), the database is restored from
the verified backup of this run: loaded into a copy
`<db>_rollback_<timestamp>` (the checksum, the space and the load checked
as by `odoo_backup.py --restore`), which then takes the place of the
database by renaming, filestore included. Before the renaming, the
database is closed to connections and its sessions are ended. Then only
the code is put back — the tar copy, or `git checkout --detach` of the
reference in each repository that moved, branches left where they are:
when the database cannot be restored, the code of the update stays, the
one that matches the database it left. The database left by the update
stays as `<db>_failed_<timestamp>`, closed to connections (Odoo does not
list it, its crons do not run), to drop once examined. What the rollback
needs is checked before the stop: the space for the copy in the data
directory of PostgreSQL, which must be readable, and the CREATEDB right
of the role; a lack refuses with code 2. The exit code stays 1.
`--no-backup` is refused with both options.

The unit is never modified: the tool only reads it and runs `systemctl
stop` / `start` (and `restart` of the PostgreSQL unit with
`--restart-postgresql`). Whatever happens after the stop — failure,
exception, Ctrl-C, SIGTERM — a unit that was running is restarted.
Without `--zip` or `--rollback git`, nothing is restored: the backup is
there for a restore decided by a person.

| Code | Meaning |
|------|---------|
| 0 | success (or simulation) |
| 1 | update, restart or apps list failed, service restarted |
| 2 | refused before anything was stopped |
| 75 | another update or backup of this database is running |
| 130 | interrupted, service restarted |

The update log goes to `--log-dir` (default `/var/log/erplibre`, falling
back to the temporary directory). After each real run, the logs `update-<db>-<timestamp>.log` of the database older than
`--log-keep-days` days (default 180, 0 keeps them all) are removed from
that folder; the 10 most recent always stay, and a symbolic link is never
removed.

**Profile.** The lasting settings of an instance come from its production
profile: `--profile FILE`, else `private/production/<unit>.json` of this
checkout (the unit given by `--service`, else the detected one). The tool
reads its group `update_module` (`timeout`, `start_wait`, `ignore_error`,
`log_dir`, `log_keep_days`, `warmup_deep`, `verbose`, `rollback`,
`pg_service`), plus `instance.db`, `backup.dest`,
`backup.state_dir`, `warmup.login` and `warmup.api_key_file` (for
`--warmup-login` and `--warmup-key-file`). Paths must be absolute, and an `ignore_error` pattern
that matches any error line or any traceback title (`ValueError: …`) is
refused (code 2). The command line wins over every value,
`--profile-unset NAME` drops one, `--no-profile` ignores the file. A
profile found through the unit that this account cannot open is ignored
with an ATTN; given by `--profile`, or with `--profile-required`, it is
refused. The modules, the unit, the account, the configuration, the
actions (`--restart-only`, `--update-list`, `--remove-missing`,
`--i18n-overwrite`, `--restart-postgresql`), the archive and its folder
(`--zip`, `--addons-dir`), `--force`, `--no-backup`, `--yes` and
`--dry-run` are never read from it: such a key is ignored with an ATTN.
A `rollback` from the profile is set aside, with an ATTN, under
`--restart-only`, `--update-list`, `--remove-missing`, `--zip` and
`--no-backup`. The plan lists each value taken from the
profile, one line per `--ignore-error` pattern, before any simulated
command.

`--no-profile` makes the abbreviation `--no` ambiguous: argparse refuses
it, so spell `--no-backup` in full.

Of the profile group `warmup`, `--warmup-deep` reads only the login and
the API key: the key is a KeePass reference that `TODO › Execute ›
Production` hands over as a 0600 file, an absolute path, or the unit's
`warmup.api_key` credential; a KeePass reference unreachable here drops
the login with it. The pages and the other warm-up settings keep their
defaults, and the health check does not read `health_check.timeout`.

## log_check.py

```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --since "2026-03-01 08:00" --until "2026-03-01 12:00"
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --file /var/log/odoo/odoo.log --json
```

**Source.** The unit is `--service`, else detected like `update_module.py`.
When its configuration sets a `logfile`, Odoo writes there and that file is
read; otherwise `journalctl -u UNIT -o short-iso`, streamed with an overall
`--timeout`. A unit with `LogNamespace=` writes to the journal of that
namespace, which `journalctl -u` alone does not see: the property is read
from `systemctl show` and passed as `--namespace=NAME`; `--namespace NAME`
replaces it. `--file` reads a given file without a unit. When the account
cannot read the configuration, a `--logfile` on ExecStart is read if there
is one, otherwise the journal; a journal read that yields no Odoo record then
refuses (code 2, advising sudo) instead of reporting nothing to review.

**Window.** `--since-last` resumes after the last read: the journal cursor
(`--after-cursor`), or the byte offset of a file that kept its inode and did
not shrink (otherwise it is read from the start, and the report says so);
the first run reads the last 24 h. `--last HOURS`, `--since`/`--until`
(local time) and `--by-hour --days N` (default 7, adds the hour × day
matrix) never touch the state. Without a window option: the last 24 h.

**State.** `--state-dir/<unit>.json` (default `/var/lib/erplibre-logcheck`),
`<unit>+<namespace>.json` for the journal of a namespace, so that two
journals never share a cursor; a cursor saved for another namespace is not
used. It is written only after a complete and successful read, through a temporary file
and a rename; a state that is a symbolic link is neither read nor replaced.
When the folder is not writable the report is still printed and says
"position not saved".

**Report.** (1) Python tracebacks grouped by their final exception line,
with count, first and last time and one sample (`--full-trace` shows all of
it); (2) other `ERROR`/`CRITICAL` records grouped by logger and normalised
message; (3) refused SQL queries (`odoo.sql_db: bad query`) by table and
PostgreSQL reason; (4) mail sending failures classified as transient or
PERMANENT with the Odoo setting to check; (5) known noise counted apart:
outdated asset source maps, serialization conflicts that Odoo retries,
outdated VAPID push subscriptions, plus `--ignore REGEX` (searched in the
header line and the final exception, never in traceback frames). Only
`ERROR` and `CRITICAL` are "to review". Times are local. `--json` prints a
summary with stable English keys; `update_module.py` uses the same parser.

**Profile.** The `log_check` group of a production profile
(`private/production/<unit>.json`, or `--profile FILE`) gives the defaults of
`--namespace`, `--days`, `--ignore`, `--state-dir` (absolute path),
`--full-trace`, `--top`, `--timeout` and `--verbose`. The profile of the
unit named by `--service`, or of the detected unit, is read; `--file` reads
no unit profile, and sets aside the `namespace` of an explicit one. The
command line always wins: an `--ignore` typed replaces the profile patterns
instead of adding to them. `--no-profile` ignores the profile,
`--profile-unset top` drops one value. The window, `--file`, `--until` and
`--json` are never read from a profile. The text report names the profile
and lists each value it took, marked "(profile)"; `--json` adds a `profile`
key (`path`, `values`, `ignored`) and prints the warnings on stderr.

It never writes anything but its state file and reads no database. Root is
not required when the account belongs to `systemd-journal` (or `adm`);
otherwise journalctl only shows the account's own messages, which is
detected and reported with code 2 and the advice to use sudo.

| Code | Meaning |
|------|---------|
| 0 | nothing to review |
| 1 | something to review |
| 2 | could not read (rights, unit, file, options) |
| 130 | interrupted |

## mail_retry.py

```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
sudo ./script/odoo/mail_retry.py --resend ids 7404,7405 --yes --json
```

**List, read-only.** One `psql` query as the unit's account, with the
connection settings of its Odoo configuration passed through the
environment and a read-only transaction forced by `PGOPTIONS`: the
`mail.mail` in state `exception` created in the last `--days` (30), oldest
first, with date, subject, recipients masked by default (`j***@example.org`,
a display name reduced to its initial; `--details` shows everything) and the
failure cause, transient or PERMANENT, whose addresses are masked the same
way, in the text as in `--json`. Then totals by subject, cause and
day, and the warnings: a PERMANENT cause fails again until the named setting
is fixed. A refusal by the SMTP server's per-session message limit (452
4.4.5, then 503 Multiple MAIL) gives the largest recipient group of those
mails ("at least N" when a 300-character recipient list is cut) and the
value of `mail.session.batch.size`: one session carries up to that many
mails (1000 when unset) and one message per recipient of each, so the server
counts the sum. Lower `mail.session.batch.size` so that it times the largest
group stays under the limit, or raise the server limit when one mail's group
alone exceeds it; a resend before that fails again and may deliver twice to
the first recipients. More than 10 mails with `mail.session.batch.size`
unset or above 20 may hit the same limit.

**Resend, through the ORM.** `--resend all | oldest N | ids LIST` with
`--yes` (without a terminal, nothing is resent without it); on a terminal
without `--resend`, a menu: `[a]ll`, `[o]ldest batch`, `[i]ds`, `[n]one`
(default). `--list` only lists. The unit's Odoo shell, built from its
`ExecStart` as `update_module.py --update-list` builds it (its options,
`--addons-path` included, kept), runs as its account in its working
directory with a short script on its standard input:
it re-reads the mails still in `exception`, calls `action_retry()` when the
method exists, else `write({'state': 'outgoing'})`, commits, and prints its
result as JSON. The scheduled action "Mail: Email Queue Manager" then sends
the queue. No SQL write is ever made. `--dry-run` shows the selection and
the exact command and script. Beyond `--timeout`, the shell's whole process
group is stopped; a commit may have happened just before, so the tool says
the outcome is unknown and the list must be read again.

**Profile.** `--days`, `--timeout`, `--verbose` and the database can come
from the instance's JSON profile, `private/production/<service>.json`
(group `mail_retry`, database in `instance.db`), or from `--profile FILE`;
the command line always wins, `--profile-unset days` drops one value and
`--no-profile` ignores the file. `--details`, `--resend`, `--yes`,
`--list`, `--dry-run` and `--json` are never read from it: a profile key
naming one of them is ignored with an ATTN. With `--resend`, the profile's
`days` is set aside: a resend selects from the list of the default window
or of a `--days` typed on the command line. The text output lists each value
taken from the profile (`--days 14 (profile)`) before any command; `--json`
adds a `"profile"` key (path, raw values, ignored keys) and prints the
warnings on stderr.

```json
{"version": 1, "service": "odoo-exemple.service",
 "instance": {"db": "exemple_db"}, "mail_retry": {"days": 14}}
```

Root is only needed to become the unit's account.

| Code | Meaning |
|------|---------|
| 0 | no failed mail, or every chosen mail requeued |
| 1 | failed mails listed and not resent, or part of the selection skipped |
| 2 | refused or impossible (detection, rights, psql, no answer from the shell) |
| 130 | interrupted |

### Odoo 12 to 18

| Point | Variation |
|-------|-----------|
| Log line | `date time,ms pid LEVEL db logger: message`, with a trailing `perf_info` from 13; db `?` outside a request; header time in UTC |
| `mail.mail.failure_type` | present in 18; not checked in 12 to 17; read without branching (`to_jsonb(m)->>'failure_type'`), the text decides when it is missing |
| `mail.mail.action_retry()` | checked in 18 only; fallback `write({'state': 'outgoing'})` |
| From filter (`from_filter`) | 15+; named in the sender advice from 15 |
| Alias domains (default from, catchall) | 17+; `mail.default.from` and `mail.catchall.domain` system parameters up to 16 |
| `mail.session.batch.size` | present in 18; not checked in 12 to 14 |

## health_check.py

```bash
./script/odoo/health_check.py --url https://odoo.example.org
./script/odoo/health_check.py --url odoo.example.org --mail-domain example.org --dkim-selector s1
./script/odoo/health_check.py --local --json
```

It checks one Odoo instance, served by systemd or published at a URL. It
is not the TODO **Healthcheck** (its own main-menu entry, `TODO ›
Healthcheck`), which checks the ERPLibre checkout — repositories, venvs, hooks — and touches no
instance. In `make todo`: `TODO › Execute › Production › Health and
warm-up`.

`--url` (repeatable; a bare host means `https://host`) probes through the
reverse proxy; `--local` (with `--service`, else the detected unit) probes
the address the unit's configuration gives, with `?db=` when the database is
known. A URL with credentials (`user:pw@`) or a scheme other than http(s) is
refused. Read-only: GET requests, plus one unauthenticated JSON-RPC call to
`/web/webclient/version_info` for the version. No cookie, no
`Authorization` header, no proxy from the environment, bodies read up to
1 MiB, `--timeout` (10 s) on every request, TLS connection and DNS lookup.

| Check | OK | ATTN | FAIL | SKIP |
|-------|----|------|------|------|
| `http_login` | 200 within 5 s | slow, redirect to the database selector, to plain HTTP or another host | no answer, 5xx, other status | |
| `web_health` | 200 `pass` | unexpected answer | no answer, 5xx, `fail` | 404 (route absent) |
| `tls_certificate` | 21 days or more | under 21 days | under 7 days, expired, refused (name, chain, self-signed) | http URL, `--local` |
| `http_redirect` | `http://host/` redirects to https on the same host | other host, port 80 closed, other status | served in clear text | http URL, `--local` |
| `hsts` | `max-age` ≥ 1 day | missing, shorter | | no 200 on `/web/login`, http URL, `--local` |
| `db_manager`, `db_selector` | blocked (401/403/404/3xx), disabled page (`list_db = False`) | undetermined (5xx); exposed on `--local`; selector listing databases | manager reachable, or master password not set, on `--url` | |
| `list_db` (`--local`) | `False` | absent or true | | |
| `odoo_conf` (`--local`) | read without error | a warning (comment after a text value, soft above hard limit, old name) | Odoo refuses the file at its next start, or cannot serve with it | |
| `websocket` (`--url`) | forwarded (400/426) | 404, no answer | 502/503/504 | `--local` |
| `robots` (`--url`) | served, or `Disallow: /` without a `Sitemap:` line (no public website) | `Disallow: /` with a `Sitemap:` line (the URL used is not the website domain) | | 404 |
| `mail_spf` | one record ending in `-all`/`~all` | other ending | none, several, `+all` | no dig/host, lookup failed |
| `mail_dmarc` | present (policy shown) | absent | | no dig/host, lookup failed |
| `mail_dkim` (`--dkim-selector`) | key found | | absent, empty key | no dig/host, lookup failed |

The certificate is judged by `tls_certificate` only: the other HTTPS
requests do not verify it, so that a refused certificate gives one FAIL and
the other checks still answer. A plain-HTTP `--url` adds an `https` ATTN.
DNS goes through `dig` or `host`, the domain and selector validated first
(no leading `-`); a failed lookup is a SKIP, never "record absent". dig
exits 0 on any answer, SERVFAIL and REFUSED included: the status of its
answer header decides, and only NOERROR and NXDOMAIN are definite. No
third-party web service is contacted.

A default deployment gets FAIL on `db_manager` through `--url`: Odoo keeps
`list_db = True` when the configuration does not set it, and the nginx
templates do not block `/web/database`. Set `list_db = False`, or deny
`/web/database` in nginx.

The `hsts` hint points to `script/nginx/template_nginx_ssl_odoo_18.0.txt`,
the repository's nginx template for Odoo 18, whose locations send the
header.

`--json` keys (English, stable): `tool`, `odoo_version`, `targets` (`kind`,
`url`, `odoo_version`), `checks` (`id`, `target`, `status`, `message`,
`hint`, `data`), `summary` (`ok`, `attn`, `fail`, `skip`), `exit_code`.

**Profile.** The `health_check` group of a production profile gives
`--url` (a list), `--mail-domain`, `--dkim-selector`, `--timeout` and
`--verbose`. With `--local`, the profile of the unit named by `--service`,
or of the detected unit, is read; without `--local`, only `--profile FILE`
brings one, whose URLs are probed without naming a service. A
`dkim_selector` without an effective `mail_domain` is set aside with an
ATTN. The command line always wins: a `--url` typed replaces the whole list
of the profile. `--no-profile` ignores the profile, `--profile-unset url`
drops one value. `--local`, `--service` and `--json` are never read from a
profile. The text report names the profile and lists each value it took,
marked "(profile)", before the first probe; `--json` adds a `profile` key
(`path`, `values`, `ignored`) and prints the warnings on stderr.

| Code | Meaning |
|------|---------|
| 0 | no FAIL (ATTN are listed) |
| 1 | at least one FAIL |
| 2 | could not check (usage, detection, unreadable configuration: run with sudo) |
| 130 | interrupted |

## odoo_conf_check.py

```bash
./script/odoo/odoo_conf_check.py
./script/odoo/odoo_conf_check.py --file /etc/odoo/odoo.conf --odoo-version 16
./script/odoo/odoo_conf_check.py --service odoo-exemple --json
```

Odoo has no command that only checks its configuration file: an error
shows when it starts, that is after a `systemctl stop`. This tool reads
the file of `--file`, else the one the systemd unit reads (`--service`,
else the detected unit, as `update_module.py` finds it), with Odoo's own
rules, and changes nothing. In `make todo`: `TODO › Execute › Production ›
Health and warm-up › Validate odoo.conf`.

| Level | Finding |
|-------|---------|
| error | key or section given twice, line outside any section or without `=` (strict `configparser` refuses the whole file); a typed option (`workers`, ports, `limit_*`…) or a choice option (`log_level`, `db_sslmode`) whose value optparse refuses, a comment after it included (`workers = 4 # four` keeps `# four` in the value); a comment after a connection or listening value (`db_host`, `db_user`, `db_name`, `db_replica_host`, `http_interface`), passed as is to PostgreSQL or to the socket; a memory limit under 100000 (bytes, meant as MB) |
| warning | no `[options]` section (Odoo starts with its defaults); comment after another text value; `limit_memory_soft` above `limit_memory_hard`; `limit_memory_soft` under 1024 MB with workers (16 and later); `longpolling_port` from 17 (ignored, the bus listens on `gevent_port`); an old name (`xmlrpc_port`) and its new name both set to different values; too many workers for the processors, or for the memory |
| info | old name (`xmlrpc_port`, read as `http_port`); `gevent` limits unset (18); `workers = 0`; suggested `limit_memory_soft`/`limit_memory_hard` |

Only a line that STARTS with `#` or `;` is a comment. `True`/`true` and
`False`/`false` are booleans; any other value of a typed option goes
through optparse (`0x10` and `-1` pass, `08` and `2048MB` do not). The
value of a key that looks like a secret (`admin_passwd`, `db_password`,
`sentry_dsn`…) is never quoted, nor the account and password of an
address (`scheme://account:password@host`) whatever the key.

The types follow the Odoo version: `--odoo-version`, else the
`.odoo-version` of the unit's directory (or of the file's directory with
`--file`), else an `odooNN.0` path in the unit's command line; unknown,
only the types common to 12 to 18 are checked. The workers and memory
advice follows the Odoo deployment guide — at most (2 × CPU) + 1 workers,
150 MB per light worker and 1 GiB per heavy one — with the processors and
memory of `--cpus` and `--memory-mb`, else of this machine (cgroup limits
are not read). The suggested limits keep 15 % of the memory for the rest
of the machine and a 10 % margin, and never put `limit_memory_soft` under
1050 MB.

The same validation runs in `update_module.py` before anything is stopped
(errors refuse, code 2) and in `health_check.py --local` (result
`odoo_conf`).

**Profile.** The `odoo_conf` group gives `--cpus`, `--memory-mb` and
`--verbose`. `--file`, `--service`, `--odoo-version` and `--json` are
never read from a profile. With `--file`, the unit is not guessed: only
`--profile` brings a profile.

`--json` keys (English, stable): `tool`, `service`, `path`,
`odoo_version`, `findings` (`level`, `line`, `key`, `code`, `message`),
`summary` (`error`, `warning`, `info`), `host` (`cpus`, `memory_mb`),
`exit_code`.

| Code | Meaning |
|------|---------|
| 0 | no error (warnings are listed) |
| 1 | at least one error: Odoo refuses the file at its next start, or cannot serve with it |
| 2 | could not check (usage, detection, unreadable file: run with sudo) |
| 130 | interrupted |

## warmup_http.py --deep

```bash
./script/odoo/warmup_http.py --deep --local
./script/odoo/warmup_http.py --deep --url https://odoo.example.org -d DATABASE --max-pages 50
./script/odoo/warmup_http.py --deep --local --login admin --api-key-file ~/.odoo_key --models res.partner,sale.order
```

Without `--deep`, nothing changes: one line, silent with `--quiet`, always
exit 0, unknown options passed to Odoo; `--deep` after `--` belongs to Odoo.
With `--deep`: wait for the first answer (`--timeout`, 120 s), then work
through `--repeat` (4, at most 16) lanes, each with its own cookies and its
own session opened on `/web/login?db=BASE`: two requests of one session
never run at once (Odoo 16+ keys an anonymous visitor on the IP, the
User-Agent and the session, and simultaneous requests of one session would
upsert the same `website_visitor` row, logged as ERROR). Fetch
`/web/login`, `/` and up to `--max-pages` (20) HTML pages of
`/sitemap.xml` (an index is followed one level; only the path of each
`<loc>` is kept, the request goes to the target), then each asset bundle
those pages reference (`/web/assets/…`, and `/web/content/…assets_…` in
older versions). Each page or bundle is fetched once alone by the first
lane — that first render compiles the templates or builds the bundle —,
then once by each other lane, at the same time; what fails on the first
request is not repeated. With `--login` and `--api-key-file`:
`common.login` through `/jsonrpc` with the API key (Odoo accepts a key only
outside an interactive login), then `execute_kw` of a closed list of
read-only methods, each once per lane at the same time:
`res.users.context_get`, `ir.ui.menu.load_menus` and, for each model of
`--models` (`res.partner`), `get_views` (16+) or `load_views` (15 and
before). The key file is read without following a link; a file readable by
other accounts gets a warning. The key leaves only over https, or over
http to the loopback (`--local`, the default-mode address): `--login` with
an `http://` URL on another host is refused (code 2). The target is
`--url`, `--local` (detected unit) or the default-mode address. A sitemap
`<loc>` that is neither an absolute URL nor a path starting with `/` is
ignored: only its path is sent, to the target.

**Profile** (`--deep` only). The `warmup` group of a production profile
(`private/production/<unit>.json`, or `--profile FILE`) gives the defaults
of `--timeout`, `--max-pages`, `--repeat`, `--login`, `--api-key-file`
(absolute path; a KeePass reference `{"kdbx": …}` is never read by the
tool), `--models` (commas, as on the command line) and `--strict`; the
database comes from `instance.db`. The profile of the unit is read with
`--local` only: named by `--service`, or the detected unit, guessed once
for both the profile and the target. With an explicit `--profile` and
`--local`, the unit is the profile's `service`; `--url` and the
default-mode address read no unit profile. `--login` and
`--api-key-file` go together: one without the other is set aside, as is
`--login` when the API key is a KeePass reference. The target (`--url`, `--local`),
`--service` and the options of the default mode (`-c`, `--log`,
`--quiet`, Odoo arguments) never come from a profile. The command line
always wins, `--profile-unset repeat` drops one value, `--no-profile`
ignores the file. A line `🔧 profile: <path> (<n>)` comes first, then
each value taken, marked "(profile)", and one `[ATTN]` per value set
aside. **The default mode (the one of `run.sh`) never reads a profile**:
it stays silent and always exits 0, even next to an invalid profile.

A request fails on no answer or a code ≥ 500, and on a JSON-RPC error; a
4xx is counted apart as "not public". No request, the default-mode probe
included, goes through the proxy of the environment (`http_proxy`).

| Code | Meaning |
|------|---------|
| 0 | done, failures included |
| 1 | with `--strict`, at least one failure |
| 2 | invalid option, unreadable key file, no database with `--login`, invalid profile |
| 130 | interrupted |

### Odoo 12 to 18 (health check, warm-up)

| Point | Variation |
|-------|-----------|
| `/web/health` | 18: present, `db_server_status=1` checks PostgreSQL; 16 and 17: present (not checked); 12 to 15: absent, SKIP |
| Bus path behind the proxy | `/websocket` from 16 (checked in 18); `/longpolling/poll` up to 15; an unknown version tries both |
| Web client URL | `/odoo` in 18, `/web` redirects to it; `/web` up to 17 |
| View loading by RPC | `get_views` from 16, `load_views` up to 15; list view type `list` in 18, `tree` before |
| API key with `common.login` | 14+ (non-interactive only); none in 12 and 13 |
| `/robots.txt` | without website, 18: `Disallow: /` plus `Allow:` lines, 404 up to 17 (not checked); with website: a `Sitemap:` line, and `Disallow: /` when the URL is not the website domain (checked in 18) |
| Database manager with `list_db = False` | 18: 200 with the "disabled" page (read, not just the status); not checked in 12 to 17, a 403 is handled too |
| ERPLibre nginx templates | no HSTS for 12 to 15; HSTS in `location /` from 16; none blocks `/web/database` |
| Typed options of `odoo.conf` (`odoo_conf_check.py`) | common to 12 to 18: `http_port`, `db_port`, `smtp_port`, `workers`, `max_cron_threads`, `limit_memory_soft`/`hard`, `limit_time_*`, `limit_request`, `db_maxconn`; `longpolling_port` 12 to 16, ignored from 17; `gevent_port` from 16; `osv_memory_age_limit` up to 17; `transient_age_limit` from 14; the `gevent` memory limits, `db_replica_port`, `db_maxconn_gevent` and `limit_time_worker_cron` in 18 |
