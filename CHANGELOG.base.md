<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Changelog
<!-- [fr] -->
# Journal des modifications
<!-- [en] -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- [fr] -->

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com). Ce projet adhère
au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- [common] -->

## [Unreleased]

<!-- [en] -->
**Migration notes**

Recreating the virtual environment, use installation guide from tool `make`.

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel, utiliser le guide d'installation depuis l'outil `make`.

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Une section **Réseau** au menu QEMU/KVM, et le script qui la porte, `script/qemu/network_qemu.py`. `--status` lit ce que sert le réseau libvirt, quel pont le porte, quelles VM y sont attachées, ce que disent leurs baux et ce que l'hôte route par ailleurs — rien n'est modifié. `--recreate` remet le sous-réseau sous ces VM en trois gestes ordonnés, et l'ordre EST la fonctionnalité : les VM attachées sont arrêtées D'ABORD, redéfinir un réseau sous une VM vivante lui laissant un bail qui ne mène nulle part et un tap qui n'est plus sur aucun pont ; puis le réseau est redéfini sur le préfixe voulu — 192.168.122 par défaut, celui de libvirt, celui que supposent les entrées ~/.ssh/config et les notes prises avant — et redémarré ; puis exactement les VM qu'il a arrêtées sont rallumées, une VM déjà éteinte le restant. Une VM qui n'obéit pas au shutdown ANNULE la redéfinition plutôt que d'y perdre son pont, et « --force-off » est ce qui lui coupe le courant. Un préfixe visé qui recouvre ce que l'hôte route déjà est refusé : c'est ainsi qu'une machine perd sa propre passerelle au profit d'un pont. Un réseau qui sert déjà le préfixe voulu n'est pas redéfini, et le seul cycle d'arrêt-relance répare encore les taps qu'un réseau abattu a détachés
- Un outil VPN, cinq technologies libres au menu — L2TP/IPsec PSK, WireGuard, OpenVPN, OpenConnect, sshuttle — accessible depuis **TODO › Execute › Réseau › VPN** et depuis la section Déploiement. Ce qui n'est pas secret (hôte, utilisateur, routes, MTU) vit dans une configuration JSON lisible et les clés pré-partagées comme les mots de passe dans un coffre KeePassXC : un profil peut donc être montré, comparé et partagé sans donner de quoi monter le tunnel. Les secrets s'écrivent en tmpfs sous 0700 et jamais sur un disque persistant ; `--dry-run` montre chaque geste privilégié sans en exécuter un, et l'outil tourne sous votre identité, chaque étape appelant sudo d'elle-même. Demander tout le trafic par le tunnel ne coupe plus la session SSH qui vient d'en donner l'ordre — l'adresse de l'opérateur, lue dans `SSH_CONNECTION`, reçoit sa propre route de survie, et toutes sont retirées au démontage. Seul L2TP/IPsec a monté un tunnel contre un concentrateur réel ; les quatre autres portent au choix une étoile disant que seuls des tests unitaires les couvrent
- `diagnose` nomme l'étage fautif du plus bas au plus haut, pour que la première ligne fausse soit la cause et non une conséquence : ce que le noyau expose · les paquets · la vérification propre à la technologie · interface et adresses · chaque route déclarée · une adresse témoin qui ne répond qu'à travers le tunnel · les journaux. L'étage du noyau attrape ce qu'aucune configuration ne rattrape : mettre à jour le paquet du noyau remplace `/lib/modules/<version>` et le noyau qui tourne ne peut plus charger aucun module, si bien que l'IPsec devient indisponible sur un noyau qui le prend en charge, que charon abandonne à l'initialisation et que le symptôme ressort trois étages plus haut en connexion jamais chargée. Le seul remède est un redémarrage, et il est PROPOSÉ, jamais fait : ni à blanc, ni sans terminal pour répondre, et seulement quand la capacité manque ET que les modules ont disparu
- L'accélération 3D des VM QEMU, cochée à la création et réglable ensuite, même sur une VM SANS écran virtuel — « auto » ne l'accorde jamais là, s'abstenant plutôt que de poser un périphérique vidéo que personne n'a demandé, alors qu'un rendu hors écran ou un émulateur tournant dedans veut exactement cela. Un nœud de rendu peut exister sans qu'EGL y démarre : QEMU refuse alors le domaine et la VM reste inutilisable jusqu'à ce que quelqu'un défasse le réglage, d'où un repli sur le rendu logiciel à la création et le retrait proposé sur une VM existante. Dans l'invité, le nœud de rendu appartient à « root:render » en 0660 et le compte n'y était pas : toute application GL retombait sur le rendu logiciel alors que la négociation VIRGL avait réussi, sans que rien ne le signale ; « render » et « video » sont désormais déclarés AVANT usage, un nom de groupe inconnu faisant que cloud-init ne crée aucun compte — ni mot de passe, ni clé SSH, une VM qui démarre injoignable
- Un diagnostic QEMU, écrit dans un fichier unique à transmettre à quelqu'un qui n'a pas accès à la machine : vingt et une sondes en lecture — hôte, hyperviseur, GPU, outils présents, stockage — chacune bornée dans le temps, une commande qui pend ne devant pas retenir le rapport, et chaque section isolée, le fichier s'écrivant d'un bloc à la fin. Il dit l'état 3D de chaque VM d'après sa définition PERSISTANTE, où trois valeurs répondent ensemble et aucune seule : le type de vidéo, « accel3d », et le device figé par libvirt. Ce dernier, un attribut arrivé avec libvirt 12.5.0 pour tenir l'ABI de l'invité stable d'un démarrage à l'autre, L'EMPORTE sur « accel3d » : une VM démarrée une première fois sans 3D garde le device sans GL, et cocher la case ensuite écrit une intention que rien n'applique. Le rapport propose aussi les outils qui lui manquent, la commande complète affichée avant la question, et la liste des périphériques que QEMU peut ouvrir — libvirt y met le nœud de rendu quand le domaine le déclare, jamais les nœuds propres d'une carte propriétaire, que sa pile ouvre pourtant. Il porte le nom de l'hôte, ses chemins et ses adresses, et le dit avant qu'on l'envoie
- La récupération de fichiers dans le disque d'une VM qui ne démarre plus, libguestfs montant son qcow2 sans elle. Toute commande porte « --ro », et c'est ce qui change la manœuvre : ouvrir en écriture le disque d'une machine allumée corrompt son système de fichiers. Les partitions sont listées, puis les répertoires à extraire, les commandes « copy-out » étant montrées plutôt que devinées
- Les assistants de développement installés DANS une VM au déploiement, et la pré-configuration qui permet de s'en servir sans rien retaper : rtk et son hook global de réécriture, starship avec son accroche au shell, un agent — Claude Code ou opencode —, tig, htop et vim, « merge.conflictStyle=zdiff3 », les hooks git du dépôt, les cinq commandes Claude du dépôt, et « source .venv.erplibre/bin/activate » dans l'historique du shell, là où la flèche du haut le retrouve. La case découvre le choix et l'identité git, pré-remplie avec celle de l'hôte, puisque c'est ce que la VM reçoit déjà et qu'un champ vide la ferait croire absente ; ce qui est saisi prime, champ par champ. Chaque pose est privée d'entrée standard et bornée dans le temps : « || true » couvre l'échec, pas l'ATTENTE, et un installateur amont qui pose une question resterait pendu sur un SSH sans terminal — d'où « -y » pour starship. L'option travaille en DEUX temps, et le second est nommé plutôt que tu : les hooks et les gabarits de commandes VIVENT dans le dépôt, si bien qu'une VM qui n'installe rien reçoit les poses et s'entend dire ce que le clone absent lui coûte. « core.editor » n'est posé que là où il n'y en a pas, l'éditeur de l'hôte voyageant déjà jusqu'au ~/.gitconfig de la VM — deux autorités sur un même réglage en font une de trop. Tout ce second temps rend 0 : une pré-configuration est un confort, et l'installation seule porte le verdict de la VM
- L'aide d'une option au formulaire de déploiement, ouverte par « ? » ou F1 et fermée par Esc : ce que chaque réglage d'installation POSE dans la VM, toutes ses étapes plutôt que les deux ou trois que le libellé d'une case peut porter — celle des outils IA en engage huit à elle seule. Le texte vit dans la même table que les cases, si bien qu'une option ajoutée sans aide affiche un bloc vide plutôt qu'un texte faux, et les DEUX écrans le lisent, celui de QEMU/KVM comme celui de Proxmox VE
- Un menu Git et Shell qui installe ce dont un clone a besoin au lieu d'afficher une commande à recopier : les hooks git du dépôt, « merge.conflictStyle=zdiff3 », Starship, Claude Code, opencode, et les plugins Claude Code avec une liste ERPLibre. Trois commandes d'assistant s'y déploient — « /git_prepare_merge », « /todo_plan_max », « /todo_generate_code ». Les outils manquants d'une réduction sûre s'installent sur les quatre familles de paquets, là où trois écritures séparées en connaissaient chacune un sous-ensemble différent. Un binaire posé dans un répertoire du HOME que le PATH du shell ne porte pas toujours est trouvé quand même, et la ligne d'export est écrite une seule fois
- Un déploiement bloqué par un disque orphelin — le qcow2 qu'une création interrompue laisse et que « deploy_qemu » refuse ensuite d'écraser — se voit proposer son effacement, taille et chemin affichés, avant que la création n'échoue après avoir fait attendre
- Un hook `pre-commit` liste les commentaires à relire dans les fichiers qu'on indexe, et ne bloque jamais : sur les sources du dépôt, 373 fichiers rendent 463 signaux, et un contrôle bloquant à cette échelle se fait désinstaller la semaine suivante. L'outil qui le sert, `script/analyse/check_comment_hygiene.py`, rapporte deux familles de sûreté inégale — la donnée identifiante, adresse, courriel ou chemin de compte, qui est une trouvaille ; et le récit, marqueur de témoignage, date absolue ou première personne, qui est un signal à RELIRE, l'outil ne pouvant savoir si la phrase énonce un fait durable. Il lit les commentaires et les docstrings, les lignes `#` comme les commentaires shell de fin de ligne, écarte le code tiers, et se replie sur un balayage ligne à ligne quand un source ne se parse pas, un rapport vide déclarant sinon propre un fichier qu'il n'a jamais lu. Les codes de sortie suivent la convention du dépôt : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué
- Le menu TODO montre le contexte fourni à un assistant, éparpillé sur six sources : instructions, règles, skills, commandes déployées, hooks git et mémoire. Chaque commande déployée est comparée à son gabarit du dépôt en ignorant les lignes d'identité git que le déploiement substitue, si bien qu'une copie périmée se voit là où une égalité stricte les déclarerait toutes périmées. Rien de `private/` n'est relevé, pas même un compte : nommer un fichier dont l'objet est de retenir ce qui ne doit pas sortir revient à le désigner
- Dupliquer une base et la neutraliser pour de bon : la duplication passe par `exp_duplicate_database` d'Odoo plutôt que par `CREATE DATABASE … TEMPLATE`, qui copie les tables et rien d'autre. Odoo seul coupe les connexions ouvertes sur la source — un shell Odoo laissé ouvert suffit à faire refuser PostgreSQL —, régénère `database.uuid`, copie le filestore et exécute les fichiers `neutralize.sql` des modules installés. Les modules maison du dépôt n'obtenaient aucun des quatre, et l'un d'eux ouvrait une porte : supprimer tous les `ir.mail_server` fait retomber Odoo sur le `smtp_server` du fichier de configuration, là où le serveur bouchon d'Odoo existe précisément pour boucher ce trou. La neutralisation d'Odoo commence à la 16 ; de 12 à 15 la copie retombe sur la technique de longue date du dépôt, `update_prod_to_dev.sh`, qui ne pose pas `is_neutralized`, ne désactive aucun cron et laisse les clés de paiement, mais supprime les serveurs de courriel et pose un compte de développement. Le chemin suivi est ANNONCÉ à l'exécution, une copie dont on ignore par quel chemin elle est passée ne se jugeant pas, et un script introuvable fait échouer la copie plutôt que de la laisser sortir brute en s'annonçant neutralisée
- L'écran de qualité de migration dit si une migration a réussi, là où il comparait seulement les paliers : tous les verdicts s'affichent, de la 12 à la 18 — seule façon de voir qu'un échec a été rattrapé à un palier plus haut — lus dans le journal de progression et rattachés au palier ODOO, non au compteur du pilote, décalé d'un rang. Il dit où vivent les traces, config.conf laissant logfile= vide et la sortie d'Odoo mourant avec le terminal ; il montre le passage du journal d'étape qui entoure chaque commande, garde par tee ce qu'il lance lui-même et le relit sans relancer ; et il lance six étapes de revue par « r », en demandant avant de basculer le checkout, car rejouer un test d'un autre palier ouvrait la base avec la mauvaise version, qui y écrit avant d'échouer. Un statut se lit comme les outils l'écrivent — 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué — si bien que plus rien n'est peint en rouge là où rien n'a échoué. La sortie est capturée par pseudo-terminal, jamais par un tube : smoke_public_url exige stdin ET stdout sur un terminal et, derrière un tube, cesse en silence d'offrir la réparation des vues COW ; neuf exécutions y passent, deux restent dehors, pty.spawn naissant en 0×0 où un plein écran se perdrait
- Trois contrôles rejoignent la revue de migration, chacun pour ce qu'un palier détruit sans signaler le moindre échec. Les trous de manifeste : un dépôt d'addons absent du manifeste d'un palier n'existe pas sur disque pendant cette étape, Odoo déclare donc ses modules introuvables, le pilote propose de les effacer, et la fonctionnalité part avec eux — seul le trou compte, présent avant et après, absent au milieu, ce qui ramène 35 candidats à 19 vraies omissions au lieu de 46 % de bruit. Le type de vue tree, supprimé en Odoo 18 sans conversion, se lit dans les SOURCES, là où tous les autres outils de la revue lisent la base et où un module jamais installé ne laisse rien ; le mot reste un identifiant valide, si bien que sur 465 occurrences 80 seulement cassent, et lxml et ast décident par la position du littéral, jamais une regex. La dérive du plan comptable : une montée de version recharge le gabarit de localisation en silence — trois des scripts l10n du noyau appellent try_loading() sans force_create=False, donc tout compte que le gabarit n'apparie pas par code est CRÉÉ, et les groupes ainsi ajoutés reclassent le plan existant. Un compte absolu n'y dit rien, seul l'ÉCART entre deux paliers d'une même migration se juge, et l'outil prescrit de rejouer le palier plutôt que de réparer : sa clé naturelle de suppression attrape aussi des comptes réappariés par code
- run.sh réveille le registre par HTTP pendant que le serveur démarre. Odoo ne charge le registre d'une base qu'à la PREMIÈRE requête qui la concerne, et sur une base migrée la personne qui ouvre la page attend des dizaines de secondes ; la sonde prend ce temps à sa place et s'arrête à la première réponse, un 303, un 404 ou un 500 prouvant tous que le registre est chargé. Elle ne peut pas nuire : elle rend TOUJOURS 0, meurt avec run.sh par un trap, abandonne après deux minutes, et prend le port sur la ligne de commande, puis dans config.conf, puis dans le journal, exact même quand le port demandé était pris — l'écoute sur une interface vide ou générale est sondée par le bouclage. `--erplibre-disable-warmup-http` la coupe et est le seul drapeau RETIRÉ avant odoo_bin.sh, qu'Odoo refuse ; `--no-http` et `--stop-after-init` la coupent aussi et passent, puisqu'il n'y a rien à réveiller quand personne n'écoute
- Une convention d'écriture pour ce qui reste dans git. Un sujet de commit lu seul, sans diff ni corps, doit dire quelle partie du système change et ce qui y est désormais différent — le symptôme, l'erreur citée et la métaphore sont des PREUVES, et une preuve va dans le corps. Un commentaire a le CODE pour sujet, au présent de ce qu'il fait : une phrase dont le sujet est un incident, une machine, une date ou une personne part vers `tasks/`, non versionné, tandis que le mode de défaillance que le code empêche reste. Rien d'identifiant hors de `private/` — ni client, ni base réelle, ni hôte, ni adresse, ni courriel, ni chemin de compte — et l'exemple qui illustre cet interdit s'invente au lieu de s'emprunter, un test figeant pour toujours ce qu'il contient. Une mesure qui établit un fait durable reste, dépouillée de sa date et de son opérateur ; le relevé de ce qui répondait ce jour-là part
- Un hook `commit-msg` refuse la part mécanique de cette convention d'écriture, et rien de plus : tag absent, sujet de plus de 72 caractères, sujet ouvrant sur une citation, corps de plus de 10 lignes pour une langue, adresse IP, courriel, chemin de compte, terme d'une liste de noms interdits qui vit hors de git puisque c'est elle qu'elle protège — absente, ce dernier contrôle se tait. Il compte des caractères et non des octets, sans quoi un sujet français de 72 caractères tomberait sur ses accents ; il exclut les trailers et le diff de `--cleanup=scissors` ; et son refus nomme `git commit --no-verify`, un garde-fou qui refuse trop étant désinstallé. Dire sur quoi porte le code reste un jugement qu'aucun hook ne rend. Le prédicat qui distingue une adresse du parc d'une version de manifeste Odoo, d'une boucle locale, d'un masque, d'une adresse de réseau ou d'un bloc de documentation RFC 5737 est partagé avec le contrôle des commentaires, deux prédicats pour une même question finissant par diverger. Ses 40 tests pèsent les acceptations — un « Merge branch », un fixup de rebase — autant que les refus
- `long_test/` — des tests qui créent de vraies machines et durent des heures, tenus hors de `test/` pour que le lanceur unitaire reste lançable en quelques secondes. `deep_proxmox.py` empile des Proxmox dans des Proxmox, `deep_qemu.py` des QEMU dans des QEMU, et les deux partagent un moteur. Mesuré sur 28 cœurs : trois étages coûtent 34 minutes, le quatrième 4 h 20 d'amorçage plus 7 h 18 d'installation — tout y est 15 à 30 fois plus lent, et c'est là que les fabricants cessent de documenter l'imbrication. La profondeur est un paramètre et vaut trois par défaut, parce que trois marche
- deep_qemu PROUVE KVM à chaque étage au lieu de le supposer : `deploy_qemu.py` ne passe jamais `--cpu host-passthrough` et, quand /dev/kvm manque, il n'échoue pas — il pose `--virt-type qemu` et crée une VM entièrement ÉMULÉE, sept minutes et demie de démarrage, sans qu'aucun code de retour ne le dise. Sans garde, la descente mesurerait de la TCG empilée en croyant mesurer de l'imbrication. Chaque étage doit montrer `/dev/kvm`, `nested=Y` et un domaine enfant en `type='kvm'` ; ce qui n'a pas été lu vaut NON
- Les deux tests longs acceptent `--hote` pour partir d'une machine qu'on possède déjà, au lieu de créer une VM de tête pour héberger un hyperviseur qu'on a sous la main — cela coûte cinq minutes ET un étage d'imbrication. Le plan se dimensionne alors sur la RACINE, lue par ssh ; les délais comptent la profondeur ABSOLUE ; et la racine n'est jamais un étage atteint, jamais détruite, et son entrée ~/.ssh/config n'est jamais retirée
- Support de la migration de base de données et de modules Odoo avec TODO
- Support du changement multi-version Odoo sur le même espace de travail
- Script pour le renforcement de la sécurité de l'installation
- Support des versions Odoo 12.0 à 18.0
- Séparation de l'installation Python ERPLibre de celle d'Odoo avec .venv.erplibre et .venv.odoo18
- Implémentation de l'auto-installation avec TODO.py
- TODO affiche la documentation, télécharge la base de données, aide au formatage du code
- Script de performance pour mesurer les requêtes par seconde
- Support de l'architecture Mainframe 390x
- Déploiement avec Cloudflare et Nginx
- Support de la configuration Apache comme Nginx
- Support du générateur de code RobotLibre
- Support d'ERPLibre DevOps, procédure d'automatisation DevOps
- Application mobile ERPLibre Home, utiliser TODO pour compiler, déployer et personnaliser
- Support de la grille Selenium depuis selenium_lib.py
- Ajout des addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor
- Déploiement de VM ERPLibre en QEMU/KVM depuis des images cloud (Ubuntu, Debian, Fedora, AlmaLinux, Rocky Linux, openSUSE Tumbleweed, Arch) en amd64, arm64 et s390x, avec un menu pour lister, tester, redimensionner, supprimer et nettoyer
- VM graphiques : un choix serveur / bureau proposant GNOME ou Cinnamon (le bureau de Linux Mint), avec accès distant par xrdp — TigerVNC sur Arch
- Interfaces Textual : tableau de bord d'installation, formulaire de
  déploiement de VM, écran de reprise de migration ; Textual s'installe à la
  demande
- Télémétrie de navigation pour TODO, en arbre, en kanban ou en liste
- Outils de migration pour les vues copy-on-write du site web : prévoir,
  photographier, comparer, neutraliser et réinitialiser
- Boîte à outils d'analyse en lecture seule d'une base Odoo
- Configuration SSH avec ProxyJump récursif, redirection de port et
  enregistrement des hôtes QEMU dans virt-manager
- Serveur de notifications NTFY auto-hébergé
- Politique d'IA générative, adoptant celle de l'OCA
- Agents et commandes Claude Code
- Serveur git local pour partager du code entre machines
- Tests unitaires pour la configuration, la refactorisation et les composants
  non couverts, avec un plan de test bilingue
- Lecture et envoi de courriel depuis le CLI TODO, en IMAP et SMTP
- L'analyse de base lit un zip de sauvegarde tel quel, sans le restaurer
- Menu de gestion RTK
- Menu d'outils d'assistance IA, avec la commande de commit Claude Code
- Menu de déploiement : cloner ERPLibre sur un hôte distant, configurer sshfs,
  et des cibles make pour le déploiement SSH
- Commandes de sauvegarde et d'effacement de base, et un nommage plus clair à
  la restauration
- Correctif git, dépôt distant git et configuration vim depuis le menu
- Vérification de sécurité de l'environnement Python
- Odoo 18 lit les fichiers STL (OpenCAD)
- Mobile : whisper.cpp et sentencepiece au manifeste, un script de test mobile,
  et le contrat d'API de synchronisation Odoo
- Entrée de FAQ sur wkhtmltopdf pour les distributions récentes
- brin_advisor et brin_cluster : recommander et appliquer le bon index
  PostgreSQL pour un modèle Odoo
- Réglages par VM dans le formulaire de déploiement : vCPU, RAM, disque, type, branche ERPLibre, version d'Odoo et fuseau horaire, un verrou qui soustrait une VM au profil global, le renommage, et plusieurs exemplaires d'une entrée
- Fournisseur d'interpréteur Python choisi par EL_PYTHON_PROVIDER — mise pose un CPython précompilé, pyenv en compile un — et retenu par déploiement
- uv pose les paquets Python, pip en repli, par EL_PIP_PROVIDER
- openSUSE Leap 16.0 et Fedora 43 au catalogue de VM
- Magasin d'applications d'une VM graphique : .deb seul, outillage Flatpak, ou snap
- Tunnel vers le bureau distant : la commande SSH est composée depuis ~/.ssh/config, avec la console de l'hyperviseur comme troisième voie
- Le tableau de bord d'installation agit sur une VM sans la quitter : mise à jour par parties, redémarrage d'Odoo, suppression ; colonne d'architecture et colonnes ajustables
- Migration : revenir à une étape depuis l'écran de reprise ou depuis une invite, et agir sur les copies COW dès leur annonce
- L'analyse des copies de site compare chaque copie à la vue qu'elle masque
- Un test vérifie que ce qu'importe l'outillage est bien déclaré
- Migration Odoo automatisée : l'outil mène toute l'exécution — réparer, rejouer, un déroulement automatique qui prend le défaut au bout de cinq secondes, et un compte à rebours qui nomme la réponse qu'il va prendre
- Écran d'état de migration : « t » montre où en est une exécution, avec les commandes en couleur, la durée écoulée, le journal du serveur lu pour vous, et un fichier de journal par étape sur disque
- Qualité de migration : ce qu'une exécution a gagné et perdu étape par étape, les fichiers manquants nommés, les refontes propres à Odoo distinguées des vraies pertes, et les changements déclarés par OpenUpgrade superposés aux réels
- Réparations de migration : le SCSS personnalisé que le palier suivant casse, prévu puis corrigé ; les thèmes désinstallés avant le premier palier ; la visibilité DMS rétablie ; les vues dont le type stocké contredit leur parent ; et les balises <tree> qu'Odoo 18 a renommées en <list>
- Tests de fumée après une migration : chaque URL publique demandée, /my et chaque application ouverte sous l'utilisateur de test de neutralisation, les vues derrière une URL en échec nommées, et le nettoyage de base OCA passé d'abord
- Vérification du filestore : si les fichiers joints sont bien arrivés, si l'enregistrement existe encore, et les nettoyages proposés sur place
- Analyse : les modules qui manquent à une base par rapport au paquet par défaut, avec une offre d'installer ceux qui sont prêts, et les fichiers joints réellement irrécupérables
- Debian sur s390x par debian-installer, aucune image cloud n'étant publiée pour cette architecture
- Une VM de développement mobile : PyCharm, Android Studio, extensions GNOME, un émulateur Android et un tunnel adb pour scrcpy, l'application mobile étant compilée et testée dedans
- Forgejo, une forge git installable depuis le menu de déploiement
- Matériel réglé par VM : le GPU de l'hôte, le mode CPU, les écrans et le réseau
- virt-viewer ouvre l'écran d'une VM depuis le menu
- Le tableau de bord d'installation affiche la RAM de l'hôte, la RAM utilisée et l'uptime d'une VM, et depuis combien de temps un journal est muet
- Une VM accueille sa connexion SSH avec les commandes propres à sa distribution
- Proxmox VE comme cible de déploiement : déployer une VM sur un hôte Proxmox distant depuis un écran qui récapitule dans le terminal avant de créer, crée le pont manquant, suit la VM et change son état, montre sa colonne Odoo et le lien web, et la supprime depuis l'hôte. Toute VM distante vient désormais avec son guide de connexion, qui manquait depuis le début
- Des réparations pour ce qu'un palier Odoo laisse derrière : les copies de site qui ne savent plus se rendre — prédites AVANT le palier plutôt que découvertes en 500 après — les index qu'Odoo 17 crée en double, et les réglages qu'aucun événement ne remet
- Des analyses qui lisent une base plutôt que de la compter : qui dépend de qui, à l'écran ; ce qui est installé, en cours et appliqué ; l'état d'une instance lu pour l'usage qu'on en fait ; et l'auscultation d'une base qui n'est pas ici
- L'anonymisation d'une copie sans IA : une copie de production sert à reproduire un défaut, les identifiants restent donc cohérents entre les tables une fois les noms remplacés
- Les statistiques de chaque VM : écriture, RAM, disque
- Le choix de la base au démarrage, sans jamais bloquer sur ce choix
- Le redémarrage fait partie de l'installation de Proxmox VE : install_proxmox.sh pose le noyau puis s'arrête, à raison, car lancé par ssh un reboot couperait sa session et ferait passer l'installation pour un échec. Le redémarrage revient à l'enveloppe de lancement, qui tourne sur NOTRE machine et survit à celle de la VM — installation, reboot, attente que « uname -r » porte le noyau Proxmox, puis vérification. Le ✅ ne s'écrit qu'après, et veut donc dire « hyperviseur utilisable »

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- The name of a VM built from a rolling release drops the version segment: `latest` distinguishes no VM from another. A named version that coexists with others in the catalogue stays
- Every menu entry carries an icon, ten menus having stayed bare, and the spacing follows the RENDERED width read from Unicode rather than guessed — two spaces after a one-column emoji, one after a wide one. The QEMU Manage section, grown too long to scan, is split into Manage, VM access and Troubleshoot
- Staging names the files, never `git add -A`. The sweep stages everything untracked, and this repository keeps two directories untracked ON PURPOSE: `private/`, the only place allowed to hold customer data, and `tasks/`, where the convention sends the investigation precisely because it is not versioned. It also swallows whatever else is in flight in the checkout, under a subject that does not cover it; `git add -p` stages the hunks when one file carries two subjects
- A countdown prompt gives 15 seconds to decide, where five were not enough to READ the question: the countdown exists so a run can be left unattended, not to go fast, and too short it does the opposite — the answer comes by reflex, or a default no one read is taken. A restored database is named after the backup file, which already carries a telling name, rather than « test », under which successive migrations all landed on one name. The name is sanitised, since it ends up in a createdb, and capped at 41 characters: the driver appends « _neutralize_upgrade_18 » and PostgreSQL truncates at 63, which would put two tiers on the same name. A remote download keeps the name the server gave
- todo.py split into nine files, one per subject, with a shared base per form. It carried 9 500 lines more than a file should and every subject went through it; the deployment forms repeated the same field-and-validation machinery, so a fix in one never reached the others. No behaviour changes
- Branch, profile and type are chosen per VM. They were global, which meant switching everything to deploy a single machine differently
- One shared base describes the guest system, where each form used to describe it again

<!-- [fr] -->

- Le nom d'une VM bâtie sur une publication continue perd le segment de version : « latest » ne distingue aucune VM d'une autre. Une version nommée qui coexiste avec d'autres au catalogue y reste
- Chaque entrée de menu porte une icône, dix menus étant restés nus, et l'espacement suit la largeur RENDUE lue dans Unicode plutôt que devinée — deux espaces derrière un emoji d'une colonne, une derrière un large. La section Gérer de QEMU, devenue trop longue à parcourir, est scindée en Gérer, Accès à la VM et Dépannage
- L'indexation nomme les fichiers, jamais `git add -A`. Le ratissage indexe tout ce qui n'est pas suivi, et le dépôt garde deux répertoires non suivis EXPRÈS : `private/`, seul endroit autorisé à porter une donnée de client, et `tasks/`, où la convention envoie l'enquête précisément parce qu'il n'est pas versionné. Il emporte aussi ce qui est en cours ailleurs dans le checkout, sous un sujet qui ne le couvre pas ; `git add -p` indexe les hunks quand un fichier porte deux sujets
- Une invite à compte à rebours laisse 15 secondes pour décider, là où cinq ne suffisaient pas à LIRE la question : le compte à rebours n'existe pas pour aller vite mais pour qu'une exécution puisse être laissée sans surveillance, et trop court il fait l'inverse — la réponse vient par réflexe, ou un défaut que personne n'a lu s'applique. Une base restaurée porte le nom du fichier de sauvegarde, qui en porte déjà un parlant, plutôt que « test », sous lequel des migrations successives finissaient toutes sur un même nom. Le nom est assaini, puisqu'il finit dans un createdb, et borné à 41 caractères : le pilote ajoute « _neutralize_upgrade_18 » et PostgreSQL tronque à 63, ce qui ferait finir deux paliers sur le même nom. Un téléchargement distant garde celui que le serveur a donné
- todo.py éclaté en neuf fichiers, un par sujet, avec un socle commun par formulaire. Il portait 9 500 lignes de plus qu'un fichier ne devrait et tous les sujets y passaient ; les formulaires de déploiement répétaient la même mécanique de champs et de validation, si bien qu'une correction dans l'un ne gagnait jamais les autres. Aucun changement de comportement
- La branche, le profil et le type se choisissent par VM. Ils étaient globaux, ce qui obligeait à tout basculer pour déployer une seule machine autrement
- Un socle commun décrit le système invité, là où chaque formulaire le redécrivait

<!-- [en] -->
## Fixed
<!-- [fr] -->
## Corrigé
<!-- [en] -->

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
<!-- [fr] -->

- Un déploiement dit POURQUOI il faut un mot de passe avant que sudo ne le demande, et sur quel constat. sudo ne dit jamais ce qu'il sert à faire : l'invite tombe entre deux lignes de journal, et l'on tape un mot de passe sans savoir s'il porte sur libvirt, sur un paquet ou sur un fichier — d'autant qu'appartenir au groupe `libvirt` a tout l'air de suffire. Il ne suffit pas, et libvirt n'y est pour rien : le disque et le seed cloud-init s'écrivent dans le pool par défaut de libvirt, un répertoire de root où le groupe ne donne aucun droit d'écriture. La raison est donc CONSTATÉE et non affirmée — l'écriture se teste, une ACL pouvant l'accorder là où « drwxr-xr-x root root » semble la refuser —, puis nommée avec le répertoire, son propriétaire et son mode, à côté de ce que le groupe couvre vraiment : la socket qemu:///system, sondée en essayant. Dit une fois par exécution, avant la première commande privilégiée, et en dernière ligne du récapitulatif final, qui est l'écran juste avant l'invite. Root ne s'entend rien annoncer, aucune invite ne lui étant due ; un virsh absent se lit comme absent, et non comme un groupe en défaut
- Un réseau libvirt ne compte plus comme sa propre collision. Un réseau démarré porte et route son /24 sur son pont, et ce pont était lu comme « l'hôte occupe déjà ceci » : le verdict était donc « collision » sur toute machine où le réseau tournait, quel que soit le sous-réseau qu'il servait. `--setup-host` — et tout déploiement, qui passe par la même vérification — abattait alors le réseau et le déplaçait sur un /24 libre là où rien n'entrait en conflit, laissant les VM qui y étaient attachées sans passerelle et le tap détaché. Le pont du réseau examiné est désormais écarté de ce que l'hôte occupe, les adresses étant lues une interface par ligne pour que chacune se rattache à la sienne ; un nom de pont illisible n'écarte rien, le silence pesant du côté prudent. Le XML remis à « net-define » passe par un vrai fichier temporaire, imprévisible et retiré même quand virsh échoue, là où un nom composé de celui du réseau était un chemin devinable dans un répertoire où tout le monde écrit
- `--setup-host` ne laisse plus derrière lui une machine qui perd son réseau au démarrage suivant. Le réseau « default » de libvirt sert 192.168.122.0/24, et toute VM déployée par ce dépôt VIT dans ce réseau : son pont y prendrait l'adresse .1, celle de sa propre passerelle. virsh refuse ce démarrage — mais seulement tant que la route est là, et au démarrage libvirtd monte ses réseaux AVANT que le bail DHCP de l'hôte n'arrive : plus rien ne signale la collision, virbr0 prend l'adresse de la passerelle, et l'hôte n'a plus de réseau. L'autostart était armé même quand le démarrage venait d'échouer, et le message invitait alors à redémarrer. Le réseau est désormais DÉPLACÉ sur un /24 libre par redéfinition — laquelle ne demande ni pont ni module du noyau, donc elle passe là où le démarrage ne passe pas — en gardant son UUID, le nom de son pont et son adresse MAC, si bien que les domaines qui le nomment le retrouvent ; l'autostart ne s'arme que là où aucune collision ne reste, et se RETIRE là où il en reste une. Un réseau trouvé actif sur une route de l'hôte est abattu d'abord : c'est la machine déjà cassée, et c'est ce qui lui rend son accès au réseau, avant même qu'il y ait de quoi télécharger un correctif. Un seul redémarrage suffit toujours quand le seul obstacle est un noyau remplacé depuis le démarrage
- L'état d'un réseau libvirt est lu en anglais. virsh TRADUIT ses étiquettes : sous une locale française, « net-info » répond « Actif : non », où un motif sur « Active: yes » ne trouve jamais rien — tout réseau se lisait donc éteint, « --setup-host » déclarait l'hôte pas prêt quel que soit son état, et son conseil était de redémarrer pour rien. Toute sortie de virsh que l'on analyse passe maintenant par un appel unique qui force « LC_ALL=C », le même geste, pour la même raison, que l'écran de gestion QEMU
- Le coffre KeePassXC s'ouvre sur une machine sans tkinter, c'est-à-dire sur tout serveur. Les deux imports partageaient un seul `try`, si bien que l'absence de tkinter mettait aussi PyKeePass à None : le coffre restait inouvrable même avec chemin et mot de passe configurés, alors que le journal annonçait « pykeepass is not installed » et que pykeepass 4.2 était là. tkinter ne sert qu'au sélecteur de fichier, quand aucun chemin n'est configuré. L'invite nomme aussi le coffre avant d'en demander le mot de passe, et non après
- Le menu QEMU passe par le groupe « libvirt » plutôt que par sudo, qui n'ajoutait aucun droit et réclamait un mot de passe à chaque entrée ; l'appartenance se tranche en ESSAYANT, jamais en lisant /etc/group. L'URI libvirt est nommée explicitement : sans « --connect », un virsh non root vise « qemu:///session », un hyperviseur SÉPARÉ où aucune VM du système n'existe, et « list --all » y rend une liste vide sans erreur — l'URI par défaut de root masquait l'omission
- Les outils système lancés depuis le menu n'héritent plus du venv en tête de leur PATH. Un outil écrit en Python et amorcé par « env python3 » démarrait dans un interpréteur privé des modules de la distribution et sortait sur « No module named 'gi' »
- Accepter d'installer les paquets QEMU ne redémarre plus l'hôte sans demander : « --assume-yes » couvrait le gestionnaire de paquets, et la commande y ajoutait « --reboot-if-needed » en silence. Une seule constante servait l'invité jetable et le poste de travail
- Trois écrans qui tombaient : les statistiques, où « datetime.datetime » n'existe pas puisque c'est la CLASSE qui est importée et où l'erreur emportait TODO entier ; une VM échouée dont la sortie montrait quatre lignes d'épilogue au lieu du message de l'outil ; et une clé i18n dupliquée qui écrasait un libellé du menu principal, la dernière définition gagnant dans un littéral de dict Python sans erreur ni avertissement
- Une réduction mesure la place libre AVANT de proposer la sauvegarde, qui double la place occupée et avait OUI pour défaut : sur un disque presque plein, une réponse vide lançait une copie qui s'arrête à mi-course et laisse un « .bak » tronqué
- « odoo_bin.sh db --drop » échouait par AccessDenied à chaque palier de migration, et le clone butait ensuite sur « database already exists » : db_restore.py lit le config.conf du dépôt, y voit admin_passwd = admin et n'envoie donc aucun mot de passe maître, quand odoo_bin.sh ne passait pas de « -c », si bien qu'Odoo lisait ~/.odoorc et son mot de passe haché. ODOO_RC ferme cette couture en un point plutôt qu'à vingt sites d'appel, les versions 12 à 18 le lisant après « -c » et avant ~/.odoorc, donc un choix explicite l'emporte toujours
- La vue SQL account.root que crée Odoo 17 est retirée avant le chargement en 18, où le modèle porte _auto = False et _table_query = '0', si bien que son nom n'entre plus dans aucune requête et que le contrôle des tables manquantes l'ignore. La vue n'est pas seulement morte mais FAUSSE, bâtie sur la colonne code que l'ORM 18 n'écrit plus, et elle est l'unique épingle des deux colonnes héritées où database_cleanup échoue — aucun DROP COLUMN, OpenUpgrade les lisant encore ensuite
- La réparation de migration créait des listes de prix qui n'avaient pas lieu d'être, de deux façons. Elle interrogeait `env.user.has_group()`, qui répond oui dès que l'exécutant est membre du groupe — et la migration l'y ajoute en cours de route —, là où la case des réglages lit tout autre chose : ce que `base.group_user` IMPLIQUE. Décider sur l'exécutant créait une liste de prix dans une base dont la fonctionnalité est éteinte, et Odoo prévenait alors à chaque ouverture des réglages qu'il allait l'archiver. Et une liste de prix partagée entre sociétés, au `company_id` vide, ne comptait pas comme appartenant à la société : la réparation voyait une société sans liste et fabriquait un doublon vide à côté de l'existante, sur une base qui n'avait pourtant rien perdu. Les deux lisent désormais l'implication du groupe et le détecteur `pricelist_missing` du même outil, qui distingue déjà les deux cas ; le contrôle « restant de migration » posait la même mauvaise question et a été corrigé avec elles
- La liste noire de l'anonymisation passait son SQL à psql en UN seul argument, et Linux plafonne un argument à 131 072 octets : le mode qui couvre le plus de tables était justement celui qui cassait, sur « OSError: [Errno 7] Argument list too long ». Le SQL passe désormais par un fichier avec `-f`, qui garde le `--single-transaction` que l'entrée standard aurait perdu en silence. Les colonnes texte à longueur déclarée sont tronquées par `left(…, n)`, l'identifiant en TÊTE pour qu'une colonne unique le reste, et tous les identifiants sont cités — Odoo laisse nommer un champ user ou order. Écarter toute colonne sous contrainte CHECK laissait le nom du partenaire intact : sur du texte, seules les contraintes de FORME sont hors de portée, et un UPDATE qui échoue n'écrit rien
- L'anonymisation respecte ce qu'une valeur SIGNIFIE, là où le type SQL dit seulement ce qu'elle EST. Odoo déclare `parent_path` en `char` mais y range un chemin d'identifiants — 1/7/12/ — reparsé aussitôt par `int()` : un nom écrit là casse le premier chargement de page ; tout modèle `_parent_store` en porte un, et `account_payment_term.days_next_month` passe de même à `int()`. Les deux noms connus sont écartés, puis le contenu lui-même est sondé : une colonne dont chaque valeur est un chemin reste intacte, même dans un module maison, et les barres obliques sont exigées, si bien qu'une valeur tout en chiffres n'échappe pas à l'anonymisation en passant pour un identifiant. Les nombres étaient tirés uniformément sur 0 à 1000, ce qui est faux pour tout nombre borné par son usage — heures, pourcentages, taux : un `float` qui porte une heure de la journée, tiré hors de 0..23, fait lever « ValueError: hour must be in 0..23 » à l'affichage de la fiche, borne qui vit dans le Python d'Odoo là où aucune contrainte PostgreSQL ne la déclare. Le tirage respecte désormais la seule borne que les DONNÉES déclarent, leur propre étendue, min et max mesurés par table ; 0 à 1000 ne reste que pour une colonne vide ou impossible à sonder
- Le lanceur unitaire ne prenait que sept préfixes de noms, « le reste demandant une base de données », et exécutait 1131 tests là où les 3703 du répertoire passent avec PostgreSQL injoignable ; il balaie test/test_*.py. Deux formes rendent un fichier muet sans erreur — unittest.main() posé en plein milieu, qui sort avant même que la seconde moitié soit définie (quatre fichiers, 87 tests), et l'absence de bloc __main__, qui compte zéro (huit fichiers, 174 tests) — et une garde refuse désormais les deux, ainsi que tout retour à une liste de préfixes
- Le vérificateur du transfert mobile n'acceptait que la disposition en packs, quand une compilation réelle livre un tar.gz par dépôt. Il échouait sur `<slug> : index.json absent` et arrêtait `compile_and_run.sh` avant l'APK — depuis le 2026-08-20, pour quiconque est sur le main mobile actuel. Il accepte désormais les deux dispositions, et prouve la présence de CHAQUE fichier promis plutôt qu'un échantillon de vingt : traverser les 139 archives coûte 6 s, et 124 350 fichiers sont comptés
- Le test du bundle gardait la limite d'entrées du ZIP en exigeant un champ `chunk` sur chaque fichier, c'est-à-dire la disposition en packs plutôt que la limite elle-même. Il compte maintenant les entrées que portera l'APK — 278 pour un plafond de 65 535 — si bien que les deux dispositions passent et qu'un retour au fichier-par-source échoue toujours

- La migration des paliers 13 à 18 tenait sur des suppositions : une ancre de page encodée en pourcent que l'analyseur ne lisait pas, web_responsive qui ne survit pas au passage en 18, un OpenUpgrade en échec qui passait pour fait, un clone rebâti qui gardait la préparation de l'ancien, et un module fautif qui emportait tout le lot de désinstallation
- Proxmox visait la mauvaise machine : l'installation partait sur l'hôte plutôt que sur la VM, le disque annoncé était celui de l'hôte, et quatre écrans parlaient d'une machine locale alors qu'ils pilotaient une machine distante. Le rebond est désormais le seul chemin vers une VM — viser directement ne marchait que tant que la VM avait une adresse routable. Six autres défauts sont venus d'un audit, pas de l'usage
- Un seul nom par entrée `~/.ssh/config`, et l'ancienne s'en va avec la convention qui l'a remplacée
- Le suivi ne met plus une VM à la poubelle avant d'en être sûr, et effacer depuis un suivi rouvert vérifie d'abord l'identité de la VM
- sshfs annonçait un montage qui n'avait pas eu lieu
- Odoo 15 déclare xlsxwriter, dont report_xlsx a toujours eu besoin
- La sonde du mot de passe maître de db_restore ne validait rien
- Une analyse cherchait l'identifiant externe de la liste de prix plutôt que la liste, et signalait des champs qui n'avaient jamais porté de donnée
- Le pont NAT s'écrivait avant de savoir si le NAT existe. Six lignes d'iptables et « code de retour 1 » arrivaient après que la strophe soit déjà posée dans /etc/network/interfaces, et rien dans ce bruit ne disait qu'il fallait redémarrer : l'hôte tournait le noyau cloud de Debian, dépouillé de netfilter. C'est notre propre install_proxmox.sh qui produit cet état, donc une Proxmox imbriquée fraîchement installée y est TOUJOURS — le garde va désormais là où la conséquence est, et non à la confirmation de l'hôte
<!-- [en] -->
## Removed
<!-- [fr] -->
## Retiré
<!-- [en] -->

- The residue check that called a language broken when its res_lang row has active at NULL — listed nowhere, no longer re-enablable. False in the 18 source: an ('active','=',False) domain compiles to (IS NULL OR = FALSE), the Languages menu action carries active_test: False, sorting goes through COALESCE(active, FALSE), and reading returns bool(value). Odoo writes that NULL itself, active being a Boolean with no default and res.lang.csv having no such column, which makes one NULL per language added to the catalogue — so « zero before, nonzero after » is not enough to declare a residue. A test now refuses a verdict key that nothing defines any more
- Ubuntu 20.04 and 22.04 support, on every architecture: pikepdf needs qpdf 12.2, whose build requires C++20, while focal ships GCC 9 and publishes no `g++-10` for s390x

<!-- [fr] -->

- Le contrôle de résidus qui jugeait cassée une langue dont la ligne res_lang porte active à NULL — listée nulle part, plus réactivable. Faux dans la source 18 : un domaine ('active','=',False) compile en (IS NULL OR = FALSE), l'action du menu Langues porte active_test: False, le tri passe par COALESCE(active, FALSE), et la lecture rend bool(value). C'est Odoo lui-même qui écrit ce NULL, active étant un booléen sans défaut et res.lang.csv n'ayant pas cette colonne, soit un NULL par langue ajoutée au catalogue — « zéro avant, non nul après » ne suffit donc pas à déclarer un résidu. Un test refuse désormais une clé de verdict que plus rien ne définit
- Le support d'Ubuntu 20.04 et 22.04, sur toutes les architectures : pikepdf réclame qpdf 12.2, dont la compilation exige C++20, quand focal livre GCC 9 et ne publie pas de `g++-10` pour s390x

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

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

<!-- [fr] -->

- Support Docker postgresql 18
- Script de formatage recherche les fichiers diff dans chaque dépôt
- Support de la neutralisation de base de données depuis Odoo
- L'installation prend en charge Fedora, Debian, Ubuntu et Arch Linux
- La synchronisation des dépôts et l'installation poetry tournent en
  parallèle, jusqu'à 50 % plus rapide sur une connexion lente
- Les modules extra CybroOdoo deviennent optionnels, suivis par version d'Odoo
- Node.js 22, exigé par Capacitor 8 pour l'application mobile
- Poetry et repo sont silencieux par défaut ; EL_VERBOSE rétablit la sortie
- Menus TODO regroupés en sections avec icônes, et texte anglais utilisé comme
  clé i18n
- Documentation bilingue, générée depuis les sources .base.md
- Une VM hérite du fuseau horaire de l'hôte qui la crée
- Le premier démarrage n'attend plus snapd, la génération de locales ni l'agent
- apt prend le miroir joignable le plus rapide avant le dépôt officiel
- Selenium : téléchargement via un hub réseau, SVG vers PNG, détection
  d'erreurs, clics multiples et pilotes à jour
- Odoo peut tourner sur une base personnalisée ; configuration de queue_job et
  options de redirection SSH dans le menu
- Tuer un processus par son port demande confirmation, avec un menu interactif
- LinuxMint 22.3 pris en charge
- Dépendances Odoo 18 : flanker, orjson, python-magic, tldextract, PyYAML
- Année de copyright portée à 2026
- Miroirs pacman canadiens placés en tête sur Arch, le miroir « géographique » officiel mesurant quatre fois plus lent depuis Montréal
- Une dépendance Poetry peut être déclinée par architecture : factur-x est épinglé en 3.x sur s390x, où saxonche ne publie pas de roue, et PyMuPDF y est écarté
- Entrée cible la version d'Odoo la plus élevée supportée, le défaut étant calculé depuis le menu
- Une cible make lance les tests unitaires, avec la dépendance mobile déclarée

<!-- [en] -->
## Fixed
<!-- [fr] -->
## Corrigé
<!-- [en] -->

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

<!-- [fr] -->

- Une installation en échec n'est plus rapportée comme réussie : le code de
  sortie remonte toute la chaîne
- --with_extra s'applique désormais à un environnement déjà installé
- Le chemin d'addons ne pointe plus vers un dépôt que le manifeste Odoo 18 ne
  clone jamais
- repo init reçoit un nom de branche, une installation neuve n'échoue plus
- Le suivi d'installation suit une VM dont le bail DHCP change
- Installation sur Debian 13, Fedora et Ubuntu 26.04 : verrou apt, wkhtmltopdf,
  SELinux et le compilateur C manquant
- Accents de la documentation et génération markdown en parallèle
- La chaîne de compilation s390x, sur Debian comme sur EL9, EL10, Fedora et openSUSE : compilateurs et en-têtes manquants, Rust pour cryptography et bcrypt, qpdf pour pikepdf, libclang pour pymupdf, des noms de paquets qui changent d'une version à l'autre, et un lot en échec sur un seul nom inconnu sans jamais le nommer
- L'installation d'un bureau graphique figeait trente minutes sur un paquet snap qui ne joignait pas le magasin
- Le compilateur était tué faute de mémoire en bâtissant CPython sur une petite VM s390x
- Le README ne listait ni Fedora, ni openSUSE, ni Linux Mint, ni Debian 13, toutes supportées
- Les outils de migration COW et la mise à niveau de la base parlent la langue du système
- Les outils d'analyse et de migration sont exécutables
- L'installateur forgejo ne réaffiche plus le mot de passe administrateur qu'il vient de poser
- La connexion Selenium renvoyait le défaut de configuration au lieu des identifiants reçus, lors de la reprise après une modale
- db_restore redemande le mot de passe maître au lieu de mourir sur une faute de frappe
- pyproj exige le binaire proj, pas seulement ses en-têtes, et PROJ est bâti là où la distribution est en retard
- run.sh est lancé par bash, contre les échecs 203/EXEC de systemd
- pykcs11 se compile avec SWIG 4.3 et au-delà
- os-release remplace lsb_release, et une collision d'IP se voit mieux

<!-- [en] -->
## Security
<!-- [fr] -->
## Sécurité
<!-- [en] -->

- Passwords and tokens are redacted before a command is displayed or logged
- The Odoo master password no longer travels on the command line: MASTER_PWD carries it, and /proc/<pid>/environ is readable only by its owner where /proc/<pid>/cmdline is readable by every user on the machine (needs the matching commit in the odoo fork)
- The KeePass password reaches the Selenium login the same way: the command carries the NAME of an environment variable, never the value
- What a command PRINTS is redacted like the command itself: a tool that reprints its own arguments no longer puts the secret back into the terminal and into the log file

<!-- [fr] -->

- Les mots de passe et jetons sont caviardés avant l'affichage ou la journalisation d'une commande
- Le mot de passe maître d'Odoo ne voyage plus sur la ligne de commande : MASTER_PWD le porte, et /proc/<pid>/environ n'est lisible que par son propriétaire là où /proc/<pid>/cmdline l'est par tout utilisateur de la machine (exige le commit correspondant dans le fork odoo)
- Le mot de passe KeePass parvient à la connexion Selenium de la même façon : la commande porte le NOM d'une variable d'environnement, jamais la valeur
- Ce qu'une commande AFFICHE est caviardé comme la commande elle-même : un outil qui réaffiche ses propres arguments ne remet plus le secret dans le terminal ni dans le fichier de journal

<!-- [common] -->

## [1.6.0] - 2025-04-25

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Support multiple Odoo versions (12.0, 14.0, 16.0) in same workspace
    - This will help for the migration of modules
- Selenium script for increasing open software client interface and automating some actions.
    - Video recording
    - Support scrolling and word generating
- FAQ about kill git-daemon
- Supports Arch Linux, Ubuntu 23.10 to 25.04
- ADD repo JayVora-SerpentCS_SerpentCS_Contributions
- ADD repo CybroOdoo_CybroAddons

<!-- [fr] -->

- Support de plusieurs versions Odoo (12.0, 14.0, 16.0) dans le même espace de travail
    - Cela aidera pour la migration des modules
- Script Selenium pour augmenter l'interface client logiciel libre et automatiser certaines actions.
    - Enregistrement vidéo
    - Support du défilement et de la génération de mots
- FAQ sur comment tuer git-daemon
- Support d'Arch Linux, Ubuntu 23.10 à 25.04
- AJOUT du dépôt JayVora-SerpentCS_SerpentCS_Contributions
- AJOUT du dépôt CybroOdoo_CybroAddons

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

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

<!-- [fr] -->

- Refactorisation de la régénération image_db, utilisation de la configuration JSON pour construire l'image
- Guide pour le passage de dev à prod
- Mise à jour Docker buster vers bullseye
- Amélioration du script de formatage pour aider le code-generator
- Amélioration du script PyCharm
- Support d'OSX pour open-terminal
- Suppression de docker-compose et remplacement par docker compose
- Mise à jour de Poetry 1.3.1 vers 1.5.1
- Les tests peuvent être lancés avec une configuration JSON et supportent les logs/résultats individuellement
- Script pour rechercher docker compose dans le système
- Le script de recherche de modèle de classe peut produire en format JSON et supporte les informations de champ
- Amélioration de la documentation d'installation Docker minimale dans le README pour Ubuntu, test avec
  Debian (https://github.com/ERPLibre/ERPLibre/issues/73)
- Script de statistiques montrant l'évolution des modules dans ERPLibre supportant Odoo 17 et Odoo 18
- Dernière version wkhtmltopdf 0.12.6.1-3

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- NPM installed locally and not globally
- Improve python code writer efficiency
- Config generator supporting space into ERPLibre directory
- Script to update Poetry to support @ URL
- OSX and recent Ubuntu installation
- Cloudflare script integration

<!-- [fr] -->

- NPM installé localement et non globalement
- Amélioration de l'efficacité du générateur de code Python
- Le générateur de configuration supporte les espaces dans le répertoire ERPLibre
- Script de mise à jour de Poetry pour supporter les URL avec @
- Installation OSX et Ubuntu récent
- Intégration du script Cloudflare

<!-- [common] -->

## [1.5.0] - 2023-07-07

<!-- [en] -->
**Migration notes**

Recreating the virtual environment

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel

<!-- [common] -->

```bash
rm -rf ~/.poetry
rm -rf ~/.pyenv

rm ./get-poetry.py
rm -rf ./.venv

make install
```

<!-- [en] -->

Do a backup of your database and update all modules :

<!-- [fr] -->

Faire une sauvegarde de votre base de données et mettre à jour tous les modules :

<!-- [common] -->

```bash
./run.sh --no-http --stop-after-init -d DATABASE -u all
```

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Support d'Ubuntu 22.04 avec script d'installation
- Module mail_history et fetchmail_thread_default dans l'image DB de base
- Le Makefile peut générer l'image DB en parallèle avec `image_db_create_all_parallel`
- Le Makefile peut exécuter tous les code_generator avec `run_parallel_cg` et `run_parallel_cg_template`
- Script pour générer la configuration PyCharm et exclure les répertoires
- Support docker alpha+beta
- Limitation de la mémoire d'exécution lors de l'installation en développement
- Template de configuration nginx
- Script de statistiques de comptage de code
- Script montrant l'évolution des modules OCA
- Support du développement Windows, consulter la documentation d'installation
- Nouveau projet (code generator pour créer un module) supporte la configuration par paramètres
- Module sync_external_model pour synchroniser les modèles Odoo avec un module

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

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

<!-- [fr] -->

- Mise à jour Odoo 12.0 du 22-07-2020 au 01-01-2023
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.3.0
    - psycopg2==2.9.5
    - Werkzeug==0.16.1
    - vérifier le diff du fichier pyproject.toml pour toutes les informations
- Mise à jour vers Python==3.7.16
- Mise à jour poetry==1.3.1
- Mise à jour multilingual-markdown==1.0.3
- Mise à jour imagedb avec toutes les mises à jour Odoo
- Le dépôt documentation-user d'Odoo change pour documentation
- Le dépôt odooaktiv/QuotationRevision est supprimé
- Mise à jour de tous les dépôts (91) à fin 2022
- Renommage du module project_task_subtask_time_range => project_time_budget
- Renommage du module project_task_time_range => project_time_range
- Refactorisation de l'emplacement des scripts, création de répertoires dans ./script/ par sujet
- Utilisation de la commande parallel dans le Makefile
- Mise à jour de la version sphinx
- Amélioration de l'emplacement des scripts

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Debian 11 installation script
- Test result
- OSX installation (not finish to support)
- Poetry update support '~='

<!-- [fr] -->

- Script d'installation Debian 11
- Résultats de tests
- Installation OSX (support non terminé)
- La mise à jour de Poetry supporte '~='

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

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

<!-- [fr] -->

- Ubuntu 18.04 est cassé, besoin d'installer manuellement nodejs et npm
- Module contract_portal et suppression de la signature dans le portail de contrat, nécessite une mise à jour
- Rétrogradation du module helpdesk_mgmt pour supprimer l'équipe email et le champ de suivi
    - Module helpdesk_partner
    - Module helpdesk_service_call
    - Module helpdesk_supplier
    - Module helpdesk_mrp
    - Module helpdesk_mailing_list
    - Module helpdesk_join_team
- Module project_time_management
- Support de vatnumber, trop ancien
- Dépendances Python dépréciées comme pycrypto

<!-- [common] -->

## [1.4.0] - 2022-10-05

<!-- [en] -->
**Migration note**

- Update module `website`,`website_form_builder`.
- For dev, run `poetry cache clear --all pypi`

<!-- [fr] -->
**Note de migration**

- Mettre à jour les modules `website`,`website_form_builder`.
- Pour le développement, exécuter `poetry cache clear --all pypi`

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Script run_parallel_test.sh pour exécuter tous les tests en parallèle pour une meilleure vitesse d'exécution
- Documentation pour utiliser Docker en production
- Ajout de dépôts :
    - Ajepe odoo-addons pour supporter restful
    - OmniaGIT Odoo PLM
    - MathBenTech family-management
    - erplibre-3D-printing-addons
- Ajout de modules :
    - iohub_connector pour supporter mqtt
    - website_snippet_all pour installer tous les snippets, extraits de tous les thèmes
    - website_blog_snippet_all pour installer website_snippet_all avec website_blog et les snippets associés
    - sinerkia_jitsi_meet pour intégrer Jitsi
    - erplibre_website_snippets_jitsi pour intégrer Jitsi dans les snippets, travail en cours
- Ajout de modules par défaut :
    - auto_backup
    - muk_website_branding
    - website_snippet_anchor
    - website_anchor_smooth_scroll
    - crm_team_quebec
    - partner_no_vat
- Documentation Odoo dev
- Commande de formatage pour les addons supportés
- Installation de thème avec la commande Odoo
- Script pour installer les addons de thème
- Image du site web avec thème par défaut
- Image démo erplibre
- Tests avec couverture

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

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

<!-- [fr] -->

- Rétrogradation de sphinx à 1.6.7 pour supporter la documentation Odoo dev
- Mise à jour vers poetry==1.1.14
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.0.1
    - PyPDF2==1.27.8
    - lxml==4.9.1
- Le code generator exporte le site web avec les pièces jointes et le fichier de design scss avec documentation
- Le code generator supporte les snippets multiples
- Dans le dépôt Numigi_odoo-project-addons, renommage du module project_template en project_template_numigi
- Dans le dépôt Numigi_odoo-product-addons, renommage du module product_dimension en product_dimension_numigi
- Dans le dépôt Numigi_odoo-partner-addons, réactivation du module auto-install
- Dans le dépôt muk-it_muk_website, réactivation du module auto-install

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Poetry supports insensitive python dependency
- Code generator new project supports relative path and check duplicated paths
- Muk web theme table header background-color and on hover for Many2many
- Script docker-compose use lowercase name
- website_form_builder HTML support and allow option to align send button
- Odoo cherry-pick 2 commits bus fix
- Minor fix css color into module hr_theme from repo CybroOdoo_OpenHRMS
- Typo in project task when logging time

<!-- [fr] -->

- Poetry supporte les dépendances Python insensibles à la casse
- Le nouveau projet du code generator supporte les chemins relatifs et vérifie les chemins dupliqués
- Couleur d'arrière-plan de l'en-tête de tableau du thème web Muk et survol pour Many2many
- Le script docker-compose utilise des noms en minuscules
- website_form_builder support HTML et option pour aligner le bouton d'envoi
- Cherry-pick Odoo de 2 commits correctif bus
- Correction mineure de couleur CSS dans le module hr_theme du dépôt CybroOdoo_OpenHRMS
- Faute de frappe dans la tâche de projet lors de la saisie du temps

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Module package erplibre from ERPLibre_erplibre_addons and use instead image creation, check Makefile

<!-- [fr] -->

- Paquet de module erplibre de ERPLibre_erplibre_addons, utiliser à la place la création d'image, voir le Makefile

<!-- [common] -->

## [1.3.0] - 2022-01-25

<!-- [en] -->
**Migration note**

With new version of poetry, a bug occurs in the update. The solution is to delete the directory to let it
recreate. `rm -rf ~/.poetry`

<!-- [fr] -->
**Note de migration**

Avec la nouvelle version de poetry, un bogue survient lors de la mise à jour. La solution est de supprimer le répertoire pour le laisser
se recréer. `rm -rf ~/.poetry`

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Le code generator supporte les vues : activity, calendar, diagram, form, graph, kanban, pivot, search, timeline et tree
- Le code generator supporte la création de champs de vue portail et de formulaires
- Le code generator génère des snippets génériques pour demo_portal
- Le code generator génère code_generator avec code_generator_code_generator
- Le code generator teste le migrateur mariadb
- Le code generator supporte l'interprétation javascript pour les snippets
- Le code generator supporte l'héritage
- Nouveau projet du code generator pour créer la suite de génération de code
- Script pour tester la génération du module `code_generator`
- Make test_full_fast pour exécuter tous les tests en parallèle
- Module `web_timeline` et `web_diagram_position` dans l'image de base.
- Module `odoo-formio` de novacode-nl
- Module `design_themes` d'Odoo
- Formatage de l'en-tête Python avec isort

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

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

<!-- [fr] -->

- Mise à jour vers Python==3.7.12
- Mise à jour vers poetry==1.1.12
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.0.0
    - lxml==4.7.1
    - babel==2.9.1
    - pyyaml==6.0
    - reportlab==3.6.5
- Le module web diagram a toutes les couleurs de l'arc-en-ciel en option
- Refactorisation et simplification du code du code_generator, meilleur support du lecteur de code

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Downgrade Werkzeug==0.11.15, only this version is supported by Odoo 12.0. This fixes some http request behind a proxy.

<!-- [fr] -->

- Rétrogradation Werkzeug==0.11.15, seule cette version est supportée par Odoo 12.0. Cela corrige certaines requêtes HTTP derrière un proxy.

<!-- [common] -->

## [1.2.1] - 2021-09-28

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- doc/migration.md

<!-- [fr] -->

- doc/migration.md

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

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

<!-- [fr] -->

- Mise à jour des dépendances pip avec correctif de sécurité
    - Jinja2==2.11.3
    - lxml==4.6.3
    - cryptography==3.4.8
    - psutil==5.6.6
    - Pillow==8.3.2
    - Werkzeug==0.15.3
- Séparation du script generate_config.sh de install_locally.sh
- Amélioration de la documentation développeur
- Plus de scripts Docker

<!-- [en] -->
#### Code generator
<!-- [fr] -->
#### Code generator
<!-- [en] -->

- Improve db_servers generation code
- Improve wizard generate UI menu

<!-- [fr] -->

- Amélioration du code de génération db_servers
- Amélioration du menu UI de l'assistant de génération

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Mobile view menu item in Web interface from muk_web_theme

<!-- [fr] -->

- Élément de menu vue mobile dans l'interface Web de muk_web_theme

<!-- [common] -->

## [1.2.0] - 2021-07-21

<!-- [en] -->
**Migration note**

Because addons repository has change, config file need to be updated.

- When upgrading to version 1.2.0:
    - From docker
        - Clone project if only download docker-compose
<!-- [fr] -->
**Note de migration**

Parce que le dépôt d'addons a changé, le fichier de configuration doit être mis à jour.

- Lors de la mise à niveau vers la version 1.2.0 :
    - Depuis docker
        - Cloner le projet si vous avez seulement téléchargé docker-compose
<!-- [common] -->
            - `git init`
            - `git remote add origin https://github.com/erplibre/erplibre`
            - `git fetch`
            - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
            - `git checkout master`
            - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
<!-- [en] -->
        - Update `./docker-compose.yml` depending of difference with git.
        - Run script `make docker_exec_erplibre_gen_config`
        - Restart the docker `make docker_restart_daemon`
    - From vanilla
        - Run script `make install_dev`
        - Restart your daemon
        - Regenerate master password manually

<!-- [fr] -->
        - Mettre à jour `./docker-compose.yml` selon les différences avec git.
        - Exécuter le script `make docker_exec_erplibre_gen_config`
        - Redémarrer le docker `make docker_restart_daemon`
    - Depuis une installation vanilla
        - Exécuter le script `make install_dev`
        - Redémarrer votre daemon
        - Régénérer le mot de passe maître manuellement

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Adaptation du script pour donner un statut d'exécution
- Markdown multilingue
- Guide pour utiliser Cloudflare avec DDNS
- Script pour vérifier le diff git et ignorer la date
- Dépôt avec l'image ERPLibre
- Amélioration de l'utilisation du dépôt git, filtrer les dépôts par cas d'utilisation
- Thème de site web ERPLibre de TechnoLibre
- Snippet de site web ERPLibre
    - Snippets HTML de base
    - Snippet carte
    - Snippets chronologie
- Module contract_digitized_signature avec contract_portal
- Module disable auto_backup
- Commande CLI Odoo db pour manipuler la restauration de base de données
- Commande CLI Odoo i18n pour générer les fichiers pot i18n

<!-- [en] -->
#### Makefile
<!-- [fr] -->
#### Makefile
<!-- [en] -->

- Format code
- Code generator test
- Addons installation
- OS installation
- Restore database
- Docker execution

<!-- [fr] -->

- Formatage du code
- Test du code generator
- Installation des addons
- Installation du système d'exploitation
- Restauration de base de données
- Exécution Docker

<!-- [en] -->
#### Code generator
<!-- [fr] -->
#### Code generator
<!-- [en] -->

- Code generator for Odoo module, depending of ERPLibre
- Support map geospatial
- Support i18n
- Script to transform Python and XML to Python code writer script to regenerate themselves

<!-- [fr] -->

- Code generator pour les modules Odoo, dépendant d'ERPLibre
- Support des cartes géospatiales
- Support i18n
- Script pour transformer Python et XML en script d'écriture de code Python pour se régénérer eux-mêmes

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update Python dependency with Poetry
- Format all Python code with black
- Module auto_backup with sftp host key
- Module muk_website_branding use ERPLibre branding
- Update docs with vscode support, custom document layout, custom email template and trick to use params to share
  variable

<!-- [fr] -->

- Mise à jour des dépendances Python avec Poetry
- Formatage de tout le code Python avec black
- Module auto_backup avec clé d'hôte sftp
- Le module muk_website_branding utilise le branding ERPLibre
- Mise à jour de la documentation avec le support vscode, mise en page de document personnalisée, modèle d'email personnalisé et astuce pour utiliser les paramètres de partage
  de variables

<!-- [en] -->
#### Docker
<!-- [fr] -->
#### Docker
<!-- [en] -->

- Use buster python 3.7.7 image to remove pyenv
- Update Postgresql to support Postgis
- Support volume addons /ERPLibre/addons/addons

<!-- [fr] -->

- Utilisation de l'image buster python 3.7.7 pour supprimer pyenv
- Mise à jour de PostgreSQL pour supporter PostGIS
- Support du volume addons /ERPLibre/addons/addons

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Ubuntu installation
- Poetry installation
- Geospatial with postgis can be installed

<!-- [fr] -->

- Installation Ubuntu
- Installation de Poetry
- Le géospatial avec PostGIS peut être installé

<!-- [common] -->

## [1.1.1] - 2020-12-11

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Developer, test, migration and user documentation
- Branding ERPLibre with muk_branding
- Uninstall module from parameter Odoo
- Makefile to generate ERPLibre documentation WIP
- Docker support volume on /etc/odoo
- Docker support update database

<!-- [fr] -->

- Documentation développeur, test, migration et utilisateur
- Branding ERPLibre avec muk_branding
- Désinstallation de module depuis les paramètres Odoo
- Makefile pour générer la documentation ERPLibre (travail en cours)
- Support Docker du volume sur /etc/odoo
- Support Docker de la mise à jour de base de données

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Better documentation on how to use ERPLibre and release
- Support wkhtmltox_0.12.6-1

<!-- [fr] -->

- Meilleure documentation sur l'utilisation d'ERPLibre et les versions
- Support de wkhtmltox_0.12.6-1

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- db_backup to accept public host key on sftp
- Docker dependency
- Freeze poetry version 1.0.10

<!-- [fr] -->

- db_backup pour accepter la clé d'hôte publique sur sftp
- Dépendances Docker
- Gel de la version poetry 1.0.10

<!-- [common] -->

## [1.1.0] - 2020-09-30

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Docker
- Pyenv pour gérer les versions Python
- Poetry pour gérer les dépendances Python
    - Script poetry_update pour rechercher toutes les dépendances dans les addons
- Travis CI (travail en cours)
- TODO.md
- Guide pour mettre à jour tous les dépôts avec la communauté
- Mise à jour du manifeste
    - Ajout des dépôts OCA manquants
    - Ajout de médical, gestion immobilière et plus
    - Ajout du dépôt cloud/saas

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update to Odoo Community 12.0 and all addons
- Rename venv to .venv
- More documentation on how to use ERPLibre

<!-- [fr] -->

- Mise à jour vers Odoo Community 12.0 et tous les addons
- Renommage de venv en .venv
- Plus de documentation sur l'utilisation d'ERPLibre

<!-- [common] -->

## [1.0.1] - 2020-07-14

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

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

<!-- [fr] -->

- Amélioration de la documentation avec l'environnement de développement et de production
- Amélioration de la documentation avec le dépôt git
- Déplacement du manifeste default.xml à la racine, l'emplacement par défaut
- Support de default.staged.xml pour mettre à jour la prod avec le dev
- Fonctionnalité pour afficher le diff entre les manifestes ou entre les dépôts de différents manifestes
- Mise à jour du manifeste
    - Thème Muk dans erplibre_base
    - Ajout du brouillon d'approbation de facture dans le portail
    - Nouveau module sale_fix_update_price_unit_when_update_qty
    - Nouveau module account_invoice_approbation
    - Nouveau module sale_margin_editor

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Production installation with git_repo

<!-- [fr] -->

- Installation de production avec git_repo

<!-- [common] -->

## [1.0.0] - 2020-07-04

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Environment of development, discovery and production with documentation and script.
- Google git-repo to support addons repository instead of using Git submodule.

<!-- [fr] -->

- Environnement de développement, découverte et production avec documentation et scripts.
- Google git-repo pour supporter le dépôt d'addons au lieu d'utiliser les sous-modules Git.

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Git submodule

<!-- [fr] -->

- Sous-modules Git

<!-- [common] -->

## [0.1.1] - 2020-04-28

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Support helpdesk supplier, helper, employee and services
- Support [SanteLibre.ca](https://santelibre.ca) with MRP, website, hr, ecommerce
- Donation module with thermometer for website
- Script to fork project and all repos in submodule to create ERPLibre

<!-- [fr] -->

- Support du helpdesk fournisseur, assistant, employé et services
- Support de [SanteLibre.ca](https://santelibre.ca) avec MRP, site web, RH, commerce en ligne
- Module de don avec thermomètre pour le site web
- Script pour forker le projet et tous les dépôts en sous-module pour créer ERPLibre

<!-- [common] -->

## [0.1.0] - 2020-04-20

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Move project from https://github.com/mathbentech/InstallScript to ERPLibre.
- Support of Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

<!-- [fr] -->

- Déplacement du projet de https://github.com/mathbentech/InstallScript vers ERPLibre.
- Support d'Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Support scrummer, project, sale, website, helpdesk and hr
- Support Nginx and improve installation

<!-- [fr] -->

- Support de scrummer, projet, vente, site web, helpdesk et RH
- Support de Nginx et amélioration de l'installation

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Support only python3.6 and python3.7, python3.8 causes error in runtime.

<!-- [fr] -->

- Support uniquement de python3.6 et python3.7, python3.8 cause des erreurs à l'exécution.

<!-- [common] -->

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
