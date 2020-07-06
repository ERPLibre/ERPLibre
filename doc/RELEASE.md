# Release
A guide on how to do a release.

## Generate new prod
```bash
./venv/repo manifest -r -o ./manifest/default.xml
```
Do your commit.
```bash
git commit -am "[#ticket] subject: short sentence"
```

## Merge release
Merge your feature to master. Generate a new tag. Fill CHANGELOG.md

# TIPS
## Compare diff repo with another ERPLibre project
To generate a list of differences between repo git commit, do
```bash
./venv/bin/python ./script/git_change_remote.py --sync_to /path/to/directory
```