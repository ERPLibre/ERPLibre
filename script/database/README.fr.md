
# Base de données

Cette section concerne le migrateur de base de données du générateur de code.

Cette configuration est pour l'environnement de développement.

Vous devez installer le script `./script/install/install_dev_extra_ubuntu.sh`.

## Restaurer une base de données

Exécutez le script pour restaurer la base de données :

```bash
./script/database/restore_mariadb_sql_example_1.sh
```

## Cluster PostgreSQL 16 de migration

Une migration peut tourner sur un cluster PostgreSQL 16 à côté du serveur du système, le catalogue pour lequel OpenUpgrade a été écrit. Il ne prend que les sauvegardes produites par PostgreSQL 16 ou plus ancien : le dump d'un serveur plus récent n'est pas fait pour un serveur plus ancien, et celui de PostgreSQL 18 y échoue franchement ; une telle migration reste donc sur le serveur du système. Le cluster appartient au compte qui lance la migration, vit dans `private/postgresql/16` et n'écoute que sur son propre socket, port 5433.

Installez les binaires (AUR `postgresql16` sur Arch, `postgresql-16` sur Debian et Ubuntu), puis réglez `TODO › Configuration › PostgreSQL de la migration` sur 16 : le menu de migration démarre le cluster et y branche Odoo, `psql` et `pg_dump` par `PGHOST` et `PGPORT`. Un nom de base que porte déjà le serveur du système est refusé, les deux serveurs partageant le filestore par nom. À la main :

```bash
./script/install/install_postgresql_migration.sh
./.venv.erplibre/bin/python script/database/migration_cluster.py start
eval "$(./.venv.erplibre/bin/python script/database/migration_cluster.py env)"
./.venv.erplibre/bin/python script/database/migration_cluster.py dump-version image_db/<backup>.zip
./.venv.erplibre/bin/python script/database/migration_cluster.py stop
```