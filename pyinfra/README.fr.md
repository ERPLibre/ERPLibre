
# ERPLibre - Infrastructure avec pyinfra

Gestion de l'infrastructure ERPLibre avec [pyinfra](https://pyinfra.com/),
un outil d'automatisation d'infrastructure en Python pur.

## Prérequis


```bash
pip install pyinfra
```

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


```bash
# Dry-run
pyinfra @local pyinfra/deploy.py --dry

# Full installation / Installation complète
pyinfra @local pyinfra/deploy.py
```

### Installation partielle


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

### Serveur distant


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

### Avec inventaire


```bash
# Use inventory / Utiliser l'inventaire
pyinfra pyinfra/inventory.py pyinfra/deploy.py

# Verbose mode / Mode verbose
pyinfra @local pyinfra/deploy.py -v
```

### Via le CLI TODO

Le menu **Infra** est disponible dans le CLI interactif :


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


```python
install_wkhtmltopdf = True   # Set False to disable / Mettre False pour désactiver
install_nginx = False         # Set True to install / Mettre True pour installer
odoo_port = 8069
longpolling_port = 8072
```

### Ajouter des serveurs distants

Éditer `inventory.py` :


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

## Avantages par rapport aux scripts bash

| Bash | pyinfra |
|------|---------|
| Non-idempotent | Idempotent (vérifie l'état avant d'agir) |
| `if/else` pour détecter l'OS | `host.get_fact(LinuxDistribution)` |
| Pas de dry-run | `--dry` natif |
| Local uniquement | Local + SSH distant |
| Erreurs silencieuses | Rapport d'erreur par opération |
| Scripts séparés à orchestrer | Un seul point d'entrée Python |