
TODO is an assistant robot to use ERPLibre
Execute it with `./script/todo/todo.py` or `make todo`.

For a new project, copy todo_example.json to private/todo/todo_override.json | private/todo/todo_override_private.json and edit it.

The `mail/` package is the mail client reachable from `Assistant > Mail`:
several IMAP/SMTP accounts, a local cache, and a Textual TUI. See
[../../doc/EMAIL.md](../../doc/EMAIL.md).

## Session log

Each run writes a log under `~/.local/state/erplibre/todo/`
(`$XDG_STATE_HOME/erplibre/todo/` when set); TODO prints its path on entry
and on exit. It keeps the loggers' messages and, for every command TODO runs,
the command, its output and its exit code. Everything in it, log messages and
crash traceback included, goes through the masking the screen uses: secret
options and variables, configuration lines such as `admin_passwd = …`,
credentials in a URL, GitHub and GitLab tokens, JSON keys, `odoo-bin -w`,
`sshpass -p`, `curl -u` and private keys. Masking is a last line of defence,
not a guarantee: a secret printed in an unknown form stays, so the file is
private (0600, in a 0700 directory). What is typed at a prompt is not
recorded. The 30 most recent logs are kept; `ERPLIBRE_TODO_LOG=0` turns it
off.

## Where the code lives

`todo.py` carries the menus and the general helpers. Everything around a
single subject sits in its own file, and the whole thing is assembled by
mixins on the `TODO` class — one file, one subject, its header states its
boundary.

| File | What it owns |
|------|--------------|
| `todo.py` | the menus, the configuration, the general helpers |
| `qemu_menu.py` | the QEMU/KVM menu, the image catalogue, the statistics |
| `qemu_deploy.py` | deciding then running a deployment |
| `qemu_install.py` | the recipes run inside a VM |
| `qemu_manage.py` | lifecycle, disks, hardware, cleanup, addresses |
| `qemu_access.py` | SSH, tunnels, consoles, Android emulator |
| `proxmox_menu.py` | the same, on a REMOTE Proxmox VE host |

The two deployment forms — libvirt here, Proxmox over there — ask the same
questions, so they share a foundation rather than each holding a copy:

| File | What it owns |
|------|--------------|
| `deploy_form_lib.py` | pure logic (sizes, plan, totals, spec), the shared CSS, the resource-row factory, the progress view |
| `deploy_form_plan.py` | the plan's gestures: overrides, locks, copies, renaming, free values |
| `qemu_deploy_form.py` | what QEMU/KVM adds: desktops, tools, branches, install profiles |
| `proxmox_deploy_form.py` | what Proxmox adds: host, storage, bridge, VMID, address |

A form inherits `PlanMixin` and provides three hooks: which presets each
resource offers, the name a VM would fall back to, and what a lock freezes.
`test_todo_deploy_form_lib.py` fails if a form redefines a gesture the
foundation already carries — that is what keeps the architecture from drifting
back into two copies.

