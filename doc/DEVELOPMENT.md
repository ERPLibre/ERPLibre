# Development guide
Setup your environment to develop modules and debug the platform.

## Installation procedure locally
### 1. Clone the project:
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
```

### 2. Execute the script:
```bash
cd ERPLibre
./script/install_dev.sh
./script/install_locally_dev.sh
```

### 3. Run ERPLibre
```bash
./run.sh
```

## Fork project to create a new project independent of ERPLibre (deprecated)
ERPLibre was created by this script. It's now deprecated.
Use this script when you need to fork directly from the original source.
Don't use this script if you want to update from ERPLibre and follow mainstream development.
```bash
./venv/bin/python ./script/fork_project.py --github_token GITHUB_KEY --organization NAME
```

# Fork all repo for you own organization
Go to your github account and generate a token to access fork option with your user. Create an organization (or you can choose your user name).

This command will fork all repos and ERPLibre to your own organization. It keeps track to ERPLibre.
```bash
./venv/bin/python ./script/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

## Generate manifest from csv repo
Add repo in file [./source_repo_addons.csv](./source_repo_addons.csv)

Execute to generate manifest of Repo
```bash
./venv/bin/python ./script/fork_project_ERPLibre.py --skip_fork
```

## Move database prod to dev
When moving database prod to your dev environment, you want to remove email servers, and install user test in order to test the database.
Run:
```bash
./run.sh --stop-after-init -i user_test,disable_mail_server --dev all -d DATABASE
```

# TODO
```bash
./venv/bin/python ./script/git_change_remote.py
```

## Change git url https to git
This will update all urls in git format:
```bash
./venv/bin/python ./script/git_change_remote_https_to_git.py
```

## Diff repo with another project
Tools to display the differences between the repo and another project.
```bash
./venv/bin/python ./script/list_repo_diff.py --sync_to /path/to/project/erplibre --dyr_sync
```

## Sync repo with another project
Tools to synchronise the repo with another project. This will show differences and try to checkout on the same commit in all repo.
```bash
./venv/bin/python ./script/git_change_remote.py --sync_to /path/to/project/erplibre
```

## Add repo
Access to a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Fork the repo to be able to push new code:
```bash
./venv/bin/python ./script/fork_project_ERPLibre.py
```

To regenerate only manifest.xml.
```bash
./venv/bin/python ./script/fork_project_ERPLibre.py --skip_fork
```
