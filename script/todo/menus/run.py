#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Run, qu'ouvre Execute : Run, Database et son menu
d'effacement, Analyse, Transform data et Doc.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu

RUN = Menu(
    "prompt_execute_instance",
    "Run",
    [
        Entry("Choose your database", "callback_execute_custom_database"),
        FromConfig("instance", "_run_instance", "instance"),
        Entry(
            "Mobile - Compile and run software",
            "callback_make_mobile_home",
            when="_mobile_exists",
        ),
    ],
    render="once",
)
