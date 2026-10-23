
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
./script/manifest/update_manifest_dev.sh
```

## dev local

[Guide pour configurer git localement](https://railsware.com/blog/taming-the-git-daemon-to-quickly-share-git-repository/).

Le script sert ce checkout par `git daemon`, fusionne les manifestes, et passe une branche à `repo init -b`, jamais
un commit nu : `repo init` refuse un commit sur un espace de travail neuf.

```bash
./script/manifest/update_manifest_local_dev.sh
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
./script/git/git_show_code_diff_repo_manifest.py
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

**Tirer** est la mise à jour d'un checkout déployé qui porte des commits ou des
modifications à lui : chaque dépôt intègre sa cible par les gestes de
`git pull` (avance rapide, rebase ou fusion), après une branche de sauvegarde,
et seulement ce que son essai à sec a montré. Entrée 3 de TODO › Execute › Git ›
Repo, et le module Odoo `erplibre_info`.

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

```bash
.venv.erplibre/bin/python script/git/repo_pull.py --dry-run --pretty
.venv.erplibre/bin/python script/git/repo_pull.py --dry-run --mode branche --strategy ff
.venv.erplibre/bin/python script/git/repo_pull.py --apply --confirm 18.0 --expect odoo18.0/addons/OCA_web=TARGET_SHA:HEAD_SHA
.venv.erplibre/bin/python script/git/repo_pull.py --list-backups
.venv.erplibre/bin/python script/git/repo_pull.py --restore-backup odoo18.0/addons/OCA_web=18.0_avant_pull_20260101T0800 --confirm 18.0
.venv.erplibre/bin/python script/git/repo_pull.py --delete-backup odoo18.0/addons/OCA_web=18.0_avant_pull_20260101T0800 --confirm 18.0
.venv.erplibre/bin/python script/git/repo_pull.py --install-deps --confirm 18.0 --pass 20260101T0800
```

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

L'amont vit dans le clone sous un remote qui porte le nom de
`fork-upstream-remote` — `OCA` ci-dessus, à `https://github.com/OCA/web.git` —
si bien que sa branche se lit `OCA/18.0`, dans tig, dans `git log` et dans le
reflog du rebase, et que sur un clone complet un simple `git fetch OCA` la rafraîchit à la main. La
passe à sec pose ce remote quand il manque, récupère la branche amont dans sa
branche de suivi `refs/remotes/OCA/18.0`, puis prédit la fusion en mémoire.
Rien d'autre ne s'écrit : aucune branche locale n'est créée ni déplacée, HEAD
et l'arbre de travail ne bougent pas.

```bash
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --diagnostic
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --upstream
PYTHONPATH=. ./.venv.erplibre/bin/python script/git/repo_upgrade.py --add-remotes
```

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

```bash
make repo_freeze UPSTREAM=1
git add manifest/
git commit -m "[UPD] manifest: freeze the forks rebased on upstream"
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

#### Geler la base amont

Le commit gelé d'un fork ne dit pas sur quel commit amont il repose. `--upstream`, ou `make repo_freeze UPSTREAM=1`,
l'écrit aussi à côté des attributs du fork, dans `fork-upstream-freeze-revision` : la base de fusion du commit gelé et
de la branche amont.

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
`manifest/` porte un gel pas encore committé — un `freeze-revision` ou un `fork-upstream-freeze-revision` qui diffère de
HEAD, la base seule suffisant —, et quels clones ont des modifications non commitées.

```bash
make repo_freeze_diff                                # HEAD -> clones
make repo_freeze_diff TO=worktree                    # what the last freeze wrote
make repo_freeze_diff ARGS=--previous                # previous freeze -> last freeze
make repo_freeze_diff FROM=v1.8.0 TO=HEAD ARGS="--log --group-by module"
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list   # commits that changed a freeze
```

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

```bash
.venv.erplibre/bin/python script/git/git_freeze_diff.py --list-refs
make repo_freeze_diff ARGS="--matrix v1.8.0,origin/master,clones"
make repo_freeze_diff ARGS="--graph 1"
```

Dans TODO › Git repo, l'entrée 15 propose les comparaisons courantes, le choix de deux révisions parmi les commits de
gel et les branches et tags d'ERPLibre, et la matrice. Sur le rapport : un numéro ouvre tig sur ce projet, `a` sur
chacun à la suite, `b N` le graphe avec les branches, `l` le journal, `d` et `s N` les diffstats, `g` le regroupement
suivant, `f` le rafraîchissement, `w` la commande qui ouvre un ancien commit dans un worktree git à côté du clone, sans
le déplacer.

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

```bash
.venv.erplibre/bin/python script/git/repo_state.py --pretty
.venv.erplibre/bin/python script/git/repo_state.py snapshot --dirty --repo odoo18.0/addons/OCA_web
.venv.erplibre/bin/python script/git/repo_state.py between odoo18.0/addons/OCA_web OLD_SHA NEW_SHA --max 50
.venv.erplibre/bin/python script/git/repo_state.py cross-version odoo18.0/addons/OCA_web --module web_responsive --full
```

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

```bash
.venv.erplibre/bin/python script/git/repo_apply.py --apply --confirm 18.0 --expect odoo18.0/addons/OCA_web
.venv.erplibre/bin/python script/git/repo_apply.py --apply --confirm 18.0 --expect odoo18.0/addons/OCA_web=UPSTREAM_SHA:HEAD_SHA
```