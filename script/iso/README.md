
# ERPLibre Arch Linux ISO (x86_64)

`archlinux/build_iso.py` builds a custom Arch Linux ISO with
[archiso](https://wiki.archlinux.org/title/Archiso), starting from its
`releng` profile. The image boots in BIOS and UEFI mode, can be written as is
to a USB key (hybrid image), and opens an installer on the first console
that installs **Arch Linux + GNOME (gdm) + ERPLibre**, with an ERPLibre
profile chosen during installation.

The target machine needs network access: packages and the ERPLibre
repository are downloaded during installation.

## Build

By default the ISO is built **in an up-to-date Arch Linux container**
(`--builder container`): the host needs only Podman (preferred) or Docker,
neither `archiso` nor an up-to-date pacman database, nor even Arch Linux.
The image `erplibre-isobuilder:<YYYYMMDD>` (also tagged `latest`) is built
from `archlinux/container/Containerfile` (`pacman -Syu archiso archinstall`)
on first use, when it is more than 14 days old, or with `--refresh-image`;
older dated tags are removed after a rebuild. Inside, `build_iso.py` runs
again with `--builder host`; the repository is mounted read-only, the output
directory and a persistent pacman cache (`~/.erplibre/iso/pkgcache`, never
purged by the script) read-write.

| Engine | How mkarchiso runs | Extra flags |
|---|---|---|
| Podman without root | as a regular user (UID 1000 = caller, `--userns=keep-id`), through `unshare` like on a host | `--security-opt unmask=/proc/*` (a masked `/proc` forbids mounting a new one in a nested user namespace) |
| Docker, or Podman run by root | as root | `--cap-add SYS_ADMIN` (mounts of the build chroot); files are then given back to the caller (`--chown`) |

`--privileged` is never used. Rootless Podman cannot run mkarchiso as root
(devtmpfs cannot be mounted in a user namespace), and rootless Docker is
refused for the same reason. The rootless Podman mode needs the usual
65,536-ID `/etc/subuid` range for the account.

`--builder host` uses the host's `archiso` (Arch Linux host). Since archiso
89, `mkarchiso` runs as a regular user (user namespaces, with a
`/etc/subuid` range for the account); older versions are run through `sudo`.
`--builder auto` uses a container when an engine answers, the host
otherwise.

```bash
./script/iso/archlinux/build_iso.py --dry-run          # plan only
./script/iso/archlinux/build_iso.py                    # container, master
./script/iso/archlinux/build_iso.py --refresh-image --branch develop
sudo pacman -S --needed archiso                        # --builder host only
./script/iso/archlinux/build_iso.py --builder host --keep-work
```

Result: `~/.erplibre/iso/erplibre-archlinux-<YYYY.MM.DD>-x86_64.iso` and its
`.sha256` file (`sha256sum -c` format). The work directory
(`~/.erplibre/iso/work/<date>`) is removed after a successful build, unless
`--keep-work` is given; it is kept after a failure. A failed build leaves
neither a partial ISO nor an outdated `.sha256` under the ISO's name.
`--dry-run` refuses the same things as a real build: an unexpected releng
profile, an existing work directory. In container mode the work directory
lives inside the container and disappears with it, unless `--work-dir` or
`--keep-work` puts it on the host; its `build/` tree then belongs to the
container's IDs, and the script prints the command that removes it
(`podman unshare rm -rf …` or `sudo rm -rf …`). The container-mode
`--dry-run` prints the exact `build` and `run` commands without starting
anything; the releng checks happen inside the container.

| Option | Default | Effect |
|---|---|---|
| `--branch` | `master` | ERPLibre branch cloned on the target |
| `--git-url` | `https://github.com/erplibre/erplibre` | ERPLibre repository |
| `--output-dir` | `~/.erplibre/iso` (`~/.erplibre/iso/autotest` with `--auto-default`) | ISO and checksum |
| `--work-dir` | `~/.erplibre/iso/work/<date>` | archiso profile and build tree |
| `--lang` | `EL_LANG`, else `fr` | installer language |
| `--auto-default <profile>` | — | **tests only**, see below |
| `--builder` | `container` | `container`, `host` or `auto` |
| `--runtime` | `podman`, else `docker` | engine of the container mode |
| `--refresh-image` | — | rebuild the builder image even if recent |
| `--pkg-cache` | `~/.erplibre/iso/pkgcache` | pacman cache of the container mode |
| `--source-date-epoch` | now | date of the ISO (file name, label) |

## Writing to a USB key

The ISO is a hybrid image: copy it to the whole device (not a partition).
**Everything on the key is erased.**

```bash
sha256sum -c erplibre-archlinux-*-x86_64.iso.sha256
sudo dd if=erplibre-archlinux-<date>-x86_64.iso of=/dev/sdX bs=4M \
    conv=fsync oflag=direct status=progress
```

## Installing

The default boot entry starts the live system; root is logged in
automatically on `tty1` and the ERPLibre installer screen opens
(`erplibre-installer-ui`, a [Textual](https://textual.textualize.io/)
application). On a serial console, with `TERM=dumb`, without a terminal, or
with `--plain`, the same questions are asked line by line instead. The
language comes from `erplibre.lang=fr|en`, else from `profiles.json`; `L`
switches it on the home screen.

The home screen offers three choices:

1. **Install ERPLibre**, driven by the machine profile
   (`/erplibre/machine.json` on the key, else the `generic` profile, shown as
   *guided*). The form asks, in this order:
   - the **keyboard layout** first: `loadkeys` applies it as soon as the
     field is left, because the LUKS passphrases that follow are typed with
     the console layout, and the installed system's console gets the same
     layout;
   - every `ask` field of the resolved profile (time zone, host name,
     locales, layout, secret volume…), then the user name;
   - the user password and its confirmation, the root policy (locked, with
     administration through sudo, or its own password), the LUKS passphrase
     and its confirmation when the layout is `lvm_on_luks`, the secret volume
     passphrase when there is one;
   - the disk, when `auto` cannot decide (no candidate, or several);
   - the ERPLibre profile: **ERPLibre + Odoo 18**
     (`make install_os && make install_odoo_18`, then `erplibre.service`,
     Odoo on port 8069), **ERPLibre Home**, **ERPLibre Dev**
     (`make install_dev`, no service) or **GNOME only**.

   A **summary** follows: the resolved plan, the hardware facts, the
   warnings, the commands of the disk stage and the disk that will be
   **erased**, whose name must be typed to go on. The installation then runs
   on the same screen, with the core's output and the ERPLibre stage log; the
   last screen offers to reboot, to quit to the shell or to go back home.
2. **Start ERPLibre TODO**: the TODO of this repository, embedded in the
   key under `/opt/erplibre` and run with the live Python, for instance to
   write another key (see *ERPLibre TODO on the key* below). Quitting it
   brings the home screen back.
3. **Run archinstall (guided, pre-filled)**: the previous path. After the
   ERPLibre profile is chosen, archinstall opens with GNOME, gdm,
   NetworkManager and pipewire already set; it asks the disk, **a user
   account** (ERPLibre is installed for it), the language and the time zone.

Passwords and passphrases are never written to the key: they are typed at
installation, stay in memory, and reach the core through a 0600 file on
`/run/erplibre-install` (tmpfs) that is overwritten and deleted when the
core returns. `erplibre-installer-ui --dry-run` asks everything and shows
the summary and the plan, but erases nothing.

The ERPLibre profiles and their commands come from the same table as the
QEMU deployment (`QemuInstallMixin._qemu_install_profiles` in
`script/todo/qemu_install.py`).

ERPLibre is installed inside archinstall's chroot, at the end of the
installation, by `erplibre-stage.sh` (archinstall `custom_commands`): it
clones the repository as the user into `~/git/erplibre`, starts PostgreSQL
with `pg_ctl` (services cannot be started in a chroot), runs the profile
command with temporary passwordless sudo, then removes that sudo rule. The
log is `/var/log/erplibre-install.log` on the installed system. If this
stage fails, the system and GNOME still boot; rerun it with
`sudo /usr/local/sbin/erplibre-stage`.

Quitting the installer leaves a root shell; `erplibre-install` relaunches
it.

## ERPLibre TODO on the key

`/opt/erplibre` holds a checkout of the repository as it stands when the
ISO is built, chosen by git rather than by walking the disk:

- tracked files (`git ls-files --cached`), copied from the working tree,
  so uncommitted changes are included;
- untracked files that `.gitignore` does not exclude
  (`git ls-files --others --exclude-standard`): the new files of a branch,
  except those whose name looks like a secret or a data dump (`.env`,
  `*.pem`, `*.key`, `id_rsa*`, `*credential*`, `*token*`, `*.sql`,
  archives… see `CHECKOUT_UNTRACKED_DENIED` in `build_iso.py`);
- never `private/` (except its `.gitignore` and `__init__.py`), `tasks/`,
  `.git`, Python caches, symbolic links, nested repositories, or what
  `.gitignore` excludes (virtualenvs, addons, built ISOs).

The build plan prints the number of files, how many are untracked, and
their size, then names every untracked file kept and every untracked file
left out. In container mode git runs on the host and hands the list to
the container in a temporary file of the output directory, deleted after
the run: the builder image needs no git, and a git worktree works too.
Outside a git checkout, the build stops.

The TODO runs with the live Python and Arch packages rather than a
`pip install --target` of `requirement/erplibre_require-ments.txt`:
Arch packages are built for that exact Python, and only what the TODO
imports at start-up goes into the ISO (`EXTRA_LIVE_PACKAGES` in
`build_iso.py`). The full requirements weigh about 480 MiB installed and
87 MiB once compressed; the checkout adds about 7 MiB to the ISO.

`erplibre-todo` writes the live Python version into the copied `conf/`,
passes the home screen language, and enlarges the live's writable layer
(`/run/archiso/cowspace`, 256 MiB by default) to 75 % of the memory
(`EL_COW_SIZE`), so that the **System › Bootable USB key** menu can keep an
ISO of more than 1 GiB under `~/.erplibre/iso`. That menu works in the live
session: it detects the keys, never offers the key the live booted from
(mounted on `/run/archiso/bootmnt`), and writes an ISO picked with the file
browser, with or without a machine profile (`xorriso` is on the key).
Building an ISO from the live is refused with its reason (the copy on the
key is not a git checkout, and the live has no container engine), and the
menus that need an installed ERPLibre (Odoo, databases, virtualenvs) report
their error.

## Automatic installation (tests)

The boot entry **ERPLibre automatic install (erases first disk)** exists
only on the test variant (`--auto-default`, below): the installation ISO
has no such entry, and `erplibre.auto=` typed by hand on its kernel command
line is refused (code `22`), since the ISO lacks the test marker
`/usr/local/share/erplibre-install/autotest`. The entry installs without
any question on the first disk that is not the boot medium, with the user
`erplibre`, then powers off. The password reaches the configuration tool
through the environment, never its arguments, and the `--creds` file lives
on the tmpfs `/run/erplibre-install`, overwritten and deleted as soon as
archinstall returns. Progress and the
final line `__ERPLIBRE_EXIT__ <code>` go to the serial console `ttyS0`, the
convention of `script/todo/qemu_install_monitor.py`.

It erases nothing until it has identified the boot medium, by the ISO's UUID
or by the `/run/archiso` mount: on a key written with `dd` the UUID always
matches. A key whose ISO files were copied onto a FAT32 partition carries
neither once `copytoram` has unmounted it, so the installer stops with code
`21`. It runs once per boot: relaunching `erplibre-install` afterwards is
refused rather than erasing the freshly installed disk again.

| Kernel parameter | Effect |
|---|---|
| `erplibre.auto=<profile>` | `odoo18`, `home`, `dev`, `gnome`; `1` = default profile |
| `erplibre.password=<pw>` | password of the `erplibre` user (default `erplibre`, for test machines only) |
| `erplibre.lang=fr\|en` | installer language |
| `erplibre.nopoweroff` | stay on at the end |
| `erplibre.ssh` | install `openssh` and enable `sshd` on the target |

`build_iso.py --auto-default <profile>` builds a **test variant**,
`erplibre-archlinux-autotest-<date>-x86_64.iso`, whose default boot entry
(3 s timeout, BIOS and UEFI) is the automatic install of `<profile>` with
`erplibre.ssh`: a virtual machine booted on it installs unattended, and the
installed system can then be checked over SSH. Its default output directory,
`~/.erplibre/iso/autotest`, keeps it out of the TODO USB catalogue, which
looks only at `~/.erplibre/iso`; `--output-dir ~/.erplibre/iso` is refused.
Never write it to a key meant for a real installation.

## Installation driven by the machine profile

`erplibre-installer` is the installer core that follows the machine profile
(`/erplibre/machine.json` on the key, else the `generic` profile). It asks
nothing: everything comes from an **answers document** (JSON) that the
screen fills in, or that a test passes on the kernel command line. It
resolves the profile against the hardware, refuses while a question, a
blocking warning, a secret or the typed confirmation of the erased disk is
missing, then:

1. **disk stage** (`erplibre_disk.py`): GPT (ESP, or `bios_grub` + `/boot`
   in BIOS), LUKS2 with the resolved sector size, iteration time and
   persistent discards, LVM (swap, optional nested-LUKS secret volume,
   root minus the free space kept for e2scrub), mounted on
   `/mnt/archinstall`. The disk is re-read just before it is erased, and
   refused if its size or model differs from the summary, if anything is
   stacked on it (LVM, LUKS, RAID, multipath), or, when an NVMe reformat
   is confirmed, if another namespace shares its controller (the 4 KiB
   reformat is then not even offered). An interrupted disk stage closes
   what it opened. If the boot medium is not identified, no disk is chosen
   automatically: the screen asks for it;
2. **archinstall** `--silent` in pre-mounted mode with the **ERPLibre
   plugin** (`erplibre_plugin.py`): systemd initramfs hooks (`sd-encrypt`,
   `lvm2`), systemd-boot entries and fallback entries or GRUB, UKI,
   locales, zram, e2scrub, AppArmor, shell, swap line in fstab. The plugin
   refuses any archinstall other than 4.5;
3. the ERPLibre stage, unchanged, then unmount.

Secrets are never stored. They are accepted only from
`erplibre.answers=b64:<base64>` (automatic tests) or from a file under
`/run/erplibre-install` (tmpfs). LUKS passphrases reach `cryptsetup` on its
standard input; account passwords reach archinstall through a `--creds`
file (0600, tmpfs) that is overwritten and deleted as soon as archinstall
returns.

```
erplibre-installer --answers /run/erplibre-install/answers.json [--dry-run]
erplibre-installer --auto --serial /dev/ttyS0   # reads erplibre.answers=
```

The kernel parameter `erplibre.answers=` makes `erplibre-install` hand the
automatic installation to this core. Exit codes: `0`, the ERPLibre stage
codes, `21` answers, `22` profile, `23` disk refused, `24` disk stage
failed (or a UUID missing after it), `25` archinstall version, `26`
archinstall, `27` plugin, `130` interrupted.

## Files

```
script/iso/archlinux/
├── build_iso.py                         releng + overlay -> mkarchiso
├── container_build.py                   container mode: engine, image, argv
├── container/Containerfile              builder image (archiso, archinstall)
└── profile/airootfs/usr/local/
    ├── bin/erplibre-install             tty1 entry: screen or automatic
    ├── bin/erplibre-installer-ui        installer screen (Textual / text)
    ├── bin/erplibre-install-config      archinstall user_configuration.json
    ├── bin/erplibre-installer           profile-driven installer core
    ├── bin/erplibre-todo                TODO embedded in the key
    └── share/erplibre-install/
        ├── erplibre-stage.sh            ERPLibre stage (archinstall chroot)
        ├── erplibre_ui.py               screen: mode, home actions
        ├── erplibre_ui_flow.py          fields, checks, summary, core run
        ├── erplibre_ui_tui.py           Textual screens
        ├── erplibre_ui_plain.py         line-by-line text mode
        ├── erplibre_ui_i18n.py          fr / en (messages.fr.json)
        ├── erplibre_installer.py        core: answers, prepare, run
        ├── erplibre_disk.py             disk stage: plan, preflight, run
        ├── erplibre_archinstall.py      pre-mounted config, --creds
        ├── erplibre_plugin.py           archinstall plugin (4.5)
        └── user_configuration.template.json
```

`profiles.json` (profiles, network source, `erplibre.service` template) and
`messages.fr.json` (the French of every phrase of the screen, taken from
`script/todo/todo_i18n.py`) are generated into the same directory at build
time, and `machine/` (`machine_profile.py`, `facts.py`,
`profile_messages.py`, `profiles/*.json`) is copied there from
`script/iso/archlinux/machine/`. The network source — the
cloned repository and branch — is set in one place: `network_source` in
`profiles.json`, read by `el_network_source_prepare` in
`erplibre-stage.sh`.

Tests: `./script/test/run_unit_test.sh test/test_iso_archlinux_build.py`
(no archiso nor container engine needed), `test/test_iso_container_build.py`,
and `test/test_iso_installer_{disk,plugin,core,ui}.py` (no archinstall
needed; the screen tests need `textual`, else they are skipped).
