
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

**Migration notes**

Recreating the virtual environment, use installation guide from tool `make`.

## Added

- A **Network** section in the QEMU/KVM menu, and the script behind it, `script/qemu/network_qemu.py`. `--status` reads what the libvirt network serves, which bridge carries it, which VMs are attached, what their leases say, and what the host routes elsewhere — nothing is modified. `--recreate` puts the subnet back under those VMs in three ordered steps, and the order IS the feature: the attached VMs are shut down FIRST, since redefining a network under a live VM leaves it with a lease that leads nowhere and a tap no longer on any bridge; then the network is redefined on the wanted prefix — 192.168.122 by default, libvirt's own, the one that ~/.ssh/config entries and old notes assume — and restarted; then exactly the VMs it stopped are started again, a VM already off staying off. A VM that ignores the shutdown CANCELS the redefinition rather than losing its bridge, and `--force-off` is what cuts its power. A target prefix that overlaps what the host already routes is refused: that is how a machine loses its own gateway to a bridge. A network already serving the wanted prefix is not redefined, and the stop-and-start alone still repairs the taps a torn-down network detached
- A VPN tool, five free technologies at the menu — L2TP/IPsec PSK, WireGuard, OpenVPN, OpenConnect, sshuttle — reachable from **TODO › Execute › Network › VPN** and from the Deployment section. What is not secret (host, user, routes, MTU) lives in readable JSON and the pre-shared keys and passwords in a KeePassXC vault, so a profile can be shown, compared and shared without handing over the means to raise the tunnel. Secrets are written to tmpfs at 0700 and never to a persistent disk; `--dry-run` shows every privileged step without running one, and the tool runs as yourself, each step calling sudo on its own. Asking for all traffic through the tunnel no longer cuts the SSH session that gave the order — the operator's address, read from `SSH_CONNECTION`, gets a survival route of its own and every one of them is withdrawn on teardown. Only L2TP/IPsec has been raised against a real concentrator; the four others are starred at the picker as covered by unit tests alone
- `diagnose` names the failing stage lowest first, so the first false line is the cause and not a consequence: what the kernel exposes · packages · the technology's own check · interface and addresses · each declared route · a witness address that answers only through the tunnel · the journals. The kernel stage catches what no configuration can fix: upgrading the kernel package replaces `/lib/modules/<version>` and the running kernel can load no further module, so IPsec turns unavailable on a kernel that supports it, charon aborts at initialisation, and the symptom surfaces three stages higher as a connection never loaded. The only remedy is a reboot, and it is OFFERED, never done: not on a dry run, not without a terminal to answer, and only when the capability is missing AND the modules are gone
- 3D acceleration for QEMU VMs, ticked at creation and settable afterwards, even on a VM with NO virtual screen — `auto` never grants one there, abstaining rather than adding a video device nobody asked for, while an off-screen render or an emulator inside the VM wants exactly that. A render node can exist while EGL refuses to start on it: QEMU then rejects the domain and the VM stays unusable until someone undoes the setting, so creation falls back to software rendering and an existing VM is offered the removal. Inside the guest the render node is `root:render` at 0660 and the account was not in it, so every GL application fell back to software rendering although VIRGL negotiation had succeeded, with nothing to say so; `render` and `video` are now declared BEFORE use, an unknown group name making cloud-init create no account at all — no password, no SSH key, a VM that boots unreachable
- A QEMU diagnostic report, written to one file to hand to someone who has no access to the machine: twenty-one read-only probes — host, hypervisor, GPU, tools present, storage — each time-bounded, since a command that hangs must not hold the report, and each section isolated, the file being written in one block at the end. It states the 3D condition of every VM from its PERSISTENT definition, where three values answer together and none alone: video type, `accel3d`, and the device libvirt pinned. That last one, an attribute added in libvirt 12.5.0 to keep the guest ABI stable across restarts, OUTRANKS `accel3d`: a VM first started without 3D keeps the non-GL device, and ticking the box afterwards writes an intent nothing applies. The report also offers the tools missing from it, showing the full command before asking, and the device list QEMU may open — libvirt adds the render node when the domain declares it, never a proprietary card's own nodes, which that stack opens too. It names the host, its paths and its addresses, and says so before it is shared
- Recovering files from the disk of a VM that no longer boots, libguestfs mounting its qcow2 without it. Every command carries `--ro`, and that is what changes the manoeuvre: opening the disk of a running machine for writing corrupts its filesystem. Partitions are listed, then the directories to copy out, the `copy-out` commands being shown rather than guessed at
- Development assistants installed INSIDE a VM at deployment, and the pre-configuration that makes them usable without retyping anything: rtk with its global auto-rewrite hook, starship with its shell hook, one agent — Claude Code or opencode —, tig, htop and vim, `merge.conflictStyle=zdiff3`, the checkout's git hooks, the five Claude commands of the repository, and `source .venv.erplibre/bin/activate` in the shell history, where the up arrow finds it. The box reveals the choice and the git identity, prefilled from the host, since that is what the VM already receives and an empty field would suggest none; what is typed wins, field by field. Every install is denied stdin and time-bounded: `|| true` covers failure, not WAITING, and an upstream installer asking a question would hang on a terminal-less SSH — hence `-y` for starship. The option works in TWO phases, and the second is named rather than silently dropped: hooks and command templates LIVE in the checkout, so a VM that installs nothing gets the installs and is told what the missing clone costs it. `core.editor` is only posed where there is none, the host's editor already travelling to the VM's `~/.gitconfig` — two authorities over one setting is one too many. Everything in that second phase returns 0: a pre-configuration is a comfort, and the install alone carries the VM's verdict
- An option's help at the deployment form, opened by `?` or F1 and closed by Esc: what each install setting POSES in the VM, listing every step rather than the two or three a checkbox label has room for — the AI tools box alone engages eight. The text lives in the same table as the boxes, so an option added without help shows an empty block instead of a wrong one, and both screens read it, the QEMU/KVM one and the Proxmox VE one
- A Git and Shell menu that installs what a checkout needs rather than printing a command to copy: the repository's git hooks, `merge.conflictStyle=zdiff3`, Starship, Claude Code, opencode, and the Claude Code plugins with an ERPLibre list. Three assistant commands are deployed from it — `/git_prepare_merge`, `/todo_plan_max`, `/todo_generate_code`. The missing tools of a safe shrink are installed across the four package families, where three separate pieces of code each knew a different subset. A binary posed in a HOME directory the shell's PATH does not always carry is found anyway, and the export line is written once
- A deployment blocked by an orphan disk — the qcow2 an interrupted creation leaves behind, which `deploy_qemu` then refuses to overwrite — is offered its deletion, size and path shown, before the creation fails after having made you wait
- A `pre-commit` hook lists the comments worth re-reading in the files being staged, and never blocks: over the repository's own sources, 373 files yield 463 signals, and a blocking check at that scale gets uninstalled the following week. The tool behind it, `script/analyse/check_comment_hygiene.py`, reports two families of unequal certainty — identifying data, an address, an e-mail or an account path, which is a finding; and narrative, a witness marker, an absolute date or the first person, which is a signal to RE-READ, since it cannot know whether the sentence states a durable fact. It reads comments and docstrings, `#` lines and shell trailing comments alike, skips vendored code, and falls back on a line scan when a source will not parse, an empty report otherwise declaring clean a file it never read. Exit codes follow the repository convention: 0 nothing to report, 1 findings, 2 the tool failed
- The TODO menu shows the context an assistant is given, scattered as it is over six sources: instructions, rules, skills, deployed commands, git hooks and memory. Each deployed command is compared against its repository template, ignoring the git identity lines the deployment substitutes, so a stale copy shows up where a strict equality would declare them all stale. Nothing from `private/` is reported, not even a count: naming a file whose purpose is to hold what must not go out amounts to pointing at it
- Duplicating a database and neutralising it for good: duplication goes through Odoo's `exp_duplicate_database` rather than `CREATE DATABASE … TEMPLATE`, which copies the tables and nothing else. Only Odoo drops the source's open connections — one Odoo shell left open is enough for PostgreSQL to refuse — regenerates `database.uuid`, copies the filestore, and runs the `neutralize.sql` files of the installed modules. The repository's in-house modules obtained none of the four, and one of them opened a door: deleting every `ir.mail_server` makes Odoo fall back on the configuration file's `smtp_server`, where Odoo's own placeholder server exists precisely to plug that hole. Odoo's neutralisation begins at 16; from 12 to 15 the copy falls back on the repository's long-standing `update_prod_to_dev.sh`, which sets no `is_neutralized`, disables no cron and leaves the payment keys, but does remove the mail servers and lay down a development account. The route taken is ANNOUNCED at run time, a copy whose route is unknown being unjudgeable, and a missing script fails the copy rather than letting it come out raw while announcing itself neutralised
- The migration quality screen says whether a run succeeded, where it only compared the tiers: every verdict shows, 12 through 18 — the only way to see that a failure at one tier was recovered higher up — read from the progression file and tied to the ODOO tier, not to the driver's counter, which is off by one. It names where the traces live, config.conf leaving logfile= empty and Odoo's output dying with the terminal; it shows the step-log passage around each command, keeps by tee what it launches itself and re-reads that without rerunning; and it runs six review steps from « r », asking before it switches the checkout, since replaying a test from another tier opened the database with the wrong version, which writes before it fails. A status is read the way the tools write it — 0 nothing to report, 1 findings, 2 the tool failed — so nothing is painted red where nothing failed. Output is captured through a pseudo-terminal, never a pipe: smoke_public_url requires stdin AND stdout to be terminals and, behind a pipe, silently stops offering the COW view repair; nine runs go through it, two stay out, pty.spawn being born 0×0 where a full-screen tool would lay out on nothing
- Three checks join the migration review, each for what a tier destroys without reporting a single failure. The manifest holes: an addons repository absent from one tier's manifest does not exist on disk during that step, so Odoo declares its modules missing, the driver offers to delete them, and the feature leaves with them — only the hole counts, present before and after, absent in between, which turns 35 candidates into 19 real omissions instead of 46% noise. The tree view type, removed in Odoo 18 with no shim, is read in the SOURCES, where every other review tool reads the database and a module that never installed leaves nothing; the word is still a valid identifier, so of 465 occurrences only 80 break, and lxml and ast decide by the literal's position, never a regex. The chart drift: a bump reloads the localisation template in silence — three of the core l10n scripts call try_loading() without force_create=False, so every account the template cannot match by code is CREATED, and the groups thus added reclassify the existing chart. An absolute count says nothing there, only the GAP between two tiers of one migration can be judged, and the tool prescribes replaying the tier rather than repairing: its natural deletion key also catches accounts re-matched by code
- run.sh warms the registry over HTTP while the server starts. Odoo loads a database's registry only on the FIRST request that concerns it, and on a migrated database whoever opens the page waits tens of seconds; the probe takes that time instead and stops at the first answer, a 303, a 404 or a 500 all proving the registry is loaded. It cannot get in the way: it ALWAYS returns 0, dies with run.sh through a trap, gives up after two minutes, and takes the port from the command line, then config.conf, then the log, exact even when the requested port was taken — an empty or wildcard listen interface is probed on the loopback. `--erplibre-disable-warmup-http` turns it off and is the only flag STRIPPED before odoo_bin.sh, which Odoo rejects; `--no-http` and `--stop-after-init` turn it off too and go through, there being nothing to wake when no one listens
- A writing convention for what stays in git. A commit subject read alone, with no diff and no body, must say which part of the system changes and what is now different there — the symptom, the quoted error and the metaphor are EVIDENCE, and evidence belongs in the body. A comment has the CODE for subject, in the present of what it does, so a sentence whose subject is an incident, a machine, a date or a person goes to the unversioned `tasks/`, while the failure mode the code prevents stays. Nothing identifying outside `private/` — no customer, real database, host, address, e-mail or account path — and an example illustrating that ban is invented rather than borrowed, a test freezing forever what it holds. A measurement that establishes a durable fact stays, stripped of its date and its operator; the reading of what answered that day goes
- A `commit-msg` hook refuses the mechanical part of that writing convention and nothing more: no tag, a subject over 72 characters, a subject opening on a quotation, a body over 10 lines for one language, an IP address, an e-mail, an account path, or a term from a forbidden-names list that lives outside git since the list is what it protects — absent, that last check stays silent. It counts characters, not bytes, or a 72-character French subject would fall on its accents; it excludes the trailers and the `--cleanup=scissors` diff; and its refusal names `git commit --no-verify`, a guard rail that refuses too much getting uninstalled. Whether the subject says what the code is about stays a judgement no hook makes. The predicate telling a fleet address from an Odoo manifest version, a loopback, a mask, a network address or an RFC 5737 documentation block is shared with the comment check, two predicates for one question drifting apart. Its 40 tests weigh the acceptances — a « Merge branch », a rebase fixup — as much as the refusals
- `long_test/` — tests that create real machines and take hours, kept out of `test/` so the unit runner stays runnable in seconds. `deep_proxmox.py` stacks Proxmox in Proxmox, `deep_qemu.py` stacks QEMU in QEMU, and they share one engine. Measured on 28 cores: three levels cost 34 minutes, the fourth 4 h 20 of boot plus 7 h 18 of install — everything there is 15 to 30 times slower, and that is where the vendors stop documenting nesting. The depth is a parameter and defaults to three, because three works
- deep_qemu proves KVM at every level instead of assuming it: `deploy_qemu.py` never passes `--cpu host-passthrough` and, when /dev/kvm is missing, it does not fail — it sets `--virt-type qemu` and creates a fully EMULATED VM, seven and a half minutes to boot, with no exit code to say so. Unguarded, the descent would measure stacked TCG while believing it measured nesting. Each level must show `/dev/kvm`, `nested=Y` and a child domain in `type='kvm'`; what was not read counts as NO
- Both long tests take `--hote` to start from a machine you already own, rather than creating a head VM to host a hypervisor you have on hand — that costs five minutes AND one level of nesting. The plan is then sized on the ROOT, read over ssh; the delays count ABSOLUTE depth; and the root is never a level reached, never destroyed, and its ~/.ssh/config entry is never removed
- Support Odoo migration database and module with TODO
- Support multi version odoo switch on same workspace
- Script for hardening the installation
- Support Odoo versions 12.0 to 18.0
- Separate ERPLibre python installation from Odoo python with .venv.erplibre and .venv.odoo18
- Implement auto-installation with TODO.py
- TODO show documentation, download database, help with code formatting
- Performance script to mesure request per second
- Support Mainframe architecture 390x
- Deployment with Cloudflare and Nginx
- Support Apache configuration like Nginx
- Support RobotLibre code generator
- Support ERPLibre DevOps, automation procedure about DevOps
- ERPLibre Home Mobile Application, use TODO to compile, deploy it and personalize it
- Support Selenium grid from selenium_lib.py
- Add addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor
- Deploy ERPLibre VMs with QEMU/KVM from cloud images (Ubuntu, Debian, Fedora, AlmaLinux, Rocky Linux, openSUSE Tumbleweed, Arch) on amd64, arm64 and s390x, with a menu to list, test, resize, delete and clean up
- Graphical VMs: a server / desktop choice offering GNOME or Cinnamon (the Linux Mint desktop), with remote access through xrdp — TigerVNC on Arch
- Textual interfaces: install dashboard, VM deployment form, migration resume
  screen; Textual is installed on demand
- Navigation telemetry for TODO, as a tree, a kanban or a list
- Migration tools for the website copy-on-write views: predict, snapshot,
  diff, neutralize and reset
- Read-only analysis toolkit for an Odoo database
- SSH configuration with recursive ProxyJump, port forwarding, and
  registration of the QEMU hosts in virt-manager
- NTFY self-hosted push notification server
- Generative AI policy, adopting the OCA one
- Claude Code agents and commands
- Local git server to share code between machines
- Unit tests for the configuration, the refactoring and the uncovered
  components, with a bilingual test plan
- Read and send email from the TODO CLI, over IMAP and SMTP
- The database analysis reads a backup zip directly, without restoring it
- RTK management menu
- AI assistant tools menu, with the Claude Code commit command
- Deploy menu: clone ERPLibre on a remote host, configure sshfs, and make
  targets for SSH deployment
- Database backup and erase commands, and a clearer restore naming
- Git patch, git remote and vim configuration from the menu
- Security check of the Python environment
- Odoo 18 reads STL files (OpenCAD)
- Mobile: whisper.cpp and sentencepiece in the manifest, a mobile test script,
  and the Odoo sync API contract
- FAQ entry on wkhtmltopdf for recent distributions
- brin_advisor and brin_cluster: recommend and apply the right PostgreSQL
  index for an Odoo model
- Per-VM settings in the deployment form: vCPU, RAM, disk, type, ERPLibre branch, Odoo version and timezone, a lock that shields a VM from the global profile, renaming, and several copies of one entry
- Python interpreter provider chosen through EL_PYTHON_PROVIDER — mise lays down a precompiled CPython, pyenv builds one — and picked per deployment
- uv places the Python packages, pip as fallback, through EL_PIP_PROVIDER
- openSUSE Leap 16.0 and Fedora 43 in the VM catalogue
- Application store of a graphical VM: .deb only, Flatpak tooling, or snap
- Remote desktop tunnel: the SSH command is composed from ~/.ssh/config, with the hypervisor console as a third route
- The install dashboard acts on a VM without leaving it: update by parts, restart Odoo, delete; architecture column and resizable columns
- Migration: go back to a step from the resume screen or from a prompt, and act on the COW copies as soon as they are announced
- The website copy analysis diffs each copy against the view it shadows
- A test checks that what the tooling imports is declared
- Automated Odoo migration: the tool drives the whole run -- repair, replay, an auto-run that takes the default after five seconds, and a countdown that names the answer it is about to take
- Migration state screen: « t » shows where a run stands, with coloured commands, elapsed time, the server log read for you, and one log file per step on disk
- Migration quality: what a run gained and lost step by step, the missing files named, Odoo's own redesigns told apart from real losses, and OpenUpgrade's declared changes laid over the real ones
- Migration repairs: the customized SCSS the next bump breaks, predicted then fixed; themes uninstalled before the first bump; DMS visibility restored; views whose stored type contradicts their parent; and the <tree> tags Odoo 18 renamed to <list>
- Smoke tests after a migration: every public URL requested, /my and every app opened as the neutralization test user, the views behind a failing URL named, and the OCA database cleanup run first
- Filestore check: whether the attachment files landed, whether the record still exists, and the cleanups offered on the spot
- Analysis: the modules a database lacks against the default package, with an offer to install those that are ready, and the attachment files that are truly unrecoverable
- Debian on s390x through debian-installer, no cloud image being published for that architecture
- A mobile development VM: PyCharm, Android Studio, GNOME extensions, an Android emulator and an adb tunnel for scrcpy, with the mobile app built and tested inside it
- Forgejo, a git forge installable from the deployment menu
- VM hardware set per machine: the host GPU, the CPU mode, the screens and the network
- virt-viewer opens a VM screen from the menu
- The install dashboard shows the host RAM, a VM's used RAM and uptime, and how long a log has been silent
- A VM greets its SSH login with the distribution's own commands
- Proxmox VE as a deployment target: deploy a VM on a remote Proxmox host from a screen that recaps in the terminal before creating, creates the missing bridge, follows the VM and changes its state, shows its Odoo column and the web link, and deletes it from the host. Every remote VM now comes with its connection guide, which was missing from the start
- Repairs for what an Odoo bump leaves behind: website copies that no longer render — predicted BEFORE the bump rather than found as a 500 after it — the indexes Odoo 17 creates twice, and the settings no event restores
- Analyses that read a database rather than count it: which module depends on which, on screen; what is installed, in progress and applied; the state of an instance read for the use made of it; and the examination of a database that is not local
- Anonymising a copy without AI: a production copy exists to reproduce a defect, so identifiers stay consistent across tables once the names are replaced
- Per-VM statistics: writes, RAM and disk
- Choosing the database at startup without ever blocking on the choice
- The reboot is part of installing Proxmox VE: install_proxmox.sh lays down the kernel and stops, rightly so, because launched over ssh a reboot would cut its session and make the install look failed. The reboot now belongs to the launching wrapper, which runs on OUR machine and survives the VM's — install, reboot, wait for `uname -r` to carry the Proxmox kernel, then verify. The ✅ is written only after that, so it means "usable hypervisor"

## Changed

- The name of a VM built from a rolling release drops the version segment: `latest` distinguishes no VM from another. A named version that coexists with others in the catalogue stays
- Every menu entry carries an icon, ten menus having stayed bare, and the spacing follows the RENDERED width read from Unicode rather than guessed — two spaces after a one-column emoji, one after a wide one. The QEMU Manage section, grown too long to scan, is split into Manage, VM access and Troubleshoot
- Staging names the files, never `git add -A`. The sweep stages everything untracked, and this repository keeps two directories untracked ON PURPOSE: `private/`, the only place allowed to hold customer data, and `tasks/`, where the convention sends the investigation precisely because it is not versioned. It also swallows whatever else is in flight in the checkout, under a subject that does not cover it; `git add -p` stages the hunks when one file carries two subjects
- A countdown prompt gives 15 seconds to decide, where five were not enough to READ the question: the countdown exists so a run can be left unattended, not to go fast, and too short it does the opposite — the answer comes by reflex, or a default no one read is taken. A restored database is named after the backup file, which already carries a telling name, rather than « test », under which successive migrations all landed on one name. The name is sanitised, since it ends up in a createdb, and capped at 41 characters: the driver appends « _neutralize_upgrade_18 » and PostgreSQL truncates at 63, which would put two tiers on the same name. A remote download keeps the name the server gave
- todo.py split into nine files, one per subject, with a shared base per form. It carried 9 500 lines more than a file should and every subject went through it; the deployment forms repeated the same field-and-validation machinery, so a fix in one never reached the others. No behaviour changes
- Branch, profile and type are chosen per VM. They were global, which meant switching everything to deploy a single machine differently
- One shared base describes the guest system, where each form used to describe it again

## Fixed

- A deployment says WHY it needs a password before sudo asks for one, and on what it checked. sudo never states what it is about to do: the prompt lands between two log lines, and one types a password without knowing whether it covers libvirt, a package or a file — the more so as being in the `libvirt` group looks like it should be enough. It is not, and libvirt is not the reason: the disk and the cloud-init seed are written into libvirt's default pool, a root-owned directory where the group grants no write right at all. The reason is therefore CHECKED and not asserted — writing is tested, since an ACL can grant it where `drwxr-xr-x root root` seems to refuse it — then named with the directory, its owner and its mode, next to what the group really does cover: the qemu:///system socket, probed by trying. Said once per run, before the first privileged command, and last on the final review page, which is the screen right before the prompt. Root is told nothing, no prompt being due; a missing virsh reads as missing rather than as a group at fault
- A libvirt network no longer counts as its own collision. A started network carries and routes its /24 on its bridge, and that bridge was read as « the host already occupies this », so the verdict was « collision » on every machine where the network ran, whatever subnet it served. `--setup-host` — and every deployment, which calls the same check — then tore the network down and moved it onto a free /24 where nothing conflicted, leaving the VMs attached to it without a gateway and with a detached tap. The bridge of the network being examined is now excluded from what the host occupies, addresses being read one interface per line so each address can be tied to its own; an unreadable bridge name excludes nothing, silence weighing on the cautious side. The XML handed to `net-define` goes through a real temporary file, unpredictable and removed even when virsh fails, where a name composed of the network's own was a guessable path in a directory everyone writes to
- `--setup-host` no longer leaves a machine that loses its network at the next boot. libvirt's `default` network serves 192.168.122.0/24, and every VM this repository deploys LIVES in that network: its bridge would take the .1 address, which is that machine's own gateway. virsh refuses such a start — but only while the route is there, and at boot libvirtd raises its networks BEFORE the host's DHCP lease arrives: nothing signals the collision any more, virbr0 takes the gateway address, and the host has no network left. Autostart was armed even when the start had just failed, and the message then advised a reboot. The network is now MOVED onto a free /24 by redefinition, which needs neither bridge nor kernel module and therefore works where the start does not, keeping its UUID, bridge name and MAC so the domains naming it still find it; autostart is armed only where no collision remains, and REMOVED where one does. A network found active on a route of the host is torn down first — that is the already-broken machine, and it is what gives the host its network back, before anything else needs downloading. One reboot still suffices where the only obstacle is a kernel replaced since boot
- The state of a libvirt network is read in English. virsh TRANSLATES its labels: under a French locale `net-info` answers « Actif : non », where a pattern on `Active: yes` never matches — so every network read as off, `--setup-host` declared the host not ready whatever its state, and its advice was to reboot for nothing. Every parsed virsh output now goes through one call that forces `LC_ALL=C`, the same gesture, for the same reason, as the QEMU management screen
- The KeePassXC vault opens on a machine without tkinter, which is every server. Both imports shared a single `try`, so a missing tkinter set PyKeePass to None as well: the vault stayed unopenable even with path and password configured, while the log said `pykeepass is not installed` and pykeepass 4.2 was there. tkinter serves only the file picker, when no path is configured. The prompt also names the vault before asking for its password, rather than after
- The QEMU menu goes through the `libvirt` group rather than sudo, which added no right and asked for a password at every entry; membership is settled by TRYING, never by reading /etc/group. The libvirt URI is named explicitly: without `--connect`, a non-root virsh targets `qemu:///session`, a SEPARATE hypervisor where no system VM exists, and `list --all` returns an empty list with no error — root's default URI had masked the omission
- System tools launched from the menu no longer inherit the venv at the head of their PATH. A Python tool bootstrapped by `env python3` started in an interpreter without the distribution's modules and died on `No module named 'gi'`
- Accepting to install the QEMU packages no longer reboots the host without asking: `--assume-yes` covered the package manager, and the command silently added `--reboot-if-needed`. One constant served both the disposable guest and the workstation
- Three screens that fell over: the statistics screen, where `datetime.datetime` does not exist since the CLASS is imported and the error took all of TODO with it; a failed VM whose output showed four lines of epilogue instead of the tool's own message; and a duplicate i18n key silently overwriting a main-menu label, the last definition winning in a Python dict literal with neither error nor warning
- A shrink measures the free space BEFORE offering the backup, which doubles the space used and defaulted to YES: on an almost full disk, an empty answer started a copy that stopped halfway and left a truncated `.bak`
- `odoo_bin.sh db --drop` failed with AccessDenied at every migration tier, and the clone then hit « database already exists »: db_restore.py reads the repository's config.conf, sees admin_passwd = admin and therefore sends no master password, while odoo_bin.sh passed no « -c », so Odoo read ~/.odoorc and its hashed one. ODOO_RC closes that seam in one place instead of twenty call sites, versions 12 to 18 reading it after « -c » and before ~/.odoorc, so an explicit choice still wins
- The account.root SQL view Odoo 17 creates is dropped before the load into 18, where the model carries _auto = False and _table_query = '0', so its name enters no query and the missing-table check skips it. The view is not merely dead but WRONG, built on the code column the 18 ORM no longer writes, and it is the sole pin holding the two legacy columns database_cleanup fails on — no DROP COLUMN, OpenUpgrade still reading them afterwards
- The migration repair created pricelists that should not exist, in two ways. It asked `env.user.has_group()`, which says yes as soon as the caller belongs to the group — and the migration adds it along the way — where the settings checkbox reads something else entirely: what `base.group_user` IMPLIES. Deciding on the caller built a pricelist in a database whose feature is off, and Odoo then warned on every opening of the settings that it would archive it. And a pricelist shared across companies, with an empty `company_id`, did not count as belonging to the company: the repair saw a company without a list and made an empty duplicate beside the existing one, on a database that had lost nothing. Both now read the group implication and the tool's own `pricelist_missing` detector, which already tells the two cases apart; the migration-residue check asked the same wrong question and was corrected with them
- The anonymisation blacklist handed its SQL to psql as a single argument, and Linux caps one argument at 131 072 bytes: the mode that covers the most tables was exactly the one that broke, on « OSError: [Errno 7] Argument list too long ». The SQL now travels through a file with `-f`, which keeps the `--single-transaction` that standard input would have silently dropped. Text columns with a declared length are truncated by `left(…, n)`, the id FIRST so a unique column stays unique, and every identifier is quoted — Odoo allows a field named user or order. Skipping every column under a CHECK constraint had left the partner name untouched: on text, only FORM constraints are out of reach, and an UPDATE that fails writes nothing
- Anonymisation respects what a value MEANS, where the SQL type says only what it IS. Odoo declares `parent_path` as `char` but stores an id path in it — 1/7/12/ — parsed straight back with `int()`, so a name written there breaks the first page load; every `_parent_store` model carries one, and `account_payment_term.days_next_month` goes to `int()` the same way. The two known names are skipped, then the content itself is probed: a column whose every value is a path is left alone, even in an in-house module, and the slashes are required, so a value of pure digits does not escape anonymisation by passing for an id. Numbers were drawn uniformly over 0 to 1000, which is wrong for every number bounded by its usage — hours, percentages, rates: a float holding an hour of day, drawn outside 0..23, makes displaying the record raise « ValueError: hour must be in 0..23 », a bound that lives in Odoo's Python where no PostgreSQL constraint declares it. The draw now respects the only bound the DATA declares, its own range, min and max measured per table; 0 to 1000 remains solely for a column that is empty or cannot be probed
- The unit runner took seven filename prefixes, « the rest needing a database », and ran 1131 tests where all 3703 in the directory pass with PostgreSQL unreachable; it globs test/test_*.py. Two shapes make a file silent without an error — unittest.main() placed mid-file, which exits before the second half is even defined (four files, 87 tests), and no __main__ block at all, which counts zero (eight files, 174 tests) — and a guard now refuses both, along with any return to a list of prefixes
- The mobile bundle check accepted only the pack layout, when a real build ships one tar.gz per repository. It failed on `<slug> : index.json absent` and stopped `compile_and_run.sh` before the APK — since 2026-08-20, for anyone on the current mobile main. It now accepts both layouts, and proves the presence of EVERY promised file rather than a sample of twenty: streaming all 139 archives costs 6 s, and 124 350 files are accounted for
- The bundle test guarded the ZIP entry limit by demanding a `chunk` field on every file, which is the pack layout rather than the limit itself. It now counts the entries the APK will carry — 278 against a ceiling of 65 535 — so either layout passes and a return to file-per-source still fails

- The 13-to-18 migration rested on assumptions: a percent-encoded page anchor the parser could not read, web_responsive that does not survive the bump to 18, a failed OpenUpgrade that passed for done, a rebuilt clone that kept the old one's preparation, and one faulty module taking the whole uninstall batch down
- Proxmox aimed at the wrong machine: the install went to the host instead of the VM, the disk it reported was the host's, and four screens spoke of a local machine while driving a remote one. The jump host is now the only route to a VM — aiming directly worked only while the VM had a routable address. Six further defects came from an audit rather than from use
- One name per `~/.ssh/config` entry, and the old one leaves with the convention that replaced it
- Monitoring no longer bins a VM before being sure, and deleting from a reopened monitor checks the VM's identity first
- sshfs announced a mount that had not happened
- Odoo 15 declares xlsxwriter, which report_xlsx has always needed
- The db_restore master-password probe validated nothing
- An analysis looked for the price list's external identifier rather than the list itself, and reported fields that had never held data
- The NAT bridge was written before knowing whether NAT exists. Six lines of iptables and "return code 1" came after the stanza had already gone into /etc/network/interfaces, and nothing in that noise said a reboot was needed: the host was running Debian's cloud kernel, stripped of netfilter. Our own install_proxmox.sh produces that state, so a freshly installed nested Proxmox is ALWAYS in it — the guard now sits where the consequence is, not at host confirmation
## Removed

- The residue check that called a language broken when its res_lang row has active at NULL — listed nowhere, no longer re-enablable. False in the 18 source: an ('active','=',False) domain compiles to (IS NULL OR = FALSE), the Languages menu action carries active_test: False, sorting goes through COALESCE(active, FALSE), and reading returns bool(value). Odoo writes that NULL itself, active being a Boolean with no default and res.lang.csv having no such column, which makes one NULL per language added to the catalogue — so « zero before, nonzero after » is not enough to declare a residue. A test now refuses a verdict key that nothing defines any more
- Ubuntu 20.04 and 22.04 support, on every architecture: pikepdf needs qpdf 12.2, whose build requires C++20, while focal ships GCC 9 and publishes no `g++-10` for s390x

## Changed

- Docker support postgresql 18
- Format script search diff file into each repository
- Support neutralize database from Odoo
- Installation supports Fedora, Debian, Ubuntu and Arch Linux
- Repository sync and poetry install run in parallel, up to 50 % faster on a
  slow connection
- CybroOdoo extra modules become opt-in, tracked per Odoo version
- Node.js 22, required by Capacitor 8 for the mobile application
- Poetry and repo are quiet by default; EL_VERBOSE restores the output
- TODO menus grouped into sections with icons, and English text used as the
  i18n key
- Documentation is bilingual, generated from the .base.md sources
- A VM inherits the timezone of the host that creates it
- First boot no longer waits on snapd, locale generation or the guest agent
- apt picks the fastest reachable mirror before the official archive
- Selenium: download through a network hub, SVG to PNG, error detection,
  multiple clicks and updated drivers
- Odoo can run on a custom database; queue_job setup and SSH forwarding
  options in the menu
- Killing a process by port asks before acting, with an interactive menu
- LinuxMint 22.3 supported
- Odoo 18 dependencies: flanker, orjson, python-magic, tldextract, PyYAML
- Copyright year updated to 2026
- Canadian pacman mirrors placed first on Arch, the official geographic mirror measuring four times slower from Montréal
- A Poetry dependency can be declined per architecture: factur-x is pinned to 3.x on s390x, where saxonche publishes no wheel, and PyMuPDF is set aside there
- Enter targets the highest supported Odoo version, the default being computed from the menu
- A make target runs the unit tests, with the mobile dependency declared

## Fixed

- A failed installation is no longer reported as a success: the exit code is
  propagated through the whole chain
- --with_extra now applies to an already-installed environment
- The addons path no longer points at a repository the Odoo 18 manifest never
  clones
- repo init receives a branch name, so a fresh install no longer fails
- The install monitor follows a VM whose DHCP lease changes
- Installation on Debian 13, Fedora and Ubuntu 26.04: apt lock, wkhtmltopdf,
  SELinux and the missing C compiler
- Documentation accents and the parallel markdown generation
- The s390x build chain, on Debian as on EL9, EL10, Fedora and openSUSE: missing compilers and headers, Rust for cryptography and bcrypt, qpdf for pikepdf, libclang for pymupdf, package names that change across releases, and a batch that failed on one unknown name without ever naming it
- A graphical desktop install froze for thirty minutes on a snap package that could not reach the store
- The compiler was killed for lack of memory while building CPython on a small s390x guest
- The README listed neither Fedora, openSUSE, Linux Mint nor Debian 13, all of them supported
- The COW migration tools and the database upgrade speak the system language
- The analysis and migration tools are executable
- The forgejo installer no longer echoes the administrator password it has just set
- The Selenium login re-sent the configured default instead of the credentials it was given, when it retried after dismissing a modal
- db_restore asks the master password again instead of dying on a typo
- pyproj needs the proj binary, not only its headers, and PROJ is built where the distribution lags behind
- run.sh is launched through bash, against systemd's 203/EXEC failures
- pykcs11 compiles with SWIG 4.3 and above
- os-release replaces lsb_release, and an IP collision is easier to see

## Security

- Passwords and tokens are redacted before a command is displayed or logged
- The Odoo master password no longer travels on the command line: MASTER_PWD carries it, and /proc/<pid>/environ is readable only by its owner where /proc/<pid>/cmdline is readable by every user on the machine (needs the matching commit in the odoo fork)
- The KeePass password reaches the Selenium login the same way: the command carries the NAME of an environment variable, never the value
- What a command PRINTS is redacted like the command itself: a tool that reprints its own arguments no longer puts the secret back into the terminal and into the log file


## [1.6.0] - 2025-04-25

## Added

- Support multiple Odoo versions (12.0, 14.0, 16.0) in same workspace
    - This will help for the migration of modules
- Selenium script for increasing open software client interface and automating some actions.
    - Video recording
    - Support scrolling and word generating
- FAQ about kill git-daemon
- Supports Arch Linux, Ubuntu 23.10 to 25.04
- ADD repo JayVora-SerpentCS_SerpentCS_Contributions
- ADD repo CybroOdoo_CybroAddons

## Changed

- Refactor image_db regeneration, use configuration JSON to build image
- Guide for moving dev to prod
- Update Docker buster to bullseye
- Improve format script to help code-generator
- Improve PyCharm script
- Support OSX for open-terminal
- Remove docker-compose and replace by docker compose
- Update Poetry 1.3.1 to 1.5.1
- Test can be launched with a json configuration and support log/result individually
- Script to search docker compose into the system
- Script search class model can output into json format and support field information
- Improve Docker minimal installation docs in README for Ubuntu, test with
  Debian (https://github.com/ERPLibre/ERPLibre/issues/73)
- Statistic script showing evolution module into ERPLibre supporting Odoo 17 and Odoo 18
- Latest version wkhtmltopdf 0.12.6.1-3

### Fixed

- NPM installed locally and not globally
- Improve python code writer efficiency
- Config generator supporting space into ERPLibre directory
- Script to update Poetry to support @ URL
- OSX and recent Ubuntu installation
- Cloudflare script integration


## [1.5.0] - 2023-07-07

**Migration notes**

Recreating the virtual environment


```bash
rm -rf ~/.poetry
rm -rf ~/.pyenv

rm ./get-poetry.py
rm -rf ./.venv

make install
```


Do a backup of your database and update all modules :


```bash
./run.sh --no-http --stop-after-init -d DATABASE -u all
```

## Added

- Support Ubuntu 22.04 with installation script
- Module mail_history and fetchmail_thread_default in base image DB
- Makefile can generate image DB in parallel with `image_db_create_all_parallel`
- Makefile can run all code_generator with `run_parallel_cg` and `run_parallel_cg_template`
- Script to generate Pycharm configuration and exclude directory
- Support docker alpha+beta
- Limit memory execution when install in develop
- Template nginx configuration
- Script code count statistic
- Script show OCA evolution module statistic
- Windows development support, check documentation installation
- New project (code generator to create module) support params configuration
- Module sync_external_model to synchronise Odoo models with module

## Changed

- Odoo 12.0 update from 22-07-2020 to 01-01-2023
- Update pip dependency with security update
    - Pillow==9.3.0
    - psycopg2==2.9.5
    - Werkzeug==0.16.1
    - check diff of file pyproject.toml for all information
- Update to Python==3.7.16
- Update poetry==1.3.1
- Update multilingual-markdown==1.0.3
- Update imagedb with all Odoo update
- Repo documentation-user from Odoo change to documentation
- Repo odooaktiv/QuotationRevision is deleted
- Update all repo (91) to end of 2022
- Rename module project_task_subtask_time_range => project_time_budget
- Rename module project_task_time_range => project_time_range
- Refactor script emplacement, create directory in ./script/ per subject
- Use command parallel in Makefile
- Update sphinx version
- Improve script location

### Fixed

- Debian 11 installation script
- Test result
- OSX installation (not finish to support)
- Poetry update support '~='

### Removed

- Ubuntu 18.04 is broken, need to install manually nodejs and npm
- Module contract_portal and remove signature in portal contract, need an update
- Downgrade module helpdesk_mgmt to remove email team and tracking field
    - Module helpdesk_partner
    - Module helpdesk_service_call
    - Module helpdesk_supplier
    - Module helpdesk_mrp
    - Module helpdesk_mailing_list
    - Module helpdesk_join_team
- Module project_time_management
- Support of vatnumber, too old
- Deprecated python dependency like pycrypto


## [1.4.0] - 2022-10-05

**Migration note**

- Update module `website`,`website_form_builder`.
- For dev, run `poetry cache clear --all pypi`

### Added

- Script run_parallel_test.sh to execute all tests in parallel for better execution speed
- Documentation to use docker in production
- Add repo:
    - Ajepe odoo-addons to support restful
    - OmniaGIT Odoo PLM
    - MathBenTech family-management
    - erplibre-3D-printing-addons
- Add module:
    - iohub_connector to support mqtt
    - website_snippet_all to install all snippets, extracted from all themes
    - website_blog_snippet_all to install website_snippet_all with website_blog and associated snippet
    - sinerkia_jitsi_meet to integrate Jitsi
    - erplibre_website_snippets_jitsi to integrate Jitsi in snippet, work in progress
- Add module by default:
    - auto_backup
    - muk_website_branding
    - website_snippet_anchor
    - website_anchor_smooth_scroll
    - crm_team_quebec
    - partner_no_vat
- Documentation Odoo dev
- Format command supported addons
- Install theme with Odoo command
- Script to install theme addons
- Image website with default theme
- Image erplibre demo
- Test with coverage

### Changed

- Downgrade sphinx to 1.6.7 to support Odoo dev documentation
- Update to poetry==1.1.14
- Update pip dependency with security update
    - Pillow==9.0.1
    - PyPDF2==1.27.8
    - lxml==4.9.1
- Code generator export website with attachments and scss design file with documentation
- Code generator support multiple snippets
- Into repo Numigi_odoo-project-addons rename module project_template to project_template_numigi
- Into repo Numigi_odoo-product-addons rename module product_dimension to product_dimension_numigi
- Into repo Numigi_odoo-partner-addons, re-enable auto-install module
- Into repo muk-it_muk_website, re-enable auto-install module

### Fixed

- Poetry supports insensitive python dependency
- Code generator new project supports relative path and check duplicated paths
- Muk web theme table header background-color and on hover for Many2many
- Script docker-compose use lowercase name
- website_form_builder HTML support and allow option to align send button
- Odoo cherry-pick 2 commits bus fix
- Minor fix css color into module hr_theme from repo CybroOdoo_OpenHRMS
- Typo in project task when logging time

### Removed

- Module package erplibre from ERPLibre_erplibre_addons and use instead image creation, check Makefile


## [1.3.0] - 2022-01-25

**Migration note**

With new version of poetry, a bug occurs in the update. The solution is to delete the directory to let it
recreate. `rm -rf ~/.poetry`

### Added

- Code generator supports view : activity, calendar, diagram, form, graph, kanban, pivot, search, timeline and tree
- Code generator supports portal view field and form creation
- Code generator generates generic snippets for demo_portal
- Code generator generates code_generator with code_generator_code_generator
- Code generator tests mariadb migrator
- Code generator supports javascript interpretation for snippet
- Code generator supports inheritance
- Code generator new project to create the suite of generation code
- Script to test the generation of module `code_generator`
- Make test_full_fast to run all test in parallel
- Module `web_timeline` and `web_diagram_position` in base image.
- Module `odoo-formio` from novacode-nl
- Module `design_themes` from Odoo
- Format python header with isort

### Changed

- Update to Python==3.7.12
- Update to poetry==1.1.12
- Update pip dependency with security update
    - Pillow==9.0.0
    - lxml==4.7.1
    - babel==2.9.1
    - pyyaml==6.0
    - reportlab==3.6.5
- Web diagram module has all color of the rainbow in option
- Refactor and simplify code of code_generator, better support of code reader

### Fixed

- Downgrade Werkzeug==0.11.15, only this version is supported by Odoo 12.0. This fixes some http request behind a proxy.


## [1.2.1] - 2021-09-28

### Added

- doc/migration.md

### Changed

- Update pip dependency with security update
    - Jinja2==2.11.3
    - lxml==4.6.3
    - cryptography==3.4.8
    - psutil==5.6.6
    - Pillow==8.3.2
    - Werkzeug==0.15.3
- Script separate generate_config.sh from install_locally.sh
- Improve developer documentation
- More Docker script

#### Code generator

- Improve db_servers generation code
- Improve wizard generate UI menu

### Fixed

- Mobile view menu item in Web interface from muk_web_theme


## [1.2.0] - 2021-07-21

**Migration note**

Because addons repository has change, config file need to be updated.

- When upgrading to version 1.2.0:
    - From docker
        - Clone project if only download docker-compose
            - `git init`
            - `git remote add origin https://github.com/erplibre/erplibre`
            - `git fetch`
            - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
            - `git checkout master`
            - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
        - Update `./docker-compose.yml` depending of difference with git.
        - Run script `make docker_exec_erplibre_gen_config`
        - Restart the docker `make docker_restart_daemon`
    - From vanilla
        - Run script `make install_dev`
        - Restart your daemon
        - Regenerate master password manually

### Added

- Adapt script to give an execution status
- Multilingual markdown
- Guide to use Cloudflare with DDNS
- Script to check git diff and ignore date
- Repo with ERPLibre image
- Improve git repo usage, filter repo by use case
- ERPLibre theme website of TechnoLibre
- ERPLibre website snippet
    - Basic HTML snippets
    - Snippet card
    - Snippet timelines
- Module contract_digitized_signature with contract_portal
- Module disable auto_backup
- Odoo cli db command to manipulate restoration db
- Odoo cli i18n command to generate i18n pot files

#### Makefile

- Format code
- Code generator test
- Addons installation
- OS installation
- Restore database
- Docker execution

#### Code generator

- Code generator for Odoo module, depending of ERPLibre
- Support map geospatial
- Support i18n
- Script to transform Python and XML to Python code writer script to regenerate themselves

### Changed

- Update Python dependency with Poetry
- Format all Python code with black
- Module auto_backup with sftp host key
- Module muk_website_branding use ERPLibre branding
- Update docs with vscode support, custom document layout, custom email template and trick to use params to share
  variable

#### Docker

- Use buster python 3.7.7 image to remove pyenv
- Update Postgresql to support Postgis
- Support volume addons /ERPLibre/addons/addons

### Fixed

- Ubuntu installation
- Poetry installation
- Geospatial with postgis can be installed


## [1.1.1] - 2020-12-11

### Added

- Developer, test, migration and user documentation
- Branding ERPLibre with muk_branding
- Uninstall module from parameter Odoo
- Makefile to generate ERPLibre documentation WIP
- Docker support volume on /etc/odoo
- Docker support update database

### Changed

- Better documentation on how to use ERPLibre and release
- Support wkhtmltox_0.12.6-1

### Fixed

- db_backup to accept public host key on sftp
- Docker dependency
- Freeze poetry version 1.0.10


## [1.1.0] - 2020-09-30

### Added

- Docker
- Pyenv to manage python version
- Poetry to manage python dependencies
    - Script poetry_update to search all dependencies in addons
- Travis CI WIP
- TODO.md
- Guide to update all repositories with community
- Update manifest
    - Add missing OCA repos
    - Add medical, property management and more
    - Add cloud/saas repo

### Changed

- Update to Odoo Community 12.0 and all addons
- Rename venv to .venv
- More documentation on how to use ERPLibre


## [1.0.1] - 2020-07-14

### Added

- Improved documentation with development and production environment
- Improved documentation with git repo
- Move default.xml manifest to root, the default location
- Support default.staged.xml to update prod with dev
- Feature to show diff between manifests or between repo of different manifests
- Update manifest
    - Muk theme in erplibre_base
    - Add draft account invoice approbation in portal
    - New module sale_fix_update_price_unit_when_update_qty
    - New module account_invoice_approbation
    - New module sale_margin_editor

### Fixed

- Production installation with git_repo


## [1.0.0] - 2020-07-04

### Added

- Environment of development, discovery and production with documentation and script.
- Google git-repo to support addons repository instead of using Git submodule.

### Removed

- Git submodule


## [0.1.1] - 2020-04-28

### Added

- Support helpdesk supplier, helper, employee and services
- Support [SanteLibre.ca](https://santelibre.ca) with MRP, website, hr, ecommerce
- Donation module with thermometer for website
- Script to fork project and all repos in submodule to create ERPLibre


## [0.1.0] - 2020-04-20

### Added

- Move project from https://github.com/mathbentech/InstallScript to ERPLibre.
- Support of Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

### Changed

- Support scrummer, project, sale, website, helpdesk and hr
- Support Nginx and improve installation

### Fixed

- Support only python3.6 and python3.7, python3.8 causes error in runtime.


[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.6.0...HEAD

[1.6.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.5.0...v1.6.0

[1.5.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.4.0...v1.5.0

[1.4.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.3.0...v1.4.0

[1.3.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.2.1...v1.3.0

[1.2.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.2.0...v1.2.1

[1.2.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.1.1...v1.2.0

[1.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.1

[1.1.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.0

[1.0.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.0...v1.0.1

[1.0.0]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.1...v1.0.0

[0.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.0...v0.1.1

[0.1.0]: https://github.com/ERPLibre/ERPLibre/releases/tag/v0.1.0