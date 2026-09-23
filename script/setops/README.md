
# Set-OPS — the declared engine and the state of the integration

Two modules, one split: **the survey touches the system, the decision does
not.** Neither imports the engine's code: it is read through files and
subprocesses. Nothing here asks a question; the menu lives in
`script/todo/setops_menu.py`, and the user manual in
[../../doc/SETOPS.md](../../doc/SETOPS.md).

## `engine` — the manifest is the only authority

`manifest/git_manifest_setops.xml` carries the engine's path and its pinned
revision. The manifest merge, the fetch script and the state screen READ
them here instead of keeping a copy, which would drift at the first move.

These functions work on text only:

- `parse_manifest(texte)`: the engine's `Declaration` — path, revision,
  upstream, remote — or `None`. The engine is THE project of the `setops`
  group: none, or two, and nothing is declared. Its path stays under the
  workspace root, neither absolute nor climbing through `..`, and comes
  back normalised;
- `groups_of(texte)`: the groups of a `groups` attribute, split as Google
  Repo splits them, on commas AND whitespace;
- `mise_de_cote(chemin)`: the `mv` that sets the folder at `chemin` aside
  as `<chemin>.manuel`, quoted to be copied as is;
- `is_pinned(revision)`: true for a full 40-hex SHA only — a branch, a tag
  or a short SHA names something else tomorrow;
- `ignore_probe(chemin)`: the path `parent_is_ignored` asks git about — an
  invented name directly under the parent, since a `folder/` rule only
  applies to a folder and git cannot tell that a path missing from the disk
  is one: the probe answers on a fresh clone too.

The others read the disk or run `git`, and never raise: an unknown verdict
is `None` — or the `inconnue` relation — and the caller decides what to
say. Git never climbs above the folder it is given
(`GIT_CEILING_DIRECTORIES`): a folder without `.git` under ERPLibre's
checkout would otherwise answer with ERPLibre's own HEAD.

- `declaration(racine)`: `parse_manifest` applied to the manifest under
  `racine`;
- `managed_by_repo(racine, chemin)`: does `.repo/project.list` list
  `chemin`? `None` without `.repo/` or with an unreadable list, `False`
  when there is no list yet. The list says what the last sync AIMED at:
  Google Repo writes it even when the fetch fails;
- `repo_worktree(racine, chemin)`: did Google Repo LAY OUT the tree there?
  True when its `.git` — a link, or a `gitdir:` file — resolves under
  `.repo/`; False for a real `.git` folder, as a manual clone has, or for
  no `.git` at all; `None` when the `gitdir:` file cannot be read;
- `relation_to_pin(moteur, sha)`: where the clone's HEAD stands against the
  pin, and how many commits apart;
- `dirty_count(moteur)`: the entries of `git status --porcelain`, untracked
  files included;
- `parent_is_ignored(racine, chemin)`: are the engine's sibling folders
  ignored by the rules of the repository at `racine`, asked with
  `git check-ignore --no-index` about `ignore_probe(chemin)`?

Where the clone's HEAD stands against the pin, from local objects only and
without network, is a closed vocabulary: `egal`, `avance`, `retard`, `diverge`, `absente`, `inconnue`.
Only `absente` is a finding about the pin — git reads the clone and the
pinned commit is not in it, which a resynchronization settles; the last
term, `inconnue`, establishes nothing.

The entry point, `main`, serves the fetch script, run from ERPLibre's root.
`chemin` prints the declared path; `verifier-emplacement` returns `0` when
the path is free, or when Google Repo lists it AND laid out the tree there,
and `3` otherwise — a manual clone, even at a listed path, or a folder
without `.git` — printing the command that moves it aside. Both return `2`
without a readable declaration. Nothing is ever deleted nor moved here.

## `state` — ten lines, decided on a survey

`releve(racine)` touches the system once — files, `git`, and at most two
bounded subprocesses in an environment built from scratch — and never
raises. The ansible-core version is asked of the dedicated venv's Python
only when the venv has its `ansible-playbook`. `scripts/voutes.py etat`
runs only with an ecosystem mounted AND its `plan/serveurs.yml`, the
prerequisite of the only line that reads its code, and with `-B`: the
survey writes nothing in the engine, not even the bytecode of its modules.

`lignes(vu)` is PURE: every verdict can be tested without a machine,
including those that cannot be provoked on the station. The prerequisites
are declared once, in `PREALABLES`; a line whose prerequisite is not held
names it and gives no other verdict, and an unknown verdict is never
carried. Each line names its source, its paths relative to ERPLibre's
root.

The lines are printed by `script/todo/state_screen.py`, the render shared
with the Devstack state screen: two renders would say, sooner or later, two
different things with the same marks.
