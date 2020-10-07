# Development guide
Setup your environment to develop modules and debug the platform.

## Local installation procedure
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

## Develop in Odoo repository
Odoo repository has partial git history for fastest deployment. You need to restore the history to be able to push.

## Solution 1
```bash
cd odoo
git fetch --unshallow odoo
```

### Solution 2
You need to remove `clone-depth="10"` from `./manifest/default.dev.xml` in order to be able to commit and push.
Make a temporary commit and regenerate with `./script/install_locally_dev.sh`

## Fork project to create a new project independent from ERPLibre (deprecated)
ERPLibre was created by this script. It's now deprecated.
Use this script when you need to fork directly from the original source.
Don't use this script if you want to update from ERPLibre and follow mainstream development.
```bash
./script/fork_project.py --github_token GITHUB_KEY --organization NAME
```

# Fork all repos for you own organization
Go to your github account and generate a token to access fork option with your user. Create an organization or use your personal account can choose your user name.

This command will fork all repos and ERPLibre to your own organization. It keeps track to ERPLibre.
```bash
./script/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

## Generate manifest from csv repo
Add repo in file [./source_repo_addons.csv](./source_repo_addons.csv)

Execute to generate Repo manifest
```bash
./script/fork_project_ERPLibre.py --skip_fork
```

## Move database prod to dev
When moving database prod to your dev environment, you want to remove email servers and install user test in order to test the database.
Run:
```bash
./run.sh --stop-after-init -i user_test,disable_mail_server --dev all -d DATABASE
```

# TODO
```bash
./script/git_change_remote.py
```

## Change git url https to git
This will update all urls in git format:
```bash
./script/git_change_remote_https_to_git.py
```

## Showing repo differences between projects
Tools to display the differences between the repo and another project.
```bash
./script/git_change_remote.py --sync_to /path/to/project/erplibre --dry_sync
```

## Sync repo with another project
Tools to synchronise the repo with another project. This will show differences and try to checkout on the same commit in all repos.
```bash
./script/git_change_remote.py --sync_to /path/to/project/erplibre
```

## Compare two files manifests
To show differences between commits in different manifests
```bash
./script/git_diff_repo_manifest.py --input1 ./manifest/MANIFEST1.xml --input2 ./manifest/MANIFEST2.xml
```

## Differences between code and manifest
To show differences between actual code and manifest
```bash
./script/git_show_code_diff_repo_manifest.py --manifest ./manifest/MANIFEST1.xml
```

## Add repo
To access a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Fork the repo to be able to push new code:
```bash
./script/fork_project_ERPLibre.py
```

To regenerate only manifest.xml.
```bash
./script/fork_project_ERPLibre.py --skip_fork
```

Check if  manifest contains "auto_install" and change the value to False.
```bash
./script/repo_remove_auto_install.py
```

# Coding
## Create module scaffold
```bash
source ./.venv/bin/activate
python odoo/odoo-bin scaffold MODULE_NAME addons/REPO_NAME/
```

# Pull request
## Show all pull requests from organization
```bash
/script/pull_request_ERPLibre.py --github_token ### --organization ERPLibre
```
