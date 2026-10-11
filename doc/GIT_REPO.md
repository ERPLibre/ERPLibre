
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

#### Compare two freezes

A side of the comparison is an ERPLibre revision (`HEAD`, a tag, a commit), `worktree` for the files of `manifest/` on
disk, or `clones` for the commit each clone is on. Without argument, the committed freeze is compared to the clones:
what moved since the last freeze. The report also says which commit ERPLibre is on, whether `manifest/` holds a freeze
not committed yet, and which clones carry uncommitted changes.

```bash
make repo_freeze_diff                                # HEAD -> clones
make repo_freeze_diff TO=worktree                    # what the last freeze wrote
make repo_freeze_diff ARGS=--previous                # previous freeze -> last freeze
make repo_freeze_diff FROM=v1.8.0 TO=HEAD ARGS="--log --group-by module"
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list   # commits that changed a freeze
```

A compact table lists each changed project: old and new commit, commits gained and lost (`rollback` when the new
commit only goes back), files and lines changed. Below it, each project's diffstat is shown whole when the total is
short, and limited to 10 files beyond 60 changed files; `--stat-count N` decides, 0 shows everything. The changed lines
are then grouped by file type, Odoo module or folder (`--group-by`), per project and for all of them. `--log` adds the
`git log --oneline` of each project, `--tig N` opens the history of project N in tig, or of each in turn without N.

Commits are compared inside the local clone, without network. A commit the clone lacks is listed with its full SHA;
`--fetch` fetches those commits from every remote of the clone, in parallel, before counting. In a shallow clone, two
commits without a known common ancestor are not counted (`? shallow`): the cut history would show a divergence that
does not exist. `--previous` and `--list` keep the commits that pin at least one project to a new commit; a commit that
only unfreezes, or only edits another part of a frozen line, is not a freeze.

The `vs branch` column places both commits on the branch the manifest names: `18.0 -12->tip` means the old commit was
12 commits behind the tip of `18.0`, and the new one is the tip; `+2 off` counts commits that are not on that branch.
Below it, each project names the refs of the clone that point to or contain each commit (branches, remote branches,
tags, git-repo's `m/`), the ERPLibre branches and tags whose `manifest/` freezes that same commit, and the date of the
clone's last fetch: remote branches are as fresh as that fetch, and a clone not fetched for over 7 days is listed.
`--fetch` refreshes the branches and tags of every changed clone and fetches the commits it lacks, in parallel.
`--graph N` opens the decorated graph of both commits and the tip of their branch, from their common ancestor.

A side may be any ERPLibre branch or tag: `--list-refs` lists those holding a freeze. `--matrix` shows, project by
project, the frozen commit in several sides at once, by default those branches and tags, `worktree` and `clones`;
only the projects where they differ, `=` standing for the commit of the column to its left:

```bash
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list-refs
make repo_freeze_diff ARGS="--matrix v1.8.0,origin/master,clones"
make repo_freeze_diff ARGS="--graph 1"
```

In TODO › Git repo, entry 12 offers the usual comparisons, a choice of two revisions among the freeze commits and the
ERPLibre branches and tags, and the matrix. On the report: a number opens tig on that project, `a` on each in turn,
`b N` the graph with the branches, `l` the log, `d` and `s N` the diffstats, `g` the next grouping, `f` the refresh,
`w` the command that opens an old commit in a git worktree beside the clone, without moving it.
