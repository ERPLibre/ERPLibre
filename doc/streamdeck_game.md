
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

```
make erplibre_home_streamdeck_install
```

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

```
python3 -m unittest discover -s tests
git push origin main
```

A change the other side can see bumps the contract version in `CONTRACT.md`
and `games_cli.CONTRACT_VERSION`, as `CONTRACT.md` says. A MINOR bump needs
nothing else; record it in ERPLibre's `games_contract` when convenient. A
MAJOR bump breaks the checkouts until ERPLibre follows: push the ERPLibre
side, with `games_contract` set to the new version, together with it. A new
game needs nothing on the ERPLibre side: `make streamdeck_<id>`, the TODO
menu and the gallery find every `game_<id>.py` of the clone, and the menu
takes the game's description from its own `GAME_META`, `description_fr` in
French, read without running the game.

`script/stream_deck/games/` is a Google Repo project of streamdeck_game:
its `.git` links into `.repo/`, and its remote is named after the
manifest's, `TechnoLibre`, over https. Work on a branch that
`repo start <branch> script/stream_deck/games` starts, commit, and push it
(`git push TechnoLibre <branch>`). Each installer run and each manifest
update syncs it by repo's own rules, as for the deck program: a branch
started by `repo start` keeps its commits, rebased on the new `main`; a
detached HEAD moves to `main`; a sync repo refuses leaves the checkout as
it is, and the installer says "NOT updated".
