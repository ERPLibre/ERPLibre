
# Guide de developpement

Configurez votre environnement pour developper des modules et deboguer la plateforme.

## Procedure d'installation locale

### 1. Cloner le projet :

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

### 2. Executer le script :

```bash
cd ERPLibre
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

### 3. Lancer ERPLibre

```bash
./run.sh
```

## Developper dans le depot Odoo

Vous devez supprimer `clone-depth="10"` de `./manifest/default.dev.xml` afin de pouvoir faire des commits et des pushs. Faites un
commit temporaire et regenerez avec `./script/install/install_locally_dev.sh`

## Forker le projet pour creer un nouveau projet independant d'ERPLibre (obsolete)

ERPLibre a ete cree avec ce script. Il est maintenant obsolete. Utilisez ce script lorsque vous devez forker directement depuis la
source originale. N'utilisez pas ce script si vous voulez recevoir les mises a jour d'ERPLibre et suivre le developpement principal.

```bash
./script/git/fork_project.py --github_token GITHUB_KEY --organization NAME
```

# Forker tous les depots pour votre propre organisation

Allez dans votre compte Github et generez un jeton pour acceder a l'option de fork avec votre utilisateur. Creez une organisation ou utilisez votre
compte personnel et choisissez votre nom d'utilisateur.

Cette commande va forker tous les depots et ERPLibre vers votre propre organisation. Elle garde le suivi d'ERPLibre.

```bash
./script/git/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

## Generer le manifeste a partir du csv des depots

Ajoutez le depot dans le fichier [./source_repo_addons.csv](./source_repo_addons.csv)

Executez pour generer le manifeste Repo

```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

## Deplacer une base de donnees de la prod vers le dev

Copiez l'image de la base de donnees dans `./image_db/prod_client.zip` et executez `make db_restore_prod_client`. Cela va creer une
base de donnees
nommee `prod_client` prete a tester.

Lorsque vous deplacez une base de donnees de la prod vers votre environnement de dev, vous voulez supprimer les serveurs de courriel, les sauvegardes et installer l'utilisateur de test
afin de tester la base de donnees. Executez :

```bash
./script/database/migrate_prod_to_test.sh DATABASE
```

## Changer les urls git de https vers Git

Cela va mettre a jour toutes les urls au format Git :

```bash
./script/git/git_change_remote_https_to_git.py
```

## Afficher les differences de depots entre les projets

Outils pour afficher les differences entre le depot et un autre projet.

```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre --dry_sync
```

## Afficher les differences de depots avec le manifeste de developpement

Pour comprendre les divergences avec le manifeste de dev.

```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

## Synchroniser les depots avec un autre projet

Outils pour synchroniser le depot avec un autre projet. Cela va afficher les differences et essayer de se positionner sur le meme commit dans
tous les depots.

```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre
```

## Comparer deux fichiers manifestes

Pour afficher les differences entre les commits dans differents manifestes

```bash
./script/git/git_diff_repo_manifest.py --input1 ./manifest/MANIFEST1.xml --input2 ./manifest/MANIFEST2.xml
```

## Differences entre le code et le manifeste

Pour afficher les differences entre le code actuel et le manifeste

```bash
./script/git/git_show_code_diff_repo_manifest.py --manifest ./manifest/MANIFEST1.xml
```

## Ajouter un depot

Pour acceder a un nouveau depot, ajoutez votre URL dans le fichier [source_repo_addons.csv](../source_repo_addons.csv)

Forkez le depot pour pouvoir pousser du nouveau code :

```bash
./script/git/fork_project_ERPLibre.py
```

Pour regenerer uniquement le manifest.xml.

```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

Verifier si le manifeste contient "auto_install" et changer la valeur a False.

```bash
./script/git/repo_remove_auto_install.py
```

## Filtrer les depots par groupe

Garder uniquement les depots etiquetes par le groupe 'base' et 'code_generator'

```bash
./script/manifest/update_manifest_local_dev_code_generator.sh
```

# Execution

## Fichier de configuration

Vous pouvez limiter vos addons dans le fichier de configuration ERPLibre en fonction d'un groupe de votre manifeste actuel.

```bash
./script/git/git_repo_update_group.py --group base,code_generator
./script/generate_config.sh
```

Ou revenir a la normale

```bash
./script/git/git_repo_update_group.py
./script/generate_config.sh
```

# Base de donnees

## Nettoyer une base de donnees PostgreSQL

Parfois, il n'est pas possible de supprimer une base de donnees depuis le gestionnaire de base de donnees `http://127.0.0.1:8069/web/database/manager`,
vous pouvez donc le faire manuellement. Remplacez `database_name` par le nom de votre base de donnees :

```bash
sudo -iu postgres
psql
```

Et executez :

```postgres-sql
DROP DATABASE database_name;
```

Quittez et supprimez le filestore :

```bash
rm -r ~/.local/share/Odoo/filestore/database_name
```

# Developpement

## Creer un squelette de module

```bash
source ./.venv.erplibre/bin/activate
python odoo/odoo-bin scaffold MODULE_NAME addons/REPO_NAME/
```

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

```bash
rm -r .venv
make install_dev
./.venv.$(cat ".erplibre-version" | xargs)/bin/poetry lock --no-update
```

# Demande de tirage (Pull request)

## Afficher toutes les demandes de tirage d'une organisation

```bash
/script/git/pull_request_ERPLibre.py --github_token ### --organization ERPLibre
```

# Commit

Utilisez ce format de commit :

```bash
git commit -am "[#ticket] subject: short sentence"
```

# Formatage du code

## Python

Utilisez [black](https://github.com/psf/black)

```bash
./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator
```

Ou si vous preferez [oca-autopep8](https://github.com/psf/black)

```bash
./script/maintenance/autopep8.sh ./addons/TechnoLibre_odoo-code-generator
```

## HTML et css

Utilisez [prettier](https://github.com/prettier/prettier)

```bash
./script/maintenance/prettier.sh ./addons/TechnoLibre_odoo-code-generator
```

## Javascript

Utilisez [prettier](https://github.com/prettier/prettier)

```bash
./script/maintenance/prettier.sh --tab-width 4 ./addons/TechnoLibre_odoo-code-generator
```

# Pre-commit

Vous pouvez installer pre-commit pour auto-formater et verifier le lint avec la configuration OCA. Cela
s'executera avant chaque commit avec git.

Consultez https://github.com/OCA/maintainer-tools/wiki/Install-pre-commit