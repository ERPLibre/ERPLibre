<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# ERPLibre - Infrastructure with pyinfra

ERPLibre infrastructure management with [pyinfra](https://pyinfra.com/),
a pure Python infrastructure automation tool.

## Prerequisites

<!-- [fr] -->
# ERPLibre - Infrastructure avec pyinfra

Gestion de l'infrastructure ERPLibre avec [pyinfra](https://pyinfra.com/),
un outil d'automatisation d'infrastructure en Python pur.

## Prérequis

<!-- [common] -->

```bash
pip install pyinfra
```

<!-- [en] -->
## Structure

```
pyinfra/
├── deploy.py              # Main entry point (full installation)
├── inventory.py           # Host definitions (local, remote)
├── README.md              # This file
├── group_data/
│   └── all.py             # Shared variables (flags, ports)
└── deploys/
    ├── __init__.py
    ├── env.py             # Dynamic project variable reading (PWD)
    ├── system.py          # PostgreSQL, build tools, pyenv deps, selenium
    ├── nodejs.py          # Node.js 20.x, rtlcss, less, prettier
    ├── wkhtmltopdf.py     # wkhtmltopdf (auto distro detection)
    └── python_env.py      # pyenv, venvs ERPLibre + Odoo, Poetry, Google Repo
```

### Module descriptions

| Module | Description |
|--------|-------------|
| `deploy.py` | Orchestrates full installation in order: system, Node.js, wkhtmltopdf, Python |
| `deploys/env.py` | Reads version files (`.odoo-version`, `.python-odoo-version`, etc.) from PWD. No hardcoded paths. |
| `deploys/system.py` | Apt packages: PostgreSQL/PostGIS, build tools, dev libs, pyenv and Selenium dependencies |
| `deploys/nodejs.py` | NodeSource repository, Node.js 20.x, global npm (rtlcss, less), local npm (prettier) |
| `deploys/wkhtmltopdf.py` | Detects Ubuntu/Debian/Mint and downloads the correct wkhtmltopdf `.deb` |
| `deploys/python_env.py` | Installs pyenv, required Python versions, creates venvs, installs Poetry and Odoo dependencies |
| `inventory.py` | Defines target hosts (`@local` by default) |
| `group_data/all.py` | Variables: `install_wkhtmltopdf`, `install_nginx`, Odoo ports |

<!-- [fr] -->
## Structure

```
pyinfra/
├── deploy.py              # Point d'entrée principal (installation complète)
├── inventory.py           # Définition des hôtes (local, distants)
├── README.md              # Ce fichier
├── group_data/
│   └── all.py             # Variables partagées (flags, ports)
└── deploys/
    ├── __init__.py
    ├── env.py             # Lecture dynamique des variables du projet (PWD)
    ├── system.py          # PostgreSQL, build tools, pyenv deps, selenium
    ├── nodejs.py          # Node.js 20.x, rtlcss, less, prettier
    ├── wkhtmltopdf.py     # wkhtmltopdf (détection auto distro)
    └── python_env.py      # pyenv, venvs ERPLibre + Odoo, Poetry, Google Repo
```

### Description des modules

| Module | Description |
|--------|-------------|
| `deploy.py` | Orchestre l'installation complète dans l'ordre : système, Node.js, wkhtmltopdf, Python |
| `deploys/env.py` | Lit les fichiers de version (`.odoo-version`, `.python-odoo-version`, etc.) depuis le PWD. Aucun chemin hardcodé. |
| `deploys/system.py` | Paquets apt : PostgreSQL/PostGIS, build tools, libs de dev, dépendances pyenv et Selenium |
| `deploys/nodejs.py` | Dépôt NodeSource, Node.js 20.x, npm global (rtlcss, less), npm local (prettier) |
| `deploys/wkhtmltopdf.py` | Détecte Ubuntu/Debian/Mint et télécharge le bon `.deb` wkhtmltopdf |
| `deploys/python_env.py` | Installe pyenv, les versions Python requises, crée les venvs, installe Poetry et les dépendances Odoo |
| `inventory.py` | Définit les hôtes cibles (`@local` par défaut) |
| `group_data/all.py` | Variables : `install_wkhtmltopdf`, `install_nginx`, ports Odoo |

<!-- [en] -->
## Bash script mapping

| Existing bash script | pyinfra module |
|---|---|
| `script/install/install_debian_dependency.sh` (PostgreSQL, build tools) | `deploys/system.py` |
| `script/install/install_debian_dependency.sh` (Node.js, npm) | `deploys/nodejs.py` |
| `script/install/install_debian_dependency.sh` (wkhtmltopdf) | `deploys/wkhtmltopdf.py` |
| `script/install/install_locally.sh` | `deploys/python_env.py` |
| `script/install/install_venv.sh` | `deploys/python_env.py` (`_create_venv_*`) |
| `script/install/install_git_repo.sh` | `deploys/python_env.py` (`_install_git_repo`) |
| `env_var.sh` | `deploys/env.py` |
| `make install_os` + `make install_dev` | `deploy.py` |

## Usage

All commands are run from the **ERPLibre project root**.

### Full installation (local)

<!-- [fr] -->
## Correspondance avec les scripts bash

| Script bash existant | Module pyinfra |
|---|---|
| `script/install/install_debian_dependency.sh` (PostgreSQL, build tools) | `deploys/system.py` |
| `script/install/install_debian_dependency.sh` (Node.js, npm) | `deploys/nodejs.py` |
| `script/install/install_debian_dependency.sh` (wkhtmltopdf) | `deploys/wkhtmltopdf.py` |
| `script/install/install_locally.sh` | `deploys/python_env.py` |
| `script/install/install_venv.sh` | `deploys/python_env.py` (`_create_venv_*`) |
| `script/install/install_git_repo.sh` | `deploys/python_env.py` (`_install_git_repo`) |
| `env_var.sh` | `deploys/env.py` |
| `make install_os` + `make install_dev` | `deploy.py` |

## Commandes d'utilisation

Toutes les commandes s'exécutent depuis la **racine du projet ERPLibre**.

### Installation complète (locale)

<!-- [common] -->

```bash
# Dry-run
pyinfra @local pyinfra/deploy.py --dry

# Full installation / Installation complète
pyinfra @local pyinfra/deploy.py
```

<!-- [en] -->
### Partial installation

<!-- [fr] -->
### Installation partielle

<!-- [common] -->

```bash
# System dependencies only / Dépendances système seulement
pyinfra @local pyinfra/deploys/system.py

# Node.js and npm packages only / Node.js et npm seulement
pyinfra @local pyinfra/deploys/nodejs.py

# wkhtmltopdf only / wkhtmltopdf seulement
pyinfra @local pyinfra/deploys/wkhtmltopdf.py

# Python environments only / Environnements Python seulement
pyinfra @local pyinfra/deploys/python_env.py
```

<!-- [en] -->
### Remote server

<!-- [fr] -->
### Serveur distant

<!-- [common] -->

```bash
# Dry-run on remote server / Dry-run sur serveur distant
pyinfra user@server.com pyinfra/deploy.py --dry

# Full install on remote / Installation complète sur serveur distant
pyinfra user@server.com pyinfra/deploy.py

# System deps on remote / Dépendances système sur serveur distant
pyinfra user@server.com pyinfra/deploys/system.py

# Multiple servers / Plusieurs serveurs
pyinfra user@srv1.com,user@srv2.com pyinfra/deploy.py
```

<!-- [en] -->
### With inventory

<!-- [fr] -->
### Avec inventaire

<!-- [common] -->

```bash
# Use inventory / Utiliser l'inventaire
pyinfra pyinfra/inventory.py pyinfra/deploy.py

# Verbose mode / Mode verbose
pyinfra @local pyinfra/deploy.py -v
```

<!-- [en] -->
### Via the TODO CLI

The **Infra** menu is available in the interactive CLI:

<!-- [fr] -->
### Via le CLI TODO

Le menu **Infra** est disponible dans le CLI interactif :

<!-- [common] -->

```bash
./.venv.erplibre/bin/python ./script/todo/todo.py
# → [1] Execute
#   → [12] Infra
#     → [1] Dry-run
#     → [2] Full installation / Installation complète
#     → [3] System dependencies only / Dépendances système seulement
#     → [4] Python environments only / Environnements Python seulement
#     → [5] Remote server / Serveur distant
```

<!-- [en] -->
## Environment variables

Variables are read dynamically from project files:

| File | Variable | Example |
|------|----------|---------|
| `.odoo-version` | Odoo version | `18.0` |
| `.python-odoo-version` | Python version for Odoo | `3.12.10` |
| `.poetry-version` | Poetry version | `2.1.3` |
| `.erplibre-version` | ERPLibre version identifier | `odoo18.0_python3.12.10` |
| `conf/python-erplibre-version` | ERPLibre Python version | `3.9.21` |
| `conf/python-erplibre-venv` | ERPLibre venv name | `.venv.erplibre` |

The `deploys/env.py` module uses `os.getcwd()` to find the project root
(searches for `.odoo-version` going up the directory tree).

## Customization

### Modify shared variables

Edit `group_data/all.py`:

<!-- [fr] -->
## Variables d'environnement

Les variables sont lues dynamiquement depuis les fichiers du projet :

| Fichier | Variable | Exemple |
|---------|----------|---------|
| `.odoo-version` | Version Odoo | `18.0` |
| `.python-odoo-version` | Version Python pour Odoo | `3.12.10` |
| `.poetry-version` | Version Poetry | `2.1.3` |
| `.erplibre-version` | Identifiant version ERPLibre | `odoo18.0_python3.12.10` |
| `conf/python-erplibre-version` | Version Python ERPLibre | `3.9.21` |
| `conf/python-erplibre-venv` | Nom du venv ERPLibre | `.venv.erplibre` |

Le module `deploys/env.py` utilise `os.getcwd()` pour trouver la racine
du projet (cherche `.odoo-version` en remontant l'arborescence).

## Personnalisation

### Modifier les variables partagées

Éditer `group_data/all.py` :

<!-- [common] -->

```python
install_wkhtmltopdf = True   # Set False to disable / Mettre False pour désactiver
install_nginx = False         # Set True to install / Mettre True pour installer
odoo_port = 8069
longpolling_port = 8072
```

<!-- [en] -->
### Add remote servers

Edit `inventory.py`:

<!-- [fr] -->
### Ajouter des serveurs distants

Éditer `inventory.py` :

<!-- [common] -->

```python
local = ["@local"]

production = [
    ("prod1.erplibre.ca", {"odoo_version": "18.0"}),
    ("prod2.erplibre.ca", {"odoo_version": "17.0"}),
]

staging = [
    ("staging.erplibre.ca", {
        "ssh_user": "erplibre",
        "odoo_version": "18.0",
    }),
]
```

<!-- [en] -->
## Advantages over bash scripts

| Bash | pyinfra |
|------|---------|
| Not idempotent | Idempotent (checks state before acting) |
| `if/else` for OS detection | `host.get_fact(LinuxDistribution)` |
| No dry-run | Native `--dry` |
| Local only | Local + remote SSH |
| Silent errors | Per-operation error reporting |
| Separate scripts to orchestrate | Single Python entry point |

<!-- [fr] -->
## Avantages par rapport aux scripts bash

| Bash | pyinfra |
|------|---------|
| Non-idempotent | Idempotent (vérifie l'état avant d'agir) |
| `if/else` pour détecter l'OS | `host.get_fact(LinuxDistribution)` |
| Pas de dry-run | `--dry` natif |
| Local uniquement | Local + SSH distant |
| Erreurs silencieuses | Rapport d'erreur par opération |
| Scripts séparés à orchestrer | Un seul point d'entrée Python |
