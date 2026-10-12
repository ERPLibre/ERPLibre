
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

## Les fichiers sources et le manifeste local

Les manifestes à modifier sont les fichiers de `manifest/` : `git_manifest_odoo18.0.xml` pour les projets d'une version
d'Odoo, `git_manifest_extra_odoo18.0.xml` pour ses modules extra, `git_manifest_mobile_home.xml` pour l'application
mobile. git-repo n'en lit aucun. Chaque reconfiguration les fusionne dans `.repo/local_manifests/erplibre_manifest.xml`,
le seul manifeste que git-repo lit :

```bash
make repo_configure_all
```

Ce fichier est réécrit à chaque reconfiguration : ne jamais le modifier, une modification faite là se perd à la
suivante. Modifier le fichier source. Quand deux fichiers sources définissent le même projet, le dernier dans l'ordre
de fusion l'emporte.

Pour ne fusionner que des fichiers choisis, `--input` prend une liste séparée par `;`, dans l'ordre de fusion :

```bash
.venv.erplibre/bin/python script/git/git_merge_repo_manifest.py --input "./manifest/git_manifest_odoo18.0.xml;./manifest/git_manifest_odoo18.0_dev.xml" --output /tmp/erplibre_manifest.xml
```

## Créer une nouvelle version de prod

Cela fige les dépôts de la version d'Odoo active, du dev vers la prod : chaque projet reçoit le commit de son clone
dans son fichier source, à côté de sa branche. [Geler les versions](#geler-les-versions) dit ce qui est écrit et ce qui est écarté.

```bash
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

## Créer une version dev

Il n'y a rien à générer : les fichiers sources portent les branches, et une reconfiguration sans `FREEZE=1` les suit.

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

```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
```

### Geler les versions

Chaque `<project>` d'un fichier source garde sa BRANCHE dans `revision`. Le gel écrit le commit de son clone à côté,
dans `freeze-revision` :

```xml
<project name="web.git" path="odoo18.0/addons/OCA_web"
         remote="ERPLibre_origin_OCA" revision="18.0_dev"
         freeze-revision="0123456789abcdef0123456789abcdef01234567" />
```

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

```bash
.venv.erplibre/bin/python script/git/git_freeze_manifest.py --dry-run
make repo_freeze
git add manifest/
git commit -m "[UPD] manifest: freeze the versions of v#.#.#"
```

Ne sont pas gelés, et sont listés :

- un projet qui n'est pas cloné, laissé tel quel ;
- un projet qu'un autre fichier fusionné définit aussi : la fusion garde l'une des définitions selon l'ordre des
  fichiers, et le gel n'en écrit qu'une ;
- un clone dont aucune branche distante ne contient le commit, puisqu'une installation neuve ne pourrait pas aller le
  chercher : le pousser d'abord.

Un clone aux modifications non commitées est gelé sur son commit, avec un avertissement : ses modifications ne font pas
partie du gel. La commande sort avec 1 quand rien n'a été gelé.

#### Installer ou reconfigurer sur les commits

```bash
make repo_configure_all FREEZE=1
# same, from the script
./script/manifest/update_manifest_local_dev.sh --freeze
```

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

```bash
# follow the branches, the freeze stays written
make repo_configure_all
# remove the freeze from every source file, then commit
make repo_unfreeze
```

#### Comparer deux gels

Un côté de la comparaison est une révision d'ERPLibre (`HEAD`, un tag, un commit), `worktree` pour les fichiers de
`manifest/` sur le disque, ou `clones` pour le commit où se trouve chaque clone. Sans argument, le gel committé est
comparé aux clones : ce qui a bougé depuis le dernier gel. Le rapport dit aussi sur quel commit se trouve ERPLibre, si
`manifest/` porte un gel pas encore committé, et quels clones ont des modifications non commitées.

```bash
make repo_freeze_diff                                # HEAD -> clones
make repo_freeze_diff TO=worktree                    # what the last freeze wrote
make repo_freeze_diff ARGS=--previous                # previous freeze -> last freeze
make repo_freeze_diff FROM=v1.8.0 TO=HEAD ARGS="--log --group-by module"
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list   # commits that changed a freeze
```

Un tableau compact liste chaque projet changé : ancien et nouveau commit, commits gagnés et perdus (`rollback` quand
le nouveau commit ne fait que reculer), fichiers et lignes changés. En dessous, le diffstat de chaque projet s'affiche
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

Un côté peut être n'importe quelle branche ou tag d'ERPLibre : `--list-refs` liste ceux qui portent un gel. `--matrix`
montre, projet par projet, le commit gelé dans plusieurs côtés à la fois, par défaut ces branches et tags, `worktree`
et `clones` ; seulement les projets où ils diffèrent, `=` tenant lieu du commit de la colonne de gauche :

```bash
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list-refs
make repo_freeze_diff ARGS="--matrix v1.8.0,origin/master,clones"
make repo_freeze_diff ARGS="--graph 1"
```

Dans TODO › Git repo, l'entrée 12 propose les comparaisons courantes, le choix de deux révisions parmi les commits de
gel et les branches et tags d'ERPLibre, et la matrice. Sur le rapport : un numéro ouvre tig sur ce projet, `a` sur
chacun à la suite, `b N` le graphe avec les branches, `l` le journal, `d` et `s N` les diffstats, `g` le regroupement
suivant, `f` le rafraîchissement, `w` la commande qui ouvre un ancien commit dans un worktree git à côté du clone, sans
le déplacer.