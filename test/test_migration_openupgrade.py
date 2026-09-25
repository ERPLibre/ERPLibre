#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La migration sait-elle quelles versions ont un OpenUpgrade ?

Chaque étape vers la version N exécute OpenUpgrade de la branche N, que
déclare manifest/git_manifest_odooN.0_dev.xml. OCA ne couvre une version
qu'après sa sortie : la cible est proposée quand même, la migration prévient
dès le choix, et s'arrête avant l'étape plutôt que de lancer un chemin vide.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo.todo_upgrade import (  # noqa: E402
    TodoUpgrade,
    http_off_option,
    split_removable,
    odoo_tree_layout,
    openupgrade_declared,
)

AVEC = """<manifest>
    <project name="OpenUpgrade.git" revision="19.0"
        path="odoo19.0/OCA_OpenUpgrade" remote="OCA" />
</manifest>
"""
SANS = """<manifest>
    <remote name="OCA" fetch="https://github.com/OCA/" />
</manifest>
"""


class TestOpenUpgradeDeclare(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name)
        (self.racine / "manifest").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _manifeste(self, version, contenu):
        (
            self.racine / "manifest" / f"git_manifest_odoo{version}.0_dev.xml"
        ).write_text(contenu)

    def test_une_branche_declaree(self):
        self._manifeste(19, AVEC)
        self.assertTrue(openupgrade_declared(19, racine=self.racine))

    def test_un_manifeste_sans_openupgrade(self):
        self._manifeste(20, SANS)
        self.assertFalse(openupgrade_declared(20, racine=self.racine))

    def test_une_version_sans_manifeste(self):
        self.assertFalse(openupgrade_declared(21, racine=self.racine))

    def test_la_branche_d_une_autre_version_ne_compte_pas(self):
        """Le chemin porte la version : un OpenUpgrade 19 ne sert pas 20."""
        self._manifeste(20, AVEC)
        self.assertFalse(openupgrade_declared(20, racine=self.racine))

    def test_les_manifestes_du_depot(self):
        """10 à 19 ont leur OpenUpgrade ; 20 pas encore."""
        for version in range(10, 20):
            with self.subTest(version=version):
                self.assertTrue(openupgrade_declared(version, racine=RACINE))


class TestLaCibleEstInstallee(unittest.TestCase):
    def test_la_plage_d_installation_comprend_la_cible(self):
        """La dernière étape bascule sur la cible : elle doit être installée."""
        source = (RACINE / "script/todo/todo_upgrade.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("range(start_version, end_version + 1)", source)


class TestLOdooOrdinaireNeVoitPlusOpenUpgrade(unittest.TestCase):
    """Jusqu'à la 13, OpenUpgrade est un Odoo complet : son « base » dans
    l'addons_path fait échouer l'Odoo ordinaire sur « odoo.openupgrade ».
    La configuration sans OpenUpgrade doit donc précéder la mise à jour de
    tous les modules, pas la suivre."""

    def test_la_configuration_est_refaite_avant_la_mise_a_jour(self):
        source = (RACINE / "script/todo/todo_upgrade.py").read_text(
            encoding="utf-8"
        )
        mise_a_jour = source.index(
            'f"./script/addons/update_addons_all.sh {database_name_upgrade}"'
        )
        sans_openupgrade = source.rindex(
            "git_repo_update_group.py && ./script/generate_config.sh",
            0,
            mise_a_jour,
        )
        # Aucune autre génération de configuration entre les deux.
        self.assertNotIn(
            "generate_config.sh", source[sans_openupgrade + 60 : mise_a_jour]
        )


class TestLArbreDOpenUpgrade(unittest.TestCase):
    """Jusqu'à 13, OpenUpgrade est un Odoo complet : son lanceur et son cœur
    d'addons suivent le nom du paquet, openerp en 9.0 et avant."""

    def test_un_arbre_openerp_se_lance_par_openerp_server(self):
        with tempfile.TemporaryDirectory() as racine:
            os.mkdir(os.path.join(racine, "openerp"))
            self.assertEqual(
                (
                    os.path.join(racine, "openerp-server"),
                    os.path.join(racine, "openerp", "addons"),
                ),
                odoo_tree_layout(racine),
            )

    def test_un_arbre_odoo_se_lance_par_odoo_bin(self):
        with tempfile.TemporaryDirectory() as racine:
            os.mkdir(os.path.join(racine, "odoo"))
            self.assertEqual(
                (
                    os.path.join(racine, "odoo-bin"),
                    os.path.join(racine, "odoo", "addons"),
                ),
                odoo_tree_layout(racine),
            )

    def test_le_http_s_eteint_selon_la_version(self):
        """OpenUpgrade 9.0 et 10.0 ne connaissent que --no-xmlrpc."""
        self.assertEqual(
            ["--no-xmlrpc", "--no-xmlrpc", "--no-http", "--no-http"],
            [http_off_option(v) for v in (9, 10, 11, 13)],
        )


class TestLesModulesFusionnesSelonOpenUpgrade(unittest.TestCase):
    """merged_modules est une liste de couples jusqu'à OpenUpgrade 10.0, un
    dictionnaire depuis 11.0 : .get() sur la liste arrêtait la migration au
    début du saut vers 9 ou vers 10."""

    def renommer(self, apriori, modules):
        from script.todo.todo_upgrade import TodoUpgrade

        with tempfile.TemporaryDirectory() as racine:
            chemin = os.path.join(racine, "apriori.py")
            with open(chemin, "w") as f:
                f.write(apriori)
            upgrade = TodoUpgrade.__new__(TodoUpgrade)
            upgrade.todo_upgrade_execute = lambda *a, **k: (0, "", [chemin])
            return sorted(upgrade.get_rename_module(list(modules), 9))

    def test_une_liste_de_couples_est_lue(self):
        apriori = (
            "renamed_modules = {'portal_claim': 'website_crm_claim'}\n"
            "merged_modules = [('account_chart', 'account')]\n"
        )
        self.assertEqual(
            ["account", "sale", "website_crm_claim"],
            self.renommer(apriori, ["account_chart", "portal_claim", "sale"]),
        )

    def test_un_dictionnaire_aussi(self):
        apriori = "merged_modules = {'account_chart': 'account'}\n"
        self.assertEqual(
            ["account"], self.renommer(apriori, ["account_chart"])
        )


class TestUnModuleManquantNEmportePasSesDependants(unittest.TestCase):
    """En Odoo 8, account dépend d'edi, retiré en 9 : désinstaller edi avant
    le saut emportait account, sale et purchase, et leurs données."""

    def test_un_dependant_qui_survit_garde_le_module(self):
        proposables, gardes = split_removable(
            ["edi", "share", "vieux_oca"],
            {
                "edi": ["account", "sale"],
                "share": ["portal"],
                "vieux_oca": [],
            },
        )
        self.assertEqual(["vieux_oca"], proposables)
        self.assertEqual(
            {"edi": ["account", "sale"], "share": ["portal"]}, gardes
        )

    def test_des_dependants_eux_memes_manquants_n_empechent_rien(self):
        proposables, gardes = split_removable(
            ["module_a", "module_b"],
            {"module_a": ["module_b"], "module_b": []},
        )
        self.assertEqual(["module_a", "module_b"], proposables)
        self.assertEqual({}, gardes)

    def test_des_dependants_inconnus_gardent_le_module(self):
        proposables, gardes = split_removable(["edi"], {"edi": None})
        self.assertEqual([], proposables)
        self.assertEqual({"edi": None}, gardes)


class TestLaBasculeSeRefaitALaReprise(unittest.TestCase):
    """OpenUpgrade tourne dans l'Odoo de la version visée.

    Une reprise rejoue l'étape 0, qui rebascule sur la version de la
    sauvegarde : la bascule notée faite doit se refaire quand même.
    """

    def montee(self, lst_switch_odoo):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.appels = []
        upgrade.switch_odoo = upgrade.appels.append
        upgrade.write_config = lambda: upgrade.appels.append("écrit")
        with open(os.devnull, "w") as muet:
            sortie, sys.stdout = sys.stdout, muet
            try:
                upgrade.switch_odoo_for_bump(lst_switch_odoo, 0, 9)
            finally:
                sys.stdout = sortie
        return upgrade

    def test_une_bascule_deja_notee_se_refait(self):
        upgrade = self.montee([True, False])
        self.assertEqual(upgrade.appels, [9])

    def test_une_premiere_bascule_est_notee(self):
        lst_switch_odoo = [False, False]
        upgrade = self.montee(lst_switch_odoo)
        self.assertEqual(upgrade.appels, [9, "écrit"])
        self.assertEqual(lst_switch_odoo, [True, False])
        self.assertEqual(
            upgrade.dct_progression["state_4_switch_odoo_lst"], [True, False]
        )


class TestUnModuleDejaRetireNEstPlusPropose(unittest.TestCase):
    """La liste d'un palier hérite du précédent, pas de la base."""

    def filtrer(self, presents, manquants):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.still_installed = lambda base, lst: presents
        return upgrade.missing_still_in_base("base", manquants)

    def test_un_module_purge_de_la_base_disparait(self):
        self.assertEqual(
            ["vieux_oca"], self.filtrer(["vieux_oca"], ["edi", "vieux_oca"])
        )

    def test_une_base_muette_garde_toute_la_liste(self):
        self.assertEqual(
            ["edi", "vieux_oca"], self.filtrer(None, ["edi", "vieux_oca"])
        )


class TestLaListeDuPalierPartDeLaBase(unittest.TestCase):
    """Un module auto_install installé en route doit être porté aussi."""

    def liste(self, base, precedente):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.modules_of_database = lambda nom: base
        upgrade.get_rename_module = lambda lst, version: sorted(lst)
        return upgrade.modules_for_bump("base", precedente, 19)

    def test_un_module_installe_en_route_est_dans_la_liste(self):
        self.assertEqual(
            ["module_auto", "sale"],
            self.liste(["sale", "module_auto"], ["sale"]),
        )

    def test_une_base_muette_garde_la_liste_precedente(self):
        self.assertEqual(["sale"], self.liste(None, ["sale"]))


class TestUnModuleRetireEstOublie(unittest.TestCase):
    """La fiche d'un module désinstallé garde son auto_install : sans elle,
    rien ne le réinstalle dans une version qui n'a pas son code."""

    def oublier(self, noms, rapport=None, erreur=None):
        from script.odoo.migration import database_cleanup

        appels = []

        def run_shell(base, config, script, **kw):
            appels.append((base, script))
            if erreur:
                raise RuntimeError(erreur)
            return rapport or {"forgotten": []}

        ancien = database_cleanup.run_shell
        database_cleanup.run_shell = run_shell
        self.addCleanup(setattr, database_cleanup, "run_shell", ancien)
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        with open(os.devnull, "w") as muet:
            sortie, sys.stdout = sys.stdout, muet
            try:
                rendu = upgrade.forget_modules("base_x", noms)
            finally:
                sys.stdout = sortie
        return rendu, appels

    def test_seuls_les_noms_de_module_entrent_dans_le_script(self):
        _rendu, appels = self.oublier(["module_auto", "x' or 1=1"])
        self.assertEqual("base_x", appels[0][0])
        self.assertIn("['module_auto']", appels[0][1])
        self.assertNotIn("or 1=1", appels[0][1])

    def test_sans_module_rien_n_est_lance(self):
        rendu, appels = self.oublier([])
        self.assertEqual([], rendu)
        self.assertEqual([], appels)

    def test_le_rapport_du_shell_est_rendu(self):
        rendu, _ = self.oublier(
            ["module_auto"], rapport={"forgotten": ["module_auto"]}
        )
        self.assertEqual(["module_auto"], rendu)

    def test_un_shell_muet_rend_none(self):
        rendu, _ = self.oublier(["module_auto"], erreur="pas de rapport")
        self.assertIsNone(rendu)


if __name__ == "__main__":
    unittest.main()
