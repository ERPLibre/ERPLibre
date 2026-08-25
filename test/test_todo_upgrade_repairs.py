#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Deux réparations existaient et ne tournaient jamais.

`fix_duplicate_index.py` et `restore_config_defaults.py` étaient écrits,
éprouvés sur copie, et absents du pilote. Chaque migration refabriquait
donc ses index redondants et reperdait sa liste de prix par défaut —
mesuré à l'identique sur DEUX chaînes 12 → 18 indépendantes : 414 index
et une liste manquante dans l'une comme dans l'autre.

Un outil qui existe sans être appelé est le défaut le plus discret de ce
dépôt : rien n'échoue, rien ne l'écrit, et l'on croit le problème réglé
parce qu'on se souvient d'avoir écrit le correctif. Ce fichier vérifie
donc les DEUX choses — que les méthodes se comportent bien, et qu'elles
sont réellement appelées depuis la boucle des paliers.

Les docstrings de ces méthodes CITENT `wait_at_error=False` pour
l'expliquer. Un test qui lirait le texte du fichier le trouverait là et
passerait au vert sans que l'argument soit passé nulle part. On lit donc
l'arbre syntaxique, jamais le texte.
"""

import ast
import unittest
from pathlib import Path

from script.todo.todo_upgrade import TodoUpgrade

PILOTE = (
    Path(__file__).resolve().parent.parent
    / "script"
    / "todo"
    / "todo_upgrade.py"
)


def arbre_du_pilote():
    """L'AST du pilote. `read_text` referme le fichier."""
    return ast.parse(PILOTE.read_text(encoding="utf-8"))


class FauxPilote:
    """Un pilote qui note ce qu'on lui demande d'exécuter."""

    def __init__(self):
        self.appels = []

    def todo_upgrade_execute(self, cmd, wait_at_error=True, **kwargs):
        self.appels.append((cmd, wait_at_error))
        return 0


class TestWhenTheIndexRepairRuns(unittest.TestCase):
    def _lancer(self, version):
        faux = FauxPilote()
        TodoUpgrade.drop_duplicate_index(faux, "ma_base", version)
        return faux.appels

    def test_it_stays_quiet_before_odoo_17(self):
        """La convention n'a pas changé avant : il ne trouverait rien."""
        for version in (13, 14, 15, 16):
            self.assertEqual(self._lancer(version), [], version)

    def test_it_runs_from_17_onward(self):
        for version in (17, 18):
            self.assertEqual(len(self._lancer(version)), 1, version)

    def test_it_repairs_rather_than_reports(self):
        cmd, _ = self._lancer(18)[0]
        self.assertIn("--apply", cmd)
        self.assertIn("fix_duplicate_index.py", cmd)
        self.assertIn("-d ma_base", cmd)

    def test_a_leftover_index_does_not_halt_the_migration(self):
        """Avec --apply, le code 1 veut dire « il en reste », pas « échec »."""
        _, wait_at_error = self._lancer(18)[0]
        self.assertFalse(wait_at_error)


class TestWhenTheDefaultsRepairRuns(unittest.TestCase):
    def _lancer(self, dernier):
        faux = FauxPilote()
        TodoUpgrade.restore_config_defaults(faux, "ma_base", dernier)
        return faux.appels

    def test_it_waits_for_the_last_step(self):
        """Il charge le registre Odoo : six fois pour rien coûterait cher."""
        self.assertEqual(self._lancer(False), [])

    def test_it_runs_on_the_last_step(self):
        self.assertEqual(len(self._lancer(True)), 1)

    def test_it_repairs_rather_than_reports(self):
        cmd, wait_at_error = self._lancer(True)[0]
        self.assertIn("--apply", cmd)
        self.assertIn("restore_config_defaults.py", cmd)
        self.assertFalse(wait_at_error)


class TestTheyAreActuallyCalled(unittest.TestCase):
    """Le défaut visé : une méthode écrite que personne n'appelle."""

    @classmethod
    def setUpClass(cls):
        cls.arbre = arbre_du_pilote()
        cls.appels = {}
        for noeud in ast.walk(cls.arbre):
            if isinstance(noeud, ast.Call) and isinstance(
                noeud.func, ast.Attribute
            ):
                cls.appels.setdefault(noeud.func.attr, []).append(noeud)

    def _boucle_des_paliers(self):
        for noeud in ast.walk(self.arbre):
            if (
                isinstance(noeud, ast.For)
                and isinstance(noeud.iter, ast.Call)
                and getattr(noeud.iter.func, "id", "") == "enumerate"
                and [
                    t.id
                    for t in ast.walk(noeud.target)
                    if isinstance(t, ast.Name)
                ]
                == ["index", "next_version"]
            ):
                return noeud
        raise AssertionError("boucle des paliers introuvable")

    def test_both_repairs_are_called_from_the_tier_loop(self):
        boucle = self._boucle_des_paliers()
        for nom in ("drop_duplicate_index", "restore_config_defaults"):
            dedans = [
                n
                for n in self.appels.get(nom, [])
                if boucle.lineno < n.lineno < boucle.end_lineno
            ]
            self.assertEqual(len(dedans), 1, nom)

    def test_the_index_repair_comes_after_the_cleanup(self):
        """Le nettoyage supprime des colonnes, donc leurs index avec."""
        nettoyage = self.appels["prompt_database_cleanup"][-1].lineno
        index = self.appels["drop_duplicate_index"][0].lineno
        fumee = self.appels["prompt_smoke_public_url"][-1].lineno
        self.assertLess(nettoyage, index)
        self.assertLess(index, fumee)

    def test_the_defaults_repair_runs_before_the_smoke_test(self):
        """Le test de fumée doit voir une base cohérente."""
        defauts = self.appels["restore_config_defaults"][0].lineno
        fumee = self.appels["prompt_smoke_public_url"][-1].lineno
        self.assertLess(defauts, fumee)

    def test_the_last_step_is_computed_from_the_loop_itself(self):
        """`is_last` doit venir de la liste, pas d'un numéro écrit en dur."""
        appel = self.appels["restore_config_defaults"][0]
        source = ast.dump(appel)
        self.assertIn("lst_next_version", source)
        self.assertNotIn("Constant(value=18)", source)


class TestTheDocstringTrapIsNotWhatWeRead(unittest.TestCase):
    """La preuve que ce fichier ne se paie pas de mots.

    `wait_at_error=False` apparaît dans les docstrings des deux méthodes.
    Si l'argument disparaissait des APPELS, un test textuel resterait vert.
    """

    def test_the_docstrings_do_mention_it(self):
        for nom in ("drop_duplicate_index", "restore_config_defaults"):
            methode = getattr(TodoUpgrade, nom)
            self.assertIn("wait_at_error=False", methode.__doc__ or "", nom)

    def test_and_yet_the_keyword_is_really_passed(self):
        arbre = arbre_du_pilote()
        for nom in ("drop_duplicate_index", "restore_config_defaults"):
            corps = None
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
                    corps = noeud
            self.assertIsNotNone(corps, nom)
            # Le corps SANS sa docstring : c'est là que doit vivre l'argument.
            sans_texte = [
                n
                for n in corps.body
                if not (
                    isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                )
            ]
            trouve = False
            for noeud in sans_texte:
                for interne in ast.walk(noeud):
                    if isinstance(interne, ast.keyword) and (
                        interne.arg == "wait_at_error"
                    ):
                        self.assertIs(interne.value.value, False, nom)
                        trouve = True
            self.assertTrue(trouve, nom)


if __name__ == "__main__":
    unittest.main()
