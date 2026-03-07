<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Discover

Explore the ERPLibre solution.

## Fast installation

### 1. Clone the project:

<!-- [fr] -->
# Découverte

Explorez la solution ERPLibre.

## Installation rapide

### 1. Clonez le projet :

<!-- [common] -->
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

<!-- [en] -->
### 2. Run installation locally:

<!-- [fr] -->
### 2. Exécutez l'installation localement :

<!-- [common] -->
```bash
cd ERPLibre
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

<!-- [en] -->
### 3. Run ERPLibre

<!-- [fr] -->
### 3. Exécutez ERPLibre

<!-- [common] -->
```bash
./run.sh
```

<!-- [en] -->
## Add repo

To access a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Execute script:

<!-- [fr] -->
## Ajouter un dépôt

Pour accéder à un nouveau dépôt, ajoutez votre URL au fichier [source_repo_addons.csv](../source_repo_addons.csv)

Exécutez le script :

<!-- [common] -->
```bash
./script/git/git_repo_manifest.py
git checkout -b NEW_BRANCH
git commit -am "Add new repo"
./script/install/install_locally_dev.sh
./script/poetry/poetry_update.py
```

<!-- [en] -->
[Update your repo.](./GIT_REPO.md)

<!-- [fr] -->
[Mettez à jour votre dépôt.](./GIT_REPO.md)
