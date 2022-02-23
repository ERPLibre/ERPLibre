# git-repo

This is a guide to understand git-repo. Scripts in ERPLibre use git-repo automatically.

[git-repo of Google](https://code.google.com/archive/p/git-repo) is used to manage all git repositories under
licence [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.html).

## Setup repo

```bash
curl https://storage.googleapis.com/git-repo-downloads/repo > ./.venv/repo
```

## prod

```bash
./.venv/repo init -u https://github.com/ERPLibre/ERPLibre -b master
./.venv/repo sync
```

## dev

```bash
./.venv/repo init -u https://github.com/ERPLibre/ERPLibre -b 12.0_repo -m ./manifest/default.dev.xml
./.venv/repo sync
```

## local dev

[Guide to setup locally git](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

```bash
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

./.venv/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.dev.xml
./.venv/repo sync -m ./manifest/default.dev.xml
```

# Create Manifest

A [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md), is an XML file managed by
git-repo to generate a repo.

## Make a new version of prod

It freezes all repo, from dev to prod.

This will add revision git hash in the manifest.

```bash
./.venv/repo manifest -r -o ./default.xml
```

Commit.

```bash
git commit -am "[#ticket] subject: short sentence"
```

### Mix prod and dev to create a stage version

When dev contains specific revision with default revision, you need to replace default revision with prod revision and
keep specific version:

```bash
./script/git_merge_repo_manifest.py --input1 ./manifest/default.dev.xml --input2 ./default.xml --output ./manifest/default.staged.xml
git commit -am "Updated manifest/default.staged.xml"

git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

./.venv/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.staged.xml
./.venv/repo sync -m ./manifest/default.staged.xml

./.venv/repo manifest -r -o ./default.xml
```

## Create a dev version

```bash
./.venv/repo manifest -o ./manifest/default.dev.xml
```

Commit.

```bash
git commit -am "[#ticket] subject: short sentence"
```

## Useful commands

### Search all repos with a specific branch name

```bash
./.venv/repo forall -pc "git branch -a|grep BRANCH"
```

### Search missing branch in all repos

```bash
./.venv/repo forall -pc 'git branch -a|(grep /BRANCH$||echo "no match")|grep "no match"'
```

### Search changed file in all repos

```bash
./.venv/repo forall -pc "git status -s"
```

### Clean all

Before cleaning, check changed file in all repos.

```bash
./.venv/repo forall -pc "git status -s"
```

Check the changed branch, and push changed if needed.

```bash
./script/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

Maybe, some version diverge from your manifest. Simply clean all and relaunch your installation.

```bash
./script/clean_repo_manifest.sh
```
