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
./script/manifest/update_manifest_dev.sh
```

<!-- [en] -->
## local dev

[Guide to setup locally git](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

The script serves this checkout with `git daemon`, merges the manifests, and passes a branch to `repo init -b`,
never a bare commit: `repo init` refuses a commit on a new workspace.

<!-- [fr] -->
## dev local

[Guide pour configurer git localement](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

Le script sert ce checkout par `git daemon`, fusionne les manifestes, et passe une branche à `repo init -b`, jamais
un commit nu : `repo init` refuse un commit sur un espace de travail neuf.

<!-- [common] -->
```bash
./script/manifest/update_manifest_local_dev.sh
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
./script/git/git_show_code_diff_repo_manifest.py
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

Two gestures the word "update" used to cover. TODO › Execute › Git repository › Repo
separates them.

An **update** moves every project to the tip of the branch its manifest gives
it. It asks nothing, cannot conflict, and runs every morning.

An **upgrade** fetches the upstream a fork DESCENDS from — another repository,
at another organisation — and replays the commits the fork carries of its own.
It can conflict and it rewrites history, so it is observed before it is
applied.

A **pull** is the update of a deployed checkout that carries commits or changes
of its own: each repository integrates its target with `git pull`'s gestures
(fast-forward, rebase or merge), after a backup branch, and only what its dry
run showed. Entry 3 of TODO › Execute › Git repository › Repo, and the Odoo module
`erplibre_info_git_fetch`.

Every git command these tools send, reads included, is printed before it
runs, as `$ git -C <path> …` with the path relative to the ERPLibre root: the
command to copy from the root. The lines go to standard error, so the JSON of
`script/git/repo_state.py` on standard output stays intact. They are printed
when standard error is a terminal, as in TODO; `ERPLIBRE_GIT_ECHO=1` forces
them, `ERPLIBRE_GIT_ECHO=0` silences them. A URL loses its user and token
before it is printed.

<!-- [fr] -->
## Mise à jour ou mise à niveau

Deux gestes que le mot « mise à jour » recouvrait. TODO › Exécution › Répertoire git › Repo
les sépare.

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
et seulement ce que son essai à sec a montré. Entrée 3 de TODO › Exécution › Répertoire git ›
Repo, et le module Odoo `erplibre_info_git_fetch`.

Chaque commande git que ces outils envoient, lectures comprises, s'affiche
avant de partir, en `$ git -C <chemin> …` avec le chemin relatif à la racine
ERPLibre : la commande à recopier depuis la racine. Les lignes vont sur la
sortie d'erreur, si bien que le JSON de `script/git/repo_state.py` sur la
sortie standard reste intact. Elles s'affichent quand la sortie d'erreur est
un terminal, comme dans TODO ; `ERPLIBRE_GIT_ECHO=1` les force,
`ERPLIBRE_GIT_ECHO=0` les coupe. Une URL perd son utilisateur et son jeton
avant d'être affichée.

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
`erplibre_info_git_fetch` gives it a budget below the timeout of its call. A
call killed anyway takes its whole process group with it, and the backups of its
pass are read back by their stamp; the restart then waits for a new dry run.

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
(`saute_delai`), et la passe répond quand même. `erplibre_info_git_fetch` lui
donne un budget sous le délai de son appel. Un appel tué malgré tout emporte son
groupe de processus entier, et les sauvegardes de sa passe se relisent par leur
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
dry run and collects consent, such as `erplibre_info_git_fetch`. `--dry-run`
lists in `attendus` the `<path>=<target sha>:<HEAD sha>` pins of the
repositories it would pull; `--apply` takes them back with `--expect`, and
`--confirm` must be the active Odoo version (exit code 2 otherwise). A plan that
changed writes nothing (exit code 4). Shallow clones need `--approve-deepen` and
the pins of `attendus_superficiel`, new repositories `--approve-clone` and one
`--expect-clone` per path of `plan_nouveaux`; `--approve-deps` runs `poetry
install` at the end. `--path` restricts the pass to one repository (`.` is the
root), `--pass` gives its stamp and `--budget` its time budget. Exit code 5
means another pass holds the lock of the checkout.

<!-- [fr] -->
#### Tirer sans le menu

`script/git/repo_pull.py` écrit un objet JSON, pour un appelant qui montre
l'essai à sec et recueille le consentement, tel `erplibre_info_git_fetch`.
`--dry-run` liste dans `attendus` les épingles `<chemin>=<sha cible>:<sha HEAD>`
des dépôts qu'il tirerait ; `--apply` les reprend par `--expect`, et `--confirm`
doit valoir la version d'Odoo active (code de sortie 2 sinon). Un plan qui a
changé n'écrit rien (code de sortie 4). Les clones superficiels demandent
`--approve-deepen` et les épingles d'`attendus_superficiel`, les nouveaux dépôts
`--approve-clone` et un `--expect-clone` par chemin de `plan_nouveaux` ;
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

`Fork and upstream status` (TODO › Execute › Git repository › Repo) then lists, numbered from 1, the forks that carry both a
frozen commit and a frozen upstream base: `<base>..<frozen>` and `+N ours`, the commits of the fork between the two,
read in the clone without network. A fork that is not cloned, whose clone lacks one of the two commits, or whose
shallow history no longer links the base to the frozen commit, shows its reason instead; nothing is fetched. `N` opens that range in tig — `git log --oneline --graph` without tig — and `a`
opens each one in turn, stopping at a tig that does not exit with `q`.

### Add the upstream remotes

`Add the upstream remotes`, entry 4 of TODO › Execute › Git repository › Repo, or
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

Without history, a shallow clone has no merge base with its upstream, and the
diagnosis leaves it out of the upgrade. The dry run and the apply entry then
offer to deepen it, after the report, with no as the default answer: the whole
branch the fork follows comes first, `git fetch --unshallow <remote> <branch>`,
then its upstream branch in full, one clone after the other. Neither a local
branch nor the working tree moves. The diagnosis then runs again, and the fork
can be rebased like any complete clone. A clone that could not be completed
shows the same commands, to run by hand.

A remote added to the clone is not part of git-repo's state: a
`repo sync --force-sync` that rewrites the git directory loses it, and the next
dry run or `Add the upstream remotes` adds it again. The freeze does not count
the tracking branches of that remote as proof that the fork holds a commit.

### Apply the upgrade

`Apply the upgrade` (TODO › Execute › Git repository › Repo) asks for a confirmation (`y/N`), then handles each fork
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

`État des forks et de leurs amonts` (TODO › Exécution › Répertoire git › Repo) liste ensuite, numérotés à partir de 1, les forks
qui portent à la fois un commit gelé et une base amont gelée : `<base>..<gel>` et `+N à nous`, les commits du fork
entre les deux, lus dans le clone sans réseau. Un fork non cloné, dont le clone n'a pas l'un des deux commits, ou
dont l'historique superficiel ne relie plus la base au commit gelé, affiche son motif à la place ; rien n'est
récupéré. `N` ouvre cette plage dans tig — `git log --oneline --graph` sans
tig — et `a` les ouvre l'une après l'autre, en s'arrêtant sur un tig qui ne sort pas par `q`.

### Ajouter les remotes amont

`Ajouter les remotes amont`, l'entrée 4 de TODO › Exécution › Répertoire git › Repo, ou
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

Sans historique, un clone superficiel n'a pas de base de fusion avec son amont,
et le diagnostic le laisse hors de la mise à niveau. La passe à sec et
l'application proposent alors de l'approfondir, après le rapport, avec non
comme réponse par défaut : la branche que suit le fork d'abord, en entier,
`git fetch --unshallow <remote> <branche>`, puis sa branche amont complète, un
clone après l'autre. Ni branche locale ni arbre de travail ne bougent. Le
diagnostic tourne ensuite de nouveau, et le fork se rebase comme tout clone
complet. Un clone qui n'a pas pu être complété affiche les mêmes commandes, à
lancer à la main.

Un remote posé dans le clone ne fait pas partie de l'état de git-repo : un
`repo sync --force-sync` qui réécrit le répertoire git le perd, et la passe à
sec suivante ou `Ajouter les remotes amont` le repose. Le gel ne compte pas les
branches de suivi de ce remote comme la preuve que le fork porte un commit.

### Appliquer la mise à niveau

`Appliquer la mise à niveau` (TODO › Exécution › Répertoire git › Repo) demande une confirmation (`o/N`), puis
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
### Fork a repository for an organisation

`Fork a repository for an organisation` (TODO › Execute › Git repository) lists the GitHub projects of the
manifests of the active version, filtered by part of their path or name. Choose one and name the organisation, or
your own account, that receives the fork. Three questions follow, each with its default:

- For a project that is already a fork, which upstream the new fork keeps: the original one (default), so the remote
  becomes `<Organisation>_origin_OCA` and the `fork-upstream-*` attributes stay; or the current fork, so the remote
  becomes `<Organisation>_origin_ERPLibre`, `fork-upstream-remote` names the old remote, `fork-upstream` its branch
  and `fork-upstream-freeze-revision` its frozen commit. A project that is not a fork takes its old source as upstream.
- Which branches to copy: the active branch only (default), created in the fork on the frozen commit, or every branch
  of the source.
- Once forked, whether the manifest takes the fork, and in which versions: the active one by default, others by their
  number. `revision` and `freeze-revision` do not change, as the fork holds the same commits.

The GitHub token is `EL_GITHUB_TOKEN`, exported in the shell that opens TODO, or the one the token assistant stores in the ERPLibre KeePass vault; `env_var.sh` is read last, but it is versioned and would carry the token into a commit. A repository of the same name already in
the organisation is reused when it belongs to the same fork network, and refused otherwise. Commit `manifest/`, then
synchronise the repositories so the clone follows the fork.

<!-- [fr] -->
### Forker un dépôt pour une organisation

`Forker un dépôt pour une organisation` (TODO › Exécution › Répertoire git) liste les projets GitHub des manifestes
de la version active, filtrés par une partie de leur chemin ou de leur nom. Choisissez-en un et nommez l'organisation,
ou votre propre compte, qui reçoit le fork. Trois questions suivent, chacune avec son défaut :

- Pour un projet qui est déjà un fork, l'amont que garde le nouveau fork : celui d'origine (défaut), et le remote
  devient `<Organisation>_origin_OCA` avec des attributs `fork-upstream-*` inchangés ; ou le fork actuel, et le remote
  devient `<Organisation>_origin_ERPLibre`, `fork-upstream-remote` nomme l'ancien remote, `fork-upstream` sa branche
  et `fork-upstream-freeze-revision` son commit gelé. Un projet qui n'est pas un fork prend son ancienne source pour
  amont.
- Les branches à copier : la branche active seulement (défaut), créée dans le fork sur le commit gelé, ou toutes les
  branches de la source.
- Une fois le fork fait, si le manifeste le prend, et dans quelles versions : l'active par défaut, les autres par leur
  numéro. `revision` et `freeze-revision` ne changent pas : le fork porte les mêmes commits.

Le jeton GitHub est `EL_GITHUB_TOKEN`, exporté dans le shell qui ouvre TODO, ou celui que l'assistant du jeton range dans le coffre KeePass d'ERPLibre ; `env_var.sh` est lu en dernier, mais il est versionné et emporterait le jeton dans un commit. Un dépôt du même nom déjà dans
l'organisation est repris s'il appartient au même réseau de forks, et refusé sinon. Committez `manifest/`, puis
synchronisez les dépôts pour que le clone suive le fork.

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
`manifest/git_manifest_extra_odoo18.0.xml`, then into the private manifest of that version,
`private/manifest/git_manifest_private_odoo18.0.xml`, when it exists, and touches no clone. Each project is frozen in
the file that declares it: a repository of the private manifest never reaches `manifest/`, and the reverse. The other
merged files, the common `git_manifest_erplibre*.xml` fragments, the other installed versions and their private
manifests, are read but never written: their projects follow their branch. `--dry-run` shows what would change,
`--source` writes only some of these files and may be repeated; a file outside them is refused, since the
reconfiguration would ignore its freeze:

<!-- [fr] -->
UN seul fichier porte donc les deux lectures. Laquelle s'applique est un argument de l'installation ou de la
reconfiguration, conservé nulle part : le même checkout suit les commits ou les branches selon la façon dont il est
reconfiguré.

#### Écrire le gel

Le gel écrit dans les trois fichiers de la version d'Odoo active (`.odoo-version`), pour 18.0
`manifest/git_manifest_odoo18.0.xml`, `manifest/git_manifest_odoo18.0_dev.xml` et
`manifest/git_manifest_extra_odoo18.0.xml`, puis dans le manifeste privé de cette version,
`private/manifest/git_manifest_private_odoo18.0.xml`, s'il existe, et ne touche aucun clone. Chaque projet est gelé
dans le fichier qui le déclare : un dépôt du manifeste privé n'atteint jamais `manifest/`, et l'inverse. Les autres
fichiers fusionnés, les fragments communs `git_manifest_erplibre*.xml`, les autres versions installées et leurs
manifestes privés, sont lus mais jamais écrits : leurs projets suivent leur branche. `--dry-run` montre ce qui
changerait, `--source` n'écrit qu'une partie de ces fichiers et se répète ; un fichier hors d'eux est refusé, puisque
la reconfiguration ignorerait son gel :

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
command exits with 1 when nothing was frozen. A freeze written into the private manifest is committed with `private/`,
which only a private repository carries.

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
partie du gel. La commande sort avec 1 quand rien n'a été gelé. Un gel écrit dans le manifeste privé se commite avec
`private/`, que seul un dépôt privé porte.

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
the files the freeze does not write. The header of TODO › Execute › Git repository › Repo counts the forks with an upstream
base, read from the files without network.

#### Freeze the branches

`--branches`, or `make repo_freeze BRANCHES=1`, also writes in `revision` the branch each clone is on, when it differs
from the manifest: a clone left by the fork upgrade on its dated branch `<branch>_maj_<YYYYMMDD>` makes the
reconfiguration follow that branch, while `freeze-revision` pins its commit. A detached HEAD changes nothing, and a
`revision` that is already a commit is never replaced by a branch.

Only a branch that the project's remote carries, its tracking branch containing the frozen commit, is written; the
others are listed, and their project keeps its branch: `branch not on the remote`, `branch ahead of the remote`,
`branch diverged from the remote`. The script pushes nothing. In TODO, the freeze asks after the upstream base whether
to freeze the branches too, No by default; before the dry run, it lists the branches missing from their remote or
ahead of it and offers to push them, all, one by one or none, none by default. Each push puts the local branch on the
branch of the same name, never forced: a diverged branch stays listed. `make repo_unfreeze` keeps `revision`.

A dated `revision` returns to its base branch, with or without `--branches`, once the remote's base branch contains the
frozen commit: that is the state the publication of a pass leaves, the dated branch pushed onto the fork's branch and
the clone detached on it. The fork upgrade always works on the base branch: a pass names `<branch>_maj_<YYYYMMDD>` and
publishes onto `<branch>`, never onto a dated branch, and the cleanup of merged branches never offers the branch the
manifest follows.

#### Push the repositories to a remote

TODO › Execute › Git repository › Repo › Push the repositories to a remote, or `make repo_push_remote REMOTE=<name>`,
pushes every cloned repository of the active Odoo version to a remote of the clones, eight at a time, never forced:
a remote that holds commits the clone lacks refuses the update, and the refusal is reported. The remote is one the
clones already carry, or a new one set from the base URL of a forge (`URL=`): each clone receives
`<base>/<owner>/<repo>.git`, the owner being the last segment of the `fetch` URL of its manifest remote, so the forge
gets the same tree as the original host. A new remote cannot take the name of a manifest remote, whose URL git-repo
rewrites at every sync; it fetches no tags and `skipFetchAll` keeps it out of `git fetch --all`. A clone where the
name already points to another repository keeps it and is left out.

The content is asked for, the lightest by default: `manifest`, the checked-out commit on the branch the manifest
follows, without a dated suffix; or `all` (`MODE=all`), every local branch, every tracking branch of the manifest
remote and every tag. A shallow clone is pushed as is unless its full history is fetched first, which TODO asks for
and `UNSHALLOW=1` requests: many servers refuse a truncated history. `DRY_RUN=1` shows the refspecs and pushes nothing.

When the freeze offers to push the branches it cannot write, it pushes them the same way, in parallel, and can target
another remote of the clones; the freeze still writes a branch only when the manifest remote carries it.

TODO first asks whether to push the ERPLibre repository too, the one that holds `manifest/`, Yes by default: its
checked-out branch goes under the same name to `<base>/<owner>/<repo>.git`, the owner and the name read from its
`origin` URL, so a new installation can start from the forge.

Instead of a URL, `qemu` creates the forge in a local QEMU VM (Ubuntu 24.04, 4 vCPU, 4 GB, 60 GB; 15 to 40 minutes,
`sudo` to create the VM). Once cloud-init has finished, which trusts the host's download cache, the VM receives the
code of this checkout through a git bundle, `.venv.erplibre` only, no Odoo, then Forgejo with push-to-create, registration closed, private repositories by default and shallow pushes
accepted. The administrator account must not share a name with an owner of the repositories, case aside. Its
password, drawn at random and passed on standard input, and the token created with it are stored in the KeePass vault
(`Forgejo admin <host:port>`, `Forgejo token <host:port>`); without a vault, the password is shown once. Your SSH
public key is added to that account, and the forge's host key replaces any older one for the same address in
`~/.ssh/known_hosts`. The forge's web URL and token stay known for the session: preparing the forge asks neither for
a token nor for consent to plain HTTP, which only crosses the host's libvirt bridge. A failed step leaves the VM in
place with its log, `~/.erplibre/forge/<vm>.log`.

#### Sync from a forge: a private manifest overlay

After a push to a forge remote, TODO offers, No by default, to write `private/manifest/git_manifest_forge_<remote>.xml`;
TODO › Repo › Sync from a forge writes or removes it at any time. The overlay holds only `<remote>` elements: each
manifest remote of the pushed repositories keeps its name and gets `<base>/<owner>/` as `fetch`. The file is listed
last in `private/default_git_manifest.csv`, and the merge gives the last file that defines a remote the last word, so
projects, revisions and freezes are unchanged and the forge's address stays out of `manifest/`; the upstream base of
the freeze (`UPSTREAM=1`) ignores the overlay, since the forge does not hold the forks' upstreams. A remote is
redirected whole: the projects of the merged manifests that it serves but that are not on the forge, those of the
fragments common to every version for instance, are listed, and the choice is then `partial` (by default: only the
remotes whose every project is on the forge), `all` or `cancel`. From the menu, a clone counts as on the forge when
its remote points to `<base>/<owner>/<repo>.git` and `git ls-remote` finds its manifest branch there. It takes effect
at the next reconfiguration, which TODO offers in the checkout's current mode, No by default; removing the file and
reconfiguring brings back the original URLs. The remote's name must suit a file name: letters, digits, `.`, `-`,
`_`.

#### Open pull requests on a forge

TODO › Repo › Open pull requests on a forge takes a forge remote of the clones and every clone whose checked-out
branch is not its manifest branch. After one confirmation, each branch is pushed under its own name, in parallel and
never forced, then a pull request goes from it to the manifest branch in the same forge repository, titled with the
subject of its last commit. A clone is skipped when the manifest branch is missing on the forge, or when it already
holds the branch's commit. An open pull request for the same pair is reused, never duplicated.

#### Follow the pull requests of a forge

TODO › Repo › Follow the pull requests of a forge takes a forge remote of the clones and reads, through the API, the
forge repository of every clone that carries it, plus the ERPLibre repository when it carries the same remote. A pull
request concerns a clone when its head is one of the clone's local branches, from the same forge repository and not
from a fork of the same name, or when its base is the clone's manifest branch. Every open one is read; among the
closed ones, only the five most recently updated. Each line gives the state (open, draft, merged, closed), the number
of comments (💬, the `comments` field of the pull request), then, for an open one, the review — the last decisive
review of each reviewer: one request for changes outweighs the approvals — and the CI, the combined status of the head
commit, which Forgejo Actions fills in. A merged one says whether its merge commit is already in the local branch of
its base. Titles and URLs come from the forge: their control characters are shown as `?`. A repository missing from
the forge is reported and the others go on.

The merged work that the local branches lack is then offered, one line per repository and base, by numbers, `all`, or
Enter for none. Fetching it runs under the lock of the pull passes, ERPLibre first, then the clones in parallel. The
fetch moves the tracking ref `<remote>/<base>` only. A missing local branch is created, without upstream
configuration, so `repo sync` and `repo prune` leave it alone; an existing one only moves by fast-forward: when
checked out, on a work tree without tracked changes; otherwise git refuses a non-fast-forward and a branch checked out
in another worktree. A local branch that is ahead, diverged, or that a shallow clone cannot compare is left as is and
reported, as is a clone in the middle of a rebase or a merge. No checked-out branch changes outside a fast-forward,
no branch is deleted, nothing is pushed and nothing is written on the forge. A merged commit that the tracking branch
of the manifest remote lacks is flagged: the next sync would bring back the upstream tip; push it (Push the
repositories to a remote, mode `all`) or sync through an overlay of that remote.

When the checkout has a freeze, the freeze of the projects that are already frozen then moves to the fetched commit,
only forward: the merged commit must descend from the frozen one, and the project must be declared with a `path` and
merged into its manifest branch. The commit must also be published at the manifest URL — a commit on the forge only
would break every installation without the private overlay, since `manifest/` is tracked; the command to push it is
shown otherwise. TODO previews each file and project, then writes after a confirmation, No by default. Changing the
freeze removes `fork-upstream-freeze-revision`, and the files of other Odoo versions that carry the same freeze
move too. The token needs no `issue` scope: everything is read from the pull request and repository endpoints.

#### Prepare a Forgejo forge

A new remote set from a forge URL offers, before pushing, to check the forge through its API (Forgejo, `/api/v1`)
and to create the missing organisations, private: push-to-create never creates the owner of a repository, so each
organisation must exist before the first push. Names are compared without case, as Forgejo does, and a name Forgejo
refuses (letters, digits, `-`, `_`, `.`, 40 characters at most) is reported, not sent. The repositories are created
through the API only on request, private and empty: a forge set for push-to-create creates them on the first push.
Anything that already exists is reused, never changed. An owner that is the account of the token gets its
repositories on that account; another user account is reported and left out.

The API lives at the web URL of the forge, asked for when the remote is an SSH URL. The access token, with the
`write:organization`, `write:repository` and `write:user` scopes, comes from `EL_FORGEJO_TOKEN`, then from the
ERPLibre KeePass vault, one entry per forge (host and port) in the `ERPLibre Forgejo` group. Otherwise TODO offers
three ways, the first by default: paste it without echo; create it through the API with the account name and
password, which over plain HTTP to another host asks its own confirmation, No by default; or create it on the forge host over SSH with the Forgejo admin CLI, at the paths of the repository's
installer and with `sudo` without a password (`sudo -n -u git /usr/local/bin/forgejo admin user generate-access-token
… --raw`). It may then be stored in the vault; when no vault is configured, TODO offers to create one, through the
same flow as the VPN secrets: a path, a master password typed twice, a file in mode 0600, and `kdbx.path` written to
the private configuration, which git does not track. A refused token can be typed again, and the new one replaces
the stored entry. It travels only in the `Authorization` header, never in a URL nor in `env_var.sh`, which the repository
tracks, and an error message that would carry it masks it. The client ignores `~/.netrc`, which would otherwise
replace the token with a password, and follows no redirect, which would turn a creation into a read. Plain HTTP to
another host than this machine asks for confirmation, No by default. Without a menu, `make forge_prepare URL=<web
URL>` does the same (`CREATE_REPOS=1`, `DRY_RUN=1`), and refuses plain HTTP unless `--allow-http`.

#### Follow the origins: mirrors on the forge

TODO › Repo › Follow the origins: mirrors on the forge gives each forge repository `<owner>/<repo>` a native Forgejo
pull mirror `<owner>-mirror/<repo>`: a private organisation per owner, the repository name unchanged. A mirror is
read-only, it accepts neither push nor pull request, hence a separate namespace; a mirror organisation whose name
matches a known owner, without regard to case, is left out, as is an owner whose name already ends in `-mirror`. The
forge refreshes each mirror every interval chosen at creation (`1h` by default, `10m` at least, the Forgejo `[mirror]
MIN_INTERVAL`). The origin is the manifest remote of the project, the fork on GitHub, not the fork's upstream;
ERPLibre itself follows on the branches typed, `develop` and `master` by default when they exist under
`refs/remotes/origin`, never a branch that heads an open pull request on the forge. Only an origin that reads
anonymously over https is followed: a private origin is reported and left out, and no GitHub token ever enters the
forge. Names, collisions and the configuration are checked before the first API call; an existing repository is never
changed, and one that is not a mirror is reported as a failure. A repository that is not the mirror of the manifest
origin is not followed, and any pair the host already holds for its working repository is removed.

A systemd timer on the forge host (`erplibre-forge-sync.timer`, hourly, `Persistent`) then moves each working branch
to the tip of its mirror, by fast-forward only. It reads the bare repositories of the forge on disk and pushes from
the mirror to the working repository through the forge over local HTTP, so hooks run and the base of every pull
request updates. The push is never forced: git refuses, on the client side, a tip that is not an ancestor of the
mirror tip. A working repository missing on disk receives nothing, since the forge creates repositories on push.

| State | Meaning |
|---|---|
| `a_jour` | the working branch is the mirror tip |
| `avance` | fast-forwarded to the mirror tip |
| `creee` | branch created from the mirror (ERPLibre branches only) |
| `en_avance` | the working branch is ahead of the origin: merged work not published yet |
| `divergent` | both moved; left as is, with the date it was first seen |
| `absente`, `absente_miroir` | the branch is missing from the working repository, or from the mirror |
| `depot_absent` | the working repository is missing from the forge |
| `refuse`, `erreur` | the forge or git refused the push; the pass fails |

A pull request merged on the forge makes its base `en_avance`; once the origin moves too, it becomes `divergent`.
Resolve it in a clone: merge or rebase the origin, then push, or publish the change upstream so that the origin
catches up. The entry also shows the last pass (`s`) or runs one now (`n`).

On the forge host, the configuration lives in `/etc/erplibre-forge-sync/config.json`, the forge URL, the repository
root and the account in `/etc/erplibre-forge-sync/environment`, and the state of the last pass in
`/var/lib/erplibre-forge-sync/etat.json`. The token, with the `write:repository` scope, is created on the host by the
Forgejo admin CLI, stored in `/etc/erplibre-forge-sync/token` (root, 0600), and reaches the service only through
systemd `LoadCredential=`; it never leaves the host and is never shown. TODO sends the configuration over standard
input and nothing secret.

```bash
sudo systemctl start erplibre-forge-sync.service     # one pass now
journalctl -u erplibre-forge-sync                    # its log
sudo systemctl disable --now erplibre-forge-sync.timer
FORGE_SYNC_ACCOUNT=<account> FORGE_SYNC_NEW_TOKEN=1 bash ~/.erplibre-forge-sync/install_forge_sync.sh
```

The last line replaces the token; an older one stays valid until it is revoked in the web interface (Settings ›
Applications). This needs a forge installed by `install_forgejo.sh` and `sudo` without a password on its host. The
installer refuses a `[repository] ROOT` under `/home`, `/root` or `/run/user`: the unit sets `ProtectHome=true`, and
every repository there would read as `depot_absent`.

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
fichiers que le gel n'écrit pas. L'en-tête de TODO › Exécution › Répertoire git › Repo compte les forks qui ont une base amont, lue
dans les fichiers sans réseau.

#### Geler les branches

`--branches`, ou `make repo_freeze BRANCHES=1`, écrit aussi dans `revision` la branche de chaque clone, quand elle
diffère de celle du manifeste : un clone que la mise à jour des forks laisse sur sa branche datée
`<branche>_maj_<AAAAMMJJ>` fait suivre cette branche à la reconfiguration, tandis que `freeze-revision` épingle son
commit. Une tête détachée ne change rien, et une `revision` qui est déjà un commit n'est jamais remplacée par une
branche.

Seule une branche que le remote du projet porte, sa branche de suivi contenant le commit gelé, s'écrit ; les autres
sont listées, et leur projet garde sa branche : `branch not on the remote`, `branch ahead of the remote`,
`branch diverged from the remote`. Le script ne pousse rien. Dans TODO, le gel demande après la base amont s'il gèle
aussi les branches, Non par défaut ; avant la passe à sec, il liste les branches absentes de leur remote ou en avance
sur lui et propose de les pousser, toutes, une à une ou aucune, aucune par défaut. Chaque push porte la branche locale
sur la branche homonyme, jamais de force : une branche divergente reste listée. `make repo_unfreeze` garde `revision`.

Une `revision` datée revient à sa branche de base, avec ou sans `--branches`, dès que la branche de base du remote
contient le commit gelé : c'est l'état que laisse la publication d'une passe, la copie datée poussée sur la branche du
fork et le clone détaché dessus. La mise à jour des forks travaille toujours sur la branche de base : une passe nomme
`<branche>_maj_<AAAAMMJJ>` et publie sur `<branche>`, jamais sur une copie datée, et le nettoyage des branches
fusionnées ne propose jamais la branche que suit le manifeste.

#### Pousser les dépôts vers un remote

TODO › Exécution › Répertoire git › Repo › Pousser les dépôts vers un remote, ou `make repo_push_remote REMOTE=<nom>`,
pousse chaque dépôt cloné de la version d'Odoo active vers un remote des clones, huit à la fois, jamais de force : un
distant qui porte des commits que le clone n'a pas refuse la mise à jour, et le refus est rapporté. Le remote est l'un
de ceux que les clones portent déjà, ou un remote neuf posé à partir de l'URL de base d'une forge (`URL=`) : chaque
clone reçoit `<base>/<propriétaire>/<dépôt>.git`, le propriétaire étant le dernier segment de l'URL `fetch` du remote
de son manifeste, si bien que la forge reçoit la même arborescence que l'hôte d'origine. Un remote neuf ne peut pas
prendre le nom d'un remote du manifeste, dont git-repo réécrit l'URL à chaque synchronisation ; il ne récupère pas les
étiquettes et `skipFetchAll` l'écarte de `git fetch --all`. Un clone où ce nom vise déjà un autre dépôt le garde et
est laissé de côté.

Le contenu se demande, le plus léger par défaut : `manifest`, le commit extrait sur la branche que suit le manifeste,
sans suffixe daté ; ou `all` (`MODE=all`), chaque branche locale, chaque branche de suivi du remote du manifeste et
chaque étiquette. Un clone superficiel se pousse tel quel, sauf si tout son historique est récupéré d'abord, ce que
TODO demande et que `UNSHALLOW=1` réclame : beaucoup de serveurs refusent un historique tronqué. `DRY_RUN=1` montre les
refspecs et ne pousse rien.

Quand le gel propose de pousser les branches qu'il ne peut écrire, il les pousse de la même façon, en parallèle, et
peut viser un autre remote des clones ; le gel n'écrit toujours une branche que si le remote du manifeste la porte.

TODO demande d'abord s'il pousse aussi le dépôt ERPLibre, celui qui porte `manifest/`, Oui par défaut : sa branche
extraite part sous le même nom vers `<base>/<propriétaire>/<dépôt>.git`, le propriétaire et le nom lus dans son URL
`origin`, pour qu'une installation neuve puisse partir de la forge.

Au lieu d'une URL, `qemu` crée la forge dans une VM QEMU locale (Ubuntu 24.04, 4 vCPU, 4 Go, 60 Go ; de 15 à 40
minutes, `sudo` pour créer la VM). Une fois cloud-init terminé, qui fait approuver le cache de téléchargement de l'hôte,
la VM reçoit le code de ce checkout par un bundle git, `.venv.erplibre` seul, sans Odoo, puis Forgejo en push-to-create, inscriptions fermées, dépôts privés par défaut et push de clone superficiel
accepté. Le compte administrateur ne doit pas porter le nom d'un propriétaire des dépôts, casse mise à part. Son mot de
passe, tiré au hasard et passé par l'entrée standard, et le jeton créé avec lui se rangent dans le coffre KeePass
(`Forgejo admin <hôte:port>`, `Forgejo token <hôte:port>`) ; sans coffre, le mot de passe s'affiche une fois. Votre clé
publique SSH est ajoutée à ce compte, et la clé d'hôte de la forge remplace toute ancienne clé de la même adresse dans
`~/.ssh/known_hosts`. L'URL web et le jeton de la forge restent connus de la session : la préparation de la forge ne
demande ni jeton ni accord pour le HTTP en clair, qui ne traverse que le pont libvirt de la machine. Une étape échouée
laisse la VM en place avec son journal, `~/.erplibre/forge/<vm>.log`.

#### Synchroniser depuis une forge : une surcouche de manifeste privée

Après un push vers un remote de forge, TODO propose, Non par défaut, d'écrire
`private/manifest/git_manifest_forge_<remote>.xml` ; TODO › Repo › Synchroniser depuis une forge l'écrit ou la retire
à tout moment. La surcouche ne porte que des éléments `<remote>` : chaque remote du manifeste des dépôts poussés garde
son nom et prend `<base>/<propriétaire>/` pour `fetch`. Le fichier est inscrit en dernier dans
`private/default_git_manifest.csv`, et la fusion donne le dernier mot au dernier fichier qui définit un remote : les
projets, révisions et gels ne changent pas, et l'adresse de la forge reste hors de `manifest/` ; la base amont du gel
(`UPSTREAM=1`) ignore la surcouche, la forge ne portant pas les amonts des forks. Un remote est redirigé en entier :
les projets des manifestes fusionnés qu'il sert sans être sur la forge, ceux des fragments communs à toutes les
versions par exemple, sont listés, et le choix porte alors sur `partial` (par défaut : seuls les remotes dont chaque
projet est sur la forge), `all` ou `cancel`. Depuis le menu, un clone compte comme présent sur la forge quand son remote
vise `<base>/<propriétaire>/<dépôt>.git` et que `git ls-remote` y trouve la branche de son manifeste. Elle prend effet
à la reconfiguration suivante, que TODO propose dans le mode actuel du checkout, Non par défaut ; retirer le fichier
puis reconfigurer ramène les URL d'origine. Le nom du remote doit convenir à un nom de fichier : lettres, chiffres,
`.`, `-`, `_`.

#### Ouvrir des pull requests sur une forge

TODO › Repo › Ouvrir des pull requests sur une forge prend un remote de forge des clones et chaque clone dont la
branche extraite n'est pas celle de son manifeste. Après une seule confirmation, chaque branche se pousse sous son nom,
en parallèle et jamais de force, puis une pull request va d'elle vers la branche du manifeste dans le même dépôt de la
forge, titrée du sujet de son dernier commit. Un clone est écarté quand la branche du manifeste manque sur la forge, ou
qu'elle porte déjà le commit de la branche. Une pull request ouverte pour la même paire est reprise, jamais doublée.

#### Suivre les pull requests d'une forge

TODO › Repo › Suivre les pull requests d'une forge prend un remote de forge des clones et lit, par l'API, le dépôt de
la forge de chaque clone qui le porte, plus le dépôt ERPLibre quand il porte le même remote. Une pull request concerne
un clone quand sa tête est l'une de ses branches locales, venue du même dépôt de la forge et non d'un fork homonyme, ou
quand sa base est la branche du manifeste du clone. Toutes les ouvertes sont lues ; parmi les fermées, les cinq
modifiées le plus récemment. Chaque ligne donne l'état (ouverte, brouillon, fusionnée, fermée), le nombre de
commentaires (💬, le champ `comments` de la pull request), puis, pour une ouverte, la revue — le dernier avis décisif
de chaque relecteur : une demande de changements l'emporte sur les approbations — et la CI, le statut combiné du
commit de tête, que Forgejo Actions renseigne. Une fusionnée dit si son commit de fusion est déjà dans la branche
locale de sa base. Les titres et les URL viennent de la forge : leurs caractères de contrôle s'affichent en `?`. Un
dépôt absent de la forge est signalé et les autres continuent.

Le travail fusionné qui manque aux branches locales est ensuite proposé, une ligne par dépôt et par base, par
numéros, `all`, ou Entrée pour aucun. Le rapatriement tourne sous le verrou des passes de tirage, ERPLibre d'abord,
puis les clones en parallèle. Le fetch ne déplace que la ref de suivi `<remote>/<base>`. Une branche locale absente
est créée, sans configuration de suivi, si bien que `repo sync` et `repo prune` l'ignorent ; une branche existante
n'avance qu'en fast-forward : extraite, sur un arbre sans modification suivie ; sinon git refuse un non-fast-forward
et une branche extraite dans un autre worktree. Une branche locale en avance, divergée, ou qu'un clone superficiel ne
permet pas de comparer reste telle quelle et est signalée, comme un clone au milieu d'un rebase ou d'une fusion.
Aucune branche extraite ne change hors d'un fast-forward, aucune branche n'est supprimée, rien n'est poussé et rien
ne s'écrit sur la forge. Un commit fusionné qui manque à la branche de suivi du remote du manifeste est signalé : la
synchronisation suivante ramènerait la pointe de l'amont ; le pousser (Pousser les dépôts vers un remote, mode `all`)
ou synchroniser par une surcouche de ce remote.

Quand le checkout a un gel, le gel des projets déjà gelés avance ensuite vers le commit rapatrié, vers l'avant
seulement : le commit fusionné doit descendre du commit gelé, et le projet doit être déclaré avec un `path` et
fusionné dans sa branche du manifeste. Le commit doit aussi être publié à l'URL du manifeste — un commit présent sur
la forge seulement casserait toute installation sans la surcouche privée, puisque `manifest/` est versionné ; la
commande pour le pousser est affichée sinon. TODO montre chaque fichier et chaque projet, puis écrit après une
confirmation, Non par défaut. Changer le gel retire `fork-upstream-freeze-revision`, et les fichiers des autres
versions d'Odoo qui portent le même gel avancent aussi. Le jeton n'a pas besoin de la portée `issue` : tout se lit
par les routes des pull requests et du dépôt.

#### Préparer une forge Forgejo

Un remote neuf posé à partir de l'URL d'une forge propose, avant le push, de vérifier la forge par son API (Forgejo,
`/api/v1`) et de créer les organisations manquantes, privées : le push-to-create ne crée jamais le propriétaire d'un
dépôt, chaque organisation doit donc exister avant le premier push. Les noms se comparent sans égard à la casse, comme
le fait Forgejo, et un nom que Forgejo refuse (lettres, chiffres, `-`, `_`, `.`, 40 caractères au plus) est signalé,
pas envoyé. Les dépôts se créent par l'API seulement sur demande, privés et vides : une forge réglée en push-to-create
les crée au premier push. Ce qui existe déjà est repris, jamais modifié. Un propriétaire qui est le compte du jeton
reçoit ses dépôts sur ce compte ; un autre compte utilisateur est signalé et laissé de côté.

L'API se trouve à l'URL web de la forge, demandée quand le remote est une URL SSH. Le jeton d'accès, avec les portées
`write:organization`, `write:repository` et `write:user`, vient de `EL_FORGEJO_TOKEN`, puis du coffre KeePass
d'ERPLibre, une entrée par forge (hôte et port) dans le groupe `ERPLibre Forgejo`. Sinon TODO propose trois façons, la
première par défaut : le coller sans écho ; le créer par l'API avec l'identifiant et le mot de passe du compte, qui demande en HTTP clair vers un autre hôte sa propre confirmation, Non par défaut ; ou le
créer sur l'hôte de la forge par SSH avec la CLI d'administration de Forgejo, aux chemins de l'installateur du dépôt et
avec `sudo` sans mot de passe (`sudo -n -u git /usr/local/bin/forgejo admin user generate-access-token … --raw`). Il
peut ensuite être rangé dans le coffre ; sans coffre configuré, TODO propose d'en créer un, par le même parcours que
les secrets VPN : un chemin, un mot de passe maître saisi deux fois, un fichier en mode 0600, et `kdbx.path` écrit dans
la configuration privée, que git ne suit pas. Un jeton refusé peut se ressaisir, et le nouveau remplace l'entrée
rangée. Il ne circule que dans
l'en-tête `Authorization`, jamais dans une URL ni dans `env_var.sh`, que le dépôt suit, et un message d'erreur qui le
porterait le masque. Le client ignore `~/.netrc`, qui remplacerait sinon le jeton par un mot de passe, et ne suit
aucune redirection, qui changerait une création en lecture. HTTP en clair vers un autre hôte que cette machine demande
confirmation, Non par défaut. Sans menu, `make forge_prepare URL=<URL web>` fait de même (`CREATE_REPOS=1`,
`DRY_RUN=1`), et refuse HTTP en clair sauf avec `--allow-http`.

#### Suivre les origines : miroirs sur la forge

TODO › Repo › Suivre les origines : miroirs sur la forge donne à chaque dépôt `<propriétaire>/<dépôt>` de la forge un
miroir natif Forgejo `<propriétaire>-mirror/<dépôt>` : une organisation privée par propriétaire, le nom du dépôt
inchangé. Un miroir est en lecture seule, il n'accepte ni push ni pull request, d'où un espace de noms à part ; une
organisation de miroirs dont le nom recouvre celui d'un propriétaire connu, sans égard à la casse, est écartée, comme
un propriétaire dont le nom finit déjà par `-mirror`. La forge rafraîchit chaque miroir à l'intervalle choisi à la
création (`1h` par défaut, `10m` au moins, le `[mirror] MIN_INTERVAL` de Forgejo). L'origine est le remote du
manifeste du projet, le fork sur GitHub, et non l'amont de ce fork ; ERPLibre lui-même se suit sur les branches
saisies, par défaut `develop` et `master` quand elles existent sous `refs/remotes/origin`, jamais une branche qui
porte une pull request ouverte sur la forge. Seule une origine lisible anonymement en https se suit : une origine
privée est signalée et écartée, et aucun jeton GitHub n'entre jamais dans la forge. Noms, collisions et configuration
se vérifient avant le premier appel à l'API ; un dépôt existant n'est jamais modifié, et celui qui n'est pas un miroir
compte comme un échec. Un dépôt qui n'est pas le miroir de l'origine du manifeste ne se suit pas, et la paire que
l'hôte porterait déjà pour son dépôt de travail se retire.

Un minuteur systemd sur l'hôte de la forge (`erplibre-forge-sync.timer`, toutes les heures, `Persistent`) avance
ensuite chaque branche de travail jusqu'à la pointe de son miroir, en fast-forward seulement. Il lit les dépôts nus de
la forge sur le disque et pousse du miroir vers le dépôt de travail par la forge, en HTTP local : les hooks tournent
et la base de chaque pull request se met à jour. Le push n'est jamais forcé : git refuse, côté client, une pointe qui
n'est pas un ancêtre de celle du miroir. Un dépôt de travail absent du disque ne reçoit rien, puisque la forge crée
les dépôts au push.

| État | Sens |
|---|---|
| `a_jour` | la branche de travail est la pointe du miroir |
| `avance` | avancée en fast-forward jusqu'à la pointe du miroir |
| `creee` | branche créée depuis le miroir (branches d'ERPLibre seulement) |
| `en_avance` | la branche de travail est en avance sur l'origine : du travail fusionné pas encore publié |
| `divergent` | les deux ont bougé ; laissée telle quelle, avec la date où c'est vu la première fois |
| `absente`, `absente_miroir` | la branche manque au dépôt de travail, ou au miroir |
| `depot_absent` | le dépôt de travail manque sur la forge |
| `refuse`, `erreur` | la forge ou git a refusé le push ; la passe échoue |

Une pull request fusionnée sur la forge met sa base `en_avance` ; dès que l'origine bouge aussi, elle devient
`divergent`. Cela se résout dans un clone : fusionner ou rebaser l'origine, puis pousser, ou publier le changement
en amont pour que l'origine le rattrape. L'entrée montre aussi la dernière passe (`s`) ou en lance une (`n`).

Sur l'hôte de la forge, la configuration vit dans `/etc/erplibre-forge-sync/config.json`, l'URL de la forge, la
racine des dépôts et le compte dans `/etc/erplibre-forge-sync/environment`, et l'état de la dernière passe dans
`/var/lib/erplibre-forge-sync/etat.json`. Le jeton, de portée `write:repository`, se crée sur l'hôte par la CLI
d'administration de Forgejo, se range dans `/etc/erplibre-forge-sync/token` (root, 0600) et n'atteint le service que
par `LoadCredential=` de systemd ; il ne quitte jamais l'hôte et ne s'affiche jamais. TODO envoie la configuration par
l'entrée standard, et rien de secret.

```bash
sudo systemctl start erplibre-forge-sync.service     # une passe maintenant
journalctl -u erplibre-forge-sync                    # son journal
sudo systemctl disable --now erplibre-forge-sync.timer
FORGE_SYNC_ACCOUNT=<compte> FORGE_SYNC_NEW_TOKEN=1 bash ~/.erplibre-forge-sync/install_forge_sync.sh
```

La dernière ligne remplace le jeton ; un ancien reste valide tant qu'il n'est pas révoqué dans l'interface web
(Paramètres › Applications). Il faut une forge posée par `install_forgejo.sh` et `sudo` sans mot de passe sur son
hôte. L'installateur refuse un `[repository] ROOT` sous `/home`, `/root` ou `/run/user` : l'unité pose
`ProtectHome=true`, et chaque dépôt rangé là se lirait `depot_absent`.

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
stays written, ready for the next `FREEZE=1`. `make repo_unfreeze` removes it from every source file, the private
manifest of every Odoo version included:

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
prêt pour le prochain `FREEZE=1`. `make repo_unfreeze` le retire de tous les fichiers sources, manifeste privé de
chaque version d'Odoo compris :

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
In TODO › Execute › Git repository › Repo, entry 15 offers the usual comparisons, a choice of two revisions among the freeze commits and the
ERPLibre branches and tags, and the matrix. On the report: a number opens tig on that project, `a` on each in turn,
`b N` the graph with the branches, `l` the log, `d` and `s N` the diffstats, `g` the next grouping, `f` the refresh,
`w` the command that opens an old commit in a git worktree beside the clone, without moving it.

<!-- [fr] -->
Dans TODO › Exécution › Répertoire git › Repo, l'entrée 15 propose les comparaisons courantes, le choix de deux révisions parmi les commits de
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
a module copied into the clone; ignored files (`.pyc`, `__pycache__`) do not count.
That state compares HEAD with the local manifest only, which follows a branch outside a frozen checkout; `freeze`
compares HEAD with the `freeze-revision` that the merge applies — from the files of the active Odoo version and from
the common fragments listed in `conf/` — and gives `ahead`, `behind` and an alignment: `conforme`, `en_avance` (the
freeze needs redoing), `en_retard` (the clone needs to move forward), `decale`, `introuvable` (the frozen commit is
not in the clone), `indetermine` (a shallow clone where both sides seem to hold commits) or `erreur`. `fingerprint` hashes everything
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
Cet état ne compare HEAD qu'au manifeste local, qui suit une branche hors d'un checkout gelé ; `freeze` compare HEAD
au `freeze-revision` qu'applique la fusion — celui des fichiers de la version d'Odoo active et des fragments communs
listés dans `conf/` — et donne `ahead`, `behind` et un alignement : `conforme`, `en_avance` (le gel est à refaire),
`en_retard` (le clone est à avancer), `decale`, `introuvable` (le commit gelé n'est pas dans le clone),
`indetermine` (un clone tronqué où les deux côtés semblent porter des commits) ou `erreur`.
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
already shown the dry run and collected consent, such as the Odoo module `erplibre_info_git_fetch`; it prints JSON. It runs the
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
qui a déjà montré l'essai à sec et recueilli le consentement, tel le module Odoo `erplibre_info_git_fetch` ; il écrit du JSON.
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
