
# Guide de développement

Configurez votre environnement pour développer des modules et déboguer la plateforme.

## Procédure d'installation locale

### 1. Cloner le projet :

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

### 2. Exécuter le script :

```bash
cd ERPLibre
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

### 3. Lancer ERPLibre

```bash
./run.sh
```

## Développer dans le dépôt Odoo

Vous devez supprimer `clone-depth="10"` de `./manifest/default.dev.xml` afin de pouvoir faire des commits et des pushs. Faites un
commit temporaire et régénérez avec `./script/install/install_locally_dev.sh`

## Forker le projet pour créer un nouveau projet indépendant d'ERPLibre (obsolète)

ERPLibre a été créé avec ce script. Il est maintenant obsolète. Utilisez ce script lorsque vous devez forker directement depuis la
source originale. N'utilisez pas ce script si vous voulez recevoir les mises à jour d'ERPLibre et suivre le développement principal.

```bash
./script/git/fork_project.py --github_token GITHUB_KEY --organization NAME
```

# Forker tous les dépôts pour votre propre organisation

Allez dans votre compte Github et générez un jeton pour accéder à l'option de fork avec votre utilisateur. Créez une organisation ou utilisez votre
compte personnel et choisissez votre nom d'utilisateur.

Cette commande va forker tous les dépôts et ERPLibre vers votre propre organisation. Elle garde le suivi d'ERPLibre.

```bash
./script/git/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

## Générer le manifeste à partir du csv des dépôts

Ajoutez le dépôt dans le fichier [./source_repo_addons.csv](./source_repo_addons.csv)

Exécutez pour générer le manifeste Repo

```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

## Déplacer une base de données de la prod vers le dev

Copiez l'image de la base de données dans `./image_db/prod_client.zip` et exécutez `make db_restore_prod_client`. Cela va créer une
base de données
nommée `prod_client` prête à tester.

Lorsque vous déplacez une base de données de la prod vers votre environnement de dev, vous voulez supprimer les serveurs de courriel, les sauvegardes et installer l'utilisateur de test
afin de tester la base de données. Exécutez :

```bash
./script/database/migrate_prod_to_test.sh DATABASE
```

## Changer les urls git de https vers Git

Cela va mettre à jour toutes les urls au format Git :

```bash
./script/git/git_change_remote_https_to_git.py
```

## Afficher les différences de dépôts entre les projets

Outils pour afficher les différences entre le dépôt et un autre projet.

```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre --dry_sync
```

## Afficher les différences de dépôts avec le manifeste de développement

Pour comprendre les divergences avec le manifeste de dev.

```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

## Synchroniser les dépôts avec un autre projet

Outils pour synchroniser le dépôt avec un autre projet. Cela va afficher les différences et essayer de se positionner sur le même commit dans
tous les dépôts.

```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre
```

## Comparer deux fichiers manifestes

Pour afficher les différences entre les commits dans différents manifestes

```bash
./script/git/git_diff_repo_manifest.py --input1 ./manifest/MANIFEST1.xml --input2 ./manifest/MANIFEST2.xml
```

## Différences entre le code et le manifeste

Pour afficher les différences entre le code actuel et le manifeste

```bash
./script/git/git_show_code_diff_repo_manifest.py --manifest ./manifest/MANIFEST1.xml
```

## Ajouter un dépôt

Pour accéder à un nouveau dépôt, ajoutez votre URL dans le fichier [source_repo_addons.csv](../source_repo_addons.csv)

Forkez le dépôt pour pouvoir pousser du nouveau code :

```bash
./script/git/fork_project_ERPLibre.py
```

Pour régénérer uniquement le manifest.xml.

```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

Vérifier si le manifeste contient "auto_install" et changer la valeur à False.

```bash
./script/git/repo_remove_auto_install.py
```

## Filtrer les dépôts par groupe

Garder uniquement les dépôts étiquetés par le groupe 'base' et 'code_generator'

```bash
./script/manifest/update_manifest_local_dev_code_generator.sh
```

# Exécution

## Fichier de configuration

Vous pouvez limiter vos addons dans le fichier de configuration ERPLibre en fonction d'un groupe de votre manifeste actuel.

```bash
./script/git/git_repo_update_group.py --group base,code_generator
./script/generate_config.sh
```

Ou revenir à la normale

```bash
./script/git/git_repo_update_group.py
./script/generate_config.sh
```

# Base de données

## Nettoyer une base de données PostgreSQL

Parfois, il n'est pas possible de supprimer une base de données depuis le gestionnaire de base de données `http://127.0.0.1:8069/web/database/manager`,
vous pouvez donc le faire manuellement. Remplacez `database_name` par le nom de votre base de données :

```bash
sudo -iu postgres
psql
```

Et exécutez :

```postgres-sql
DROP DATABASE database_name;
```

Quittez et supprimez le filestore :

```bash
rm -r ~/.local/share/Odoo/filestore/database_name
```

# Développement

## Créer un squelette de module

```bash
source ./.venv.erplibre/bin/activate
python odoo/odoo-bin scaffold MODULE_NAME addons/REPO_NAME/
```

## Utiliser le générateur de code

Lisez CODE_GENERATOR.md.

# Version

Lisez GIT_REPO.md pour comprendre comment changer de version.

## Version Python

Votre version actuelle est dans le fichier .python-odoo-version. Utilisez le script `./script/version/change_python_version.sh 3.7.16` pour changer
à la version 3.7.16 .

Lancez l'installation, `make install_dev`.

Mettez à jour poetry, `./script/poetry/poetry_update.py`.

Créez le docker, `make docker_build`.

### Changement majeur de version Python

Lorsque vous devez changer de python 3.7.17 à 3.8.10, faites :

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

Ou si vous préférez [oca-autopep8](https://github.com/psf/black)

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

Vous pouvez installer pre-commit pour auto-formater et vérifier le lint avec la configuration OCA. Cela
s'exécutera avant chaque commit avec git.

Consultez https://github.com/OCA/maintainer-tools/wiki/Install-pre-commit