# Discover

Explore the ERPLibre solution.

## Fast installation

### 1. Clone the project:

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

### 2. Run installation locally:

```bash
cd ERPLibre
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

### 3. Run ERPLibre

```bash
./run.sh
```

## Add repo

To access a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Execute script:

```bash
./script/git/git_repo_manifest.py
git checkout -b NEW_BRANCH
git commit -am "Add new repo"
./script/install/install_locally_dev.sh
./script/poetry/poetry_update.py
```

[Update your repo.](./GIT_REPO.md)
