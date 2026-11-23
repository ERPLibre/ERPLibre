<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# The ERPLibre Home GNOME extension in ERPLibre

The ERPLibre Home GNOME extension is a repository of its own,
[erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension),
which runs without ERPLibre; its `README.md` says how. This page covers
what ERPLibre adds: where the extension lives in a checkout, how it arrives
and follows new commits, what ERPLibre runs of it, and how to change it.
`CONTRACT.md`, at the root of the extension, states what each side relies
on.

## In a checkout

The extension is a Google Repo project at
`script/gnome-extension/erplibre_home/`, which ERPLibre's git ignores, and
is linked as
`~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`.
`manifest/git_manifest_erplibre_home_gnome_extension.xml` points at its
`main` branch: a checkout gets the latest extension at each update.
`script/gnome-extension/erplibre_home_contract` holds the contract version
ERPLibre is written against, and
`test/test_erplibre_home_extension_repo.py` fails when the checkout's MAJOR
differs. ERPLibre's tests read from the checkout only what its
`CONTRACT.md` states, with the values it gives
(`test/erplibre_home_extension.py`): the extension's code may change shape
as long as its own tests hold it to the contract.

Google Repo brings it two ways:

- **The manifest update.** `conf/git_manifest_erplibre_home.csv` names the
  manifest, in the group `erplibre_home`, apart from the Stream Deck's: the
  base installs without the deck. `git_merge_repo_manifest.py` adds it
  when `script/gnome-extension/erplibre_home` exists, or with
  `--with_erplibre_home`; an Odoo server never gets it. Every
  `script/manifest/update_manifest_*.sh` then syncs it to `main`.
- **The installer**, at both levels:

<!-- [fr] -->
# L'extension GNOME ERPLibre Home dans ERPLibre

L'extension GNOME ERPLibre Home forme un dépôt à part,
[erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension),
qui tourne sans ERPLibre ; son `README.md` dit comment. Cette page couvre
ce qu'ERPLibre ajoute : où vit l'extension dans un checkout, comment elle
arrive et suit les nouveaux commits, ce qu'ERPLibre en lance, et comment la
modifier. `CONTRACT.md`, à la racine de l'extension, dit ce que chaque côté
attend de l'autre.

## Dans un checkout

L'extension est un projet Google Repo dans
`script/gnome-extension/erplibre_home/`, que le git d'ERPLibre ignore, et
elle est liée en
`~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`.
`manifest/git_manifest_erplibre_home_gnome_extension.xml` pointe sur sa
branche `main` : un checkout reçoit la dernière extension à chaque mise à
jour. `script/gnome-extension/erplibre_home_contract` porte la version du
contrat pour laquelle ERPLibre est écrit, et
`test/test_erplibre_home_extension_repo.py` échoue quand la version
MAJEURE du checkout diffère. Les tests d'ERPLibre ne lisent du checkout que
ce qu'énonce son `CONTRACT.md`, avec les valeurs qu'il donne
(`test/erplibre_home_extension.py`) : le code de l'extension peut changer
de forme tant que ses propres tests le tiennent au contrat.

Google Repo l'amène de deux façons :

- **La mise à jour des manifestes.** `conf/git_manifest_erplibre_home.csv`
  nomme le manifeste, dans le groupe `erplibre_home`, à part de celui du
  Stream Deck : la base s'installe sans le deck.
  `git_merge_repo_manifest.py` l'ajoute quand
  `script/gnome-extension/erplibre_home` existe, ou avec
  `--with_erplibre_home` ; un serveur Odoo ne la reçoit jamais. Chaque
  `script/manifest/update_manifest_*.sh` la synchronise alors sur `main`.
- **L'installateur**, aux deux niveaux :

<!-- [end] -->
<!-- [common] -->
```
make erplibre_home_install
```

<!-- [end] -->
<!-- [en] -->
  It takes `repo` from `.venv.erplibre`, so
  `./script/install/install_erplibre.sh` comes first
  (`./script/install/install_git_repo.sh` adds `bin/repo` when only that
  is missing). A checkout without `.repo` gets one `repo init
  --standalone-manifest`, never a second one. The installer adds the
  extension's project to `.repo/local_manifests/erplibre_manifest.xml`,
  removing nothing from that file, then runs `repo sync` on that path
  alone, at each run, before it reads the GNOME versions `metadata.json`
  supports. A directory there that is not a repo checkout, a plain git
  clone or a copy, is moved aside whole to
  `script/gnome-extension/erplibre_home.avant-repo-<date>/`, named in the
  summary, and put back when the sync fails: the directory the session
  loads is never left missing or empty. On a repo checkout, a failed sync
  leaves the extension as it is, and the summary says "NOT updated". The
  installer stops before any sync when a pending manifest change would
  make repo remove a project: `make` comes first then. The base therefore
  needs `git`, `.venv.erplibre` and GitHub; `--extension-only`
  (`make erplibre_home_install_extension`) syncs too, and `--uninstall`
  removes neither the checkout, nor `.repo`, nor the local manifest.

## What ERPLibre runs of it

The installer links the checkout, runs `tools/migrate_legacy.py`, compiles
`schemas/` and each `po/<lang>.po`, and enables the extension through
`tools/enable_next_login.py`. The make targets
`erplibre_home_enable_extension`, `erplibre_home_dev_nested`,
`erplibre_home_e2e_nested`, `erplibre_home_compile_locale`,
`extension_i18n_compile`, `claude_install_hooks` and `test_gnome_extension`
run one of its files: without the checkout each stops on one line naming
`make erplibre_home_install_extension`, which syncs it without requiring
GNOME Shell. `make test_full_fast` runs the extension's suites when the
checkout is there and announces them skipped otherwise. The Stream Deck
program, the controller, the translator and the TODO menu talk to the
running extension over D-Bus and degrade when it does not answer. The
extension, in turn, finds the ERPLibre checkout from its own path and runs
the deck program and the controller from there.

## Older ERPLibre commits

ERPLibre commits older than the extension's move to its own repository
track its files at this same path, and so do the branches made from them.
Git treats the files it ignores as expendable: checking out such a branch
or commit writes its versions over the clone's files without asking, and
uncommitted changes to the extension are lost. Checking a newer commit out
again deletes those files, and the directory the session loads keeps only
`.git` and what the clone does not track. A bisect across that move does
the same.

Work on such a branch in its own worktree, `git worktree add <dir>
<branch>`, and merge the current branch into it there; once merged, it no
longer tracks the extension. When it happened, restore the clone's files
from its own history:

```
git -C script/gnome-extension/erplibre_home checkout -- .
```

The `post-checkout` hook of `script/git/hooks` (`git config core.hooksPath
script/git/hooks`) prints that command after a checkout from or to a
commit that tracks the extension. It restores nothing itself: it cannot
tell an overwrite from a wanted change.

## Changing the extension

A commit pushed to `main` of erplibre-home-gnome-extension reaches every
checkout at its next update. Run the extension's tests first, in its
directory:

<!-- [fr] -->
  Il prend `repo` dans `.venv.erplibre` :
  `./script/install/install_erplibre.sh` passe donc d'abord
  (`./script/install/install_git_repo.sh` ajoute `bin/repo` quand seul
  celui-ci manque). Un checkout sans `.repo` reçoit un seul `repo init
  --standalone-manifest`, jamais un second. L'installateur ajoute le
  projet de l'extension à `.repo/local_manifests/erplibre_manifest.xml`,
  sans rien retirer de ce fichier, puis lance `repo sync` sur ce seul
  chemin, à chaque exécution, avant de lire les versions de GNOME que
  `metadata.json` prend en charge. Un répertoire qui n'est pas un checkout
  repo, un clone git ou une copie, est mis de côté entier dans
  `script/gnome-extension/erplibre_home.avant-repo-<date>/`, nommé dans le
  bilan, et remis en place quand le sync échoue : le répertoire que charge
  la session n'est jamais laissé absent ni vide. Sur un checkout repo, un
  sync en échec laisse l'extension telle quelle, et le bilan dit « NOT
  updated ». L'installateur s'arrête avant tout sync quand un changement
  de manifeste en attente ferait supprimer un projet par repo : `make`
  passe alors d'abord. La base demande donc `git`, `.venv.erplibre` et
  GitHub ; `--extension-only` (`make erplibre_home_install_extension`)
  synchronise aussi, et `--uninstall` ne retire ni le checkout, ni
  `.repo`, ni le manifeste local.

## Ce qu'ERPLibre en lance

L'installateur lie le checkout, lance `tools/migrate_legacy.py`, compile
`schemas/` et chaque `po/<langue>.po`, et active l'extension par
`tools/enable_next_login.py`. Les cibles make
`erplibre_home_enable_extension`, `erplibre_home_dev_nested`,
`erplibre_home_e2e_nested`, `erplibre_home_compile_locale`,
`extension_i18n_compile`, `claude_install_hooks` et `test_gnome_extension`
lancent un de ses fichiers : sans le checkout, chacune s'arrête sur une
ligne qui nomme `make erplibre_home_install_extension`, qui la synchronise
sans demander GNOME Shell. `make test_full_fast` lance les suites de
l'extension quand le checkout est là, et les annonce sautées sinon. Le
programme du Stream Deck, le contrôleur, le traducteur et le menu TODO
parlent à l'extension en marche par D-Bus et se dégradent quand elle ne
répond pas. L'extension, elle, trouve le checkout d'ERPLibre par son propre
chemin et y lance le programme du deck et le contrôleur.

## Les commits d'ERPLibre plus anciens

Les commits d'ERPLibre antérieurs au passage de l'extension dans son propre
dépôt suivent ses fichiers à ce même chemin, comme les branches faites à
partir d'eux. git tient les fichiers qu'il ignore pour jetables : extraire
une telle branche ou un tel commit écrit ses versions par-dessus les
fichiers du clone sans rien demander, et les modifications non commitées de
l'extension sont perdues. Extraire de nouveau un commit plus récent
supprime ces fichiers, et le répertoire que charge la session ne garde que
`.git` et ce que le clone ne suit pas. Un bisect qui traverse ce passage
fait de même.

Travailler sur une telle branche dans son propre worktree, `git worktree
add <répertoire> <branche>`, et y fusionner la branche courante ; une fois
fusionnée, elle ne suit plus l'extension. Quand c'est arrivé, restaurer les
fichiers du clone depuis son propre historique :

```
git -C script/gnome-extension/erplibre_home checkout -- .
```

Le hook `post-checkout` de `script/git/hooks` (`git config core.hooksPath
script/git/hooks`) affiche cette commande après une extraction depuis ou
vers un commit qui suit l'extension. Il ne restaure rien lui-même : il ne
distingue pas un écrasement d'une modification voulue.

## Modifier l'extension

Un commit poussé sur `main` d'erplibre-home-gnome-extension atteint chaque
checkout à sa prochaine mise à jour. Lancer d'abord les tests de
l'extension, dans son répertoire :

<!-- [end] -->
<!-- [common] -->
```
node --test test/unit/*.test.js
python3 -m unittest discover -s test/python
git push TechnoLibre HEAD:main
```

<!-- [end] -->
<!-- [en] -->
`make test_gnome_extension`, from the ERPLibre root, runs the same suites
after a strict check of the schema. A change the other side can see bumps
the contract version in `CONTRACT.md`, as `CONTRACT.md` says. A MINOR bump
needs nothing else; record it in ERPLibre's `erplibre_home_contract` when
convenient. A MAJOR bump breaks the checkouts until ERPLibre follows: push
the ERPLibre side, with `erplibre_home_contract` set to the new version,
together with it.

`script/gnome-extension/erplibre_home/` is a Google Repo project of
erplibre-home-gnome-extension: its `.git` links into `.repo/`, and its
remote is named after the manifest's, `TechnoLibre`, over https. Work on a
branch that `repo start <branch> script/gnome-extension/erplibre_home`
starts, commit, and push it (`git push TechnoLibre <branch>`; for SSH, set
`url.git@github.com:.pushInsteadOf https://github.com/` in git's config).
Each installer run and each manifest update syncs it by repo's own rules:
a branch started by `repo start` keeps its commits, rebased on the new
`main`; a detached HEAD moves to `main`, leaving the commits made on it
(`git reflog` still finds them); a sync repo refuses, uncommitted changes
in the way or a rebase conflict, leaves the checkout as it is, and the
installer says "NOT updated". The running GNOME session keeps the code it
loaded: `make erplibre_home_reload` loads a new copy under Wayland without
logging out.

<!-- [fr] -->
`make test_gnome_extension`, depuis la racine d'ERPLibre, lance les mêmes
suites après une vérification stricte du schéma. Un changement que l'autre
côté voit fait monter la version du contrat dans `CONTRACT.md`, comme le
dit `CONTRACT.md`. Une version MINEURE ne demande rien d'autre ; la
reporter dans `erplibre_home_contract` d'ERPLibre quand c'est commode. Une
version MAJEURE fait casser les checkouts tant qu'ERPLibre ne suit pas :
pousser le côté ERPLibre, avec `erplibre_home_contract` à la nouvelle
version, en même temps.

`script/gnome-extension/erplibre_home/` est un projet Google Repo
d'erplibre-home-gnome-extension : son `.git` est un lien vers `.repo/`, et
son remote porte le nom de celui du manifeste, `TechnoLibre`, en https.
Travailler sur une branche que lance `repo start <branche>
script/gnome-extension/erplibre_home`, commiter, et la pousser
(`git push TechnoLibre <branche>` ; pour SSH, régler
`url.git@github.com:.pushInsteadOf https://github.com/` dans la config de
git). Chaque exécution de l'installateur et chaque mise à jour des
manifestes la synchronise selon les règles de repo : une branche lancée
par `repo start` garde ses commits, rebasés sur le nouveau `main` ; un HEAD
détaché passe sur `main` et laisse les commits faits dessus (`git reflog`
les retrouve) ; un sync que repo refuse, des modifications non commitées en
travers ou un conflit de rebase, laisse le checkout tel quel, et
l'installateur dit « NOT updated ». La session GNOME en cours garde le code
qu'elle a chargé : `make erplibre_home_reload` charge une nouvelle copie
sous Wayland sans fermer la session.

<!-- [end] -->
