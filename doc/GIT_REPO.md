
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

## Source files and the local manifest

The manifests to edit are the files of `manifest/`: `git_manifest_odoo18.0.xml` for the projects of an Odoo version,
`git_manifest_extra_odoo18.0.xml` for its extra modules, `git_manifest_mobile_home.xml` for the mobile application.
git-repo reads none of them. Each reconfiguration merges them into `.repo/local_manifests/erplibre_manifest.xml`, the
only manifest git-repo reads:

```bash
make repo_configure_all
```

That file is written again at every reconfiguration: never edit it, an edit made there is lost at the next one. Edit
the source file. When two source files define the same project, the last one in the merge order wins.

To merge chosen files only, `--input` takes a list separated by `;`, in merge order:

```bash
.venv.erplibre/bin/python script/git/git_merge_repo_manifest.py --input "./manifest/git_manifest_odoo18.0.xml;./manifest/git_manifest_odoo18.0_dev.xml" --output /tmp/erplibre_manifest.xml
```

## Make a new version of prod

It freezes all repos, from dev to prod: every project receives the commit of its clone in its source file, next to
its branch. [Freeze the versions](#freeze-the-versions) says what is written and what is skipped.

```bash
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

## Create a dev version

There is nothing to generate: the source files carry the branches, and a reconfiguration without `FREEZE=1` follows
them.

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

```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
```

### Freeze the versions

Each `<project>` of a source file keeps its BRANCH in `revision`. The freeze writes the commit of its clone next to
it, in `freeze-revision`:

```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         freeze-revision="0123456789abcdef0123456789abcdef01234567" />
```

ONE file therefore carries both readings. Which one applies is an argument of the installation or the
reconfiguration, stored nowhere: the same checkout follows the commits or the branches depending on how it is
reconfigured.

#### Write the freeze

The freeze writes into the source files the reconfiguration merges, those of `manifest/` and a private one listed in
`private/default_git_manifest.csv`, and touches no clone. `--dry-run` shows what would change, `--source` limits it
to one file and may be repeated:

```bash
.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

Not frozen, and listed:

- a project that is not cloned, left as it is;
- a project defined by several source files, since writing into one of them would be arbitrary;
- a clone whose commit no remote branch contains, since a new installation could not fetch it: push it first.

A clone with uncommitted changes is frozen on its commit, with a warning: its changes are not part of the freeze. The
command exits with 1 when nothing was frozen.

#### Install or reconfigure on the commits

```bash
make repo_configure_all FREEZE=1
# same, from the script
./script/manifest/update_manifest_local_dev.sh --freeze
```

`.repo/local_manifests/erplibre_manifest.xml` then carries the commit in `revision`, and the branch in `upstream` and
`dest-branch`: `repo sync -c` fetches the commit, and a branch opened by `repo start` follows the branch rather than
the commit. `freeze-revision` never reaches that file, git-repo does not know it. A project without `freeze-revision`,
added after the freeze or skipped by it, follows its branch, and the reconfiguration lists it under a WARNING.

#### Follow the branches again

A reconfiguration without the argument follows the branches, whether the files carry a freeze or not: the freeze
stays written, ready for the next `FREEZE=1`. `make repo_unfreeze` removes it from every source file:

```bash
# follow the branches, the freeze stays written
make repo_configure_all
# remove the freeze from every source file, then commit
make repo_unfreeze
```