
# Découverte

Explorez la solution ERPLibre.

## Installation rapide

### 1. Clonez le projet :

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

### 2. Exécutez l'installation localement :

```bash
cd ERPLibre
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

### 3. Exécutez ERPLibre

```bash
./run.sh
```

## Ajouter un dépôt

Pour accéder à un nouveau dépôt, ajoutez votre URL au fichier [source_repo_addons.csv](../source_repo_addons.csv)

Exécutez le script :

```bash
./script/git/git_repo_manifest.py
git checkout -b NEW_BRANCH
git commit -am "Add new repo"
./script/install/install_locally_dev.sh
./script/poetry/poetry_update.py
```

[Mettez à jour votre dépôt.](./GIT_REPO.md)