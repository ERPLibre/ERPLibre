
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

```bash
make docker_show_databases
```

## Vanilla

- Exécutez le script `make install_dev`
- Redémarrez votre démon
- Régénérez le mot de passe maître manuellement

## Migration Odoo 12 vers Odoo 13

Remplacez BD par le nom de votre base de données.

D'abord, assurez-vous que tous les addons sont mis à jour avec le script.

```bash
./script/addons/update_addons_all.sh BD
```

Exécutez la migration avec OpenUpgrade.

```bash
make config_gen_migration
./.venv.erplibre/bin/python ./script/OCA_OpenUpgrade/odoo-bin -c ./config.conf --no-http --update all --stop-after-init -d BD
```

## Migration Odoo 13 vers Odoo 14

Remplacez BD par le nom de votre base de données.

```bash
make config_gen_migration
./run.sh --upgrade-path=./script/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --no-http --stop-after-init --load=base,web,openupgrade_framework -d BD
```