
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

It freezes the repos of the active Odoo version, from dev to prod: every project receives the commit of its clone
in its source file, next to its branch. [Freeze the versions](#freeze-the-versions) says what is written and what is skipped.

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

The upstream lives in the clone under a remote named after
`fork-upstream-remote` — `OCA` above, at `https://github.com/OCA/web.git` —
so its branch reads `OCA/18.0`, in tig, in `git log` and in the reflog of the
rebase, and on a full clone a plain `git fetch OCA` refreshes it by hand. The dry run adds that
remote when it is missing, fetches the upstream branch into its tracking
branch `refs/remotes/OCA/18.0`, then predicts the merge in memory. Nothing else
is written: no local branch is created or moved, HEAD and the work tree stay
put.

```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --add-remotes
```

When the freeze wrote the upstream base of a fork (`fork-upstream-freeze-revision`, see
[Freeze the upstream base](#freeze-the-upstream-base)), the dry run also counts the upstream commits since the freeze,
or flags in red an upstream rewritten since then: the frozen base is no longer in its history.

`Fork and upstream status` (TODO › Execute › Git › Repo) then lists, numbered from 1, the forks that carry both a
frozen commit and a frozen upstream base: `<base>..<frozen>` and `+N ours`, the commits of the fork between the two,
read in the clone without network. A fork that is not cloned, whose clone lacks one of the two commits, or whose
shallow history no longer links the base to the frozen commit, shows its reason instead; nothing is fetched. `N` opens that range in tig — `git log --oneline --graph` without tig — and `a`
opens each one in turn, stopping at a tig that does not exit with `q`.

### Add the upstream remotes

`Add the upstream remotes`, entry 3 of TODO › Execute › Git › Repo, or
`--add-remotes`, does only that, on every fork, without diagnosing: add the
named upstream remote, then fetch its branch. The remote is added with
`--no-tags`, and every fetch passes it too, so the upstream tags never mix with
those of the clone. It is added with `-t <branch>`: its refspec follows only the
declared upstream branch, so `git fetch OCA` brings `OCA/18.0` and not every
branch of the upstream. An existing remote of that name at the same URL, read
raw from the git config without `insteadOf` rewriting, is reused as is, with
its own refspec; the https and ssh spellings of the same repository,
`https://github.com/OCA/web.git` and `git@github.com:OCA/web.git`, count as the
same URL, so `make repo_use_all_ssh` does not turn the remote into a
collision. One at another repository is never touched: the report shows the URL in place and the
command that corrects it, `git -C <path> remote set-url <remote> <url>`, and
the dry run marks that fork as not comparable.

A shallow clone — the Odoo core fork, cloned with `clone-depth` — receives the
remote but no fetch: fetching a full upstream into it would bring its whole
history. The remote is marked `skipFetchAll`, so `git fetch --all`, and the
fetch of missing commits by the freeze comparison, leave it out. The report
gives the command that fetches it at the depth of the manifest,
`git -C <path> fetch --depth=<clone-depth> <remote> <branch>`: on that clone it
is the only fetch of the remote that keeps it shallow, and a plain
`git fetch OCA` would bring the whole history of the branch. The
dry run neither adds a remote nor fetches on a shallow clone. A fork whose
upstream is guessed, without `fork-upstream-remote`, or that has no
`fork-upstream` branch, receives nothing and is listed among the skipped forks
with its reason; a guessed upstream keeps being fetched by URL in the dry run,
into `FETCH_HEAD` only.

A remote added to the clone is not part of git-repo's state: a
`repo sync --force-sync` that rewrites the git directory loses it, and the next
dry run or `Add the upstream remotes` adds it again. The freeze does not count
the tracking branches of that remote as proof that the fork holds a commit.

### Apply the upgrade

`Apply the upgrade` (TODO › Execute › Git › Repo) asks to type the Odoo version to confirm, then handles each fork
the dry run marks to rebase, conflicting, absorbed upstream or behind upstream. Nothing is pushed. Each fork receives
a dated branch `<branch>_maj_<YYYYMMDD>`, created on HEAD, where:

- a fork with commits of its own replays them on the upstream branch of its named remote: `rebase OCA/18.0`
  (`FETCH_HEAD` for an upstream fetched by URL), where git drops by itself our
  commits the upstream already took. Only when the upstream was rewritten since the freeze — the frozen base is no
  longer in its history — the frozen commit is in HEAD's history and the base under the frozen commit, are only the
  commits laid since the base replayed: `rebase --onto OCA/18.0 <base>`, so that the old upstream is not replayed
  as ours. A base the fork outgrew would replay as ours the upstream commits between it and HEAD: it falls back to the
  plain rebase. The chosen mode and its reason are recorded in the pass;
- a fork without commits of its own, behind upstream, fast-forwards: `merge --ff-only OCA/18.0`.

Two refusals come before anything is written: a work tree whose tracked files are modified, on which git would refuse
the rebase, and a fork branch whose tip known to the clone is not an ancestor of HEAD — the remote carries commits HEAD
lacks, and publishing the result would lose them. A rebase git refuses to start is reported as such, not as a
conflict, and so is a refused fast-forward. Either can leave the work tree half written — a checkout interrupted by a
symbolic link that a remote file system such as sshfs refuses, or a directory without write permission — so the
repository is put back where the pass found it: `checkout -f` to its starting branch or commit, the upstream files that
appeared untracked since are removed, and the dated branch is deleted. Should that return fail, the dated branch stays
and the report prints the command to run by hand. Each pass is recorded under `tasks/git_repo_upgrade/`, which is not versioned.

#### Conflict queue

A rebase stopped on a conflict is left in place: that is where it gets resolved. The conflict queue lists the
repositories with a rebase in progress, read from the clones themselves, so a rebase finished by hand leaves the
queue. On each one: open a shell, show the conflicting diff, keep ours, take upstream, continue the rebase, skip the
commit, abort the rebase, or return to the state managed by repo. "Keep ours" keeps the fork's version, although git
calls it `theirs` during a rebase. A gesture that ends the rebase writes its outcome into the pass, which the
publication reads. A rebase finished outside the menu is picked up when entering the queue, the report or the
publication: a repository whose dated branch contains the upstream of the pass counts as rebased, wherever HEAD is,
since that branch is what the publication pushes; one detached on its starting commit as back to repo; any other is
listed and left as is.

#### Publish the updated forks

`Publish the updated forks` pushes the dated branches of the last pass, rebased or fast-forwarded, onto the branch of
their fork. A choice of numbers, or `all`, picks them; each repository shows its remote, the dated branch and the fork
branch, the old and the new tip, and whether the push is forced, and nothing leaves without a confirmation.

Every push carries `--force-with-lease` on the remote tip recorded in the pass, empty when the branch did not exist on
the remote: a fast-forward is not forced, a rewritten history is. A remote that moved since the pass refuses the
publication: a tracking tip that left the recorded one stops it before anything is sent, so does, before a forced
push, the tip the remote announces through `git ls-remote`, and git refuses the push if the remote itself moved; the
pass is to be run again. Before a forced push, the old remote tip, and the frozen commit when
it is part of it, must stay reachable through a tag or another branch that the fork remote carries, read with
`git ls-remote` at publish time: a local ref or a stale tracking ref does not say what the remote keeps. Otherwise the
menu asks for a tag or a branch, with an editable proposed name — `ERPLibre/v<version>_odoo<Odoo version>`, suffixed
with `_<YYYYMMDD>` when taken, or `<branch>_avant_maj_<YYYYMMDD>` — and pushes it BEFORE the forced push. A branch is
only created, never moved over an existing one. Once the push is accepted, the clone is detached on the pushed commit,
as git-repo expects, and the dated branch stays.

The manifest still holds the old frozen commits: the menu offers to freeze again right away. Then commit
`manifest/`:

```bash
make repo_freeze UPSTREAM=1
git add manifest/
git commit -m "[UPD] manifest: freeze the forks rebased on upstream"
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

The freeze writes into the three files of the active Odoo version (`.odoo-version`), for 18.0
`manifest/git_manifest_odoo18.0.xml`, `manifest/git_manifest_odoo18.0_dev.xml` and
`manifest/git_manifest_extra_odoo18.0.xml`, and touches no clone. The other merged files, the common
`git_manifest_erplibre*.xml` fragments, the other installed versions and the private manifests, are read but never
written: their projects follow their branch. `--dry-run` shows what would change, `--source` writes only some of the
three files and may be repeated; a file outside them is refused, since the reconfiguration would ignore its freeze:

```bash
.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

Not frozen, and listed:

- a project that is not cloned, left as it is;
- a project that another merged file also defines: the merge keeps one of the definitions depending on the order of
  the files, and the freeze writes only one;
- a clone whose commit no remote branch contains, since a new installation could not fetch it: push it first.

A clone with uncommitted changes is frozen on its commit, with a warning: its changes are not part of the freeze. The
command exits with 1 when nothing was frozen.

#### Freeze the upstream base

The frozen commit of a fork does not say which upstream commit it rests on. `--upstream`, or
`make repo_freeze UPSTREAM=1`, also writes it beside the fork attributes, in `fork-upstream-freeze-revision`: the merge
base of the frozen commit and the upstream branch.

```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         freeze-revision="0123456789abcdef0123456789abcdef01234567"
         fork-upstream-remote="OCA" fork-upstream="18.0"
         fork-upstream-freeze-revision="fedcba9876543210fedcba9876543210fedcba98" />
```

```bash
.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run --upstream
make repo_freeze UPSTREAM=1
```

It is the only part of the freeze that uses the network, so it is asked for: in TODO, the freeze first asks whether to
freeze the upstream base too, No by default, and the answer holds for the dry run and for the write. Only a fork whose
upstream is DECLARED is queried, `fork-upstream-remote` naming a `<remote>` of the merged files and `fork-upstream` its
branch: a URL guessed from the name of the remote could point to another repository. The upstream branch is fetched
into `FETCH_HEAD`, four forks at a time, and the base is computed right after. That fetch stores objects in the clone;
it moves no branch or ref and does not touch the work tree.

A shallow clone is deepened until a base appears: the fork side along its branch, from the URL of its remote, then
the upstream at the same depth, doubling from 50 to 1600 commits. Only history is added. A base is accepted only when
no shallow boundary is reachable from the frozen commit or the upstream without going through it: behind a boundary
may lie a better base, while an older common commit stays reachable through the second parent of a merge.

For each fork the report gives the frozen commit, its base, the commits of the fork since that base and how far it
lags behind upstream; that delay is shown, never written. A fork without a base is listed with its reason, and its
commit is frozen all the same:

- `upstream not declared`;
- `no upstream branch`: the upstream carries nothing for this Odoo version;
- `upstream unreachable`, or `fork unreachable` when a shallow clone needs the fork's remote to deepen;
- `shallow: no base within 1600`: no safe base within 1600 commits;
- `no merge base`: the histories share no commit;
- `ambiguous merge base`: several merge bases, and none to pick.

The base only holds for the frozen commit beside it: a freeze that changes `freeze-revision` without computing a base
removes it, and a freeze without `--upstream` keeps it only while the commit does not change. `make repo_unfreeze`
removes both attributes. Like `freeze-revision`, it never reaches git-repo: the merge consumes it, and drops it from
the files the freeze does not write. The header of TODO › Execute › Git › Repo counts the forks with an upstream
base, read from the files without network.

#### Install or reconfigure on the commits

```bash
make repo_configure_all FREEZE=1
# same, from the script
./script/manifest/update_manifest_local_dev.sh --freeze
```

`.repo/local_manifests/erplibre_manifest.xml` then carries the commit in `revision`, and the branch in `upstream` and
`dest-branch`: `repo sync -c` fetches the commit, and a branch opened by `repo start` follows the branch rather than
the commit. `freeze-revision` never reaches that file, git-repo does not know it. A project without `freeze-revision`,
added after the freeze or skipped by it, follows its branch, and the reconfiguration lists it under a WARNING; the
projects of the files the freeze does not write are only counted. A `freeze-revision` found in one of those files is
ignored and listed under a WARNING: `make repo_unfreeze` removes it.

In TODO, `Installation` asks for the environment once an Odoo version is chosen, before the extra modules:
`Development` follows the branches, `Production` installs on the frozen commits of that version. It shows how many
projects are frozen, and falls back to development, saying so, when no manifest of that version carries a freeze.

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
not committed yet — a `freeze-revision` or a `fork-upstream-freeze-revision` that differs from HEAD, the base alone
being enough —, and which clones carry uncommitted changes.

```bash
make repo_freeze_diff                                # HEAD -> clones
make repo_freeze_diff TO=worktree                    # what the last freeze wrote
make repo_freeze_diff ARGS=--previous                # previous freeze -> last freeze
make repo_freeze_diff FROM=v1.8.0 TO=HEAD ARGS="--log --group-by module"
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list   # commits that changed a freeze
```

A compact table lists each changed project: old and new commit, commits gained and lost (`rollback` when the new
commit only goes back), files and lines changed. A line above it gives the totals of all changed projects: commits
gained and lost, files, lines added and removed, and how many projects a missing commit or a shallow clone leaves
out. Below it, each project's diffstat is shown whole when the total is
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

Between two freezes, a fork whose `fork-upstream-freeze-revision` changed carries `upstream <old> -> <new> +N -M` in
its notes: the upstream commits of the new base missing from the old one, then the reverse, `-` standing for a side
without a base. The counts are left out when a base is missing from the clone, or when a shallow clone does not know
their common ancestor. The base can change under a frozen commit that does not: such projects are listed under
`Upstream base changed, same frozen commit`. The `clones` side has no base, and shows no such line.

A side may be any ERPLibre branch or tag: `--list-refs` lists those holding a freeze. `--matrix` shows, project by
project, the frozen commit in several sides at once, by default those branches and tags, `worktree` and `clones`;
only the projects where they differ, `=` standing for the commit of the column to its left:

```bash
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list-refs
make repo_freeze_diff ARGS="--matrix v1.8.0,origin/master,clones"
make repo_freeze_diff ARGS="--graph 1"
```

In TODO › Git repo, entry 14 offers the usual comparisons, a choice of two revisions among the freeze commits and the
ERPLibre branches and tags, and the matrix. On the report: a number opens tig on that project, `a` on each in turn,
`b N` the graph with the branches, `l` the log, `d` and `s N` the diffstats, `g` the next grouping, `f` the refresh,
`w` the command that opens an old commit in a git worktree beside the clone, without moving it.

#### Read the state of the code as JSON

`script/git/repo_state.py` writes on its standard output a JSON object, versioned by its `schema` field (1), meant for a
program rather than a person, such as an Odoo module that stores it in the database. It only reads — no
fetch, no checkout, no index written — and every git call runs with `-c safe.directory=*`, `GIT_TERMINAL_PROMPT=0`,
`GIT_OPTIONAL_LOCKS=0` and a timeout (`--timeout`, 30 s by default), so that the account of an Odoo service can run
it on clones it does not own.

`snapshot`, the default command, gives the ERPLibre version and commit, the Odoo version, the mode (`branches` or
`frozen`, read in the local manifest as the menu header does), and for each repository of the local manifest: its
HEAD, the commit its `revision` asks for, `freeze-revision`, the upstream of a fork, the Odoo modules it holds with
the version of their `__manifest__.py` (read with `ast.literal_eval`, never imported), and a state: `conforme` (HEAD
is the requested commit), `en_avance` (HEAD descends from it), `decale` (any other case), `absent` (not cloned),
`hors_manifeste` (a clone under `odoo<V>/` the manifest does not name), `erreur`, and with `--dirty`, which also runs
`git status` in every clone, `sale`: a modified tracked file or an untracked file that no `.gitignore` covers, such as
a module copied into the clone; ignored files (`.pyc`, `__pycache__`) do not count. `fingerprint` hashes everything
but the date: two snapshots of the same state share it. About 250 repositories take a second or two without `--dirty`.

`between` lists the commits between two revisions of a clone, bounded by `--max` (200), and says when the list is
cut or when the old commit is unknown to the clone; `--paths` adds the modules whose files differ between the two
commits (`changed_modules`) and the changed files, bounded by `--max-paths` (1000). `cross-version` compares a
repository with the same path under the other `odoo<V>/` trees of the checkout: presence and version of each module,
our commits of the other version's fork that have no equivalent here, matched by `git patch-id --stable` on the
module directory then by subject, the recent history of each module on both sides, and the diffstat of the modules
both sides hold; `--full` adds the whole diff, bounded by `--max-bytes`. Our commits start at the newer of two
upstream bases: the merge base with the upstream tracking branch, or `fork-upstream-freeze-revision` when it descends
from that merge base, since only the upgrade diagnostic advances the tracking branch. The output stays bounded on a
repository as large as the Odoo core: the diffstat counts every file but lists at most `--max-paths` (100) per module
and `--max-paths-total` (1000) in all, and without `--module` only `--history-modules` (100) modules get a history,
those that differ first. A repository that fails is reported in its entry, never as a traceback. Exit codes: 0 done, 1 internal
error, 2 usage, 3 target not found.

```bash
.venv.erplibre/bin/python script/git/repo_state.py --pretty
.venv.erplibre/bin/python script/git/repo_state.py snapshot --dirty --repo odoo18.0/addons/OCA_web
.venv.erplibre/bin/python script/git/repo_state.py between odoo18.0/addons/OCA_web OLD_SHA NEW_SHA --max 50
.venv.erplibre/bin/python script/git/repo_state.py cross-version odoo18.0/addons/OCA_web --module web_responsive --full
```