
# git-repo

Ce guide explique le fonctionnement de git-repo. Les scripts dans ERPLibre utilisent git-repo automatiquement.

[git-repo de Google](https://code.google.com/archive/p/git-repo) est utilisé pour gérer tous les dépôts git sous
licence [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.html).

## Configurer repo

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

## dev local

[Guide pour configurer git localement](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

```bash
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.dev.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all) -m ./manifest/default.dev.xml
```

# Créer un Manifest

Un [Manifest](https://gerrit.googlesource.com/git-repo/+/master/docs/manifest-format.md) est un fichier XML géré par
git-repo pour générer un dépôt.

## Créer une nouvelle version de prod

Cela fige tous les dépôts, du dev vers la prod.

Cela ajoutera le hash de révision git dans le manifest.

```bash
.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

Committez.

```bash
git commit -am "[#ticket] subject: short sentence"
```

### Mélanger prod et dev pour créer une version de staging

Lorsque dev contient une révision spécifique avec la révision par défaut, vous devez remplacer la révision par défaut par la révision prod et garder la version spécifique :

```bash
./script/git/git_merge_repo_manifest.py --input "./manifest/default.dev.xml;./default.xml" --output ./manifest/default.staged.xml
git commit -am "Updated manifest/default.staged.xml"

git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ./manifest/default.staged.xml
.venv.erplibre/bin/repo sync -c -j $(nproc --all) -m ./manifest/default.staged.xml

.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

## Créer une version dev

```bash
.venv.erplibre/bin/repo manifest -o ./manifest/default.dev.xml
```

Committez.

```bash
git commit -am "[#ticket] subject: short sentence"
```

## Commandes utiles

### Rechercher tous les dépôts avec un nom de branche spécifique

```bash
.venv.erplibre/bin/repo forall -pc "git branch -a|grep BRANCH"
```

### Rechercher les branches manquantes dans tous les dépôts

```bash
.venv.erplibre/bin/repo forall -pc 'git branch -a|(grep /BRANCH$||echo "no match")|grep "no match"'
```

### Rechercher les fichiers modifiés dans tous les dépôts

```bash
.venv.erplibre/bin/repo forall -pc "git status -s"
```

### Tout nettoyer

Avant de nettoyer, vérifiez les fichiers modifiés dans tous les dépôts.

```bash
.venv.erplibre/bin/repo forall -pc "git status -s"
```

Vérifiez les branches modifiées, et poussez les changements si nécessaire.

```bash
./script/git/git_show_code_diff_repo_manifest.py -m ./manifest/default.dev.xml
```

Peut-être que certaines versions divergent de votre manifest. Nettoyez simplement tout et relancez votre installation.

```bash
./script/git/clean_repo_manifest.sh
```

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

### D'où descend un fork

git-repo ne connaît que le remote qui sert à CLONER, et pour un fork c'est
celui du fork. Trois attributs portent ce qu'il ne sait pas exprimer :

```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         fork-upstream-remote="OCA" fork-upstream="18.0" />
```

`fork-upstream-remote` nomme le `<remote>` amont, dont le `fetch` donne l'URL.
`fork-upstream-name` ne paraît que sur un fork RENOMMÉ, où le nom du dépôt
amont diffère. `fork-upstream` nomme la branche amont ; son ABSENCE, alors que
le remote est déclaré, dit que l'amont ne porte rien pour cette version
d'Odoo — ce qui n'est pas la même chose qu'un amont inconnu.

La passe à sec n'écrit rien : elle amène l'amont dans `FETCH_HEAD` et prédit
la fusion en mémoire, sans déplacer de référence ni toucher l'arbre de travail.

### Geler les versions

`repo manifest -r -o` épingle chaque projet à son commit. Le fichier porte le
COMMIT dans `revision` et la BRANCHE dans `upstream`, donc UN seul fichier
sert les deux modes : figé suit le commit, dev suit la branche. Le mode vit
dans `.erplibre-state.json`, pour qu'une reconfiguration lancée ailleurs lise
le même choix. Il prend effet à la reconfiguration suivante.

```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
```