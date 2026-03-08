
# ERPLibre - Infrastructure with pyinfra

ERPLibre infrastructure management with [pyinfra](https://pyinfra.com/),
a pure Python infrastructure automation tool.

## Prerequisites


```bash
pip install pyinfra
```

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


```bash
# Dry-run
pyinfra @local pyinfra/deploy.py --dry

# Full installation / Installation complète
pyinfra @local pyinfra/deploy.py
```

### Partial installation


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

### Remote server


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

### With inventory


```bash
# Use inventory / Utiliser l'inventaire
pyinfra pyinfra/inventory.py pyinfra/deploy.py

# Verbose mode / Mode verbose
pyinfra @local pyinfra/deploy.py -v
```

### Via the TODO CLI

The **Infra** menu is available in the interactive CLI:


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


```python
install_wkhtmltopdf = True   # Set False to disable / Mettre False pour désactiver
install_nginx = False         # Set True to install / Mettre True pour installer
odoo_port = 8069
longpolling_port = 8072
```

### Add remote servers

Edit `inventory.py`:


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

## Advantages over bash scripts

| Bash | pyinfra |
|------|---------|
| Not idempotent | Idempotent (checks state before acting) |
| `if/else` for OS detection | `host.get_fact(LinuxDistribution)` |
| No dry-run | Native `--dry` |
| Local only | Local + remote SSH |
| Silent errors | Per-operation error reporting |
| Separate scripts to orchestrate | Single Python entry point |
