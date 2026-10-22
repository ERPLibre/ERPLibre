# ERPLibre Stream Deck: the game library in its own repository

**Status:** steps 1 to 5 done, and version 1.1. The games repository is
pushed; its first version is tagged `v1.0.0`, and from 1.1 ERPLibre follows
its `main` branch instead of a tag. Playing a game on the deck, from TODO,
make and the gallery, remains for a person.
**Builds on:** `2026-10-17-erplibre-streamdeck-games-split-design.md` (B1:
games and gallery in `script/stream_deck/games/`, the `GAMES` setting) and
`2026-10-14-erplibre-home-deck-service-menu-design.md` (deck service, deck
lock, hand-over).

## Goal

`script/stream_deck/games/` holds 45 games, their shared command line and
the web gallery: about 780 KB of Python that has nothing to do with an Odoo
distribution. Its fixes fill the ERPLibre history, release notes and
reviews, and it would release on its own cadence if it could.

After this work:

- the game library lives in its own repository, with its history;
- an ERPLibre checkout finds it at the same path,
  `script/stream_deck/games/`, so no make target, menu, extension or
  mobile bundle path changes;
- what the two sides expect of each other is written down and versioned
  (the contract below), and each side tests its half;
- an ERPLibre checkout without the games works: the deck program, the
  controller and the service run, and every game entry says the library is
  absent instead of failing.

## Out of scope

- Changing any game, the gallery's behaviour or `games_cli.py`'s options.
- Moving the deck program (`erplibre_streamdeck/`), the controller,
  `deck_lock.py`, `Assets/` or the install scripts: they stay in ERPLibre.
- The extension hiding its Games submenu when the games are absent (a
  follow-up; the gallery probe already shows it offline).
- Publishing the games as a Python package. They are scripts run by path.

## Where the two sides touch today

Read from the code at the time of writing; the plan re-reads it.

| ERPLibre side | What it uses of `games/` |
|---|---|
| `conf/make.streamdeck.Makefile` | 45 `streamdeck_<game>` targets and `streamdeck_gallery`, by path, behind `streamdeck_games_guard` |
| `script/todo/todo.py` | `_scan_streamdeck_games` lists `games/game_*.py`; the TODO games menu runs one through the hand-over |
| `script/gnome-extension/erplibre_home/lib/project-root.js` | `GALLERY_SERVER_REL`, the gallery's path; the controller indicator starts it and reads `GET /api/games`, `GET /launch/<id>` on port 8042 |
| `script/install/erplibre_home_handover.sh` | runs a game under the deck lock as program `game`; exits 4 when `GAMES` is not on |
| `script/stream_deck/deck_lock.py` | `HANDOVER_PROGRAM`, `deck.inner`, exit 2 on a held deck |
| `script/install/erplibre_home_settings.sh` | `deck_games_enabled`, `deck_games_message` |
| `.venv.streamdeck` / `script/stream_deck/requirements.txt` | the interpreter and libraries every game runs under |
| `.gitignore` | `script/stream_deck/games/save/` (the save files) |
| `mobile/erplibre_home_mobile/vite.config.ts` | bundles the checkout, manifest repositories included, into the app's source viewer |
| tests | `test_streamdeck_games_layout.py` (9), parts of `test_streamdeck_entry_points.py` (48) and `test_todo_streamdeck_menu.py` (47) |

| Games side | What it uses of ERPLibre |
|---|---|
| `gallery_server.py` | `ERPLIBRE_DIR` three levels up; runs `script/install/erplibre_home_handover.sh` and sources `script/install/erplibre_home_settings.sh` |
| `game_*.py` | `games_cli.py` only; no game imports a sibling, `deck_lock` or anything above `games/` |

## The contract

A file `CONTRACT.md` at the root of the games repository states it, with a
version `MAJOR.MINOR`. `games_cli.py` exposes the same value as
`CONTRACT_VERSION`. ERPLibre records the version it was built against in
`script/stream_deck/games_contract` (one line), and its tests check the
two match in MAJOR. `CONTRACT.md` 1.0, as written in the repository, is
the authoritative text; it adds to the points below that a game's
docstring opens on its one-line description, read by the TODO menu, and
two optional `--meta` keys: `saves`, and `section`, which the extension
reads.

1. **Layout.** A game is a file `game_<id>.py` at the repository root,
   executable, runnable as `python game_<id>.py`. `<id>` is
   `[a-z0-9]+`. No other root file matches `game_*.py`.
2. **Command line** (`games_cli.py`). `-h`/`--help` print the usage and
   exit 0, and an unknown argument exits 2, both before the PIL and
   StreamDeck imports. `--meta` prints one JSON object on stdout and exits
   0 within 5 s, after those imports but without opening the deck. Keys:
   `name`, `category`, `multiplayer`, `sdplus`, `description`, `icon`;
   readers ignore unknown keys.
3. **Playing.** Without an option the game opens the first Stream Deck,
   plays, and exits 0 when the player quits. It never takes the deck lock
   itself: the hand-over holds it. Any exit code is passed through by the
   hand-over.
4. **Saves.** A game that keeps state writes it under `save/` at the
   repository root (today only DJ Scratch does), in files whose name
   contains `<id>`; the gallery lists and deletes them by that rule. The
   repository ignores `save/*` and keeps `save/.gitkeep`.
5. **Gallery.** `gallery_server.py` serves on port 8042. The extension
   relies on `GET /api/games` (the `--meta` objects plus `id` and `saves`)
   and `GET /launch/<id>` (2xx when started, else `{"error": "<line>"}`,
   403 for games off, 404 for an unknown id). `/stop`, `/api/restart` and
   the `/api/saves…` routes serve its own page only. It launches every
   game through `<ERPLibre>/script/install/erplibre_home_handover.sh`.
6. **What the games need from ERPLibre.** The checkout root is three levels
   above the repository; `script/install/erplibre_home_handover.sh` exists
   and exits 4 when `GAMES` is not on;
   `script/install/erplibre_home_settings.sh` defines `deck_games_enabled`
   and `deck_games_message`; the interpreter is
   `.venv.streamdeck/bin/python` with `requirements.txt` installed.
7. **Versioning.** A change a reader on the other side can see (a new
   required key, a moved file, a new exit code) bumps MAJOR; an optional
   addition bumps MINOR.

## Repository

- **Name:** `streamdeck_game`, at
  `https://github.com/TechnoLibre/streamdeck_game`, branch `main`. Its
  first commit, made when it was created, holds `LICENSE` (AGPL-3.0, like
  ERPLibre), a two-line `README.md` and GitHub's Python `.gitignore`.
- **Root:** the content of today's `script/stream_deck/games/`, plus
  `CONTRACT.md`, `README.base.md` with its mmg outputs, and the tests that
  belong to it (below). The `.gitignore` gains `save/*` and
  `!save/.gitkeep`; the template already ignores `__pycache__/`.
- **History:** `git filter-repo` on a fresh clone of ERPLibre's
  `dev/streamdeck`, keeping these paths and renaming them to the root:

  ```
  --path script/stream_deck/games/
  --path-glob 'script/stream_deck/game_*.py'
  --path script/stream_deck/gallery_server.py
  --path script/stream_deck/index.html
  --path script/stream_deck/save/.gitkeep
  --path-rename script/stream_deck/games/:
  --path-rename script/stream_deck/:
  ```

  The list is written out, not taken from `git log --follow`: `--follow`
  pairs empty files across unrelated paths, so `save/.gitkeep`'s history
  pulls in the empty `__init__.py` files of `script/` and `private/`.
  Commits that touched only other files disappear, and a message that
  names ERPLibre-only files stays as it was written. The result, 17
  commits, is merged into `main` with `--allow-unrelated-histories`, so
  the repository's first commit stays first and each imported commit
  keeps its date. The merged tree's files are identical to
  `script/stream_deck/games/` at the cut.
- **Commits after the cut:** a fix to a game that lands in ERPLibre between
  the cut and the untrack commit (step 4) is replayed in the games
  repository by hand; the cut is taken right before step 4 to keep that
  window empty.

## ERPLibre side

1. **Manifest.** `manifest/git_manifest_streamdeck_game.xml` declares the
   `TechnoLibre` remote, as `git_manifest_mobile_home.xml` does, and the
   project `name="streamdeck_game.git"` at
   `path="script/stream_deck/games"`, `groups="streamdeck"`, first pinned
   to the tag `v1.0.0`, then on `main` from version 1.1 (see Version 1.1).
   The three lists
   `conf/git_manifest.csv`, `git_manifest_mobile.csv` and
   `git_manifest_odoo.csv` name it: `git_merge_repo_manifest.py` skips
   `git_manifest.csv` when a checkout has both the mobile project and the
   Odoo modules, so one list alone would miss that case. Unlike the mobile
   project, it needs no `--with_…` option, since it weighs under 1 MB.
2. **A checkout without Google Repo.** `install_erplibre_home.sh
   --stream-deck` never runs `repo sync`, and a plain `git clone` of
   ERPLibre has no games. The Stream Deck level therefore clones the games
   repository at the revision the manifest pins, read from the manifest
   file with `xml.etree`, when `script/stream_deck/games/` is absent or
   holds only `save/` and `__pycache__/`. Those two are what a checkout
   keeps when it pulls the untrack commit, since git removes the tracked
   files and leaves the ignored ones; the clone then takes the saves over.
   Any other existing directory is left alone, whatever manages it,
   except a clean detached clone the installer made, which follows the
   manifest's revision (see Version 1.1). The
   clone goes to a sibling temporary directory renamed once checked out, so
   a failure leaves no half-filled `games/`. `--uninstall` does not delete
   it (open question 1, as proposed). `--dry-run` prints
   `games: clone <url> at <revision> into <dir>` or `games: keep <dir>`.
3. **Untrack.** `git rm -r --cached script/stream_deck/games`, the path
   added to `.gitignore` like `/mobile/erplibre_home_mobile/`, in the same
   commit as the manifest, so no checkout ever has the files both tracked
   and managed by repo. `script/stream_deck/games_contract` lands in that
   commit too.
4. **Games absent.** Every entry point that runs a game first checks that
   `script/stream_deck/games/games_cli.py` exists, and otherwise prints one
   line naming how to get it (`make erplibre_home_streamdeck_install`).
   `erplibre_home_settings.sh` holds the check and the line
   (`deck_games_present`, `deck_games_absent_message`); the make target
   `streamdeck_games_present` gates `streamdeck_games_guard`, hence every
   game target, and `streamdeck_gallery`; the TODO games menu checks
   before scanning; the hand-over exits 5, before stopping anything. The
   extension already greys its gallery entry when `gallery_server.py` is
   missing, under the label "Stream Deck not installed", which is
   imprecise when only the games are missing (open question 3). The deck
   program, the controller and the service never look at `games/`.
5. **Docs.** `script/stream_deck/INSTALL.base.md`, `README.base.md` and
   the CHANGELOG say where the games live and how they arrive; mmg
   regenerates the outputs.

## Tests

- **Moved to the games repository:** the checks on the games themselves
  (layout, `--help` exit 0, unknown option exit 2, no option reaches the
  hardware, `--meta` keys and placement, the gallery's command line), in
  its `tests/test_contract.py`, standard library only. They leave
  `test_streamdeck_entry_points.py`, and `test_streamdeck_games_layout.py`
  becomes `test_streamdeck_games_repo.py`.
- **Stay in ERPLibre:** the hand-over, the make guard and the TODO games
  command run in a reduced copy of the checkout from
  `test/streamdeck_checkout.py` (hand-over, settings library,
  `deck_lock.py`, and a fake `games/` holding only `games_cli.py`), so
  they no longer depend on the real library; plus one test per entry point
  with `games/` absent. The gallery's integration with the hand-over and
  `GAMES`, the real scans and "every installed game has its make target"
  read the real clone and are skipped with their reason without it. The
  suite passes both with and without `games/`.
- **Boundary and contract:** `test_streamdeck_games_repo.py` checks that
  ERPLibre tracks nothing under `games/` and ignores it, that the manifest
  names the games' `main` branch (a tag before 1.1) and the three lists
  name it, and that `games_contract` and,
  when cloned, `games_cli.CONTRACT_VERSION` share their MAJOR.
- **Installer:** `games_source` returns the manifest's project; a clone
  from a local repository lands on the manifest's revision, detached; a
  clean clone follows a new tag or a new commit of `main`, also after
  `main` is rewritten upstream; a branch or local work stays; any other
  directory is untouched; leftovers are cloned around the saves; a failed
  clone leaves nothing; the dry-run lines.
- **Long test:** `long_test/install_erplibre_home.py` gains the `games`
  check after `venv`: on the VM, `games/games_cli.py` exists and HEAD is
  the manifest's revision (`origin/main` from 1.1).
- **Mobile bundle:** one build with the games as a manifest repository,
  checking the bundle index lists `script/stream_deck/games/` (its files
  are all under the 1 MB limit) and `check_bundle_transfer.py` passes.

## Order of work

1. Write `CONTRACT.md` and `CONTRACT_VERSION`, with the tests that pin
   them (done, in the games repository).
2. Make every ERPLibre entry point work with `games/` absent (step 4 of
   the ERPLibre side), tested with a temporary checkout (done).
3. In the games repository: import the history with `git filter-repo`,
   ignore `save/`, add the README; push, then tag `v1.0.0` (done).
4. In one ERPLibre commit: manifest, csv entries, `.gitignore`, untrack,
   `games_contract`. Then the installer's clone, then the docs (done,
   in the same commit, so a pull never removes the games without the
   installer that clones them back).
5. On a fresh `git clone` and on a `repo sync` checkout: install the Stream
   Deck level, play one game from TODO, from make and from the gallery.
   Done in scratch checkouts, without hardware (see Step 5 below); playing
   on the deck remains for a person.

Step 2 is useful on its own. Since the repository existed when the work
started, step 1 landed in it, after the import of step 3, rather than in
ERPLibre first. The ERPLibre tests that check the games themselves
(`test_streamdeck_games_layout.py`, the games' part of
`test_streamdeck_entry_points.py`) leave with step 4.

## Step 5

Checked on scratch checkouts, never on a real session: a fresh clone of
`dev/streamdeck`, one pulled from the commit before the move, and repo
v2.69 workspaces. What held: without the games every entry point refuses
with one line; the installer clones `v1.0.0`, also over the `save/` and
`__pycache__/` a pull leaves, keeping the saves; with the games, make, the
TODO scan and the real gallery scan under `.venv.streamdeck` list the 45
games; the unit suite passes with and without `games/`.

What it found, and the fixes:

- **repo sync refuses an installer clone** (`.git: unsupported checkout
  state`), while it adopts a directory of untracked files.
  `script/manifest/streamdeck_games_to_repo.sh` runs between `repo init`
  and `repo sync` in every `update_manifest_*.sh`. When `repo list -p
  --all` names the path (without `--all`, repo lists only projects already
  checked out), it moves a plain clone without visible local work to
  `games.plain-clone-<date>/` and copies `save/` back; visible local work
  stops the update. A first version deleted the clone and lost work its
  checks missed (`status.showUntrackedFiles=no`, skip-worktree, commits
  reached only by a local tag or the reflog, linked worktrees): nothing is
  deleted now.
- **repo deletes a project directory an init leaves out**, saves
  included (the games ignore `save/*`, so repo sees nothing dirty): the
  code generator's init gains the `streamdeck` group, and the same script
  copies `save/` to `games.save-<date>/` when an init leaves a repo-managed
  `games/` out. A `.git` file not pointing into `.repo/` holds the clone
  back; the old repo layout (`.git/objects` a link) counts as repo's.
- **A silent dead end:** a `games/` holding anything besides `save/` and
  `__pycache__/` was kept without a word. The installer's summary now
  names those entries; dotted names, dangling links and a `games` file
  count too.
- The absent message names `games_cli.py`, which is what is tested; the
  installer's clone gets the umask mode instead of `mktemp`'s 0700.
- A tracked game file edited before the pull blocks it; INSTALL says what
  to do.

## Open questions

1. `--uninstall` and the games directory: kept, as proposed (it may hold
   saves, and repo may manage it); removing it when the installer cloned
   it stays possible later.
2. Whether the gallery stays with the games (proposed: it lists and
   launches them, and its only ERPLibre dependency is the hand-over path)
   or moves to ERPLibre next to the deck program.
3. Whether the extension should hide its Games submenu when `games/` is
   absent, in this work or the follow-up.
4. Where the saves should live: decided for streamdeck_game 1.1 (see
   Version 1.1 below).

## Version 1.1

- **Saves out of the repository.** `games_cli.save_dir()` is
  `$XDG_DATA_HOME/erplibre-home/streamdeck/save/`: no clone, `repo sync`,
  `git clean` or excluding init reaches it, and the mobile bundle, which
  walks the workspace, no longer ships it. Files left in the former
  `save/` move there, never over an existing file; djscratch finds the WAV
  paths its state recorded by their name. ERPLibre never reads the saves,
  so the contract moves to 1.1, not 2.0.
- **The repository stands alone.** Its README installs and runs the games
  without ERPLibre (`requirements.txt`, a udev rule, a venv); a game
  missing its libraries names that file; the gallery, with no ERPLibre
  three levels up, reads no `GAMES` setting and runs games without a
  hand-over. ERPLibre's side is in `doc/streamdeck_game.md`.
- **ERPLibre follows `main`, not a tag.** The manifest names the games'
  `main` branch, so repo sync and the installer bring their last commit;
  no tag is cut per version. The installer clones detached on
  `origin/main`, fetches at each run and moves a clone it made, unless it
  holds a branch or local work; it installs the games' `requirements.txt`
  in `.venv.streamdeck`. The contract's MAJOR check is then the only guard
  between the two sides: a MAJOR change lands on both together.

## Risks

- **Two sources of the revision.** The installer reads it from the
  manifest file, never from a copy of its own.
- **A checkout with the files still tracked** when `repo sync` brings the
  project: repo refuses to overwrite tracked files. The untrack commit
  and the manifest land together (step 4) for that reason.
- **Mobile bundle:** the workspace bundle walks the disk, not
  `git ls-files`, so `games/` stays in it, and once a local manifest names
  the games the manifest-repo loop packs them too: 56 files twice, about
  0.75 MB. The fix belongs to the mobile repository: pass the manifest
  projects present on disk as `excludeAbsPaths` to the workspace walk.
  Not done here.
- **A `-g` without `streamdeck`** passed to `update_manifest_local_dev.sh`
  or `update_manifest_local_mobile.sh` once repo manages the games makes
  repo delete them; the saves survive as a copy in `games.save-<date>/`.
  An ERPLibre commit from before the move has no such guard, and its
  update deletes `games/` with the saves (open question 4).
- **The gallery listened on every interface,** with acting routes on a
  plain GET and `Access-Control-Allow-Origin: *`: any host on the
  network, or any page in the browser, could launch a game or delete
  saves. Contract 2.0 closes it: 127.0.0.1 only, a Host check against DNS
  rebinding, Sec-Fetch-Site against other sites, and the header
  `X-Stream-Deck-Gallery: 1` on acting routes, which the extension sends;
  a client that sends no Sec-Fetch-Site, such as wkhtmltopdf rendering an
  `<img>`, cannot add it. A MAJOR change, landed on both sides together.
- **Saves.** Today `script/stream_deck/games/save/` is ignored by ERPLibre;
  after the move it is ignored by the games repository. A `git clean -fdx`
  in the games repository deletes them, as it would today in ERPLibre.
