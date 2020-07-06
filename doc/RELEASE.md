# Release
A guide on how to do a release.

## Generate new prod
```bash
./venv/repo manifest -r -o ./default.xml
```
Do your commit.
```bash
git commit -am "[#ticket] subject: short sentence"
```

## Merge release
When ready to make a release, create a branch release/#.#.# and create a pull request to master.
Update file CHANGELOG.md and create a section with new version.
Merge it when maintener accept it.

Add a tag on the commit on branch master with your release.
> git tag v#.#.#
Push your tag
> git push --tags

# TIPS
## Compare diff repo with another ERPLibre project
To generate a list of differences between repo git commit, do
```bash
./venv/bin/python ./script/git_change_remote.py --sync_to /path/to/directory
```