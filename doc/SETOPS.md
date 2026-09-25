
# Set-OPS: driving the engine from TODO

`TODO › Execute › Deploy › Set-OPS` drives Set-OPS, an engine that builds a
sovereign ecosystem from a declarative plan, with Ansible and Proxmox.
**TODO launches the engine; it does not copy it.** The engine stays the only
source of truth for its gestures, and every command TODO names can be
replayed by hand, without TODO.

The menu shows only what exists: today, the state of the integration and
the setting up of the Ansible environment. The engine's gestures are added
as they are written.

## Getting the engine

The engine is **opt-in**. `manifest/git_manifest_setops.xml` declares it —
its path under `private/repo/` and its revision, a full commit SHA — and no
manifest merged by default names it: an ordinary ERPLibre installation never
contacts the engine's forge. The engine is fetched by:


```bash
./script/manifest/update_manifest_local_setops.sh
```

The script fetches the engine alone, at the pinned revision, through Google
Repo. Its three guards run before any side effect — git daemon, manifest
merge, `.repo/` — and only read, so a refusal leaves nothing behind. They
all speak in the same run: one run names every refusal.

- `.venv.erplibre/bin/repo` missing or not executable: it names
  `./script/install/install_git_repo.sh`;
- a folder that Google Repo did not lay out occupies the engine's path: it
  names the command that moves it aside. That folder is a manual clone —
  a real `.git` folder — or a folder without `.git`, even at a path that
  `.repo/project.list` lists: Google Repo writes that list even when the
  fetch fails;
- ERPLibre's HEAD is detached and no local branch contains it: on a fresh
  workspace, `repo init` needs a branch name, never a bare SHA.

The path guard runs in `.venv.erplibre/bin/python`: when it is missing or
not executable, the script refuses (code `1`) saying the engine's location
could not be checked, and only the next run, once ERPLibre is installed,
names what occupies it.

Its exit code is `3` when a folder that Google Repo did not lay out occupies
the engine's path, `2` without a readable declaration of the engine, and
`1` for the other refusals. Past the guards, it is that of the manifest
merge, `repo init` or `repo sync`, whichever fails first.

The guards never delete nor move anything. Google Repo, however, aligns
`.repo/project.list` with the merged manifest on every sync, this one
included: a project that manifest no longer names loses its tree if the
tree is clean — its objects stay under `.repo/projects/` — and makes the
sync fail, naming it, if it carries changes. The script merges the same
manifests as `./script/manifest/update_manifest_local_dev.sh`, plus the
engine.

Moving the pin forward is a deliberate gesture: a new SHA in the manifest,
reviewed and committed.

### When a sync runs without the engine

Once fetched, the engine belongs to the workspace: the following manifest
merges keep it by themselves, since `.repo/project.list` lists its path,
and `repo forall` — hence `make repo_do_stash` — goes through it like any
other project. The only group list the repository gives `repo init`,
`make repo_configure_group_code_generator` (`-g base,code_generator,setops`),
names it.

A sync that runs WITHOUT it deletes its tree: after a `repo init -g` whose
list lacks `setops`, on an ERPLibre branch that has no
`manifest/git_manifest_setops.xml`, or after a merge run with
`--with_new_manifest` and without `--with_setops`. Google Repo deletes
every file of the tree, those the engine's `.gitignore` hides included;
only the targets of the `instance` and `underlay.yml` links survive, since
they live outside it.
The following merges then leave the engine out: the station is no longer
opted in, and `./script/manifest/update_manifest_local_setops.sh` opts it
back in.

A tree with changes, untracked files included, makes that sync fail
instead (`uncommitted changes are present`), and the tree stays. The sync
goes through once the changes are committed, or stashed with
`git stash --include-untracked`, in the engine itself: `make repo_do_stash`
does not reach it then, since `repo forall` only goes through the projects
the manifest and its groups name.

Nothing that cannot be rebuilt therefore belongs in
`private/repo/Set-OPS-Public`: ecosystems and sites live in its sibling
folders, and vault keys under `~/.config`.

### Migrating a manual clone

A clone made by hand is set aside, then the engine is fetched through the
manifest:


```bash
mv private/repo/Set-OPS-Public private/repo/Set-OPS-Public.manuel
./script/manifest/update_manifest_local_setops.sh
```

The set-aside clone keeps what lives INSIDE the engine's folder: the
`instance` link and `underlay.yml`. The state screen then names the gestures
that mount an ecosystem and a site again.

## Where the data lives

The engine finds its ecosystems and its sites among its **sibling**
folders. That is why it sits under `private/repo/`, which ERPLibre's
`.gitignore` ignores: an ecosystem placed next to the engine carries a
customer's data and never enters an ERPLibre commit.

- the **active ecosystem** is the engine's `instance` link, to a sibling
  folder; TODO reads it and keeps no registry of its own;
- the **mounted site** is the engine's `underlay.yml` link, to the
  `underlay.yml` of a sibling folder;
- the **vault keys** stay outside every repository, under the user's
  configuration directory (`~/.config`, or `$XDG_CONFIG_HOME`).

## The state screen

`Set-OPS - State of the integration, line by line` is READ-ONLY: no `make`,
no network, no write. `git` reads without its optional locks, so it does not
rewrite the engine's index. Beyond `git`, the screen runs a few
bounded subprocesses, in an environment built from scratch:

- the ansible-core version, and the version of each library the engine
  pins, asked of the dedicated venv's Python, when the venv has its
  `ansible-playbook`;
- the `major.minor` that `python3` returns on the gesture's PATH. It is
  asked of a BARE `python3`, because that is exactly what the engine's
  guard does: a venv called by absolute path would answer where the gesture
  itself would fail;
- `scripts/voutes.py etat`, only with an ecosystem mounted AND its
  `plan/serveurs.yml`, the prerequisite of the vault key line. It runs with
  `-B`: nothing is written in the engine, not even the bytecode of its
  modules. Its return code alone is read — its output names the ecosystem
  and is not even captured.

Ten lines, in the order the station is set up: platform, engine manifest,
private location, Google Repo, engine, Ansible environment, mounted
ecosystem, mounted site, ecosystem vault key, station tools. Each line gives
its state, the gesture that settles it, and the source it reads (`↳`),
its paths relative to ERPLibre's root. When a line finds several things to
settle, it names them all on one line, so settling the first does not
uncover the next on the following run.

Three states, because "the repository knows how" and "this station has set
it up" are two distinct questions:

| mark | in the count | meaning |
|---|---|---|
| ✓ | carried | settled here, as its source shows |
| ◐ | to set up here | the repository knows how; the line names the gesture |
| ○ | not in the repository | what the repository does not carry: for instance no declaration, a revision that is not pinned, a location git does not ignore, or the Ansible venv `.venv.todo.setops` it does not set up yet |

A line whose prerequisite is not held says only `first: <segment>`: the
engine line waits for the manifest line to be carried; Ansible, the
ecosystem and the site wait for the engine's folder to be present; the
vault key waits for the ecosystem line to be carried. An unknown verdict is
never ✓: a probe that fails turns its line to ◐ or ○ with "unreadable
verdict" or "cannot tell", never to a traceback.

Line by line:

- **Platform**: carried on Linux; ○ elsewhere, since the engine assumes
  bash and the GNU tools.
- **Engine manifest**: carried when `manifest/git_manifest_setops.xml`
  declares exactly one project of the `setops` group, at a full commit SHA;
  ○ without a readable declaration, or on a revision that is not pinned.
- **Private location**: carried when git ignores what sits next to the
  engine. Its source is the very question the line asks git, to be
  replayed from ERPLibre's root:
  `git check-ignore -v --no-index -- private/repo/.sonde-setops-ignore`
  — return code `0`, ignored; `1`, not ignored (○); anything else, "cannot
  tell" (○). The question bears on an invented name under `private/repo/`:
  asked about the folder itself, without `--no-index`, git answers "not
  ignored", since the folder holds the tracked `private/repo/.gitkeep`.
- **Google Repo**: carried when `.venv.erplibre/bin/repo` is executable,
  the rule the fetch script applies, and `.repo/manifest.xml` exists —
  `repo init` writes it, whereas the manifest merge alone creates the
  `.repo/` folder. Otherwise ◐: without `repo`, the line names
  `./script/install/install_git_repo.sh`; without `.repo/manifest.xml`, the
  fetch script, which initializes `.repo/` — and first, when something
  Google Repo did not lay out occupies the engine's path, the `mv` that
  sets it aside.
- **Engine**: carried only when Google Repo manages it, at the pin, with a
  clean tree. Managed follows the fetch script's rule: `.repo/project.list`
  lists the path AND Google Repo laid out the tree there, its `.git` leading
  under `.repo/`. ◐ when nothing is at the path, naming the fetch script;
  ◐ for a manual clone — anything else at the path, even a listed one:
  another folder, a file, a broken link — naming its `mv`, or when it
  cannot tell whether Google Repo manages the path; ◐ ahead
  of or behind the pin, on a HEAD that does not descend from the pin, on a
  pin the clone does not hold ("resynchronize"), when it
  "cannot tell where HEAD stands against the pin", and on modified files.
  A pin the clone does not hold is a finding: git reads the clone and the
  pinned object is not in it, which resynchronizing settles. "Cannot tell"
  is the lack of a finding — git stops answering, or the pin names an
  object that is not a commit — so the line names no gesture: nothing
  shows that anything is missing. When git cannot read the clone, the line
  says so, and says nothing about the pin or modified files.
- **Ansible environment**: ○ while `.venv.todo.setops` has no
  `ansible-playbook` — the repository does not set it up yet — and when
  the engine's range (`serveur_ops_ansible`) is not a bounded ansible-core
  requirement: another package, a URL, extras, a marker, or no bound.
  Carried when the version the venv imports is within the range; ◐ outside
  it or unreadable. A pre-release is within the range only if the range
  itself names a pre-release, whatever version of `packaging` is
  installed.
- **Mounted ecosystem**: carried when `instance` is a link to a folder that
  holds its `plan/serveurs.yml`. ◐ otherwise: without a link, the line
  names `make -C private/repo/Set-OPS-Public instance-utiliser NOM=…`; a
  real `instance` folder is one the engine refuses to switch.
- **Mounted site**: carried when `underlay.yml` leads to a file, and the
  line names the folder that holds it. Otherwise ◐, a link that leads to
  no file — broken, or to a folder — being named as such, with the same
  gesture, typed from ERPLibre's root:
  `ln -sfn ../<site>/underlay.yml private/repo/Set-OPS-Public/underlay.yml`
  — `<site>` is the sibling folder, under `private/repo/`, that holds the
  site's `underlay.yml`, and the target is relative to the link's folder.
  The source points to the engine's
  `docs/implanter-un-tenant-sur-un-site.md`.
- **Ecosystem vault key**: return code `0` of `scripts/voutes.py etat`,
  carried. ◐ on `1`, the key is missing: the line names the command that
  shows why, since a script that raises exits with `1` too. ◐ "unreadable
  verdict" on any other code, or none.
- **Station tools**: carried as soon as `make`, `git` and `ssh` are found,
  ◐ without one of them. A missing optional tool is listed as a note, with
  the engine targets it blocks.

## The Ansible environment

`Set-OPS - Ansible environment (set it up)` builds the venv that drives the
engine, `.venv.todo.setops` under ERPLibre's root. **It shows every command
before asking**, and each one can be replayed by hand.

Everything it installs is READ in the engine: the ansible-core range
(`serveur_ops_ansible`), the pinned Python libraries
(`requirements-python.txt`) and the pinned collections (`requirements.yml`).
No version is written here. The collections land under the engine, in
`.ansible/collections`, a folder its own `.gitignore` covers: the engine's
tree stays clean, and they do not mix with whatever the station already
carries.

**Why a dedicated Python minor.** The engine's `serveur_ops` role requires
that controller and target share their `major.minor`, and it builds the
offline wheel cache with the `python3` found on the PATH — not with
Ansible's interpreter. A controller on 3.14 therefore produces `cp314`
wheels that a 3.13 target refuses to install, and the guard stops the
gesture before that. The venv is built with a Python 3.13: the one already
on the station if there is one, otherwise the one `mise install python@3.13`
provides. When neither exists, the screen names the command and installs
nothing behind your back.

**Setting up the venv is not enough, it has to be ACTIVATED.** The guard and
the wheel download both run a BARE `python3`. The same 3.13 venv, called by
absolute path on a station whose shell `python3` is 3.14, is refused; with
its `bin` first on the PATH it passes. Every gesture therefore runs with that
PATH, and the verification measures what `python3` returns through it rather
than trusting the venv it just built.

An out-of-range venv is offered for rebuilding, after the screen names what
it found and shows what it would erase. Reinstalling over it would leave the
wrong INTERPRETER, and that is the case that breaks.

## Ecosystems

An ecosystem is a sibling repository of the engine, and the engine works on
ONE at a time: the `instance` link names it, and every gesture applies to it.
Three screens drive the engine's own targets.

`Set-OPS - Ecosystems discovered beside the engine` lists what the engine
finds, with the mounted one marked. The engine returns a refusal when two
FEDERATED ecosystems claim the same index — same VLANs, same VMIDs on the
trunk. The list is shown anyway, with the engine's own words: hiding it would
take away what explains the refusal.

`Set-OPS - Switch the active ecosystem` asks for a NUMBER in the list, never
for the name. A name typed again is a name typed wrong, and the engine then
refuses on a missing folder without saying whether the typing or the
ecosystem is at fault.

`Set-OPS - Create an ecosystem from a template` asks for a name, a template
chosen among those the engine offers, and an index. The free index is
PROPOSED, read from the federated ones already taken; the engine validates
what it receives and refuses a collision. What follows — identity, vault,
first application — is printed by the engine itself.

Every screen opens with the mounted ecosystem, read on the link without
launching anything, and shows each command before running it. Reading runs
with `CONFIRMER=false`, writing with `CONFIRMER=true`, on the line itself.
