# ERPLibre overrides: odoo-guidelines

The upstream text targets Odoo master/20.0; ERPLibre runs 18.0 by default. Where an
entry below names an upstream section, the entry wins; everything not named applies as
written. First find the checkout's Odoo version (`.odoo-version` at the ERPLibre root,
else the `odoo<ver>/` directory in use) and confirm any API in that version's sources
(`odoo<ver>/odoo`), not from memory. Odoo 12-15 are not covered: verify every API there.

## [Module structure and file naming](guidelines/module_structure.md#module-structure-and-file-naming)

- In 16-18: access rows go in `security/ir.model.access.csv` (model `ir.model.access`;
  there is no `ir.access`).
- In 18: no `populate/` (no `populate.blueprint`; `odoo-bin populate` only duplicates
  existing records). 16/17: `populate/` holds Python defining `_populate_factories`.
- Add `migrations/<series>.x.y.z/` (the new manifest `version`) when existing data must
  change on update: `pre-*.py`, `post-*.py`, `end-*.py`, each with
  `migrate(cr, version)`; a `0.0.0/` folder runs on any version change. `readme/`: see
  [OCA readme fragments](#oca-readme-fragments).

## [Manifest](guidelines/manifest.md#manifest)

- `oca` and `erplibre` classes: `version` is `<series>.x.y.z` (`18.0.1.0.0`): `x` for a
  data-model or view change that needs migration, `y` for a backward-compatible
  feature, `z` for a fix. Bump it with every change that needs a module update.
- `odoo` class: keep the module's existing short version (`1.2`); change it only
  together with a `migrations/` script.
- `license` is always explicit (18 logs a warning and falls back to `LGPL-3`). New
  modules in ERPLibre-owned repos: `AGPL-3`; in a third-party repo, the repo's license.
  Never change the license of an existing module, whoever wrote it.
- In 18: nothing injects `base` (`depends` defaults to `[]`). A module that needs
  nothing else writes `'depends': ['base']`; omit `base` only when another dependency
  brings it. Never remove `base` from an existing OCA manifest.
- `oca` class: what the repo's `.pylintrc` and pre-commit enforce: `author` ending in
  `,Odoo Community Association (OCA)`, `website` `https://github.com/OCA/<repo>` (set by
  the `oca-fix-manifest-website` hook), a `license` from the allowed list, a valid
  `maintainers` list and `development_status`, no `description`/`active`.
- `erplibre` class: `author` and `website` as in the sibling manifests of the repo.

## [Imports](guidelines/python.md#imports)

"The `ruff.toml` at the repository root" is the addon's own git repo root, never
ERPLibre's `.ruff.toml` (it excludes `addons/`, `odoo*`). By [repo class](#repository-classes-and-scope):

- `odoo`: `odoo<ver>/odoo/ruff.toml` (17, 18) is lint-only. Lint touched files with
  `.venv.erplibre/bin/ruff check --config odoo<ver>/odoo/ruff.toml <files>`; never
  run a formatter over core files. 16 has none: PEP 8 and the surrounding style.
- `oca`: the repo's `.pre-commit-config.yaml` (ruff, pylint-odoo, prettier, readme
  generator); from the repo root `<erplibre>/.venv.erplibre/bin/pre-commit run --files`.
- `erplibre`, ERPLibre-owned repos (`ERPLibre_*`, `TechnoLibre_*`, those a `make
  format_*` target names): from the ERPLibre root, that target or
  `./script/maintenance/format_addons.sh [--xml] <repo dir name>` (import sort + `ruff
  format`, repo config else `conf/ruff.addons.toml`). Third-party repos: the repo's own
  config, else the surrounding style; never a whole-repo formatter.
- Not `make format` nor `script/maintenance/format.sh` on addon Python: they send
  `addons/` files to isort + black at 79 columns, which is not the addon norm.

## [Naming and model layout](guidelines/python.md#naming-and-model-layout)

- In 16-18: `_sql_constraints` goes with the private attributes (see
  [Computes, onchange and constraints](#computes-onchange-and-constraints)).

## [Translate only static literals](guidelines/python.md#translate-only-static-literals)

- In 18: a list argument is NOT formatted per language; it renders as the repr
  `['a', 'b']`. Format it first with `format_list` (`from odoo.tools import
  format_list`): `self.env._("Missing fields: %s", format_list(self.env, names))`.
- 16/17: no `self.env._` nor `LazyTranslate`: `from odoo import _, _lt`, same
  arguments; `LABEL = _lt("...")` translates on `str()` inside a method. The bare `_`
  fallback logs at DEBUG. 17 has `format_list` as in 18; 16 does not (`", ".join`), and
  its `_()` does not escape arguments: build HTML as `Markup(_("<b>%s</b>")) % value`.

## [Recordsets, domains and context](guidelines/orm.md#recordsets-domains-and-context)

- In 18: no `odoo.fields.Domain`; domains are plain lists. Combine held domains with
  `from odoo.osv import expression`: `expression.AND([d1, d2])`,
  `expression.OR([d1, d2])`, negation `['!', *expression.normalize_domain(d)]`.
- In 18: prefix operators are the native syntax of a literal domain
  (`['|', ('state', '=', 'draft'), ('user_id', '=', False)]`). Domains you hold are
  combined with `expression.AND/OR`, never `+` or hand-inserted `'&'`/`'|'`.
- 16: `grouped()` does not exist.

## [Computes, onchange and constraints](guidelines/orm.md#computes-onchange-and-constraints)

- In 16-18 `_sql_constraints` is THE declarative SQL constraint: do NOT flag, remove or
  convert it (the upstream "flag `_sql_constraints`" rule is master-only). Write
  `_sql_constraints = [('pages_positive', 'CHECK (pages > 0)', "message")]`.
- No `models.Constraint`, `models.Index` or `models.UniqueIndex` in 16-18. One column:
  field `index=`; several: `init()` (see [Fields](#fields)) or `unique(...)` above.

## [Fields](guidelines/fields.md#fields)

- In 16-18: a multi-column or custom index is made in the model's `init()`:
  `tools.create_index(self.env.cr, 'library_book_author_date_idx', self._table,
  ['author_id', 'date'], where='active')`, or `create_unique_index`. Both do nothing
  when an index of that name exists: a changed definition needs a new name.

## [Controllers](guidelines/controllers.md#controllers)

- In 18: route `type` is `'http'` or `'json'` (JSON-RPC, no CSRF token check);
  `'jsonrpc'` and `'json2'` do not exist. `auth='bearer'` takes no `bearer_scope`
  (none exists): it needs a global API key (no scope) as `Authorization: Bearer <key>`.
  Without it, the session is accepted only for an interactive browser navigation
  (`Sec-Fetch-*` headers); a session-only XHR/JSON call raises `AccessDenied`.
- 16/17: `auth` is `user`, `public` or `none`; `readonly` has no effect.

## [Views, actions and data records](guidelines/xml.md#views-actions-and-data-records)

- 16/17: the list view is `<tree>` (view type `tree`, id `<model>_view_tree`).
- 16: no `<asset>` tag; use the manifest `assets` key or `<record model="ir.asset">`.

## [Access rights](guidelines/security.md#access-rights)

16-18 have no `ir.access`, no `operation` column and no `base.group_everyone`. The
whole section is replaced by two separate mechanisms.

- `ir.model.access` (`security/ir.model.access.csv`, header
  `id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink`,
  values 1/0) grants model-level CRUD, without domain; rows OR-ed over the groups.
- DANGER: a row with an empty `group_id:id` GRANTS to every user, portal and public
  included; it never restricts. Flag `perm_write`/`perm_create`/`perm_unlink` = 1 on
  rows whose group is empty, `base.group_portal` or `base.group_public`; scrutinize
  `perm_read` there on any sensitive model.
- `ir.rule` (XML) filters records and never grants beyond the ACL. A rule without
  `groups` is global: AND-ed onto every user (non-overlapping global rules lock
  everyone out). Group rules are OR-ed among the user's groups, then AND-ed with the
  global ones; a user with no group rule on the model gets the global rules only.
  `perm_*` default to True: unchecking one exempts that operation from THIS rule only;
  other rules on the model still apply to it.
- Multi-company: a global rule, `domain_force` `['|', ('company_id', '=', False),
  ('company_id', 'in', company_ids)]` (`company_ids`: the user's active allowed
  companies, in the rule evaluation context). Drop the `False` branch when
  `company_id` is required.

## [Batch ORM calls](guidelines/performance.md#batch-orm-calls)

- 16: `_read_group` has the old `(domain, fields, groupby)` signature; each row is a
  dict, the many2one value an `(id, name)` tuple: `{g['author_id'][0]: g['author_id_count']
  for g in Book.read_group([('author_id', 'in', authors.ids)], ['author_id'], ['author_id'])}`.

## [Tests](guidelines/tests.md#tests)

- In 16-18 the default tags are `standard` and `at_install`. A test needing the full
  registry (business flows, every `HttpCase`) writes `@tagged('post_install',
  '-at_install')`; a bare `@tagged('post_install')` keeps both tags and runs twice.
  `at_install` needs no decorator and no justifying comment.
- In 18: `BaseCommon` disables mail side effects but runs as the superuser in the main
  company: `setup_independent_user()`/`setup_independent_company()` return `None`.
  Override them (`return cls._create_new_internal_user(login='book_user')`, `return
  cls._create_company()`) or use `BaseUsersCommon` (`cls.user_internal`, `user_portal`).
- 16/17: no `setup_independent_*` hooks; the loader also runs imported classes and
  inherited `test_*` methods (no `allow_inherited_tests_method`); no `expectUnloadPage`.
- "runbot" is the repo's CI (OCA: GitHub Actions, fail on an ERROR log; ERPLibre: the
  `erplibre-commands` skill); no parallelization concern.

## [Plain ASCII punctuation in comments and messages](guidelines/comments.md#plain-ascii-punctuation-in-comments-and-messages)

- ASCII applies to code literals (source strings are English), English comments and
  docstrings, and English commit text (all of an `odoo`/`oca` commit, the English half
  of an `erplibre` one). French prose keeps French typography (guillemets, em dash):
  French comments of ERPLibre-owned code, the `--- FR ---` commit section, `msgstr`.
- Core 16-18 strings still hold curly quotes: leave existing text alone.

## [Changes in a stable version](guidelines/stable.md#changes-in-a-stable-version)

Every ERPLibre target is a released series: decide by repo class, not by branch.

- `odoo` (a patch to `odoo<ver>/odoo`): stable.md in full. There is no master to fix a
  term in, and an English-to-English translation cannot replace a Python code term
  (`_()` returns the source unchanged for `en_US`): leave the term.
- `oca`: fixes and backward-compatible features go on the series branch with a version
  bump, plus `migrations/<new version>/` when existing data must change. Keep
  translatable terms and XML ids. A public method signature changes only as a
  deliberate break: an `x` bump, and every override and caller found in the manifest's
  repos updated in the same change set. Do not edit `.po` (Weblate) nor `.pot` (the OCA
  bot regenerates it); a new module may ship its own `.po`.
- `erplibre`: features are allowed. Bump the version, add `migrations/<version>/` for
  any data-model change, and update `i18n/<module>.pot` (`./odoo_bin.sh -d <db>
  --modules=<module> --i18n-export=<file>.pot`) and `i18n/fr_CA.po` in the same change.
  A public method signature change follows the `oca` rule above.

## Repository classes and scope

- Scope: modules in `odoo<ver>/addons/<org>_<repo>/`, `addons/<org>_<repo>/` (one
  Google Repo checkout each), `odoo<ver>/odoo/addons/`, `odoo<ver>/odoo/odoo/addons/`.
- `python3 script/git/commit_convention.py <repo path>` (ERPLibre root) prints `odoo`
  (core `odoo<ver>/odoo`, odoo/* repos), `oca` (OCA repos, forks) or `erplibre` (rest).
- Commits: `odoo`/`oca` follow the odoo-git skill and its ERPLIBRE.md; `erplibre`
  follows `/commit` (`conf/template_claude_commands_commit.md`). In every class: an
  `Assisted-by:` trailer, no AI in `Co-authored-by:`, nothing identifying.

## Comments

- In every repo class, a justifying comment (a `cr.commit()`, a `sudo()`, an opt-out of
  a default) states the technical constraint or the failure mode it prevents. Never an
  incident, date, person, customer, real database, host or address: name the class.
- Check with `python3 script/analyse/check_comment_hygiene.py <file>` (or `--staged`).

## OCA readme fragments

- In a repo whose `.pre-commit-config.yaml` runs `oca-gen-addon-readme` (every OCA
  repo), edit the fragments (`readme/DESCRIPTION.md`, `USAGE.md`, `CONTRIBUTORS.md`,
  ...), never `README.rst` or `static/description/index.html`: the hook generates them.
- Elsewhere `readme/` has no generator: update the fragment and any shipped README.
