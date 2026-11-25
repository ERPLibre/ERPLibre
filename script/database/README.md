
# Database

This section is for code generator database migrator.

This configuration is for development environnement.

You need to install script `./script/install/install_dev_extra_ubuntu.sh`.

## Restore database

Run script to restore database:

```bash
./script/database/restore_mariadb_sql_example_1.sh
```

## Production backup: odoo_backup.py

`odoo_backup.py` takes verified backups of an Odoo database run by systemd,
in Odoo's own zip format (`dump.sql`, `manifest.json`, `filestore/`), the
one `/web/database/manager` restores as is. It also reports their age,
test-restores them into a temporary database, and restores one into a new
database. It needs neither the Odoo venv nor `list_db`. In `make todo`:
`TODO › Execute › Production › Backups` (now, status, test restore,
restore into a new database, test restore of a file) and `TODO › Execute › Production › systemd
timers` for the scheduled backup.

```bash
./script/database/odoo_backup.py --dry-run
sudo ./script/database/odoo_backup.py --db demo_db
./script/database/odoo_backup.py --status
sudo ./script/database/odoo_backup.py --test-restore --db demo_db
sudo ./script/database/odoo_backup.py --restore --file /var/backups/erplibre/demo_db/demo_db_2031-03-10_03h00m00s.zip --into demo_copy
```

**Detection.** As for `script/odoo/update_module.py`: the unit
(`--service`, else the one whose `WorkingDirectory` is this checkout, else
the only active one), its account, its Odoo configuration, the database
(`--db`, else `-d` of the unit, else `db_name`) and its data directory, in
Odoo's order: `-D`/`--data-dir` of the unit, `data_dir` of the
configuration (`~` is the account's home, a relative path starts from the
unit's directory), `XDG_DATA_HOME` of the unit, then
`~account/.local/share/Odoo`.

**Account.** `pg_dump`, `psql`, `createdb` and `dropdb` run as the unit's
account: directly when it is the current account, through `runuser` as
root. Any other account is refused (code 2), except with `--dry-run` and
`--status`. `--dry-run` needs no sudo: a folder that only root can create
is shown as the `sudo mkdir` the real run will do. As root, every file in
a folder the unit's account owns is created, given away and read through
its open descriptor, never by a path the account could swap for a
symbolic link. The connection is Odoo's (`db_host`, `db_port`, `db_user`,
`db_password`, `db_sslmode`; tools found in `pg_path` when set), passed
through the environment: the password never appears on a command line nor
in the output.

**Backup.** The free space is checked before anything is written:
`(database size + filestore) × 1.2`. `pg_dump --no-owner` is streamed
straight into the zip, the filestore is read after the dump, regular files
only (a symbolic link is skipped and reported, even one swapped in during
the read); as root, the filestore folder must belong to the unit's
account. The zip is written as
`<name>.partial`, read back in full (CRC of every member, pg_dump end
marker, readable manifest), synced, then renamed to
`<dest>/<db>/<db>_<YYYY-MM-DD>_<HH>h<MM>m<SS>s.zip`, with a `.sha256`
next to it (`sha256sum -c` format). Files are 0600 and the database folder
0700, owned by the unit's account. A missing filestore is a warning when
the database stores no attachment on disk, a failure otherwise. The
backup takes the database lock, the same as `update_module.py`: a backup
never runs during an update.

**Retention**, after a successful backup and only on the tool's own file
names for this database: the newest backup of each of the last
`--keep-daily` days (7), `--keep-weekly` ISO weeks (4) and
`--keep-monthly` months (12) that have one, plus everything from the last
`--keep-recent-days` days (2), so that a backup taken before an update
survives the scheduled one of the same day. The newest backup is never
deleted; a gap in backups never deletes everything.

**State.** Each database has `<state-dir>/<db>/state.json` (default
`/var/lib/erplibre-backup`): last success (time, file, size, sha256), last
failure, last copy, last test restore, the active crons of the
`auto_backup` module seen by the last backup, and the age threshold the
timer installer derived from the schedule. It is readable by everyone, so
`--status` needs no sudo, and `--status` runs no PostgreSQL command.

**Status.** `--status` fails (code 1) when a database has no success, or
one older than `--max-age` hours; without `--max-age`, the threshold
derived from the schedule while the timer is installed, else 26. It also
fails when the last test restore failed, or when the program in the
`ExecStart` of the backup service no longer exists (a moved checkout makes
every run fail); a path the account running `--status` cannot examine
(a closed home folder) is only a detail. It warns about a failure newer than the last success, a
recorded file missing on disk, a failed copy, a timer missing or not
active, a service without `--copy-to` (a backup kept on the server is lost
with it), active crons of `auto_backup` or `auto_database_backup` that
have a backup configuration (a second backup from Odoo, on the same disk;
a cron without one backs up nothing), and a test restore missing or older than `--max-restore-age`
days (7). It shows the number and total size of the backups (their folder
belongs to the unit's account: under sudo) and every date with its UTC
offset, since backup names use local time. The timer is read with
`systemctl show`, which needs no root.

**Test restore.** `--test-restore` restores the newest backup (or
`--file`) into a temporary database `<db>_restoretest_<stamp>` (cut to
fit PostgreSQL's 63 bytes), checks the sha256, loads `dump.sql`, checks the
tables, `ir_module_module`, the `base` module and the installed modules
against the manifest, extracts the filestore as the unit's account into a
temporary folder, then always drops what it created; a temporary database
it cannot drop ends with code 1. The source database is never touched.
The garbage-collection markers of Odoo 18 (`filestore/checklist/`) are not
counted as attachments when the number of files the database references is
compared with the backup. Except with `--dry-run`, the outcome (time,
success, file, last error) is recorded as `last_restore_test`, which
`--status` judges, when the file is a backup of the database, under the
tool's name, in its folder. The temporary folder is the database's backup folder,
or Odoo's filestore folder when no backup was taken yet.

**Room in PostgreSQL.** A test restore or a restore creates a full copy on
the same PostgreSQL server: a full volume would stop the production
database too. Before `createdb`, the tool checks the free space of
PostgreSQL's `data_directory` for twice the size of `dump.sql` (indexes
are rebuilt), or the size of the source database when it is larger, plus
20 %. The folder is read as the unit's role, else, as root, as the
`postgres` system account over the local socket. When it cannot be read,
or `db_host` is another host, the tool refuses, unless `--force-space`.

**Restore.** `--restore --file F --into NEW` only restores into a database
that does not exist yet, and a filestore folder
`<data_dir>/filestore/NEW` that does not exist either. Archive paths that
would leave the extraction folder are refused. `--file` also takes a
`.tar.xz` of the older backup tool (`dump.sql`, `manifest.json` and
`filestore/` at its root, the zip's content), recognised by its first
bytes: a link, a special file or a duplicate name in it refuses the
archive. The tool never writes one. The filestore is written as
the unit's account. A failure after `createdb` drops the new database and
its partial filestore. Before starting Odoo on
the copy, neutralize it (`odoo-bin neutralize`, from Odoo 16); its
`database.uuid` is the source's.

**Into a development checkout.** The zip has Odoo's own format, so
`db_restore.py` restores it on a development machine: an `--image` that
holds a `/` is a path, read as is and restored without a `_cache_` copy. A
database already named like `-d` is dropped first.

```bash
./script/database/db_restore.py -d demo_copy --neutralize --image ~/Downloads/demo_db_2031-03-10_03h00m00s.zip
./script/addons/update_prod_to_dev.sh demo_copy
```

`--neutralize` has Odoo neutralize the database while loading it (Odoo 16
and later: crons and mail servers off); `update_prod_to_dev.sh` then
installs the development modules (`test`/`test` account, outgoing mail,
automatic backups and payment providers disabled). `TODO › Execute ›
Database › Restore from backup (.zip)` asks the same questions for a zip
placed in `image_db/`.

**Off-site copy.** `--copy-to [user@]host:/path` (or an absolute path),
disabled by default, runs after the retention: rsync over
`ssh -o BatchMode=yes`, as the unit's account, so its ssh key and
`known_hosts` are used. It sends the database's folder, filtered to the
tool's names for this database (`<db>_<stamp>.zip` and its `.sha256`), so
a copy missed or cut short at one run is sent again at the next. An
interrupted transfer waits in `.rsync-partial/` and never takes the final
name (`--partial-dir`, `--delay-updates`). A failed copy keeps the local
backup, is recorded, and ends with code 1. `--copy-prune` then lists the
destination (`rsync --list-only`) and applies the same retention to the
backups found there: those it does not keep are deleted, each with its
`.sha256`, never one still present locally, at most `--copy-prune-max`
backups per run (20), the oldest first. The remote history is judged by
itself: a rebuilt server, a new destination or local backups deleted by
hand never make it delete more than the retention keeps. No other remote
file is deleted (only the targeted names are included), and a local folder
that is empty or unreadable sends nothing. A failed pruning or one that
stops at the limit is a warning: the backups are copied. Without
`--copy-prune`, the remote side keeps growing.

**Backups of the older tool.** Its archives are named
`<db>_<YYYY-MM-DD>_<HHMMSS>.zip` or `.tar.xz`: retention, `--status` and the
choice of the newest backup ignore them, and `--copy-prune` never deletes
them remotely. Restore or test one with `--file` (a test of a file that is
not a backup of the database in its folder is not recorded for
`--status`), then delete them by hand
once the new backups cover the period:

```bash
sudo ./script/database/odoo_backup.py --test-restore --db demo_db --file /var/backups/odoo/demo_db/demo_db_2031-03-09_030000.tar.xz
```

**Profile.** The lasting settings of an instance live in its JSON profile,
group `backup`: `dest`, `state_dir` (absolute paths), `keep_daily` (at
least 1), `keep_weekly`, `keep_monthly`, `keep_recent_days` (together at
least 2, counting the tool's default for a value the command line
replaces), `copy_to`, `copy_prune`, `copy_prune_max` (at least 1),
`max_age` (at most 168), `max_restore_age`, `timeout`, `verbose`, and
`db` from the shared group `instance`. The file is `--profile FILE`, else
`private/production/<service>.json` of this checkout, the service being
`--service` or the guessed unit; no file means no profile. The command
line always wins; `--no-profile` reads no profile, `--profile-unset NAME`
(e.g. `keep-daily`) drops one value, `--profile-required` fails (code 2)
without one. The modes, `--file`, `--into`, `--service`, `--odoo-conf`,
`--user`, `--force-space` and `--dry-run` are never read from a profile:
such a key is ignored with a warning. `--status` guesses no unit and
ignores the profile's `db`, so it still lists every database. The
profile's values are listed under the detected instance, before the
simulated commands.

```json
{
  "version": 1,
  "service": "odoo-exemple.service",
  "instance": {"db": "exemple_db"},
  "backup": {"dest": "/srv/sauvegardes", "keep_daily": 10,
             "copy_to": "sauvegarde@backup.example.org:/srv/hors-site"}
}
```

**Upload limits.** A backup uploaded through `/web/database/manager` goes
through the reverse proxy's request size limit (`client_max_body_size` for
nginx) and Odoo's request time limit (`limit_time_real`, with workers): for
a large database, restore it on the server with `--restore`.

| Code | Meaning |
|------|---------|
| 0 | success (or simulation) |
| 1 | failure: backup, verification, copy, stale or missing status, test restore, temporary database not dropped |
| 2 | refused before anything was done |
| 75 | another backup or update of this database is running |
| 130 | interrupted; the partial file is removed |

The scheduled backup is installed by `script/systemd/install_backup_timer.py`,
see [doc/PRODUCTION.md](../../doc/PRODUCTION.md). It reads the same
profile: its own group `backup_timer` (`on_calendar`, `randomized_delay`,
`verbose`), plus `dest`, `state_dir`, the `keep_*` settings, `copy_to`,
`copy_prune` and `copy_prune_max` from `backup` (the last two written with
`--copy-to` only), and `db` from `instance`. It derives the age threshold
of `--status` from the schedule: the largest gap between two of the next
64 runs (`systemd-analyze calendar --iterations`), plus the randomized
delay and 2 h, recorded as `expected_max_age_hours` in the database's
state; when no threshold can be derived (a systemd too old for
`--iterations`, an unreadable output), it keeps 26 h, with a warning, and
clears the threshold of an earlier installation.
It ends by reminding to run a test restore once. `--on-calendar` and
`--randomized-delay` refuse a malformed value at parsing (code 2), from
the command line or the profile; `systemd-analyze calendar` still checks
the calendar at installation. The command line always wins, and the same
meta-options apply (`--profile`, `--no-profile`, `--profile-unset`,
`--profile-required`). `--uninstall`, `--service`, `--odoo-conf`,
`--user`, `--root`, `--credential` and `--dry-run` are never read from a
profile. The retained values are listed before the units and the
simulated commands.

`ExecStart` takes one of two forms:

- **profile mode**, when a profile is used, the unit's account can read
  it (`runuser -u ACCOUNT -- test -r`, checked under sudo) and the tool of
  the retained checkout applies it (read statically, nothing is run): the
  detected identity (`--service`, `--db`, `--odoo-conf`, `--user`), the
  fields fixed at installation (`--dest`, `--state-dir`, `--copy-to`)
  whatever their origin, the `--keep-*` settings only when typed, then
  `--profile <absolute path> --profile-required`. The backup reads the
  profile at each run: an edited retention applies from the next night,
  and a profile that became invalid makes the backup fail (code 2, seen
  by `--status`) rather than silently drop `--copy-to`. `systemctl cat`
  shows the path. Under root, the tool only reads a profile that neither
  its group nor other accounts can write, nor its directory, owned by
  root, the checkout's owner or the sudo caller.
- **frozen mode** otherwise (no profile, a profile the account cannot
  read, a tool older than profiles): every value written as if typed, as
  before, ending with `--no-profile` when the tool knows profiles. With a
  profile present, a warning says that an edit of the profile needs a
  reinstall.

`--dest`, `--state-dir`, `--copy-to`, `--db`, `--on-calendar` and
`--randomized-delay` are fixed at installation (timer file, directories
created for the account, its `known_hosts`): after changing them in the
profile, reinstall.

**Secrets.** `--credential NAME=PATH` (repeatable) gives a secret that the
backup tool declares; `backup` declares none today, the path is generic.
Root reads `PATH` without following a link, and stores it as a systemd
credential of the unit, never on a command line nor in the environment:

| systemd | Storage | Unit line |
|---|---|---|
| 250+ with `systemd-creds` | `systemd-creds encrypt --with-key=host`, secret on stdin, `/etc/credstore.encrypted/<unit>.<NAME>` (0600, directory 0700) | `LoadCredentialEncrypted=` |
| 247–249, or no `systemd-creds` | in clear, `/etc/credstore/<unit>.<NAME>` (0600 root, directory 0700), with a warning | `LoadCredential=` |
| before 247, or unknown | refused (code 2) before anything is written | — |

Only a missing `systemd-creds` (code 127) selects clear storage: any other
failure of `systemd-creds --version` on systemd 250+ is refused (code 2)
rather than stored in clear. The unit lines hold absolute paths. A file
encrypted with `--with-key=host` is only readable with the host's
`/var/lib/systemd/credential.secret`: restoring `/etc` alone leaves the
unit unable to start. A secret that the profile declares without
`--credential` keeps the stored file, first the one the installed unit
cites, with its line, even after a systemd upgrade (a file kept in clear
while encryption is available gets a warning), and is refused when there
is none; `--dry-run` reads nothing and shows the line "(provided at
installation)". A reinstall removes the line and the file of a secret
that the profile no longer declares; a file stored by an install that
fails before writing the service is removed at once. `--uninstall`
removes the credential files of the unit, only under `/etc/credstore` or
`/etc/credstore.encrypted` and named after the unit: those the unit
cites, `<unit>.<NAME>` for every secret of the tool, and the temporary
leftovers of an interrupted write (`--root` prefixes them; `--dry-run`
shows the `rm`, marked "(if present)" when, without root, the 0700
directory cannot be checked).
