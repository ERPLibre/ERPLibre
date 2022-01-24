# Release

A guide on how to generate a release.

## Clean environment before generating new release

Before the cleaning, check if existing file isn't committed, not pushed or in stash.

```bash
./.venv/repo forall -pc "git stash list"
./script/git_show_code_diff_repo_manifest.py
```

This will erase everything in addons. Useful before creating docker, manifest and do a release.

```bash
./script/clean_repo_manifest.sh
```

And update all from dev to merge into prod.

```bash
./script/install_locally_dev.sh
```

## Validate environment

- Check if [manifest/default.dev.xml](../manifest/default.dev.xml) is ready for production.
- Run test :

```bash
make test
```

### Format code

To format all code, run:

```bash
make format
```

### Update image_db

To generate database images in directory `./image_db`, run:

```bash
make config_gen_all
make image_db_create_all
```

### Update documentations

To generate Markdown in directory `./doc`, run:

```bash
make doc_markdown
```

### Test docker generate

To generate a docker, run:

```bash
make docker_build
```

### Rename old version to new version

Search old version, like :
```bash
grep --color=always --exclude-dir={.repo,.venv,.git} --exclude="*.svg" -nri v1.2.0
```

Replace if need it to new version.

Update file `./pyproject.toml` in [tool.poetry], line `version =`.

### Test production Ubuntu environment

Follow instructions in [PRODUCTION.md](./PRODUCTION.md).

Test installation with code generator Geomap:

```bash
make addons_install_code_generator_full
```

## Generate new prod and release

Generate production manifest and freeze all repos versions.

```bash
./.venv/repo manifest -r -o ./default.xml
```

Update ERPLIBRE_VERSION variable in [env_var.sh](../env_var.sh), [Dockerfile.prod](../docker/Dockerfile.prod.pkg) and [docker-compose](../docker-compose.yml).

Generate [poetry](./POETRY.md) and keep only missing dependencies, remove updates.

```bash
./script/poetry_update.py
```

When running script poetry_update.py, note manually inserted dependencies, stash all changes and add it manually.

```bash
poetry add DEPENDENCY
```

Understand differences from last release:

```bash
# Get all differences between the last tag and HEAD, to update the CHANGELOG.md
# ERPLibre
git diff v#.#.#..HEAD

# All repo
./.venv/repo forall -pc "git diff ERPLibre/v#.#.#..HEAD"
```

Simplification tools:

```bash
# Show all divergence repository with production
make repo_diff_manifest_production
# Short version with statistique
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

## Generate image db to accelerate db installation

Generate image db before tag, the image is stored in directory ./image_db

```bash
make image_db_create_all
```

To test it, you need to clean caches and install it:

```bash
./script/db_restore.py --clean_cache
./script/db_restore.py --database test --image erplibre_website
```

## Create tag

Add a tag on the commit in branch master with your release. When adding tag, be sure to update default.xml

```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
./.venv/repo forall -pc "git tag ERPLibre/v#.#.#"
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

Visit `https://github.com/ERPLibre/ERPLibre/releases/new` and create a release named `v#.#.#` and copy information from CHANGELOG.md.

# TIPS

## Compare repo differences with another ERPLibre project

To generate a list of differences between repo git commit

```bash
./script/git_change_remote.py --sync_to /path/to/directory
```
