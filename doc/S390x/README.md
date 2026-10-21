
# ERPLibre on IBM Z (s390x)

This guide explains how ERPLibre installs on the s390x architecture (IBM Z
mainframe, LinuxONE), what the installer does differently from amd64, and
why. It is meant both for the person installing and for the developer
maintaining the scripts.

## In one sentence

PyPI publishes almost no precompiled package (wheel) for s390x: where pip
downloads a ready-made binary on amd64, it **compiles from source** on s390x.
Everything specific to s390x in ERPLibre follows from that: more system
packages, more memory, more time, and a few features left out.

## Supported systems

| System | Versions on s390x | How the VM is installed | Notes |
|---|---|---|---|
| Ubuntu | 24.04, 25.10, 26.04 | cloud image | 24.04 builds qpdf from source |
| Debian | 12, 13 | debian-installer (no s390x cloud image) | 12 builds qpdf and PROJ from source |
| Fedora | 43 only | cloud image (*fedora-secondary*) | s390x is a secondary Fedora architecture: only the current release is built |
| AlmaLinux | 9, 10 | cloud image | Rust below 1.95 (1.92 on 10) → completed by rustup; qpdf built from source (EL9 ships 10.3, EL10 11.9) |
| Rocky Linux | 9, 10 | cloud image | same as AlmaLinux |
| openSUSE | Leap 16.0, Tumbleweed | cloud image | Leap 16.0 builds qpdf (11.10 shipped); Tumbleweed's qpdf is recent enough; distribution Python used |

**Not supported on s390x:** Arch Linux (no official s390x image, the project
targets x86_64), NixOS (the only cloud image, built by a third party, is
x86_64 only), Proxmox VE (its repository has no s390x index). Ubuntu 20.04 and
22.04 are refused on every architecture: pikepdf needs qpdf 12.2 built in
C++20, and focal ships GCC 9 with no g++-10 for s390x.

## Installing

The order matters: **`make install_os` first**. It installs the system
packages that the compilations need. On amd64 the precompiled packages hide
this need; on s390x, running `make` alone on a bare machine stops on missing
headers.

- `make install_os`: system packages, swap, Rust, and qpdf or PROJ if needed;
- `make`: opens TODO and offers to build `.venv.erplibre`;
- `make install_odoo_18`: Odoo venv (`poetry install`) and Odoo sources
  (`repo sync`).

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
make install_os
make
make install_odoo_18
```

Orders of magnitude on a native s390x VM (KVM) with 4 GiB of RAM: about
5 minutes for `make install_os`, about 25 minutes for `make install_odoo_18`.
Under emulation on an x86 host, count roughly ten times longer.

If `make` is run before `make install_os`, the installer no longer fails
after long minutes of compilation: it first checks the build prerequisites
(C headers, compiler, pkg-config, cargo) and names what is missing, with the
apt command to install it, or apt or dnf for the pyenv check
(`script/install/S390x/build_check.sh` and
`script/install/lib_python_provider.sh`).

## What ERPLibre adds on s390x, and why

| Addition | Why | Where |
|---|---|---|
| Temporary swap file, up to 8 GiB of RAM + swap | one `cc1plus` alone can take 2.5 GiB (matplotlib); the kernel kills it and the compiler only reports `Killed signal terminated program cc1plus`, without naming memory | `S390x/lib_lowmem.sh` (`el_swap_ensure`) |
| Limit on parallel compilations: one per 2 GiB of RAM + swap | every build engine starts as many compilers as there are cores | `S390x/lib_lowmem.sh` (`el_build_limit_jobs`) |
| Rust ≥ 1.95, through rustup when the distribution is older | orjson 3.13 (Odoo 18) requires rustc 1.95; cryptography and bcrypt carry Rust extensions | `S390x/lib_rust.sh` |
| qpdf 12.3.2 built from source when the system has < 12.2 | pikepdf compiles against the system qpdf | `S390x/lib_qpdf.sh` |
| PROJ 9.6.2 built from source when the system has < 9.4 (apt family) | pyproj compiles against the system PROJ (its amd64 and arm64 wheels embed their own) | `S390x/lib_proj.sh` |
| Build packages: tbb, cmake, ninja, geos, proj, krb5, clang… | manifold3d, pyproj, pymupdf and others compile | `S390x/debian.sh`, `fedora.sh`, `suse.sh` |
| `libclang.so` symbolic link | pymupdf loads `libclang.so` by its bare name; distributions ship only versioned names | same files |
| `cryptography<47` for the Poetry bootstrap when OpenSSL < 3 | on s390x only, cryptography compiles against the system OpenSSL, and version 47 dropped OpenSSL 1.1.1 | `install_locally.sh` |
| Node.js from the distribution, or from nodejs.org if older than 18 | NodeSource publishes no s390x | `install_debian_dependency.sh` |

The swap file is **not** written to `/etc/fstab`: it only serves during the
installation and is no longer active after a reboot. The file itself stays on
disk, and a later run reactivates it; delete it by hand to reclaim the space.
On btrfs (Fedora, openSUSE)
it lives in a dedicated subvolume `/.erplibre-swap`, marked `+C` (no
copy-on-write, no compression), otherwise `swapon` refuses it.

## What is missing compared to amd64

| Missing | Consequence | Reason |
|---|---|---|
| **wkhtmltopdf** | no PDF reports (invoices, quotes); Odoo shows the report as HTML instead | no s390x package upstream; the installer skips it on every architecture other than x86_64 |
| **PyMuPDF** | excluded from the Odoo 18 requirements on s390x; PDF features that depend on it (OCA edi) are unavailable | MuPDF does not build on s390x |
| **factur-x ≥ 4** | factur-x 3.x is used instead, without Schematron validation | factur-x ≥ 4 depends on saxonche, which has no s390x wheel |
| **mise** | `make install_mise` does nothing; Python comes from the distribution or is compiled by pyenv | mise publishes no s390x binary |
| **Forgejo** (QEMU option) | the option is greyed out | no s390x binary |
| **Virtual display** for desktop VMs | the desktop is reached over the network | the s390x kernel does not guarantee the virtio-gpu driver |
| **PostGIS** on openSUSE Tumbleweed | installed best-effort, absent from the s390x repositories | not packaged |
| **GeographicLib C++** on openSUSE | not installed | openSUSE packages only the Python binding |

## Advantages and drawbacks compared to amd64

| | s390x | amd64 |
|---|---|---|
| Python packages | compiled from source (numpy, pandas, pillow, matplotlib, cryptography, orjson, pikepdf, pyproj, manifold3d…) | precompiled wheels |
| Odoo installation time | tens of minutes, mostly in the compiler | a few minutes |
| Memory during installation | 4 GiB of RAM recommended, swap added automatically | the catalogue minimum is enough |
| Python interpreter | distribution Python, or CPython compiled by pyenv | distribution Python, or a precompiled CPython from mise in seconds |
| `uv` | available, but almost no gain: the time is in the compiler | noticeable gain |
| Odoo features | no wkhtmltopdf, no PyMuPDF, factur-x 3.x | complete |
| Hardware | IBM Z reliability, I/O and virtualisation; ERPLibre runs where the organisation's data already lives | widely available, cheaper to test |
| Reproducibility | the lock is architecture-neutral: the same lock (`requirement/poetry.odoo18.0_python3.12.10.lock`) serves both, the differences being platform markers | — |

## By system

### Debian, Ubuntu, Linux Mint (apt)

- The s390x part lives in `script/install/S390x/debian.sh`, sourced by
  `install_debian_dependency.sh`.
- Package names change between releases: `apt_pick` asks apt which name is
  installable (GeographicLib), so that one obsolete name does not make apt
  reject the whole batch.
- Only build-essential, pkg-config, libssl-dev, zlib1g-dev, libjpeg-dev and
  cmake stop the installation if they are missing; the others serve optional
  Odoo modules.
- Ubuntu is a *ports* architecture on s390x: packages come from
  ubuntu-ports mirrors, not archive.ubuntu.com.
- Ubuntu 24.04 and Debian 12 compile qpdf (about half an hour under
  emulation); Debian 12 also compiles PROJ. Ubuntu 26.04 and Debian 13 ship a
  Rust below 1.95, completed by rustup.

### Fedora, AlmaLinux, Rocky (dnf)

- The s390x part lives in `script/install/S390x/fedora.sh`.
- On AlmaLinux and Rocky, EPEL and CRB are enabled: most `-devel` packages
  live there.
- `qpdf-devel` is installed only if it reaches 12.2; otherwise qpdf is built
  in `/usr/local`. The RHEL linker searches `/usr/lib64` before
  `/usr/local/lib64`, so an old `qpdf-devel` would make pikepdf link against
  the old library despite the new headers.
- AlmaLinux and Rocky 10 ship Rust 1.92: rustup completes it.
- Fedora sets up a zram swap equal to the RAM: with 4 GiB of RAM, the target
  is almost reached and no swap file is added.

### openSUSE Leap 16.0 and Tumbleweed (zypper)

- The s390x part lives in `script/install/S390x/suse.sh`.
- A missing `cargo` is fatal on s390x: bcrypt and cryptography could not
  compile, and the failure would otherwise show an hour later.
- The distribution's Python 3.12 is installed and preferred: building CPython
  3.12.10 with gcc 15.2 on s390x stops on an internal compiler error.
- qpdf goes through the same 12.2 check as with apt and dnf: Leap 16.0 ships
  11.10 and compiles it; Tumbleweed's version passes, so nothing is compiled
  there.
- Leap is the version to choose for a long-lived installation; Tumbleweed
  moves every day and its s390x tree lags behind x86_64.

## Deploying s390x VMs with the QEMU tools

From TODO: **Execute › Deploy › QEMU/KVM**, then choose the s390x
architecture. From the command line:

```bash
sudo ./script/qemu/deploy_qemu.py --setup-host --assume-yes
sudo ./script/qemu/deploy_qemu.py --name erplibre-ubuntu-2604-s390x \
    --distro ubuntu --version 26.04 --arch s390x \
    --ssh-key ~/.ssh/id_ed25519.pub -y
```

- **Always pass `--arch s390x`**: the default is amd64, even on an s390x
  host.
- **KVM or emulation.** On an s390x host (an LPAR or a z/VM guest with KVM),
  s390x VMs run natively and boot in about twenty seconds. On an x86 host
  they are emulated (TCG; package `qemu-system-s390x` on apt and dnf,
  `qemu-s390` on zypper, `qemu-emulators-full` on pacman), about ten times
  slower. Inside a VM without nested virtualisation, libvirt silently falls
  back to emulation even when the architectures match.
- **Memory.** An s390x VM gets at least 4 GiB by default; other
  architectures keep the catalogue minimum of the version (1 to 3 GiB).
- **Machine.** `s390-ccw-virtio`, boot from disk (IPL/zipl): no BIOS, no
  UEFI. The console is SCLP (`ttysclp0`), logged in
  `/var/log/libvirt/qemu/<name>-console.log`.
- **Debian** has no s390x cloud image: the VM is installed by
  debian-installer, driven by a preseed embedded in the initrd. Its address
  is **fixed** (chosen in .200–.249 of the libvirt network), not given by
  DHCP; its network card is named `enc1`.
- **QEMU download cache.** When the cache is active, it intercepts the VMs'
  HTTPS and re-signs it with its own authority; the deployment installs that
  authority in every VM, through cloud-init or, for Debian, through the
  installer. A VM deployed while the cache was stopped, then intercepted once
  it is restarted, fails every HTTPS download: redeploy it.
- **SSH key.** A deployment that installs ERPLibre requires a key in
  `~/.ssh`; TODO generates one if needed, before creating any VM.

## Settings

| Variable | Default | Effect |
|---|---|---|
| `EL_SWAP_TARGET_GIB` | `8` | RAM + swap targeted, in GiB; `0` disables the swap file |
| `EL_SWAP_FILE` | `/swapfile.erplibre` | swap file path; on btrfs, the file goes into a `.erplibre-swap` subvolume of its directory (`/.erplibre-swap/swapfile.erplibre` by default) |
| `EL_MEM_PER_JOB_MB` | `2048` | memory reserved per parallel compilation |
| `EL_RUST_MIN_MINOR` | `95` | minimum Rust (1.95) below which rustup is installed |
| `EL_PYTHON_PROVIDER` | `auto` | `auto`, `mise` or `pyenv`; `auto` takes a compatible distribution Python before installing anything, which on s390x avoids compiling CPython |
| `EL_PIP_PROVIDER` | `auto` | `auto`, `uv` or `pip` |

## Troubleshooting

| Symptom | Cause | What to do |
|---|---|---|
| `zlib not available` at the end of a pyenv build | CPython built without its `-dev` headers | `make install_os`, then rerun |
| `Killed signal terminated program cc1plus` | not enough memory | 4 GiB of RAM; check that `el_swap_ensure` added swap |
| `certificate signer not trusted` on `git clone` | VM intercepted by the QEMU cache without its authority | redeploy the VM with the cache active |
| `rustc 1.9x is not supported … requires rustc 1.95` | Rust too old for orjson | `make install_os` (rustup); check access to sh.rustup.rs |
| QEMU install waits 20 minutes, then `Permission denied (publickey)` | VM created without an SSH key | provide a key in `~/.ssh` and redeploy |
| `run.sh`: `can't open file … odoo-bin` | Odoo sources not fetched (`repo sync` interrupted) | rerun `make install_odoo_18`: it detects the missing sources |
| `No module named 'babel'` during the preparation phase | `config_update` runs before Poetry installed the packages | harmless, the installation continues |

## For developers: where the code lives

Everything **dedicated** to s390x is in `script/install/S390x/`; what serves
every architecture stays where it is.

| File | Role |
|---|---|
| `S390x/debian.sh` | s390x part of the apt installation |
| `S390x/fedora.sh` | s390x part of the dnf installation |
| `S390x/suse.sh` | s390x part of the zypper installation |
| `S390x/build_check.sh` | build prerequisites check before the tooling venv, on every architecture other than amd64 and arm64 |
| `S390x/lib_lowmem.sh` | swap and limit on parallel compilations |
| `S390x/lib_rust.sh` | Rust minimum version, rustup fallback |
| `S390x/lib_qpdf.sh` | qpdf built from source when too old |
| `S390x/lib_proj.sh` | PROJ built from source when too old |

The `S390x/*.sh` files are **sourced**, never executed: they inherit the
caller's variables and functions (`APT_GET`, `DNF`, `zyp_soft`), and an `exit` in them
stops the whole installation, as it would in the caller. A global script
loads its fragment with:

```bash
if [ "$(uname -m)" = "s390x" ]; then
  . ./script/install/S390x/debian.sh
fi
```

What stays global although it matters a lot on s390x:
`script/install/lib_python_provider.sh` (choice of the Python interpreter),
`script/install/swig_compat.h` (included in every compilation of
`poetry install`), and `install_locally.sh`, which calls the s390x limits
only after testing the architecture. The Python requirements are
architecture-neutral: the `platform_machine` markers (PyMuPDF excluded on
s390x; factur-x ≥ 6.8 elsewhere, < 4 on s390x) are kept in the single lock of
each Odoo version (`requirement/poetry.odoo18.0_python3.12.10.lock`).
