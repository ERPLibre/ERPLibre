# Architecture des environnements virtuels

```
.venv.erplibre/              # Venv ERPLibre (outils : repo, poetry, coverage)
.venv.odoo18/                # Venv Odoo 18 (Python 3.12)
.venv.odoo17/                # Venv Odoo 17 (Python 3.10)
.venv.odoo16/                # Venv Odoo 16 (Python 3.10)
.venv.odoo14/                # Venv Odoo 14 (Python 3.8)
.venv.odoo12/                # Venv Odoo 12 (Python 3.7)
```

Géré via **pyenv** pour les multiples versions de Python.

## Système de dépendances

Chaque version Odoo a son propre ensemble dans `requirement/` :
- `pyproject.odooXX.0_pythonY.Z.toml` — Configuration Poetry
- `poetry.odooXX.0_pythonY.Z.lock` — Lock file Poetry
- `requirements.odooXX.0_pythonY.Z.txt` — Requirements pip (fallback)
- `ignore_requirements.odooXX.0.txt` — Paquets à ignorer

Mise à jour : `./script/poetry/poetry_update.py`
