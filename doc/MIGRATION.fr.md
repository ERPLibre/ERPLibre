
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

Exécutez la migration avec OpenUpgrade, depuis son clone de la version cible et dans le venv d'Odoo 13.0, dont
le nom est la clé `odoo13.0_…` de `conf/supported_version_erplibre.json`.

```bash
make config_gen_migration
./.venv.odoo13.0_python3.7.17/bin/python ./odoo13.0/OCA_OpenUpgrade/odoo-bin -c ./config.conf --no-http --update all --stop-after-init -d BD
```

## Migration Odoo 13 vers Odoo 14

Remplacez BD par le nom de votre base de données.

```bash
make config_gen_migration
./run.sh --upgrade-path=./odoo14.0/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --no-http --stop-after-init --load=base,web,openupgrade_framework -d BD
```

## PostgreSQL pendant la migration

Un seul PostgreSQL 18 porte toute la chaîne, d'Odoo 12 à 18 : aucun saut n'exige une autre version. Une sauvegarde ne
se restaure que dans un serveur de même version majeure ou plus récent.

À son début et à chaque reprise, la migration vérifie le serveur qu'elle utilise, par la connexion de `config.conf`, et
ne s'arrête en disant pourquoi que lorsqu'un saut échouerait à coup sûr : un serveur local, joint par son socket Unix,
doit être celui installé. Après une mise à jour du paquet PostgreSQL, un serveur démarré avant garde l'ancien
exécutable, et la première bibliothèque qu'il charge échoue sur « undefined symbol » : le saut vers 13 charge
plpgsql. Le redémarrer, `sudo systemctl restart postgresql`, puis relancer la migration, qui reprend là où elle
s'est arrêtée. Un serveur en TCP, un conteneur ou un autre hôte, n'est pas comparé.

Une sauvegarde d'un PostgreSQL plus récent que le serveur, ou un serveur que la vérification ne sait pas interroger,
ne donne qu'un avertissement. Une commande qui échoue sur une bibliothèque que le serveur ne charge pas dit de le
redémarrer, et `TODO › Bilan de santé` signale le même écart entre serveur en marche et serveur installé.

Une base passée de PostgreSQL 17 à 18 peut échouer dans le module mail sur `discuss_channel_member_channel_id_fkey` :
quand la base porte la contrainte `discuss_channel_channel_type_not_null`, l'étape de neutralisation applique
`script/postgresql/migration/fix_postgresql_18_discuss_channel_type_not_null.sql`, puis se relance.