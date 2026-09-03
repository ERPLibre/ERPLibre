---
name: todo_plan_max
description: "Plan a todo.py command at maximum effort: questions first, superpowers when installed, then the specification /todo_add_command implements."
disable-model-invocation: true
effort: max
allowed-tools:
  - Bash(claude plugin list:*)
  - Bash(claude plugin marketplace list:*)
  - Bash(grep:*)
  - Bash(sed:*)
  - Bash(ls:*)
  - Bash(git log:*)
  - Read
  - Glob
  - Grep
  - Write
---

## Context

- Existing menus: !`grep -n "def prompt_execute" script/todo/todo.py`
- Menu sections in todo.json: !`python3 -c "import json;print(*json.load(open('script/todo/todo.json')),sep='\n')"`
- Installed plugins: !`claude plugin list`
- Last commits on the menu: !`git log --oneline -8 -- script/todo/`

## Task

Plan ONE command for the `script/todo/todo.py` menu, at the effort tier this
file pins. Planning is the whole job: this command produces a specification
and writes no menu code. `/todo_add_command` implements what comes out.

### The effort tier

The `effort: max` above applies to this invocation and to it alone.

Two other levers exist, and they are the user's to pull, not yours. `/effort
ultracode` PINS ultracode for the rest of the session — every substantive task
then goes through the Workflow tool, and an interactive terminal releases the
pin with `/effort high`. The bare keyword `ultracode` in a typed prompt opts in
that ONE turn. Say which of the two would serve, and let the user type it;
never claim a pin that is not shown as on.

Invoking this command is itself an explicit opt-in to multi-agent
orchestration, so the Workflow tool is available here without any further ask.
Reach for it when the plan genuinely has independent dimensions to explore in
parallel — several candidate designs, or a survey of how the existing menus
already solve the problem. A single obvious entry does not need one, and a
workflow spawned for it burns tokens the user is paying for.

### 1. Ask before planning

Ask with the question tool, never as prose the user has to answer in a
paragraph. Ask ONLY what changes the plan — a question whose every answer
leads to the same design is noise, and four is the ceiling per round.

What usually forks the design, in this repository:

- **Which menu.** Git, Code, Database, Config, Network, Process, Test, Update,
  Run, Doc, Security — the parent decides who finds the entry.
- **Pattern A or B.** A hard-coded method when the entry prompts, branches or
  reads state; a `todo.json` entry when it is one bash command or one make
  target. Guessing wrong costs a rewrite, not an edit.
- **What it does on failure.** An entry that stops at the first error, one that
  carries on and reports at the end, and one that asks before each step are
  three different features wearing one name.
- **Whether it destroys anything.** A command that drops a database, deletes a
  VM or overwrites a file needs a confirmation prompt and a name typed in full;
  the repository already writes them that way.
- **Whether it touches customer data.** Only `private/` may hold it. If the
  answer is yes, the plan says where the data lives and what never leaves it.

Take the answers as given. When one contradicts what the code does, say so in
a sentence and plan what was asked for.

### 2. Plan with superpowers when it is installed

Read the context block above. When `superpowers` appears among the installed
plugins, use it: its brainstorming skill for the design, its subagent-driven
development and code-review skills for the shape of the work, its systematic
debugging skill when the entry wraps something that already misbehaves.

When it is absent, say so in one line and plan without it — plan mode, the
repository's own conventions, and the menus already written. Do not install it
from here: `TODO › Execute › GPT code › Plugins Claude Code` carries the
ERPLibre list and the install is the user's decision, not a side effect of
asking for a plan.

### 3. Read what already exists

A menu of this size has almost always solved the problem next door. Before
designing anything, find the two or three closest entries and read them —
`grep -n "def prompt_execute" script/todo/todo.py` for the parents, then the
private methods under them. Copy the shape that is there: the same
confirmation prompt, the same `t()` keys, the same way of running a command.
An entry that behaves like its neighbours needs no explaining.

### 4. What the plan contains

Write it to `tasks/todo.md` — `tasks/` is not versioned, which is why the
convention sends working material there — as checkable items, and state:

- the parent menu and the position of the entry in it;
- pattern A or B, and why the other was rejected;
- the exact i18n keys, with their French and English text, both mandatory;
- for pattern A, the method name and its signature; for pattern B, the
  `todo.json` section and the command line;
- what the entry prints on success and on failure, and every confirmation it
  asks for;
- how to verify it: the syntax checks, the unit test to add under `test/`, and
  what to run by hand. A real machine goes to `long_test/`, never to `test/`,
  which stays runnable in seconds.

Then stop and hand it over. The plan is checked before code is written — that
is the whole point of planning at this tier. When it is approved,
`/todo_add_command` implements it.
