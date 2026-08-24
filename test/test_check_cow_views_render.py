#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Prédire, AVANT le palier, la copie qui rendra 500 après.

`check_cow_views` cherchait la rupture qui ARRÊTE la migration : la forme
que l'arch doit avoir change. Deux autres la laissent finir et ne se
voient qu'à l'ouverture de la page — et personne n'ouvre les pages avant
la fin.

Mesuré sur une chaîne 12 → 18 réelle : /contact rendait 500 depuis le
palier 14 → 15. Rejouée avec ce contrôle, la prédiction nomme le défaut
dès le palier 13 → 14, cinq paliers avant que quiconque s'en aperçoive.

Ces copies-là ne se NEUTRALISENT pas : chacune porte une page écrite par
quelqu'un, et la mettre de côté l'effacerait du site. Elles se réparent.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)
sys.path.append(
    os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), "..", "script", "odoo", "migration"
        )
    )
)

import check_cow_views as cow  # noqa: E402

# La copie du client : sa page, sans l'ancrage que la cible attend, et
# avec un appel vers un gabarit que la cible ne livre plus.
ARCH_COPIE = (
    "<t t-name='website.contactus'>"
    "<t t-call='website.layout'>"
    "<div id='wrap'><h1>Parlons de votre projet</h1>"
    "<t t-call='website.company_description'/></div>"
    "</t></t>"
)

MODULE_ENFANT = """<odoo>
  <template id="contactus_form" inherit_id="website.contactus">
    <xpath expr="//t[@t-set='contactus_form_values']" position="after">
      <t t-set="autre" t-value="2"/>
    </xpath>
  </template>
</odoo>
"""

MODULE_PARENT = """<odoo>
  <template id="contactus" name="Contact">
    <t t-call="website.layout"><div id="wrap"/></t>
  </template>
  <template id="layout" name="Layout"><div/></template>
</odoo>
"""


class TestFullKey(unittest.TestCase):
    def test_a_bare_id_takes_its_module(self):
        self.assertEqual(
            cow.full_key("website", "contactus"), "website.contactus"
        )

    def test_a_qualified_id_is_left_alone(self):
        self.assertEqual(
            cow.full_key("website_crm", "website.contactus"),
            "website.contactus",
        )

    def test_nothing_stays_nothing(self):
        self.assertIsNone(cow.full_key("website", ""))
        self.assertIsNone(cow.full_key("website", None))


class TestScanningTheTargetSources(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp(prefix="el_cow_")
        self.addCleanup(shutil.rmtree, self.racine, True)
        for module, contenu in (
            ("website", MODULE_PARENT),
            ("website_crm", MODULE_ENFANT),
        ):
            chemin = os.path.join(self.racine, "odoo", "addons", module)
            os.makedirs(chemin)
            with open(
                os.path.join(chemin, "views.xml"), "w", encoding="utf-8"
            ) as f:
                f.write(contenu)

    def scan(self, modules=("website", "website_crm")):
        return cow.scan_target_views(self.racine, list(modules))

    def test_it_lists_what_the_target_ships(self):
        declares, _ = self.scan()
        self.assertIn("website.contactus", declares)
        self.assertIn("website.layout", declares)

    def test_it_maps_a_child_xpath_to_the_parent_it_needs(self):
        # C'est LE renseignement qui manquait : quelle vue de la cible
        # exige quel ancrage, et dans quel parent.
        _, heritages = self.scan()
        self.assertEqual(
            heritages["website.contactus"],
            ["//t[@t-set='contactus_form_values']"],
        )

    def test_a_module_absent_from_the_target_is_skipped(self):
        declares, _ = self.scan(["website", "jamais_livre"])
        self.assertIn("website.contactus", declares)

    def test_a_template_without_xpath_adds_no_requirement(self):
        _, heritages = self.scan(["website"])
        self.assertEqual(heritages, {})


class TestWillNotRender(unittest.TestCase):
    """Le verdict, en remplaçant ce qui touche la base et le disque."""

    def setUp(self):
        self.vrai = (
            cow.query_cow_archs,
            cow.installed_modules,
            cow.scan_target_views,
        )

    def tearDown(self):
        (
            cow.query_cow_archs,
            cow.installed_modules,
            cow.scan_target_views,
        ) = self.vrai

    def poser(self, copies, declares, heritages):
        cow.query_cow_archs = lambda d: copies
        cow.installed_modules = lambda d: ["website"]
        cow.scan_target_views = lambda v, m: (declares, heritages)

    def copie(self, arch=ARCH_COPIE, langues=None):
        return [
            (
                1228,
                "website.contactus",
                "primary",
                1,
                langues or {"en_US": arch},
            )
        ]

    def test_it_names_the_anchor_a_target_child_will_need(self):
        self.poser(
            self.copie(),
            {
                "website.contactus",
                "website.layout",
                "website.company_description",
            },
            {"website.contactus": ["//t[@t-set='contactus_form_values']"]},
        )
        risques = cow.will_not_render("db", "odoo18.0")
        self.assertEqual(1, len(risques), risques)
        self.assertIn("contactus_form_values", risques[0][5])

    def test_an_anchor_the_copy_already_has_is_not_reported(self):
        arch = ARCH_COPIE.replace(
            "<div id='wrap'>",
            "<t t-set='contactus_form_values' t-value='1'/><div id='wrap'>",
        )
        self.poser(
            self.copie(arch),
            {
                "website.contactus",
                "website.layout",
                "website.company_description",
            },
            {"website.contactus": ["//t[@t-set='contactus_form_values']"]},
        )
        self.assertEqual([], cow.will_not_render("db", "odoo18.0"))

    def test_it_names_a_template_the_target_no_longer_ships(self):
        self.poser(
            self.copie(),
            {"website.contactus", "website.layout"},
            {},
        )
        risques = cow.will_not_render("db", "odoo18.0")
        self.assertEqual(1, len(risques), risques)
        self.assertIn("company_description", risques[0][5])

    def test_another_copy_counts_as_a_known_template(self):
        # Un gabarit peut n'exister qu'en base : une copie de site qui en
        # appelle une autre n'est pas cassée pour autant.
        copies = self.copie() + [
            (
                99,
                "website.company_description",
                "primary",
                1,
                {"en_US": "<t/>"},
            )
        ]
        self.poser(copies, {"website.contactus", "website.layout"}, {})
        self.assertEqual([], cow.will_not_render("db", "odoo18.0"))

    def test_a_copy_broken_in_one_language_only_is_still_reported(self):
        # Le site rend dans SA langue : réparer l'anglais et laisser le
        # français cassé donne une page en 500 et un rapport vert.
        sain = ARCH_COPIE.replace(
            "<div id='wrap'>",
            "<t t-set='contactus_form_values' t-value='1'/><div id='wrap'>",
        )
        self.poser(
            self.copie(langues={"en_US": sain, "fr_CA": ARCH_COPIE}),
            {
                "website.contactus",
                "website.layout",
                "website.company_description",
            },
            {"website.contactus": ["//t[@t-set='contactus_form_values']"]},
        )
        risques = cow.will_not_render("db", "odoo18.0")
        self.assertEqual(1, len(risques), risques)

    def test_a_copy_without_a_key_is_left_alone(self):
        self.poser(
            [(7, "", "primary", 1, {"en_US": ARCH_COPIE})],
            {"website.company_description"},
            {},
        )
        self.assertEqual([], cow.will_not_render("db", "odoo18.0"))

    def test_no_copy_at_all_is_not_an_error(self):
        self.poser([], set(), {})
        self.assertEqual([], cow.will_not_render("db", "odoo18.0"))


class TestItStaysOutOfTheNeutralizer(unittest.TestCase):
    """Ces copies se réparent ; les neutraliser effacerait la page."""

    def test_the_neutralizer_only_acts_on_the_shape_bucket(self):
        with open(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "script",
                "odoo",
                "migration",
                "neutralize_cow_views.py",
            ),
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        self.assertIn("lst_at_risk, _, _ = analyse(", source)
        self.assertNotIn("will_not_render", source)


if __name__ == "__main__":
    unittest.main()
