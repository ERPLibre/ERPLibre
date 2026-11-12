
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

Le cœur d'Odoo est un clone superficiel, à la `clone-depth` de son projet dans `./manifest/git_manifest_odoo<version>.xml`.
Complétez son historique avant d'y faire des commits et des pushs :

```bash
git -C odoo<version>/odoo fetch --unshallow ERPLibre_origin_odoo ERPLibre/<version>
```

## Forker un dépôt pour votre organisation

Pour pousser vos propres commits sur un dépôt d'addons, forkez-le dans votre organisation (ou votre propre compte
GitHub) et faites prendre le fork au manifeste. Il faut un jeton GitHub autorisé à créer des dépôts dans cette
organisation (jeton classique : `public_repo`, ou `repo` pour un dépôt privé). Exportez-le dans le shell qui ouvre
TODO › Exécution › Répertoire git › Forker un dépôt pour une organisation, plutôt que de l'écrire dans `env_var.sh`,
qui est versionné et emporterait le jeton dans un commit :

```bash
export EL_GITHUB_TOKEN="<jeton>"
./todo.sh
```

Choisissez le dépôt parmi ceux des manifestes de la version active, et nommez l'organisation. L'outil demande quel
amont garde un dépôt déjà forké, s'il faut copier la branche active seulement ou toutes les branches, puis si le
manifeste prend le fork et dans quelles versions. Committez `manifest/`, puis synchronisez les dépôts pour que le clone
suive le fork. Le détail est dans [GIT_REPO.fr.md](./GIT_REPO.fr.md#forker-un-dépôt-pour-une-organisation). Les
dépôts se forkent un à la fois.

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
./script/git/git_show_code_diff_repo_manifest.py
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

TODO › Exécution › Répertoire git › Ajouter un dépôt à un manifeste demande l'URL GitHub, la version d'Odoo (l'active
par défaut) et la branche (la version par défaut). Il vérifie que la branche existe sur GitHub, déclare le projet dans
`./manifest/git_manifest_odoo<version>.xml` avec le remote de son organisation, à
`odoo<version>/addons/<organisation>_<dépôt>`, gelé sur la tête de la branche quand le manifeste est gelé, puis propose
de le forker. Un dépôt déjà dans le manifeste est refusé. Committez `manifest/`, puis synchronisez les dépôts pour le
cloner.

Les mêmes outils tournent sans le menu :

```bash
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add https://github.com/OCA/l10n-switzerland --version 18.0
./.venv.erplibre/bin/python ./script/git/manifest_repo.py fork OCA_l10n-switzerland --organisation MonOrg
./.venv.erplibre/bin/python ./script/git/manifest_repo.py branch OCA_l10n-switzerland 18.0_ma_fonction --push origin
./.venv.erplibre/bin/python ./script/git/manifest_repo.py upstream OCA_l10n-switzerland
```

`branch` crée une branche dans le clone et s'y place, puis la pousse en la faisant suivre quand `--push` nomme un
remote ; `upstream` pose le remote amont que le manifeste déclare pour un fork, et récupère sa branche. Les deux sont
aussi dans TODO › Exécution › Répertoire git.

## Retirer auto_install d'un dépôt d'addons

Passer à False chaque `auto_install` des modules de dépôts d'addons. TODO › Exécution › Analyse module › Désactiver
auto_install dans des dépôts du manifeste liste les dépôts clonés du manifeste de la version active ; cochez-en
plusieurs et ils sont traités en parallèle, avec un commit facultatif des seuls manifestes modifiés, sur la branche
courante, et un push facultatif. Le script fait de même pour les dépôts donnés, en répétant `--addons_dir` ; il
committe et pousse sauf `--ignore_commit` ou `--ignore_push`.

```bash
./script/git/repo_remove_auto_install.py --addons_dir PATH1 --addons_dir PATH2 --ignore_push
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