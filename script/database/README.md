
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
database. It needs neither the Odoo venv nor `list_db`.

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
failure, last copy. It is readable by everyone, so `--status` needs no
sudo. `--status` fails (code 1) when a database has no success, or one
older than `--max-age` hours (26); it warns about a failure newer than the
last success, a recorded file missing on disk, and a failed copy.

**Test restore.** `--test-restore` restores the newest backup (or
`--file`) into a temporary database `<db>_restoretest_<stamp>` (cut to
fit PostgreSQL's 63 bytes), checks the sha256, loads `dump.sql`, checks the
tables, `ir_module_module`, the `base` module and the installed modules
against the manifest, extracts the filestore as the unit's account into a
temporary folder, then always drops what it created; a temporary database
it cannot drop ends with code 1. The source database is never touched.

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
would leave the extraction folder are refused. The filestore is written as
the unit's account. A failure after `createdb` drops the new database and
its partial filestore. Before starting Odoo on
the copy, neutralize it (`odoo-bin neutralize`, from Odoo 16); its
`database.uuid` is the source's.

**Off-site copy.** `--copy-to [user@]host:/path` (or an absolute path),
disabled by default: `rsync -a --partial` over `ssh -o BatchMode=yes`, as
the unit's account, so its ssh key and `known_hosts` are used. A failed
copy keeps the local backup, is recorded, and ends with code 1. Retention
does not apply on the remote side: it keeps growing.

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
see [doc/PRODUCTION.md](../../doc/PRODUCTION.md).
