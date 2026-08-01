#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Préférences persistantes du CLI TODO.

Réglages qui survivent d'une session à l'autre et qui appartiennent à
l'UTILISATEUR, pas au dépôt : ils vivent donc dans ~/.erplibre (comme la
télémétrie de navigation) et non dans un fichier versionné.

- get(key, default) / set(key, value) : accès unitaire.
- reset() : efface tout et revient aux défauts.

Tout est best-effort : une préférence illisible ou un disque plein ne doivent
JAMAIS empêcher le CLI de démarrer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Clés connues et leur valeur par défaut. Une clé absente de ce dictionnaire
# reste lisible/écrivable, mais n'apparaît pas dans l'écran de configuration.
DEFAULTS = {
    # Interface du déploiement QEMU : "ask" pose la question à chaque fois,
    # "tui" ouvre le formulaire directement, "cli" garde les invites en ligne.
    "qemu_deploy_ui": "ask",
    # Affichage pendant le déploiement : "cli" (sortie texte, facile à copier
    # depuis le terminal) ou "tui" (blocs repliables + copie OSC 52).
    "qemu_deploy_progress": "cli",
    # Interface de la migration Odoo : "ask" / "tui" / "cli".
    "migration_ui": "ask",
}


def _path() -> Path:
    base = Path(os.path.expanduser("~/.erplibre"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "todo_prefs.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass


def get(key: str, default=None):
    """Valeur d'une préférence : fichier, puis DEFAULTS, puis `default`."""
    if default is None:
        default = DEFAULTS.get(key)
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - API voulue : prefs.set(...)
    data = load()
    data[key] = value
    _save(data)


def reset() -> int:
    """Efface toutes les préférences. Renvoie le nombre de clés effacées."""
    count = len(load())
    _save({})
    return count
