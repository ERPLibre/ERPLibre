#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'entrée « [0] Retour » des menus, en bleu poudre vers un terminal."""

import io
import unittest

from script.todo import todo_couleur
from script.todo.todo_i18n import t


class Terminal(io.StringIO):
    def isatty(self):
        return True


class TestRetour(unittest.TestCase):
    def test_bleu_poudre_en_couleur_vraie(self):
        texte = todo_couleur.retour(
            None, Terminal(), {"COLORTERM": "truecolor"}
        )
        self.assertEqual(
            texte, f"\x1b[38;2;176;224;230m[0] {t('Back')}\x1b[0m"
        )

    def test_repli_sur_256_couleurs(self):
        texte = todo_couleur.retour(None, Terminal(), {})
        self.assertTrue(texte.startswith("\x1b[38;5;152m"))
        self.assertTrue(texte.endswith("\x1b[0m"))

    def test_pas_de_couleur_hors_terminal(self):
        self.assertEqual(
            todo_couleur.retour(None, io.StringIO(), {}), f"[0] {t('Back')}"
        )

    def test_no_color_et_term_dumb_coupent_la_couleur(self):
        for environ in ({"NO_COLOR": ""}, {"TERM": "dumb"}):
            self.assertEqual(
                todo_couleur.retour(None, Terminal(), environ),
                f"[0] {t('Back')}",
            )

    def test_un_flux_sans_isatty_reste_sans_couleur(self):
        self.assertFalse(todo_couleur.couleurs_actives(object(), {}))


class TestMenus(unittest.TestCase):
    def test_le_menu_type_porte_l_entree_retour(self):
        """fill_help_info, par où passe la plupart des menus."""
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        texte = todo.fill_help_info([{"prompt_description": "Un"}])
        self.assertIn(todo_couleur.retour(), texte)

    def test_plus_aucun_retour_ecrit_a_la_main(self):
        """Une entrée « [0] Retour » écrite sans retour() échapperait à la
        couleur : aucune ne doit rester dans le TODO."""
        import glob
        import re

        motif = re.compile(
            r"""\[0\] \{t\(["']Back["']\)\}|"\s*\[0\] " \+ t\("Back"\)"""
        )
        restes = []
        for chemin in glob.glob("script/todo/**/*.py", recursive=True):
            if chemin.endswith("todo_couleur.py"):
                continue
            with open(chemin, encoding="utf-8") as fh:
                if motif.search(fh.read()):
                    restes.append(chemin)
        self.assertEqual(restes, [])


if __name__ == "__main__":
    unittest.main()
