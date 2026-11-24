#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les questions oui/non de TODO : le défaut de chacune, lu dans le
code et épinglé dans CONFIRM_DEFAULTS.

Chaque appel `ui.confirm(` de `script/todo`, hors du port (`ui/`), donne
une clé (fichier, fonction, première clé `t("…")` de ses arguments, ou
`<dynamique>`) et la liste des défauts de ses appels, dans l'ordre du
fichier : un booléen littéral, `état` pour un nom (le défaut est l'état
qu'il porte), `typed` pour une confirmation tapée, sinon le texte de
l'expression. Les appels des enveloppes de WRAPPERS, qui posent leur
question par `ui.confirm`, entrent de même, leur défaut lu sur `default=`
au site appelant ; le `ui.confirm` d'une enveloppe n'a pas de ligne. Un
défaut qui change, une question qui naît ou part, change la table dans le
même commit.
"""

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo import auto_ask

REPO = Path(__file__).resolve().parent.parent
TODO = REPO / "script" / "todo"
PORT = TODO / "ui"

# Fonctions qui posent leur question par `ui.confirm`. Un nom nu reconnaît
# tout appel de ce nom ; « Classe.méthode », `self.méthode(` dans une
# méthode de cette classe.
WRAPPERS = {"show_and_ask", "ask_and_install", "TodoUpgrade.confirm"}

# (fichier, fonction, première clé t()) → défauts, dans l'ordre du fichier.
CONFIRM_DEFAULTS = {
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_assure_emulation",
        "Install buildx and QEMU now?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_build_odoo",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_build_odoo",
        "Rebuild without cache?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_install",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_install",
        "Use vendor packages?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_nettoyage",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_nettoyer_images",
        "Remove?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_nettoyer_projets",
        "Remove?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Continue anyway?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Continue?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Delete it?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Drop it and restore over it?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Is this database a copy? If unsure, yes.",
    ): [True],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Neutralize (mail servers, crons)?",
    ): [False],
    (
        "script/todo/container_menu.py",
        "ContainerMenuMixin._container_restaurer_base",
        "Update every module after the restore (-u all)?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Keep a _cache_ copy, not neutralized, to speed up the next restore"
        " of this image?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Neutralize the database?",
    ): [True],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Update all addons after neutralizing?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Update all addons before neutralizing?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager._restore_commands",
        "Update all addons?",
    ): [False],
    (
        "script/todo/database_manager.py",
        "DatabaseManager.duplicate_database",
        "Neutralize the copy?",
    ): [True],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin._poetry_drift_actif",
        "Update the venv to match the lock?",
    ): [False],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin._poetry_drift_autre",
        "Update the venv to match the lock?",
    ): [False],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin._venv_outillage_drift",
        "Install the missing requirements?",
    ): [False],
    (
        "script/todo/python_menu.py",
        "PythonMenuMixin.execute_python_versions",
        "Run them now?",
    ): [False],
    (
        "script/todo/qemu_install_monitor.py",
        "install_cli_browser",
        "Install now?",
    ): [False],
    (
        "script/todo/qemu_manage.py",
        "QemuManageMixin._qemu_install_shrink_tools",
        "Install them?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_caches_sudo",
        "Run these commands with sudo?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_cpu_installer",
        "Install {name}?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_diagnostic",
        "Save this report in private/diagnostic/?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_espace",
        "Delete these items?",
    ): [False],
    (
        "script/todo/system_menu.py",
        "SystemMenuMixin._system_gpu_sudo",
        "Read them with sudo? The password is asked here.",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._shell_install_starship_binary",
        "Install starship?",
    ): [False],
    (
        "script/todo/todo.py",
        "TODO._shell_install_starship_binary",
        "Run the upstream installer?",
    ): [False],
    (
        "script/todo/todo_install.py",
        "run_steps",
        "Upgrade the whole system first?",
    ): [False],
    (
        "script/todo/todo_telemetry.py",
        "install_sensors",
        "Install lm-sensors now?",
    ): [False],
    (
        "script/todo/transform_menu.py",
        "TransformMenuMixin._transform_install_env",
        "Create it now?",
    ): [True],
}


def _key(call) -> str:
    """La première clé `t("…")` des arguments de `call`, hors `default=`,
    dans l'ordre du source ; `<dynamique>` sans elle."""
    values = [*call.args]
    values += [kw.value for kw in call.keywords if kw.arg != "default"]
    found = []
    for value in values:
        for node in ast.walk(value):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func, first = node.func, node.args[0]
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            literal = isinstance(first, ast.Constant)
            if name == "t" and literal and isinstance(first.value, str):
                found.append((node.lineno, node.col_offset, first.value))
    return min(found)[2] if found else "<dynamique>"


def _default(value):
    """Le défaut que lit la table pour l'expression `value` (None quand
    l'appel n'en passe pas)."""
    if value is None:
        return None
    if isinstance(value, ast.Constant) and isinstance(value.value, bool):
        return value.value
    if isinstance(value, ast.Name):
        return "état"
    return ast.unparse(value)


def _asks(call, wrappers, owner) -> str | None:
    """`ui` pour un appel `ui.confirm(`, `wrapper` pour l'appel d'une
    enveloppe de `wrappers` depuis la classe `owner`, None sinon."""
    func = call.func
    target = getattr(func, "value", None)
    if isinstance(func, ast.Attribute) and func.attr == "confirm":
        if isinstance(target, ast.Name) and target.id == "ui":
            return "ui"
    name = getattr(func, "id", None) or getattr(func, "attr", None)
    if name in wrappers:
        return "wrapper"
    is_self = isinstance(target, ast.Name) and target.id == "self"
    if is_self and f"{owner}.{name}" in wrappers:
        return "wrapper"
    return None


def survey_source(source, path, wrappers=WRAPPERS) -> dict:
    """Les lignes de la table que donne le module `source`, de chemin
    `path` ; `wrappers` : les enveloppes, comme WRAPPERS."""
    rows = {}

    def visit(node, scope, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, [*scope, child.name], child.name)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, [*scope, child.name], owner)
                continue
            if isinstance(child, ast.Call):
                read(child, ".".join(scope) or "<module>", owner)
            visit(child, scope, owner)

    def read(call, where, owner):
        kind = _asks(call, wrappers, owner)
        if kind is None or where in wrappers:
            return
        given = {kw.arg: kw.value for kw in call.keywords}
        if kind == "ui" and "typed" in given:
            default = "typed"
        elif kind == "ui" and "default" not in given and len(call.args) > 1:
            default = _default(call.args[1])
        else:
            default = _default(given.get("default"))
        rows.setdefault((path, where, _key(call)), []).append(default)

    visit(ast.parse(source), [], None)
    return rows


def survey() -> dict:
    """Les lignes de la table que donne `script/todo`, hors du port."""
    rows = {}
    for path in sorted(TODO.rglob("*.py")):
        if path.is_relative_to(PORT):
            continue
        name = str(path.relative_to(REPO))
        rows.update(survey_source(path.read_text(encoding="utf-8"), name))
    return rows


SAMPLE = """
def wipe(name, state):
    ui.confirm(t("Delete it?"), default=False)
    ui.confirm(t("Delete it?"), True)
    ui.confirm(f"{name}: " + t("Keep it?"), default=state)
    ui.confirm(text, default=False)
    ui.confirm(t("Type the name"), typed=name)
    ui.confirm(t("Unsaid?"))

class Upgrade:
    def confirm(self, text, default):
        return ui.confirm(text, default=default)

    def step(self):
        self.confirm(t("Go on?"), default=True)
        show_and_ask("make forged", t("Install it?"), default=self.flag)
        click.confirm(t("Untouched?"))

class Other:
    def step(self):
        self.confirm(t("Not a wrapper?"), default=True)

def show_and_ask(cmd, question, default=False):
    return ui.confirm(question, default=default)
"""


class TestConfirmDefaults(unittest.TestCase):
    def test_the_survey_reads_each_form(self):
        rows = survey_source(
            SAMPLE, "forged.py", {"show_and_ask", "Upgrade.confirm"}
        )
        self.assertEqual(
            rows,
            {
                ("forged.py", "wipe", "Delete it?"): [False, True],
                ("forged.py", "wipe", "Keep it?"): ["état"],
                ("forged.py", "wipe", "<dynamique>"): [False],
                ("forged.py", "wipe", "Type the name"): ["typed"],
                ("forged.py", "wipe", "Unsaid?"): [None],
                ("forged.py", "Upgrade.step", "Go on?"): [True],
                ("forged.py", "Upgrade.step", "Install it?"): ["self.flag"],
            },
        )

    def test_every_confirm_states_its_default(self):
        self.assertEqual(survey(), CONFIRM_DEFAULTS)


class TestCountdownOnlyInAutoMode(unittest.TestCase):
    def test_seconds_is_the_delay_in_auto_mode_and_none_otherwise(self):
        names = (auto_ask.ENV_ENABLED, auto_ask.ENV_DELAY)
        with patch.dict(os.environ):
            for name in names:
                os.environ.pop(name, None)
            self.assertIsNone(auto_ask.seconds())
            os.environ[auto_ask.ENV_DELAY] = "7"
            self.assertIsNone(auto_ask.seconds())
            os.environ[auto_ask.ENV_ENABLED] = "1"
            self.assertEqual(auto_ask.seconds(), 7)
            os.environ[auto_ask.ENV_DELAY] = "-1"
            self.assertEqual(auto_ask.seconds(), auto_ask.DEFAULT_DELAY)


if __name__ == "__main__":
    unittest.main()
