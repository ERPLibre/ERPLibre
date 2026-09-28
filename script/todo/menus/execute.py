#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Execute : Update, qu'ouvre Execute › Code.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu

UPDATE = Menu(
    "prompt_execute_update",
    "Update",
    [
        FromConfig(
            "update_from_makefile", "execute_from_configuration", "instance"
        ),
        Entry("Upgrade Odoo - Migration Database", "_upgrade_odoo"),
        Entry("Upgrade Poetry - Dependency of Odoo", "upgrade_poetry"),
    ],
    intro="_update_intro",
    render="once",
)
