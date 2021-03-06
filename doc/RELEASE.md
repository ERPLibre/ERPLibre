# Release

A guide on how to generate a release.

Before starting, validate [manifest/default.dev.xml](../manifest/default.dev.xml) is ready for production.

## Clean environment before generate new release

Be sure all files are commit and push, this will erase everything in addons.

```bash
./script/clean_repo_manifest.sh
```

And update all from dev to merge into prod.

```bash
./script/install_locally_dev.sh
```

## Generate new prod and release

Generate production manifest and freeze all repos versions.

```bash
./.venv/repo manifest -r -o ./default.xml
```

Update ERPLIBRE_VERSION variable in [env_var.sh](../env_var.sh) and [Dockerfile.prod](../docker/Dockerfile.prod.pkg).

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

Update file [CHANGELOG.md](../CHANGELOG.md) and create a section with new version, use next command to read all changes.

Create a branch release/#.#.# and create a pull request to branch master with your commit:

```bash
git commit -am "Release v#.#.#"
```

Review by your peers, test the docker file and merge to master.

## Create tag

Add a tag on the commit in branch master with your release. When adding tag, be sure to update default.xml

```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
./.venv/repo forall -pc "git tag ERPLibre/v#.#.#"
./.venv/repo forall -pc "git push ERPLibre --tags"
```

## Generate and push docker

Important to generate container after push git tags, otherwise the git version will be wrong.

When building your docker with script
> ./script/docker_build.sh --release

List your docker version
> docker image

You need to push your docker image and update your tag, like 1.0.1:
> docker push technolibre/erplibre:VERSION

# TIPS

## Compare repo differences with another ERPLibre project

To generate a list of differences between repo git commit

```bash
./script/git_change_remote.py --sync_to /path/to/directory
```