
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

```
make erplibre_home_streamdeck_install
```

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

```
cd script/stream_deck/deck
../../../.venv.streamdeck/bin/python -m unittest discover -s tests
git push TechnoLibre HEAD:main
```

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
