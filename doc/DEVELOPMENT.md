
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
