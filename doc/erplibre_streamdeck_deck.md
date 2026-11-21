
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

The deck program is cloned at `script/stream_deck/deck/`, which ERPLibre's
git ignores. `manifest/git_manifest_erplibre_streamdeck_deck.xml` points at
its `main` branch: a checkout gets the latest deck program at each update.
`script/stream_deck/deck_contract` holds the contract version ERPLibre is
written against, and `test/test_streamdeck_deck_repo.py` fails when the
MAJOR of the clone's `CONTRACT.md` differs or its MINOR is lower: such a
clone lacks something ERPLibre uses. ERPLibre's tests that read the
clone go through `test/streamdeck_deck.py`, and are skipped, naming the
install command, when the clone is missing.

It arrives two ways:

- **Google Repo.** `conf/git_manifest_streamdeck.csv` names the manifest,
  in the group `streamdeck`, apart from the extension's `erplibre_home`:
  the base of ERPLibre Home installs without the deck.
  `git_merge_repo_manifest.py` adds it when `script/stream_deck/deck`
  exists, or with `--with_streamdeck`; an Odoo server never clones it.
  Every `script/manifest/update_manifest_*.sh` then syncs it to `main`. A
  plain clone made by the installer is refused by `repo sync`:
  `script/manifest/streamdeck_deck_to_repo.sh`, run between `repo init`
  and `repo sync`, moves only its `.git` to
  `script/stream_deck/deck.plain-clone-git-<date>/` when it holds no local
  work, and repo checks `main` out over the files in place: the directory
  the service runs from is never empty. It stops the update, naming the
  work, otherwise, and also when the init would make repo remove the deck
  (group `streamdeck` missing from `repo init -g`).
- **The installer**, for a checkout without Google Repo, at the Stream
  Deck level:

```
make erplibre_home_streamdeck_install
```

  It clones the deck program when its directory is missing or holds only
  Python caches, detached on the last commit of `main`, then installs its
  `requirements.txt` in `.venv.streamdeck`. At each later run it fetches
  `main` and moves a clone it made to its new last commit; a branch or
  local work stays, and the summary says so. Any other content stops the
  install, naming it. `--uninstall` never removes the clone.

## What ERPLibre runs of it

`DECK_PROGRAM` of `streamdeck.conf` picks what the service
`erplibre-home-streamdeck.service` runs, through
`script/install/erplibre_home_deck.sh`: `tiler`, the package
`script/stream_deck/deck/erplibre_streamdeck`, or `controller`,
`script/stream_deck/deck/erplibre_controller.py`, both under
`.venv.streamdeck`. Without the clone, the service's start check and the
entry point stop on one line naming `make erplibre_home_streamdeck_install`.
The make targets `streamdeck_erplibre`, `streamdeck`, `streamdeck_tiler`,
`streamdeck_translator_*`, `streamdeck_tiler_unittest` (the deck's whole
suite) and `streamdeck_translator_unittest` run a file of the clone and
stop the same way. TODO › ERPLibre Home reads the deck lock through the
clone's `deck_lock.py`, lists the plugins of
`erplibre_streamdeck/plugins/`, and says "Deck program: not cloned"
without it. The GNOME extension looks for the deck program in the clone
first (its contract 1.5).

## Changing the deck program

A commit pushed to `main` of erplibre_streamdeck reaches every checkout at
its next update. Run the deck's tests first, in its directory:

```
cd script/stream_deck/deck
../../../.venv.streamdeck/bin/python -m unittest discover -s tests
git push origin main
```

`make streamdeck_tiler_unittest`, from the ERPLibre root, runs the same
suite. A change the other side can see bumps the contract version in
`CONTRACT.md`, as `CONTRACT.md` says. A MINOR bump needs nothing else;
record it in ERPLibre's `deck_contract` once ERPLibre relies on what it
adds, since a clone below it then fails ERPLibre's tests. A MAJOR bump
breaks the checkouts until ERPLibre follows: push the ERPLibre side, with
`deck_contract` set to the new version, together with it.

`script/stream_deck/deck/` is a git checkout of erplibre_streamdeck. A
clone the installer made is detached on a commit of `main` and names its
remote `origin`; a Google Repo project names it after the manifest's
remote, `TechnoLibre`. Start a branch from the remote's `main`
(`git fetch origin main` then `git switch -c <branch> FETCH_HEAD`, with
`TechnoLibre` for a repo project), commit, and push it. While the clone is
on a branch or holds local work, the installer leaves it; while it holds
local work, a manifest update stops before touching it. A running deck
program keeps the code it loaded: restart the service
(`systemctl --user restart erplibre-home-streamdeck.service`).
