#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La seule fonction qui puisse donner le feu vert à une destruction.

Elle arrive AVANT l'exercice de restauration qui s'en servira : une garde
écrite après le geste qu'elle garde n'a jamais gardé ce geste.

LE NOM N'EST JAMAIS INTERROGÉ, et c'est ce que tient l'épreuve centrale.
Deux bases aux noms opposés, répondant la même chose, reçoivent le même
verdict — sans quoi le prédicat ne serait qu'une liste de préfixes de plus,
comme celle qu'il vient remplacer.

AUCUN SERVEUR N'EST TOUCHÉ, et aucune épreuve n'est sautée. Le lecteur est
injecté : c'est ce qui rend la décision vérifiable depuis une station, et
une garde qu'on ne sait pas éprouver s'ouvre le jour où elle casse.

Les noms de base cités ici sont inventés.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.database import drill_guard as G  # noqa: E402

# Les fragments qui distinguent les quatre lectures dans une requête.
MOTIFS = {
    "odoo": "information_schema",
    "flag": "is_neutralized",
    "test_user": "res_users",
    "payment_live": "payment_provider",
    "cron_active": "ir_cron",
}


def lecteur(odoo=1, flag=0, test_user=0, payment_live=0, cron_active=0):
    """Un lecteur de banc. `None` simule une requête qui n'aboutit pas."""
    reponses = dict(
        odoo=odoo,
        flag=flag,
        test_user=test_user,
        payment_live=payment_live,
        cron_active=cron_active,
    )
    vues = []

    def run(database, sql):
        vues.append((database, sql))
        for cle, motif in MOTIFS.items():
            if motif in sql:
                valeur = reponses[cle]
                # Une requête refusée rend une liste VIDE, exactement comme
                # zéro ligne : c'est la confusion que le COUNT dénoue.
                return [] if valeur is None else [[valeur]]
        raise AssertionError(f"requête non reconnue : {sql}")

    run.vues = vues
    return run


class TestLeNomNeProuveRien(unittest.TestCase):
    def test_two_opposite_names_answering_alike_get_the_same_verdict(self):
        """L'épreuve centrale. Sans elle, le prédicat ne serait qu'une
        liste de préfixes de plus."""
        drill = lecteur(flag=1)
        self.assertEqual(
            G.inspect("production", run_psql=drill).verdict,
            G.inspect("essai_jetable", run_psql=lecteur(flag=1)).verdict,
        )

    def test_a_name_that_screams_test_is_not_enough(self):
        """Sept bases portaient la marque de neutralisation dans leur nom,
        et le drapeau était absent des sept."""
        vu = G.inspect("test_jetable_2026", run_psql=lecteur())
        self.assertEqual(G.REAL, vu.verdict)

    def test_the_name_is_never_looked_at_only_connected_to(self):
        """Il sert de POIGNÉE : aucune requête ne le mentionne."""
        run = lecteur(flag=1)
        G.inspect("base-de-banc", run_psql=run)
        self.assertTrue(run.vues, "aucune requête : rien n'est prouvé")
        for _base, sql in run.vues:
            with self.subTest(sql=sql[:40]):
                self.assertNotIn("base-de-banc", sql)


class TestLesDeuxTemoinsSontDisjoints(unittest.TestCase):
    """Les deux façons de fabriquer une copie laissent des traces
    différentes : exiger les deux déclarerait « réelle » la moitié des
    copies que l'outillage fabrique lui-même."""

    def test_the_flag_alone_is_enough(self):
        self.assertEqual(
            G.DRILL, G.inspect("x", run_psql=lecteur(flag=1)).verdict
        )

    def test_the_drill_account_alone_is_enough(self):
        self.assertEqual(
            G.DRILL, G.inspect("x", run_psql=lecteur(test_user=1)).verdict
        )

    def test_neither_trace_means_a_real_database(self):
        """Une copie qu'on n'a pas neutralisée n'est pas un exercice."""
        self.assertEqual(G.REAL, G.inspect("x", run_psql=lecteur()).verdict)

    def test_both_together_are_still_a_drill(self):
        self.assertEqual(
            G.DRILL,
            G.inspect("x", run_psql=lecteur(flag=1, test_user=1)).verdict,
        )


class TestLesVetos(unittest.TestCase):
    """Une copie qui encaisse ou qui envoie des courriels n'est pas un
    exercice, même marquée comme tel."""

    def test_an_active_scheduled_task_disqualifies(self):
        vu = G.inspect("x", run_psql=lecteur(flag=1, cron_active=33))
        self.assertEqual(G.REAL, vu.verdict)
        self.assertEqual(33, vu.cron_active)

    def test_a_live_payment_provider_disqualifies(self):
        vu = G.inspect("x", run_psql=lecteur(flag=1, payment_live=1))
        self.assertEqual(G.REAL, vu.verdict)

    def test_the_veto_beats_both_witnesses_at_once(self):
        vu = G.inspect(
            "x", run_psql=lecteur(flag=1, test_user=1, cron_active=1)
        )
        self.assertEqual(G.REAL, vu.verdict)


class TestCeQuOnNeSaitPasSeRefuse(unittest.TestCase):
    def test_one_unreadable_check_is_enough_to_refuse(self):
        """Se prononcer sur trois réponses quand la quatrième manque, c'est
        parier que la manquante allait dans le même sens."""
        vu = G.inspect("x", run_psql=lecteur(flag=1, test_user=None))
        self.assertEqual(G.UNREADABLE, vu.verdict)

    def test_it_names_what_it_could_not_read(self):
        """« illisible » sans dire quoi envoie chercher au hasard."""
        vu = G.inspect("x", run_psql=lecteur(test_user=None, cron_active=None))
        self.assertIn("cron_active", vu.detail)
        self.assertIn("test_user", vu.detail)

    def test_an_unreachable_database_is_unreadable_not_real(self):
        """Et le DIT : « illisible » tout court ne distingue pas un serveur
        muet d'un contrôle sur quatre qui n'a pas répondu, alors que le
        premier se corrige côté connexion et le second côté base."""
        vu = G.inspect("x", run_psql=lecteur(odoo=None))
        self.assertEqual(G.UNREADABLE, vu.verdict)
        self.assertTrue(vu.detail)
        self.assertNotEqual(
            vu.detail, G.inspect("x", run_psql=lecteur(flag=None)).detail
        )

    def test_something_that_is_not_an_odoo_database_says_so(self):
        """Sans cette question, une base vide rend « relation inexistante »
        sur chaque contrôle, et se lirait comme illisible."""
        self.assertEqual(
            G.NOT_ODOO, G.inspect("x", run_psql=lecteur(odoo=0)).verdict
        )

    def test_a_reader_that_raises_never_yields_a_drill(self):
        def casse(_db, _sql):
            raise RuntimeError("connexion refusée")

        self.assertEqual(G.UNREADABLE, G.inspect("x", run_psql=casse).verdict)

    def test_none_and_zero_are_not_the_same_thing(self):
        """L'un dit qu'on n'a pas pu regarder, l'autre qu'il n'y a rien."""
        illisible = G.inspect("x", run_psql=lecteur(flag=None))
        vide = G.inspect("x", run_psql=lecteur(flag=0))
        self.assertEqual(G.UNREADABLE, illisible.verdict)
        self.assertEqual(G.REAL, vide.verdict)


class TestLeFeuVert(unittest.TestCase):
    def test_only_a_drill_opens_the_door(self):
        for verdict, run in (
            (G.DRILL, lecteur(flag=1)),
            (G.REAL, lecteur()),
            (G.UNREADABLE, lecteur(flag=None)),
            (G.NOT_ODOO, lecteur(odoo=0)),
        ):
            with self.subTest(verdict=verdict):
                self.assertEqual(
                    verdict == G.DRILL,
                    G.is_drill_database("x", run_psql=run),
                )

    def test_the_vocabulary_is_closed_and_pinned(self):
        """Un écran les affichera : un jeton renommé casse un consommateur
        sans qu'aucune constante bouge."""
        self.assertEqual(
            ("drill", "real", "unreadable", "not-odoo"), G.VERDICTS
        )

    def test_every_verdict_it_can_reach_is_in_the_vocabulary(self):
        for run in (
            lecteur(flag=1),
            lecteur(),
            lecteur(flag=None),
            lecteur(odoo=0),
        ):
            self.assertIn(G.inspect("x", run_psql=run).verdict, G.VERDICTS)


class TestElleNeFaitRienDAutre(unittest.TestCase):
    """Elle ne détruit rien, n'appelle rien, n'affiche rien."""

    def source(self):
        chemin = os.path.join(RACINE, "script", "database", "drill_guard.py")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    def test_it_neither_prints_nor_prompts_nor_runs(self):
        import ast

        arbre = ast.parse(self.source())
        appels = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertTrue(appels, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "exec", "eval"):
            self.assertNotIn(interdit, appels)

    def test_it_is_a_library_and_does_not_run_itself(self):
        """Pas de « main », pas d'analyseur d'arguments : une garde qui se
        lance est une garde qu'on peut lancer au lieu de l'interroger."""
        source = self.source()
        self.assertNotIn("__main__", source)
        self.assertNotIn("argparse", source)

    def test_it_reads_only_counts(self):
        """Un rapport finit dans un billet : des COMPTES, jamais des
        valeurs."""
        run = lecteur(flag=1)
        G.inspect("x", run_psql=run)
        for _base, sql in run.vues:
            with self.subTest(sql=sql[:40]):
                self.assertIn("count(*)", sql)

    def test_it_never_writes(self):
        run = lecteur(flag=1)
        G.inspect("x", run_psql=run)
        for _base, sql in run.vues:
            for mot in ("DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE"):
                with self.subTest(mot=mot):
                    self.assertNotIn(mot, sql.upper())


if __name__ == "__main__":
    unittest.main()
