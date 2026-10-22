
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

```
make erplibre_home_streamdeck_install
```

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

## Saves

Games keep their saves in `$XDG_DATA_HOME/erplibre-home/streamdeck/save/`
(`~/.local/share` by default), outside both repositories: no clone, sync
or `git clean` reaches them. Saves left in `script/stream_deck/games/save/`
by older versions move there on the next run.

## Changing the games

A commit pushed to `main` of streamdeck_game reaches every checkout at its
next update. Run the games' tests first:

```
python3 -m unittest discover -s tests
git push origin main
```

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
