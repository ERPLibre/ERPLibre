<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Development guide

Setup your environment to develop modules and debug the platform.

## Local installation procedure

### 1. Clone the project:

<!-- [fr] -->
# Guide de developpement

Configurez votre environnement pour developper des modules et deboguer la plateforme.

## Procedure d'installation locale

### 1. Cloner le projet :

<!-- [common] -->
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

<!-- [en] -->
### 2. Execute the script:

<!-- [fr] -->
### 2. Executer le script :

<!-- [common] -->
```bash
cd ERPLibre
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

<!-- [en] -->
### 3. Run ERPLibre

<!-- [fr] -->
### 3. Lancer ERPLibre

<!-- [common] -->
```bash
./run.sh
```

<!-- [en] -->
## Develop in Odoo repository

You need to remove `clone-depth="10"` from `./manifest/default.dev.xml` in order to be able to commit and push. Make a
temporary commit and regenerate with `./script/install/install_locally_dev.sh`

## Fork project to create a new project independent of ERPLibre (deprecated)

ERPLibre was created with this script. It's now deprecated. Use this script when you need to fork directly from the
original source. Don't use this script if you want to update from ERPLibre and follow mainstream development.

<!-- [fr] -->
## Developper dans le depot Odoo

Vous devez supprimer `clone-depth="10"` de `./manifest/default.dev.xml` afin de pouvoir faire des commits et des pushs. Faites un
commit temporaire et regenerez avec `./script/install/install_locally_dev.sh`

## Forker le projet pour creer un nouveau projet independant d'ERPLibre (obsolete)

ERPLibre a ete cree avec ce script. Il est maintenant obsolete. Utilisez ce script lorsque vous devez forker directement depuis la
source originale. N'utilisez pas ce script si vous voulez recevoir les mises a jour d'ERPLibre et suivre le developpement principal.

<!-- [common] -->
```bash
./script/git/fork_project.py --github_token GITHUB_KEY --organization NAME
```

<!-- [en] -->
# Fork all repos for you own organization

Go to your Github account and generate a token to access fork option with your user. Create an organization or use your
personal account and choose your user name.

This command will fork all repos and ERPLibre to your own organization. It keeps track of ERPLibre.

<!-- [fr] -->
# Forker tous les depots pour votre propre organisation

Allez dans votre compte Github et generez un jeton pour acceder a l'option de fork avec votre utilisateur. Creez une organisation ou utilisez votre
compte personnel et choisissez votre nom d'utilisateur.

Cette commande va forker tous les depots et ERPLibre vers votre propre organisation. Elle garde le suivi d'ERPLibre.

<!-- [common] -->
```bash
./script/git/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

<!-- [en] -->
## Generate manifest from csv repo

Add repo in file [./source_repo_addons.csv](./source_repo_addons.csv)

Execute to generate Repo manifest

<!-- [fr] -->
## Generer le manifeste a partir du csv des depots

Ajoutez le depot dans le fichier [./source_repo_addons.csv](./source_repo_addons.csv)

Executez pour generer le manifeste Repo

<!-- [common] -->
```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

<!-- [en] -->
## Move database from prod to dev

Copy the database image into `./image_db/prod_client.zip` and run `make db_restore_prod_client`. This will create a
database
named `prod_client` ready to test.

When moving database from prod to your dev environment, you want to remove email servers, backups and install user test
in order to test the database. Run:

<!-- [fr] -->
## Deplacer une base de donnees de la prod vers le dev

Copiez l'image de la base de donnees dans `./image_db/prod_client.zip` et executez `make db_restore_prod_client`. Cela va creer une
base de donnees
nommee `prod_client` prete a tester.

Lorsque vous deplacez une base de donnees de la prod vers votre environnement de dev, vous voulez supprimer les serveurs de courriel, les sauvegardes et installer l'utilisateur de test
afin de tester la base de donnees. Executez :

<!-- [common] -->
```bash
./script/database/migrate_prod_to_test.sh DATABASE
```

<!-- [en] -->
## Change git url https to Git

This will update all urls in Git format:

<!-- [fr] -->
## Changer les urls git de https vers Git

Cela va mettre a jour toutes les urls au format Git :

<!-- [common] -->
```bash
./script/git/git_change_remote_https_to_git.py
```

<!-- [en] -->
## Showing repo differences between projects

Tools to display the differences between the repo and another project.

<!-- [fr] -->
## Afficher les differences de depots entre les projets

Outils pour afficher les differences entre le depot et un autre projet.

<!-- [common] -->
```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre --dry_sync
```

<!-- [en] -->
## Showing repo differences with manifest develop

To understand the divergences with the dev manifest.

<!-- [fr] -->
## Afficher les differences de depots avec le manifeste de developpement

Pour comprendre les divergences avec le manifeste de dev.

<!-- [common] -->
```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

<!-- [en] -->
## Sync repo with another project

Tools to synchronise the repo with another project. This will show differences and try to checkout on the same commit in
all repos.

<!-- [fr] -->
## Synchroniser les depots avec un autre projet

Outils pour synchroniser le depot avec un autre projet. Cela va afficher les differences et essayer de se positionner sur le meme commit dans
tous les depots.

<!-- [common] -->
```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre
```

<!-- [en] -->
## Compare two files manifests

To show differences between commits in different manifests

<!-- [fr] -->
## Comparer deux fichiers manifestes

Pour afficher les differences entre les commits dans differents manifestes

<!-- [common] -->
```bash
./script/git/git_diff_repo_manifest.py --input1 ./manifest/MANIFEST1.xml --input2 ./manifest/MANIFEST2.xml
```

<!-- [en] -->
## Differences between code and manifest

To show differences between actual code and manifest

<!-- [fr] -->
## Differences entre le code et le manifeste

Pour afficher les differences entre le code actuel et le manifeste

<!-- [common] -->
```bash
./script/git/git_show_code_diff_repo_manifest.py --manifest ./manifest/MANIFEST1.xml
```

<!-- [en] -->
## Add repo

To access a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Fork the repo to be able to push new code:

<!-- [fr] -->
## Ajouter un depot

Pour acceder a un nouveau depot, ajoutez votre URL dans le fichier [source_repo_addons.csv](../source_repo_addons.csv)

Forkez le depot pour pouvoir pousser du nouveau code :

<!-- [common] -->
```bash
./script/git/fork_project_ERPLibre.py
```

<!-- [en] -->
To regenerate only manifest.xml.

<!-- [fr] -->
Pour regenerer uniquement le manifest.xml.

<!-- [common] -->
```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

<!-- [en] -->
Check if manifest contains "auto_install" and change the value to False.

<!-- [fr] -->
Verifier si le manifeste contient "auto_install" et changer la valeur a False.

<!-- [common] -->
```bash
./script/git/repo_remove_auto_install.py
```

<!-- [en] -->
## Filter repo by group

Only keep repo tagged by group 'base' and 'code_generator'

<!-- [fr] -->
## Filtrer les depots par groupe

Garder uniquement les depots etiquetes par le groupe 'base' et 'code_generator'

<!-- [common] -->
```bash
./script/manifest/update_manifest_local_dev_code_generator.sh
```

<!-- [en] -->
# Execution

## Config file

You can limit your addons in ERPlibre config file depending on a group of your actual manifest.

<!-- [fr] -->
# Execution

## Fichier de configuration

Vous pouvez limiter vos addons dans le fichier de configuration ERPLibre en fonction d'un groupe de votre manifeste actuel.

<!-- [common] -->
```bash
./script/git/git_repo_update_group.py --group base,code_generator
./script/generate_config.sh
```

<!-- [en] -->
Or go back to normal

<!-- [fr] -->
Ou revenir a la normale

<!-- [common] -->
```bash
./script/git/git_repo_update_group.py
./script/generate_config.sh
```

<!-- [en] -->
# Database

## Clean database PostgreSQL

Sometime, it's not possible to delete a database from the database manager `http://127.0.0.1:8069/web/database/manager`,
so you can do it manually. Replace `database_name` by your database name:

<!-- [fr] -->
# Base de donnees

## Nettoyer une base de donnees PostgreSQL

Parfois, il n'est pas possible de supprimer une base de donnees depuis le gestionnaire de base de donnees `http://127.0.0.1:8069/web/database/manager`,
vous pouvez donc le faire manuellement. Remplacez `database_name` par le nom de votre base de donnees :

<!-- [common] -->
```bash
sudo -iu postgres
psql
```

<!-- [en] -->
And run:

<!-- [fr] -->
Et executez :

<!-- [common] -->
```postgres-sql
DROP DATABASE database_name;
```

<!-- [en] -->
Exit and delete filestore:

<!-- [fr] -->
Quittez et supprimez le filestore :

<!-- [common] -->
```bash
rm -r ~/.local/share/Odoo/filestore/database_name
```

<!-- [en] -->
# Coding

## Create module scaffold

<!-- [fr] -->
# Developpement

## Creer un squelette de module

<!-- [common] -->
```bash
source ./.venv.erplibre/bin/activate
python odoo/odoo-bin scaffold MODULE_NAME addons/REPO_NAME/
```

<!-- [en] -->
## Use Code generator

Read CODE_GENERATOR.md.

# Version

Read GIT_REPO.md to understand how changer version.

## Python version

Your actual version is in file .python-odoo-version. Use script `./script/version/change_python_version.sh 3.7.16` to change
to version 3.7.16 .

Run the installation, `make install_dev`.

Update poetry, `./script/poetry/poetry_update.py`.

Create docker, `make docker_build`.

### Python version major change

When you need to change python 3.7.17 to 3.8.10, do :

<!-- [fr] -->
## Utiliser le generateur de code

Lisez CODE_GENERATOR.md.

# Version

Lisez GIT_REPO.md pour comprendre comment changer de version.

## Version Python

Votre version actuelle est dans le fichier .python-odoo-version. Utilisez le script `./script/version/change_python_version.sh 3.7.16` pour changer
a la version 3.7.16 .

Lancez l'installation, `make install_dev`.

Mettez a jour poetry, `./script/poetry/poetry_update.py`.

Creez le docker, `make docker_build`.

### Changement majeur de version Python

Lorsque vous devez changer de python 3.7.17 a 3.8.10, faites :

<!-- [common] -->
```bash
rm -r .venv
make install_dev
./.venv.$(cat ".erplibre-version" | xargs)/bin/poetry lock --no-update
```

<!-- [en] -->
# Pull request

## Show all pull requests from organization

<!-- [fr] -->
# Demande de tirage (Pull request)

## Afficher toutes les demandes de tirage d'une organisation

<!-- [common] -->
```bash
/script/git/pull_request_ERPLibre.py --github_token ### --organization ERPLibre
```

<!-- [en] -->
# Commit

Use this commit format:

<!-- [fr] -->
# Commit

Utilisez ce format de commit :

<!-- [common] -->
```bash
git commit -am "[#ticket] subject: short sentence"
```

<!-- [en] -->
# Format code

## Python

Use [black](https://github.com/psf/black)

<!-- [fr] -->
# Formatage du code

## Python

Utilisez [black](https://github.com/psf/black)

<!-- [common] -->
```bash
./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator
```

<!-- [en] -->
Or if you prefer [oca-autopep8](https://github.com/psf/black)

<!-- [fr] -->
Ou si vous preferez [oca-autopep8](https://github.com/psf/black)

<!-- [common] -->
```bash
./script/maintenance/autopep8.sh ./addons/TechnoLibre_odoo-code-generator
```

<!-- [en] -->
## HTML and css

Use [prettier](https://github.com/prettier/prettier)

<!-- [fr] -->
## HTML et css

Utilisez [prettier](https://github.com/prettier/prettier)

<!-- [common] -->
```bash
./script/maintenance/prettier.sh ./addons/TechnoLibre_odoo-code-generator
```

<!-- [en] -->
## Javascript

Use [prettier](https://github.com/prettier/prettier)

<!-- [fr] -->
## Javascript

Utilisez [prettier](https://github.com/prettier/prettier)

<!-- [common] -->
```bash
./script/maintenance/prettier.sh --tab-width 4 ./addons/TechnoLibre_odoo-code-generator
```

<!-- [en] -->
# Pre-commit

You can install pre-commit to auto-format and check lint with OCA configuration. This
will run before commit with git.

Check https://github.com/OCA/maintainer-tools/wiki/Install-pre-commit

<!-- [fr] -->
# Pre-commit

Vous pouvez installer pre-commit pour auto-formater et verifier le lint avec la configuration OCA. Cela
s'executera avant chaque commit avec git.

Consultez https://github.com/OCA/maintainer-tools/wiki/Install-pre-commit
