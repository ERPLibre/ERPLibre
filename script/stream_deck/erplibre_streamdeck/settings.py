# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The one reader and writer of settings.json.

Each writer reloads the file right before saving and changes only its
own keys, so a11y and the translator keep each other's values. The
write is not atomic."""

import json
import os

from erplibre_streamdeck import paths


def load():
    """settings.json as a dict; {} when missing or not JSON."""
    try:
        with open(paths.SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(data):
    os.makedirs(paths.CONFIG_DIR, exist_ok=True)
    with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
