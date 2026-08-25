
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

**Migration notes**

Recreating the virtual environment, use installation guide from tool `make`.

## Added

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

- todo.py split into nine files, one per subject, with a shared base per form. It carried 9 500 lines more than a file should and every subject went through it; the deployment forms repeated the same field-and-validation machinery, so a fix in one never reached the others. No behaviour changes
- Branch, profile and type are chosen per VM. They were global, which meant switching everything to deploy a single machine differently
- One shared base describes the guest system, where each form used to describe it again

## Fixed

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