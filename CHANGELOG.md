
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## Added

- Site presets for the VPN: one `.json` carries a site's gateway, protocol and connection group, and neither a username nor a secret, so it can be handed around. Read from `conf/vpn_presets/`, then from a git-ignored `private/vpn/presets/`, then from any directory listed in `vpn_preset_paths`; on the same identifier the latest wins, so a site fixes a shipped template without touching a tracked file
- Import a Cisco AnyConnect `.xml` profile from the menu, browsing the client's own directories or typing the path, and get a preset from its `HostName`, `HostAddress` and `UserGroup`
- OpenConnect tells apart the two mechanisms that designate a service on one concentrator: the connection group in the URL and the value picked from a dropdown. Confusing them hands over another service's login form, so correct credentials are refused with nothing naming the group
- Reach a gateway that demands an embedded browser for SAML, which stops OpenConnect on « No SSO handler »: the web step is delegated to an `openconnect-sso` helper that the installer offers to set up, and the tunnel is then brought up by the driver itself, so the interface name, the state files and the diagnosis stay with the profile
- Declare a concentrator that compares only the first characters of a password: it is announced before the secret is stored, and nothing is ever truncated
- The VPN installer looks for `vpnc-script` — a file, not a binary on the `PATH` — and names the package to install per distribution family, instead of letting the tunnel fail on an interface that never appears
- A command launched by the VPN runner gets `/dev/null` on standard input, so a captured-output command can no longer be stopped by a SIGTTOU and freeze the machine's package manager
- The VPN profile list marks which profiles carry a live tunnel, so connecting one already up asks first and disconnecting one already down says so instead of looking like a mistake. A profile is judged on its interface, not on the state file a tunnel killed without `down` leaves behind — a state left over used to be reported as mounted on the same screen that declared the process gone
- `Assistant › LLM` — ask a model server over several turns, local or remote. The history lives in memory and dies with the menu, `/save` being the only way to keep a trace; every command carries a leading slash, so a question pasted over several lines stays one turn. A third-party destination has to be retyped before the first send
- Server recognition across eleven ports and twelve families, identity read from the response BODY and never from the port: one port hosts up to three products, and one family re-serves another's whole native API
- Finding a server from six sources — the loopback, this machine's QEMU domains, the hosts of `~/.ssh/config`, an address or a network typed by hand, and the networks read over SSH on another machine. Anything wider than a `/24` is refused before enumeration, and two preferences bound the sweep: `assistant_sweep_workers`, `assistant_sweep_timeout`
- A gpt catalogue in `script/todo/assistant/gpt/`: one Markdown file per tool, whose declared requirements are matched against what the server announces. An unknown never greys a tool out — only a requirement contradicted by a field actually read does, with the figure that refuses it
- A declared READ-ONLY context per tool, files and allowlisted commands, shown and confirmed before the first send, capped in size and duration, and scanned for identifying data. The scan's honest limit is stated: it sees addresses, e-mails and account paths, not names
- `Execute › GPT code › Claude Code` — list the machine's sessions, ask one a question with read-only tools, or resume one in its own terminal. A copy is branched by default, since two writers on one session lose a branch
- `check_comment_hygiene.py` signals a fully qualified machine name in a comment, as a re-read signal and never a finding: a BARE host name is mechanically indistinguishable from an ordinary word, so the absence of a signal proves nothing about names. The copyright header, the RFC 2606 domains and any address carried by a URL are left alone
- Transform data, a menu entry that opens an external file — Excel, Access, CSV, XML or JSON — reports what it holds, then draws an anonymised copy of it. The original is never touched. Numbers are drawn from the measured extent of their own column rather than a fixed 0-1000 range, which turns a tax rate into 743 and a year into 12; they are drawn without replacement, since a hundred distinct keys in a range of a hundred otherwise yield sixty-six outputs and a fixture that no longer reimports. Text takes a French word from a local dictionary of 1366, assigned by a counter rather than a draw, and a portable mapping table gives the same client the same word across a whole batch
- Eleven structural labels are left alone on their NAME — `id`, `create_uid`, `sequence`, `active` and the rest, plus anything ending in `/id` or `/.id` — since a test set has to keep working. Every OTHER column is judged on its measured CONTENT, never on the strength of its name. In an import-ready export, `partner_id` holds the relation's display name and `display_name` is the data itself, so deciding on the label copied the most identifying columns of the file verbatim while announcing them as protected
- The anonymiser rereads the bytes it has just written and refuses the copy when a value it announced as replaced survives in it. A workbook holds data in a dozen places that are not cells: a pivot cache and an external link each carry an entire copy of the source, a chart caches its categories and its axis titles, a custom number format carries a label, a comment carries its author, a cell hyperlink carries a path. The guard depends on no list of those, so a place nobody thought to clean produces a refusal instead of a silence — and what stays by decision, a header row or a column left alone, is named on screen before anything is written
- Transform data anonymises an Odoo database too, the entry asking for the SOURCE rather than the format: an external file, a live database, or a backup zip taken from `image_db/`. A zip is never modified — it is restored into a database, anonymised there, then dumped into a NEW zip by Odoo's own backup, so the dump, the filestore and the manifest are written by the software that will read them back. A live database is modified ITSELF, which is said before the work and not after, and nothing is drawn when the write did not happen: declining otherwise handed back a zip of the untouched database, announced as anonymised. A register records which databases the entry produced, since the server does not
- An anonymised number can keep its digit count, on the file anonymiser and on `anonymize.py` alike (`--keep-digits`): 8839 then draws in 1000..9999, so the copy keeps columns of the same width, which an export read by eye or imported into a bounded field asks for. Each value keeps ITS own width and not its column's — 7 stays at one digit where 12 keeps two — and below the unit the rule does not apply, 0.15 having no digit before the point. The option trades one guarantee for another: the measured extent no longer bounds anything, so a rate or a year can leave its range, and the preview SAYS so rather than letting it be found at reimport. Uniqueness is what yields when a band fills up, a duplicate of the same width beating a value of a different one, and the band never exceeds what the type RECEIVING the draw holds, which is not always the column's: an Odoo `integer` over a column PostgreSQL did not create as an integer — what an upgraded base carries — is poured into `numeric`, which has no ceiling, where `integer` stops at 2 147 483 647 and a draw past it aborts the whole write, that write being one transaction
- The anonymiser asks four questions instead of eleven, seven of the eleven having had an obvious default. Answering them one by one to arrive at the same place makes prompts be passed by reflex, and a prompt passed by reflex consents to nothing; they now live behind « Advanced options? ». The short path DECLARES what it takes, in sentences rather than in yes/no, since those are decisions taken and not questions whose answer was lost. Macros and charts are asked on both paths: they are not visible in the cells
- `markdown-it-py` is declared as a functional dependency: it renders the language model's markdown to HTML, before sanitising, on the assistant page. It reached the environment transitively through `bandit` → `rich`, a lint tool, so removing a lint dependency removed a portal page's rendering engine
- A download cache shared by the QEMU VMs of a host, installed from **Deployment › QEMU cache**. Two VMs of the same distribution stop pulling the same hundreds of megabytes twice: a package file is served from disk, while an index is always taken from upstream, so a withdrawn package can never turn into a « failed retrieving file … 404 ». An index is stored all the same and only comes back out when upstream is unreachable, which is what makes an offline deployment possible. The cache never shrinks by itself: `--status` says what it occupies
- Interception is transparent and covers the whole host bridge, so a VM cannot opt out from the inside. Every VM trusts the cache's authority as long as the service runs. To take ONE machine out, tick « keep this VM out of the download cache » when deploying: its MAC address is fixed before creation and an exception is posted on the host. To take them all out, stop the service — its rules leave with it. A Proxmox host that is itself a VM here is no exception: the machines it carries come out behind its address, so the deployment poses the authority in each of them, by ssh, before installing anything
- The measurement is not limited to Arch: any catalogue system whose package family is known, and either a batch of packages or the real install of ERPLibre and Odoo 18. Measured on Ubuntu 24.04 with that real install, the second VM pulled **zero byte** of package from the network and finished 19 % faster. Verified on the seven systems of the catalogue
- Git is MIRRORED rather than cached: its protocol is a negotiation, the server computing its answer from what the client already holds, so no answer is reusable. A bare mirror per upstream repository is kept on the host and served locally, and a mirror already held serves with no network at all — measured, a repository cloned inside a VM while the cache's upstream was cut. Measured on a full ERPLibre install: the second VM pulled **zero** git request from upstream, where git had been four fifths of the traffic. **Deployment › QEMU cache › Git mirrors** fills them ahead from the manifests, so the first VM does not pay every clone
- An offline deployment also covers the base suite of a cloud image. Its apt REVALIDATES the index it ships instead of downloading it, upstream answers 304, and the cache had no body to keep — so that one suite, and only it, was missing offline while its `-updates` and `-security` neighbours came off the disk. A conditional request for something the cache does not hold now goes upstream without its condition, once, and a client that holds its own copy gets 304 rather than 504 when upstream is mute.
- What an offline deployment covers, exactly: packages, repository indexes and git. NOT what the cache is forbidden to decrypt — a client carrying its own trust store, npm and poetry among them, is tunnelled opaquely, and a tunnel carries nothing once the network is gone. A full ERPLibre install therefore still needs the network, though everything the cache holds is served from disk
- A mirror is COMPLETE where `repo sync` clones at depth one, so it costs tens of gigabytes. Below ten gigabytes free, no new mirror is created and the request goes back upstream. The diagnosis says what the objects and the mirrors each occupy
- **Deployment › QEMU cache › Age and cleanup** groups the cache by age of last use (day, week or month; objects and git repositories apart) and gives back what has not served for a chosen delay, or everything. A served object has its date renewed, so « old » means « no longer used ». Both cleanups say what would go before erasing anything, and entry 5 lists the mirrors heaviest first to remove one
- `long_test/qemu_cache.py` measures whether the cache really serves the second VM, and `--hors-ligne` cuts the upstream of the cache service alone to prove a third VM still builds from the stored index
- Before cutting, the form says whether the cache holds the base suite of each system asked for: F5 warns « cache holds nothing for ubuntu 26.04 » and a second F5 goes ahead anyway. The verdict is given only where a release is named unambiguously in the URL — the apt families — rather than reassuring wrongly elsewhere. The verdict is given component by component — `main`, `universe`, `restricted`, `multiverse`, on the base suite and on its `-updates` and `-security` companions — because a single stored URL used to silence it while a whole component was missing, and apt only said so twenty minutes later, by « Unable to locate package »
- **Deployment › QEMU cache › Copy it to another machine** carries the store to another ERPLibre host in a single stream — `tar`, compressed, over ssh, no intermediate file for tens of gigabytes — and hands the files to the service account on arrival, the same account rarely bearing the same number on two machines. Only the STORE travels: an object is keyed by its URL and never by the machine that fetched it, and a git mirror is a repository. The settings stay behind — bridge, subnet and authority belong to the host, and entry 1 poses them there
- The deployment form carries a **Network** section with « No internet connection »: for the whole deployment, install included, the cache service loses its way out AND the VMs lose theirs — ping, other ports, UDP, IPv6 — so a step that takes any path but the cache fails instead of quietly succeeding online. Names no longer resolve through the internet either: the host answers every name itself with an address the cache intercepts, so only what the cache holds can be reached; dnsmasq must be installed on the host. A VM behind the cache pulls from one fixed apt mirror: cloud-init's mirror search discards every mirror behind a resolver that answers every name, and would fall back on another mirror than the one the previous VMs filled the cache from. The cut refuses rather than drops, so an address the cache does not hold answers 504 at once instead of after a connection timeout; a kernel that cannot load the reject module gets the dropping set instead. Offered only where the cache runs, and the deployment refuses rather than run with the upstream still up, a VM built that way succeeding for the wrong reason. **Proxmox VE** carries the same box, offered where its host is itself a VM of this bridge: its guests come out behind its address, so the local cut covers them and nothing is posted on the remote host. A Proxmox host that does not live here is never offered it — nothing here can cut its way out
- A Proxmox VE deployment can ask for **3D acceleration**. The VM is created with an accelerated screen (`--vga virtio-gl`) rather than the serial console as its display, and the account joins the GPU groups INSIDE the guest: the render node belongs to `root:render`, so without them every GL application falls back to software rendering while the VIRGL negotiation reports success, and nothing says so. The box is offered only where the remote host has a render node AND the three libraries Proxmox loads for that screen — VIRGL, GL and EGL. It names the missing ones and refuses to start the machine, once its disk is written and its configuration posted, so a host carrying GL without EGL would fail at the very last step. Where a piece is missing the form says which, and the package to install on the host: a box that vanishes without a word reads as a regression. A button installs them without leaving the screen — the form hands the terminal back so sudo can ask for a password and apt can be watched — then reads the host again rather than taking apt's word for it, and the box appears in place of the message. The serial port stays posted, so `qm terminal` keeps working
- Offline, the cache replays what an online pass saw, not only 200 bodies: redirects, definitive refusals (404/410) and HEAD answers of volatile URLs are kept without a body, under keys of their own, and served ONLY when upstream is mute. A TUF client probing the next version of its root gets the 404 it expects instead of a 504, so mise installs Python offline with its Sigstore verification intact; GNOME extensions, Claude Code's installer and rtk's version lookup follow their redirects offline
- The offline cut ends when the last installation ends, not when the monitor closes: a root unit, handed the lift at launch, waits for every installation's exit marker and survives the monitor closed early, todo.py killed or the terminal gone — 12 h at most. The monitor is therefore required while offline. A second offline deployment is refused while one runs, and an online deployment started meanwhile is told it would run offline
- F5 also reads the previous offline runs of the same VM and warns « at least N addresses were missing », minus what the store holds now (`erplibre_go_qemu_cache --detient`, read-only, no root). **Deployment › QEMU cache › Fill what offline runs lacked** replays them online, through the cache
- The install log names the commit the VM runs; offline, the recap says, branch by branch, which commit the cache's mirror will give
- `long_test/qemu_cache.py --distro tous` (or a comma list) chains one campaign per catalogue system, destroys each system's VMs before the next, and ends on a table of verdict, durations and upstream bytes. A failure does not stop the series
- The QEMU download cache can clean itself up every day: by age (`EL_PURGE_AGE`, e.g. `90j`) and by size ceiling (`EL_MAX_SIZE`, e.g. `50G`, the least recently served going first, objects and git mirrors alike). Both are off by default and set from **Deployment › QEMU cache › Automatic cleanup**, which previews what would go; `--purge-to-size` runs the ceiling by hand. A reinstall keeps the values chosen
- NixOS 25.11 as a deployable system, alongside the eight others. It is the only one no distribution publishes a cloud image for: the image is rebuilt by a third party, so its release is pinned, its sha256 verified at every download, and its origin printed before anything is created. cloud-init receives no network configuration there — its networkd renderer takes the key of a block as an interface NAME, where netplan honours a `match:` — and the account is created with `/bin/sh`, sshd refusing an account whose shell does not exist
- ERPLibre installed on NixOS, its dependencies DECLARED in `conf/nixos/erplibre.nix` and applied by `nixos-rebuild`, where the four other families install them one command at a time. `services.envfs` answers `/usr/bin/env` and `programs.nix-ld` gives manylinux wheels the dynamic loader they ask for; the headers of what has no wheel are linked into the system profile, and its libraries reach the loader too, a module compiled on the machine carrying no RPATH. The install reaches it from the menu like any other distribution: the bootstrap poses git, make and python3 — absent from that image — in the user profile for the clone, and « make install_os » redeclares them for the system. Checked on a VM: the 362-package lock installs and Odoo answers over HTTP
- A `nix + nixos-anywhere` option on the OTHER distributions, the reverse of picking NixOS: it leaves an ordinary VM able to install NixOS onto any machine reachable over SSH. Nix is called by absolute path, the remote shell's PATH being frozen before the installer drops the binary, and the flake features are repeated on the command line, writing `nix.conf` needing a sudo that may fail
- NixOS deploys on a **Proxmox** host as it does on QEMU/KVM, which took three fixes no code reading could have found. Its image has no BIOS boot sector: a VM created in SeaBIOS reports « running » with a silent console, so the catalogue now marks which images need UEFI — one marker per distribution, since Debian 13 boots in SeaBIOS on that same host. `--ciuser` and `--sshkeys` defer to the image's DEFAULT account, which NixOS declares as another name: the repository's own cloud-config now travels as a snippet for every distribution, carrying an explicit `users:` block. And the cloud-init drive moves to the SCSI bus — an image built for virtio alone has no ATA driver and never sees an IDE drive, so cloud-init hunted network datasources and the VM came up with no account at all. Checked end to end: NixOS answers with `/bin/sh`, Debian 13 with `/bin/bash`, sudo on both
- The third-party image is verified against the sum the repository pins for it on the Proxmox path too, where a bare `wget` used to be enough. One accessor carries that sum for both paths, and the check runs even on a cached image — the case aimed at is a file substituted or truncated between deployments, which a presence test cannot see
- One entry of the download cache can be removed, by URL. A checksum that does not match invalidated nothing: the store kept serving the same bytes, and re-downloading changed nothing since the store is what answers. Neither existing purge reaches it — `--purge` erases everything, and `--purge-older-than` skips what is recent while every service resets that date, so a poisoned object that keeps being served never ages. `--oublie` is symmetric to `--detient`: same input lines, same key functions, same refusals, and a present object that resists is reported as a refusal rather than a forget. Both checksum failures now name it, with the exact URL
- The install log carries what the host decided before launching: the download cache authority placed or refused, the bypass, the mirror. Those lines were said on a console that scrolls away, while the file reopened after a failure held only the symptom — on a guest with no trust store, a refused certificate, hundreds of derivations to build and six hundred lines of errors, without a word on the cause
- One entry of the download cache can be forgotten from the menu, under « Age and cleanup ». The binary could already do it; the menu offered only the two bulk purges, neither of which reaches a single object — « erase what has not served » never reaches one the service rejuvenates each time it serves it, and « erase everything » costs the whole cache for one file. `--detient` runs first and is the preview: same line, same key, nothing modified
- `erplibre_go_qemu_cache --recle` stores a cache's objects again under the current key, without downloading anything, and merges the copies a mirror carried under several paths. Objects written under the former key rule stay on disk but become UNREACHABLE, so the service asks upstream for them again and the space they hold serves no one: on a store of 12 764 objects, 5 419 were in that case — 9.11 GiB — and merging the duplicates returned about 3.37 GiB. The service must be stopped, the body being renamed before its meta, and `--dry-run` only counts what would move. A status-only entry is left alone, its key carrying the host rather than the path
- The `pre-commit` hook runs `check_python_version.py` on staged files: it reports source that does not parse under the Python of `conf/python-erplibre-version`, without blocking the commit, and says when no such interpreter was there to check. Neither black nor flake8 sees that fault — black's target bounds what it writes, never what it accepts
- `Deploy › Local › [4]` opens a SOCKS proxy over SSH — `ssh -D`, port 1080 by default — so the browser reaches, FROM the remote machine, an interface listening only on its loopback or a host of its network. The address comes from `~/.ssh/config` or by hand; an alias is passed to ssh as is, so its `ProxyJump` still applies and a nested VM stays reachable. The Firefox settings print before the tunnel opens, the command only returning on Ctrl+C
- `make format_test` formats `test/` and `long_test/`, which no target covered: 75 files out of 210 followed no standard, and only a file a diff reported was ever touched

## Changed

- `Assistant › [1]` no longer sends every question to a single remote API on a fixed model: it asks whichever server is configured, and falls back to the remote one only when no local server answers
- The comment hygiene check reads Go comments, not only `#` ones: `//` outside a string, the raw string between backticks, and `/* … */` blocks
- Debian and Ubuntu `by-hash` index files are served from disk, their name being the digest of their content; `…/releases/latest/download/…` is no longer pinned to the first version seen
- An upstream that refuses or drops connections is remembered for 20 s: a request with a stored answer is served at once instead of waiting its connect timeout, which made up most of an offline install's time; a request with nothing stored still tries upstream. A git mirror skips its refresh while its forge is unreachable
- Mirror prefetch runs under the cache's service account, never as root
- The long-test menu asks before creating real machines, and asks again, in words of its own, before `--detruire` removes machines with their disks. The command is shown first, which is what makes the question answerable; a dry run or a performance report creates nothing and asks nothing
- Every entry of the Proxmox VE menu carries an icon, the same picture meaning the same action as in the other menus of the tool
- The QEMU cache binary speaks English or French: service journal, `--status`, `--age`, option help and the error served to a VM. The language comes from `--lang`, then `EL_LANG`, then French; the installer writes `EL_LANG` to the service settings and the TODO menu passes its own. Rules, verdict codes and JSON keys are never translated
- A repository index the cache already holds is revalidated with its ETag rather than downloaded again: upstream still judges every request, and a « 304 » serves the stored body from disk. On a full ERPLibre install the pip indexes, npm metadata and repo bundle had been about 110 MB per VM, taken whole each time. An index stored without its host — shared by every mirror of a rotating list — and an answer carrying no ETag are taken whole as before; the access log names the new outcome `revalidated`
- A registry page served under `Vary: Accept` keeps one copy per representation. npm asks for the same `/npm` page abridged, then complete, then abridged again; kept under one key they replaced each other and the 31 MB were fetched on every install. Each representation is now revalidated and, offline, served on its own; `--detient` still reads the page under its URL alone
- A VM deployed with the cache upstream cut — QEMU form, Proxmox VE, or `deploy_qemu.py --offline` — has npm's security audit turned off (`NPM_CONFIG_AUDIT=false`): it queries a remote service no cache can replay, and failed on every offline install. An online VM keeps its audit
- Verifying a downloaded image no longer needs `--verify`: it runs by default for every distribution that publishes a sum, and `--no-verify` is what skips it — to be kept for offline runs, where a substituted image would otherwise pass unremarked
- `--bios` is refused on an image with no BIOS boot sector, and says why. Forced there, it gave a VM reported « running » with a silent console — the very failure that flag exists to avoid elsewhere
- The tooling virtual environment `.venv.erplibre` runs Python 3.14.7, independently of the Odoo one (3.12.10 for Odoo 18.0). `install_erplibre.sh` builds it through `install_venv.sh` and `EL_PYTHON_PROVIDER` instead of the system `python3`
- `.venv.erplibre` on an incompatible Python is DELETED and rebuilt; whatever was installed in it by hand goes with it. Odoo's venv is kept when it merely differs in version, and rebuilt only when it is unusable: rebuilding it redoes a whole Poetry install. A directory without `pyvenv.cfg` is never deleted
- `make` and `make todo` run `./todo.sh`, a launcher whose name says a menu opens and not an installation; it hands every argument to `install.sh`, which picks an interpreter able to READ the code before running it: `.venv.erplibre` on the right version, else a recent enough system `python3`, else the install, which runs only on a yes typed in a terminal (`o`, `oui`, `y`, `yes`) since it can delete `.venv.erplibre`. A system older than `conf/python-erplibre-version` would otherwise stop on a syntax error raised before any guard could name the command to type. TODO then relaunches itself in `.venv.erplibre`, or offers to run `install_erplibre.sh` in a terminal
- The production Docker image builds `.venv.erplibre` on Odoo's Python and stops when that Python cannot parse `script/`
- Debian 11 is dropped from the deployment catalogue: its LTS ended, and its security suite is neither served nor archived — the index it still publishes names packages whose pool no longer holds the file, so apt stops before installing git. Debian 13 takes its place, its cloud image always being the latest point release
- Every container image is built on bookworm, whatever the Odoo version. The base is `python:<version>-slim-<suite>`: the interpreter comes from the official image, never from Debian, and the bookworm variants exist down to 3.7.17. The wkhtmltopdf build follows the suite — bullseye's requires libssl1.1, absent from bookworm
- The PATCH bounds only Odoo's venv, whose pyproject requires `>=3.12.10,<3.13`. For the tooling one, the major.minor is enough: requiring the patch turned away a distribution's Python one step behind — NixOS 25.11 ships 3.14.2 where conf asks 3.14.7 — and made pyenv COMPILE CPython for a difference nothing needs
- `make format` picks the formatter from each file's context: an Odoo module keeps isort and black on `py37`, the series still supported going down that far, while this repository's own tooling goes through ruff, configured once in `.ruff.toml`. ruff follows CPython's versions, where black 24.8.0 stops at `py313`, and its import sorting replaces isort; it is also what the OCA standard uses since it left black
- The repositories that Google Repo checks out under `script/` are excluded from that formatting, a named path included: reformatting them would write in someone else's history. `target-version` stays at `py310` there, because the git hooks carry `#!/usr/bin/env python3` and a distribution still ships 3.10 — from 3.14 on, ruff would write `except A, B:` without parentheses
- The list of Claude Code commands in `TODO › Execute › GPT code › Claude configs` compares each ERPLibre template in `conf/` with its copy in `~/.claude/commands/`: a command not installed is shown, an outdated copy is marked with its count of added and removed lines, and a command that comes from elsewhere is labelled as such. On a yes it prints the diff, then redeploys the outdated copies, keeping the git name and e-mail `/commit` carried
- A commit message opens on an English subject and an English body; `--- FR ---` then opens the French section, which starts with the subject translated under the same tag. The `commit-msg` hook refuses a `--- EN ---` marker and a French section without that title, and checks the title like a subject. `/commit` and `/git_prepare_merge` follow the same order
- TODO menus: the language is set only from Configuration, the duplicate entry in Execute is gone, and Fork moves from the main menu to Configuration. The main menu now numbers Telemetry 4 and Configuration 5. The language chooser shows a flag per language
- Odoo 18 dependencies refreshed. `openai` is pinned to 2.x, whose 3.x requires an `idna` that Odoo 18 forbids; `fsspec` is pinned beside `s3fs`, which demands it at its own exact version, so the two move together; `meteostat` returns to 1.x, every 2.x capping `pytz` below 2024. PyMuPDF stays excluded on s390x, now declared in the requirements so a regeneration keeps it. Major bumps of `ujson` 6, `plotly` 7, `python-slugify` 9 and `sqlalchemy` 2.1 are not yet tested
- Dependabot ignores the major versions of `meteostat`
- Odoo 18 moves to pandas 3.0.6, cryptography 50 with pyopenssl 26.4, Pillow 12.3 and botocore/boto3 1.43.75 with aiobotocore 3.9.1, the highest botocore its narrow range accepts. The seven modules that import pandas run their pandas calls unchanged; `freq='d'` in a Cybro attendance dashboard now warns and will break with pandas 4
- Dependabot groups `aiobotocore`, `botocore` and `boto3` into one pull request, since each aiobotocore accepts only a narrow botocore range; security fixes still arrive on their own
- `TODO › Transform data` reads Excel with openpyxl 3.1.5 and xlsxwriter 3.2.9; the leak test that guards openpyxl's exact pin passes on them
- factur-x requires 6.8 outside s390x, the version already locked, so a regeneration can no longer fall back to an untested 4.x or 5.x
- The interface chooser of the QEMU deployment and of the Odoo migration, and its preferences in `TODO › Configuration`, mark the TUI form with 📋 and the line by line questions with 💬

## Fixed

- Reading the dnsmasq leases no longer opens a root password prompt: the files are read directly, which suffices on a standard install where they are 0644, and only then is `sudo -n` tried, which fails instead of asking. Displaying a VM list called that path once per VM, and waiting on a VM called it every three seconds for ten minutes
- `--max_process` runs again on Python 3.10 and later: `loop=` left `asyncio.wait` in 3.10 and `asyncio.get_event_loop()` raises outside a running loop since 3.14, so the pool was not even constructible while the help still advertised the flag
- A prompt no longer writes its colon twice — the most-seen menu of the software asked « Command:: », and seven remote-deployment prompts showed a colon followed by another
- Eleven submenus now leave their segment in the breadcrumb, and navigation telemetry stops filing them as commands under their raw method name
- The three readers of `~/.ssh/config` agree on what a machine name is: an alias declared with a lowercase `host` is seen, a tab separates as legally as a space, and a negated `!name` pattern is no longer taken for a machine to connect to
- Three translation keys declared twice are gone, and a check refuses the next one: a repeated key silently overwrites the previous, which had already cost a menu label
- `anonymize.py` abstains from a unique numeric column and NAMES it in the report. A draw guarantees nothing on a unique column, and a number has no way out where text has one — appending the id carries uniqueness for text, but would change a number's magnitude. Two rows drawing the same number failed the UPDATE and, the whole run being one transaction, took the entire anonymisation with them. Without the report naming it, an identifying column stays in the clear with nothing saying so
- Restoring a backup no longer raises `AttributeError` before running the command: `_monitoring_restore` read `self._execute` where `TODO` sets `self.execute`, and both entries leading there — the local backup and the remote one — were broken. A check refuses the next one: every `self.X` that `TODO` READS must be set by TODO or by one of its bases. Searching the name across `script/todo/` did not see the fault, another object of the package setting `_execute`; it has to be searched in the classes TODO INHERITS from
- The Selenium scripts run on a Python built without `tkinter` — any server with no graphical toolkit package. That module is only needed by the vault's file picker, so it is now optional: with no `tkinter` and no configured KDBX path, opening the vault logs an error and returns, instead of breaking the import of every browser-automation script
- Dark mode works again in a private window on a current Firefox. The « Run in Private Windows » permission is granted when the addon is installed, through the `allowPrivateBrowsing` field, rather than clicked through the `about:addons` interface: Firefox refuses navigation to `about:addons` from the content context, and the chrome context demands `-remote-allow-system-access`, which geckodriver rejects through capabilities, so both routes to that checkbox are closed. A geckodriver that ignores the field installs without the permission instead of killing the session
- The « - Default » label appears again at the version and environment menus: both reads asked for a capitalised key the version file never writes, and a missing key returns nothing without a word
- The cache's « nothing in store » message is inert as a shell script, every line being a comment. Fed to an installer built on `curl … | bash`, it used to become a cascade of « command not found » that hid the real cause. Such a download now also asks curl to fail on an HTTP error rather than execute the error page
- The wait for a VM to be ready now covers the guest-agent install too. That one is launched as a DETACHED unit so cloud-init returns in seconds, and it runs an `apt-get update`: `cloud-init status --wait` said « done » while the package lock was still held, the next step burnt through its retries, and the install then ran on an index never refreshed — « Unable to locate package », a message that blames the repository rather than the lock. An update that never succeeds now says so on the spot
- A desktop install no longer waits minutes on the apt lock: the apt-daily SERVICE is stopped and not only its timer, a timer being disabled without interrupting the apt-get it already started; and the retry comes back every two seconds rather than every ten, `DPkg::Lock::Timeout` not covering the list lock at all
- Fedora VMs boot again: the firmware loads and starts their loader, then freezes without writing a byte — no console, no DHCP lease, a machine "running" that does nothing. Fedora is booted in legacy BIOS, where the same image starts its kernel; `--bios` still wins when asked
- A VM receives a hostname it can accept — an underscore, which a libvirt domain name tolerates, made it keep its image's generic name — and a timezone its own distribution knows, a legacy alias having left it in UTC
- starship installs in a VM: its installer runs as root, bounded by a root timeout, so it never reaches the `sudo -v` that sudo-rs refuses; its shell hook no longer prints « command not found », nor fails a sourced rc, when starship is absent
- Each optional tool says whether it was installed, and a GNOME extension whose download failed is no longer reported as unavailable for this GNOME
- mise, pyenv and GNOME extensions are downloaded, then run: without pipefail, `curl | sh` could neither report a failed download nor reach its fallback
- The guest-agent unit no longer ends in failure after a successful install
- The cache answers 508 to a request that targets the cache itself, instead of calling itself until it runs out of descriptors
- The cache diagnosis no longer reports a stopped service as running
- The wait for `apt-get update` is bounded by a deadline rather than by a number of attempts. An attempt fails in under a second on a held lock, but takes minutes when the cache answers 504 on every index it does not hold: sixty attempts were then worth hours of silence where five minutes were promised, and the install went on to fail on unmet dependencies
- A Proxmox guest is pinned to the same apt mirror as the rest of the fleet, written over ssh before anything downloads. The store keys its indexes by HOST, so a VM left on the default repositories of its image found none of what the cache had been filled with — offline, every one of those indexes was missing
- The cache installer accepts a bridge and a subnet given by hand. It probed libvirt first and died on « network default not found », so the workaround its own header advertised — `EL_BRIDGE` and `EL_SUBNET` — could never be reached. A machine whose libvirt network is not started, or which carries its bridge otherwise, can now lay the cache down by naming it; and when the probe does run and fails, it names both ways out
- **Deployment › QEMU cache › Install or reinstall** no longer announces « installed and started » when the installer failed. It caught exceptions only: a non-zero exit — a missing libvirt network, a build that gave way — printed the success line right under the error itself, along with the path of an authority that does not exist
- A Proxmox guest receives its guide, its timezone, its apt mirror and the cache authority again. All four go by ssh and used to start as soon as an address was known, while cloud-init was still creating accounts and keys: they failed together, and the VM was born in UTC, guideless, without the authority and on its image's repositories. The deployment now waits for the machine to answer ssh — five minutes at most — and says so when it never does, rather than failing four times in a row
- The cache no longer serves a repository index newer than the signature that announces it. Offline, each object came out with its own date: an index refreshed on Saturday under a Friday `InRelease` made apt fail on « File has unexpected size » or « Hash Sum mismatch », and the install stopped on unmet dependencies — a message that blames the repository, never the cache. The comparison is made on the upstream `Last-Modified`, never on the storage date, which is renewed on every hit
- The refusal to copy the cache to another machine names the gesture that lifts it, and that gesture is not entry 1 — entry 1 installs the cache HERE, so following it reinstalled the host that already had one while the target stayed empty. Three situations were reported as a single « no cache installed »: an ssh link that never ran the probe, a target carrying no cache, and a target whose cache lacks its service account. Each has its own message now, and the missing-cache one lists the steps to run ON the target, the two ways past an installer that reads the « default » libvirt network included — start libvirt, or name the bridge, a stopped libvirt making it die on a network that exists. The steps also name the branch to put the target on, read from this host: the installer is a file of the repository, so a machine left on another branch answers « no such file », which looks nothing like a missing cache. A fourth case is checked before a single byte leaves: sudo asking for a password on the target, which no terminal can answer since the store itself occupies ssh's standard input — the message gives the ticket to obtain there first. The arrival is asked for the privilege ONCE, `tar` and `chown` under a single invocation. Where sudo there wants a password, the entry offers two ways out instead of failing: the one-off sudoers line that allows it, or a two-step mode — the store is sent into the target's own account, which needs no privilege at all, and a printed command extracts it from a terminal there, where a password can be typed. That mode needs twice the store on the target, checked before a byte leaves, a cache holding only already-compressed packages and git archives. The guide carries the same section
- The Proxmox VE deployment form checks the cache before cutting the network, as the libvirt one already did: what the store lacks, no cut VM will read, and the failure used to land an hour later, at the desktop step — a message that blames the repository, never the cache. F5 again means going ahead anyway. Both forms now share a single verdict instead of two copies of it, which would have drifted apart at the first adjustment
- The cache keeps its repository indexes when a mirror list rotates. An index published under the hash of its content — `by-hash/SHA256/…` — was stored under a key carrying the host, so the same bytes served by a second mirror were fetched again; offline they were simply missing, and the install failed on files the store already held, with a message that blames the repository. Such an object is now keyed by its path alone, its name BEING the checksum of its content
- The cache diagnosis no longer reports « no redirection rule is posted » when it simply could not read them. On a host whose sudo asks for a password, `sudo -n nft` returns nothing, and that silence was read as an absence of rules — sending the operator to reinstall a cache that was redirecting correctly. The reading now carries a third state, « cannot tell », marked with a dot rather than a cross, exactly as the upstream-cut reading already did
- A lifted cut gives the upstreams their chance back at once. The service remembers, for a short while, which upstreams just failed to connect, so that an offline install does not pay the connection delay hundreds of times; nothing told it the cut was over, and the first requests after the lift fell back on the store while the network was already back. The lift now touches a witness file inside the store, which that memory consults — there is no channel at all to the running service
- Before cutting, the form also warns about what no index can reveal: a package the deployment lays down OUTSIDE the watched thread — the guest agent, installed by a detached unit whose failure surfaces nowhere — and the git repositories declared by the manifests that have no mirror yet. A held suite index was enough to call the cache complete while not one byte of that package had ever crossed it; and a git negotiation is never stored, so a repository without a mirror simply cannot be cloned once the network is gone
- The mirror warning counts only the repositories of the Odoo version being deployed. It used to add up every manifest in the repository — the deprecated one included — and announced 170 missing mirrors where a real Odoo 18 deployment meets four: an alarm that fires for nothing is one that stops being read. Filling the mirrors still takes every version ahead, which is its purpose
- A host banned from decryption on a burst of transport errors gets another chance. Three failed handshakes in a row put it in an opaque tunnel, and a tunnel never consults the store: a distribution mirror condemned by a few corrupted records sent all its traffic back upstream, including the hundreds of objects already held for it, until the service was restarted. A TLS alert still bans for good — the client looked at our certificate and refused it — but a repeated cut is only a suspicion, and it reopens after ten minutes
- **Deployment › QEMU cache › Git mirrors** fills the base of the active Odoo version, or its extra modules, on their own — beside the full fill of every manifest, which takes hours. Each list shows how many repositories it declares and how many still lack a mirror. What a deployment clones is now read with the manifest merge's own rule and lists, so the extra modules, installed only on request, and the mobile project no longer count: the offline warning announced four missing mirrors that a default Odoo 18 install never clones
- pip's PEP 658 metadata — the `.whl.metadata` file fetched before each wheel — is served from disk. The name ends in `.metadata`, which no rule knew, so each file was taken again on every install: 178 of them on a full ERPLibre install. Copies stored before this change are not reached again; the next online install refills them
- The timezone a deployed VM inherits from its host is translated to its canonical name. Ubuntu 24.04 cloud images no longer carry the legacy aliases — `Canada/*`, `US/*`, `Asia/Calcutta` — moved to a `tzdata-legacy` package they do not install: cloud-init refused the zone, the VM stayed on UTC, and the only sign was cloud-init reporting an error, the offset showing up in timestamps long afterwards. The alias table is the host's own `tzdata.zi`, not a copy kept in the code
- `make` looks for bash instead of assuming `/bin/bash`. That path does not exist on NixOS, where the shell lives in the store, and make stopped before running any recipe — including the one that installs what creates that path. Elsewhere the resolved shell is the same one as before
- The locale and the keyboard a deployed VM is given now apply on Debian, where both silently failed. A locale is generated from `/etc/locale.gen` and nowhere else, so `update-locale` refused one that was not there and the VM stayed on C.UTF-8; the keyboard module ends on a `console-setup` the genericcloud image does not carry, so `/etc/default/keyboard` — the file localed and X read — is written directly instead. Every Debian deployment used to print `cloud-init: status: error`, and a word that always shows warns of nothing
- A guest with no per-file trust anchor is taken out of the download cache instead of being intercepted without one. Interception is transparent and covers the whole bridge, so a VM given no authority still fails every HTTPS download on « self-signed certificate in certificate chain » — and on a declarative system placing the authority comes too late, the first rebuild being the first download. On a Proxmox host it is the HOST that is exempted: a nested guest leaves masqueraded behind it and the bridge never sees its own address. Measured from inside the guest: code 000 and SSL verification 19, then 200 and 0. Without it the package manager fell back to building 564 derivations, whose sources failed for the same reason
- NixOS learns the download cache's authority WITHOUT a rebuild, so it is no longer taken out of the cache — which used to close offline deployment to it, the store being the only source there and an exempted VM having none. It has no per-file trust anchor and /etc is generated read-only, while a declaration would come too late, the first rebuild being the first download. The authority is therefore POINTED AT, consumer by consumer, through the environment — and the environment is lost at three boundaries the four imperative families never meet. nix-daemon is socket-activated and sees no session: a drop-in under /run/systemd/system, a tmpfs writable where /etc is not, reaches it. sudo wipes it, and root's nix talks straight to the local store rather than the daemon, downloading on its own: `Defaults env_keep` carries the variables across, visudo being reached through the system profile since cloud-init's PATH there holds no sudo. And the ssh session opens one second before cloud-init writes the bundle, so the exports live inside the wait for it rather than at the head of the command. The bundle concatenates the system authorities with the cache's, giving the cache's alone would stop trusting everything else. Checked on a fresh VM with upstream CUT: nix-shell realises from the store; and with the cache intercepting, a complete install ends with no certificate refusal
- Odoo answers from outside a NixOS VM. It listened on 0.0.0.0:8069 and replied locally, but NixOS enables a firewall by default where none of the four other cloud images does: the host received nothing — not a refusal, silence until the timeout — and the monitor declared Odoo absent on a machine where it was running. Measured from the host: 000 after 12 s, then 303 in 9 ms
- ERPLibre runs as a service on NixOS. The install ended by writing a unit into `/etc/systemd/system`, generated from the store and mounted read-only: it returned 1 at its last step, after the clone, the venv and an Odoo start had all succeeded. The unit is now declared by the module; its interpreter comes from the store, `/bin` being an envfs FUSE mount that systemd does not see when it resolves the executable; and its PATH carries bash, whose absence stopped `run.sh` before Odoo
- What a declarative system must declare, and the four others receive free from their cloud image: xmlsec1, without which Odoo refuses to install auth_saml, a module of the addons path; parallel and shfmt, called by bare name; growpart, absent from the whole system while the disk grow is written « … || true » and returned 0 without growing anything; and the guest agent, which came from the image rather than the repository, its unit PATH lacking findmnt so that guest-exec died with 127 on its first line
- The connection guide is displayed on NixOS. Deployment writes `/etc/motd` everywhere and relies on pam_motd to show it — true of the four cloud images, false here, where sshd reports « printmotd no » and the PAM stack holds no pam_motd: the guide was written, complete, and nobody read it. It also gains a NixOS block naming the trap it exists for — `/etc/nixos/erplibre.nix` is rewritten by `make install_os`, and declarations added there vanish without a word
- « make db_drop_all » no longer announces databases as dropped that were not. It built a parallel command, discarded its exit status and printed the list; the case is reachable as soon as parallel is missing from the PATH, and the operator moves on believing their databases are gone
- A download cache mirror refused for lack of space names its threshold and its measurement. It echoed a field every ordinary caller leaves at zero — « less than 0 B free on disk » announces no threshold and does not say what was measured
- A downloaded image is checked against the sum its publisher ships, for every distribution that publishes one and WITHOUT asking. The check existed behind a flag and for Ubuntu only, so the other images arrived with nothing looking at them. Six now enter, read off the repositories rather than guessed: Debian publishes sha512 where everything else is sha256, the RHEL families name the file « CHECKSUM », Rocky writes the BSD form, and Arch and openSUSE ship a sum per image. An unreachable sums file no longer stops a deployment — that is an availability failure — while a mismatch still stops everything and removes the image
- The locale a deployed VM is given applies on NixOS. cloud-init applies it through locale-gen and update-locale, absent there, and the VM kept the distribution's default — « fr_CA.UTF-8 » asked for, « en_US.UTF-8 » obtained. Both it and the timezone are declared by the module now, and neither is imposed on a NixOS one already had
- The connection guide fits an 80-column terminal even on a VM carrying its tools and a desktop, where it rendered 103 columns wide: the frame overflowed, the terminal wrapped wherever it liked, and the two-column alignment — the only thing making the guide readable at a glance — was lost. A gloss now wraps under its column, and moves below its command when that command leaves no room. The layout carries the rule, not the length of the texts, which would have held only until the next tool
- A VM deployed offline gets its cache variables before its installation starts. « cloud-init status --wait » returns as soon as cloud-init declares itself in error — an accessory module suffices — while its final stage is still writing the authority, `/etc/environment` and the sudoers file; a session opened in that second lived without them, and an install run by sudo then rejected the cache certificate. The deployment now waits for the cloud-final unit, and only its « activating » state, that unit being a oneshot that stays active once finished
- Repository metadata an RPM distribution names after the hash of its content is served from disk like a package, and a range request on a file the cache does not hold fetches the whole file in the background, once per key. Such an index of tens of megabytes was taken whole on every install — about 110 MB per VM on a RHEL family system — and dnf, which fetches its zchunk metadata by ranges, got a « 504 » with upstream cut, no range being stored
- A VM deployed offline no longer waits for a time synchronisation that cannot come. An image that enables `systemd-time-wait-sync` holds `time-sync.target` until the first NTP answer, and cloud-init's final stage is ordered after it: with no reachable time server, that stage never ran, nor the ssh host keys it generates, and the VM reached its login prompt without ever answering ssh
- The download cache no longer re-fetches a package it already holds because a mirror files it under another path. A mirror prefixes the path as it pleases — « /rocky/10.2/… », « /mirror/rocky-linux/10.2/… », « /pub/archive/fedora/… » — and the whole path gave two keys for the same bytes: over a log of 7099 delivered names, 1124 lived under several paths and 3.18 GiB went back upstream for nothing. Only the last six segments count now, empty ones falling with them. Six is the smallest collision-free bound: a Debian path carries exactly six, so five would serve Ubuntu's package for Debian's, which bears the same name for other bytes. Pacman packages stop at four, their paths being shorter than the common bound, which drops the mirror's prefix and keeps the repository name. A store filled before this change is brought over by `--recle`
- A kept image that has gone stale is fetched once more instead of ending the deployment. A distribution's « latest » directory moves with each point release and the published sum stops describing the image on disk, with no byte corrupted: the check deleted it and exited, losing a whole campaign — three VMs — to a staleness one download repairs. A second mismatch is on freshly downloaded bytes, stops everything and deletes the image; called with no mirror list, and for unreachable sums, nothing changes
- `long_test/qemu_cache.py` no longer fails a campaign where the cache served everything. A URL counts as « already seen » only if the first VM obtained its bytes: one package lives under two paths depending on the mirror, and the first VM can get a « 504 » on one — upstream judged mute — then be served from disk by the other, so nothing was stored under the first path and the second VM's honest download was counted a fault. A missing status counts as delivered, older logs not always writing it, and the new-files line names both of its causes instead of blaming Arch whatever the system measured
- An interrupted image download resumes on the same mirror, three attempts, by a `Range` asking for the rest, instead of throwing away what it received: a VM image weighs half a gigabyte, and a truncated `.part` used to send the reader back to a hand-typed `curl -C -`. A server ignoring the Range returns the whole file, and the transfer restarts from zero rather than doubling the bytes already there
- The cache's certificate variables name a bundle only when the file exists. A recent Fedora lacks `/etc/pki/tls/certs/ca-bundle.crt`, and pointing pip at a missing path made it refuse EVERY download, including what has nothing to do with the cache. None found writes no variable, and pip keeps its own certificate set
- `make version` names both Pythons, Odoo's and the tooling's. A bare label suggested the repository had one, and the figure shown was not that of the venv the reader works in
- `make` no longer launches a `.venv.erplibre` built on another machine, such as a checkout mounted over the network, which died on « No module named 'encodings' ». `install.sh` reads the interpreter's version by running code: `python -V` answers before the standard library loads, so it vouched for an interpreter that could not start. Such a venv is now reported as built elsewhere, with the command that rebuilds it
- Dependabot no longer opens pull requests against the frozen requirements of Odoo 12 to 17: its security updates scan `requirement/` as its own directory, which the exclusions did not cover
- `poetry_update.py` stops on a missing `pyproject.toml` with the command that creates it, `make switch_odoo_XX` for the active version, and offers to run it then restart when launched from a terminal
- `poetry_update.py` runs Poetry in the Odoo venv even from a shell under `.venv.erplibre`, whose Python made it fail on « InvalidCurrentPythonVersionError »
- `poetry_update.py` skips requirements and manifests under a `doc`, `docs`, `example` or `examples` directory: an example file declaring a loose `>=` no longer moves a dependency for the whole environment

## Removed

- The `sshconf` dependency, declared and installed everywhere and imported nowhere

## Security

- An API key and a bearer token are redacted too before a command is displayed, logged or reprinted: `OPENAI_API_KEY=` went out in the clear, and a header token escaped by construction, carrying neither an option name nor a variable name
- Following a redirect, the cache no longer forwards the client's credentials (Authorization, Cookie, Proxy-Authorization) to another host
- Odoo 18 installs `idna` 3.20 instead of the 3.6 its own requirements pin, which is affected by CVE-2024-3651
- Odoo 18 installs `requests` 2.32.4 instead of the 2.31.0 its own requirements pin, which is affected by CVE-2024-35195 and CVE-2024-47081
- The git mirror of the QEMU cache clones only over `http` and `https`: a client could name an `ssh://` or `git://` repository in its request and make the cache connect, with its service account keys, to a host of its choosing. Repositories fetched over HTTPS are mirrored as before; the binary reports 0.2.17


## [1.8.0] - 2026-09-04

**Migration notes**

Recreating the virtual environment, the Python interpreter and the package
installer being chosen now. Use the installation guide from tool `make`.
Ubuntu 20.04 and 22.04 are no longer supported.

## Added

- Deploy ERPLibre VMs with QEMU/KVM from cloud images: Ubuntu, Debian, Fedora, AlmaLinux, Rocky, openSUSE, Arch, Linux Mint, and Debian on s390x. Hardware, branch and Odoo version are set per machine
- Proxmox VE as a deployment target, its installation including the reboot it needs
- A QEMU menu: network status and repair, 3D acceleration, a diagnostic report, file recovery from a VM that no longer boots, virt-viewer and a remote desktop tunnel
- An install dashboard and Textual forms: deploy, follow, update, restart or delete a VM without leaving the screen
- A mobile development VM: PyCharm, Android Studio, an Android emulator and an adb tunnel
- A VPN tool, five free technologies from the menu, the secrets in a KeePassXC vault and a diagnosis that names the failing stage
- Automated Odoo migration: the tool drives the whole run, goes back to a step, and repairs what a version bump leaves behind
- Migration review: a verdict per step, smoke tests on every public URL, and a filestore check
- A read-only analysis toolkit for an Odoo database, a backup zip included, with PostgreSQL index advice
- Anonymising a production copy without AI, and duplicating a database neutralised for good
- Development assistants installed inside a VM, and a Git and Shell menu that installs what a checkout needs
- A writing convention for what stays in git, held by a `pre-commit` and a `commit-msg` hook
- `long_test/` — tests that create real machines, nested QEMU and Proxmox included, kept out of the unit runner
- NTFY, Forgejo, a local git server, e-mail from the CLI, and SSH configuration with recursive ProxyJump
- The Python interpreter and the package installer are chosen, through EL_PYTHON_PROVIDER and EL_PIP_PROVIDER
- The OCA generative AI policy, Claude Code agents and commands, and the context an assistant is given, shown from the menu
- Unit tests with a bilingual test plan, navigation telemetry for TODO, and Odoo 18 reading STL files

## Changed

- todo.py split into nine files, one per subject, with a shared base per form
- Every menu entry carries an icon, the menus are grouped into sections, and a countdown prompt gives 15 seconds to decide
- Branch, profile, type and timezone are chosen per VM rather than globally
- Installation covers Fedora, Debian, Ubuntu, Arch and openSUSE; repository sync and Poetry run in parallel, quiet unless EL_VERBOSE asks
- Node.js 22 for Capacitor 8, flanker for Odoo 18, CybroOdoo extras opt-in, and a Poetry dependency declinable per architecture
- A VM boots faster and picks the fastest reachable mirror, Canadian pacman mirrors coming first on Arch
- Staging names the files, never `git add -A`
- Enter targets the highest supported Odoo version, and a VM name drops the `latest` segment

## Fixed

- The libvirt network no longer counts as its own collision, no longer leaves a host without network at the next boot, and its state is read in English whatever the locale
- QEMU deployment: sudo says why it needs a password, the `libvirt` group replaces it where it suffices, no host reboots unasked, and an orphan disk no longer blocks a creation
- Migration: the database drop, the account.root view Odoo 17 leaves behind, the pricelists a repair invented, and the assumptions the 13-to-18 run rested on
- Anonymisation respects what a value means, and no longer breaks past the 131 072-byte limit of a single argument
- Installation on Debian 13, Fedora, Ubuntu 26.04 and s390x: apt locks, missing compilers and headers, too little memory, and what a recent SWIG or PROJ needs
- Secrets: the KeePassXC vault opens on a server without tkinter, the forgejo installer stops echoing the password it set, and db_restore validates the master one
- A question is seen before it is answered, and one faulty repository no longer takes a whole batch down
- Three screens that fell over, a shrink that would have filled the disk, and a monitor that binned a VM before being sure
- The unit runner globs the whole directory, where it ran 1131 tests of 3703
- Proxmox no longer aims at the host instead of the VM

## Removed

- Ubuntu 20.04 and 22.04 support, on every architecture
- The residue check that called a language broken when its `active` is NULL

## Security

- Passwords and tokens are redacted before a command is displayed, logged or reprinted
- The Odoo master password and the KeePass one leave the command line, an environment variable carrying them instead


## [1.7.0] - 2026-03-11

**Migration notes**

Recreating the virtual environment, use installation guide from tool `make`.

## Added

- Odoo 12.0 to 18.0 in a single workspace, switched without reinstalling: the manifests, the configuration and the addons paths follow the version named in `.odoo-version`
- ERPLibre's Python separated from Odoo's — `.venv.erplibre` carries the repository's own tools, `.venv.odoo<version>` the server — so a tool of the repository no longer depends on the interpreter a given Odoo version imposes
- Auto-installation driven from TODO: the menu lays down the environment it needs, Poetry, the Google Repo manifests and the addons included, rather than printing a command to retype
- Migration of an Odoo database and its modules from TODO, `--neutralize` included, with the repair of the mail module that a move from PostgreSQL 17 to 18 leaves behind
- A hardening script for the installation
- The ERPLibre Home mobile application: TODO compiles it, deploys it, renames the software and changes its menu image
- The RobotLibre code generator, with the queue_job channels its configuration needs
- ERPLibre DevOps, and the automation procedure it describes
- The Selenium grid from `selenium_lib.py`: a KeePass vault opened for the run, file downloads, dark mode, video recording and a scenario library
- A performance script measuring the requests per second a website answers
- Deployment: Cloudflare DNS, nginx with a non-interactive certbot, Apache templates matching the nginx ones, and a systemd unit whose working directory is configurable
- The s390x mainframe architecture
- Addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor, and the design-themes repository
- Database backup and erase commands, and a clearer restore naming
- A security check of the Python environment, from the menu
- TODO shows the documentation, downloads a database and helps with code formatting
- Killing an Odoo process by the port it holds, from the menu
- CLAUDE.md and the agent information document, so an assistant reads the repository's conventions instead of guessing them
- A FAQ entry on wkhtmltopdf for recent distributions

## Changed

- Odoo 18.0 becomes the default version of a checkout
- Docker moves to PostgreSQL 18, with the matching client
- The documentation is bilingual, generated by mmg from the `.base.md` sources: a `.md` or `.fr.md` edited directly is lost at the next generation
- The TODO menus are grouped into sections, and the English text serves as the i18n key rather than a code of its own
- The formatting script looks for the changed files in every repository, hidden addons included, and skips a repository that is not installed
- Odoo runs on a custom database, and the menu configures queue_job as well as the SSH forwarding a remote instance needs
- Killing a process by port asks before acting, through an interactive menu
- Neutralising a database goes through Odoo's own `--neutralize`
- LinuxMint 22.3, Ubuntu 25.10, and macOS without Python 3.7
- Odoo 18 dependencies: tldextract, PyYAML, pdfminer.six, and cryptography at its latest version
- A make target runs the unit tests
- The Makefile is split: its commands live in `conf/`, and `Common.Makefile` extends it for a project of one's own

## Fixed

- The documentation accents, and the markdown generation running in parallel
- `git_tool` returns nothing instead of raising where `.git` is absent
- `poetry iscompatible` no longer crashes on a version carrying a letter, an alpha or a release candidate
- pymssql compiles again, and the Odoo 18 requirements leave pyssql out of a production install
- wkhtmltopdf is no longer offered where it does not exist: no package is published for s390x on Ubuntu 25.10
- Selenium: the snap Firefox path, a 60-second timeout when reaching for an element, execution in a private window, and a login that waits for Odoo 18
- The formatting script ignores the files and directories it must not touch
- `db_drop_all` runs its shell command, and the backup processing keeps the permissions of what it writes
- TODO: the first import, the regeneration of `.repo/local_manifests`, the database open dialog, and a missing Odoo version reported instead of a crash
- The code generator: creating a project, extracting a class carrying a selection, and reading a model through the Python 3.11 `ast` module rather than astor
- Docker: the duplicated Odoo 18 build target, and the compose file pinned to an image that works


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


[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.8.0...HEAD

[1.8.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.7.0...v1.8.0

[1.7.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.6.0...v1.7.0

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