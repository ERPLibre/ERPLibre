#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'écran de reprise doit dire ce qui a eu lieu, pas ce qu'il croit.

Une base venant d'une vieille version se met à jour AVANT la neutralisation :
l'outil le propose au tout début. Ce travail est celui de l'étape 2, fait plus
tôt — mais il n'était enregistré que sous `state_1_update_all`, et l'écran
cherchait `state_2_*`.

Deux conséquences, l'une visible et l'autre chère : l'étape restait « non
démarrée » alors qu'elle venait de tourner, et la reprise suivante relançait
`update_addons_all` sur une base déjà à jour.
"""

import unittest

from script.todo import todo_i18n
from script.todo.todo_upgrade import MIGRATION_STEP, TodoUpgrade


class StatusCase(unittest.TestCase):
    def setUp(self):
        # PAS set_lang() : il persiste la langue dans env_var.sh, suivi par
        # git. On écrit la mémoïsation, et on la rend.
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestUpdateAllStatus(StatusCase):
    def status(self, dct):
        return TodoUpgrade.step_status(dct, 2)

    def test_an_old_log_knows_only_the_early_flag(self):
        # Le cas signalé : un journal écrit avant le correctif. L'étape a bien
        # eu lieu, il ne faut pas la dire « non démarrée ».
        icon, detail = self.status({"state_1_update_all": True})
        self.assertEqual(icon, "✅")
        self.assertIn("early", detail)

    def test_a_new_log_says_when_it_happened(self):
        icon, detail = self.status(
            {
                "state_1_update_all": True,
                "state_2_update_all": True,
                "state_2_done_early": True,
            }
        )
        self.assertEqual(icon, "✅")
        self.assertIn("early", detail)

    def test_done_at_its_normal_place_says_only_done(self):
        icon, detail = self.status({"state_2_update_all": True})
        self.assertEqual(icon, "✅")
        self.assertNotIn("early", detail)

    def test_really_not_started(self):
        icon, detail = self.status({"state_0_install_odoo": True})
        self.assertEqual(icon, "⬜")
        self.assertIn("not started", detail)

    def test_the_other_steps_are_untouched(self):
        # Le correctif ne vaut que pour l'étape 2 : les autres gardent leur
        # règle, sinon un drapeau d'une étape en éclairerait une autre.
        dct = {"state_1_update_all": True}
        for step, _ in MIGRATION_STEP:
            if step in (1, 2):
                continue
            icon, _ = TodoUpgrade.step_status(dct, step)
            self.assertEqual(icon, "⬜", f"étape {step}")


class TestNeedsUpdateAll(unittest.TestCase):
    """Ce qui décide de relancer, ou non, une mise à jour de plusieurs heures."""

    def test_nothing_done_yet(self):
        self.assertTrue(TodoUpgrade.needs_update_all({}))

    def test_its_own_flag_is_enough(self):
        self.assertFalse(
            TodoUpgrade.needs_update_all({"state_2_update_all": True})
        )

    def test_the_early_flag_survives_a_resume(self):
        # LE défaut : la variable de session repart à False à la reprise, et
        # seule la trace écrite subsiste. Sans la lire, on relançait tout.
        self.assertFalse(
            TodoUpgrade.needs_update_all({"state_1_update_all": True})
        )

    def test_the_session_variable_still_counts(self):
        self.assertFalse(TodoUpgrade.needs_update_all({}, True))

    def test_an_unrelated_flag_does_not_count(self):
        self.assertTrue(
            TodoUpgrade.needs_update_all({"state_1_restore_database": True})
        )


if __name__ == "__main__":
    unittest.main()
