<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# git-repo

This is a guide to understand git-repo. Scripts in ERPLibre use git-repo automatically.

[git-repo of Google](https://code.google.com/archive/p/git-repo) is used to manage all git repositories under
licence [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.html).

## Setup repo

<!-- [fr] -->
# git-repo

Ce guide explique le fonctionnement de git-repo. Les scripts dans ERPLibre utilisent git-repo automatiquement.

[git-repo de Google](https://code.google.com/archive/p/git-repo) est utilisé pour gérer tous les dépôts git sous
licence [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.html).

## Configurer repo

<!-- [common] -->
```bash
curl https://storage.googleapis.com/git-repo-downloads/repo > .venv.erplibre/bin/repo
```

<!-- [en] -->
## prod

<!-- [fr] -->
## prod

<!-- [common] -->
```bash
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b master
.venv.erplibre/bin/repo sync -c -j $(nproc --all)
```

<!-- [en] -->
## dev

<!-- [fr] -->
## dev

<!-- [common] -->
```bash
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b 12.0_repo -m ./manifest/default.dev.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all)
```

<!-- [en] -->
## local dev

[Guide to setup locally git](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

<!-- [fr] -->
## dev local

[Guide pour configurer git localement](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

<!-- [common] -->
```bash
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.dev.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all) -m ./manifest/default.dev.xml
```

<!-- [en] -->
# Create Manifest

A [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md), is an XML file managed by
git-repo to generate a repo.

## Source files and the local manifest

The manifests to edit are the files of `manifest/`: `git_manifest_odoo18.0.xml` for the projects of an Odoo version,
`git_manifest_extra_odoo18.0.xml` for its extra modules, `git_manifest_mobile_home.xml` for the mobile application.
git-repo reads none of them. Each reconfiguration merges them into `.repo/local_manifests/erplibre_manifest.xml`, the
only manifest git-repo reads:

<!-- [fr] -->
# Créer un Manifest

Un [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md) est un fichier XML géré par
git-repo pour générer un dépôt.

## Les fichiers sources et le manifeste local

Les manifestes à modifier sont les fichiers de `manifest/` : `git_manifest_odoo18.0.xml` pour les projets d'une version
d'Odoo, `git_manifest_extra_odoo18.0.xml` pour ses modules extra, `git_manifest_mobile_home.xml` pour l'application
mobile. git-repo n'en lit aucun. Chaque reconfiguration les fusionne dans `.repo/local_manifests/erplibre_manifest.xml`,
le seul manifeste que git-repo lit :

<!-- [common] -->
```bash
make repo_configure_all
```

<!-- [en] -->
That file is written again at every reconfiguration: never edit it, an edit made there is lost at the next one. Edit
the source file. When two source files define the same project, the last one in the merge order wins.

To merge chosen files only, `--input` takes a list separated by `;`, in merge order:

<!-- [fr] -->
Ce fichier est réécrit à chaque reconfiguration : ne jamais le modifier, une modification faite là se perd à la
suivante. Modifier le fichier source. Quand deux fichiers sources définissent le même projet, le dernier dans l'ordre
de fusion l'emporte.

Pour ne fusionner que des fichiers choisis, `--input` prend une liste séparée par `;`, dans l'ordre de fusion :

<!-- [common] -->
```bash
.venv.erplibre/bin/python script/git/git_merge_repo_manifest.py --input "./manifest/git_manifest_odoo18.0.xml;./manifest/git_manifest_odoo18.0_dev.xml" --output /tmp/erplibre_manifest.xml
```

<!-- [en] -->
## Make a new version of prod

It freezes the repos of the active Odoo version, from dev to prod: every project receives the commit of its clone
in its source file, next to its branch. [Freeze the versions](#freeze-the-versions) says what is written and what is skipped.

<!-- [fr] -->
## Créer une nouvelle version de prod

Cela fige les dépôts de la version d'Odoo active, du dev vers la prod : chaque projet reçoit le commit de son clone
dans son fichier source, à côté de sa branche. [Geler les versions](#geler-les-versions) dit ce qui est écrit et ce qui est écarté.

<!-- [common] -->
```bash
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

<!-- [en] -->
## Create a dev version

There is nothing to generate: the source files carry the branches, and a reconfiguration without `FREEZE=1` follows
them.

<!-- [fr] -->
## Créer une version dev

Il n'y a rien à générer : les fichiers sources portent les branches, et une reconfiguration sans `FREEZE=1` les suit.

<!-- [en] -->
## Useful commands

### Search all repos with a specific branch name

<!-- [fr] -->
## Commandes utiles

### Rechercher tous les dépôts avec un nom de branche spécifique

<!-- [common] -->
```bash
.venv.erplibre/bin/repo forall -pc "git branch -a|grep BRANCH"
```

<!-- [en] -->
### Search missing branch in all repos

<!-- [fr] -->
### Rechercher les branches manquantes dans tous les dépôts

<!-- [common] -->
```bash
.venv.erplibre/bin/repo forall -pc 'git branch -a|(grep /BRANCH$||echo "no match")|grep "no match"'
```

<!-- [en] -->
### Search changed file in all repos

<!-- [fr] -->
### Rechercher les fichiers modifiés dans tous les dépôts

<!-- [common] -->
```bash
.venv.erplibre/bin/repo forall -pc "git status -s"
```

<!-- [en] -->
### Clean all

Before cleaning, check changed file in all repos.

<!-- [fr] -->
### Tout nettoyer

Avant de nettoyer, vérifiez les fichiers modifiés dans tous les dépôts.

<!-- [common] -->
```bash
.venv.erplibre/bin/repo forall -pc "git status -s"
```

<!-- [en] -->
Check the changed branch, and push changed if needed.

<!-- [fr] -->
Vérifiez les branches modifiées, et poussez les changements si nécessaire.

<!-- [common] -->
```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

<!-- [en] -->
Maybe, some version diverge from your manifest. Simply clean all and relaunch your installation.

<!-- [fr] -->
Peut-être que certaines versions divergent de votre manifest. Nettoyez simplement tout et relancez votre installation.

<!-- [common] -->
```bash
./script/git/clean_repo_manifest.sh
```

<!-- [en] -->
## Update or upgrade

Two gestures the word "update" used to cover. TODO › Execute › Git › Repo
separates them, and Execute › Code › Update leads to the same screen.

An **update** moves every project to the tip of the branch its manifest gives
it. It asks nothing, cannot conflict, and runs every morning.

An **upgrade** fetches the upstream a fork DESCENDS from — another repository,
at another organisation — and replays the commits the fork carries of its own.
It can conflict and it rewrites history, so it is observed before it is
applied.

<!-- [fr] -->
## Mise à jour ou mise à niveau

Deux gestes que le mot « mise à jour » recouvrait. TODO › Execute › Git › Repo
les sépare, et Execute › Code › Update mène au même écran.

Une **mise à jour** déplace chaque projet sur la pointe de la branche que son
manifeste lui donne. Elle ne pose aucune question, ne peut pas entrer en
conflit, et se lance tous les matins.

Une **mise à niveau** va chercher l'amont dont un fork DESCEND — un autre
dépôt, chez une autre organisation — et rejoue les commits que le fork porte
en propre. Elle peut entrer en conflit et réécrit un historique, donc elle se
constate avant de s'appliquer.

<!-- [en] -->
### Where a fork comes from

git-repo only knows the remote used to CLONE, and for a fork that is the
fork's own. Three attributes carry what it cannot express:

<!-- [fr] -->
### D'où descend un fork

git-repo ne connaît que le remote qui sert à CLONER, et pour un fork c'est
celui du fork. Trois attributs portent ce qu'il ne sait pas exprimer :

<!-- [common] -->
```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         fork-upstream-remote="OCA" fork-upstream="18.0" />
```

<!-- [en] -->
`fork-upstream-remote` names the upstream `<remote>`, whose `fetch` gives the
URL. `fork-upstream-name` appears only on a RENAMED fork, where the upstream
repository name differs. `fork-upstream` names the upstream branch; its
ABSENCE, while the remote is declared, says the upstream carries nothing for
this Odoo version — which is not the same thing as an unknown upstream.

The dry run writes nothing: it brings the upstream into `FETCH_HEAD` and
predicts the merge in memory, moving no ref and touching no work tree.

<!-- [fr] -->
`fork-upstream-remote` nomme le `<remote>` amont, dont le `fetch` donne l'URL.
`fork-upstream-name` ne paraît que sur un fork RENOMMÉ, où le nom du dépôt
amont diffère. `fork-upstream` nomme la branche amont ; son ABSENCE, alors que
le remote est déclaré, dit que l'amont ne porte rien pour cette version
d'Odoo — ce qui n'est pas la même chose qu'un amont inconnu.

La passe à sec n'écrit rien : elle amène l'amont dans `FETCH_HEAD` et prédit
la fusion en mémoire, sans déplacer de référence ni toucher l'arbre de travail.

<!-- [common] -->
```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
```

<!-- [en] -->
When the freeze wrote the upstream base of a fork (`fork-upstream-freeze-revision`, see
[Freeze the upstream base](#freeze-the-upstream-base)), the dry run also counts the upstream commits since the freeze,
or flags in red an upstream rewritten since then: the frozen base is no longer in its history.

<!-- [fr] -->
Quand le gel a écrit la base amont d'un fork (`fork-upstream-freeze-revision`, voir
[Geler la base amont](#geler-la-base-amont)), la passe à sec compte aussi les commits amont depuis le gel, ou signale
en rouge un amont réécrit depuis : la base gelée n'est plus dans son historique.

<!-- [en] -->
### Freeze the versions

Each `<project>` of a source file keeps its BRANCH in `revision`. The freeze writes the commit of its clone next to
it, in `freeze-revision`:

<!-- [fr] -->
### Geler les versions

Chaque `<project>` d'un fichier source garde sa BRANCHE dans `revision`. Le gel écrit le commit de son clone à côté,
dans `freeze-revision` :

<!-- [common] -->
```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         freeze-revision="0123456789abcdef0123456789abcdef01234567" />
```

<!-- [en] -->
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

<!-- [fr] -->
UN seul fichier porte donc les deux lectures. Laquelle s'applique est un argument de l'installation ou de la
reconfiguration, conservé nulle part : le même checkout suit les commits ou les branches selon la façon dont il est
reconfiguré.

#### Écrire le gel

Le gel écrit dans les trois fichiers de la version d'Odoo active (`.odoo-version`), pour 18.0
`manifest/git_manifest_odoo18.0.xml`, `manifest/git_manifest_odoo18.0_dev.xml` et
`manifest/git_manifest_extra_odoo18.0.xml`, et ne touche aucun clone. Les autres fichiers fusionnés, les fragments
communs `git_manifest_erplibre*.xml`, les autres versions installées et les manifestes privés, sont lus mais jamais
écrits : leurs projets suivent leur branche. `--dry-run` montre ce qui changerait, `--source` n'écrit qu'une partie
des trois fichiers et se répète ; un fichier hors d'eux est refusé, puisque la reconfiguration ignorerait son gel :

<!-- [common] -->
```bash
.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

<!-- [en] -->
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

<!-- [fr] -->
Ne sont pas gelés, et sont listés :

- un projet qui n'est pas cloné, laissé tel quel ;
- un projet qu'un autre fichier fusionné définit aussi : la fusion garde l'une des définitions selon l'ordre des
  fichiers, et le gel n'en écrit qu'une ;
- un clone dont aucune branche distante ne contient le commit, puisqu'une installation neuve ne pourrait pas aller le
  chercher : le pousser d'abord.

Un clone aux modifications non commitées est gelé sur son commit, avec un avertissement : ses modifications ne font pas
partie du gel. La commande sort avec 1 quand rien n'a été gelé.

#### Geler la base amont

Le commit gelé d'un fork ne dit pas sur quel commit amont il repose. `--upstream`, ou `make repo_freeze UPSTREAM=1`,
l'écrit aussi à côté des attributs du fork, dans `fork-upstream-freeze-revision` : la base de fusion du commit gelé et
de la branche amont.

<!-- [common] -->
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

<!-- [en] -->
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

<!-- [fr] -->
C'est la seule partie du gel qui passe par le réseau, elle se demande donc : dans TODO, le gel demande d'abord s'il
gèle aussi la base amont, Non par défaut, et la réponse vaut pour la passe à sec comme pour l'écriture. Seul un fork
dont l'amont est DÉCLARÉ est interrogé, `fork-upstream-remote` nommant un `<remote>` des fichiers fusionnés et
`fork-upstream` sa branche : une URL devinée à partir du nom du remote pourrait viser un autre dépôt. La branche amont
est récupérée dans `FETCH_HEAD`, quatre forks à la fois, et la base se calcule aussitôt. Ce fetch range des objets
dans le clone ; il ne déplace ni branche ni référence et ne touche pas l'arbre de travail.

Un clone superficiel s'approfondit jusqu'à ce qu'une base apparaisse : le côté fork le long de sa branche, depuis l'URL
de son remote, puis l'amont à la même profondeur, en doublant de 50 à 1600 commits. Seul de l'historique s'ajoute. Une
base n'est retenue que si aucune frontière du clone superficiel n'est joignable depuis le commit gelé ou l'amont sans
passer par elle : derrière une frontière peut se trouver une meilleure base, alors qu'un commit commun plus ancien reste
joignable par le second parent d'une fusion.

Pour chaque fork, le rapport donne le commit gelé, sa base, les commits du fork depuis cette base et son retard sur
l'amont ; ce retard s'affiche, il ne s'écrit jamais. Un fork sans base est listé avec son motif, et son commit est
gelé quand même :

- `upstream not declared` : l'amont n'est pas déclaré ;
- `no upstream branch` : l'amont ne porte rien pour cette version d'Odoo ;
- `upstream unreachable`, ou `fork unreachable` quand un clone superficiel a besoin du remote du fork pour
  s'approfondir ;
- `shallow: no base within 1600` : aucune base sûre dans les 1600 commits ;
- `no merge base` : les historiques n'ont aucun commit en commun ;
- `ambiguous merge base` : plusieurs bases de fusion, et aucune à choisir.

La base ne vaut que pour le commit gelé à côté d'elle : un gel qui change `freeze-revision` sans calculer de base la
retire, et un gel sans `--upstream` ne la garde que tant que le commit ne change pas. `make repo_unfreeze` retire les
deux attributs. Comme `freeze-revision`, elle n'atteint jamais git-repo : la fusion la consomme, et la retire des
fichiers que le gel n'écrit pas. L'en-tête de TODO › Execute › Git › Repo compte les forks qui ont une base amont, lue
dans les fichiers sans réseau.

#### Installer ou reconfigurer sur les commits

<!-- [common] -->
```bash
make repo_configure_all FREEZE=1
# same, from the script
./script/manifest/update_manifest_local_dev.sh --freeze
```

<!-- [en] -->
`.repo/local_manifests/erplibre_manifest.xml` then carries the commit in `revision`, and the branch in `upstream` and
`dest-branch`: `repo sync -c` fetches the commit, and a branch opened by `repo start` follows the branch rather than
the commit. `freeze-revision` never reaches that file, git-repo does not know it. A project without `freeze-revision`,
added after the freeze or skipped by it, follows its branch, and the reconfiguration lists it under a WARNING; the
projects of the files the freeze does not write are only counted. A `freeze-revision` found in one of those files is
ignored and listed under a WARNING: `make repo_unfreeze` removes it.

#### Follow the branches again

A reconfiguration without the argument follows the branches, whether the files carry a freeze or not: the freeze
stays written, ready for the next `FREEZE=1`. `make repo_unfreeze` removes it from every source file:

<!-- [fr] -->
`.repo/local_manifests/erplibre_manifest.xml` porte alors le commit dans `revision`, et la branche dans `upstream` et
`dest-branch` : `repo sync -c` va chercher le commit, et une branche ouverte par `repo start` suit la branche plutôt
que le commit. `freeze-revision` n'atteint jamais ce fichier, git-repo ne le connaît pas. Un projet sans
`freeze-revision`, ajouté après le gel ou écarté par lui, suit sa branche, et la reconfiguration le liste sous un
WARNING ; les projets des fichiers que le gel n'écrit pas sont seulement comptés. Un `freeze-revision` trouvé dans
l'un de ces fichiers est ignoré et listé sous un WARNING : `make repo_unfreeze` le retire.

#### Suivre de nouveau les branches

Une reconfiguration sans l'argument suit les branches, que les fichiers portent un gel ou non : le gel reste écrit,
prêt pour le prochain `FREEZE=1`. `make repo_unfreeze` le retire de tous les fichiers sources :

<!-- [common] -->
```bash
# follow the branches, the freeze stays written
make repo_configure_all
# remove the freeze from every source file, then commit
make repo_unfreeze
```

<!-- [en] -->
#### Compare two freezes

A side of the comparison is an ERPLibre revision (`HEAD`, a tag, a commit), `worktree` for the files of `manifest/` on
disk, or `clones` for the commit each clone is on. Without argument, the committed freeze is compared to the clones:
what moved since the last freeze. The report also says which commit ERPLibre is on, whether `manifest/` holds a freeze
not committed yet — a `freeze-revision` or a `fork-upstream-freeze-revision` that differs from HEAD, the base alone
being enough —, and which clones carry uncommitted changes.

<!-- [fr] -->
#### Comparer deux gels

Un côté de la comparaison est une révision d'ERPLibre (`HEAD`, un tag, un commit), `worktree` pour les fichiers de
`manifest/` sur le disque, ou `clones` pour le commit où se trouve chaque clone. Sans argument, le gel committé est
comparé aux clones : ce qui a bougé depuis le dernier gel. Le rapport dit aussi sur quel commit se trouve ERPLibre, si
`manifest/` porte un gel pas encore committé — un `freeze-revision` ou un `fork-upstream-freeze-revision` qui diffère de
HEAD, la base seule suffisant —, et quels clones ont des modifications non commitées.

<!-- [common] -->
```bash
make repo_freeze_diff                                # HEAD -> clones
make repo_freeze_diff TO=worktree                    # what the last freeze wrote
make repo_freeze_diff ARGS=--previous                # previous freeze -> last freeze
make repo_freeze_diff FROM=v1.8.0 TO=HEAD ARGS="--log --group-by module"
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list   # commits that changed a freeze
```

<!-- [en] -->
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

<!-- [fr] -->
Un tableau compact liste chaque projet changé : ancien et nouveau commit, commits gagnés et perdus (`rollback` quand
le nouveau commit ne fait que reculer), fichiers et lignes changés. Une ligne au-dessus donne les totaux de tous les
projets changés : commits gagnés et perdus, fichiers, lignes ajoutées et retirées, et combien de projets un commit
absent ou un clone superficiel laisse de côté. En dessous, le diffstat de chaque projet s'affiche
en entier quand le total est court, et se borne à 10 fichiers au-delà de 60 fichiers changés ; `--stat-count N`
tranche, 0 montre tout. Les lignes changées sont ensuite regroupées par type de fichier, module Odoo ou dossier
(`--group-by`), par projet et pour l'ensemble. `--log` ajoute le `git log --oneline` de chaque projet, `--tig N` ouvre
l'historique du projet N dans tig, ou de chacun à la suite sans N.

Les commits se comparent dans le clone local, sans réseau. Un commit absent du clone se liste avec son SHA complet ;
`--fetch` va chercher ces commits sur chaque distant du clone, en parallèle, avant de compter. Dans un clone
superficiel, deux commits sans ancêtre commun connu ne se comptent pas (`? shallow`) : l'historique coupé montrerait
une divergence qui n'existe pas. `--previous` et `--list` retiennent les commits qui posent au moins un projet sur un
nouveau commit ; un commit qui ne fait que dégeler, ou que modifier une autre partie d'une ligne gelée, n'est pas un
gel.

La colonne `vs branch` place les deux commits sur la branche que nomme le manifeste : `18.0 -12->tip` veut dire que
l'ancien commit était à 12 commits de la pointe de `18.0`, et que le nouveau en est la pointe ; `+2 off` compte les
commits qui ne sont pas sur cette branche. En dessous, chaque projet nomme les refs du clone qui pointent sur chaque
commit ou le contiennent (branches, branches distantes, tags, `m/` de git-repo), les branches et tags d'ERPLibre dont
`manifest/` gèle ce même commit, et la date du dernier fetch du clone : les branches distantes sont aussi fraîches que
ce fetch, et un clone sans fetch depuis plus de 7 jours est listé. `--fetch` rafraîchit les branches et les tags de
chaque clone changé et va chercher les commits qui lui manquent, en parallèle. `--graph N` ouvre le graphe décoré des
deux commits et de la pointe de leur branche, depuis leur ancêtre commun.

Entre deux gels, un fork dont `fork-upstream-freeze-revision` a changé porte `upstream <ancienne> -> <nouvelle> +N -M`
dans ses notes : les commits amont de la nouvelle base absents de l'ancienne, puis l'inverse, `-` tenant lieu d'un
côté sans base. Les compteurs sont omis quand une base manque au clone, ou quand un clone superficiel ne connaît pas
leur ancêtre commun. La base peut changer sous un commit gelé qui ne change pas : ces projets sont listés sous
`Upstream base changed, same frozen commit`. Le côté `clones` n'a pas de base, et ne montre aucune ligne de ce genre.

Un côté peut être n'importe quelle branche ou tag d'ERPLibre : `--list-refs` liste ceux qui portent un gel. `--matrix`
montre, projet par projet, le commit gelé dans plusieurs côtés à la fois, par défaut ces branches et tags, `worktree`
et `clones` ; seulement les projets où ils diffèrent, `=` tenant lieu du commit de la colonne de gauche :

<!-- [common] -->
```bash
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list-refs
make repo_freeze_diff ARGS="--matrix v1.8.0,origin/master,clones"
make repo_freeze_diff ARGS="--graph 1"
```

<!-- [en] -->
In TODO › Git repo, entry 12 offers the usual comparisons, a choice of two revisions among the freeze commits and the
ERPLibre branches and tags, and the matrix. On the report: a number opens tig on that project, `a` on each in turn,
`b N` the graph with the branches, `l` the log, `d` and `s N` the diffstats, `g` the next grouping, `f` the refresh,
`w` the command that opens an old commit in a git worktree beside the clone, without moving it.

<!-- [fr] -->
Dans TODO › Git repo, l'entrée 12 propose les comparaisons courantes, le choix de deux révisions parmi les commits de
gel et les branches et tags d'ERPLibre, et la matrice. Sur le rapport : un numéro ouvre tig sur ce projet, `a` sur
chacun à la suite, `b N` le graphe avec les branches, `l` le journal, `d` et `s N` les diffstats, `g` le regroupement
suivant, `f` le rafraîchissement, `w` la commande qui ouvre un ancien commit dans un worktree git à côté du clone, sans
le déplacer.
