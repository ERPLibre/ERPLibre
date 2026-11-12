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

To access a new repo, add a `<project>` for it, and its `<remote>` if the organisation is new, to
`./manifest/git_manifest_odoo<version>.xml`, then:

<!-- [fr] -->
## Ajouter un dépôt

Pour accéder à un nouveau dépôt, ajoutez son `<project>`, et son `<remote>` si l'organisation est nouvelle, à
`./manifest/git_manifest_odoo<version>.xml`, puis :

<!-- [common] -->
```bash
git checkout -b NEW_BRANCH
git commit -am "Add new repo"
./script/install/install_locally_dev.sh
./script/poetry/poetry_update.py
```

<!-- [en] -->
[Update your repo.](./GIT_REPO.md)

<!-- [fr] -->
[Mettez à jour votre dépôt.](./GIT_REPO.md)
