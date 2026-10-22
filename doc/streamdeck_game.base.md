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

The games are cloned at `script/stream_deck/games/`, which ERPLibre's git
ignores. `manifest/git_manifest_streamdeck_game.xml` points at their `main`
branch: a checkout gets the latest games at each update.
`script/stream_deck/games_contract` holds the contract version ERPLibre is
written against, and `test/test_streamdeck_games_repo.py` fails when the
clone's MAJOR differs.

They arrive two ways:

- **Google Repo.** The three lists `conf/git_manifest*.csv` name the
  manifest, so every `script/manifest/update_manifest_*.sh` syncs the games
  to `main`. A plain clone made by the installer is refused by
  `repo sync`: `script/manifest/streamdeck_games_to_repo.sh`, run between
  `repo init` and `repo sync`, moves it to
  `script/stream_deck/games.plain-clone-<date>/` when it holds no local
  work, and stops the update, naming that work, otherwise.
- **The installer**, for a checkout without Google Repo:

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

Les jeux sont clonés dans `script/stream_deck/games/`, que le git
d'ERPLibre ignore. `manifest/git_manifest_streamdeck_game.xml` pointe sur
leur branche `main` : un checkout reçoit les derniers jeux à chaque mise à
jour. `script/stream_deck/games_contract` porte la version du contrat pour
laquelle ERPLibre est écrit, et `test/test_streamdeck_games_repo.py` échoue
quand la version MAJEURE du clone diffère.

Ils arrivent de deux façons :

- **Google Repo.** Les trois listes `conf/git_manifest*.csv` nomment le
  manifeste : chaque `script/manifest/update_manifest_*.sh` synchronise les
  jeux sur `main`. `repo sync` refuse un clone ordinaire fait par
  l'installateur : `script/manifest/streamdeck_games_to_repo.sh`, lancé
  entre `repo init` et `repo sync`, le déplace vers
  `script/stream_deck/games.plain-clone-<date>/` quand il ne porte aucun
  travail local, et arrête sinon la mise à jour en nommant ce travail.
- **L'installateur**, pour un checkout sans Google Repo :

<!-- [end] -->
<!-- [common] -->
```
make erplibre_home_streamdeck_install
```

<!-- [end] -->
<!-- [en] -->
  It clones the games when `games/` is missing or holds only `save/` and
  `__pycache__/`, detached on the last commit of `main`. At each later run
  it fetches `main` and moves a clone it made to its new last commit; a
  branch or local work stays, and the summary says so, as it says a fetch
  that fails. Then it installs `script/stream_deck/requirements.txt` and
  the games' `requirements.txt` in `.venv.streamdeck`. `--uninstall` never
  removes the games.

## Running them

TODO › Stream Deck › Games, and the gallery (`make streamdeck_gallery`, or
the GNOME extension's Games submenu, which goes through it) run a game
under `.venv.streamdeck` through `script/install/erplibre_home_handover.sh`:
it holds the deck lock, stops the deck service for the game and starts it
again after, and refuses (exit 4) when the `GAMES` setting is off.
`make streamdeck_<id>`, one target per game in
`conf/make.streamdeck.Makefile`, runs the game directly under
`.venv.streamdeck`, without the hand-over: it refuses when `GAMES` is off,
but neither takes the deck lock nor stops the service, so stop the service
first. Without the games, each entry prints one line naming
`make erplibre_home_streamdeck_install`, and the hand-over exits 5 before
stopping anything; the deck program, the controller and the service do not
need the games.

The gallery listens on 127.0.0.1:8042 only. Its routes that act (launch,
stop, delete saves) take only a request carrying the header
`X-Stream-Deck-Gallery: 1`, which its page and the GNOME extension send:
another site's page, a link or a document renderer cannot launch a game
or delete saves through it.

## Saves

Games keep their saves in `$XDG_DATA_HOME/erplibre-home/streamdeck/save/`
(`~/.local/share` by default), outside both repositories: no clone, sync
or `git clean` reaches them. Saves left in `script/stream_deck/games/save/`
by older versions move there on the next run.

## Changing the games

A commit pushed to `main` of streamdeck_game reaches every checkout at its
next update. Run the games' tests first:

<!-- [fr] -->
  Il clone les jeux quand `games/` manque ou ne garde que `save/` et
  `__pycache__/`, en HEAD détaché sur le dernier commit de `main`. À chaque
  exécution suivante, il va chercher `main` et amène un clone qu'il a fait
  à son nouveau dernier commit ; une branche ou du travail local reste, et
  le bilan le dit, comme il dit un fetch qui échoue. Il installe ensuite
  `script/stream_deck/requirements.txt` et le `requirements.txt` des jeux
  dans `.venv.streamdeck`. `--uninstall` ne retire jamais les jeux.

## Les lancer

TODO › Stream Deck › Jeux et la galerie (`make streamdeck_gallery`, ou le
sous-menu Jeux de l'extension GNOME, qui passe par elle) lancent un jeu
sous `.venv.streamdeck` par `script/install/erplibre_home_handover.sh` : il
tient le verrou du deck, arrête le service du deck le temps du jeu et le
relance après, et refuse (code 4) quand le réglage `GAMES` est à off.
`make streamdeck_<id>`, une cible par jeu dans
`conf/make.streamdeck.Makefile`, lance le jeu directement sous
`.venv.streamdeck`, sans la passation : elle refuse quand `GAMES` est à
off, mais ne prend pas le verrou du deck et n'arrête pas le service ;
arrête donc le service d'abord. Sans les jeux, chaque entrée affiche une
ligne qui nomme `make erplibre_home_streamdeck_install`, et la passation
sort en 5 avant d'arrêter quoi que ce soit ; le programme du deck, le
contrôleur et le service n'ont pas besoin des jeux.

La galerie n'écoute que sur 127.0.0.1:8042. Ses routes qui agissent
(lancer, arrêter, effacer des sauvegardes) n'acceptent qu'une requête
portant l'en-tête `X-Stream-Deck-Gallery: 1`, que sa page et l'extension
GNOME envoient : la page d'un autre site, un lien ou un moteur de rendu de
documents ne peut ni lancer un jeu ni effacer de sauvegarde par elle.

## Sauvegardes

Les jeux gardent leurs sauvegardes dans
`$XDG_DATA_HOME/erplibre-home/streamdeck/save/` (`~/.local/share` par
défaut), hors des deux dépôts : aucun clone, aucune synchronisation, aucun
`git clean` ne les atteint. Celles que d'anciennes versions ont laissées
dans `script/stream_deck/games/save/` y passent à la prochaine exécution.

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
game also needs its make target in `conf/make.streamdeck.Makefile`, which
`test_the_game_targets_are_the_games_of_the_clone` asks for.

`script/stream_deck/games/` is a git checkout of streamdeck_game, detached
on a commit of `main`. A clone the installer made names its remote
`origin`; a Google Repo project names it after the manifest's remote,
`TechnoLibre`. Start a branch from the remote's `main` (`git fetch origin
main` then `git switch -c <branch> FETCH_HEAD`, with `TechnoLibre` for a
repo project), commit, and push it to streamdeck_game. While an installer
clone is on a branch or holds local work, the installer leaves it and a
manifest update stops before touching it.

<!-- [fr] -->
Un changement que l'autre côté voit fait monter la version du contrat dans
`CONTRACT.md` et `games_cli.CONTRACT_VERSION`, comme le dit `CONTRACT.md`.
Une version MINEURE ne demande rien d'autre ; la reporter dans
`games_contract` d'ERPLibre quand c'est commode. Une version MAJEURE fait
casser les checkouts tant qu'ERPLibre ne suit pas : pousser le côté
ERPLibre, avec `games_contract` à la nouvelle version, en même temps. Un nouveau jeu demande aussi sa cible make dans
`conf/make.streamdeck.Makefile`, que réclame
`test_the_game_targets_are_the_games_of_the_clone`.

`script/stream_deck/games/` est un checkout git de streamdeck_game, détaché
sur un commit de `main`. Un clone fait par l'installateur nomme son remote
`origin` ; un projet Google Repo le nomme d'après le remote du manifeste,
`TechnoLibre`. Partir d'une branche sur le `main` du remote
(`git fetch origin main` puis `git switch -c <branche> FETCH_HEAD`, avec
`TechnoLibre` pour un projet repo), commiter, et la pousser vers
streamdeck_game. Tant qu'un clone de l'installateur est sur une branche ou
porte du travail local, l'installateur le laisse et une mise à jour des
manifestes s'arrête avant d'y toucher.

<!-- [end] -->
