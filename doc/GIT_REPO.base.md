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

## Make a new version of prod

It freezes all repo, from dev to prod.

This will add revision git hash in the manifest.

<!-- [fr] -->
# Créer un Manifest

Un [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md) est un fichier XML géré par
git-repo pour générer un dépôt.

## Créer une nouvelle version de prod

Cela fige tous les dépôts, du dev vers la prod.

Cela ajoutera le hash de révision git dans le manifest.

<!-- [common] -->
```bash
.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

<!-- [en] -->
Commit.

<!-- [fr] -->
Committez.

<!-- [common] -->
```bash
git commit -am "[#ticket] subject: short sentence"
```

<!-- [en] -->
### Mix prod and dev to create a stage version

When dev contains specific revision with default revision, you need to replace default revision with prod revision and
keep specific version:

<!-- [fr] -->
### Mélanger prod et dev pour créer une version de staging

Lorsque dev contient une révision spécifique avec la révision par défaut, vous devez remplacer la révision par défaut par la révision prod et garder la version spécifique :

<!-- [common] -->
```bash
./script/git/git_merge_repo_manifest.py --input "./manifest/default.dev.xml;./default.xml" --output ./manifest/default.staged.xml
git commit -am "Updated manifest/default.staged.xml"

git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.staged.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all) -m ./manifest/default.staged.xml

.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

<!-- [en] -->
## Create a dev version

<!-- [fr] -->
## Créer une version dev

<!-- [common] -->
```bash
.venv.erplibre/bin/repo manifest -o ./manifest/default.dev.xml
```

<!-- [en] -->
Commit.

<!-- [fr] -->
Committez.

<!-- [common] -->
```bash
git commit -am "[#ticket] subject: short sentence"
```

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

<!-- [en] -->
### Freeze the versions

`repo manifest -r -o` pins every project to its commit. The file carries the
COMMIT in `revision` and the BRANCH in `upstream`, so ONE file serves both
modes: frozen follows the commit, dev follows the branch. The mode lives in
`.erplibre-state.json`, so a reconfiguration launched elsewhere reads the same
choice. It takes effect on the next reconfiguration.

<!-- [fr] -->
### Geler les versions

`repo manifest -r -o` épingle chaque projet à son commit. Le fichier porte le
COMMIT dans `revision` et la BRANCHE dans `upstream`, donc UN seul fichier
sert les deux modes : figé suit le commit, dev suit la branche. Le mode vit
dans `.erplibre-state.json`, pour qu'une reconfiguration lancée ailleurs lise
le même choix. Il prend effet à la reconfiguration suivante.

<!-- [common] -->
```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
```
