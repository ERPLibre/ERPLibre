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
# Guide de développement

Configurez votre environnement pour développer des modules et déboguer la plateforme.

## Procédure d'installation locale

### 1. Cloner le projet :

<!-- [common] -->
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

<!-- [en] -->
### 2. Execute the script:

<!-- [fr] -->
### 2. Exécuter le script :

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

The Odoo core is a shallow clone, at the `clone-depth` of its project in `./manifest/git_manifest_odoo<version>.xml`.
Complete its history before committing and pushing in it:

```bash
git -C odoo<version>/odoo fetch --unshallow ERPLibre_origin_odoo ERPLibre/<version>
```

<!-- [fr] -->
## Développer dans le dépôt Odoo

Le cœur d'Odoo est un clone superficiel, à la `clone-depth` de son projet dans `./manifest/git_manifest_odoo<version>.xml`.
Complétez son historique avant d'y faire des commits et des pushs :

```bash
git -C odoo<version>/odoo fetch --unshallow ERPLibre_origin_odoo ERPLibre/<version>
```

<!-- [en] -->
## Fork a repository for your organisation

To push your own commits on an addons repository, fork it into your organisation (or your own GitHub account) and
make the manifest take the fork. You need a GitHub token allowed to create repositories in that organisation
(classic token: `public_repo`, or `repo` for a private repository). Export it in the shell that opens TODO ›
Execute › Git repository › Fork a repository for an organisation, rather than writing it into `env_var.sh`, which is
versioned and would carry the token into a commit:

```bash
export EL_GITHUB_TOKEN="<token>"
./todo.sh
```

Without an exported token, TODO › Execute › Git repository › Check the GitHub token offers an assistant, also
offered when a GitHub action is refused. It shows both kinds of token — classic, on a page pre-filled with `repo`,
`workflow` and `read:org`; fine-grained, with the rights to tick — reads the token without echo, checks it, and stores
it in the ERPLibre KeePass vault (`kdbx.path` in `script/todo/todo.json`), under the title given by
`kdbx_config.github.kdbx_key`, `GitHub token` by default. The token is read from `EL_GITHUB_TOKEN`, then the vault,
then `env_var.sh`.

Choose the repository among those of the manifests of the active version, and name the organisation. The tool asks
which upstream an already forked repository keeps, whether to copy the active branch only or every branch, then whether
the manifest takes the fork and in which versions. Commit `manifest/`, then synchronise the repositories so the clone
follows the fork. The details are in [GIT_REPO.md](./GIT_REPO.md#fork-a-repository-for-an-organisation). Repositories
are forked one at a time.

<!-- [fr] -->
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

Sans jeton exporté, TODO › Exécution › Répertoire git › Vérifier le jeton GitHub propose un assistant, aussi proposé
quand une action GitHub est refusée. Il présente les deux sortes de jeton — classique, sur une page préremplie avec
`repo`, `workflow` et `read:org` ; à granularité fine, avec les droits à cocher —, lit le jeton sans écho, le vérifie,
et le range dans le coffre KeePass d'ERPLibre (`kdbx.path` dans `script/todo/todo.json`), sous le titre que donne
`kdbx_config.github.kdbx_key`, `GitHub token` par défaut. Le jeton se lit dans `EL_GITHUB_TOKEN`, puis le coffre, puis
`env_var.sh`.

Choisissez le dépôt parmi ceux des manifestes de la version active, et nommez l'organisation. L'outil demande quel
amont garde un dépôt déjà forké, s'il faut copier la branche active seulement ou toutes les branches, puis si le
manifeste prend le fork et dans quelles versions. Committez `manifest/`, puis synchronisez les dépôts pour que le clone
suive le fork. Le détail est dans [GIT_REPO.fr.md](./GIT_REPO.fr.md#forker-un-dépôt-pour-une-organisation). Les
dépôts se forkent un à la fois.

<!-- [en] -->
## Move database from prod to dev

Copy the database image into `./image_db/prod_client.zip` and run `make db_restore_prod_client`. This will create a
database
named `prod_client` ready to test.

When moving database from prod to your dev environment, you want to remove email servers, backups and install user test
in order to test the database. Run:

<!-- [fr] -->
## Déplacer une base de données de la prod vers le dev

Copiez l'image de la base de données dans `./image_db/prod_client.zip` et exécutez `make db_restore_prod_client`. Cela va créer une
base de données
nommée `prod_client` prête à tester.

Lorsque vous déplacez une base de données de la prod vers votre environnement de dev, vous voulez supprimer les serveurs de courriel, les sauvegardes et installer l'utilisateur de test
afin de tester la base de données. Exécutez :

<!-- [common] -->
```bash
./script/database/migrate_prod_to_test.sh DATABASE
```

<!-- [en] -->
## Change git url https to Git

This will update all urls in Git format:

<!-- [fr] -->
## Changer les urls git de https vers Git

Cela va mettre à jour toutes les urls au format Git :

<!-- [common] -->
```bash
./script/git/git_change_remote_https_to_git.py
```

<!-- [en] -->
## Showing repo differences between projects

Tools to display the differences between the repo and another project.

<!-- [fr] -->
## Afficher les différences de dépôts entre les projets

Outils pour afficher les différences entre le dépôt et un autre projet.

<!-- [common] -->
```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre --dry_sync
```

<!-- [en] -->
## Showing repo differences with manifest develop

To understand the divergences with the dev manifest.

<!-- [fr] -->
## Afficher les différences de dépôts avec le manifeste de développement

Pour comprendre les divergences avec le manifeste de dev.

<!-- [common] -->
```bash
./script/git/git_show_code_diff_repo_manifest.py
```

<!-- [en] -->
## Sync repo with another project

Tools to synchronise the repo with another project. This will show differences and try to checkout on the same commit in
all repos.

<!-- [fr] -->
## Synchroniser les dépôts avec un autre projet

Outils pour synchroniser le dépôt avec un autre projet. Cela va afficher les différences et essayer de se positionner sur le même commit dans
tous les dépôts.

<!-- [common] -->
```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre
```

<!-- [en] -->
## Compare two files manifests

To show differences between commits in different manifests

<!-- [fr] -->
## Comparer deux fichiers manifestes

Pour afficher les différences entre les commits dans différents manifestes

<!-- [common] -->
```bash
./script/git/git_diff_repo_manifest.py --input1 ./manifest/MANIFEST1.xml --input2 ./manifest/MANIFEST2.xml
```

<!-- [en] -->
## Differences between code and manifest

To show differences between actual code and manifest

<!-- [fr] -->
## Différences entre le code et le manifeste

Pour afficher les différences entre le code actuel et le manifeste

<!-- [common] -->
```bash
./script/git/git_show_code_diff_repo_manifest.py --manifest ./manifest/MANIFEST1.xml
```

<!-- [en] -->
## Add repo

TODO › Execute › Git repository › Add a repository to a manifest asks for the repository URL, then the Odoo version
only when several are installed (`.repo/installed_odoo_version.txt`): a single installed version is taken without a
question, and versions that are not installed are never offered. It then asks, with no default, whether the repository
goes to the public manifest, `./manifest/git_manifest_odoo<version>.xml`, published with ERPLibre, or to the private
one, `./private/manifest/git_manifest_private_odoo<version>.xml`, created when missing and listed in
`./private/default_git_manifest.csv` so the merge reads it. One `git ls-remote --symref <url> HEAD 'refs/heads/*'`, with
no clone and no GitHub token, reads the branches and the host's default branch: the branch offered is the version when
the host has it, its default branch otherwise (`main`, for instance). A private repository git cannot read without
credentials can still be added, unchecked and unfrozen. The project is declared with its organisation's remote, at
`odoo<version>/addons/<organisation>_<repository>`, frozen on the head of the branch when the manifest is frozen; a
public GitHub repository is then offered for a fork. A repository already in either manifest is refused. Commit
`manifest/` or `private/`, then synchronise the repositories to clone it.

Add a repository from an existing directory lists the git clones under the installed `odoo<version>/` that no manifest
declares, takes a typed path, or opens the file browser on Enter. Without network, it reads in the clone its URL, the branch it tracks and its HEAD,
asks public or private, and declares it at its own path, frozen on HEAD only when HEAD is pushed. `repo sync` refuses a
clone it did not make (`unsupported checkout state`): the tool offers to rename it aside, as
`.<name>.avant_repo`, kept and never deleted, then lets repo clone it again. It refuses to move a clone with
uncommitted work or an unpushed HEAD.

The same tools run without the menu:

```bash
# Declare a GitHub repository in the manifest of an Odoo version, frozen on the branch head if the manifest is frozen
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add https://github.com/OCA/l10n-switzerland --version 18.0

# Same, in the private manifest; without --branch, the version if the host has it, else its default branch
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add https://github.com/MyOrg/my-addons --private

# Declare a clone that already exists, at its path and on its tracked branch, then set it aside for repo to reclone
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add-local odoo18.0/addons/addons --private --set-aside

# Fork the repository into an organisation through the API, then make the active version's manifest take the fork
./.venv.erplibre/bin/python ./script/git/manifest_repo.py fork OCA_l10n-switzerland --organisation MyOrg

# Create a branch in the clone, switch to it, and push it with tracking to the named remote
./.venv.erplibre/bin/python ./script/git/manifest_repo.py branch OCA_l10n-switzerland 18.0_my_feature --push origin

# Add the upstream remote the manifest declares for a fork, and fetch its branch
./.venv.erplibre/bin/python ./script/git/manifest_repo.py upstream OCA_l10n-switzerland

# List the open pull requests, in an organisation, of every repository of the manifest
./.venv.erplibre/bin/python ./script/git/manifest_repo.py pulls --organisation MyOrg

# Open a pull request from the clone's current branch, once pushed, towards the declared upstream
./.venv.erplibre/bin/python ./script/git/manifest_repo.py pr OCA_l10n-switzerland --title "Fix the invoice report" --target amont

# Remove the project from its manifest, its remote too if unused; --apply also syncs, deleting a clean clone
./.venv.erplibre/bin/python ./script/git/manifest_repo.py remove OCA_l10n-switzerland --apply

# Regenerate the local manifest and synchronise this clone only
./.venv.erplibre/bin/python ./script/git/manifest_repo.py sync OCA_l10n-switzerland

# Freeze the project on its clone's HEAD (or --commit) in the manifest, with its upstream base
./.venv.erplibre/bin/python ./script/git/manifest_repo.py refreeze OCA_l10n-switzerland

# Create the same branch in several clones in parallel, pushed to each project's remote
./.venv.erplibre/bin/python ./script/git/manifest_repo.py branches 18.0_my_feature OCA_web OCA_server-tools --push

# Status of the token account's pull requests: review, CI, merged or closed
./.venv.erplibre/bin/python ./script/git/manifest_repo.py mine

# Delete the merged branches of the clone, on the fork remotes too, squash-merged ones included
./.venv.erplibre/bin/python ./script/git/manifest_repo.py prune OCA_web --fetch --github --apply --remote

# Update every fork of the active version from its upstream on GitHub (merge-upstream)
./.venv.erplibre/bin/python ./script/git/manifest_repo.py fork-sync

# Check the token's scopes and its account's membership of the organisation
./.venv.erplibre/bin/python ./script/git/manifest_repo.py token --organisation MyOrg

# List the organisation's forks that no manifest clones any more
./.venv.erplibre/bin/python ./script/git/manifest_repo.py orphans MyOrg
```

`pulls` lists the open pull requests, in an organisation, of every repository of the manifest; `pr` opens one from the
current branch of the clone, once pushed, towards the upstream (`amont`) or the repository of the manifest
(`manifeste`). `branch` creates a branch in the clone and switches to it, then pushes it with tracking when `--push` names a remote;
`upstream` adds the upstream remote the manifest declares for a fork, and fetches its branch. Both are also in TODO ›
Execute › Git repository.

`remove` takes the project out of its manifest file; `--apply` also regenerates the local manifest and synchronises, which deletes a clean clone; `sync` synchronises one clone, and `refreeze` writes its
head, or `--commit`, into the manifest with the upstream base. `branches` creates the same branch in several clones in
parallel. `mine` shows the token account's pull requests with their review and CI state. `prune` lists the merged
branches of a clone and deletes them with `--apply`, on the fork remotes too with `--remote`; `--github` adds those
merged by squash. `fork-sync` updates the manifest's forks from their upstream on GitHub, when the fork's GitHub parent
is the declared upstream. `token` reports the token's scopes and membership; `orphans` lists the forks of an
organisation that no manifest clones any more. Each is also in TODO › Execute › Git repository.

<!-- [fr] -->
## Ajouter un dépôt

TODO › Exécution › Répertoire git › Ajouter un dépôt à un manifeste demande l'URL du dépôt, puis la version d'Odoo
seulement quand plusieurs sont installées (`.repo/installed_odoo_version.txt`) : une seule version installée est prise
sans question, et une version non installée n'est jamais proposée. Il demande ensuite, sans défaut, si le dépôt va au
manifeste public, `./manifest/git_manifest_odoo<version>.xml`, publié avec ERPLibre, ou au privé,
`./private/manifest/git_manifest_private_odoo<version>.xml`, créé s'il manque et inscrit dans
`./private/default_git_manifest.csv` pour que la fusion le lise. Un seul `git ls-remote --symref <url> HEAD
'refs/heads/*'`, sans clone ni jeton GitHub, lit les branches et la branche par défaut de l'hôte : la branche proposée est
la version quand l'hôte l'a, sinon sa branche par défaut (`main`, par exemple). Un dépôt privé que git ne sait pas lire
sans identifiants s'ajoute quand même, sans vérification ni gel. Le projet est déclaré avec le remote de son
organisation, à `odoo<version>/addons/<organisation>_<dépôt>`, gelé sur la tête de la branche quand le manifeste est
gelé ; un dépôt GitHub public se voit ensuite proposer un fork. Un dépôt déjà dans l'un ou l'autre manifeste est refusé.
Committez `manifest/` ou `private/`, puis synchronisez les dépôts pour le cloner.

Ajouter un dépôt depuis un répertoire existant liste les clones git sous les `odoo<version>/` installés qu'aucun
manifeste ne déclare, prend un chemin tapé, ou ouvre le navigateur de fichiers sur Entrée. Sans réseau, il lit dans le clone son URL, la branche qu'il suit et son
HEAD, demande public ou privé, et le déclare à son propre chemin, gelé sur HEAD seulement quand HEAD est poussé. `repo
sync` refuse un clone qu'il n'a pas fait (`unsupported checkout state`) : l'outil propose de le renommer de côté, en
`.<nom>.avant_repo`, gardé et jamais supprimé, puis laisse repo le recloner. Il refuse de déplacer un clone au travail
non commité ou au HEAD non poussé.

Les mêmes outils tournent sans le menu :

```bash
# Déclarer un dépôt GitHub dans le manifeste d'une version d'Odoo, gelé sur la tête de branche si le manifeste l'est
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add https://github.com/OCA/l10n-switzerland --version 18.0

# Pareil, dans le manifeste privé ; sans --branch, la version si l'hôte l'a, sinon sa branche par défaut
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add https://github.com/MonOrg/mes-addons --private

# Déclarer un clone qui existe déjà, à son chemin et sur sa branche suivie, puis le mettre de côté pour que repo le reclone
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add-local odoo18.0/addons/addons --private --set-aside

# Forker le dépôt dans une organisation par l'API, puis faire prendre le fork au manifeste de la version active
./.venv.erplibre/bin/python ./script/git/manifest_repo.py fork OCA_l10n-switzerland --organisation MonOrg

# Créer une branche dans le clone, s'y placer, et la pousser en la faisant suivre vers le remote nommé
./.venv.erplibre/bin/python ./script/git/manifest_repo.py branch OCA_l10n-switzerland 18.0_ma_fonction --push origin

# Poser le remote amont que le manifeste déclare pour un fork, et récupérer sa branche
./.venv.erplibre/bin/python ./script/git/manifest_repo.py upstream OCA_l10n-switzerland

# Lister les pull requests ouvertes, dans une organisation, de chaque dépôt du manifeste
./.venv.erplibre/bin/python ./script/git/manifest_repo.py pulls --organisation MonOrg

# Ouvrir une pull request depuis la branche courante du clone, une fois poussée, vers l'amont déclaré
./.venv.erplibre/bin/python ./script/git/manifest_repo.py pr OCA_l10n-switzerland --title "Corriger le rapport de facture" --target amont

# Retirer le projet de son manifeste, et son remote s'il ne sert plus ; --apply synchronise aussi, ce qui supprime un clone propre
./.venv.erplibre/bin/python ./script/git/manifest_repo.py remove OCA_l10n-switzerland --apply

# Régénérer le manifeste local et synchroniser ce seul clone
./.venv.erplibre/bin/python ./script/git/manifest_repo.py sync OCA_l10n-switzerland

# Geler le projet sur la tête de son clone (ou --commit) dans le manifeste, avec sa base amont
./.venv.erplibre/bin/python ./script/git/manifest_repo.py refreeze OCA_l10n-switzerland

# Créer la même branche dans plusieurs clones en parallèle, poussée vers le remote de chaque projet
./.venv.erplibre/bin/python ./script/git/manifest_repo.py branches 18.0_ma_fonction OCA_web OCA_server-tools --push

# État des pull requests du compte du jeton : revue, CI, fusionnée ou fermée
./.venv.erplibre/bin/python ./script/git/manifest_repo.py mine

# Supprimer les branches fusionnées du clone, sur les remotes de fork aussi, celles fusionnées par squash comprises
./.venv.erplibre/bin/python ./script/git/manifest_repo.py prune OCA_web --fetch --github --apply --remote

# Mettre à jour chaque fork de la version active depuis son amont sur GitHub (merge-upstream)
./.venv.erplibre/bin/python ./script/git/manifest_repo.py fork-sync

# Vérifier les portées du jeton et l'adhésion de son compte à l'organisation
./.venv.erplibre/bin/python ./script/git/manifest_repo.py token --organisation MonOrg

# Lister les forks de l'organisation qu'aucun manifeste ne clone plus
./.venv.erplibre/bin/python ./script/git/manifest_repo.py orphans MonOrg
```

`pulls` liste les pull requests ouvertes, dans une organisation, de chaque dépôt du manifeste ; `pr` en ouvre une depuis
la branche courante du clone, une fois poussée, vers l'amont (`amont`) ou le dépôt du manifeste (`manifeste`). `branch`
crée une branche dans le clone et s'y place, puis la pousse en la faisant suivre quand `--push` nomme un
remote ; `upstream` pose le remote amont que le manifeste déclare pour un fork, et récupère sa branche. Les deux sont
aussi dans TODO › Exécution › Répertoire git.

`remove` sort le projet de son fichier manifeste ; `--apply` régénère aussi le manifeste local et synchronise, ce qui supprime un clone propre ; `sync` synchronise un seul clone, et `refreeze` écrit
sa tête, ou `--commit`, dans le manifeste avec la base amont. `branches` crée la même branche dans plusieurs clones, en
parallèle. `mine` montre les pull requests du compte du jeton avec leur revue et l'état de leur CI. `prune` liste les
branches fusionnées d'un clone et les supprime avec `--apply`, sur les remotes de fork aussi avec `--remote` ;
`--github` ajoute celles fusionnées par squash. `fork-sync` met les forks du manifeste à jour depuis leur amont sur
GitHub, quand le parent GitHub du fork est l'amont déclaré. `token` donne les portées et l'adhésion du jeton ;
`orphans` liste les forks d'une organisation qu'aucun manifeste ne clone plus. Chacun est aussi dans TODO › Exécution ›
Répertoire git.

<!-- [en] -->
## Remove auto_install from an addons repository

Set every `auto_install` to False in the modules of addons repositories. TODO › Execute › Analyse module › Disable
auto_install in repositories of the manifest lists the cloned repositories of the active version's manifest; check
several and they are handled in parallel, with an optional commit of the changed manifests only, on the current
branch, and an optional push. The script does the same for the repositories given, repeating `--addons_dir`; it
commits and pushes unless `--ignore_commit` or `--ignore_push`.

<!-- [fr] -->
## Retirer auto_install d'un dépôt d'addons

Passer à False chaque `auto_install` des modules de dépôts d'addons. TODO › Exécution › Analyse module › Désactiver
auto_install dans des dépôts du manifeste liste les dépôts clonés du manifeste de la version active ; cochez-en
plusieurs et ils sont traités en parallèle, avec un commit facultatif des seuls manifestes modifiés, sur la branche
courante, et un push facultatif. Le script fait de même pour les dépôts donnés, en répétant `--addons_dir` ; il
committe et pousse sauf `--ignore_commit` ou `--ignore_push`.

<!-- [common] -->
```bash
./script/git/repo_remove_auto_install.py --addons_dir PATH1 --addons_dir PATH2 --ignore_push
```

<!-- [en] -->
## Filter repo by group

Only keep repo tagged by group 'base' and 'code_generator'

<!-- [fr] -->
## Filtrer les dépôts par groupe

Garder uniquement les dépôts étiquetés par le groupe 'base' et 'code_generator'

<!-- [common] -->
```bash
./script/manifest/update_manifest_local_dev_code_generator.sh
```

<!-- [en] -->
# Execution

## Config file

You can limit your addons in ERPlibre config file depending on a group of your actual manifest.

<!-- [fr] -->
# Exécution

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
Ou revenir à la normale

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
# Base de données

## Nettoyer une base de données PostgreSQL

Parfois, il n'est pas possible de supprimer une base de données depuis le gestionnaire de base de données `http://127.0.0.1:8069/web/database/manager`,
vous pouvez donc le faire manuellement. Remplacez `database_name` par le nom de votre base de données :

<!-- [common] -->
```bash
sudo -iu postgres
psql
```

<!-- [en] -->
And run:

<!-- [fr] -->
Et exécutez :

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
# Développement

## Créer un squelette de module

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

<!-- [common] -->
```bash
rm -r .venv
make install_dev
./.venv.$(cat ".erplibre-version" | xargs)/bin/poetry lock --no-update
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
Ou si vous préférez [oca-autopep8](https://github.com/psf/black)

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

Vous pouvez installer pre-commit pour auto-formater et vérifier le lint avec la configuration OCA. Cela
s'exécutera avant chaque commit avec git.

Consultez https://github.com/OCA/maintainer-tools/wiki/Install-pre-commit
