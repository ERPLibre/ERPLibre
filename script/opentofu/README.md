
# Deploying a fleet of VMs with OpenTofu

A **fleet** is a set of VMs described by a JSON spec,
`private/opentofu/<fleet>/spec.json` (git-ignored, like all of `private/`).
OpenTofu (`tofu`) plans, applies and destroys it on a Proxmox VE host. The
menu and the form only talk to the engine interface of
`script/opentofu/moteur.py`: `tofu` is one engine behind it, and a Python
engine may replace it later without touching the menu.

## Where to find it

`TODO › Execute › Deploy › OpenTofu`. The menu has four sections:

- **Fleets**: create a fleet, edit it in the form, list the fleets.
- **Operations**: plan, apply, destroy, show the tofu state, show the VM
  addresses.
- **Proxmox**: prepare the host (role, user, API token).
- **Tool**: check or install `tofu`.

The form (a Textual TUI) edits the spec in tabs, with the plan and the
engine log at the bottom. Keys: `s` save, `p` plan, `a` apply, `d` destroy,
`q` quit. While `tofu` runs, the form is busy: the actions and `Ctrl+Q` are
disabled until it returns, so a run is never cut halfway. An apply that
replaces or destroys a VM, and every destroy, asks you to retype the fleet
name. A destroy, from the menu or the form, also removes the VMs' SSH
aliases from `~/.ssh/config`, and so does an apply for the VMs it destroys.

## First run

1. **Tool**: the menu checks `tofu` against `conf/opentofu.json`. Where
   `pacman` exists (Arch), it installs the package; elsewhere it downloads
   the release zip, verifies the checksum file and its GPG signature
   (fingerprint pinned in `conf/opentofu.json`), then installs the binary
   into `~/.local/bin`. Either way it asks for confirmation [y/N] first.
2. **Create a fleet**: a name (`^[a-z][a-z0-9-]{0,30}$`) and the SSH target
   of the Proxmox host. The spec starts with one default VM.
3. **Prepare the host**: over SSH, creates the role `ERPLibreTofu`, the user
   `tofu@pve` and the API token `tofu@pve!<fleet>`, and enables the
   `snippets` and `import` contents on a storage. The token secret is shown
   by Proxmox once: it goes straight into the fleet's `secrets.json`.
4. **Plan**, then **apply**. The plan lists what is created, replaced or
   destroyed; apply creates the VMs, then adds an SSH alias
   `<host>+<vm>` to `~/.ssh/config` (the Proxmox host as jump host). A VM
   marked `installer_erplibre` then goes through the ERPLibre install of the
   QEMU/KVM menu.

## The spec

`"schema": 1`. Top level: `nom` (the fleet), `moteur` (`tofu`), `cible`,
`compte`, `vms`.

| Field | Meaning |
|-------|---------|
| `cible.type` | target kind: `proxmox` |
| `cible.hote` | SSH access to the host: `target`, `jump`, `port`, `sudo` (`"sudo "` or `""`) |
| `cible.api_url` | Proxmox API URL; empty, it becomes `https://<host>:8006/` |
| `cible.insecure` | accept the host's self-signed certificate |
| `cible.noeud` | Proxmox node name |
| `cible.stockage` | storage for disks and images |
| `cible.stockage_snippets` | storage that accepts snippets (cloud-init) |
| `cible.pont` | network bridge |
| `cible.ssh_user`, `cible.ssh_port` | account and port `ssh -G` gives for the host target; the provider uses them to write the snippets |
| `compte.user`, `compte.ssh_key` | account created in the VMs, path of the public key file put in it (default: the first of `~/.ssh/id_ed25519.pub` and `~/.ssh/id_rsa.pub` that exists, else `~/.ssh/id_ed25519.pub`), not the key itself |
| `vms[].nom` | VM name, `^[a-z][a-z0-9-]{0,62}$`, unique in the fleet |
| `vms[].vmid` | Proxmox VMID; empty, the first free one |
| `vms[].distro`, `version`, `arch` | image from the deployment catalog |
| `vms[].vcpus`, `ram`, `disque` | vCPUs, RAM in MiB (512 or more), disk like `20G` |
| `vms[].ip` | `auto`, `dhcp`, or a fixed `a.b.c.d/nn` |
| `vms[].passerelle`, `dns` | gateway and resolvers of a fixed address |
| `vms[].demarrer` | start the VM after creation |
| `vms[].installer_erplibre`, `branche` | install ERPLibre after the apply, on that branch |

The fields left empty are **resolved on the host** the first time and
**written back to the spec**: `api_url`, `ssh_user`, `ssh_port`, `noeud`,
`stockage`, `stockage_snippets`, `pont`, `vmid`, and for `ip: "auto"` the
address (`dhcp` on a bridge that faces the LAN, otherwise a fixed address
derived from the VMID, with `passerelle` and `dns`). A field already filled
is never read again nor overwritten, so a second plan right after an apply is
empty. Each VM's cloud-init is written to the snippet storage as
`erplibre-<fleet>-<vm>.yml`.

Renaming a VM makes `tofu` destroy it and create a new one, **under a new
VMID**: the plan says so and asks for a confirmation. The form clears the
VMID of a renamed VM, and an address derived from that VMID goes back to
`auto`. When renaming in `spec.json` by hand, empty `vmid` (and such an
`ip`) yourself: otherwise the new VM is created on the VMID of the one being
destroyed, and the apply fails.

A spec edited by hand and broken (invalid JSON, missing or mistyped field,
duplicate VM name or VMID) gives a list of readable errors, not a traceback.

## Secrets and state

- `private/opentofu/<fleet>/secrets.json` (mode 0600, directory 0700) holds
  the API token and the passphrase that encrypts the state.
- The state and the plan files are encrypted: the engine sets `TF_ENCRYPTION`
  (key provider `pbkdf2`, method `aes_gcm`, `enforced = true`), so a clear
  state or plan is refused.
- The token and the passphrase reach `tofu` through its environment only:
  never on the command line, in the generated `.tf.json` or in the log, which
  masks them. Every inherited `PROXMOX_VE_*` variable is dropped, since it
  belongs to another fleet or host, and so are the `TF_LOG*` variables, since
  a trace copies the authorization header.
- When `conf/opentofu.json` pins another provider version, the next plan runs
  `tofu init -upgrade` so the lock file follows.
- **A lost or overwritten `secrets.json` makes the state unreadable.** The
  engine then refuses to plan rather than create a new passphrase next to the
  existing state. Restore `secrets.json` from a backup. Without a backup, the
  VMs still exist on the host. Destroy ONLY the VMIDs listed in the fleet's
  `spec.json` (`vms[].vmid`), and confirm each one first with `qm config <vmid>`
  (the name must match the spec); touch no other VM. Then delete the fleet's
  state directory, `private/opentofu/<fleet>/.tofu/`, and run Prepare the host
  again, answering YES to recreating the token: the old token still exists on
  the host with no local secret, so the preparation refuses otherwise.

## Limits of v1

- Proxmox only (libvirt later). No jump host to reach the Proxmox API, no
  USB or GPU passthrough.
- One token per fleet, with the role on `/`. The role carries the privilege
  list of the bpg/proxmox documentation example, which is wider than needed
  and is to be narrowed.
- On a production host, the SSH account that writes the snippets needs a
  restricted sudoers rule: passwordless `/usr/sbin/pvesm apiinfo` and
  `tee` into the snippets directory, nothing more. A host that lets the
  account run any command through sudo needs none.

## Licence

OpenTofu and the `bpg/proxmox` provider are MPL-2.0. They run as separate
programs: nothing of them is copied into this repository. Providers come from
`registry.opentofu.org` only, at the version pinned in
`conf/opentofu.json`; `terraform` and `registry.terraform.io` are never used.

## Long test

`long_test/opentofu_proxmox.py` runs a fleet end to end on a disposable
Proxmox VE: `--dry-run` stops at the plan, `--detruire` removes what the run
built. See `long_test/README.md`.
