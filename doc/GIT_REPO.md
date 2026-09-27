
# git-repo

This is a guide to understand git-repo. Scripts in ERPLibre use git-repo automatically.

[git-repo of Google](https://code.google.com/archive/p/git-repo) is used to manage all git repositories under
licence [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.html).

## Setup repo

```bash
curl https://storage.googleapis.com/git-repo-downloads/repo > .venv.erplibre/bin/repo
```

## prod

```bash
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b master
.venv.erplibre/bin/repo sync -c -j $(nproc --all)
```

## dev

```bash
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b 12.0_repo -m ./manifest/default.dev.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all)
```

## local dev

[Guide to setup locally git](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

```bash
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.dev.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all) -m ./manifest/default.dev.xml
```

# Create Manifest

A [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md), is an XML file managed by
git-repo to generate a repo.

## Make a new version of prod

It freezes all repo, from dev to prod.

This will add revision git hash in the manifest.

```bash
.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

Commit.

```bash
git commit -am "[#ticket] subject: short sentence"
```

### Mix prod and dev to create a stage version

When dev contains specific revision with default revision, you need to replace default revision with prod revision and
keep specific version:

```bash
./script/git/git_merge_repo_manifest.py --input "./manifest/default.dev.xml;./default.xml" --output ./manifest/default.staged.xml
git commit -am "Updated manifest/default.staged.xml"

git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.staged.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all) -m ./manifest/default.staged.xml

.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

## Create a dev version

```bash
.venv.erplibre/bin/repo manifest -o ./manifest/default.dev.xml
```

Commit.

```bash
git commit -am "[#ticket] subject: short sentence"
```

## Useful commands

### Search all repos with a specific branch name

```bash
.venv.erplibre/bin/repo forall -pc "git branch -a|grep BRANCH"
```

### Search missing branch in all repos

```bash
.venv.erplibre/bin/repo forall -pc 'git branch -a|(grep /BRANCH$||echo "no match")|grep "no match"'
```

### Search changed file in all repos

```bash
.venv.erplibre/bin/repo forall -pc "git status -s"
```

### Clean all

Before cleaning, check changed file in all repos.

```bash
.venv.erplibre/bin/repo forall -pc "git status -s"
```

Check the changed branch, and push changed if needed.

```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

Maybe, some version diverge from your manifest. Simply clean all and relaunch your installation.

```bash
./script/git/clean_repo_manifest.sh
```

## Update or upgrade

Two gestures the word "update" used to cover. TODO › Execute › Git › Repo
separates them, and Execute › Code › Update leads to the same screen.

An **update** moves every project to the tip of the branch its manifest gives
it. It asks nothing, cannot conflict, and runs every morning.

An **upgrade** fetches the upstream a fork DESCENDS from — another repository,
at another organisation — and replays the commits the fork carries of its own.
It can conflict and it rewrites history, so it is observed before it is
applied.

### Where a fork comes from

git-repo only knows the remote used to CLONE, and for a fork that is the
fork's own. Three attributes carry what it cannot express:

```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         fork-upstream-remote="OCA" fork-upstream="18.0" />
```

`fork-upstream-remote` names the upstream `<remote>`, whose `fetch` gives the
URL. `fork-upstream-name` appears only on a RENAMED fork, where the upstream
repository name differs. `fork-upstream` names the upstream branch; its
ABSENCE, while the remote is declared, says the upstream carries nothing for
this Odoo version — which is not the same thing as an unknown upstream.

The dry run writes nothing: it brings the upstream into `FETCH_HEAD` and
predicts the merge in memory, moving no ref and touching no work tree.

### Freeze the versions

`repo manifest -r -o` pins every project to its commit. The file carries the
COMMIT in `revision` and the BRANCH in `upstream`, so ONE file serves both
modes: frozen follows the commit, dev follows the branch. The mode lives in
`.erplibre-state.json`, so a reconfiguration launched elsewhere reads the same
choice. It takes effect on the next reconfiguration.

```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
```