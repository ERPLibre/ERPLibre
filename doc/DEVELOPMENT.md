
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

The Odoo core is a shallow clone, at the `clone-depth` of its project in `./manifest/git_manifest_odoo<version>.xml`.
Complete its history before committing and pushing in it:

```bash
git -C odoo<version>/odoo fetch --unshallow ERPLibre_origin_odoo ERPLibre/<version>
```

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

Choose the repository among those of the manifests of the active version, and name the organisation. The tool asks
which upstream an already forked repository keeps, whether to copy the active branch only or every branch, then whether
the manifest takes the fork and in which versions. Commit `manifest/`, then synchronise the repositories so the clone
follows the fork. The details are in [GIT_REPO.md](./GIT_REPO.md#fork-a-repository-for-an-organisation). Repositories
are forked one at a time.

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
./script/git/git_show_code_diff_repo_manifest.py
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

TODO › Execute › Git repository › Add a repository to a manifest asks for the GitHub URL, the Odoo version (the active
one by default) and the branch (the version by default). It checks that the branch exists on GitHub, declares the
project in `./manifest/git_manifest_odoo<version>.xml` with its organisation's remote, at
`odoo<version>/addons/<organisation>_<repository>`, frozen on the head of the branch when the manifest is frozen, then
offers to fork it. A repository already in the manifest is refused. Commit `manifest/`, then synchronise the
repositories to clone it.

The same tools run without the menu:

```bash
./.venv.erplibre/bin/python ./script/git/manifest_repo.py add https://github.com/OCA/l10n-switzerland --version 18.0
./.venv.erplibre/bin/python ./script/git/manifest_repo.py fork OCA_l10n-switzerland --organisation MyOrg
./.venv.erplibre/bin/python ./script/git/manifest_repo.py branch OCA_l10n-switzerland 18.0_my_feature --push origin
./.venv.erplibre/bin/python ./script/git/manifest_repo.py upstream OCA_l10n-switzerland
```

`branch` creates a branch in the clone and switches to it, then pushes it with tracking when `--push` names a remote;
`upstream` adds the upstream remote the manifest declares for a fork, and fetches its branch. Both are also in TODO ›
Execute › Git repository.

## Remove auto_install from an addons repository

Set every `auto_install` to False in the modules of addons repositories. TODO › Execute › Analyse module › Disable
auto_install in repositories of the manifest lists the cloned repositories of the active version's manifest; check
several and they are handled in parallel, with an optional commit of the changed manifests only, on the current
branch, and an optional push. The script does the same for the repositories given, repeating `--addons_dir`; it
commits and pushes unless `--ignore_commit` or `--ignore_push`.

```bash
./script/git/repo_remove_auto_install.py --addons_dir PATH1 --addons_dir PATH2 --ignore_push
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
