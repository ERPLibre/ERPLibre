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


class TestQuitter(unittest.TestCase):
    def test_meme_bleu_poudre_que_retour(self):
        environ = {"COLORTERM": "truecolor"}
        self.assertEqual(
            todo_couleur.quitter(None, Terminal(), environ),
            f"\x1b[38;2;176;224;230m[0] 🚪 {t('Quit')}\x1b[0m",
        )
        self.assertTrue(
            todo_couleur.retour(None, Terminal(), environ).startswith(
                "\x1b[38;2;176;224;230m"
            )
        )

    def test_pas_de_couleur_hors_terminal(self):
        self.assertEqual(
            todo_couleur.quitter(None, io.StringIO(), {}),
            f"[0] 🚪 {t('Quit')}",
        )


class TestMenus(unittest.TestCase):
    def test_le_menu_type_porte_l_entree_retour(self):
        """fill_help_info, par où passe la plupart des menus."""
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        texte = todo.fill_help_info([{"prompt_description": "Un"}])
        self.assertIn(todo_couleur.retour(), texte)

    def test_plus_aucun_retour_ecrit_a_la_main(self):
        """Une entrée « [0] Retour » écrite sans retour(), ou « [0] Quitter »
        sans quitter(), échapperait à la couleur : aucune ne doit rester."""
        import glob
        import re

        motif = re.compile(
            r"""\[0\] \{t\(["']Back["']\)\}|"\s*\[0\] " \+ t\("Back"\)"""
            r"""|\[0\] 🚪 \{t\(["']Quit["']\)\}"""
        )
        restes = []
        for chemin in glob.glob("script/todo/**/*.py", recursive=True):
            if chemin.endswith("todo_couleur.py"):
                continue
            with open(chemin, encoding="utf-8") as fh:
                if motif.search(fh.read()):
                    restes.append(chemin)
        self.assertEqual(restes, [])

    def test_toute_sortie_composee_passe_par_le_bleu_poudre(self):
        """« 0: 🔙 Retour », « ⏎ 🔙 Retour », « 0: Quitter », « [0] 🔙
        Plus tard » : toute sortie de menu COMPOSÉE en texte — f-string ou
        concaténation qui porte t("Back"), t("Quit") ou « 🔙 » — passe par
        retour(), quitter() ou bleu_poudre(). Un t("Quit") nu, libellé de
        bouton ou raccourci Textual, n'est pas composé : une séquence ANSI
        s'y afficherait telle quelle, il reste hors de la règle."""
        import ast
        import glob

        colorants = {"retour", "quitter", "bleu_poudre"}

        def sortie(noeud):
            if isinstance(noeud, ast.Call):
                return (
                    getattr(noeud.func, "id", None) == "t"
                    and len(noeud.args) == 1
                    and isinstance(noeud.args[0], ast.Constant)
                    and noeud.args[0].value in ("Back", "Quit")
                )
            return isinstance(noeud, ast.Constant) and "🔙" in str(noeud.value)

        restes = []
        for chemin in glob.glob("script/todo/**/*.py", recursive=True):
            if chemin.endswith(("todo_couleur.py", "todo_i18n.py")):
                continue
            with open(chemin, encoding="utf-8") as fh:
                arbre = ast.parse(fh.read())
            parents = {}
            for noeud in ast.walk(arbre):
                for enfant in ast.iter_child_nodes(noeud):
                    parents[enfant] = noeud
            for noeud in ast.walk(arbre):
                if not sortie(noeud):
                    continue
                compose = colore = False
                courant = parents.get(noeud)
                while courant is not None and not colore:
                    if isinstance(courant, (ast.JoinedStr, ast.BinOp)):
                        compose = True
                    if (
                        isinstance(courant, ast.Call)
                        and getattr(courant.func, "id", None) in colorants
                    ):
                        colore = True
                    courant = parents.get(courant)
                if compose and not colore:
                    restes.append(f"{chemin}:{noeud.lineno}")
        self.assertEqual(restes, [])


if __name__ == "__main__":
    unittest.main()
