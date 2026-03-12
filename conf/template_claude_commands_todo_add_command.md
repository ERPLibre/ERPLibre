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

## Architecture Reference

### Files to modify

| File | Role |
|------|------|
| `script/todo/todo.py` | Main CLI — menu methods, business logic |
| `script/todo/todo_i18n.py` | Translations dict `TRANSLATIONS` with `"fr"` and `"en"` keys |
| `script/todo/todo.json` | Config-driven entries (optional, for `bash_command` or `makefile_cmd`) |

### Pattern A — Hardcoded menu entry (interactive logic)

Used when the command needs Python logic (user prompts, conditionals, API calls).

1. **Add i18n keys** in `todo_i18n.py` `TRANSLATIONS` dict:
```python
"my_feature_description": {
    "fr": "Description en français",
    "en": "English description",
},
```

2. **Add choice** in the parent menu method (e.g. `prompt_execute_git`):
```python
choices = [
    ...,
    {"prompt_description": t("my_feature_description")},
]
```

3. **Add elif branch** in the same menu's while loop:
```python
elif status == "N":
    self._my_feature()
```

4. **Add method** to the `TODO` class:
```python
def _my_feature(self):
    # Implementation here
    pass
```

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

- i18n keys: `snake_case`, grouped by section with a comment header
- Method names: `_private_method` for actions, `prompt_execute_*` for submenus
- All user-facing strings must use `t("key")` — never hardcoded text
- Use `self.execute.exec_command_live(cmd, source_erplibre=False)` to run bash
- Use `input(t("prompt_key")).strip()` for user input
- Use `click.prompt(help_info)` for menu navigation
- Menu methods return `False` on back, use `self.fill_help_info(choices)` for formatting

## Task

Add a new command to the todo.py menu system. The user will describe what they want.

### Steps

1. **Determine the target menu section** from the user's description
2. **Choose Pattern A or B** based on complexity:
   - Simple bash/make command → Pattern B (todo.json entry)
   - Needs user interaction or logic → Pattern A (hardcoded method)
3. **Add i18n translations** in `todo_i18n.py` — always both `"fr"` and `"en"`
4. **Implement the feature** following the appropriate pattern
5. **Validate syntax**:
   ```bash
   python3 -m py_compile script/todo/todo.py
   python3 -m py_compile script/todo/todo_i18n.py
   python3 -c "import json; json.load(open('script/todo/todo.json'))"
   ```

### Rules

- Keep menu numbering sequential — update all `elif` branches if inserting
- Group i18n keys with a `# Section name` comment
- Match existing code style (Black, 79 char lines for Odoo modules)
- Do not break existing menu entries or their numbering
- Test that `fill_help_info` and `execute_from_configuration` handle the new entry

## User Request

$ARGUMENTS
