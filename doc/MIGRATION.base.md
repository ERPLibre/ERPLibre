<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [fr] -->
# Migration

Guide pour aider à la migration entre différentes versions.

## Docker

- Cloner le projet si vous n'avez téléchargé que docker-compose
    - `git init`
    - `git remote add origin https://github.com/erplibre/erplibre`
    - `git fetch`
    - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
    - `git checkout master`
    - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
- Faites manuellement une sauvegarde de la base de données ERPLibre (À FAIRE : implémenter une commande makefile)
- Mettez à jour `./docker-compose.yml` en fonction des différences avec git.
- Exécutez le script `make docker_exec_erplibre_gen_config`
- Arrêtez le docker `make docker_stop`
- Supprimez le volume, `docker volume rm ${BASENAME}_erplibre-db-data`
- Démarrez le docker `make docker_run_daemon`
- Restaurez la sauvegarde manuellement.

### Migration de base de données, mise à jour PostgreSQL 11 vers 12

À FAIRE : ne fonctionne pas automatiquement, vérifiez la dernière procédure et faites-le manuellement. La commande docker ne supporte pas le cas où la base de données est externe.

Méthode facile : faites une sauvegarde avec ERPLibre, mettez à jour PostgreSQL, restaurez la même sauvegarde.

Lister toutes les bases de données :

<!-- [common] -->
```bash
make docker_show_databases
```

<!-- [en] -->
## Vanilla

- Run script `make install_dev`
- Restart your daemon
- Regenerate master password manually

## Migration Odoo 12 to Odoo 13

Replace BD to your database name.

First, be sure all addons is updated with script.

<!-- [fr] -->
## Vanilla

- Exécutez le script `make install_dev`
- Redémarrez votre démon
- Régénérez le mot de passe maître manuellement

## Migration Odoo 12 vers Odoo 13

Remplacez BD par le nom de votre base de données.

D'abord, assurez-vous que tous les addons sont mis à jour avec le script.

<!-- [common] -->
```bash
./script/addons/update_addons_all.sh BD
```

<!-- [en] -->
Execute migration with OpenUpgrade.

<!-- [fr] -->
Exécutez la migration avec OpenUpgrade.

<!-- [common] -->
```bash
make config_gen_migration
./.venv.erplibre/bin/python ./script/OCA_OpenUpgrade/odoo-bin -c ./config.conf --no-http --update all --stop-after-init -d BD
```

<!-- [en] -->
## Migration Odoo 13 to Odoo 14

Replace BD to your database name.

<!-- [fr] -->
## Migration Odoo 13 vers Odoo 14

Remplacez BD par le nom de votre base de données.

<!-- [common] -->
```bash
make config_gen_migration
./run.sh --upgrade-path=./script/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --no-http --stop-after-init --load=base,web,openupgrade_framework -d BD
```
