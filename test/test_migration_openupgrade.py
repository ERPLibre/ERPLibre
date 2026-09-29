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
    http_off_option,
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
        self.assertEqual(["account"], self.renommer(apriori, ["account_chart"]))


if __name__ == "__main__":
    unittest.main()
