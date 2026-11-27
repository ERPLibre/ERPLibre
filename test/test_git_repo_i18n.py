#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les libellés de la mise à niveau des dépôts, dans les deux langues.

t() rend sa clé telle quelle quand le catalogue ne la connaît pas : une
clé oubliée ne lève rien, l'écran montre simplement l'anglais à qui a
choisi le français. Ces gardes lisent donc la SOURCE des modules, là où
une clé oubliée se voit encore.
"""

import ast
import os
import unittest

from script.git import repo_upgrade
from script.todo import git_repo_menu, todo_i18n

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULES = (
    os.path.join("script", "git", "repo_upgrade.py"),
    os.path.join("script", "git", "repo_apply.py"),
    os.path.join("script", "todo", "git_repo_menu.py"),
    os.path.join("script", "todo", "git_repo_tui.py"),
)

# Les tables qui portent des CLÉS, traduites à l'affichage.
TABLES = {
    "repo_upgrade.LIBELLES_APPROFONDIR": repo_upgrade.LIBELLES_APPROFONDIR,
    "repo_upgrade._TITRES": repo_upgrade._TITRES,
    "repo_upgrade._VERDICTS_TITRE": repo_upgrade._VERDICTS_TITRE,
    "repo_upgrade._ISSUES_TITRE": repo_upgrade._ISSUES_TITRE,
    "git_repo_menu.ETATS": git_repo_menu.ETATS,
    "git_repo_menu.DECOMPTES": git_repo_menu.DECOMPTES,
}


def arbre(chemin):
    with open(os.path.join(RACINE, chemin), encoding="utf-8") as fh:
        return ast.parse(fh.read())


def est_appel_t(noeud):
    return (
        isinstance(noeud, ast.Call)
        and isinstance(noeud.func, ast.Name)
        and noeud.func.id == "t"
    )


def cles_litterales(chemin):
    """Les clés passées à t() sous forme de chaîne littérale."""
    return [
        n.args[0].value
        for n in ast.walk(arbre(chemin))
        if est_appel_t(n)
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
    ]


def appels_t_a_l_import(chemin):
    """Les appels à t() que l'import du module évalue : ceux du niveau
    module et des corps de classe, hors fonctions et lambdas."""
    trouves = []

    def visiter(noeud):
        if isinstance(
            noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        ):
            return
        if est_appel_t(noeud):
            trouves.append(noeud.lineno)
        for enfant in ast.iter_child_nodes(noeud):
            visiter(enfant)

    visiter(arbre(chemin))
    return trouves


class TestChaqueCleEstTraduite(unittest.TestCase):
    def test_les_cles_ont_ete_lues(self):
        """Sinon un parcours vide ferait passer la garde suivante."""
        total = sum(len(cles_litterales(m)) for m in MODULES)
        self.assertGreater(total, 200)

    def test_chaque_litteral_est_une_cle_du_catalogue(self):
        for module in MODULES:
            with self.subTest(module=module):
                absentes = sorted(
                    {
                        c
                        for c in cles_litterales(module)
                        if c not in todo_i18n.TRANSLATIONS
                    }
                )
                self.assertEqual(absentes, [], "clés absentes du catalogue")

    def test_chaque_valeur_de_table_est_une_cle_du_catalogue(self):
        for nom, table in TABLES.items():
            with self.subTest(table=nom):
                absentes = sorted(
                    v
                    for v in table.values()
                    if v not in todo_i18n.TRANSLATIONS
                )
                self.assertEqual(absentes, [], "clés absentes du catalogue")


class TestLaLangueSeLitALAffichage(unittest.TestCase):
    """Le module s'importe au démarrage de TODO, AVANT que la langue soit
    choisie : un libellé traduit à l'import garderait la langue d'alors."""

    def setUp(self):
        self.langue = todo_i18n._current_lang

    def tearDown(self):
        todo_i18n._current_lang = self.langue

    def test_aucun_t_n_est_evalue_a_l_import(self):
        for module in MODULES:
            with self.subTest(module=module):
                self.assertEqual(appels_t_a_l_import(module), [])

    def test_un_changement_de_langue_atteint_les_titres(self):
        cle = repo_upgrade._VERDICTS_TITRE["a_rebaser"]
        attendu = todo_i18n.TRANSLATIONS[cle]
        self.assertNotEqual(attendu["fr"], attendu["en"])
        for langue in ("en", "fr", "en"):
            todo_i18n._current_lang = langue
            with self.subTest(langue=langue):
                self.assertEqual(
                    repo_upgrade.titre_verdict("a_rebaser"), attendu[langue]
                )
                self.assertEqual(
                    repo_upgrade.libelle_approfondir("complet"),
                    todo_i18n.TRANSLATIONS[
                        repo_upgrade.LIBELLES_APPROFONDIR["complet"]
                    ][langue],
                )

    def test_un_identifiant_inconnu_reste_lisible(self):
        """Un verdict hors table s'affiche tel quel plutôt que de lever."""
        self.assertEqual(repo_upgrade.titre_verdict("inconnu"), "inconnu")
        self.assertEqual(
            repo_upgrade.libelle_approfondir("inconnu"), "inconnu"
        )


if __name__ == "__main__":
    unittest.main()
