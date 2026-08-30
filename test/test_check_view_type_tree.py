#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""« tree » est d'abord un IDENTIFIANT, et rarement un type de vue.

Sur 465 occurrences du mot dans odoo18.0/addons, quatre-vingts cassent.
Le reste est un id de <record>, un <field name="name">, un env.ref(), un
nom de variable — et le noyau 18 lui-même a gardé ses anciens ids en ne
renommant que les balises : account.view_invoice_tree existe toujours.

Un détecteur qui ancre sur le mot rend quatre cents lignes fausses et ne
sera pas relancé une seconde fois. C'est donc le TRI qu'on teste ici, pas
la détection : chaque exclusion a son test, et il y en a plus que de
motifs.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from script.analyse import check_view_type_tree as arbre  # noqa: E402


class Base(unittest.TestCase):
    """Un checkout jetable : une version, un module, ce qu'on y met."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)
        self.version("18.0")
        self.addons = os.path.join(self.racine, "odoo18.0", "addons")
        os.makedirs(self.addons)

    def version(self, texte):
        with io.open(
            os.path.join(self.racine, arbre.FICHIER_VERSION),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(texte + "\n")

    def module(self, nom="essai", manifeste=None, init="from . import models"):
        chemin = os.path.join(self.addons, "depot", nom)
        os.makedirs(chemin, exist_ok=True)
        dct = {"name": nom, "version": "18.0.1.0.0", "data": []}
        dct.update(manifeste or {})
        self.ecrire(os.path.join(chemin, arbre.MANIFESTE), repr(dct))
        if init is not None:
            self.ecrire(os.path.join(chemin, "__init__.py"), init)
        return chemin

    def ecrire(self, chemin, contenu):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write(contenu)
        return chemin

    def constats(self):
        return arbre.inspect(self.racine)["findings"]

    def motifs(self):
        return sorted(c[3] for c in self.constats())


class TestTheVersionGate(Base):
    def test_below_18_nothing_is_a_defect(self):
        # `tree` y est valide, au pire déprécié en 17. Crier dessus
        # ferait rejeter le rapport en entier.
        self.assertFalse(arbre.concerne((17, 0)))
        self.assertFalse(arbre.concerne((12, 0)))

    def test_18_and_beyond_are_judged(self):
        self.assertTrue(arbre.concerne((18, 0)))
        self.assertTrue(arbre.concerne((19, 0)))

    def test_an_unreadable_version_judges_nothing(self):
        os.remove(os.path.join(self.racine, arbre.FICHIER_VERSION))
        self.assertIsNone(arbre.version_active(self.racine))
        self.assertEqual([], self.constats())

    def test_a_nonsense_version_judges_nothing(self):
        self.version("develop")
        self.assertIsNone(arbre.version_active(self.racine))


class TestTheModuleGate(Base):
    def test_a_manifest_is_read_never_executed(self):
        # Un __manifest__.py vient d'un dépôt tiers : l'exécuter pour lire
        # quatre clés donnerait la main à n'importe qui.
        chemin = self.ecrire(
            os.path.join(self.racine, "m", arbre.MANIFESTE),
            "__import__('os').system('touch /tmp/jamais')\n",
        )
        self.assertIsNone(arbre.lire_manifeste(chemin))

    def test_a_module_that_odoo_would_not_list_is_skipped(self):
        # `installable: False` : il ne peut casser ni à l'installation ni
        # à l'exécution.
        module = self.module(
            manifeste={"installable": False, "data": ["v.xml"]}
        )
        self.ecrire(
            os.path.join(module, "v.xml"),
            "<odoo><record model='ir.ui.view'><field name='arch'>"
            "<tree/></field></record></odoo>",
        )
        self.assertEqual([], self.constats())

    def test_a_module_that_is_installable_is_read(self):
        module = self.module(manifeste={"data": ["v.xml"]})
        self.ecrire(
            os.path.join(module, "v.xml"),
            "<odoo><record model='ir.ui.view'><field name='arch'>"
            "<tree/></field></record></odoo>",
        )
        self.assertEqual(["xml_balise"], self.motifs())

    def test_a_directory_without_a_manifest_is_not_a_module(self):
        os.makedirs(os.path.join(self.addons, "depot", "pas_un_module"))
        self.assertEqual([], arbre.modules(self.addons))


class TestTheLoadingGate(Base):
    def test_an_xml_the_manifest_does_not_load_is_ignored(self):
        # Personne ne le charge : il ne casse rien, et le signaler ferait
        # crier sur des brouillons laissés là.
        module = self.module(manifeste={"data": []})
        self.ecrire(
            os.path.join(module, "orphelin.xml"), "<odoo><tree/></odoo>"
        )
        self.assertEqual([], self.constats())

    def test_a_demo_file_counts_like_a_data_file(self):
        module = self.module(manifeste={"demo": ["d.xml"]})
        self.ecrire(os.path.join(module, "d.xml"), "<odoo><tree/></odoo>")
        self.assertEqual(["xml_balise"], self.motifs())

    def test_a_python_nobody_imports_is_ignored(self):
        module = self.module(init="")
        self.ecrire(
            os.path.join(module, "brouillon.py"),
            "A = [(1, 'tree')]\n",
        )
        self.assertEqual([], self.constats())

    def test_a_python_reached_through_the_init_is_read(self):
        module = self.module(init="from . import models")
        self.ecrire(os.path.join(module, "models.py"), "A = [(1, 'tree')]\n")
        self.assertEqual(["py_views"], self.motifs())

    def test_a_module_imported_for_its_function_is_still_followed(self):
        # « from .hooks import post_init_hook » importe une FONCTION ;
        # chercher post_init_hook.py manquait tous les hooks.py, et avec
        # eux vingt-sept constats réels.
        module = self.module(init="from .hooks import post_init_hook")
        self.ecrire(
            os.path.join(module, "hooks.py"),
            "def post_init_hook(env):\n"
            "    env['code.generator.view'].create({'view_type': 'tree'})\n",
        )
        self.assertEqual(["py_view_type"], self.motifs())

    def test_a_subpackage_is_walked(self):
        module = self.module(init="from . import models")
        self.ecrire(
            os.path.join(module, "models", "__init__.py"), "from . import x"
        )
        self.ecrire(
            os.path.join(module, "models", "x.py"), "A = [(1, 'tree')]\n"
        )
        self.assertEqual(["py_views"], self.motifs())

    def test_a_test_file_is_never_judged(self):
        module = self.module(init="from . import tests")
        self.ecrire(
            os.path.join(module, "tests", "__init__.py"), "from . import t"
        )
        self.ecrire(
            os.path.join(module, "tests", "t.py"), "A = [(1, 'tree')]\n"
        )
        self.assertEqual([], self.constats())


class TestTheXmlPatterns(Base):
    def vue(self, corps, manifeste=None):
        module = self.module(manifeste=manifeste or {"data": ["v.xml"]})
        self.ecrire(os.path.join(module, "v.xml"), corps)
        return self.constats()

    def test_a_tree_tag_is_caught(self):
        self.assertEqual(
            ["xml_balise"],
            [
                c[3]
                for c in self.vue(
                    "<odoo><tree><field name='a'/></tree></odoo>"
                )
            ],
        )

    def test_the_closing_tag_is_not_a_second_defect(self):
        # Elle est la moitié du même : les compter séparément double le
        # total et fait croire à deux corrections.
        self.assertEqual(1, len(self.vue("<odoo><tree/></odoo>")))

    def test_a_commented_tree_is_not_a_defect(self):
        # Aucun geste explicite : lxml ne construit pas d'élément pour le
        # contenu d'un commentaire. C'est l'argument décisif contre grep.
        self.assertEqual([], self.vue("<odoo><!-- <tree/> --></odoo>"))

    def test_a_record_id_that_contains_tree_is_not_a_defect(self):
        # Le noyau 18 a gardé account.view_invoice_tree, arch en <list>.
        self.assertEqual(
            [],
            self.vue(
                "<odoo><record id='view_invoice_tree' model='ir.ui.view'>"
                "<field name='name'>account.move.tree</field>"
                "<field name='arch' type='xml'><list/></field>"
                "</record></odoo>"
            ),
        )

    def test_a_view_mode_naming_tree_is_caught(self):
        constats = self.vue(
            "<odoo><field name='view_mode'>tree,form</field></odoo>"
        )
        self.assertEqual(["xml_view_mode"], [c[3] for c in constats])
        self.assertEqual("list,form", constats[0][5])

    def test_a_space_after_the_comma_does_not_hide_it(self):
        self.assertEqual(
            ["xml_view_mode"],
            [
                c[3]
                for c in self.vue(
                    "<odoo><field name='view_mode'>form, tree</field></odoo>"
                )
            ],
        )

    def test_a_mode_that_merely_starts_with_tree_is_not_caught(self):
        # Un substring attraperait « treemap ».
        self.assertEqual(
            [],
            self.vue(
                "<odoo><field name='view_mode'>treemap,form</field></odoo>"
            ),
        )

    def test_an_explicit_type_field_is_caught(self):
        self.assertEqual(
            ["xml_type"],
            [
                c[3]
                for c in self.vue(
                    "<odoo><field name='type'>tree</field></odoo>"
                )
            ],
        )

    def test_an_xpath_aiming_at_a_tree_is_caught(self):
        self.assertEqual(
            ["xml_xpath"],
            [
                c[3]
                for c in self.vue(
                    "<odoo><xpath expr=\"//tree/field[@name='a']\"/></odoo>"
                )
            ],
        )

    def test_an_xpath_naming_tree_inside_a_predicate_is_not_caught(self):
        self.assertEqual(
            [],
            self.vue(
                "<odoo><xpath expr=\"//list[@name='tree_view']\"/></odoo>"
            ),
        )

    def test_an_unparsable_file_is_reported_apart(self):
        # Autre cause, autre réparation : ne pas le mêler aux « tree ».
        module = self.module(manifeste={"data": ["v.xml"]})
        self.ecrire(os.path.join(module, "v.xml"), "<odoo><tree")
        rapport = arbre.inspect(self.racine)
        self.assertEqual([], rapport["findings"])
        self.assertEqual(1, len(rapport["unreadable"]))

    def test_a_file_listed_but_absent_is_reported_apart(self):
        # Il rend le module ininstallable, et cela n'a rien à voir avec
        # un type de vue.
        self.module(manifeste={"data": ["jamais_ecrit.xml"]})
        rapport = arbre.inspect(self.racine)
        self.assertEqual(1, len(rapport["missing"]))

    def test_the_line_reported_is_where_the_tag_opens(self):
        # lxml rend la ligne où la balise ouvrante FINIT ; mesuré, il
        # disait 66 quand <tree commençait à 61.
        constats = self.vue(
            "<odoo>\n<tree\n  string='x'\n  create='0'\n>\n"
            "<field name='a'/></tree>\n</odoo>"
        )
        self.assertEqual(2, constats[0][2])


class TestThePythonPatterns(Base):
    def code(self, source):
        module = self.module(init="from . import models")
        self.ecrire(os.path.join(module, "models.py"), source)
        return self.constats()

    def test_a_view_tuple_typed_tree_is_caught(self):
        self.assertEqual(
            ["py_views"],
            [
                c[3]
                for c in self.code(
                    "def f(res):\n    return [(res and res.id or False, 'tree')]\n"
                )
            ],
        )

    def test_a_pair_of_two_strings_is_defensive_code_not_a_defect(self):
        # ('list', 'tree') couvre les deux noms de balise ; en 18 seule la
        # branche list se produit, l'entrée tree reste morte.
        self.assertEqual([], self.code("A = ('list', 'tree')\n"))

    def test_the_variable_name_decides_nothing(self):
        # Le piège le plus tentant : les deux formes sont à quelques
        # lignes d'écart dans le même dépôt et ne diffèrent que par le
        # littéral. Odoo ne lit pas les noms de variables.
        self.assertEqual([], self.code("tree_view = [(1, 'list')]\n"))

    def test_a_dict_view_mode_is_caught(self):
        self.assertEqual(
            ["py_view_mode"],
            [c[3] for c in self.code("A = {'view_mode': 'tree,form'}\n")],
        )

    def test_a_view_mode_without_the_action_type_is_still_caught(self):
        # Plusieurs actions réelles omettent la clé `type` et sont
        # pourtant renvoyées telles quelles au client.
        self.assertEqual(
            ["py_view_mode"],
            [
                c[3]
                for c in self.code(
                    "A = {'name': 'x', 'view_mode': 'form,tree,kanban'}\n"
                )
            ],
        )

    def test_view_type_on_an_act_window_is_a_harmless_leftover(self):
        # Vestige d'Odoo 12 : la 18 ne lit que view_mode / views / view_ids
        # et ignore la clé surnuméraire sans bruit.
        self.assertEqual(
            [],
            self.code(
                "A = {'type': 'ir.actions.act_window', 'view_type': 'tree'}\n"
            ),
        )

    def test_view_type_anywhere_else_is_a_live_selection(self):
        # code.generator.view.view_type ne propose plus que « list » :
        # la valeur tree lève au post_init_hook.
        self.assertEqual(
            ["py_view_type"],
            [
                c[3]
                for c in self.code(
                    "A = {'view_type': 'tree', 'view_name': 'x'}\n"
                )
            ],
        )

    def test_a_comparison_against_tree_is_not_a_defect(self):
        # Une comparaison ne fabrique jamais un type de vue : au pire du
        # code mort. La compter gonflerait le rapport de lignes que
        # personne ne peut réparer isolément.
        self.assertEqual(
            [],
            self.code(
                "def f(v):\n    return v != 'tree' and v in ('list', 'tree')\n"
            ),
        )

    def test_a_tree_used_as_a_data_structure_is_not_a_defect(self):
        self.assertEqual(
            [],
            self.code(
                "import lxml.etree as etree\n"
                "def f(d):\n    return d['tree'], etree.tostring\n"
            ),
        )

    def test_the_unix_command_named_tree_is_not_a_defect(self):
        self.assertEqual([], self.code("cmd = 'tree'\nPKGS = ['tree']\n"))

    def test_a_file_that_does_not_parse_is_reported_apart(self):
        module = self.module(init="from . import models")
        self.ecrire(os.path.join(module, "models.py"), "def f(:\n")
        rapport = arbre.inspect(self.racine)
        self.assertEqual([], rapport["findings"])
        self.assertEqual(1, len(rapport["unreadable"]))


class TestTheCommand(Base):
    def lancer(self, argv):
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = arbre.main(argv)
        return code, tampon.getvalue()

    def test_a_missing_root_is_a_tool_failure(self):
        code, _ = self.lancer(["--root", os.path.join(self.racine, "absent")])
        self.assertEqual(2, code)

    def test_a_clean_checkout_exits_zero(self):
        self.module()
        code, texte = self.lancer(["--root", self.racine, "--no-color"])
        self.assertEqual(0, code)
        self.assertIn(arbre.t("No module carries it."), texte)

    def test_a_finding_exits_one(self):
        module = self.module(manifeste={"data": ["v.xml"]})
        self.ecrire(os.path.join(module, "v.xml"), "<odoo><tree/></odoo>")
        code, _ = self.lancer(["--root", self.racine, "--no-color"])
        self.assertEqual(1, code)

    def test_below_18_it_says_so_instead_of_staying_silent(self):
        self.version("17.0")
        _code, texte = self.lancer(["--root", self.racine, "--no-color"])
        self.assertIn(
            arbre.t("nothing to do below 18.0 — tree is valid there"), texte
        )

    def test_the_json_says_what_to_replace_it_with(self):
        import json

        module = self.module(manifeste={"data": ["v.xml"]})
        self.ecrire(
            os.path.join(module, "v.xml"),
            "<odoo><field name='view_mode'>tree,form</field></odoo>",
        )
        _code, texte = self.lancer(["--root", self.racine, "--json"])
        dct = json.loads(texte)
        self.assertEqual("18.0", dct["odoo"])
        self.assertEqual("list,form", dct["findings"][0]["replace_with"])


class TestAgainstTheRealCheckout(unittest.TestCase):
    """Sur le vrai arbre — c'est là que le tri se prouve."""

    @classmethod
    def setUpClass(cls):
        cls.rapport = arbre.inspect(REPO)

    def test_it_reads_the_whole_addon_tree(self):
        if not arbre.concerne(arbre.version_active(REPO)):
            self.skipTest("checkout sous la 18.0")
        self.assertGreater(self.rapport["scanned"], 1000)

    def test_it_finds_the_line_that_broke_a_kanban(self):
        # « View types not defined tree found in act_window action 444 »,
        # au clic sur action_view_ticket depuis le kanban de projet.
        if not arbre.concerne(arbre.version_active(REPO)):
            self.skipTest("checkout sous la 18.0")
        vus = [
            (f, ligne)
            for _m, f, ligne, _p, _e, _c in self.rapport["findings"]
            if "helpdesk_mgmt_project" in f
        ]
        self.assertTrue(vus, "le défaut rencontré en production n'est pas vu")

    def test_the_core_odoo_identifiers_are_not_reported(self):
        # account.view_invoice_tree et ses semblables vivent dans le noyau
        # 18 avec une arch en <list> : les signaler serait ~400 lignes
        # fausses, et le rapport ne serait pas relancé.
        for _m, fichier, _l, _p, _e, _c in self.rapport["findings"]:
            self.assertNotIn("odoo18.0/odoo/", fichier)


if __name__ == "__main__":
    unittest.main()
