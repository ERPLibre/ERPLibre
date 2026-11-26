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

<!-- [fr] -->
## Vanilla

- Exécutez le script `make install_dev`
- Redémarrez votre démon
- Régénérez le mot de passe maître manuellement

## Migration de base de données entre versions d'Odoo

**TODO › Exécuter › Code › Mise à jour › Mise à jour Odoo - Migration de base
de données** migre une base d'Odoo 8 jusqu'à 20, une version à la fois. C'est
la référence : en plus d'OpenUpgrade, elle installe les versions manquantes,
désinstalle les modules absents de la version suivante, lance les
vérifications et les correctifs de chaque saut, et reprend là où elle s'est
arrêtée. Les touches depuis un clone neuf sont dans le README, section
*Migrer une base de données entre versions d'Odoo*.

Les commandes ci-dessous sont celles que lance chaque saut, pour une
exécution à la main ou un diagnostic. Remplacez `N` par la version cible, `BD`
par le nom de la base et `VENV` par la clé `odooN.0_…` de
`conf/supported_version_erplibre.json`. D'abord, mettez à jour les addons de
la base :

<!-- [common] -->
```bash
./script/addons/update_addons_all.sh BD
```

<!-- [en] -->
### Target Odoo 13 or earlier

OpenUpgrade is a complete Odoo: the configuration takes its addons and its
core instead of those of Odoo, and its launcher runs in the venv of the target
version. Up to Odoo 9, the core is `openerp/addons`, the launcher
`openerp-server`, and up to Odoo 10 the HTTP server is turned off by
`--no-xmlrpc` instead of `--no-http`.

<!-- [fr] -->
### Cible Odoo 13 ou avant

OpenUpgrade est un Odoo complet : la configuration prend ses addons et son
cœur à la place de ceux d'Odoo, et son lanceur tourne dans le venv de la
version cible. Jusqu'à Odoo 9, le cœur est `openerp/addons` et le lanceur
`openerp-server`, et jusqu'à Odoo 10 le serveur HTTP s'éteint par
`--no-xmlrpc` au lieu de `--no-http`.

<!-- [common] -->
```bash
OU=$PWD/odooN.0/OCA_OpenUpgrade
./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py --ignore-odoo-path \
  --extra-addons-path $OU,$OU/addons,$OU/odoo/addons && ./script/generate_config.sh
./.venv.VENV/bin/pip install odoorpc==0.7.0 openupgradelib
./.venv.VENV/bin/python $OU/odoo-bin -c ./config.conf --update all --no-http --stop-after-init -d BD
```

<!-- [en] -->
### Target Odoo 14 or later

OpenUpgrade only brings its migration scripts, run by `run.sh` with the
`openupgrade_framework` module and `erplibre_openupgrade_compat`, which fixes
openupgradelib and lives in `script/odoo/openupgrade_addons`. Memory and time
limits are lifted: those of Odoo stop an update of a whole database.

<!-- [fr] -->
### Cible Odoo 14 ou après

OpenUpgrade n'apporte que ses scripts de migration, lancés par `run.sh` avec
le module `openupgrade_framework` et `erplibre_openupgrade_compat`, qui
corrige openupgradelib et vit dans `script/odoo/openupgrade_addons`. Les
limites de mémoire et de temps sont levées : celles d'Odoo arrêtent une mise
à jour de toute une base.

<!-- [common] -->
```bash
./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py \
  --extra-addons-path $PWD/odooN.0/OCA_OpenUpgrade,$PWD/script/odoo/openupgrade_addons \
  && ./script/generate_config.sh
./run.sh --upgrade-path=./odooN.0/OCA_OpenUpgrade/openupgrade_scripts/scripts \
  --update all -c config.conf --stop-after-init --no-http \
  --limit-memory-hard=0 --limit-memory-soft=0 --limit-time-real 99999 --limit-time-cpu 99999 \
  --load=base,web,openupgrade_framework,erplibre_openupgrade_compat -d BD
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

A database moved from PostgreSQL 17 to 18 can fail in the mail module on `discuss_channel_member_channel_id_fkey`: when
the database carries the constraint `discuss_channel_channel_type_not_null`, the neutralization step applies
`script/postgresql/migration/fix_postgresql_18_discuss_channel_type_not_null.sql`, and reruns.

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

Une base passée de PostgreSQL 17 à 18 peut échouer dans le module mail sur `discuss_channel_member_channel_id_fkey` :
quand la base porte la contrainte `discuss_channel_channel_type_not_null`, l'étape de neutralisation applique
`script/postgresql/migration/fix_postgresql_18_discuss_channel_type_not_null.sql`, puis se relance.
