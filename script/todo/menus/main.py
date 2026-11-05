#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu principal et trois des menus qu'il ouvre : l'entrée [4],
Navigation telemetry, Configuration et Healthcheck. Install et Assistant,
qu'il ouvre aussi, sont déclarés avec leurs familles, dans `proxmox.py` et
`assistant.py`.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.
"""

from script.todo.ui.registry import Entry, FromMethod, Menu, Section

# Le menu principal, dessiné une fois après le logo et la langue qu'écrit
# `run` ; [0] quitte TODO (`quits`).
MAIN = Menu(
    "run",
    "TODO",
    [
        Entry("Execute", "prompt_execute"),
        Entry("Install", "prompt_install"),
        Entry("Assistant", "prompt_assistant"),
        Entry("Navigation telemetry", "prompt_telemetry"),
        Entry("Configuration", "prompt_configuration"),
        Entry("Healthcheck", "prompt_healthcheck"),
    ],
    intro="=> Enter your choice by number and press Enter!",
    back=None,
    render="once",
    quits=True,
)

TELEMETRY = Menu(
    "prompt_telemetry",
    "Navigation telemetry",
    [
        Entry("Navigation telemetry (TUI)", "_todo_telemetry_tui"),
        Entry("Navigation telemetry (WEB)", "_todo_telemetry_web"),
        Entry("Stop the web interface", "_todo_web_stop"),
        Entry("Desktop window", "_todo_desktop_window"),
    ],
    state="_web_state",
)

CONFIGURATION = Menu(
    "prompt_configuration",
    "Configuration",
    [
        Section("Interface"),
        Entry("Language / Langue", "_change_language", suffix="_lang_label"),
        Entry(
            "QEMU deployment interface",
            "_pref_edit",
            kwargs={"key": "qemu_deploy_ui"},
            suffix="_pref_label",
        ),
        Entry(
            "Display while deploying",
            "_pref_edit",
            kwargs={"key": "qemu_deploy_progress"},
            suffix="_pref_label",
        ),
        Entry(
            "Odoo migration interface",
            "_pref_edit",
            kwargs={"key": "migration_ui"},
            suffix="_pref_label",
        ),
        Entry("Fork - Open TODO in a new tab", "_fork_todo"),
        Section("Maintenance"),
        Entry("Reset all preferences", "_reset_preferences", danger=True),
    ],
    back=None,
)

# Les vérifications à sec du checkout. Chaque entrée de portée passe son
# axe à la portée suivante, et le suffixe dit celle en cours ; l'ouverture
# (`opens`) remet chaque axe à sa portée la plus étroite. Une vérification
# par élément de `_healthcheck_checks`.
HEALTHCHECK = Menu(
    "prompt_healthcheck",
    "Healthcheck",
    [
        Entry("Run every check", "_healthcheck_run"),
        Section("Scope"),
        Entry(
            "Files",
            "_healthcheck_scope",
            kwargs={"axe": "fichiers"},
            suffix="_healthcheck_scope_label",
        ),
        Entry(
            "Repositories",
            "_healthcheck_scope",
            kwargs={"axe": "depots"},
            suffix="_healthcheck_scope_label",
        ),
        Section("One check"),
        FromMethod("_healthcheck_checks", "_healthcheck_run", "check"),
    ],
    back=None,
    opens="_healthcheck_open",
)
