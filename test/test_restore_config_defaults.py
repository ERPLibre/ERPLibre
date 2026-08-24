#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les réglages qu'Odoo ne recrée qu'à des moments qu'une migration évite.

Deux enregistrements ont cessé d'être LIVRÉS en données pour devenir le
produit d'un geste — créer une société, cocher une case, charger un plan
comptable. Une migration n'en fait aucun : le nettoyage des orphelins les
emporte et rien ne les remet.

Mesuré sur une chaîne 12 → 18 réelle : 1 liste de prix en 16, 0 en 17,
alors que le groupe compte six membres ; 1 modèle de rapprochement en 12,
0 dès la 13, pour trois journaux de trésorerie.

Ce que l'outil doit surtout savoir faire, c'est SE TAIRE : sans le groupe
des listes de prix, sans journal de trésorerie, ou sur une base qui n'a
ni vente ni comptabilité, l'absence est normale et le dire serait du
bruit qu'on apprendrait à ignorer.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo.migration import restore_config_defaults as conf  # noqa: E402


def rapport(**extra):
    base = {
        "dry_run": True,
        "companies": 1,
        "pricelist_before": 0,
        "pricelist_after": 0,
        "pricelist_group": True,
        "reconcile_before": 0,
        "reconcile_after": 0,
        "cash_journals": 3,
        "charts": ["ca_2023"],
    }
    base.update(extra)
    return base


class TestWhenAPricelistIsReallyMissing(unittest.TestCase):
    def test_none_and_the_feature_is_on(self):
        self.assertTrue(conf.pricelist_missing(rapport()))

    def test_the_feature_is_off_so_the_absence_is_normal(self):
        # Sans le groupe, le menu n'existe pas : signaler l'absence
        # enverrait réparer ce que personne n'utilise.
        self.assertFalse(
            conf.pricelist_missing(rapport(pricelist_group=False))
        )

    def test_there_is_already_one(self):
        self.assertFalse(conf.pricelist_missing(rapport(pricelist_before=1)))

    def test_the_module_is_not_installed_at_all(self):
        self.assertFalse(
            conf.pricelist_missing(rapport(pricelist_absent=True))
        )


class TestWhenAReconcileModelIsReallyMissing(unittest.TestCase):
    def test_none_and_there_are_journals_to_match(self):
        self.assertTrue(conf.reconcile_missing(rapport()))

    def test_no_cash_journal_so_nothing_to_match(self):
        # Créer des modèles là serait du bruit dans un menu qu'on
        # n'ouvre pas.
        self.assertFalse(conf.reconcile_missing(rapport(cash_journals=0)))

    def test_there_are_already_some(self):
        self.assertFalse(conf.reconcile_missing(rapport(reconcile_before=4)))

    def test_accounting_is_not_installed(self):
        self.assertFalse(
            conf.reconcile_missing(rapport(reconcile_absent=True))
        )


class TestJudgingBeforeAndAfter(unittest.TestCase):
    """Le compte d'AVANT reste à zéro pour l'éternité.

    Juger dessus après une réparation réussie conclurait toujours « il en
    manque encore ». C'est le compte d'APRÈS qui dit si le geste a pris.
    """

    def test_before_the_repair_both_are_missing(self):
        self.assertEqual(["pricelist", "reconcile"], conf.findings(rapport()))

    def test_after_a_successful_repair_nothing_is_missing(self):
        plein = rapport(pricelist_after=1, reconcile_after=4)
        self.assertEqual([], conf.findings(plein, apres=True))
        # …et le compte d'avant, lui, dit toujours qu'il manquait.
        self.assertEqual(2, len(conf.findings(plein)))

    def test_a_half_repair_is_reported(self):
        moitie = rapport(pricelist_after=1, reconcile_after=0)
        self.assertEqual(["reconcile"], conf.findings(moitie, apres=True))


class TestTheReport(unittest.TestCase):
    def test_a_healthy_database_says_so(self):
        sain = rapport(pricelist_before=1, reconcile_before=4)
        texte = "\n".join(conf.render(sain, True))
        self.assertIn("✅", texte)

    def test_it_says_what_breaks_for_a_user_not_what_is_missing(self):
        # « 0 liste de prix » ne dit rien à personne ; « tout devis
        # s'ouvre sans liste » se comprend sans connaître le modèle.
        #
        # On demande la MÊME traduction que le code : comparer à un mot
        # anglais en dur fait tomber le test dès qu'on traduit, ce qui
        # m'est arrivé sur celui-ci.
        texte = "\n".join(conf.render(rapport(), True))
        self.assertIn(
            conf.t("Every quotation opens without one: raw price, no rule."),
            texte,
        )
        self.assertIn(
            conf.t("Every statement line is matched by hand."), texte
        )

    def test_it_counts_the_journals_it_found(self):
        texte = "\n".join(conf.render(rapport(cash_journals=3), True))
        self.assertIn("3", texte)

    def test_the_dry_run_offers_the_flag(self):
        self.assertIn("--apply", "\n".join(conf.render(rapport(), True)))

    def test_after_applying_it_shows_the_movement(self):
        # Un rapport qui répète « il en manquait » sans dire ce qui a été
        # fait laisse rouvrir l'outil pour savoir.
        fait = rapport(pricelist_after=1, reconcile_after=4)
        texte = "\n".join(conf.render(fait, False))
        self.assertIn("0 → 1", texte)
        self.assertIn("0 → 4", texte)
        self.assertNotIn("--apply", texte)


class TestTheOrmScript(unittest.TestCase):
    """Le script poussé dans le shell doit être du Python valide."""

    def test_both_shapes_compile(self):
        for sec in (True, False):
            with self.subTest(dry=sec):
                compile(conf.build_script(sec), "script", "exec")

    def test_the_dry_run_never_writes(self):
        sec = conf.build_script(True)
        self.assertIn("DRY = True", sec)

    def test_applying_commits_each_repair(self):
        # Le shell d'Odoo annule en sortant : sans commit, la réparation
        # s'évapore et l'outil annonce une réussite qui n'a rien laissé.
        #
        # UN par réparation, et l'on compte : chercher « il y a un
        # commit » laissait retirer celui du rapprochement sans que rien
        # ne le dise — l'autre le masquait. Mesuré.
        vif = conf.build_script(False)
        self.assertIn("DRY = False", vif)
        self.assertEqual(2, vif.count("env.cr.commit()"), vif)

    def test_each_branch_has_its_own_commit(self):
        vif = conf.build_script(False)
        prix = vif[vif.index("_activate_or_create_pricelists") :]
        prix = prix[: prix.index("account.reconcile.model")]
        self.assertIn("env.cr.commit()", prix)
        reco = vif[vif.index("_get_account_reconcile_model") :]
        self.assertIn("env.cr.commit()", reco)

    def test_it_calls_odoo_rather_than_inventing_records(self):
        vif = conf.build_script(False)
        self.assertIn("_activate_or_create_pricelists", vif)
        self.assertIn("_get_account_reconcile_model", vif)
        self.assertIn("_load_data", vif)

    def test_it_lets_odoo_skip_what_already_exists(self):
        # `ignore_duplicates` est ce qui rend l'outil rejouable ; sans
        # lui, une seconde passe doublerait les modèles.
        self.assertIn("ignore_duplicates=True", conf.build_script(False))

    def test_it_uses_the_sentinels_run_shell_imposes(self):
        # En poser d'autres ferait lire un rapport vide.
        vif = conf.build_script(False)
        self.assertIn(conf.DEBUT, vif)
        self.assertIn(conf.FIN, vif)


if __name__ == "__main__":
    unittest.main()
