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
