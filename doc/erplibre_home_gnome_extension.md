
# The ERPLibre Home GNOME extension in ERPLibre

The ERPLibre Home GNOME extension is a repository of its own,
[erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension),
which runs without ERPLibre; its `README.md` says how. This page covers
what ERPLibre adds: where the extension lives in a checkout, how it arrives
and follows new commits, what ERPLibre runs of it, and how to change it.
`CONTRACT.md`, at the root of the extension, states what each side relies
on.

## In a checkout

The extension is cloned at `script/gnome-extension/erplibre_home/`, which
ERPLibre's git ignores, and linked as
`~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`.
`manifest/git_manifest_erplibre_home_gnome_extension.xml` points at its
`main` branch: a checkout gets the latest extension at each update.
`script/gnome-extension/erplibre_home_contract` holds the contract version
ERPLibre is written against, and
`test/test_erplibre_home_extension_repo.py` fails when the clone's MAJOR
differs.

It arrives two ways:

- **Google Repo.** `conf/git_manifest_erplibre_home.csv` names the
  manifest, in the group `erplibre_home`, apart from the Stream Deck's: the
  base installs without the deck. `git_merge_repo_manifest.py` adds it
  when `script/gnome-extension/erplibre_home` exists, or with
  `--with_erplibre_home`; an Odoo server never clones it. Every
  `script/manifest/update_manifest_*.sh` then syncs it to `main`. A plain
  clone made by the installer is refused by `repo sync`:
  `script/manifest/erplibre_home_extension_to_repo.sh`, run between
  `repo init` and `repo sync`, moves only its `.git` to
  `script/gnome-extension/erplibre_home.plain-clone-git-<date>/` when it
  holds no local work, and repo checks `main` out over the files in place:
  the directory the session loads is never empty. It stops the update,
  naming the work, otherwise, and also when the init would make repo
  remove the extension (group `erplibre_home` missing from `repo init -g`).
- **The installer**, for a checkout without Google Repo, at both levels:

```
make erplibre_home_install
```

  It clones the extension when its directory is missing or holds only
  what an untracking update leaves (`locale/`, `schemas/gschemas.compiled`,
  `__pycache__/`), detached on the last commit of `main`, before it reads
  the GNOME versions `metadata.json` supports. At each later run it
  fetches `main` and moves a clone it made to its new last commit; a
  branch or local work stays, and the summary says so. Any other content
  stops the install, naming it. The base therefore needs `git` and GitHub;
  `--extension-only` (`make erplibre_home_install_extension`) clones too,
  and `--uninstall` never removes the clone.

## What ERPLibre runs of it

The installer links the clone, runs `tools/migrate_legacy.py`, compiles
`schemas/` and each `po/<lang>.po`, and enables the extension through
`tools/enable_next_login.py`. The make targets
`erplibre_home_enable_extension`, `erplibre_home_dev_nested`,
`erplibre_home_e2e_nested`, `erplibre_home_compile_locale`,
`extension_i18n_compile`, `claude_install_hooks` and `test_gnome_extension`
run one of its files: without the clone each stops on one line naming
`make erplibre_home_install`. The Stream Deck program, the controller, the
translator and the TODO menu talk to the running extension over D-Bus and
degrade when it does not answer. The extension, in turn, finds the
checkout from its own path and runs the deck program, the controller and
the games gallery from there.

## Changing the extension

A commit pushed to `main` of erplibre-home-gnome-extension reaches every
checkout at its next update. Run the extension's tests first, in its
directory:

```
node --test test/unit/*.test.js
python3 -m unittest discover -s test/python
git push origin main
```

`make test_gnome_extension`, from the ERPLibre root, runs the same suites
after a strict check of the schema. A change the other side can see bumps
the contract version in `CONTRACT.md`, as `CONTRACT.md` says. A MINOR bump
needs nothing else; record it in ERPLibre's `erplibre_home_contract` when
convenient. A MAJOR bump breaks the checkouts until ERPLibre follows: push
the ERPLibre side, with `erplibre_home_contract` set to the new version,
together with it.

`script/gnome-extension/erplibre_home/` is a git checkout of
erplibre-home-gnome-extension. A clone the installer made is detached on a
commit of `main` and names its remote `origin`; a Google Repo project names
it after the manifest's remote, `TechnoLibre`. Start a branch from the
remote's `main` (`git fetch origin main` then
`git switch -c <branch> FETCH_HEAD`, with `TechnoLibre` for a repo
project), commit, and push it. While the clone is on a branch or holds
local work, the installer leaves it; while it holds local work, a manifest
update stops before touching it. The running GNOME session keeps the code it loaded:
`make erplibre_home_reload` loads a new copy under Wayland without logging
out.
