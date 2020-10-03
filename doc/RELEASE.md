# Release
A guide on how to generate a release.

## Generate new prod
```bash
./.venv/repo manifest -r -o ./default.xml
```
Commit.
```bash
git commit -am "[#ticket] subject: short sentence"
```

Update  ERPLIBRE_VERSION variable in [env_var.sh](../env_var.sh)

## Merge release
When you are ready to generate a release, create a branch release/#.#.# and create a pull request to master.

Update file [CHANGELOG.md](../CHANGELOG.md) and create a section with new version.
Merge it when the maintainer accepts it.

Add a tag on the commit in branch master with your release. When adding tag, be sure to update default.xml
```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
./.venv/repo forall -pc "git tag ERPLibre/v#.#.#"
./.venv/repo forall -pc "git push ERPLibre --tags"
# Get all difference between a tag and HEAD, to update the CHANGELOG.md
./.venv/repo forall -pc "git diff ERPLibre/v#.#.#..HEAD"
```

## Push docker
[Build and push guide](../docker/README.md) at section `# Update docker`.

# TIPS
## Compare repo differences with another ERPLibre project
To generate a list of differences between repo git commit 
```bash
./script/git_change_remote.py --sync_to /path/to/directory
```