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

A **pull** is the update of a deployed checkout that carries commits or changes
of its own: each repository integrates its target with `git pull`'s gestures
(fast-forward, rebase or merge), after a backup branch, and only what its dry
run showed. Entry 3 of TODO › Execute › Git › Repo, and the Odoo module
`erplibre_info`.

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

**Tirer** est la mise à jour d'un checkout déployé qui porte des commits ou des
modifications à lui : chaque dépôt intègre sa cible par les gestes de
`git pull` (avance rapide, rebase ou fusion), après une branche de sauvegarde,
et seulement ce que son essai à sec a montré. Entrée 3 de TODO › Execute › Git ›
Repo, et le module Odoo `erplibre_info`.

<!-- [en] -->
### Pull the repositories

Two modes. **manifest** (the default) pulls the ERPLibre root on its tracked
branch, regenerates `.repo/local_manifests/erplibre_manifest.xml` with
`git_merge_repo_manifest.py` — frozen when the local manifest already is — then
each clone integrates the target of its new entry, detached HEAD included. A
detached clone with no commit of its own — none that a remote-tracking ref
lacks — switches to its target with `checkout --detach`, as `repo sync` does
(`bascule`), whatever the strategy; when the manifest moves a clone with local
commits to another upstream line, the rebase replays only those commits.
**branches** pulls each clone on the branch it tracks (`@{u}`), or on the remote
and branch its manifest entry gives; a detached HEAD is skipped. The root is a
repository like the others in both modes.

The strategy is `rebase` (the default), `ff` (fast-forward only: a diverged
repository is left as is) or `merge`. A repository behind its target
fast-forwards whatever the strategy.

The dry run only fetches: no local branch, HEAD or work tree moves. For each
repository it shows the target, the incoming commits, the commits of its own,
whether its tracked files are modified (they will be stashed, then reapplied),
whether it is shallow, the ignored local files that the target starts tracking
(git would overwrite them silently: the pull copies them into its pass first,
and puts them back when the repository returns to its start), plus the
regenerated manifest, the new and the retired repositories, and the Python
dependency files that change. A tag of the manifest is fetched under
`refs/repo_pull/tags/`, so a local tag of the same name never moves.

The pull itself runs the dry run again and writes nothing if a repository, its
target or its HEAD changed since the one shown. Before moving HEAD, it creates
the branch `<branch>_avant_pull_<YYYYMMDDTHHMM>` on it — a reference only. A
rebase or merge that conflicts is aborted and the repository goes back to its
start commit, its stash reapplied (`conflit_annule`); the others go on. A
`stash pop` that conflicts leaves the tree on the pulled commit and keeps the
stash, with the command that applies it again (`stash_garde`). A tree that
stays modified after a `stash push` that saved nothing — a submodule moved to
another commit — is refused; the content changed inside a submodule does not
count as modified. Nothing is pushed. The pass is recorded under
`tasks/git_repo_pull/<stamp>/`, after each repository.

`--budget SECONDS` bounds a pass: past it, no repository, deepening step, clone
or install starts any more (`saute_delai`), and the pass still answers.
`erplibre_info` gives it a budget below the timeout of its call. A call killed
anyway takes its whole process group with it, and the backups of its pass are
read back by their stamp; the restart then waits for a new dry run.

A shallow clone is fetched with `--shallow-since`, never `--depth`, which would
shorten the history of HEAD. The bound is the oldest boundary of HEAD's history
minus an hour. A boundary that a fetch puts inside HEAD's history (a commit
dated before its parent) is removed again, and a new boundary of the target
newer than the bound — the merge of an old branch, which hides HEAD — is pushed
back by `--deepen=1`, four times at most: such a fast-forward stays one. When
no safe common base appears, the dry run says so and the pull deepens that
clone only when asked (network): `--deepen` by doubling steps, up to 1600
commits.

A repository of the regenerated manifest that is not cloned yet is cloned only
when asked, by a `repo sync` restricted to its path: a plain `git clone` would
break the next `repo sync`. It is refused when `.repo/project.list` names a
project the manifest drops, since `repo sync` would delete its work tree. A
project retired from the manifest stays on disk, untouched.

When `poetry.lock` or the `pyproject.toml` of the active couple changes, the
pull offers `poetry install --no-root` in the Odoo virtual environment; it can
also be run later, or skipped before a restart. A retargeted `pyproject.toml`
or `poetry.lock` link is a new Python/Odoo couple: that takes `make install`.

Each backup can be restored (the repository moves back to it; its tree must
have no tracked change, and be on the same branch, or detached as it was, and
at the commit where the pass left it: a commit made after the pull is never
dropped, `head_deplacee`) or deleted, restored or not. Restoring the root also
puts back the local manifest the pass replaced.

<!-- [fr] -->
### Tirer les dépôts

Deux modes. **manifeste** (par défaut) tire la racine ERPLibre sur sa branche
suivie, régénère `.repo/local_manifests/erplibre_manifest.xml` par
`git_merge_repo_manifest.py` — gelé quand le manifeste local l'est déjà — puis
chaque clone intègre la cible de sa nouvelle entrée, HEAD détachée comprise. Un
clone détaché sans commit à lui — aucun qui manque à une référence de suivi —
passe sur sa cible par `checkout --detach`, comme `repo sync` (`bascule`),
quelle que soit la stratégie ; quand le manifeste mène un clone porteur de
commits locaux sur une autre ligne amont, le rebase ne rejoue que ces commits.
**branches** tire chaque clone sur la branche qu'il suit (`@{u}`), ou sur le
remote et la branche que lui donne son entrée du manifeste ; une HEAD détachée
est sautée. La racine est un dépôt comme les autres dans les deux modes.

La stratégie vaut `rebase` (par défaut), `ff` (avance rapide seulement : un
dépôt divergé reste tel quel) ou `merge`. Un dépôt en retard sur sa cible
avance rapidement quelle que soit la stratégie.

L'essai à sec ne fait que récupérer : aucune branche locale, aucune HEAD, aucun
arbre de travail ne bouge. Pour chaque dépôt, il montre la cible, les commits
entrants, ses commits à lui, si ses fichiers suivis sont modifiés (ils seront
mis de côté, puis réappliqués), s'il est superficiel, les fichiers locaux
ignorés que la cible se met à suivre (git les écraserait sans rien dire : le
tirage les copie d'abord dans sa passe, et les remet quand le dépôt revient à
son départ), puis le manifeste régénéré, les dépôts nouveaux et retirés, et les
fichiers de dépendances Python qui changent. Un tag du manifeste se récupère
sous `refs/repo_pull/tags/` : un tag local du même nom ne bouge jamais.

Le tirage refait l'essai à sec et n'écrit rien si un dépôt, sa cible ou son
HEAD a changé depuis celui qui a été montré. Avant de déplacer HEAD, il y pose
la branche `<branche>_avant_pull_<AAAAMMJJTHHMM>` — une référence seulement. Un
rebase ou une fusion en conflit est abandonné et le dépôt revient sur son
commit de départ, stash réappliqué (`conflit_annule`) ; les autres continuent.
Un `stash pop` en conflit laisse l'arbre sur le commit tiré et garde le stash,
avec la commande qui le réapplique (`stash_garde`). Un arbre encore modifié
après un `stash push` qui n'a rien gardé — un sous-module passé sur un autre
commit — est refusé ; le contenu modifié dans un sous-module ne compte pas comme
une modification. Rien n'est poussé. La passe s'inscrit sous
`tasks/git_repo_pull/<horodatage>/`, après chaque dépôt.

`--budget SECONDES` borne une passe : au-delà, aucun dépôt, aucun palier
d'approfondissement, aucun clonage ni aucune installation ne commence plus
(`saute_delai`), et la passe répond quand même. `erplibre_info` lui donne un
budget sous le délai de son appel. Un appel tué malgré tout emporte son groupe
de processus entier, et les sauvegardes de sa passe se relisent par leur
horodatage ; le redémarrage attend alors un nouvel essai à sec.

Un clone superficiel se récupère par `--shallow-since`, jamais `--depth`, qui
raccourcirait l'historique de HEAD. La borne est la plus ancienne frontière de
l'historique de HEAD moins une heure. Une frontière qu'une récupération pose
dans l'historique de HEAD (un commit daté avant son parent) est retirée, et une
frontière nouvelle de la cible plus récente que la borne — la fusion d'une
vieille branche, qui cache HEAD — est repoussée par `--deepen=1`, quatre fois au
plus : une telle avance rapide en reste une. Quand aucune base commune sûre
n'apparaît, l'essai à sec le dit et le tirage n'approfondit ce clone que sur
demande (réseau) : `--deepen` par paliers doublés, jusqu'à 1600 commits.

Un dépôt du manifeste régénéré qui n'est pas encore cloné ne se clone que sur
demande, par un `repo sync` restreint à son chemin : un simple `git clone`
casserait le `repo sync` suivant. Il est refusé quand `.repo/project.list`
nomme un projet que le manifeste abandonne, car `repo sync` effacerait son
arbre. Un projet retiré du manifeste reste sur le disque, intact.

Quand `poetry.lock` ou le `pyproject.toml` du couple actif change, le tirage
propose `poetry install --no-root` dans l'environnement virtuel d'Odoo ; il se
lance aussi plus tard, ou se saute avant un redémarrage. Un lien
`pyproject.toml` ou `poetry.lock` redirigé est un nouveau couple Python/Odoo :
il demande `make install`.

Chaque sauvegarde se restaure (le dépôt y revient ; son arbre ne doit porter
aucune modification suivie, être sur la même branche, ou détaché comme il
l'était, et sur le commit où la passe l'a laissé : un commit fait après le
tirage n'est jamais ôté, `head_deplacee`) ou se supprime, restaurée ou non.
Restaurer la racine remet aussi le manifeste local que la passe avait remplacé.

<!-- [en] -->
#### Pull without the menu

`script/git/repo_pull.py` prints one JSON object, for a caller that shows the
dry run and collects consent, such as `erplibre_info`. `--dry-run` lists in
`attendus` the `<path>=<target sha>:<HEAD sha>` pins of the repositories it
would pull; `--apply` takes them back with `--expect`, and `--confirm` must be
the active Odoo version (exit code 2 otherwise). A plan that changed writes
nothing (exit code 4). Shallow clones need `--approve-deepen` and the pins of
`attendus_superficiel`, new repositories `--approve-clone` and one
`--expect-clone` per path of `plan_nouveaux`; `--approve-deps` runs
`poetry install` at the end. `--path` restricts the pass to one repository
(`.` is the root), `--pass` gives its stamp and `--budget` its time budget.
Exit code 5 means another pass holds the lock of the checkout.

<!-- [fr] -->
#### Tirer sans le menu

`script/git/repo_pull.py` écrit un objet JSON, pour un appelant qui montre
l'essai à sec et recueille le consentement, tel `erplibre_info`. `--dry-run`
liste dans `attendus` les épingles `<chemin>=<sha cible>:<sha HEAD>` des dépôts
qu'il tirerait ; `--apply` les reprend par `--expect`, et `--confirm` doit
valoir la version d'Odoo active (code de sortie 2 sinon). Un plan qui a changé
n'écrit rien (code de sortie 4). Les clones superficiels demandent
`--approve-deepen` et les épingles d'`attendus_superficiel`, les nouveaux
dépôts `--approve-clone` et un `--expect-clone` par chemin de `plan_nouveaux` ;
`--approve-deps` lance `poetry install` à la fin. `--path` restreint la passe à
un dépôt (`.` est la racine), `--pass` donne son horodatage et `--budget` son
délai. Le code de sortie 5 dit qu'une autre passe tient le verrou du checkout.

<!-- [common] -->
```bash
.venv.erplibre/bin/python script/git/repo_pull.py --dry-run --pretty
.venv.erplibre/bin/python script/git/repo_pull.py --dry-run --mode branche --strategy ff
.venv.erplibre/bin/python script/git/repo_pull.py --apply --confirm 18.0 --expect odoo18.0/addons/OCA_web=TARGET_SHA:HEAD_SHA
.venv.erplibre/bin/python script/git/repo_pull.py --list-backups
.venv.erplibre/bin/python script/git/repo_pull.py --restore-backup odoo18.0/addons/OCA_web=18.0_avant_pull_20260101T0800 --confirm 18.0
.venv.erplibre/bin/python script/git/repo_pull.py --delete-backup odoo18.0/addons/OCA_web=18.0_avant_pull_20260101T0800 --confirm 18.0
.venv.erplibre/bin/python script/git/repo_pull.py --install-deps --confirm 18.0 --pass 20260101T0800
```

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

The upstream lives in the clone under a remote named after
`fork-upstream-remote` — `OCA` above, at `https://github.com/OCA/web.git` —
so its branch reads `OCA/18.0`, in tig, in `git log` and in the reflog of the
rebase, and on a full clone a plain `git fetch OCA` refreshes it by hand. The dry run adds that
remote when it is missing, fetches the upstream branch into its tracking
branch `refs/remotes/OCA/18.0`, then predicts the merge in memory. Nothing else
is written: no local branch is created or moved, HEAD and the work tree stay
put.

<!-- [fr] -->
`fork-upstream-remote` nomme le `<remote>` amont, dont le `fetch` donne l'URL.
`fork-upstream-name` ne paraît que sur un fork RENOMMÉ, où le nom du dépôt
amont diffère. `fork-upstream` nomme la branche amont ; son ABSENCE, alors que
le remote est déclaré, dit que l'amont ne porte rien pour cette version
d'Odoo — ce qui n'est pas la même chose qu'un amont inconnu.

L'amont vit dans le clone sous un remote qui porte le nom de
`fork-upstream-remote` — `OCA` ci-dessus, à `https://github.com/OCA/web.git` —
si bien que sa branche se lit `OCA/18.0`, dans tig, dans `git log` et dans le
reflog du rebase, et que sur un clone complet un simple `git fetch OCA` la rafraîchit à la main. La
passe à sec pose ce remote quand il manque, récupère la branche amont dans sa
branche de suivi `refs/remotes/OCA/18.0`, puis prédit la fusion en mémoire.
Rien d'autre ne s'écrit : aucune branche locale n'est créée ni déplacée, HEAD
et l'arbre de travail ne bougent pas.

<!-- [common] -->
```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --add-remotes
```

<!-- [en] -->
When the freeze wrote the upstream base of a fork (`fork-upstream-freeze-revision`, see
[Freeze the upstream base](#freeze-the-upstream-base)), the dry run also counts the upstream commits since the freeze,
or flags in red an upstream rewritten since then: the frozen base is no longer in its history.

`Fork and upstream status` (TODO › Execute › Git › Repo) then lists, numbered from 1, the forks that carry both a
frozen commit and a frozen upstream base: `<base>..<frozen>` and `+N ours`, the commits of the fork between the two,
read in the clone without network. A fork that is not cloned, whose clone lacks one of the two commits, or whose
shallow history no longer links the base to the frozen commit, shows its reason instead; nothing is fetched. `N` opens that range in tig — `git log --oneline --graph` without tig — and `a`
opens each one in turn, stopping at a tig that does not exit with `q`.

### Add the upstream remotes

`Add the upstream remotes`, entry 4 of TODO › Execute › Git › Repo, or
`--add-remotes`, does only that, on every fork, without diagnosing: add the
named upstream remote, then fetch its branch. The menu entry covers every Odoo
version of the checkout, each `odoo<V>/` tree that has a manifest, in
ascending order and not only the active one; on the command line,
`--add-remotes --all-versions` does the same, and `--version` alone picks one.
The remote is added with
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

`Apply the upgrade` (TODO › Execute › Git › Repo) asks for a confirmation (`y/N`), then handles each fork
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

<!-- [fr] -->
Quand le gel a écrit la base amont d'un fork (`fork-upstream-freeze-revision`, voir
[Geler la base amont](#geler-la-base-amont)), la passe à sec compte aussi les commits amont depuis le gel, ou signale
en rouge un amont réécrit depuis : la base gelée n'est plus dans son historique.

`État des forks et de leurs amonts` (TODO › Execute › Git › Repo) liste ensuite, numérotés à partir de 1, les forks
qui portent à la fois un commit gelé et une base amont gelée : `<base>..<gel>` et `+N à nous`, les commits du fork
entre les deux, lus dans le clone sans réseau. Un fork non cloné, dont le clone n'a pas l'un des deux commits, ou
dont l'historique superficiel ne relie plus la base au commit gelé, affiche son motif à la place ; rien n'est
récupéré. `N` ouvre cette plage dans tig — `git log --oneline --graph` sans
tig — et `a` les ouvre l'une après l'autre, en s'arrêtant sur un tig qui ne sort pas par `q`.

### Ajouter les remotes amont

`Ajouter les remotes amont`, l'entrée 4 de TODO › Execute › Git › Repo, ou
`--add-remotes`, ne fait que cela, sur chaque fork, sans diagnostic : poser le
remote amont nommé, puis récupérer sa branche. L'entrée du menu passe chaque
version d'Odoo du checkout, chaque arbre `odoo<V>/` qui a un manifeste, en
ordre croissant et non la seule active ; en ligne de commande,
`--add-remotes --all-versions` fait de même, et `--version` seul en choisit une.
Le remote est posé avec
`--no-tags`, et chaque fetch le passe aussi : les tags de l'amont ne se mêlent
jamais à ceux du clone. Il est posé avec `-t <branche>` : sa refspec ne suit
que la branche amont déclarée, si bien que `git fetch OCA` amène `OCA/18.0` et
non chaque branche de l'amont. Un remote de ce nom déjà là à la même URL, lue
brute dans la configuration git sans réécriture `insteadOf`, sert tel quel,
avec sa propre refspec ; l'écriture https et l'écriture ssh d'un même dépôt,
`https://github.com/OCA/web.git` et `git@github.com:OCA/web.git`, comptent pour
la même URL, si bien que `make repo_use_all_ssh` ne fait pas du remote une
collision. Un remote qui vise un autre dépôt n'est jamais touché : le rapport montre l'URL en place
et la commande qui la corrige, `git -C <chemin> remote set-url <remote> <url>`,
et la passe à sec rend ce fork non comparable.

Un clone superficiel — le fork du cœur d'Odoo, cloné avec `clone-depth` —
reçoit le remote mais aucun fetch : y récupérer l'amont complet rapatrierait
tout son historique. Le remote est marqué `skipFetchAll`, si bien que
`git fetch --all`, et la récupération des commits manquants de la comparaison
des gels, le laissent de côté. Le rapport donne la commande qui le récupère à
la profondeur du manifeste, `git -C <chemin> fetch --depth=<clone-depth>
<remote> <branche>` : sur ce clone, c'est le seul fetch du remote qui le garde
superficiel, et un simple `git fetch OCA` rapatrierait tout l'historique de la
branche. La passe à sec, elle, ne pose ni remote ni fetch sur un clone
superficiel. Un fork dont l'amont est deviné, sans `fork-upstream-remote`, ou
qui n'a pas de branche `fork-upstream`, ne reçoit rien et figure parmi les
forks sautés avec son motif ; un amont deviné reste récupéré par l'URL dans la
passe à sec, dans `FETCH_HEAD` seulement.

Un remote posé dans le clone ne fait pas partie de l'état de git-repo : un
`repo sync --force-sync` qui réécrit le répertoire git le perd, et la passe à
sec suivante ou `Ajouter les remotes amont` le repose. Le gel ne compte pas les
branches de suivi de ce remote comme la preuve que le fork porte un commit.

### Appliquer la mise à niveau

`Appliquer la mise à niveau` (TODO › Execute › Git › Repo) demande une confirmation (`o/N`), puis
traite chaque fork que la passe à sec marque à rebaser, en conflit, absorbé par l'amont ou en retard sur l'amont. Rien
n'est poussé. Chaque fork reçoit une branche datée `<branche>_maj_<AAAAMMJJ>`, créée sur HEAD, où :

- un fork qui porte des commits en propre les rejoue sur la branche amont de son remote nommé : `rebase OCA/18.0`
  (`FETCH_HEAD` pour un amont récupéré par l'URL), où git écarte de lui-même nos
  commits que l'amont a déjà repris. Seulement quand l'amont a été réécrit depuis le gel — la base gelée n'est plus
  dans son historique —, que le commit gelé est dans l'historique de HEAD et la base sous le commit gelé, seuls les
  commits posés depuis la base se rejouent : `rebase --onto OCA/18.0 <base>`, pour que l'ancien amont ne se rejoue
  pas comme nôtre. Une base que le fork a dépassée rejouerait comme nôtres les commits amont entre elle et HEAD : elle
  revient au rebase ordinaire. Le mode retenu et sa raison s'inscrivent dans la passe ;
- un fork sans commit propre, en retard sur l'amont, avance en fast-forward : `merge --ff-only OCA/18.0`.

Deux refus précèdent toute écriture : un arbre de travail dont des fichiers suivis sont modifiés, sur lequel git
refuserait le rebase, et une branche du fork dont la pointe connue du clone n'est pas un ancêtre de HEAD — le distant
porte des commits que HEAD n'a pas, et publier le résultat les perdrait. Un rebase que git refuse de commencer est
rapporté comme tel, et non comme un conflit, de même qu'un fast-forward refusé. L'un comme l'autre peut laisser l'arbre
à moitié écrit — un checkout interrompu par un lien symbolique qu'un système de fichiers distant comme sshfs refuse, ou
par un dossier sans droit d'écriture — : le dépôt est donc remis où la passe l'a pris, par `checkout -f` vers sa branche
ou son commit de départ, les fichiers de l'amont apparus hors suivi depuis sont effacés et la branche datée est
supprimée. Si ce retour échoue, la branche datée reste et le rapport affiche la commande à lancer à la main. Chaque passe s'enregistre sous `tasks/git_repo_upgrade/`, qui n'est pas
versionné.

#### File des conflits

Un rebase arrêté sur un conflit est laissé en l'état : c'est là que la résolution se fait. La file des conflits liste
les dépôts dont un rebase est en cours, lus dans les clones eux-mêmes : un rebase terminé à la main sort de la file.
Sur chacun : ouvrir un shell, montrer le diff en conflit, garder le nôtre, prendre l'amont, continuer le rebase, sauter
le commit, abandonner le rebase, ou revenir à l'état géré par repo. « Garder le nôtre » garde la version du fork, bien
que git la nomme `theirs` pendant un rebase. Un geste qui termine le rebase inscrit son issue dans la passe, que la
publication lit. Un rebase terminé hors du menu se relit en entrant dans la file, le rapport ou la publication : un
dépôt dont la branche datée contient l'amont de la passe compte comme rebasé, où que soit HEAD, puisque c'est cette
branche que la publication pousse ; un dépôt détaché sur son commit de départ comme revenu à repo ; tout autre est
listé et laissé tel quel.

#### Publier les forks mis à niveau

`Publier les forks mis à niveau` pousse les branches datées de la dernière passe, rebasées ou avancées, sur la branche
de leur fork. Une liste de numéros, ou `all`, les choisit ; chaque dépôt montre son remote, la branche datée et la
branche du fork, l'ancienne et la nouvelle pointe, et si le push est forcé, et rien ne part sans confirmation.

Chaque push porte `--force-with-lease` sur la pointe distante inscrite dans la passe, vide quand la branche n'existait
pas au distant : un fast-forward n'est pas forcé, un historique réécrit l'est. Un distant qui a bougé depuis la passe
refuse la publication : une pointe suivie qui a quitté celle inscrite l'arrête avant tout envoi, de même, avant un
push forcé, la pointe que le distant annonce par `git ls-remote`, et git refuse le push si le distant lui-même a bougé ;
la passe est à refaire. Avant un push forcé, l'ancienne pointe distante, et le commit
gelé quand il en fait partie, doivent rester atteignables par un tag ou une autre branche que porte le remote du fork,
lus par `git ls-remote` au moment de publier : une référence locale ou un suivi périmé ne dit pas ce que le distant
garde. Sinon le menu demande un tag ou une branche, au nom proposé et modifiable —
`ERPLibre/v<version>_odoo<version d'Odoo>`, suffixé de `_<AAAAMMJJ>` quand il est pris, ou
`<branche>_avant_maj_<AAAAMMJJ>` — et le pousse AVANT le push forcé. Une branche ne fait que se créer, jamais se
déplacer sur une branche existante. Une fois le push accepté, le clone est détaché sur le commit poussé, comme git-repo
l'attend, et la branche datée reste.

Le manifeste porte encore les anciens commits gelés : le menu propose de geler de nouveau sur-le-champ. Committer
ensuite `manifest/` :

<!-- [common] -->
```bash
make repo_freeze UPSTREAM=1
git add manifest/
git commit -m "[UPD] manifest: freeze the forks rebased on upstream"
```

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

In TODO, `Installation` asks for the environment once an Odoo version is chosen, before the extra modules:
`Development` follows the branches, `Production` installs on the frozen commits of that version. It shows how many
projects are frozen, and falls back to development, saying so, when no manifest of that version carries a freeze.

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

Dans TODO, `Installation` demande l'environnement une fois la version d'Odoo choisie, avant les modules extra :
`Développement` suit les branches, `Production` installe sur les commits gelés de cette version. Il affiche combien de
projets sont gelés, et se rabat sur le développement, en le disant, quand aucun manifeste de cette version ne porte de
gel.

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
In TODO › Git repo, entry 15 offers the usual comparisons, a choice of two revisions among the freeze commits and the
ERPLibre branches and tags, and the matrix. On the report: a number opens tig on that project, `a` on each in turn,
`b N` the graph with the branches, `l` the log, `d` and `s N` the diffstats, `g` the next grouping, `f` the refresh,
`w` the command that opens an old commit in a git worktree beside the clone, without moving it.

<!-- [fr] -->
Dans TODO › Git repo, l'entrée 15 propose les comparaisons courantes, le choix de deux révisions parmi les commits de
gel et les branches et tags d'ERPLibre, et la matrice. Sur le rapport : un numéro ouvre tig sur ce projet, `a` sur
chacun à la suite, `b N` le graphe avec les branches, `l` le journal, `d` et `s N` les diffstats, `g` le regroupement
suivant, `f` le rafraîchissement, `w` la commande qui ouvre un ancien commit dans un worktree git à côté du clone, sans
le déplacer.

<!-- [en] -->
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

<!-- [fr] -->
#### Lire l'état du code en JSON

`script/git/repo_state.py` écrit sur sa sortie standard un objet JSON, versionné par son champ `schema` (1), destiné à
un programme plutôt qu'à une personne, tel un module Odoo qui le stocke en base. Il ne fait que lire — ni
fetch, ni checkout, ni index écrit — et chaque appel à git passe `-c safe.directory=*`, `GIT_TERMINAL_PROMPT=0`,
`GIT_OPTIONAL_LOCKS=0` et un délai (`--timeout`, 30 s par défaut), si bien que le compte d'un service Odoo peut le
lancer sur des clones dont il n'est pas propriétaire.

`snapshot`, la commande par défaut, donne la version et le commit d'ERPLibre, la version d'Odoo, le mode (`branches`
ou `frozen`, lu dans le manifeste local comme le fait l'en-tête du menu), et pour chaque dépôt du manifeste local :
son HEAD, le commit que demande sa `revision`, `freeze-revision`, l'amont d'un fork, les modules Odoo qu'il porte
avec la version de leur `__manifest__.py` (lu par `ast.literal_eval`, jamais importé), et un état : `conforme` (HEAD
est le commit demandé), `en_avance` (HEAD en descend), `decale` (tout autre cas), `absent` (non cloné),
`hors_manifeste` (un clone sous `odoo<V>/` que le manifeste ne nomme pas), `erreur`, et avec `--dirty`, qui lance en
plus `git status` dans chaque clone, `sale` : un fichier suivi modifié, ou un fichier non suivi qu'aucun `.gitignore`
ne couvre, tel un module copié dans le clone ; les fichiers ignorés (`.pyc`, `__pycache__`) ne comptent pas.
`fingerprint` hache tout sauf la date : deux instantanés du même état la partagent. Environ 250 dépôts prennent une seconde ou deux sans `--dirty`.

`between` liste les commits entre deux révisions d'un clone, bornés par `--max` (200), et dit quand la liste est
coupée ou quand l'ancien commit est inconnu du clone ; `--paths` ajoute les modules dont un fichier diffère entre les
deux commits (`changed_modules`) et les fichiers modifiés, bornés par `--max-paths` (1000). `cross-version` compare un
dépôt au même chemin sous les autres arbres `odoo<V>/` du checkout : présence et version de chaque module, nos commits
du fork de l'autre version qui n'ont pas d'équivalent ici, appariés par `git patch-id --stable` sur le dossier du
module puis par sujet, l'historique récent de chaque module des deux côtés, et le diffstat des modules que les deux
côtés portent ; `--full` ajoute le diff entier, borné par `--max-bytes`. Nos commits partent de la plus récente de
deux bases amont : la base de fusion avec la branche de suivi amont, ou `fork-upstream-freeze-revision` quand il
descend de cette base de fusion, puisque seul le diagnostic de mise à niveau avance la branche de suivi. La sortie
reste bornée sur un dépôt aussi grand que le cœur d'Odoo : le diffstat compte tous les fichiers mais n'en liste que
`--max-paths` (100) par module et `--max-paths-total` (1000) en tout, et sans `--module` seuls `--history-modules`
(100) modules reçoivent un historique, ceux qui diffèrent d'abord. Un dépôt en échec se signale dans son entrée, jamais par une trace. Codes de sortie : 0 terminé,
1 erreur interne, 2 usage, 3 cible introuvable.

<!-- [common] -->
```bash
.venv.erplibre/bin/python script/git/repo_state.py --pretty
.venv.erplibre/bin/python script/git/repo_state.py snapshot --dirty --repo odoo18.0/addons/OCA_web
.venv.erplibre/bin/python script/git/repo_state.py between odoo18.0/addons/OCA_web OLD_SHA NEW_SHA --max 50
.venv.erplibre/bin/python script/git/repo_state.py cross-version odoo18.0/addons/OCA_web --module web_responsive --full
```

<!-- [en] -->
#### Apply an upgrade pass without the menu

`script/git/repo_apply.py --apply --confirm <Odoo version> --expect <path>...` applies a pass for a caller that has
already shown the dry run and collected consent, such as the Odoo module `erplibre_info`; it prints JSON. It runs the
diagnostic again and refuses to write anything (exit code 4) unless the forks without predicted conflict
(`a_rebaser`, `en_retard`) are exactly the `--expect` paths. `--expect <path>=<upstream sha>:<HEAD sha>` also pins
the state the dry run showed, from the `cible_sha` and `head` of its diagnostic: a pinned fork whose upstream or
HEAD moved since refuses the pass the same way, listed under `derives`, so the rebase never lands on commits nobody
reviewed. `--confirm` must be the active Odoo version
(exit code 2 otherwise). The forks with a predicted conflict (`en_conflit`, `absorbe`) are left
to the menu and listed under `laisses`. A fork that conflicts anyway has its rebase aborted and returns to its start
commit, state `conflit_annule`: no tree is left with conflicts. The pass is recorded under `tasks/git_repo_upgrade/`
like a pass of the menu, and nothing is pushed.

<!-- [fr] -->
#### Appliquer une passe de mise à niveau sans le menu

`script/git/repo_apply.py --apply --confirm <version d'Odoo> --expect <chemin>...` applique une passe pour un appelant
qui a déjà montré l'essai à sec et recueilli le consentement, tel le module Odoo `erplibre_info` ; il écrit du JSON.
Il refait le diagnostic et refuse de rien écrire (code de sortie 4) si les forks sans conflit prédit (`a_rebaser`,
`en_retard`) ne sont pas exactement les chemins `--expect`. `--expect <chemin>=<sha amont>:<sha HEAD>` épingle en
plus l'état que l'essai à sec a montré, tiré des `cible_sha` et `head` de son diagnostic : un fork épinglé dont
l'amont ou le HEAD a bougé depuis refuse la passe de la même façon, listé sous `derives`, si bien que le rebase ne
se pose jamais sur des commits que personne n'a vus. `--confirm` doit valoir la version d'Odoo active
(code de sortie 2 sinon). Les forks dont un conflit est prédit (`en_conflit`, `absorbe`) sont
laissés au menu et listés sous `laisses`. Un fork qui bute malgré tout voit son rebase abandonné et revient sur son
commit de départ, état `conflit_annule` : aucun arbre ne reste en conflit. La passe s'inscrit sous
`tasks/git_repo_upgrade/` comme une passe du menu, et rien n'est poussé.

<!-- [common] -->
```bash
.venv.erplibre/bin/python script/git/repo_apply.py --apply --confirm 18.0 --expect odoo18.0/addons/OCA_web
.venv.erplibre/bin/python script/git/repo_apply.py --apply --confirm 18.0 --expect odoo18.0/addons/OCA_web=UPSTREAM_SHA:HEAD_SHA
```
