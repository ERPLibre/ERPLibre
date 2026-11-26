
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

## Migration Odoo 12 to Odoo 13

Replace BD to your database name.

First, be sure all addons is updated with script.

```bash
./script/addons/update_addons_all.sh BD
```

Execute migration with OpenUpgrade, from its clone of the target version and in the Odoo 13.0 venv, whose
name is the `odoo13.0_…` key of `conf/supported_version_erplibre.json`.

```bash
make config_gen_migration
./.venv.odoo13.0_python3.7.17/bin/python ./odoo13.0/OCA_OpenUpgrade/odoo-bin -c ./config.conf --no-http --update all --stop-after-init -d BD
```

## Migration Odoo 13 to Odoo 14

Replace BD to your database name.

```bash
make config_gen_migration
./run.sh --upgrade-path=./odoo14.0/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --no-http --stop-after-init --load=base,web,openupgrade_framework -d BD
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
