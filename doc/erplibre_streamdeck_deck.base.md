<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# The Stream Deck deck program in ERPLibre

The deck program of ERPLibre Home is a repository of its own,
[erplibre_streamdeck](https://github.com/TechnoLibre/erplibre_streamdeck):
the `erplibre_streamdeck` package and its plugins, the classic controller
`erplibre_controller.py`, the deck lock `deck_lock.py`, the speech-to-text
translator, `requirements.txt` and its tests. It runs without ERPLibre; its
`README.md` says how. This page covers what ERPLibre adds: where the deck
program lives in a checkout, how it arrives and follows new commits, what
ERPLibre runs of it, and how to change it. `CONTRACT.md`, at the root of
the deck repository, states what each side relies on.

## In a checkout

The deck program is a Google Repo project at `script/stream_deck/deck/`,
which ERPLibre's git ignores.
`manifest/git_manifest_erplibre_streamdeck_deck.xml` points at its `main`
branch: a checkout gets the latest deck program at each update.
`script/stream_deck/deck_contract` holds the contract version ERPLibre is
written against, and `test/test_streamdeck_deck_repo.py` fails when the
MAJOR of the checkout's `CONTRACT.md` differs or its MINOR is lower: such
a checkout lacks something ERPLibre uses. ERPLibre's tests that read the
checkout go through `test/streamdeck_deck.py`, and are skipped, naming the
install command, when it is missing.

Google Repo brings it two ways:

- **The manifest update.** `conf/git_manifest_streamdeck.csv` names the
  manifest, in the group `streamdeck`, apart from the extension's
  `erplibre_home`: the base of ERPLibre Home installs without the deck.
  `git_merge_repo_manifest.py` adds it when `script/stream_deck/deck`
  exists, or with `--with_streamdeck`; an Odoo server never gets it. Every
  `script/manifest/update_manifest_*.sh` then syncs it to `main`.
- **The installer**, at the Stream Deck level:

<!-- [fr] -->
# Le programme du deck Stream Deck dans ERPLibre

Le programme du deck d'ERPLibre Home forme un dépôt à part,
[erplibre_streamdeck](https://github.com/TechnoLibre/erplibre_streamdeck) :
le paquet `erplibre_streamdeck` et ses plugins, le contrôleur classique
`erplibre_controller.py`, le verrou du deck `deck_lock.py`, le traducteur
parole-texte, `requirements.txt` et ses tests. Il tourne sans ERPLibre ;
son `README.md` dit comment. Cette page couvre ce qu'ERPLibre ajoute : où
vit le programme du deck dans un checkout, comment il arrive et suit les
nouveaux commits, ce qu'ERPLibre en lance, et comment le modifier.
`CONTRACT.md`, à la racine du dépôt du deck, dit ce que chaque côté attend
de l'autre.

## Dans un checkout

Le programme du deck est un projet Google Repo dans
`script/stream_deck/deck/`, que le git d'ERPLibre ignore.
`manifest/git_manifest_erplibre_streamdeck_deck.xml` pointe sur sa branche
`main` : un checkout reçoit le dernier programme du deck à chaque mise à
jour. `script/stream_deck/deck_contract` porte la version du contrat pour
laquelle ERPLibre est écrit, et `test/test_streamdeck_deck_repo.py` échoue
quand la version MAJEURE du `CONTRACT.md` du checkout diffère ou que sa
MINEURE est plus basse : un tel checkout n'a pas tout ce dont ERPLibre se
sert. Les tests d'ERPLibre qui lisent le checkout passent par
`test/streamdeck_deck.py`, et sont sautés, en nommant la commande
d'installation, quand il manque.

Google Repo l'amène de deux façons :

- **La mise à jour des manifestes.** `conf/git_manifest_streamdeck.csv`
  nomme le manifeste, dans le groupe `streamdeck`, à part du groupe
  `erplibre_home` de l'extension : la base d'ERPLibre Home s'installe sans
  le deck. `git_merge_repo_manifest.py` l'ajoute quand
  `script/stream_deck/deck` existe, ou avec `--with_streamdeck` ; un
  serveur Odoo ne le reçoit jamais. Chaque
  `script/manifest/update_manifest_*.sh` le synchronise alors sur `main`.
- **L'installateur**, au niveau Stream Deck :

<!-- [end] -->
<!-- [common] -->
```
make erplibre_home_streamdeck_install
```

<!-- [end] -->
<!-- [en] -->
  As for the extension (see
  [the extension in ERPLibre](erplibre_home_gnome_extension.md)), it
  takes `repo` from `.venv.erplibre`, so
  `./script/install/install_erplibre.sh` comes first, adds the deck's
  project to `.repo/local_manifests/erplibre_manifest.xml`, removing
  nothing from that file, and runs `repo sync` on that path alone at each
  run, then installs its `requirements.txt` in `.venv.streamdeck`. A base
  install run afterwards keeps the deck in the local manifest. A directory
  there that is not a repo checkout, a plain git clone or a copy, is moved
  aside whole to `script/stream_deck/deck.avant-repo-<date>/`, named in
  the summary, and put back when the sync fails: the directory the service
  runs from is never left missing or empty. On a repo checkout, a failed
  sync leaves the deck program as it is, and the summary says "NOT
  updated". `--uninstall` removes neither the checkout, nor `.repo`, nor
  the local manifest.

## What ERPLibre runs of it

`DECK_PROGRAM` of `streamdeck.conf` picks what the service
`erplibre-home-streamdeck.service` runs, through
`script/install/erplibre_home_deck.sh`: `tiler`, the package
`script/stream_deck/deck/erplibre_streamdeck`, or `controller`,
`script/stream_deck/deck/erplibre_controller.py`, both under
`.venv.streamdeck`. Without the checkout, the service's start check and the
entry point stop on one line naming `make erplibre_home_streamdeck_install`.
The make targets `streamdeck_erplibre`, `streamdeck`, `streamdeck_tiler`,
`streamdeck_translator_*`, `streamdeck_tiler_unittest` (the deck's whole
suite) and `streamdeck_translator_unittest` run a file of the checkout and
stop the same way. TODO › ERPLibre Home reads the deck lock through the
checkout's `deck_lock.py`, lists the plugins of
`erplibre_streamdeck/plugins/`, and says "Deck program: not installed"
without it. The GNOME extension looks for the deck program in
`script/stream_deck/deck/` first (its contract 1.5).

## Changing the deck program

A commit pushed to `main` of erplibre_streamdeck reaches every checkout at
its next update. Run the deck's tests first, in its directory:

<!-- [fr] -->
  Comme pour l'extension (voir
  [l'extension dans ERPLibre](erplibre_home_gnome_extension.fr.md)), il
  prend `repo` dans `.venv.erplibre` : `./script/install/install_erplibre.sh`
  passe donc d'abord. Il ajoute le projet du deck à
  `.repo/local_manifests/erplibre_manifest.xml`, sans rien retirer de ce
  fichier, et lance `repo sync` sur ce seul chemin à chaque exécution,
  puis installe son `requirements.txt` dans `.venv.streamdeck`. Une
  installation de la base lancée ensuite garde le deck dans le manifeste
  local. Un répertoire qui n'est pas un checkout repo, un clone git ou une
  copie, est mis de côté entier dans
  `script/stream_deck/deck.avant-repo-<date>/`, nommé dans le bilan, et
  remis en place quand le sync échoue : le répertoire d'où le service
  lance le programme n'est jamais laissé absent ni vide. Sur un checkout
  repo, un sync en échec laisse le programme du deck tel quel, et le bilan
  dit « NOT updated ». `--uninstall` ne retire ni le checkout, ni `.repo`,
  ni le manifeste local.

## Ce qu'ERPLibre en lance

`DECK_PROGRAM` de `streamdeck.conf` choisit ce que lance le service
`erplibre-home-streamdeck.service`, par
`script/install/erplibre_home_deck.sh` : `tiler`, le paquet
`script/stream_deck/deck/erplibre_streamdeck`, ou `controller`,
`script/stream_deck/deck/erplibre_controller.py`, tous deux sous
`.venv.streamdeck`. Sans le checkout, la vérification de démarrage du
service et le point d'entrée s'arrêtent sur une ligne qui nomme
`make erplibre_home_streamdeck_install`. Les cibles make
`streamdeck_erplibre`, `streamdeck`, `streamdeck_tiler`,
`streamdeck_translator_*`, `streamdeck_tiler_unittest` (toute la suite du
deck) et `streamdeck_translator_unittest` lancent un fichier du checkout et
s'arrêtent de même. TODO › ERPLibre Home lit le verrou du deck par le
`deck_lock.py` du checkout, liste les plugins de
`erplibre_streamdeck/plugins/`, et dit « Programme du deck : pas installé »
sans lui. L'extension GNOME cherche le programme du deck d'abord dans
`script/stream_deck/deck/` (son contrat 1.5).

## Modifier le programme du deck

Un commit poussé sur `main` d'erplibre_streamdeck atteint chaque checkout à
sa prochaine mise à jour. Lancer d'abord les tests du deck, dans son
répertoire :

<!-- [end] -->
<!-- [common] -->
```
cd script/stream_deck/deck
../../../.venv.streamdeck/bin/python -m unittest discover -s tests
git push TechnoLibre HEAD:main
```

<!-- [end] -->
<!-- [en] -->
`make streamdeck_tiler_unittest`, from the ERPLibre root, runs the same
suite. A change the other side can see bumps the contract version in
`CONTRACT.md`, as `CONTRACT.md` says. A MINOR bump needs nothing else;
record it in ERPLibre's `deck_contract` once ERPLibre relies on what it
adds, since a clone below it then fails ERPLibre's tests. A MAJOR bump
breaks the checkouts until ERPLibre follows: push the ERPLibre side, with
`deck_contract` set to the new version, together with it.

`script/stream_deck/deck/` is a Google Repo project of erplibre_streamdeck:
its `.git` links into `.repo/`, and its remote is named after the
manifest's, `TechnoLibre`, over https. Work on a branch that
`repo start <branch> script/stream_deck/deck` starts, commit, and push it
(`git push TechnoLibre <branch>`; for SSH, set
`url.git@github.com:.pushInsteadOf https://github.com/` in git's config).
Each installer run and each manifest update syncs it by repo's own rules:
a branch started by `repo start` keeps its commits, rebased on the new
`main`; a detached HEAD moves to `main`, leaving the commits made on it
(`git reflog` still finds them); a sync repo refuses, uncommitted changes
in the way or a rebase conflict, leaves the checkout as it is, and the
installer says "NOT updated". A running deck program keeps the code it
loaded: restart the service
(`systemctl --user restart erplibre-home-streamdeck.service`).

<!-- [fr] -->
`make streamdeck_tiler_unittest`, depuis la racine d'ERPLibre, lance la
même suite. Un changement que l'autre côté voit fait monter la version du
contrat dans `CONTRACT.md`, comme le dit `CONTRACT.md`. Une version MINEURE
ne demande rien d'autre ; la reporter dans `deck_contract` d'ERPLibre dès
qu'ERPLibre se sert de ce qu'elle ajoute, puisqu'un clone en dessous fait
alors échouer les tests d'ERPLibre. Une version MAJEURE fait casser les
checkouts tant qu'ERPLibre ne suit pas : pousser le côté ERPLibre, avec
`deck_contract` à la nouvelle version, en même temps.

`script/stream_deck/deck/` est un projet Google Repo d'erplibre_streamdeck :
son `.git` est un lien vers `.repo/`, et son remote porte le nom de celui
du manifeste, `TechnoLibre`, en https. Travailler sur une branche que lance
`repo start <branche> script/stream_deck/deck`, commiter, et la pousser
(`git push TechnoLibre <branche>` ; pour SSH, régler
`url.git@github.com:.pushInsteadOf https://github.com/` dans la config de
git). Chaque exécution de l'installateur et chaque mise à jour des
manifestes le synchronise selon les règles de repo : une branche lancée par
`repo start` garde ses commits, rebasés sur le nouveau `main` ; un HEAD
détaché passe sur `main` et laisse les commits faits dessus (`git reflog`
les retrouve) ; un sync que repo refuse, des modifications non commitées en
travers ou un conflit de rebase, laisse le checkout tel quel, et
l'installateur dit « NOT updated ». Un programme du deck en marche garde le
code qu'il a chargé : relancer le service
(`systemctl --user restart erplibre-home-streamdeck.service`).

<!-- [end] -->
