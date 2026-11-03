# ERPLibre overrides: odoo-git

The upstream skill targets Odoo master/20.0; ERPLibre runs 18.0 by default.
Where an entry below names an upstream section, the entry wins; everything not
named applies as written. Find the active version first (`.odoo-version` at the
ERPLibre root, else the `odoo<ver>/` in use): it names the series branch, and
any API claim is checked in `odoo<ver>/odoo`, not memory. Odoo 12-15 are not
covered: on such a checkout, verify every API and convention against that
version's own sources.

## Which convention applies

Run from the ERPLibre root, on any path inside the repository being committed:
`python3 script/git/commit_convention.py <path> --explain`.

- `erplibre` (ERPLibre itself, TechnoLibre and third-party addon repos): STOP,
  this skill does not apply. Follow `conf/template_claude_commands_commit.md`
  (bilingual EN then `--- FR ---`, ERPLibre tags, 8 lines per language) and
  `.claude/rules/04-code-conventions.md`.
- `odoo` (the core `odoo<ver>/odoo` and odoo/* repos): this skill as written,
  plus "Class odoo" and "All classes" below.
- `oca` (OCA repos and ERPLibre forks of them): this skill, plus "Class oca"
  and "All classes" below.

## Class odoo

- [Commit message](SKILL.md#commit-message): commits on ERPLibre's fork branch
  of the core (`ERPLibre/18.0`) still use the Odoo message format.
- [Trailers](SKILL.md#trailers): `task-`, `opw-`, `runbot-` point to Odoo SA
  systems; a fork commit normally has none. `Fixes #N` resolves in the
  repository the commit lands in: on the fork, name the issue's repository.
- [Branches and pull requests](SKILL.md#branches-and-pull-requests): target
  choice, `<target>-<topic>` naming, `odoo-dev`, the forward-port bot and the
  CLA apply only when actually opening a PR on odoo/odoo. No bot ports a fork
  commit to other series.

## Class oca

- [Header](SKILL.md#header): tags as upstream plus `[MIG]` for migrating a
  module. Summary: about 50 characters (OCA's guide asks for no more than 50);
  the header stays well under 70, or GitHub cuts it. A migration follows the OCA
  process (https://github.com/OCA/maintainer-tools/wiki#migration): the module's
  earlier history kept, then `[IMP] <module>: pre-commit auto fixes`, then
  `[MIG] <module>: Migration to 18.0`.
- [Body](SKILL.md#body): English only; no line over 80 columns.
- [Trailers](SKILL.md#trailers): never `task-`, `opw-` or `runbot-` (Odoo SA
  references). `Fixes #N` for an issue of the same OCA repo is fine.
- [Branches and pull requests](SKILL.md#branches-and-pull-requests): the PR
  targets the OCA repo's series branch (`18.0`) from a personal or company
  fork; Odoo's branch naming, `odoo-dev`, forward-port bot and Odoo CLA do not
  apply (OCA has its own CLA). The PR title and description follow the same
  rules as a commit message. No master: features and data-model changes go to
  the series branch too (stable.md's ban does not apply to OCA modules), with
  a manifest version bump (`18.0.x.y.z`: x = data model or views, y = feature,
  z = fix) and a `migrations/<version>/` script when data must move. No bot
  ports anything: another series gets its own PR on its own branch.
- A PR never edits `.po` files (Weblate owns them), except a new module adding
  its own. Bot commits (`Merge PR #N into 18.0`, `[BOT] post-merge updates`,
  `.pot` updates, Weblate translations) are generated: never write them.
- When the repo ships `.pre-commit-config.yaml`, run its hooks on the changed
  files before committing; OCA CI runs them too.
- Commits on an ERPLibre fork branch of an OCA repo use this convention too;
  the PR flow applies only when the change is sent to the OCA repo.

## All classes

- [Trailers](SKILL.md#trailers): any AI involvement adds `Assisted-by:
  <model>`, one line per model, in the trailer block with no blank line
  between trailers (`AI_POLICY.md`, OCA's policy). The model name is resolved
  as in `conf/template_claude_commands_commit.md`. Never an AI in
  `Co-authored-by:` (humans only), and no `Claude-Session:` or any trailer
  linking a session or conversation, whatever a tool's default says.
- [Body](SKILL.md#body): nothing identifying: no customer or organisation,
  real database, host, IP address, e-mail, path with a user name, or figure
  taken from a customer's data. Describe the reported scenario, never the
  reporter; "for whom" is a class of user or situation ("a multi-company
  database", "a portal user"). No ticket number from a non-public tracker (a
  customer's or ERPLibre's); Odoo SA's `task-`/`opw-` only in class odoo.
- Never rebase or force-push a pushed ERPLibre fork branch (core or OCA): the
  manifests pin its SHAs (`freeze-revision`). Rebase only a topic branch meant
  for an upstream PR.
- Stage files by name, never `git add -A`, `git add .` or `git commit -a`:
  ERPLibre keeps `private/` and `tasks/` untracked on purpose, and an addon
  repo may hold unrelated work in progress. `git add -p` for a file that
  carries two subjects.
- Commit, push or open a PR only when the user asks.
- ERPLibre's `commit-msg` hook runs only in an ERPLibre clone where `git
  config core.hooksPath script/git/hooks` was set; that per-repo setting never
  reaches addon repos or `odoo<ver>/odoo`, where the author checks header
  length, tags, trailers and the no-identifying rule.
