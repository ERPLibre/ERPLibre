
# Release

A guide on how to generate a release.

## Clean environment before generating new release

Before the cleaning, check if existing file isn't committed, not pushed or in stash.

```bash
.venv.erplibre/bin/repo forall -pc "git stash list"
./script/git/git_show_code_diff_repo_manifest.py
```

This will erase everything in addons. Useful before creating docker, manifest and do a release.

```bash
./script/git/clean_repo_manifest.sh
```

And update all from dev to merge into prod.

Test all supported Odoo version :

```bash
make install_odoo_all_version
```

## Validate environment

- Check if each manifest version like [manifest/git_manifest_odoo16.0.xml](../manifest/git_manifest_odoo16.0.xml) is ready for production.
- Run test :

```bash
make test_full_fast
```

### Format code

To format all code, run:

```bash
make format
```

### Update documentations

To generate Markdown in directory `./doc`, run:

```bash
make doc_markdown
```

### Test docker generate

To generate a docker, run:

```bash
make docker_build_odoo_18
```

### Rename old version to new version

Search old version, like :

```bash
grep --color=always --exclude-dir={.repo,.venv,.git} --exclude="*.svg" -nri v1.8.0
```

Replace if need it to new version.

Update file `./pyproject.toml` in [tool.poetry], line `version =`.

### Test production Ubuntu environment

Follow instructions in [PRODUCTION.md](./PRODUCTION.md).

Test installation with code generator Geomap:

```bash
make addons_install_code_generator_full
```

### Update image_db

To generate database images in directory `./image_db`, run:

```bash
make db_clean_cache
make config_gen_all
make image_db_create_all_parallel
```

To test it, you need to clean caches and install it:

```bash
./script/database/db_restore.py --clean_cache
./script/database/db_restore.py --database test --image erplibre_website
```

## Generate new prod and release

Freeze the repos versions of the active Odoo version: every project of `manifest/git_manifest_odoo<V>.xml`,
`git_manifest_odoo<V>_dev.xml` and `git_manifest_extra_odoo<V>.xml` receives the commit of its clone, next to its
branch. Check first what would change, then freeze and commit the manifest files. A clone whose commit is on no
remote branch is skipped: push it first. [GIT_REPO.md](./GIT_REPO.md#freeze-the-versions) details what is skipped.

To carry the upstream changes into the release, first upgrade the forks on their upstream and publish them
([GIT_REPO.md](./GIT_REPO.md#apply-the-upgrade)): the freeze records the published commits. Freeze with `UPSTREAM=1`,
so the release also records, in `fork-upstream-freeze-revision`, the upstream commit each fork rests on; it fetches
every declared upstream over the network.

```bash
.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run --upstream
make repo_freeze UPSTREAM=1
git add manifest/
```

An installation made from this commit follows the frozen commits with `make repo_configure_all FREEZE=1`; without the
argument, it follows the branches.

Update ERPLIBRE_VERSION variable in [env_var.sh](../env_var.sh), [Dockerfile.prod](../docker/Dockerfile.prod.pkg)
and [docker-compose](../docker-compose.yml).

Generate [poetry](./POETRY.md) and keep only missing dependencies, remove updates.

```bash
./script/poetry/poetry_update.py
```

When running script ./script/poetry/poetry_update.py, note manually inserted dependencies, stash all changes and add it
manually.

```bash
poetry add DEPENDENCY
```

Understand differences from last release:

```bash
# Get all differences between the last tag and HEAD, to update the CHANGELOG.md
# ERPLibre
git diff v#.#.#..HEAD

# All repo
.venv.erplibre/bin/repo forall -pc "git diff ERPLibre/v#.#.#..HEAD"
```

Simplification tools:

```bash
# Show all divergence repository with production
make repo_diff_manifest_production
# Short version with statistics
make repo_diff_stat_from_last_version
# Long version
make repo_diff_from_last_version
```

Update file [CHANGELOG.md](../CHANGELOG.md) and create a section with new version, use next command to read all changes.

Create a branch release/#.#.# and create a pull request to branch master with your commit:

```bash
git commit -am "Release v#.#.#"
```

Review by your peers, test the docker file and **merge to master**.

```bash
git checkout master
git merge --no-ff RELEASE_BRANCH
```

Add comment `Release v#.#.#`.

## Create tag

Add a tag on the commit in branch master with your release. The tagged commit must carry the freeze: check that
`.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run` reports no change before tagging.

```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
.venv.erplibre/bin/repo forall -pc "git tag ERPLibre/v#.#.#"
make tag_push_all
```

## Generate and push docker

Important to generate container after push git tags, otherwise the git version will be wrong.

When building your docker with script
> make docker_build_release

List your docker version
> docker images

You need to push your docker image and update your tag, like 1.0.1:
> docker push technolibre/erplibre:VERSION

## Do a release on github

Visit `https://github.com/ERPLibre/ERPLibre/releases/new` and create a release named `v#.#.#` and copy information from
CHANGELOG.md.

# TIPS

## Compare repo differences with another ERPLibre project

To generate a list of differences between repo git commit

```bash
./script/git/git_change_remote.py --sync_to /path/to/directory
```

## Semantic versioning

```
<valid semver> ::= <version core> "-" <pre-release> "+" <build>
```