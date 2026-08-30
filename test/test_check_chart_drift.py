#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une montée de version ajoute au référentiel comptable.

Mesuré sur une migration 12 → 18 réelle, entre les deux derniers paliers :

    comptes    96 → 427        taxes           32 → 64
    groupes     0 → 168        positions       14 → 28

Le script de migration de `l10n_ca` recharge le plan `ca_2023` sans
`force_create=False` ; les codes du client ne recouvrent le gabarit que
sur 15 des 341, et les 326 autres sont créés. Rien n'est détruit — mais
les 168 groupes reclassent les comptes du client par PRÉFIXE de code, et
un compte fournisseurs de 1067 écritures se retrouve sous « Residential
Mortgage Loans ».

Ce qui se teste ici n'est pas le comptage — psql le fait — mais le
JUGEMENT : un compte absolu ne dit rien (un plan peut légitimement porter
mille comptes), seul l'écart entre deux paliers de la même migration se
juge. Et la comparaison doit rester muette quand rien n'a bougé, sinon
personne ne la lira deux fois.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from script.analyse import check_chart_drift as drift  # noqa: E402
from script.analyse import lib_analyse  # noqa: E402


class Base(unittest.TestCase):
    """psql bouchonné : chaque base rend les comptes qu'on lui prête."""

    def setUp(self):
        self.vues = []
        self.ancien = lib_analyse.run_psql
        self.addCleanup(setattr, lib_analyse, "run_psql", self.ancien)
        self.tables = {}
        self.sans_ecriture = (0, 0)
        self.homonymes = 0
        self.reclasses = 0
        lib_analyse.run_psql = self.repondre

    def poser(self, base, **compteurs):
        self.tables[base] = compteurs

    def repondre(self, database, sql, **kwargs):
        self.vues.append((database, sql))
        compteurs = self.tables.get(database, {})
        if "to_regclass" in sql and "count(*)" not in sql:
            table = sql.split("public.")[1].split("'")[0]
            return "true" if table in compteurs else "false"
        if "account_move_line l WHERE l.account_id" in sql:
            total, vides = self.sans_ecriture
            return '[{"total": %d, "sans_ecriture": %d}]' % (total, vides)
        if "HAVING count(*) > 1" in sql:
            return str(self.homonymes)
        if "code_prefix_start" in sql:
            return str(self.reclasses)
        for table, valeur in compteurs.items():
            if f"FROM {table};" in sql:
                return str(valeur)
        return ""


class TestWhatItCompares(Base):
    def test_it_reads_both_steps(self):
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=427)
        drift.inspect("apres", "avant")
        bases = {base for base, _sql in self.vues}
        self.assertEqual({"avant", "apres"}, bases)

    def test_a_table_that_does_not_exist_is_not_a_zero(self):
        # Sans le module account, la table manque : dire « 0 → 0 » ferait
        # croire à une mesure, et « 0 → 400 » à une explosion.
        self.poser("avant")
        self.poser("apres", account_account=427)
        rapport = drift.inspect("apres", "avant")
        ligne = [x for x in rapport["tables"] if x["key"] == "account"][0]
        self.assertIsNone(ligne["before"])
        self.assertIsNone(ligne["delta"])

    def test_every_declared_table_is_measured(self):
        self.poser("avant", account_account=1)
        self.poser("apres", account_account=1)
        rapport = drift.inspect("apres", "avant")
        self.assertEqual(
            {e["key"] for e in drift.TABLES},
            {x["key"] for x in rapport["tables"]},
        )


class TestWhatItJudges(Base):
    def rapport(self, avant, apres):
        self.poser("avant", **avant)
        self.poser("apres", **apres)
        return drift.inspect("apres", "avant")

    def test_nothing_added_is_nothing_to_report(self):
        rapport = self.rapport(
            {"account_account": 96}, {"account_account": 96}
        )
        self.assertEqual([], drift.judge(rapport))

    def test_a_chart_that_quadruples_is_a_finding(self):
        rapport = self.rapport(
            {"account_account": 96}, {"account_account": 427}
        )
        trouve = drift.judge(rapport)
        self.assertEqual(1, len(trouve))
        self.assertEqual(331, trouve[0][1]["delta"])

    def test_a_chart_that_SHRINKS_is_not_reported_here(self):
        # Ce n'est pas le sujet de cet outil, et le dire ferait deux
        # constats pour deux causes différentes sous un seul nom.
        rapport = self.rapport(
            {"account_account": 427}, {"account_account": 96}
        )
        self.assertEqual([], drift.judge(rapport))

    def test_groups_appearing_from_nothing_are_judged(self):
        # Zéro groupe puis cent soixante-huit : c'est la grille du gabarit,
        # et elle reclasse les comptes du client.
        rapport = self.rapport({"account_group": 0}, {"account_group": 168})
        self.assertEqual("group", drift.judge(rapport)[0][0]["key"])

    def test_gravity_wins_over_size(self):
        rapport = self.rapport(
            {"account_journal": 8, "account_account": 96},
            {"account_journal": 28, "account_account": 99},
        )
        trouve = drift.judge(rapport)
        cles = [entree["key"] for entree, _ in trouve]
        self.assertEqual("account", cles[0], "la gravite doit primer")
        self.assertEqual("journal", cles[-1])
        # Et l'écart le plus GROS est bien celui qu'on relègue.
        deltas = dict(zip(cles, [ligne["delta"] for _e, ligne in trouve]))
        self.assertGreater(deltas["journal"], deltas["account"])

    def test_at_equal_gravity_the_bigger_gap_comes_first(self):
        rapport = self.rapport(
            {"account_account": 96, "account_tax": 32},
            {"account_account": 427, "account_tax": 64},
        )
        cles = [entree["key"] for entree, _ in drift.judge(rapport)]
        self.assertEqual(["account", "tax"], cles)

    def test_every_entry_says_why_it_matters(self):
        for entree in drift.TABLES:
            self.assertTrue(entree["why"].strip(), entree["key"])
            self.assertIn(entree["gravity"], ("broken", "watch"))


class TestTheReport(Base):
    def test_it_names_both_steps(self):
        self.poser("base_upgrade_17", account_account=96)
        self.poser("base_upgrade_18", account_account=427)
        rapport = drift.inspect("base_upgrade_18", "base_upgrade_17")
        texte = drift.render(rapport, colour=False)
        self.assertIn("base_upgrade_17", texte)
        self.assertIn("base_upgrade_18", texte)

    def test_it_shows_the_before_and_the_after_not_just_the_delta(self):
        # « +331 » seul ne dit pas si l'on part de 96 ou de 4000.
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=427)
        texte = drift.render(drift.inspect("apres", "avant"), colour=False)
        self.assertIn("+331", texte)
        self.assertIn("96", texte)
        self.assertIn("427", texte)

    def test_a_quiet_migration_says_so_and_stops(self):
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=96)
        texte = drift.render(drift.inspect("apres", "avant"), colour=False)
        self.assertIn(
            drift.t("Nothing was added to the reference data."), texte
        )
        self.assertNotIn("❌", texte)

    def test_it_points_at_the_replay_not_at_surgery(self):
        # La clé naturelle de suppression attrape aussi des comptes du
        # client, et douze des ajoutés sont accrochés en SET NULL.
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=427)
        texte = drift.render(drift.inspect("apres", "avant"), colour=False)
        self.assertIn(
            drift.t("Replay the step with the fix; do not operate the"),
            texte,
        )

    def test_the_shape_is_shown_when_there_is_something_to_show(self):
        self.sans_ecriture = (427, 404)
        self.homonymes = 15
        self.reclasses = 422
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=427, account_group=168)
        texte = drift.render(drift.inspect("apres", "avant"), colour=False)
        self.assertIn("404", texte)
        self.assertIn("422", texte)


class TestFindingThePreviousStep(unittest.TestCase):
    """Le palier précédent se LIT dans la chaîne, il ne se devine pas."""

    def chaine(self):
        return {
            "config_database_name": "base",
            "target_odoo_version": "18.0",
            "state_4_upgrade_odoo_lst": [1, 2, 3, 4, 5, 6],
        }

    def test_it_reads_the_chain_the_migration_wrote(self):
        self.assertEqual(
            "base_upgrade_17",
            drift.previous_database("base_upgrade_18", self.chaine()),
        )

    def test_the_first_step_has_no_predecessor(self):
        # La base de DÉPART ne porte pas de suffixe : lui retrancher 1
        # donnerait un nom qui n'existe pas.
        self.assertIsNone(drift.previous_database("base", self.chaine()))

    def test_a_database_outside_the_chain_is_not_guessed(self):
        self.assertIsNone(
            drift.previous_database("une_autre_base", self.chaine())
        )


class TestTheCommand(Base):
    def lancer(self, argv):
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = drift.main(argv)
        return code, tampon.getvalue()

    def setUp(self):
        super().setUp()
        self.ancien_require = lib_analyse.require_odoo_database
        self.addCleanup(
            setattr, lib_analyse, "require_odoo_database", self.ancien_require
        )
        lib_analyse.require_odoo_database = lambda *a, **k: None

    def test_without_a_previous_step_it_is_a_tool_failure(self):
        # Sortir 0 laisserait croire que la comparaison a eu lieu.
        ancien = drift.previous_database
        drift.previous_database = lambda *a, **k: None
        self.addCleanup(setattr, drift, "previous_database", ancien)
        code, _ = self.lancer(["-d", "base_upgrade_18"])
        self.assertEqual(2, code)

    def test_no_drift_exits_zero(self):
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=96)
        code, _ = self.lancer(
            ["-d", "apres", "--before", "avant", "--no-color"]
        )
        self.assertEqual(0, code)

    def test_drift_exits_one(self):
        # 1 = des trouvailles, la convention des outils du dépôt.
        self.poser("avant", account_account=96)
        self.poser("apres", account_account=427)
        code, _ = self.lancer(
            ["-d", "apres", "--before", "avant", "--no-color"]
        )
        self.assertEqual(1, code)

    def test_the_json_carries_both_counts(self):
        import json

        self.poser("avant", account_account=96)
        self.poser("apres", account_account=427)
        _code, texte = self.lancer(
            ["-d", "apres", "--before", "avant", "--json"]
        )
        dct = json.loads(texte)
        ligne = [x for x in dct["tables"] if x["key"] == "account"][0]
        self.assertEqual(96, ligne["before"])
        self.assertEqual(427, ligne["after"])
        self.assertEqual(331, ligne["delta"])


class TestItNeverWrites(unittest.TestCase):
    """On compare deux bases de palier : l'une d'elles est parfois la
    seule copie d'un état."""

    def test_no_statement_of_the_tool_can_write(self):
        """Sur le CODE, jamais sur la prose.

        Les docstrings de l'outil expliquent justement pourquoi il ne
        faut pas opérer la base — « accrochés en ON DELETE SET NULL » —
        et une garde qui lit le texte échoue sur le texte qui l'explique.
        """
        import ast
        import inspect

        arbre = ast.parse(inspect.getsource(drift))
        for noeud in ast.walk(arbre):
            if isinstance(
                noeud, (ast.Module, ast.FunctionDef, ast.ClassDef)
            ) and ast.get_docstring(noeud):
                noeud.body = noeud.body[1:]
        code = ast.unparse(arbre).upper()
        for interdit in ("UPDATE ", "DELETE ", "INSERT ", "DROP ", "ALTER "):
            self.assertNotIn(interdit, code, interdit)

    def test_it_only_ever_selects(self):
        import ast
        import inspect

        arbre = ast.parse(inspect.getsource(drift))
        requetes = [
            n.value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and "FROM " in n.value.upper()
        ]
        self.assertTrue(requetes)
        for requete in requetes:
            self.assertTrue(
                requete.upper().lstrip().startswith("SELECT"), requete[:40]
            )


if __name__ == "__main__":
    unittest.main()
