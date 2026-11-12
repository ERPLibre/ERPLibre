
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