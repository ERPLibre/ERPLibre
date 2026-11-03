# ERPLibre overrides: odoo-review

The upstream skill targets Odoo master/20.0; ERPLibre runs 18.0 by default.
Where an entry below names an upstream section, the entry wins; everything
not named applies as written. First find the active Odoo version
(`.odoo-version` at the ERPLibre root, else the `odoo<ver>/` directory in use)
and confirm any API against its sources (`odoo<ver>/odoo`), not memory.
Odoo 12-15 are not covered: there, verify every API in the active sources.

## [Reviewing Odoo code](SKILL.md#reviewing-odoo-code)

- Each sibling skill is read with its `ERPLIBRE.md` (`../odoo-guidelines/`,
  `../odoo-web-guidelines/`, `../odoo-security/`).
- In 18: no `ir.access` model; the security row means
  `security/ir.model.access.csv` rows plus `ir.rule` records.
- 16/17: `static/tests/` holds QUnit tests, not hoot.

## [Process](SKILL.md#process)

- **Scope.** Framework in `odoo<ver>/odoo`, each addons repo its own git repo
  under `odoo<ver>/addons/<org>_<repo>`; another `odoo<ver>/` is another
  version, never a source. Repo class (`odoo`, `oca`, `erplibre`), which
  drives Stable vs master: `python3 script/git/commit_convention.py <repo> --explain`.
- **Scope, other half.** No enterprise: any same-named branch in the manifest
  projects (`manifest/*.xml`) plus the ERPLibre root:
  `for d in odoo<ver>/odoo odoo<ver>/addons/*/ .; do git -C "$d" branch -a --list '*<branch>' | sed "s|^|$d: |"; done`
- **Map.** Sections are read with their skill's `ERPLIBRE.md`. Changes in a
  stable version: every file in `odoo` repos; in `oca` repos a bug fix only
  (else Stable vs master, `oca`); never in `erplibre` repos.
- **Merits pass.** Fresh database: `./odoo_bin.sh db drop --if-exists <db>`,
  then `./test.sh -d <db> --db-filter <db> -i <module>`. `make test` is
  ERPLibre's fixed suite, not the module. OCA CI: its GitHub Actions job.
- **Report.** **Guidelines read:** also lists every `ERPLIBRE.md` opened. State
  the repo class and Odoo version. A finding resting on code outside the diff
  names the repo path and its commit: each addons repo has its own history.

## [Stable vs master](SKILL.md#stable-vs-master)

No target is Odoo's master: core and addons track a series branch (`18.0`,
`18.0_dev`, `ERPLibre/18.0`); the ERPLibre root's `develop`/`master` are its
own. By class:

- `odoo`: the stable policy as written. In `odoo` and `oca` repos, ERPLibre's
  `make format` run over upstream files is a finding.
- `oca`: fixes and backward-compatible features land on the series branch;
  the repo's style and pre-commit config win. Version `18.0.x.y.z` (x: data
  model or views, y: feature, z: fix); a breaking change ships its migration
  script. `.po` files belong to Weblate: a PR edits none but a new module's.
- `erplibre`: features are accepted; apply the guidelines to new code as in
  master. Check the `__manifest__.py` version bump fits the change, a
  `migrations/<new version>/pre-*.py` or `post-*.py` when stored data must move
  (runs on update only if the installed version is lower), and a regenerated
  `i18n/<module>.pot` plus updated `i18n/fr_CA.po` (nothing regenerates them
  automatically).

## [Version traps](SKILL.md#version-traps)

- Grep the active version's checkout, not master: the ORM is
  `odoo<ver>/odoo/odoo/models.py`, `fields.py`, `api.py` (`odoo/orm/` is 19+).
- In 18: `attrs=`/`states=`, `<tree>`, `name_get` are gone (`<list>`,
  `view_mode` `list`, `_compute_display_name`). `read_group(domain, fields,
  groupby, ..., lazy)` still exists (dicts): never flag it as removed; server
  code prefers `_read_group(domain, groupby=(), aggregates=(), ...)` (tuples).
- 16/17: `<tree>` and `view_mode` `tree`. 17: `name_get` deprecated
  (override `_compute_display_name`), `attrs`/`states` refused. 16: `name_get`
  and `attrs`/`states` live; `_read_group` has `read_group`'s old signature.

## [Code the diff never shows](SKILL.md#code-the-diff-never-shows)

- Consumers live in every repo of the manifest: `grep -rn` over
  `odoo<ver>/addons/*/`, `odoo<ver>/odoo/addons`, `odoo<ver>/odoo/odoo/addons`
  (`git grep` covers one repo only); the other half is the one from Scope.
- A signature change is no bug on its own in `oca` (breaking: x bump,
  migration notes or script) and `erplibre`; every override and caller found
  changes in the same change set.

## ERPLibre: commits and identifying data

- Commits: `odoo-git` read with its `ERPLIBRE.md`, per-class sections (`odoo`,
  `oca`); `conf/template_claude_commands_commit.md` (`erplibre`). In all:
  `Assisted-by: <model>` for any AI, no AI in `Co-authored-by:`, no
  session-link trailer.
- Code, comments, test data, commits and the report name no customer, real
  database, host, IP or e-mail: generalise to the class of situation. Comments
  say how the code works, never the incident (`.claude/rules/04-code-conventions.md`);
  a cloned module inherits its source's comments. Candidates:
  `python3 script/analyse/check_comment_hygiene.py <file>`.
