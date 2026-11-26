
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

```bash
./script/addons/update_addons_all.sh BD
```

### Cible Odoo 13 ou avant

OpenUpgrade est un Odoo complet : la configuration prend ses addons et son
cœur à la place de ceux d'Odoo, et son lanceur tourne dans le venv de la
version cible. Jusqu'à Odoo 9, le cœur est `openerp/addons` et le lanceur
`openerp-server`, et jusqu'à Odoo 10 le serveur HTTP s'éteint par
`--no-xmlrpc` au lieu de `--no-http`.

```bash
OU=$PWD/odooN.0/OCA_OpenUpgrade
./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py --ignore-odoo-path \
  --extra-addons-path $OU,$OU/addons,$OU/odoo/addons && ./script/generate_config.sh
./.venv.VENV/bin/pip install odoorpc==0.7.0 openupgradelib
./.venv.VENV/bin/python $OU/odoo-bin -c ./config.conf --update all --no-http --stop-after-init -d BD
```

### Cible Odoo 14 ou après

OpenUpgrade n'apporte que ses scripts de migration, lancés par `run.sh` avec
le module `openupgrade_framework` et `erplibre_openupgrade_compat`, qui
corrige openupgradelib et vit dans `script/odoo/openupgrade_addons`. Les
limites de mémoire et de temps sont levées : celles d'Odoo arrêtent une mise
à jour de toute une base.

```bash
./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py \
  --extra-addons-path $PWD/odooN.0/OCA_OpenUpgrade,$PWD/script/odoo/openupgrade_addons \
  && ./script/generate_config.sh
./run.sh --upgrade-path=./odooN.0/OCA_OpenUpgrade/openupgrade_scripts/scripts \
  --update all -c config.conf --stop-after-init --no-http \
  --limit-memory-hard=0 --limit-memory-soft=0 --limit-time-real 99999 --limit-time-cpu 99999 \
  --load=base,web,openupgrade_framework,erplibre_openupgrade_compat -d BD
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