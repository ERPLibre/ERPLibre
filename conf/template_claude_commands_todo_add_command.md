---
name: todo_add_command
description: "Add a new menu command to script/todo/todo.py with i18n support and optional todo.json entry."
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(python3 -m py_compile:*)
  - Bash(python3 -c:*)
---

## Context

- Current todo.py menu structure: !`grep -n "def prompt_execute" script/todo/todo.py | head -20`
- Current todo.json sections: !`python3 -c "import json; d=json.load(open('script/todo/todo.json')); print('\n'.join(d.keys()))"`
- Current i18n keys count: !`grep -c fr.: script/todo/todo_i18n.py`

## Planning first

`/todo_plan_max` plans one entry at maximum effort: it asks what forks the
design, uses the superpowers plugin when it is installed, and writes the
specification to `tasks/todo.md`. Both commands are deployed together by
`TODO › Execute › GPT code › Claude configs`. When such a specification
exists, implement it rather than re-deciding the design here.

## Architecture Reference

### Files to modify

| File | Role |
|------|------|
| `script/todo/todo.py` | Main CLI — menu methods, business logic |
| `script/todo/menus/<family>.py` | Declared menus of a family (`execute`, `git`, `main`, `run`): registry calls only |
| `script/todo/todo_i18n.py` | Translations dict `TRANSLATIONS` with `"fr"` and `"en"` keys |
| `script/todo/todo.json` | Config-driven entries (optional, for `bash_command` or `makefile_cmd`) |
| `test/test_todo_menu.py` | `RegistryCoherence` classes: where each entry of a declared menu leads |
| `test/todo_menu_golden.json` | Reference renders of the declared menus, written by `test/todo_menu_golden.py` |

### Pattern A — Declared menu entry (interactive logic)

Used when the command needs Python logic (user prompts, conditionals, API calls).

1. **Add i18n keys** in `todo_i18n.py` `TRANSLATIONS` dict; the key of a
declared entry is its English text:
```python
"My feature - What it does": {
    "fr": "Ma fonctionnalité - Ce qu'elle fait",
    "en": "My feature - What it does",
},
```

2. **Declare an `Entry`** in the parent menu, in its family's
`script/todo/menus/<family>.py` (e.g. `GIT` in `menus/git.py` for
`prompt_execute_git`). Its number is its place in the list: no `choices`
item, no `elif` branch.
```python
Entry("My feature - What it does", "_my_feature"),
```
`kwargs={"name": "literal"}` passes arguments to the method, and
`danger=True` marks an entry that runs as root or installs software: its
menu runs it, the navigation telemetry TUI and the web page do not. A menu
file holds registry calls with literal arguments, nothing else. A numbered
menu is always declared: `TestGuards` in `test/test_todo_ui_legacy.py`
refuses a menu loop numbered by hand in `script/todo/`, outside those
`NUMBERED_LOOPS` names, a list that only shrinks.

3. **Keep the menu method as it is**: the public method of a declared menu
stays `return navigate(self, menus_git.GIT)`. A new submenu is a `Menu(...)`
in the same file, opened by an `Entry` that names its method; that method is
`return navigate(self, menus_<family>.MY_MENU)`, and the `crumb` of the
`Menu` is its breadcrumb segment and its telemetry key: the navigator and
the telemetry tree read it there, and nowhere else.

4. **Add method** to the `TODO` class:
```python
def _my_feature(self):
    # Implementation here
    pass
```

5. **Extend the tests**: add the entry to `EXPECTED` of the family's
`RegistryCoherence` class in `test/test_todo_menu.py` (e.g.
`TestGitMenuNumbering`: `"My feature": "_my_feature"`), then rewrite the
reference renders with `PYTHONPATH=. .venv.erplibre/bin/python
test/todo_menu_golden.py`, which runs TODO under its own temporary HOME, and
check that the diff of `test/todo_menu_golden.json` only adds the new entry
and renumbers those after it. A new submenu also goes into `MENUS` of
`test/todo_menu_golden.py`.

### Pattern B — Config-driven entry (simple bash command)

Used when the command just runs a bash command or a make target.

1. **Add i18n key** in `todo_i18n.py` (use `prompt_description_key`).

2. **Add entry** in `todo.json` under the appropriate `*_from_makefile` section:
```json
{
    "prompt_description_key": "my_i18n_key",
    "bash_command": "my-command --flag"
}
```
Or for make targets:
```json
{
    "prompt_description_key": "my_i18n_key",
    "makefile_cmd": "my_make_target"
}
```

These are automatically picked up by `execute_from_configuration()`.

### Available menu sections

| Menu | Method | JSON key |
|------|--------|----------|
| Automation | `prompt_execute_function` | `function` |
| Code | `prompt_execute_code` | `code_from_makefile` |
| Config | `prompt_execute_config` | — |
| Database | `prompt_execute_database` | — |
| Doc | `prompt_execute_doc` | — |
| Git | `prompt_execute_git` | `git_from_makefile` |
| GPT code | `prompt_execute_gpt_code` | — |
| Network | `prompt_execute_network` | — |
| Process | `prompt_execute_process` | — |
| Run | `prompt_execute_instance` | `instance` |
| Security | `prompt_execute_security` | — |
| Test | `prompt_execute_test` | — |
| Update | `prompt_execute_update` | `update_from_makefile` |

### Key conventions

- i18n keys: the English text itself, grouped by section with a comment header
- Method names: `_private_method` for actions, `prompt_execute_*` for submenus
- All user-facing strings must use `t("key")` — never hardcoded text
- Use `self.execute.exec_command_live(cmd, source_erplibre=False)` to run bash
- Use `input(t("prompt_key")).strip()` for user input
- A declared menu is drawn and answered by `navigate`; [0] returns its `back`, `False` by default

## Task

Add a new command to the todo.py menu system. The user will describe what they want.

### Steps

1. **Determine the target menu section** from the user's description
2. **Choose Pattern A or B** based on complexity:
   - Simple bash/make command → Pattern B (todo.json entry)
   - Needs user interaction or logic → Pattern A (declared entry and method)
3. **Add i18n translations** in `todo_i18n.py` — always both `"fr"` and `"en"`
4. **Implement the feature** following the appropriate pattern
5. **Validate syntax**:
   ```bash
   python3 -m py_compile script/todo/todo.py
   python3 -m py_compile script/todo/todo_i18n.py
   python3 -c "import json; json.load(open('script/todo/todo.json'))"
   ```
6. **Run the menu tests**:
   ```bash
   PYTHONPATH=. .venv.erplibre/bin/python test/test_todo_menu.py
   PYTHONPATH=. .venv.erplibre/bin/python test/test_todo_menu_golden.py
   ```

### Rules

- A declared entry is numbered by its place: inserting one renumbers the following ones, and the reference renders show it
- Group i18n keys with a `# Section name` comment
- Match existing code style (Black, 79 char lines for Odoo modules)
- Do not break existing menu entries or their numbering
- Test that the new entry leads to its method (`EXPECTED`) and that `execute_from_configuration` handles a todo.json entry

## User Request

$ARGUMENTS
