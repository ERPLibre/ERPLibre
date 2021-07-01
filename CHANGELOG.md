# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Adapt script to give an execution status
- Multilingual markdown
- Guide to use Cloudflare with DDNS
- Script to check git diff and ignore date
- Repo with ERPLibre image
- Improve git repo usage, filter repo by use case

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
- Support default.stage.xml to update prod with dev
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

[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.1.1...HEAD

[1.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.1

[1.1.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.0

[1.0.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.0...v1.0.1

[1.0.0]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.1...v1.0.0

[0.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.0...v0.1.1

[0.1.0]: https://github.com/ERPLibre/ERPLibre/releases/tag/v0.1.0
