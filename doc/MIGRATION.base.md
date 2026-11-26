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
Execute migration with OpenUpgrade, from its clone of the target version and in the Odoo 13.0 venv, whose
name is the `odoo13.0_…` key of `conf/supported_version_erplibre.json`.

<!-- [fr] -->
Exécutez la migration avec OpenUpgrade, depuis son clone de la version cible et dans le venv d'Odoo 13.0, dont
le nom est la clé `odoo13.0_…` de `conf/supported_version_erplibre.json`.

<!-- [common] -->
```bash
make config_gen_migration
./.venv.odoo13.0_python3.7.17/bin/python ./odoo13.0/OCA_OpenUpgrade/odoo-bin -c ./config.conf --no-http --update all --stop-after-init -d BD
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
./run.sh --upgrade-path=./odoo14.0/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --no-http --stop-after-init --load=base,web,openupgrade_framework -d BD
```

<!-- [en] -->
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

<!-- [fr] -->
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
