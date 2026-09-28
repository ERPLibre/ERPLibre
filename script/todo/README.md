
TODO is an assistant robot to use ERPLibre
Execute it with `./script/todo/todo.py` or `make todo`.

For a new project, copy todo_example.json to private/todo/todo_override.json | private/todo/todo_override_private.json and edit it.

The `mail/` package is the mail client reachable from `Assistant > Mail`:
several IMAP/SMTP accounts, a local cache, and a Textual TUI. See
[../../doc/EMAIL.md](../../doc/EMAIL.md).

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

## Web interface and desktop window

TODO also runs in a browser page or in a desktop window, served by a local
hub, one per checkout, under the user's account. Each web session is the real
TODO in a terminal of its own: menus and questions become buttons and fields,
and the terminal still answers everything.

- Open: TODO › [4] Navigation telemetry › [2] WEB, or `make todo_web`. The
  page opens in the browser, and its one-time link is also printed in the
  terminal; without a display, TODO prints the SSH tunnel to run from the
  workstation.
- Stop: [4] › [3], or `make todo_web_stop`. The hub also stops by itself
  after 30 minutes with no session and no request.
- Desktop window: [4] › [4], or `make todo_desktop`, opens the same page in a
  native window (pywebview, not installed by default: TODO prints the
  commands to install it).
  `make todo_desktop_install` adds an ERPLibre TODO entry for this checkout
  to the desktop's application menu.
- File picker: when a command asks for a file or a directory, the page shows
  a picker, and the desktop window also offers the system's file dialog.
- Task logs: each task run in a web session is kept 30 days under
  `~/.erplibre/todo_web/`, 0600, secrets masked; `make todo_web_purge`
  removes those older than 30 days.
- Source: the footer of the page offers its source, as section 13 of the
  AGPL asks.

Security model:

- the hub listens on 127.0.0.1 only;
- a login is a one-time code, valid 120 s, carried by the fragment of the
  link, never by a command line;
- the session cookie bears the hub's port in its name, `HttpOnly` and
  `SameSite=Strict`, and every write carries a CSRF token;
- every write and every WebSocket must come from the exact Origin of the
  page;
- the hub refuses to run as root: sudo stays per command, on the terminal
  of the session.

Limits: 3 sessions at once; at most 5 new sessions per minute; a login lasts
12 hours, and 16 live at once. Refused login codes count against no limit: a
good code is always accepted. A ▶ launch refused by the limit has already
closed the idle session it was to replace; the page shows the wait in seconds
at the refusal, without counting it down.

