# Release
A guide on how to do a release.

## Generate new prod
```bash
./.venv/repo manifest -r -o ./default.xml
```
Do your commit.
```bash
git commit -am "[#ticket] subject: short sentence"
```

Update variable ERPLIBRE_VERSION in [env_var.sh](../env_var.sh)

## Merge release
When ready to make a release, create a branch release/#.#.# and create a pull request to master.

Update file [CHANGELOG.md](../CHANGELOG.md) and create a section with new version.
Merge it when maintainer accept it.

Add a tag on the commit on branch master with your release. When adding tag, be sure to update default.xml
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

# TIPS
## Compare diff repo with another ERPLibre project
To generate a list of differences between repo git commit, do
```bash
./script/git_change_remote.py --sync_to /path/to/directory
```