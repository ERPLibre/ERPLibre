
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
**Everything on the key is erased.** The TODO menu `Bootable USB key` does
the same after three confirmations, and can add a machine profile and an
offline payload first (see « Writing a key with a payload »).

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
archinstall, `27` plugin, `28` offline install refused, `29` the
installed system still trusts the offline payload authority, `130`
interrupted.

## Offline installation (payload on the key)

A key can carry an **offline payload**: a third partition, ext4,
`LABEL=ERPLIBRE_DATA`, added to the ISO by `xorriso -append_partition 3`
when the key is written (never by editing the key after `dd`). It holds one
payload for one ERPLibre profile:

```
manifest.json   schema, ERPLibre profile, git source (url, branch, commit),
                creation date, archinstall version, Arch snapshot date,
                sizes, sha256 of the small parts
repo/           pacman repository: <repo>/os/x86_64/<repo>.db + packages
store/          store of the Go caching proxy (script/qemu_cache), git
                mirrors under store/git/
bin/            the proxy, built static (CGO_ENABLED=0)
ca/             a certificate authority of this payload only (named
                « ERPLibre offline payload », valid two years from a week
                before its creation)
```

When a valid payload is found, the screen offers its profile by default,
labelled « offline install (payload <profile>, <date>) »; choosing it needs
no network. Another profile stays possible online, network required.

In automatic mode (`erplibre.answers`), the answers' `"offline"` alone
decides: `true` waits for neither the network nor `pacman-init`, and a
missing or unreadable payload is refused at once (code `28`); `false`
waits for both, even when the key carries a payload.

Before anything is erased, the core checks that the payload exists, is of
the chosen profile, that the profile command of this ISO is the one the
payload recorded (`erplibre.profile_command_sha256`; a payload without it
only gets a warning), and that its repository serves every package the
archinstall configuration asks for (exit code `28` otherwise). It then
starts `erplibre-offline start --profile <key>`:

- the clock is moved forward to the payload creation date when it is
  behind (a hardware clock kept in local time): the authority and the
  snapshot signatures would otherwise be « not yet valid »;

- the pacman keyring is initialised: without network, releng's
  `pacman-init` waits forever for a synchronised clock, so the wait is
  lifted (as `archinstall --skip-ntp` does for itself);
- the partition is mounted read-only (`ro,noload,nodev,nosuid,noexec`:
  `noload` keeps even a pending ext4 journal from being replayed);
- the proxy and the authority are copied to `/run/erplibre-offline`, their
  sha256 checked, and the proxy runs `--hors-ligne` on 127.0.0.1 under an
  unprivileged UID: it serves the store, and the local pacman repository
  for **every** Arch mirror URL, never contacts upstream, never writes;
- dnsmasq answers 198.18.0.1 to every name, systemd-resolved asks only it;
  that address sits on a dummy interface with a low-priority default route,
  without which `connect()` fails before the nft rule and systemd-resolved
  answers « Network is down »;
- nft redirects TCP 80/443 output of every process but the proxy to it
  (IPv6 to 80/443 is rejected so that clients fall back to IPv4);
- the live trusts the authority (anchor + `trust extract-compat`);
- the live mirrorlist gets a server if it has none: pacstrap copies it into
  the target, which keeps a real mirror;
- a self-test fetches `core.db` through the whole path;
- the live keyring is updated from the payload repository when the
  snapshot's `archlinux-keyring` is newer (`pacman -Sy`, `pacman -Qu`,
  `pacman -S`, signature checked by the current keyring): it replaces the
  WKD sync that `--skip-wkd` skips, so that a packager key added or
  extended after the ISO was built refuses before the erase, not after.

archinstall runs with `--offline --skip-ntp --skip-wkd`. The archinstall
chroot shares the live network, so the ERPLibre stage reaches the proxy as
well; inside the target it trusts the authority (anchor, `SSL_CERT_FILE`,
`REQUESTS_CA_BUNDLE`, `PIP_CERT`, `UV_NATIVE_TLS`, `NODE_EXTRA_CA_CERTS`, a
global `npmrc` for `sudo npm -g`) and removes all of it at the end. The core
then checks the target (`erplibre-offline clean-target`): it always
regenerates the target bundles (`trust extract-compat` in the chroot),
then searches them for the authority itself, not only its anchor, since
a removed anchor whose extract failed (full disk, killed stage) leaves it
trusted. If the authority is still there the install fails with code `29`.
It then stops the service, which undoes each step in reverse order; any
exception during `start`, Ctrl-C included, undoes it as well. The installed system is
normal: regular mirrorlist, no proxy authority, no proxy service.

The payload is built on the host by `archlinux/offline_payload.py`
(`build-proxy`, `manifest`, `image`); the proxy is compiled there with the
Go toolchain of the repository, because its store format belongs to the
version that filled it. The repository must carry each package's `.sig`:
pacman downloads it, the databases no longer embed signatures. The image
makes every file readable (the proxy runs under its own account), except
the authority's key.

### Building a payload

```bash
./script/iso/archlinux/offline_payload.py build --profile gnome \
    --iso ~/.erplibre/iso/erplibre-archlinux-<date>-x86_64.iso --dry-run
./script/iso/archlinux/offline_payload.py build --profile odoo18 \
    --iso <iso> --seed-git-mirrors /var/cache/erplibre_go_qemu_cache/git
```

`build` makes a **reference install** of the profile in QEMU (KVM, no
root): the static proxy runs on the host in record mode, on 127.0.0.1 and
two free ports, with an empty store; the VM boots the ISO as a USB key by
its kernel (answers in `erplibre.answers`, generic machine profile, UEFI
when OVMF is present) with a second key `LABEL=ERPLIBRE_DATA` that holds
only a **record manifest** (`"mode": "record"`, the proxy address and
ports, the authority's certificate). The installer then takes its offline
path, except that nft sends 80/443 to the host proxy through the QEMU
user-network gateway (10.0.2.2) and the live keeps its network and DNS:
the reference install fetches exactly what the offline install will ask.
Running the proxy on the host rather than in the live writes the store
straight into the build directory (nothing to extract from a VM disk) and
needs no root. It runs with `--sans-tunnel`: reached through the QEMU
gateway, without a kernel redirect on the host, it has no original
destination to tunnel to, so it always decrypts. `--seed-git-mirrors` first copies the profile's bare git
mirrors from an existing store (reflink on btrfs/XFS, read only on the
source); the install still goes through the proxy, which updates them.

The packages a machine profile can ask for but the VM did not (kernels,
both microcodes, open GPU drivers, power, shells, AppArmor, LUKS/LVM,
GRUB, sound firmware) are then fetched through the proxy from the host,
their closure computed by `pacman -Sp` on the recorded databases.

`assemble <build dir>` (also run by `build`) turns the store into the
payload: pacman files become `repo/` — the recorded official database is
kept when it names a present file for every recorded package, otherwise
the repository is rebuilt by `repo-add` on the newest recorded version
(unsigned database, accepted by Arch's `SigLevel = Required
DatabaseOptional`; packages keep their `.sig`); the rest of the store is
kept (hard links), and only the git mirrors the access log shows served.
Then `manifest.json`, the ext4 image and its `.sha256`, and `report.json`
(sizes, times, packages the pre-erase check would miss: must be empty),
all under `~/.erplibre/iso/offline/<profile>-<stamp>/`.

### Writing a key with a payload

In the TODO, `System › Bootable USB key › Write an ISO to a USB key`: after
the machine profile, an ERPLibre ISO asks « Offline installation »:

- `[0]` no: the key installs online, network required;
- one line per payload found under `~/.erplibre/iso/offline/`: profile,
  date, image size and the advised key size. A payload is listed with
  `✗` and cannot be chosen when its `.sha256` is missing, its manifest
  (read from the image by `debugfs`, without root) is missing or refused by
  the live's own check, or `report.json` says a required package is
  missing or unsigned;
- a last entry runs the factory (`offline_payload.py build`) for a chosen
  ERPLibre profile, after showing its duration, the free space it needs
  (refused below it) and the command; the git mirrors of the host cache
  are seeded when present. The list is read again afterwards.

Choosing a payload warns when nothing says which ISO recorded it, when it
was recorded with another ISO (only an ISO with the offline mode uses the
partition; an older one ignores it and installs online), when the ISO's
archinstall differs from the payload's, or when no plugged-in key is large
enough; each warning asks before keeping the payload.

The payload then goes into a derived ISO, with the machine profile if one
was chosen, under `~/.erplibre/iso/derived/<base>-<profile|none>-<payload>.iso`
(0700 folder, 0600 file: the payload holds its authority's key):

```bash
xorriso -indev <base.iso> -outdev <derived.iso> \
    -boot_image any replay -boot_image any gpt_disk_guid=volume_date_uuid \
    -volume_date uuid <date of the base> [-map <profile.json> /erplibre/machine.json] \
    -append_partition 3 0x83 <payload.img> -commit
```

Before xorriso, the free space is checked (base + image; outdated derived
ISOs are removed first if that is enough), and the image's sha256 is
checked against its `.sha256`. After it, the derived ISO is checked with
`sfdisk -J`, `xorriso -report_el_torito` and `blkid`: BIOS and UEFI El
Torito images, EFI partition, same UUID as the base (archiso finds its
medium by it), partition 3 of type Linux at least as large as the image;
otherwise it is removed. The key is then written as usual (`dd`, `cmp`): a
key smaller than the derived ISO is refused, with the advised key size —
an Odoo 18 payload (about 26 GB) needs a key of 32 GB or more. Writing and
reading back such an image takes tens of minutes on a slow key.

On the live, archiso mounts partition 1 (ISO 9660) of the key, so
partition 3 stays free for `erplibre-offline`, which finds it by its label.
`Detect USB keys and show their information` shows when a key carries a payload, with its profile and
date when the device is readable without sudo; `Supported ISO list` lists
the payloads of `~/.erplibre/iso/offline/`.

## Files

```
script/iso/archlinux/
├── build_iso.py                         releng + overlay -> mkarchiso
├── container_build.py                   container mode: engine, image, argv
├── container/Containerfile              builder image (archiso, archinstall)
├── offline_payload.py                   offline payload: reference install, image
└── profile/airootfs/usr/local/
    ├── bin/erplibre-install             tty1 entry: screen or automatic
    ├── bin/erplibre-installer-ui        installer screen (Textual / text)
    ├── bin/erplibre-install-config      archinstall user_configuration.json
    ├── bin/erplibre-installer           profile-driven installer core
    ├── bin/erplibre-todo                TODO embedded in the key
    ├── bin/erplibre-offline             offline payload service
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
        ├── erplibre_offline.py          offline: probe, start, stop, checks
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
`test/test_iso_installer_{disk,plugin,core,ui}.py` (no archinstall
needed; the screen tests need `textual`, else they are skipped), and
`test/test_iso_offline.py` (offline service, stage, payload tool).
