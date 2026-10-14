# ERPLibre Home — Deployment and Multi-Distribution Validation

- **Status**: Draft
- **Date**: 2026-10-13
- **Author**: Mathieu Benoit (brainstormed with Claude)
- **Target**: `script/install/`, `script/stream_deck/`, `script/gnome-extension/erplibre_home/`, `conf/make.streamdeck.Makefile`, `script/todo/`, `long_test/`
- **Scope**: New installer, TODO entries, QEMU tool and profile, long test; small fixes to the existing Stream Deck code and to `long_test/descente.py`

## 1. Goals

The Stream Deck code (deck controller, games, gallery, translator, tiler)
and the ERPLibre Home GNOME extension live in the repository, but nothing
installs them and nothing proves they run. The setup steps are spread over
`INSTALL.md` (Ubuntu only), Makefile targets that swallow errors, and an
extension that expects the full ERPLibre venv.

This spec delivers:

1. **One installer**, `script/install/install_erplibre_home.sh`, that sets up
   ERPLibre Home on every supported distribution, without Odoo, with the
   Stream Deck programs in their own venv.
2. **The GNOME extension enabled**. "Enabled" means *ACTIVE in a running
   session*: GNOME Shell's `GetExtensionInfo` reports state `1` and an empty
   `error`. Being listed in `enabled-extensions` is not enough.
3. **TODO entries**: a local install in the Stream Deck section, an
   `erplibre_home` tool in the QEMU tools catalog, and an "ERPLibre Home
   (no Odoo)" install profile for QEMU VMs.
4. **A long test**, `long_test/install_erplibre_home.py`, that creates a real VM
   per distribution version, installs ERPLibre Home from the local checkout,
   logs a user into GNOME and checks that the extension is ACTIVE.

### Non-goals

- Physical deck I/O inside the VM. No USB device is passed through. The test
  proves that the software is installed and running, not that a key press
  reaches a game.
- Configuring autologin on the user's machine. Only the long test sets it up,
  and only inside its own VMs.
- Supporting GNOME 52 or later. `metadata.json` declares 45–51. Adding a
  version is a separate change, and the long test reports when one is needed.
- arm64, s390x, ppc64le. Only amd64 is in scope.

## 2. Support matrix

The extension declares `shell-version` 45 to 51. A distribution version is in
scope when it is amd64, ships GNOME 45–51, and offers a GNOME desktop path in
`_qemu_erplibre_remote_cmd(desktop="gnome")`.

| Distribution | Keys (`--distro:--version`) | Expected GNOME | Expected verdict |
|---|---|---|---|
| Ubuntu | `ubuntu:24.04`, `ubuntu:25.10`, `ubuntu:26.04` | 46, 49, 50 | ACTIVE |
| Debian | `debian:13` | 48 | ACTIVE |
| Fedora | `fedora:41` … `fedora:44` | 47 … 50 | ACTIVE |
| AlmaLinux | `almalinux:10` | 47 | ACTIVE |
| Rocky Linux | `rocky:10` | 47 | ACTIVE |
| openSUSE Leap | `opensuse:16.0` | 48 | ACTIVE |
| Arch Linux (rolling) | `arch:latest` | 51 | ACTIVE while GNOME ≤ 51, else UNSUPPORTED (shell version) |
| openSUSE Tumbleweed (rolling) | `opensuse:tumbleweed` | ≥ 50 | same as Arch |

The keys are the values `deploy_qemu.py` accepts, and the ones `--only` takes.

The "Expected GNOME" column is a claim, not a fact. The long test measures
`gnome-shell --version` on every VM and reports a mismatch. The table in the
script is corrected from those reports, and no reader has to trust this one.

Listed as unsupported, with no VM created:

| Distribution | Reason |
|---|---|
| `debian:12` | GNOME 43 < 45 (upstream release notes, not measured) |
| `almalinux:9`, `rocky:9` | GNOME 40 < 45 (upstream release notes, not measured) |
| `nixos:25.11` | no GNOME desktop path in the QEMU installer |
| `proxmox:9` | out of scope by choice: a hypervisor host. Its Debian 13 base would take the apt GNOME path, but a deck on a hypervisor is not a supported use |
| any arm64 / s390x / ppc64le | out of scope (amd64 only); s390x has no display |

## 3. Architecture

A single shell installer is the only place that knows how to install
ERPLibre Home. Everything else calls it:

```
TODO › Stream Deck › Install (local) ─────┐
make erplibre_home_install ───────────────┤
QEMU tool "erplibre_home" (in the VM) ────┼──► script/install/install_erplibre_home.sh
QEMU profile "ERPLibre Home (no Odoo)" ───┤
long_test/install_erplibre_home.py (VM) ──┘
```

Two alternatives were rejected:

- An installer written in Python inside TODO, plus a separate shell script for
  VMs. It duplicates the package table, and the two copies drift apart.
- Packages declared in cloud-init. This covers VMs only, does not cover a
  user's workstation, and cannot enable the extension.

### 3.1 Dedicated venv: `.venv.streamdeck`

The deck code imports `StreamDeck`, `PIL`, `cv2`, `pyudev`, `requests`
(`erplibre_controller.py`), `keyboard` (`keyboard_talk.py`) and `polib`
(`po/compile_locales.py`). `vosk` is optional: `translator.py` imports it
lazily and reports the backend unavailable without it. Nothing needs Odoo or
`.venv.erplibre`. A dedicated venv:

- installs in minutes instead of the hour an ERPLibre install takes;
- is created with the system `python3 -m venv`, with no pyenv, so it works the
  same on every distribution;
- lets the long test skip Odoo entirely.

**Entry points** call `.venv.streamdeck/bin/python` explicitly. Shebangs stay
`#!/usr/bin/env python3`, because a shebang cannot name a path relative to the
checkout. The entry points are:

| Entry point | Today | After |
|---|---|---|
| Makefile `streamdeck`, `streamdeck_<game>`, `streamdeck_gallery`, `streamdeck_tiler`, `streamdeck_translator_{doctor,test,stream}`, the `translator_doctor.py --recommend` call of `streamdeck_translator_install_ollama` | `./script/stream_deck/<x>.py` (shebang) | `$(STREAMDECK_PY) script/stream_deck/<x>.py` |
| Makefile `streamdeck_translator_unittest`, `streamdeck_tiler_unittest` | `python3 -m unittest` | `$(STREAMDECK_PY) -m unittest` |
| Makefile `streamdeck_translator_install_vosk_fr` | `pip install --user vosk` (invisible to a venv) | `$(STREAMDECK_PY) -m pip install vosk` |
| Makefile and installer, `po/compile_locales.py` | `python3` | `$(STREAMDECK_PY)` |
| `gallery_server.py` game launcher | `python3 {game_file}` in a terminal | `{shlex.quote(sys.executable)} {game_file}` (the server already runs under the venv) |
| `todo.py` `prompt_execute_streamdeck_games` | `<game>.py` by shebang | `.venv.streamdeck/bin/python <game>.py` |
| `indicators/device.js` `_launchController` | `.venv.erplibre/bin/python` | `.venv.streamdeck/bin/python` |
| `indicators/controller.js` gallery launcher | `source .venv.erplibre/bin/activate && make streamdeck_gallery` | `make streamdeck_gallery` (the target picks the venv) |

`script/stream_deck/launch_game.sh` is referenced by nothing; it is removed.

`STREAMDECK_PY` is defined at the top of the Makefile fragment as
`.venv.streamdeck/bin/python`. A target whose venv is missing stops with a
message that names `make erplibre_home_install`.

**These keep `.venv.erplibre` on purpose.** They run ERPLibre's own tools, not
the deck's:

- `game_tiler.py`, which opens `script/todo/todo.py`;
- `indicators/erplibre.js`, which runs `make` targets of an instance and the
  selenium login.

On an ERPLibre Home install without Odoo they degrade as they do today, and this series
does not change them: the selenium login notifies and falls back to `xdotool`;
`game_tiler.py` runs `todo.py` with the system `python3`; the ERPLibre
indicator's TODO terminal shows the shell's error.

The `.po` and `.pot` strings `Python venv not found at .venv.erplibre` change
to name `.venv.streamdeck`, and the catalogs are recompiled.

### 3.2 Extension path resolution

`make erplibre_home_install_extension` creates a symlink:
`~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca` →
`<checkout>/script/gnome-extension/erplibre_home`. GNOME Shell reports
`extension.path` as the symlink path. `device.js` `_projectRoot()` strips
`/script/gnome-extension/erplibre_home` from that path, which fails on the
symlink path, so the controller launcher looks for the venv in the wrong
place.

The symlink stays, because it keeps the edit-then-reload loop. The hot-reload
copy (`erplibre-home-reload-*`) is a symlink to the checkout too.

A new `lib/project-root.js` exports a pure
`projectRootFrom(path, readLink)`:
- `readLink(p)` returns the symlink target of `p`, or `null` when `p` is not a
  symlink;
- a relative target is resolved against the link's parent;
- the `/script/gnome-extension/erplibre_home` suffix is stripped from the
  resolved path; a path that is not a symlink gives the same result as today.

The GJS caller passes a `readLink` built on
`Gio.File.query_info('standard::symlink-target', NOFOLLOW_SYMLINKS)`. Gio is
injected or imported dynamically, never statically, so that `node --test` can
load the module, as `badges.js` and `erplibre-detect.js` already do.

It serves `device.js` `_projectRoot()` and the fallback branch of
`erplibre.js` `_autoLoginSelenium` (after the `git-sync-path` setting).
`controller.js` is untouched: it runs in a path taken from its settings.

## 4. The installer: `script/install/install_erplibre_home.sh`

```
install_erplibre_home.sh [--no-enable] [--extension-only] [--with-extras] [--uninstall] [--dry-run]
```

The installer:

- runs as the user, from the checkout root, and calls `sudo` only for system
  packages and the udev rule;
- refuses to run as root, because the venv, the extension and gsettings belong
  to the user;
- uses `set -euo pipefail`;
- is idempotent: a second run changes nothing and exits 0.

**Exit codes:**
- `0`: installed.
- `2`: unsupported system. The reason goes on stderr on one line that starts
  with `UNSUPPORTED:`.
- `1`: any other failure.

### 4.1 Steps

1. **Pre-checks.**
   - Read `/etc/os-release` and map it to a family, `debian`/`rhel`/`suse`/`arch`.
     The `detect_os`/`family` logic is the one in `install_vpn.sh`. It is copied,
     not sourced, because `install_vpn.sh` runs as root and calls `die` with its
     own wording.
   - NixOS and macOS exit 2.
   - Read `gnome-shell --version`. No gnome-shell exits 2 (`no GNOME Shell`).
   - Read the accepted versions from `metadata.json` `shell-version` with
     `python3 -c 'import json…'`, never from a list in the script. A major
     version outside that list exits 2 (`GNOME <v> not in shell-version`).
   - `ERPLIBRE_HOME_OS_RELEASE` and `ERPLIBRE_HOME_GNOME_VERSION` override the two
     reads, so the unit tests can run them without a VM.
2. **System packages**, from the table in 4.2, with the family's package
   manager in non-interactive mode. Already installed packages are skipped by
   the package manager itself.
3. **udev rule.** Write `/etc/udev/rules.d/70-streamdeck.rules`, compared with
   the existing file before it is replaced:
   ```
   SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
   KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
   ```
   Then run `udevadm control --reload-rules && udevadm trigger`.
   - `uaccess` grants the logged-in seat user access on every family.
   - The `plugdev` group of the current `INSTALL.md` exists on Debian and
     Ubuntu only.
   - The `70-` prefix orders the rule before `73-seat-late.rules`, which is
     where `uaccess` is applied.
4. **venv.** `python3 -m venv .venv.streamdeck` if it is absent, then
   `.venv.streamdeck/bin/pip install -r script/stream_deck/requirements.txt`.
5. **Extension.**
   - Create the symlink as in 3.2.
   - Run `glib-compile-schemas --strict` on `schemas/`. A failure fails the
     install.
   - Run `po/compile_locales.py` with the venv's python. A failure fails the
     install too, since `polib` is now guaranteed by the venv.
6. **Enable** (skipped with `--no-enable`).
   - Add the UUID to `org.gnome.shell enabled-extensions`, without duplicating
     it.
   - Remove the UUID from `org.gnome.shell disabled-extensions`, which wins
     over `enabled-extensions` when an extension was once turned off in the
     Extensions app.
   - Set `org.gnome.shell disable-user-extensions` to `false`.
   - Write with `gsettings` on the session bus: `DBUS_SESSION_BUS_ADDRESS`
     when set; else `/run/user/<uid>/bus` when that socket exists (an ssh
     session beside an open GNOME session, whose dconf service would
     otherwise overwrite the write); else under `dbus-run-session --` (a fresh
     VM, no session). The last case is the bus guard of the `gnome_ext`
     tool's `gx()` wrapper. That wrapper runs `gnome-extensions` and ignores
     failures; the installer instead reads the keys back and fails if they
     did not take.
   - Also run `gnome-extensions enable` when a session bus with
     `org.gnome.Shell` is reachable. It does nothing otherwise.
   - Every step checks before it writes: an existing correct symlink, rule or
     venv is left untouched, which is what makes a second run a no-op.
7. **Summary.** Print what was done, and: "log out and back in: GNOME Shell
   loads a new extension only at session start under Wayland".

### 4.2 System packages

| Role | apt | dnf | zypper | pacman |
|---|---|---|---|---|
| hidapi + libusb | `libhidapi-libusb0 libusb-1.0-0` | `hidapi libusb1` | `libhidapi-libusb0 libusb-1_0-0` | `hidapi libusb` |
| venv | `python3-venv` | `python3` | `python3` | `python` |
| schemas | `libglib2.0-bin` | `glib2` | `glib2-tools` | `glib2` |
| gettext | `gettext` | `gettext` | `gettext-tools` | `gettext` |
| window control | `wmctrl` | `wmctrl` | `wmctrl` | `wmctrl` |

- On AlmaLinux and Rocky Linux, `wmctrl` comes from EPEL. The installer
  enables EPEL (`dnf install -y epel-release`) only on those two.
- `opencv-python` ships manylinux wheels for amd64, and needs no system
  package.
- The spike confirms each name. A wrong name fails the install, which is what
  the long test is for.

`--with-extras` adds the optional tools used by the indicators: `mpv`,
`yt-dlp`, `nmap`, `keepassxc`, `xdotool`, and the Python `lz4` module as a
system package (`python3-lz4` on apt, dnf and zypper, `python-lz4` on pacman).
The Firefox tab importer runs under the system `python3` from `prefs.js`, so
`lz4` in the venv does not serve it; `lz4` leaves `requirements.txt`. A
missing extra package is reported and skipped, never fatal: these features
already degrade without them.

### 4.3 Uninstall

`--uninstall`:
- removes the UUID from `enabled-extensions`;
- removes the extension symlink, the udev rule and `.venv.streamdeck`;
- never removes system packages, because other software may use them.

### 4.4 Dry run

`--dry-run` prints, one per line, what the steps would do:
- the family;
- the GNOME version and its verdict;
- the package command;
- the files it would write.

It changes nothing and calls no `sudo`. This is the unit-test surface.

### 4.5 Prerequisite fixes

These go in the same series, before the installer:

- `requirements.txt`: add `requests` and `keyboard`, and drop `lz4` (see 4.2).
  `erplibre_controller.py` imports `requests` at the top level, so today the
  controller does not start on a fresh venv; `keyboard_talk.py` imports
  `keyboard`.
- `make.streamdeck.Makefile`, in `erplibre_home_install_extension`:
  - drop the `2>/dev/null || true` after `glib-compile-schemas`;
  - delegate the symlink, schema and locale work to
    `install_erplibre_home.sh --extension-only`, which runs step 5 alone, with no
    `sudo` and no OS check;
  - keep the recipe's first line, `tools/migrate_legacy.py`, which moves a
    workstation off the extension's former identity: it runs under the
    system `python3`, before any venv exists, and always exits 0;
  - one implementation, so `make` and the installer cannot disagree.
- New targets `erplibre_home_install` and `erplibre_home_uninstall`. The new
  `erplibre_home_uninstall` replaces the alias of
  `erplibre_home_uninstall_extension` that carried the name.
- `INSTALL.base.md`: replace the Ubuntu-only block with
  `make erplibre_home_install`, keep the per-family table for reference, and
  regenerate with mmg.

## 5. TODO integration

### 5.1 Local install

The Stream Deck section of `Execute` gets an entry, "Install ERPLibre Home
(local)", next to "[17] Games".
- It runs `./script/install/install_erplibre_home.sh` live, with
  `exec_command_live`.
- Exit 2 shows the `UNSUPPORTED:` reason, not a stack of errors.
- i18n keys are in `todo_i18n.py`, in French and English.
- `test/test_todo_menu.py` `EXPECTED` gets the new entry.

### 5.2 QEMU tool `erplibre_home`

A new entry in `_QEMU_VM_TOOLS`, next to `gnome_ext`:

```python
"erplibre_home": {
    "label": "ERPLibre Home",
    "help": (
        "script/install/install_erplibre_home.sh in the VM's checkout",
        "system packages, udev rule, .venv.streamdeck, extension enabled",
        "log out and back in to load the extension",
    ),
    "hint": "deck controller, games, GNOME extension",
    "disk_gb": 2,
    "arches": ("amd64",),
    "desktops": ("gnome",),
    "needs_desktop": True,
    "families": ("apt", "dnf", "pacman", "zypper"),
    "phase": "after",
}
```

- `label`, `hint` and every `help` line get French and English keys in
  `todo_i18n.py`; `test_deploy_form_help` requires a non-empty `help`.
- Its block is added to `_qemu_after_remote_cmd`'s dispatch. It runs
  `install_erplibre_home.sh` in the VM's checkout, chained with `&&`, so a failure
  makes the VM red. This adds ERPLibre Home on top of any install profile.

### 5.3 Install profile "ERPLibre Home (no Odoo)"

The command run after the clone is the install profile the user picks, from
`_qemu_install_profiles`. No tool changes it. A new profile, next to
"ERPLibre mobile (home)", installs ERPLibre Home alone:

```python
(t("ERPLibre Home (no Odoo)"), "./script/install/install_erplibre_home.sh"),
```

- The desktop is installed before the profile command, so the installer finds
  `gnome-shell`.
- The profile does not run `make install_os`: the installer brings its own
  packages, and the VM is ready in minutes.
- Ticking the `erplibre_home` tool with this profile runs the installer twice;
  the second run is a no-op.
- The profile's French and English labels go in `todo_i18n.py`.

## 6. Long test: `long_test/install_erplibre_home.py`

It follows the pattern of `long_test/install_nixos.py`: the constants
`DELAI_SSH`, `DELAI_INSTALL`, `DELAI_HTTP`, and the helpers `adresse_de`,
`ssh_base`, `attendre_ssh`, `sonder`. `creer_vm` is re-implemented with
parameters (distro, version, desktop, GPU, size), since the original hardcodes
NixOS. Unlike `install_nixos.py`, it passes `drapeaux_cache()` to
`deploy_qemu.py`, so a host with the QEMU image cache uses it.

**Report contract**, as `descente.dernier_rapport` and `detruire` read it:
- `"outil": "install_erplibre_home"`, `"dry_run"`, `"pid": os.getpid()`;
- `"etages"`: one `{"niveau": 1, "nom", "uuid", "alias", "cree": true}` per
  VM still alive;
- `systemes` is an extra key, ignored by `descente.py`.

The live-run guard is `pid` plus the script's basename in `descente.SCRIPTS`.
`install_erplibre_home.py` is added to `descente.SCRIPTS` and to
`longtest_menu.SCRIPTS_DEFAISABLES`; a test keeps the two lists equal.

`descente.detruire` undoes only the first `niveau == 1` entry today. It is
extended to undo every `niveau == 1` entry, so that `--detruire` cleans up
every VM kept by `--garder` or left by a crash. The `deep_*` tests write one
such entry, and keep their behaviour.

Per-system logs are `.log` files in a sub-directory of the run, so
`dernier_rapport` never reads them as reports.

### 6.1 Interface

```
./long_test/install_erplibre_home.py                 # the whole matrix
./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
./long_test/install_erplibre_home.py --extras        # also run --with-extras on Ubuntu 24.04
./long_test/install_erplibre_home.py --dry-run       # print the plan, create nothing
./long_test/install_erplibre_home.py --garder        # keep the VMs for inspection
./long_test/install_erplibre_home.py --detruire      # undo the last run
```

### 6.2 Per-VM flow

VMs run one at a time. Each VM is destroyed before the next is created, unless
`--garder` is given.

1. **Source** (once per run).
   - Refuse to start when `git status --porcelain` is not empty: the test
     installs what HEAD holds, and a dirty tree would test something else.
   - Otherwise write `git bundle create <run>/erplibre_home.bundle HEAD`.
2. **VM.** Run `deploy_qemu.py` under sudo with:
   - `--distro <d> --version <v> --name <n> --desktop --gpu off`;
   - `--vcpus 2 --memory 4096` (MiB) `--disk-size 26G`;
   - `--ssh-key <public key>` (`descente.cle_publique()`) and
     `drapeaux_cache()`.

   As soon as the VM exists, its `etages` entry is written to the report.

   The test sizes the VM itself: `deploy_qemu.py` adds nothing for a desktop.
   `--gpu off` is the most constrained case, software rendering, so a pass
   holds on hosts without a render node.
3. **Desktop.** Run, over ssh in one session, the script
   `_qemu_erplibre_remote_cmd(branch=None, desktop="gnome")` returns. This is
   the desktop-only path: no clone, no Odoo. It keeps the menu's proven
   cloud-init wait and GNOME install. It also installs the remote-desktop
   server and disables automatic upgrades, as for any desktop VM.
4. **Code.**
   - Install `git` with the family's package manager: the desktop-only path
     does not run the `curl git make` bootstrap, and minimal cloud images ship
     without git.
   - `scp` the bundle.
   - `git clone <bundle> ~/git/erplibre`.
   - `git -C ~/git/erplibre checkout <HEAD sha>`.

   The VM never reaches GitHub for the code.
5. **Install.** Run `./script/install/install_erplibre_home.sh` and record its exit
   code and its output.
   - Exit 2 gives the verdict `UNSUPPORTED(<reason>)`. On Arch and Tumbleweed
     this means GNOME moved past 51, and it is the expected signal to update
     `metadata.json`.
   - Exit 1 gives `FAILED(install)`.
6. **Autologin**, test-only. Write the display manager's autologin for the VM
   user:

   | Family | File | Keys |
   |---|---|---|
   | debian | `/etc/gdm3/custom.conf` | `[daemon] AutomaticLoginEnable=true`, `AutomaticLogin=<user>` |
   | rhel, arch | `/etc/gdm/custom.conf` | same |
   | suse | `/etc/sysconfig/displaymanager` | `DISPLAYMANAGER_AUTOLOGIN="<user>"` |

   Then reboot the VM and wait for ssh again.
7. **Checks**, over ssh, each with its own timeout. The first failure gives
   `FAILED(<check>)`, and later checks are skipped.

   | Check | Command / condition | Timeout |
   |---|---|---|
   | `session` | `/run/user/$UID/bus` exists and `org.gnome.Shell` is on it (`gdbus call … org.freedesktop.DBus.NameHasOwner`) | 300 s |
   | `gnome-version` | `gnome-shell --version`, recorded and compared with the matrix | — |
   | `extension-active` | `GetExtensionInfo erplibre-home@technolibre.ca`: `state` is `1` and `error` is empty. **Main verdict.** | 120 s |
   | `extension-dbus` | the extension's own `ListPaths` and `ListDevices` answer. The object is exported before `getSettings()`, and stays exported when `enable()` throws later, so a method that touches neither settings nor indicators (`GetMonitorGeometry`) proves nothing. `ListPaths` reads the settings. `ListDevices` answers `[]` both when no deck is plugged in and when the device indicator never mounted, so its answer does not prove the indicator; `extension-indicators` checks that. | 30 s |
   | `extension-indicators` | the session journal (`journalctl --user -b -o cat`) holds the `[ERPLibreHome] enabled` line that ends `enable()`, and no `[ERPLibreHome] mount <id> failed` line. A journal without the enabled line fails the check: an ssh failure or an empty journal must not read as "no failed mount". The extension keeps running when an indicator's constructor throws, so ACTIVE and the D-Bus answers do not prove the panel is whole: under a Shell API break every indicator can fail while `GetExtensionInfo` still reports ACTIVE. | 30 s |
   | `venv` | `.venv.streamdeck/bin/python -c 'import StreamDeck, pyudev, PIL, cv2, requests'` | 60 s |
   | `udev` | `/etc/udev/rules.d/70-streamdeck.rules` contains `uaccess` and `0fd9` | — |
   | `idempotent` | a second `install_erplibre_home.sh` exits 0, and leaves the rule, venv and symlink with unchanged mtimes | install timeout |
   | `reinstall` | `--uninstall`, then install, reboot, `extension-active` and `extension-indicators` again | install timeout |

   The session-bus commands run with
   `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.
8. **On failure**, attach to the report:
   - `journalctl --user -b | grep -i -e erplibrehome -e erplibre-home -e gnome-shell` (last 200
     lines);
   - `gnome-extensions info erplibre-home@technolibre.ca`;
   - the installer's output.

### 6.3 Report

The report follows the `descente.py` contract, and adds one entry per system
under a `systemes` key:

```json
{"distro": "fedora", "version": "43", "gnome_attendu": "49",
 "gnome_mesure": "49.1", "verdict": "ACTIVE", "etape": null,
 "duree_s": 1840, "journal": "fedora-43.log"}
```

- `verdict` is one of `ACTIVE`, `FAILED`, `UNSUPPORTED`.
- `etape` names the failed check or the reason.
- The unsupported systems of section 2 appear with `UNSUPPORTED` and no VM.
- Between systems, the VM is destroyed in-process with
  `descente.detruire_etage1` and `retirer_alias`, never with `detruire()`,
  which prompts. The report's `etages` is then rewritten with the VMs still
  alive.
- The run ends with a summary table on stdout.
- The exit code is `0` when every in-scope system is ACTIVE, or UNSUPPORTED
  where the matrix allows it (Arch, Tumbleweed). It is `1` otherwise.

### 6.4 TODO access and README

- Two entries in `TODO › Execute › Test › Long tests` (`longtest_menu.py`):
  plan only, and run. They have their own dispatch branch, which passes no
  `--depth`. The undo entry is renumbered. The existing tests
  `test_every_listed_choice_has_a_branch` and
  `test_the_two_copies_of_the_list_agree` stay green.
- The script accepts `--detruire --dry-run`.
- A section in `long_test/README.base.md`, regenerated with mmg.

## 7. Error handling summary

| Situation | Behaviour |
|---|---|
| Unsupported OS or GNOME version | installer exit 2, one `UNSUPPORTED:` line; TODO shows it; long test verdict UNSUPPORTED |
| Package missing from a repository | installer exit 1, package manager output shown |
| Extra package missing (`--with-extras`) | warning, install continues |
| Schema does not compile | installer exit 1 |
| Run as root | installer exit 1, "run as your user" |
| Dirty working tree | long test refuses to start |
| VM creation or ssh timeout | `FAILED(vm)` / `FAILED(ssh)`, next system |
| Extension enabled but in ERROR | `FAILED(extension-active)`, with the `error` text and the journal |
| An indicator failed to mount | `FAILED(extension-indicators)`, with the journal lines |
| `enabled-extensions` not written | installer exit 1 (the key is read back) |

## 8. Testing

**Unit tests** (`test/`, seconds, no VM):

- `test_install_erplibre_home.py`:
  - `--dry-run` with fake `os-release` files for Ubuntu, Debian, Fedora,
    AlmaLinux, openSUSE Leap, Arch and NixOS;
  - the family, the package command, and exit 2 for NixOS;
  - exit 2 for a GNOME version outside `shell-version`;
  - refusal as root;
  - `bash -n`.
- `test_longtest_install_erplibre_home.py`:
  - the dry-run plan (systems, unsupported lines, VM sizing);
  - parsing of recorded `gdbus` outputs for ACTIVE, ERROR, OUT_OF_DATE and an
    absent extension;
  - parsing of the session journal: the `[ERPLibreHome] enabled` line
    must be present, or the journal counts as unread and the check fails;
    `[ERPLibreHome] mount <id> failed` lines give the ids of the
    indicators that did not mount;
  - the autologin file and keys per family;
  - the report contract read by `descente.py`;
  - the dirty-tree refusal.
- `test_todo_menu.py`: the new ERPLibre Home entry.
- the `longtest_menu` test: the new long test entry.
- The QEMU tool and profile:
  - the `erplibre_home` key is in the catalog, with its translations;
  - its after-phase block calls the installer, chained with `&&`;
  - the "ERPLibre Home (no Odoo)" profile is listed and runs the installer.
- GNOME extension (`make test_gnome_extension`, which runs `node --test`):
  `projectRootFrom` with a stub `readLink`, for a direct path, an absolute
  symlink, a relative symlink and a hot-reload symlink.
- `descente.detruire` undoes every `niveau == 1` entry, and still undoes the
  single entry of a `deep_*` report.
- `gallery_server.py` launches a game with `sys.executable`.

**Long test:** the matrix of section 2, run by hand before a release, and after
any change to the installer or to `metadata.json`.

## 9. Delivery order

1. **Spike**, on one Ubuntu 24.04 VM, by hand, with throwaway commands. It must
   show five things:
   - GDM autologin reaches a GNOME session with `--gpu off`;
   - an ssh session reads the user's session bus at `/run/user/$UID/bus`;
   - `GetExtensionInfo` is readable from it and reports state `1` for a
     symlinked extension;
   - `extension.path`, logged by the extension, is the unresolved symlink path
     (the premise of 3.2);
   - `journalctl --user -b -o cat | grep -E '\[ERPLibreHome\] (mount|enabled)'`
     shows the `enabled` line and no `failed` line: `enable()` ran to its
     end and every indicator mounted.

   If any fails, the design returns to brainstorming before code is written.
2. Prerequisite fixes (4.5, 3.1, 3.2), with their unit tests.
3. The installer, with its unit tests.
4. TODO local entry, QEMU tool and install profile.
5. The long test, with its unit tests and README section.
6. A full matrix run. The matrix table in the script is corrected from the
   measured GNOME versions.

## 10. Open risks

- **Software rendering.** GNOME Shell under `--gpu off` may fall back to a
  degraded session on some distributions. The spike checks Ubuntu, and the
  matrix run reveals the rest. A distribution that cannot start GNOME without
  3D is reported `FAILED(session)`, not hidden.
- **Leap 16.0 and the EL10 rebuilds** may lack `wmctrl` or `hidapi` in their
  default repositories. The package table is corrected from the long test, not
  guessed in advance.
- **Rolling distributions** move past GNOME 51 without notice. Their
  UNSUPPORTED verdict is the intended early warning.
