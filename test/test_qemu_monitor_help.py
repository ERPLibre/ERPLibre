#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fenêtre d'aide du suivi d'installation : h, F1 ou « ? » liste tous
les raccourcis, construits à partir des BINDINGS du suivi."""

import os
import sys
import unittest

from textual.widgets import Static

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_qemu_monitor_add_vms import Base  # noqa: E402


class TestAide(Base):
    async def _texte_aide(self, pilot, app):
        await pilot.pause()
        return "\n".join(str(w.render()) for w in app.screen.query(Static))

    async def test_h_lists_every_shortcut(self):
        app = self.app()
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            await pilot.press("h")
            self.assertEqual("HelpScreen", type(app.screen).__name__)
            texte = await self._texte_aide(pilot, app)
            for b in app.BINDINGS:
                libelle = b.description if hasattr(b, "description") else b[2]
                self.assertIn(libelle, texte)
            # Les noms de touches Textual se lisent comme sur le clavier.
            self.assertIn("+ ", texte)
            self.assertNotIn("greater_than_sign", texte)
            # Les touches d'une même action tiennent sur une seule ligne.
            self.assertIn("h / F1 / ?", texte)
            # L'aide vient juste après « Quitter », dans le pied de page
            # comme dans la fenêtre.
            self.assertEqual("h", app.BINDINGS[1][0])
            lignes = [x for x in texte.splitlines() if x.startswith("  ")]
            self.assertIn("h / F1 / ?", lignes[1])

    async def test_question_mark_opens_and_escape_closes(self):
        app = self.app()
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            self.assertEqual("HelpScreen", type(app.screen).__name__)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotEqual("HelpScreen", type(app.screen).__name__)

    async def test_help_does_not_stack(self):
        app = self.app()
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f1")
            app.action_help()
            await pilot.pause()
            self.assertEqual(2, len(app.screen_stack))


if __name__ == "__main__":
    unittest.main(verbosity=1)
