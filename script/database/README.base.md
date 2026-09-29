<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Database

This section is for code generator database migrator.

This configuration is for development environnement.

You need to install script `./script/install/install_dev_extra_ubuntu.sh`.

## Restore database

Run script to restore database:

<!-- [fr] -->
# Base de données

Cette section concerne le migrateur de base de données du générateur de code.

Cette configuration est pour l'environnement de développement.

Vous devez installer le script `./script/install/install_dev_extra_ubuntu.sh`.

## Restaurer une base de données

Exécutez le script pour restaurer la base de données :

<!-- [common] -->
```bash
./script/database/restore_mariadb_sql_example_1.sh
```

<!-- [en] -->
## PostgreSQL 16 migration cluster

A migration can run on a PostgreSQL 16 cluster next to the system server, the catalogue OpenUpgrade was written for. It only takes backups dumped by PostgreSQL 16 or older: a dump from a newer server is not meant to restore into an older one, and PostgreSQL 18's fails outright, so such a migration stays on the system server. The cluster belongs to the account that runs the migration, lives in `private/postgresql/16` and listens only on its own socket, port 5433.

Install the binaries (AUR `postgresql16` on Arch, `postgresql-16` on Debian and Ubuntu), then set `TODO › Configuration › PostgreSQL of the migration` to 16: the migration menu starts the cluster and points Odoo, `psql` and `pg_dump` at it through `PGHOST` and `PGPORT`. A database name the system server already holds is refused, since both servers share the filestore by name. By hand:

<!-- [fr] -->
## Cluster PostgreSQL 16 de migration

Une migration peut tourner sur un cluster PostgreSQL 16 à côté du serveur du système, le catalogue pour lequel OpenUpgrade a été écrit. Il ne prend que les sauvegardes produites par PostgreSQL 16 ou plus ancien : le dump d'un serveur plus récent n'est pas fait pour un serveur plus ancien, et celui de PostgreSQL 18 y échoue franchement ; une telle migration reste donc sur le serveur du système. Le cluster appartient au compte qui lance la migration, vit dans `private/postgresql/16` et n'écoute que sur son propre socket, port 5433.

Installez les binaires (AUR `postgresql16` sur Arch, `postgresql-16` sur Debian et Ubuntu), puis réglez `TODO › Configuration › PostgreSQL de la migration` sur 16 : le menu de migration démarre le cluster et y branche Odoo, `psql` et `pg_dump` par `PGHOST` et `PGPORT`. Un nom de base que porte déjà le serveur du système est refusé, les deux serveurs partageant le filestore par nom. À la main :

<!-- [common] -->
```bash
./script/install/install_postgresql_migration.sh
./.venv.erplibre/bin/python script/database/migration_cluster.py start
eval "$(./.venv.erplibre/bin/python script/database/migration_cluster.py env)"
./.venv.erplibre/bin/python script/database/migration_cluster.py dump-version image_db/<backup>.zip
./.venv.erplibre/bin/python script/database/migration_cluster.py stop
```
