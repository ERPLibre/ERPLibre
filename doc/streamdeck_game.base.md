<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Stream Deck games in ERPLibre

The Stream Deck games and their gallery are a repository of their own,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), which
runs without ERPLibre; its `README.md` says how. This page covers what
ERPLibre adds: where the games live in a checkout, how they arrive and
follow new commits, how ERPLibre runs them, and how to change them.
`CONTRACT.md`, at the root of the games, states what each side relies on.

## In a checkout

The games are a Google Repo project at `script/stream_deck/games/`, which
ERPLibre's git ignores. `manifest/git_manifest_streamdeck_game.xml` points
at their `main` branch: a checkout gets the latest games at each update,
and a frozen install (`FREEZE=1`) the commit of its `freeze-revision`.
`script/stream_deck/games_contract` holds the contract version ERPLibre is
written against, and `test/test_streamdeck_games_repo.py` fails when the
checkout's MAJOR differs.

Google Repo brings them two ways:

- **The manifest update.** `conf/git_manifest_streamdeck.csv` names the
  manifest, in the group `streamdeck`, next to the deck program. Like the
  mobile's list, `git_merge_repo_manifest.py` adds it when
  `script/stream_deck/games` exists, or with `--with_streamdeck`; an Odoo
  server never gets the games. Every `script/manifest/update_manifest_*.sh`
  then syncs them to `main`.
- **The installer**, at the Stream Deck level:

<!-- [fr] -->
# Les jeux Stream Deck dans ERPLibre

Les jeux Stream Deck et leur galerie forment un dépôt à part,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), qui
tourne sans ERPLibre ; son `README.md` dit comment. Cette page couvre ce
qu'ERPLibre ajoute : où vivent les jeux dans un checkout, comment ils
arrivent et suivent les nouveaux commits, comment ERPLibre les lance, et
comment les modifier. `CONTRACT.md`, à la racine des jeux, dit ce que chaque
côté attend de l'autre.

## Dans un checkout

Les jeux sont un projet Google Repo dans `script/stream_deck/games/`, que
le git d'ERPLibre ignore. `manifest/git_manifest_streamdeck_game.xml`
pointe sur leur branche `main` : un checkout reçoit les derniers jeux à
chaque mise à jour, et une installation gelée (`FREEZE=1`) le commit de son
`freeze-revision`. `script/stream_deck/games_contract` porte la version du
contrat pour laquelle ERPLibre est écrit, et
`test/test_streamdeck_games_repo.py` échoue quand la version MAJEURE du
checkout diffère.

Google Repo les amène de deux façons :

- **La mise à jour des manifestes.** `conf/git_manifest_streamdeck.csv`
  nomme le manifeste, dans le groupe `streamdeck`, à côté du programme du
  deck. Comme la liste du mobile, `git_merge_repo_manifest.py` l'ajoute
  quand `script/stream_deck/games` existe, ou avec `--with_streamdeck` ; un
  serveur Odoo ne reçoit jamais les jeux. Chaque
  `script/manifest/update_manifest_*.sh` les synchronise alors sur `main`.
- **L'installateur**, au niveau Stream Deck :

<!-- [end] -->
<!-- [common] -->
```
make erplibre_home_streamdeck_install
```

<!-- [end] -->
<!-- [en] -->
  As for the deck program (see
  [the deck program in ERPLibre](erplibre_streamdeck_deck.md)), it adds
  the games' project to `.repo/local_manifests/erplibre_manifest.xml`,
  removing nothing from that file, and runs `repo sync` on that path alone
  at each run, then installs `script/stream_deck/deck/requirements.txt`
  and the games' `requirements.txt` in `.venv.streamdeck`. A directory
  there that is not a repo checkout, a plain git clone, a copy or the
  `save/` an older layout left, is moved aside whole to
  `script/stream_deck/games.avant-repo-<date>/`, named in the summary, and
  put back when the sync fails. On a repo checkout, a failed sync leaves
  the games as they are, and the summary says "NOT updated". `--uninstall`
  never removes the games.

## Running them

TODO › ERPLibre Home › Games, the gallery (`make streamdeck_gallery`, or
the GNOME extension's Games submenu, which goes through it) and
`make streamdeck_<id>` run a game under `.venv.streamdeck` through
`script/install/erplibre_home_streamdeck_handover.sh`: it holds the deck
lock, stops the deck service for the game and starts it again after, and
refuses (exit 4) when the `GAMES` setting is off.
`make streamdeck_<id>` is one pattern rule in
`conf/make.streamdeck.Makefile` that runs `game_<id>.py` of the clone, and
`make streamdeck_games` lists the ids: ERPLibre names no game, so a game
added to the repository needs no ERPLibre change. An id with no file
stops with exit 2. Without the games, each entry prints one line naming
`make erplibre_home_streamdeck_install`, and the hand-over exits 5 before
stopping anything; it does the same without the deck program, or on a deck
checkout whose contract is below `script/stream_deck/deck_contract`, since
its `deck_lock.py` would run no game. The deck program, the controller and the
service do not need the games.

The gallery listens on 127.0.0.1:8042 only. Its routes that act (launch,
stop, delete saves) take only a request carrying the header
`X-Stream-Deck-Gallery: 1`, which its page and the GNOME extension send:
another site's page, a link or a document renderer cannot launch a game
or delete saves through it.

## Saves

Games keep their saves in `$XDG_DATA_HOME/erplibre-home/streamdeck/save/`
(`~/.local/share` by default), outside both repositories: no sync or
`git clean` reaches them. Saves left in `script/stream_deck/games/save/`
by older versions move there on the next run; those of a `games/` the
installer set aside stay in its `save/`, to copy there by hand.

## Changing the games

A commit pushed to `main` of streamdeck_game reaches every checkout at its
next update. Run the games' tests first:

<!-- [fr] -->
  Comme pour le programme du deck (voir
  [le programme du deck dans ERPLibre](erplibre_streamdeck_deck.fr.md)), il
  ajoute le projet des jeux à `.repo/local_manifests/erplibre_manifest.xml`,
  sans rien retirer de ce fichier, et lance `repo sync` sur ce seul chemin
  à chaque exécution, puis installe `script/stream_deck/deck/requirements.txt`
  et le `requirements.txt` des jeux dans `.venv.streamdeck`. Un répertoire
  qui n'est pas un checkout repo, un clone git, une copie ou le `save/`
  qu'une disposition antérieure a laissé, est mis de côté entier dans
  `script/stream_deck/games.avant-repo-<date>/`, nommé dans le bilan, et
  remis en place quand le sync échoue. Sur un checkout repo, un sync en
  échec laisse les jeux tels quels, et le bilan dit « NOT updated ».
  `--uninstall` ne retire jamais les jeux.

## Les lancer

TODO › ERPLibre Home › Jeux, la galerie (`make streamdeck_gallery`, ou le
sous-menu Jeux de l'extension GNOME, qui passe par elle) et
`make streamdeck_<id>` lancent un jeu sous `.venv.streamdeck` par
`script/install/erplibre_home_streamdeck_handover.sh` : il tient le verrou
du deck, arrête le service du deck le temps du jeu et le relance après, et
refuse (code 4) quand le réglage `GAMES` est à off.
`make streamdeck_<id>` est une seule règle à motif de
`conf/make.streamdeck.Makefile`, qui lance le `game_<id>.py` du clone, et
`make streamdeck_games` en liste les id : ERPLibre ne nomme aucun jeu, si
bien qu'un jeu ajouté au dépôt ne demande aucun changement à ERPLibre. Un
id sans fichier s'arrête en code 2. Sans les jeux, chaque entrée affiche une
ligne qui nomme `make erplibre_home_streamdeck_install`, et la passation
sort en 5 avant d'arrêter quoi que ce soit ; elle fait de même sans le
programme du deck, ou sur un checkout du deck dont le contrat est sous
`script/stream_deck/deck_contract`, son `deck_lock.py` ne lançant alors
aucun jeu. Le programme du deck, le contrôleur et le service n'ont pas
besoin des jeux.

La galerie n'écoute que sur 127.0.0.1:8042. Ses routes qui agissent
(lancer, arrêter, effacer des sauvegardes) n'acceptent qu'une requête
portant l'en-tête `X-Stream-Deck-Gallery: 1`, que sa page et l'extension
GNOME envoient : la page d'un autre site, un lien ou un moteur de rendu de
documents ne peut ni lancer un jeu ni effacer de sauvegarde par elle.

## Sauvegardes

Les jeux gardent leurs sauvegardes dans
`$XDG_DATA_HOME/erplibre-home/streamdeck/save/` (`~/.local/share` par
défaut), hors des deux dépôts : aucune synchronisation, aucun `git clean`
ne les atteint. Celles que d'anciennes versions ont laissées dans
`script/stream_deck/games/save/` y passent à la prochaine exécution ; celles
d'un `games/` que l'installateur a mis de côté restent dans son `save/`, à y
copier à la main.

## Modifier les jeux

Un commit poussé sur `main` de streamdeck_game atteint chaque checkout à sa
prochaine mise à jour. Lancer d'abord les tests des jeux :

<!-- [end] -->
<!-- [common] -->
```
python3 -m unittest discover -s tests
git push origin main
```

<!-- [end] -->
<!-- [en] -->
A change the other side can see bumps the contract version in `CONTRACT.md`
and `games_cli.CONTRACT_VERSION`, as `CONTRACT.md` says. A MINOR bump needs
nothing else; record it in ERPLibre's `games_contract` when convenient. A
MAJOR bump breaks the checkouts until ERPLibre follows: push the ERPLibre
side, with `games_contract` set to the new version, together with it. A new
game needs nothing on the ERPLibre side: `make streamdeck_<id>`, the TODO
menu and the gallery find every `game_<id>.py` of the clone.

`script/stream_deck/games/` is a Google Repo project of streamdeck_game:
its `.git` links into `.repo/`, and its remote is named after the
manifest's, `TechnoLibre`, over https. Work on a branch that
`repo start <branch> script/stream_deck/games` starts, commit, and push it
(`git push TechnoLibre <branch>`). Each installer run and each manifest
update syncs it by repo's own rules, as for the deck program: a branch
started by `repo start` keeps its commits, rebased on the new `main`; a
detached HEAD moves to `main`; a sync repo refuses leaves the checkout as
it is, and the installer says "NOT updated".

<!-- [fr] -->
Un changement que l'autre côté voit fait monter la version du contrat dans
`CONTRACT.md` et `games_cli.CONTRACT_VERSION`, comme le dit `CONTRACT.md`.
Une version MINEURE ne demande rien d'autre ; la reporter dans
`games_contract` d'ERPLibre quand c'est commode. Une version MAJEURE fait
casser les checkouts tant qu'ERPLibre ne suit pas : pousser le côté
ERPLibre, avec `games_contract` à la nouvelle version, en même temps. Un
nouveau jeu ne demande rien côté ERPLibre : `make streamdeck_<id>`, le menu
TODO et la galerie trouvent chaque `game_<id>.py` du clone.

`script/stream_deck/games/` est un projet Google Repo de streamdeck_game :
son `.git` est un lien vers `.repo/`, et son remote porte le nom de celui
du manifeste, `TechnoLibre`, en https. Travailler sur une branche que lance
`repo start <branche> script/stream_deck/games`, commiter, et la pousser
(`git push TechnoLibre <branche>`). Chaque exécution de l'installateur et
chaque mise à jour des manifestes le synchronise selon les règles de repo,
comme pour le programme du deck : une branche lancée par `repo start` garde
ses commits, rebasés sur le nouveau `main` ; un HEAD détaché passe sur
`main` ; un sync que repo refuse laisse le checkout tel quel, et
l'installateur dit « NOT updated ».

<!-- [end] -->
