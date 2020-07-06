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
./script/install_dev.sh
./script/install_locally_dev.sh
```

### 3. Run ERPLibre
```bash
./run.sh
```

## Add repo
Access to a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Execute script:
```bash
./venv/bin/python ./script/git_repo_manifest.py
./script/install_locally_dev.sh
git commit -am "Add new repo"
```
[Update your repo.](./GIT_REPO.md)
