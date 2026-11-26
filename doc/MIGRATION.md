
# Migration

Guide to help migration with different version.

## Docker

- Clone project if only download docker-compose
    - `git init`
    - `git remote add origin https://github.com/erplibre/erplibre`
    - `git fetch`
    - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
    - `git checkout master`
    - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
- Do manually a backup of ERPLibre database (TODO implement makefile command)
- Update `./docker-compose.yml` depending of difference with git.
- Run script `make docker_exec_erplibre_gen_config`
- Stop the docker `make docker_stop`
- Delete the volume, `docker volume rm ${BASENAME}_erplibre-db-data`
- Start the docker `make docker_run_daemon`
- Restore the backup manually.

### Database migration, PostgreSQL update 11 to 12

TODO not working automatically, check last procedure and do it manually. The command to the docker is missing support
when database is external.

Easy way, do a backup with ERPLibre, upgrade Postgresql, restore the same backup.

List all database :

```bash
make docker_show_databases
```

## Vanilla

- Run script `make install_dev`
- Restart your daemon
- Regenerate master password manually

## Database migration between Odoo versions

**TODO › Execute › Code › Update › Upgrade Odoo - Migration Database** migrates
a database from Odoo 8 up to 20, one version at a time. It is the reference:
besides OpenUpgrade, it installs the missing versions, uninstalls the modules
absent from the next version, runs the checks and the fixes of each hop, and
resumes where it stopped. The keys from a fresh clone are in the README,
section *Migrate a database between Odoo versions*.

The commands below are those each hop runs, for a manual run or a diagnosis.
Replace `N` by the target version, `BD` by the database name, and `VENV` by
the `odooN.0_…` key of `conf/supported_version_erplibre.json`. First update
the addons of the database:

```bash
./script/addons/update_addons_all.sh BD
```

### Target Odoo 13 or earlier

OpenUpgrade is a complete Odoo: the configuration takes its addons and its
core instead of those of Odoo, and its launcher runs in the venv of the target
version. Up to Odoo 9, the core is `openerp/addons`, the launcher
`openerp-server`, and up to Odoo 10 the HTTP server is turned off by
`--no-xmlrpc` instead of `--no-http`.

```bash
OU=$PWD/odooN.0/OCA_OpenUpgrade
./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py --ignore-odoo-path \
  --extra-addons-path $OU,$OU/addons,$OU/odoo/addons && ./script/generate_config.sh
./.venv.VENV/bin/pip install odoorpc==0.7.0 openupgradelib
./.venv.VENV/bin/python $OU/odoo-bin -c ./config.conf --update all --no-http --stop-after-init -d BD
```

### Target Odoo 14 or later

OpenUpgrade only brings its migration scripts, run by `run.sh` with the
`openupgrade_framework` module and `erplibre_openupgrade_compat`, which fixes
openupgradelib and lives in `script/odoo/openupgrade_addons`. Memory and time
limits are lifted: those of Odoo stop an update of a whole database.

```bash
./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py \
  --extra-addons-path $PWD/odooN.0/OCA_OpenUpgrade,$PWD/script/odoo/openupgrade_addons \
  && ./script/generate_config.sh
./run.sh --upgrade-path=./odooN.0/OCA_OpenUpgrade/openupgrade_scripts/scripts \
  --update all -c config.conf --stop-after-init --no-http \
  --limit-memory-hard=0 --limit-memory-soft=0 --limit-time-real 99999 --limit-time-cpu 99999 \
  --load=base,web,openupgrade_framework,erplibre_openupgrade_compat -d BD
```

## PostgreSQL during the migration

One PostgreSQL 18 carries the whole chain, from Odoo 12 to 18: no hop needs another version. A backup restores only
into a server of the same major version or newer.

At its start and at each resume, the migration checks the server it uses, through the connection of `config.conf`,
and stops with the reason only when a hop would fail for sure: a local server, reached through its Unix socket, must
be the installed one. After an update of the PostgreSQL package, a server started before keeps the old executable, and
the first library it loads fails on « undefined symbol »: the hop to 13 loads plpgsql. Restart it,
`sudo systemctl restart postgresql`, then rerun the migration, which resumes where it stopped. A server over TCP, a
container or another host, is not compared.

A backup from a newer PostgreSQL than the server, or a server the check cannot query, only gives a warning. A command
that fails on a library the server does not load says to restart it, and `TODO › Healthcheck` reports the same
mismatch between running and installed server.

A database moved from PostgreSQL 17 to 18 can fail in the mail module on `discuss_channel_member_channel_id_fkey`: when
the database carries the constraint `discuss_channel_channel_type_not_null`, the neutralization step applies
`script/postgresql/migration/fix_postgresql_18_discuss_channel_type_not_null.sql`, and reruns.
