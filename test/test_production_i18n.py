#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Chaque message des outils de production a sa traduction.

`t()` rend sa CLÉ quand la traduction manque : une clé oubliée s'affiche
en anglais sans que rien ne signale l'oubli. Le test lit les appels
`t("…")` des outils et du menu, et les modèles `N_("…")` que
`lib_ops/service.py` laisse traduire à l'outil qui attrape son refus.
"""

import ast
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

FICHIERS = (
    "script/odoo/update_module.py",
    "script/database/odoo_backup.py",
    "script/systemd/install_backup_timer.py",
    "script/todo/ops_menu.py",
    "script/lib_ops/service.py",
)


def cles(chemin):
    """Les chaînes littérales passées à t() ou N_() dans `chemin`."""
    with open(os.path.join(REPO, chemin), encoding="utf-8") as fichier:
        arbre = ast.parse(fichier.read())
    trouvees = set()
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        nom = getattr(noeud.func, "id", getattr(noeud.func, "attr", ""))
        if nom not in ("t", "N_"):
            continue
        for argument in noeud.args:
            if isinstance(argument, ast.Constant) and isinstance(
                argument.value, str
            ):
                trouvees.add(argument.value)
    return trouvees


class TestTraductions(unittest.TestCase):
    def test_chaque_cle_a_sa_traduction(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for chemin in FICHIERS:
            with self.subTest(fichier=chemin):
                manquantes = sorted(cles(chemin) - set(TRANSLATIONS))
                self.assertEqual(manquantes, [])

    def test_le_controle_lit_bien_quelque_chose(self):
        """Un test qui ne trouve aucune clé passerait toujours."""
        for chemin in FICHIERS:
            with self.subTest(fichier=chemin):
                self.assertGreater(len(cles(chemin)), 5)

    def test_aucune_cle_morte(self):
        """Chaque clé de la section Production de todo_i18n.py est encore
        une chaîne d'un des outils, ou de todo.py qui ouvre le menu : une
        clé que plus rien n'émet décrit un fonctionnement disparu.

        La section commence à son premier commentaire `# Production -` et
        va jusqu'à la fin du dictionnaire."""
        chemin = os.path.join(REPO, "script", "todo", "todo_i18n.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        debut = source.index("    # Production - ")
        ligne_debut = source.count("\n", 0, debut) + 1
        section = set()
        for noeud in ast.walk(ast.parse(source)):
            if isinstance(noeud, ast.Dict):
                for cle in noeud.keys:
                    if (
                        isinstance(cle, ast.Constant)
                        and isinstance(cle.value, str)
                        and cle.lineno > ligne_debut
                        and cle.col_offset == 4
                    ):
                        section.add(cle.value)
        self.assertGreater(len(section), 100)
        emises = set()
        for fichier in FICHIERS + ("script/todo/todo.py",):
            with open(os.path.join(REPO, fichier), encoding="utf-8") as f:
                for noeud in ast.walk(ast.parse(f.read())):
                    if isinstance(noeud, ast.Constant) and isinstance(
                        noeud.value, str
                    ):
                        emises.add(noeud.value)
        self.assertEqual(sorted(section - emises), [])

    def test_les_parametres_se_retrouvent_dans_le_francais(self):
        import re

        from script.todo.todo_i18n import TRANSLATIONS

        champ = re.compile(r"\{[^}]*\}")
        for chemin in FICHIERS:
            for cle in cles(chemin):
                with self.subTest(cle=cle):
                    francais = TRANSLATIONS[cle]["fr"]
                    self.assertEqual(
                        sorted(champ.findall(cle)),
                        sorted(champ.findall(francais)),
                    )


if __name__ == "__main__":
    unittest.main()
