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
./script/install/install_dev.sh
./script/install/install_locally_dev.sh
```

### 3. Run ERPLibre

```bash
./run.sh
```

## Develop in Odoo repository

You need to remove `clone-depth="10"` from `./manifest/default.dev.xml` in order to be able to commit and push. Make a
temporary commit and regenerate with `./script/install/install_locally_dev.sh`

## Fork project to create a new project independent of ERPLibre (deprecated)

ERPLibre was created with this script. It's now deprecated. Use this script when you need to fork directly from the
original source. Don't use this script if you want to update from ERPLibre and follow mainstream development.

```bash
./script/git/fork_project.py --github_token GITHUB_KEY --organization NAME
```

# Fork all repos for you own organization

Go to your Github account and generate a token to access fork option with your user. Create an organization or use your
personal account and choose your user name.

This command will fork all repos and ERPLibre to your own organization. It keeps track of ERPLibre.

```bash
./script/git/fork_project_ERPLibre.py --github_token GITHUB_KEY --organization NAME
```

## Generate manifest from csv repo

Add repo in file [./source_repo_addons.csv](./source_repo_addons.csv)

Execute to generate Repo manifest

```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

## Move database from prod to dev

Copy the database image into `./image_db/prod_client.zip` and run `make db_restore_prod_client`. This will create a
database
named `prod_client` ready to test.

When moving database from prod to your dev environment, you want to remove email servers, backups and install user test
in order to test the database. Run:

```bash
./script/database/migrate_prod_to_test.sh DATABASE
```

## Change git url https to Git

This will update all urls in Git format:

```bash
./script/git/git_change_remote_https_to_git.py
```

## Showing repo differences between projects

Tools to display the differences between the repo and another project.

```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre --dry_sync
```

## Showing repo differences with manifest develop

To understand the divergences with the dev manifest.

```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

## Sync repo with another project

Tools to synchronise the repo with another project. This will show differences and try to checkout on the same commit in
all repos.

```bash
./script/git/git_change_remote.py --sync_to /path/to/project/erplibre
```

## Compare two files manifests

To show differences between commits in different manifests

```bash
./script/git/git_diff_repo_manifest.py --input1 ./manifest/MANIFEST1.xml --input2 ./manifest/MANIFEST2.xml
```

## Differences between code and manifest

To show differences between actual code and manifest

```bash
./script/git/git_show_code_diff_repo_manifest.py --manifest ./manifest/MANIFEST1.xml
```

## Add repo

To access a new repo, add your URL to file [source_repo_addons.csv](../source_repo_addons.csv)

Fork the repo to be able to push new code:

```bash
./script/git/fork_project_ERPLibre.py
```

To regenerate only manifest.xml.

```bash
./script/git/fork_project_ERPLibre.py --skip_fork
```

Check if manifest contains "auto_install" and change the value to False.

```bash
./script/git/repo_remove_auto_install.py
```

## Filter repo by group

Only keep repo tagged by group 'base' and 'code_generator'

```bash
./script/manifest/update_manifest_local_dev_code_generator.sh
```

# Execution

## Config file

You can limit your addons in ERPlibre config file depending on a group of your actual manifest.

```bash
./script/git/git_repo_update_group.py --group base,code_generator
./script/generate_config.sh
```

Or go back to normal

```bash
./script/git/git_repo_update_group.py
./script/generate_config.sh
```

# Database

## Clean database PostgreSQL

Sometime, it's not possible to delete a database from the database manager `http://127.0.0.1:8069/web/database/manager`,
so you can do it manually. Replace `database_name` by your database name:

```bash
sudo -iu postgres
psql
```

And run:

```postgres-sql
DROP DATABASE database_name;
```

Exit and delete filestore:

```bash
rm -r ~/.local/share/Odoo/filestore/database_name
```

# Coding

## Create module scaffold

```bash
source ./.venv.erplibre/bin/activate
python odoo/odoo-bin scaffold MODULE_NAME addons/REPO_NAME/
```

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

```bash
rm -r .venv
make install_dev
./.venv.$(cat ".erplibre-version" | xargs)/bin/poetry lock --no-update
```

# Pull request

## Show all pull requests from organization

```bash
/script/git/pull_request_ERPLibre.py --github_token ### --organization ERPLibre
```

# Commit

Use this commit format:

```bash
git commit -am "[#ticket] subject: short sentence"
```

# Format code

## Python

Use [black](https://github.com/psf/black)

```bash
./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator
```

Or if you prefer [oca-autopep8](https://github.com/psf/black)

```bash
./script/maintenance/autopep8.sh ./addons/TechnoLibre_odoo-code-generator
```

## HTML and css

Use [prettier](https://github.com/prettier/prettier)

```bash
./script/maintenance/prettier.sh ./addons/TechnoLibre_odoo-code-generator
```

## Javascript

Use [prettier](https://github.com/prettier/prettier)

```bash
./script/maintenance/prettier.sh --tab-width 4 ./addons/TechnoLibre_odoo-code-generator
```

# Pre-commit

You can install pre-commit to auto-format and check lint with OCA configuration. This
will run before commit with git.

Check https://github.com/OCA/maintainer-tools/wiki/Install-pre-commit
