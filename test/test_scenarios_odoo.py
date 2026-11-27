#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""scenarios_odoo : le schéma des scénarios du générateur, leurs phases,
et les réécritures de config.conf et de hooks.py. Sans base ni Odoo."""

import configparser
import json
import os
import unittest

from script.test import scenarios_odoo as s

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exec(nom="scn_fictif", **cles):
    e = {
        "run_test_exec": True,
        "test_name": nom,
        "path_module_check": "./odoo99.0/addons/DepotFictif",
        "restore_db_image_name": "image_fictive",
    }
    e.update(cles)
    return e


def _commande(nom="cmd_fictive", **cles):
    e = {"run_command": True, "test_name": nom, "script": "./faux.sh"}
    e.update(cles)
    return e


def _json(*entrees):
    return json.dumps({"lst_test": list(entrees)})


class TestJsonDuDepot(unittest.TestCase):
    def test_repository_files_validate(self):
        for version in ("18.0", "12.0"):
            with self.subTest(version=version):
                chemin = s.json_par_defaut(RACINE, version)
                with open(chemin, encoding="utf-8") as fh:
                    entrees = s.charger_et_valider(fh.read())
                actives = s.selectionner(entrees)
                self.assertEqual(len(entrees), 18)
                self.assertEqual(len(actives), 11)
                phases = {e["test_name"]: e["sequence"] for e in actives}
                self.assertEqual(phases.pop("helloworld_test"), 10)
                self.assertEqual(set(phases.values()), {0})

    def test_hello_world_declares_what_it_touches_on_the_origin(self):
        with open(s.json_par_defaut(RACINE, "18.0"), encoding="utf-8") as fh:
            e = s.entree(s.charger_et_valider(fh.read()), "helloworld_test")
        self.assertTrue(
            e["script_coverage"].endswith("coverage_hello_world.sh")
        )
        self.assertTrue(
            s.chemins_origine(e)[0].endswith("code_generator_demo/hooks.py")
        )


class TestSchema(unittest.TestCase):
    def assertRefuse(self, texte, *morceaux):
        with self.assertRaises(s.SchemaInvalide) as ctx:
            s.charger_et_valider(texte)
        for morceau in morceaux:
            self.assertIn(morceau, str(ctx.exception))

    def test_a_typo_key_is_refused_naming_the_entry(self):
        self.assertRefuse(
            _json(_commande(), _exec("scn_typo", generated_path="./x")),
            "entrée 1",
            "scn_typo",
            "generated_path",
        )

    def test_a_disabled_entry_is_validated_too(self):
        self.assertRefuse(
            _json(_exec(disable=True, generated_path="./x")),
            "generated_path",
        )

    def test_missing_required_keys(self):
        cas = {
            "test_name": _exec(),
            "path_module_check": _exec(),
            "restore_db_image_name": _exec(),
            "script": _commande(),
        }
        for cle, entree in cas.items():
            with self.subTest(cle=cle):
                del entree[cle]
                self.assertRefuse(_json(entree), cle)

    def test_duplicate_names(self):
        self.assertRefuse(
            _json(_exec("double"), _commande("double")),
            "entrée 1",
            "double",
            "entrée 0",
        )

    def test_wrong_types(self):
        for cle, valeur in (
            ("sequence", True),
            ("sequence", "10"),
            ("disable", "oui"),
            ("tested_module", ""),
            ("run_in_sandbox", 1),
        ):
            with self.subTest(cle=cle, valeur=valeur):
                self.assertRefuse(_json(_exec(**{cle: valeur})), cle)

    def test_exactly_one_kind(self):
        self.assertRefuse(_json(_exec(run_command=True)), "sorte")
        sans = _exec()
        del sans["run_test_exec"]
        self.assertRefuse(_json(sans), "sorte")

    def test_a_key_of_the_other_kind_is_refused(self):
        self.assertRefuse(_json(_exec(script="./x.sh")), "script")
        self.assertRefuse(
            _json(_commande(path_module_check="./x")), "path_module_check"
        )

    def test_origin_flag_needs_files(self):
        self.assertRefuse(
            _json(_exec(file_to_restore_origin=True)), "file_to_restore"
        )

    def test_root_shape(self):
        self.assertRefuse("[]", "racine")
        self.assertRefuse('{"lst_test": []}', "lst_test")
        self.assertRefuse('{"lst_test": [], "autre": 1}', "autre")
        self.assertRefuse("{pas du json", "JSON")

    def test_defaults_and_kind_are_set(self):
        (e,) = s.charger_et_valider(_json(_exec()))
        self.assertEqual(e["sequence"], 0)
        self.assertIs(e["disable"], False)
        self.assertIs(e["run_in_sandbox"], True)
        self.assertEqual(e["sorte"], "run_test_exec")


class TestSelection(unittest.TestCase):
    def setUp(self):
        self.entrees = s.charger_et_valider(
            _json(
                _exec("alpha_test"),
                _exec("alpha_test_long"),
                _exec("beta_test", sequence=5),
                _exec("gamma_test", disable=True),
                _commande("delta", sequence=10),
            )
        )

    def noms(self, choisis):
        return [e["test_name"] for e in choisis]

    def test_all_active_by_default(self):
        self.assertEqual(
            self.noms(s.selectionner(self.entrees)),
            ["alpha_test", "alpha_test_long", "beta_test", "delta"],
        )

    def test_exact_names(self):
        self.assertEqual(
            self.noms(s.selectionner(self.entrees, noms=["alpha_test"])),
            ["alpha_test"],
        )

    def test_unknown_or_disabled_name(self):
        with self.assertRaisesRegex(ValueError, "inconnu"):
            s.selectionner(self.entrees, noms=["omega"])
        with self.assertRaisesRegex(ValueError, "désactivé"):
            s.selectionner(self.entrees, noms=["gamma_test"])

    def test_k_is_a_substring_or_a_pattern(self):
        self.assertEqual(
            self.noms(s.selectionner(self.entrees, motifs=["alpha"])),
            ["alpha_test", "alpha_test_long"],
        )
        self.assertEqual(
            self.noms(s.selectionner(self.entrees, motifs=["*_test"])),
            ["alpha_test", "beta_test"],
        )

    def test_failed_set_and_union(self):
        self.assertEqual(
            self.noms(
                s.selectionner(
                    self.entrees, noms=["delta"], echecs={"beta_test"}
                )
            ),
            ["beta_test", "delta"],
        )
        self.assertEqual(s.selectionner(self.entrees, echecs=set()), [])

    def test_elements_carry_the_phase(self):
        elements = s.elements(s.selectionner(self.entrees))
        self.assertEqual(
            [(el.nom, el.phase) for el in elements],
            [
                ("alpha_test", 0),
                ("alpha_test_long", 0),
                ("beta_test", 5),
                ("delta", 10),
            ],
        )

    def test_default_jobs_is_the_largest_phase(self):
        self.assertEqual(s.jobs_par_defaut(s.selectionner(self.entrees)), 2)
        self.assertEqual(s.jobs_par_defaut([]), 1)


class TestCheminsOrigine(unittest.TestCase):
    def test_declared_origin_paths(self):
        (e,) = s.charger_et_valider(
            _json(
                _exec(
                    file_to_restore="mod_a/i18n/a.pot,mod_a/i18n/fr.po",
                    file_to_restore_origin=True,
                )
            )
        )
        self.assertEqual(
            s.chemins_origine(e),
            [
                "odoo99.0/addons/DepotFictif/mod_a/i18n/a.pot",
                "odoo99.0/addons/DepotFictif/mod_a/i18n/fr.po",
            ],
        )

    def test_sandbox_restores_are_not_origin_paths(self):
        (e,) = s.charger_et_valider(_json(_exec(file_to_restore="mod_a/x.po")))
        self.assertEqual(s.chemins_origine(e), [])


CONFIG = """[options]
addons_path = /fictif/odoo99.0/addons/DepotA,/fictif/odoo99.0/addons/DepotFictif,/fictif/odoo99.0/addons/DepotFictif-bis,/fictif/odoo99.0/addons/DepotB
admin_passwd = fictif
db_user = role_fictif
"""


class TestUpdateConfig(unittest.TestCase):
    def chemins(self, texte):
        lecteur = configparser.ConfigParser()
        lecteur.read_string(texte)
        return lecteur["options"]["addons_path"].split(","), lecteur

    def test_origin_replaced_by_the_copies(self):
        texte = s.update_config(
            CONFIG,
            ["./odoo99.0/addons/DepotFictif", "./odoo99.0/addons/DepotB"],
            [
                "/bac/w/odoo99.0/addons/DepotFictif",
                "/bac/w/odoo99.0/addons/DepotB",
            ],
        )
        chemins, lecteur = self.chemins(texte)
        self.assertEqual(
            chemins,
            [
                "/bac/w/odoo99.0/addons/DepotB",
                "/bac/w/odoo99.0/addons/DepotFictif",
                "/fictif/odoo99.0/addons/DepotA",
                "/fictif/odoo99.0/addons/DepotFictif-bis",
            ],
        )
        self.assertEqual(lecteur["options"]["db_user"], "role_fictif")

    def test_only_the_first_match_is_removed(self):
        config = CONFIG.replace("DepotB", "DepotFictif")
        chemins, _ = self.chemins(
            s.update_config(config, ["odoo99.0/addons/DepotFictif"], [])
        )
        self.assertEqual(
            chemins.count("/fictif/odoo99.0/addons/DepotFictif"), 1
        )

    def test_a_trailing_module_is_cut(self):
        chemins, _ = self.chemins(
            s.update_config(
                CONFIG,
                ["./odoo99.0/addons/DepotFictif/mod_genere"],
                ["/bac/w/odoo99.0/addons/DepotFictif/mod_genere"],
                module="mod_genere",
            )
        )
        self.assertEqual(chemins[0], "/bac/w/odoo99.0/addons/DepotFictif")
        self.assertNotIn("/fictif/odoo99.0/addons/DepotFictif", chemins)


HOOK_COMMENTE = """import os

MODULE_NAME = "mod_genere"


def post_init_hook(env):
    # path_module_generate = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))

    short_name = MODULE_NAME.replace("_", " ").title()
    value = {
        # "path_sync_code": path_module_generate,
        "name": MODULE_NAME,
    }
"""

HOOK_COMMENTE_ATTENDU = """import os

MODULE_NAME = "mod_genere"


def post_init_hook(env):
    path_module_generate = "/bac/w/depot"

    short_name = MODULE_NAME.replace("_", " ").title()
    value = {
        "path_sync_code": path_module_generate,
        "name": MODULE_NAME,
    }
"""

HOOK_TEMPLATE = """def post_init_hook(env):
    # Le chemin du fichier
    # path_module_generate = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
    template_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", MODULE_NAME)
    )

    suite = 1
"""

HOOK_TEMPLATE_ATTENDU = """def post_init_hook(env):
    # Le chemin du fichier
    path_module_generate = "/bac/w/depot"
    template_dir = "/bac/w/depot/" + MODULE_NAME



    suite = 1
"""

HOOK_ACTIF = """def post_init_hook(env):
        path_module_generate = os.path.dirname(__file__)
        autre = 2

    fin = 3
"""

HOOK_ACTIF_ATTENDU = """def post_init_hook(env):
        path_module_generate = "/bac/w/depot"

    fin = 3
"""


class TestReecrireHooks(unittest.TestCase):
    def test_commented_key_and_sync_code(self):
        self.assertEqual(
            s.reecrire_hooks(HOOK_COMMENTE, "/bac/w/depot"),
            HOOK_COMMENTE_ATTENDU,
        )

    def test_template_dir_is_rewritten_at_the_same_indentation(self):
        self.assertEqual(
            s.reecrire_hooks(HOOK_TEMPLATE, "/bac/w/depot"),
            HOOK_TEMPLATE_ATTENDU,
        )

    def test_active_key_up_to_the_blank_line(self):
        self.assertEqual(
            s.reecrire_hooks(HOOK_ACTIF, "/bac/w/depot"), HOOK_ACTIF_ATTENDU
        )

    def test_without_key_it_fails(self):
        with self.assertRaises(s.CleHooksAbsente):
            s.reecrire_hooks("def post_init_hook(env):\n    pass\n", "/bac")

    def test_a_repository_hook_stays_python(self):
        """Sur un hooks.py du dépôt de gabarits, s'il est présent : le
        résultat se compile et génère dans le bac."""
        depot = os.path.join(
            RACINE,
            "odoo18.0",
            "addons",
            "TechnoLibre_odoo-code-generator-template",
        )
        trouves = []
        if os.path.isdir(depot):
            for module in sorted(os.listdir(depot)):
                hook = os.path.join(depot, module, "hooks.py")
                if module.startswith("code_generator_") and os.path.exists(
                    hook
                ):
                    trouves.append(hook)
        if not trouves:
            self.skipTest("dépôt de gabarits absent de ce checkout")
        for hook in trouves[:5]:
            with self.subTest(hook=os.path.basename(os.path.dirname(hook))):
                with open(hook, encoding="utf-8") as fh:
                    source = fh.read()
                try:
                    texte = s.reecrire_hooks(source, "/bac/w/depot")
                except s.CleHooksAbsente:
                    continue
                compile(texte, hook, "exec")
                self.assertIn('path_module_generate = "/bac/w/depot"', texte)


class TestNomBase(unittest.TestCase):
    def test_prefix_length_and_uniqueness(self):
        noms = {
            s.nom_base("0a1b2c3d", "un_scenario_au_nom_vraiment_tres_long" * 3)
            for _ in range(20)
        }
        self.assertEqual(len(noms), 20)
        for nom in noms:
            self.assertTrue(nom.startswith(s.prefixe_bases("0a1b2c3d")))
            self.assertLessEqual(len(nom), 62)

    def test_the_name_is_reduced_to_safe_characters(self):
        nom = s.nom_base("0a1b2c3d", "Scénario-X", alea="0" * 12)
        self.assertEqual(nom, "test_scn_0a1b2c3d_000000000000_sc_nario_x")

    def test_run_ids(self):
        rid = s.nouveau_run_id()
        self.assertRegex(rid, r"^[0-9a-f]{8}$")
        self.assertNotEqual(rid, s.nouveau_run_id())


if __name__ == "__main__":
    unittest.main()
