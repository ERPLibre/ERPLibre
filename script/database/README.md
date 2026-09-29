
# Database

This section is for code generator database migrator.

This configuration is for development environnement.

You need to install script `./script/install/install_dev_extra_ubuntu.sh`.

## Restore database

Run script to restore database:

```bash
./script/database/restore_mariadb_sql_example_1.sh
```

## PostgreSQL 16 migration cluster

A migration can run on a PostgreSQL 16 cluster next to the system server, the catalogue OpenUpgrade was written for. It only takes backups dumped by PostgreSQL 16 or older: a dump from a newer server is not meant to restore into an older one, and PostgreSQL 18's fails outright, so such a migration stays on the system server. The cluster belongs to the account that runs the migration, lives in `private/postgresql/16` and listens only on its own socket, port 5433.

Install the binaries (AUR `postgresql16` on Arch, `postgresql-16` on Debian and Ubuntu), then set `TODO › Configuration › PostgreSQL of the migration` to 16: the migration menu starts the cluster and points Odoo, `psql` and `pg_dump` at it through `PGHOST` and `PGPORT`. A database name the system server already holds is refused, since both servers share the filestore by name. By hand:

```bash
./script/install/install_postgresql_migration.sh
./.venv.erplibre/bin/python script/database/migration_cluster.py start
eval "$(./.venv.erplibre/bin/python script/database/migration_cluster.py env)"
./.venv.erplibre/bin/python script/database/migration_cluster.py dump-version image_db/<backup>.zip
./.venv.erplibre/bin/python script/database/migration_cluster.py stop
```