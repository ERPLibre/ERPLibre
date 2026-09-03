---
name: todo_generate_code
description: "Write code in ERPLibre by the rules the repository actually enforces: Odoo/OCA module conventions first, then the real format and verify toolchain."
disable-model-invocation: true
effort: high
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(make format:*)
  - Bash(make test_unit:*)
  - Bash(make test_unit_file:*)
  - Bash(./script/maintenance/:*)
  - Bash(python3:*)
  - Bash(git status:*)
  - Bash(git diff:*)
  - Bash(ls:*)
  - Bash(cat:*)
---

## Context

- Odoo series in this checkout: !`cat .odoo-version`
- Available venvs: !`ls -d .venv.* 2>/dev/null`
- Branch and pending work: !`git status --porcelain`
- Addons trees: !`ls -d odoo*/addons/*/ 2>/dev/null | head -12`

## Task

Write code in this repository by the rules it ENFORCES, which are not always
the rules it documents. Establish them first, then write. The sections below
were read off the configuration files and the in-house modules, not off the
prose; where a document disagrees with a tool, the tool wins and the
disagreement is named.

### The effort tier

The `effort: high` above applies to this invocation — "comprehensive
implementation with extensive testing", the tier for code that has to survive
review.

A session can be pinned above it. `/effort ultracode` sets xhigh AND turns on
dynamic workflow orchestration, and a system-reminder then asks for a workflow
on every substantive task. That standing opt-in does not apply here: writing
one module correctly is one agent's job, and fanning it out multiplies both the
token cost and the ways the pieces disagree.

So when a reminder says ultracode is on, say in one line that this command
works at high, and ask the user to type `/effort high` — that one command sets
the tier and clears the ultracode flag in the same move. A command's
frontmatter cannot release a session pin; only the user's own `/effort` can,
from an interactive terminal. Work solo either way.

### 1. Before writing a line

**Find the tree.** New modules go under `odoo<VERSION>/addons/<Org>_<repo>/<module>/`
— the version-prefixed tree is the real addons root, and the generator
rewrites any `addons/` it is handed into `odoo<VERSION>/addons/`
(`script/code_generator/new_project.py:144-146`). The version is in
`.odoo-version`; the venv carries BOTH versions in its name, so find it with
`ls -d .venv.odoo*` rather than composing it from memory.

**Read the neighbours.** Two or three in-house modules under
`odoo<VERSION>/addons/ERPLibre_erplibre_addons/` show the conventions in force
better than any list. Copy their shape.

**Bootstrap rather than hand-roll.** `script/code_generator/new_project.py -d
<git root dir> -m <module name>` creates a module; `create_from_existing_module.py`
clones one. A module cloned from an existing one INHERITS its comments and
docstrings — reread them before committing, a client or database name travels
that way on its own.

**Two rules bind every line you write**, and no tool checks either:
- Nothing identifying outside `private/` — no customer or third-party
  organisation, no real database, host or VM name, no IP, e-mail or path
  carrying an account name. Generalise to the class of situation instead.
- A comment says how the CODE works, in the present. A sentence whose subject
  is an incident, a machine, a date or a person belongs in `tasks/`, which is
  not versioned.

**Never edit a generated file.** `FICHIER.md` and `FICHIER.fr.md` come from
`FICHIER.base.md` through mmg; an edit is lost at the next `make doc_markdown`.

### 2. Odoo module conventions

`__manifest__.py` carries at minimum `name`, `version`, `author`, `license`,
`category`, `summary`, `depends`, `data`, `installable`. `version` is
`<series>.1.0.0` — `18.0.1.0.0` on an 18.0 checkout — and `license` is
`AGPL-3`, which every in-house module uses.

The `data` list is ordered `security/`, then `data/`, then `wizards/`, then
`views/`, with `views/menu.xml` last.

Non-Odoo Python requirements go in `external_dependencies: {"python": [...]}`,
and the import is guarded in the model with `try/except ImportError` logging at
debug level — a missing optional dependency must not break the registry.

Layout: `models/`, `views/`, `security/`, `wizards/`, `data/`, `controllers/`,
`i18n/`, `report/`, `tests/`, `static/description/`. Ship
`static/description/icon.png`.

Naming, one for one:
- `models/<model_name_with_dots_as_underscores>.py`, one model per file —
  model `devops.workspace` lives in `models/devops_workspace.py`.
- `views/<same_name>.xml` for a Model; a TransientModel's Python AND its XML
  both live in `wizards/`.
- `ir.ui.view` ids: `<model_underscored>_view_<type>` (`_view_form`,
  `_view_tree`, `_view_search`, `_view_kanban`).
- `ir.actions.act_window` ids: `<model_underscored>_<action>_action_window`;
  server actions: `<model_underscored>_<name>_server_action`.
- `res.groups` go in `security/<module_name>.xml` — named after the module, not
  `security.xml` — and that file is listed BEFORE `ir.model.access.csv`.

`security/ir.model.access.csv` carries exactly the header
`id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink`.
Split the rows by privilege level — a read-only row for the broad group, a
full-CRUD row for the administrative one — rather than one blanket row.

Every Python file opens with the AGPL licence comment; hand-written models and
hooks also carry the shebang and copyright lines. A package `__init__.py`
starts with `# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)`,
a blank line, then imports. The root `__init__.py` imports subpackages on one
line (`from . import models, wizards`) and a hook by name
(`from .hooks import post_init_hook`); hooks live in a top-level `hooks.py` and
are declared under the matching manifest key.

Models declare `_name`, `_description` and, when mixins are used, `_inherit`;
the class name is the CamelCase of the model. Odoo symbols come in one grouped
import — `from odoo import _, api, exceptions, fields, models`.

Translations go in `i18n/` as `<module>.pot` plus one `.po` per locale.

### 3. Format — the toolchain that exists

`make format` before committing. It formats only what git reports as
modified, added, renamed or untracked, dispatching each file by extension —
so it is cheap and safe to run repeatedly. `make format_all` sweeps whole
areas instead.

What it runs underneath, and what to match when writing by hand:

| Kind | Tool and settings |
|------|-------------------|
| Python | `isort --profile black -l 79`, then `black -l 79 --preview -t py37` |
| XML | prettier + `@prettier/plugin-xml`, tab-width 4, print-width 120 |
| XML under `data/` | same, print-width 999999999 — long data strings stay on one line |
| js, css, scss, html | prettier, tab-width 4, print-width 120, no bracket spacing |
| Shell | `shfmt -i 2 -ci -w` |

black and isort run from `.venv.erplibre`, prettier from the repo-pinned
`./node_modules/.bin` — a globally installed prettier is a different version
and reformats differently. Nothing under `not_supported_files/` is formatted.

**What NOT to run**, each verified absent from this checkout rather than
assumed:
- `./script/maintenance/autopep8.sh` — `oca-autopep8` is not installed; the
  script exits 1. `doc/DEVELOPMENT.base.md` still recommends it; the document
  is stale.
- Any `oca-*` console script (`oca-gen-addon-readme`, `oca-towncrier`, …) —
  `script/OCA_maintainer-tools` is checked out but never pip-installed, and its
  install block in `install_locally_dev.sh` is commented out. Run one as a
  module from that directory if you truly need it.
- `pre-commit run` at the repository root — there is no root
  `.pre-commit-config.yaml`. ERPLibre's own hooks are hand-written Python,
  installed once per clone with
  `git config core.hooksPath script/git/hooks`.

**A vendored OCA addon** under `odoo<VERSION>/addons/OCA_*` carries its own
`.pre-commit-config.yaml`: run THAT from its directory instead of the ERPLibre
format scripts, so the patch matches what upstream will accept.

### 4. Lint

Neither linter runs on its own — no target, no hook, no CI invokes them, so
running them is a deliberate act:

- flake8 lives in the Odoo venv, not `.venv.erplibre`. The root `.flake8`
  applies: max-line-length 80, max-complexity 16, `select = C,E,F,W,B,B9`,
  ignoring E203, E501 and W503 for black compatibility.
- pylint-odoo also lives in the Odoo venv:
  `.venv.odoo<...>/bin/pylint --load-plugins=pylint_odoo --rcfile=<file> <path>`.
  The `--rcfile` is not optional — the repository root ships no `.pylintrc`,
  and the ones found under vendored trees belong to those projects.

### 5. Verify

Verification is entirely local: `.github/` holds no workflow, so nothing
catches a mistake after the fact.

**Repository scripts** — `make test_unit` is the fast gate: no PostgreSQL, no
Odoo, no VM, a few seconds. While iterating on one file, `make test_unit_file
F=test/test_<name>.py`.

A new file in `test/` must declare at least one `test_*` function and end with
`if __name__ == "__main__": unittest.main()` as the LAST top-level statement —
the suite has its own test that enforces both, since the runner selects files
by the glob `test/test_*.py`. A test that creates a real machine, installs a
system or runs for hours goes in `long_test/` instead, and undoes itself with
`--detruire`.

**An Odoo module** — drop the database, then run the module's tests:

```bash
./odoo_bin.sh db --drop --database test_<module>
./test.sh -d test_<module> --db-filter test_<module> -i <module>
```

`./test.sh` is `./run.sh` with `ODOO_MODE_TEST=true --workers 0`, which adds
`--test-enable --no-http --stop-after-init`. For coverage, bracket that with
`./.venv.erplibre/bin/coverage erase` before and a combine/report after, and
set `ODOO_MODE_COVERAGE=true` — coverage is switched on through the
environment, never a CLI flag. `make open_test_coverage` opens the report.

To run ONE test file inside a module, install the module first, then pass
`--test-file=`.

### 6. Then, and only then, commit

`make format`, the tests above, then `/commit` — which resolves the model,
writes the `[TYPE] portée : sujet` subject under 72 characters, the bilingual
body under ten lines per language, and the `Assisted-by:` trailer. The
`commit-msg` hook REFUSES a message that breaks the mechanical part of that;
the `pre-commit` hook only reports comments worth rereading and never blocks.

Stage by naming files. `git add -A` sweeps in `private/` and `tasks/`, which
are untracked on purpose.
