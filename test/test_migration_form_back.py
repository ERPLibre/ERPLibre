#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'écran de reprise doit OFFRIR le retour à une étape, pas le cacher.

Le mécanisme existait — Entrée sur une ligne du tableau — mais vivait dans une
ligne d'astuce sous quatre boutons nommés. Une capacité qu'il faut deviner
n'est pas offerte : elle a donc une touche, un bouton et un message, comme les
quatre autres actions.
"""

import json
import unittest

from script.todo import todo_i18n
from script.todo.migration_form import run_resume_tui
from script.todo.todo_upgrade import TodoUpgrade


def context():
    """Le contexte d'une migration arrêtée avant les montées de version."""
    progression = {
        "migration_file": "./image_db/technolibre.zip",
        "config_database_name": "technolibre_migration_01_neutralize",
        "target_odoo_version": "18.0",
        "date_create": "2026-08-12 05:04:22",
        "state_0_install_odoo": True,
        "state_1_restore_database": True,
        "state_2_update_all": True,
        "state_3_clean_database": True,
    }
    return TodoUpgrade.resume_context(TodoUpgrade, progression)


class TestBackIsOffered(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.ctx = context()

    def bindings(self, app):
        out = {}
        for item in app.BINDINGS:
            if isinstance(item, tuple):
                out[item[0]] = item[1]
            else:
                out[item.key] = item.action
        return out

    def test_b_is_a_binding_like_the_others(self):
        app = run_resume_tui(self.ctx, run_app=False)
        self.assertEqual(self.bindings(app).get("b"), "back_step")

    def test_the_action_exists(self):
        self.assertTrue(
            hasattr(
                run_resume_tui(self.ctx, run_app=False), "action_back_step"
            )
        )


class TestBackWorks(unittest.IsolatedAsyncioTestCase):
    """Piloté dans un terminal simulé : la touche mène bien au choix."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.ctx = context()

    async def test_b_focuses_the_steps_and_enter_replays_from_there(self):
        from textual.widgets import DataTable

        app = run_resume_tui(self.ctx, run_app=False)
        async with app.run_test() as pilot:
            await pilot.press("b")
            await pilot.pause()
            table = app.query_one("#steps", DataTable)
            self.assertTrue(table.has_focus)
            # Le curseur part sur la première étape inachevée ; on remonte de
            # deux pour viser « mettre à jour tous les modules ».
            await pilot.press("up")
            await pilot.press("up")
            await pilot.pause()
            expected = str(self.ctx["steps"][table.cursor_row]["step"])
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app._result["answer"], expected)

    async def test_there_is_a_button_too(self):
        # C'est l'absence VISIBLE qui a été signalée : une touche seule ne se
        # voit pas parmi quatre boutons. Les widgets ne se lisent qu'une fois
        # l'écran monté, d'où le pilote.
        from textual.widgets import Button

        app = run_resume_tui(self.ctx, run_app=False)
        async with app.run_test():
            labels = [b.label.plain for b in app.query(Button)]
        self.assertIn("Go back to a step", labels)

    async def test_the_button_does_the_same(self):
        from textual.widgets import Button, DataTable

        app = run_resume_tui(self.ctx, run_app=False)
        async with app.run_test() as pilot:
            button = next(b for b in app.query(Button) if b.id == "a_back")
            await pilot.click(button)
            await pilot.pause()
            self.assertTrue(app.query_one("#steps", DataTable).has_focus)
            # Et surtout : le bouton ne répond PAS à la place de l'utilisateur.
            self.assertIsNone(app._result["answer"])


if __name__ == "__main__":
    unittest.main()
