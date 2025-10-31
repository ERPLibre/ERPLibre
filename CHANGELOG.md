# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## Added

- Support Odoo migration database and module with TODO
- Support multi version odoo switch on same workspace
- Script for hardening the installation
- Support Odoo versions 12.0 to 18.0
- Separate ERPLibre python installation from Odoo python with .venv.erplibre and .venv.odoo18
- Implement auto-installation with TODO.py
- TODO show documentation, download database, help with code formatting

## Changed

- Docker support postgresql 18

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
