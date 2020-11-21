# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Developer, test, migration and user documentation

### Changed
- Travis CI

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

[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.1...v1.0.0
[0.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ERPLibre/ERPLibre/releases/tag/v0.1.0
