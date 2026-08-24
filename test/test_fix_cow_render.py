#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une copie de site web qui ne sait plus se rendre après la montée.

`check_cow_views` cherche la rupture qui ARRÊTE la migration : la forme
que l'arch doit avoir a changé. Deux autres la laissent finir sans un mot
et ne se voient qu'à l'ouverture de la page.

Mesuré sur une migration 12 → 18 réelle : /contact rendait 500 depuis le
palier 14 → 15 — quatre paliers de silence. La copie COW de
`website.contactus` n'a jamais eu le `t-set='contactus_form_values'` que
le module a gagné en chemin, et sur lequel sa vue héritière fait un
xpath. Les deux copies appelaient en plus `website.company_description`,
gabarit disparu en 18.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo.migration import fix_cow_render as cow  # noqa: E402

# La forme réelle, réduite : le module porte l'ancrage, la copie ne l'a
# jamais eu, et toutes deux appellent le gabarit disparu.
ARCH_MODULE = (
    "<t t-name='website.contactus'>"
    "<t t-call='website.layout'>"
    "<t t-set='logged_partner' t-value='1'/>"
    "<t t-set='contactus_form_values' t-value=\"{'a': 1}\"/>"
    "<div id='wrap'><h1>Contact us</h1></div>"
    "</t></t>"
)
ARCH_COPIE = (
    "<t t-name='website.contactus'>"
    "<t t-call='website.layout'>"
    "<div id='wrap'><h1>Parlons de votre projet</h1>"
    "<t t-call='website.company_description'/></div>"
    "</t></t>"
)
ARCH_ENFANT = (
    "<data><xpath expr=\"//t[@t-set='contactus_form_values']\" position='after'>"
    "<t t-set='autre' t-value='2'/></xpath></data>"
)


class TestWhatAChildAsksFor(unittest.TestCase):
    def test_it_reads_the_xpath_of_a_child(self):
        self.assertEqual(
            cow.anchors_wanted(ARCH_ENFANT),
            ["//t[@t-set='contactus_form_values']"],
        )

    def test_a_child_without_xpath_asks_for_nothing(self):
        self.assertEqual(
            cow.anchors_wanted("<data><field name='x'/></data>"), []
        )

    def test_an_unparsable_arch_asks_for_nothing_rather_than_crashing(self):
        self.assertEqual(cow.anchors_wanted("<data><oops"), [])


class TestLocating(unittest.TestCase):
    def test_the_module_has_the_anchor(self):
        self.assertTrue(
            cow.locates(ARCH_MODULE, "//t[@t-set='contactus_form_values']")
        )

    def test_the_copy_does_not(self):
        self.assertFalse(
            cow.locates(ARCH_COPIE, "//t[@t-set='contactus_form_values']")
        )

    def test_an_illegible_expression_counts_as_found(self):
        # Elle ne relève pas de cet outil ; la signaler enverrait réparer
        # une vue qui n'a rien.
        self.assertTrue(cow.locates(ARCH_COPIE, "//[[["))

    def test_an_unparsable_arch_counts_as_found(self):
        self.assertTrue(cow.locates("<t><oops", "//t"))


class TestDanglingCalls(unittest.TestCase):
    CONNUS = {"website.layout", "website.contactus"}

    def test_it_names_the_template_that_is_gone(self):
        self.assertEqual(
            cow.dangling_calls(ARCH_COPIE, self.CONNUS),
            ["website.company_description"],
        )

    def test_a_known_template_is_not_reported(self):
        self.assertNotIn(
            "website.layout", cow.dangling_calls(ARCH_COPIE, self.CONNUS)
        )

    def test_a_computed_call_is_left_alone(self):
        # Il se résout à l'exécution : on ne peut rien en dire ici.
        arch = "<t><t t-call='{{ nom }}'/><t t-call='#x'/></t>"
        self.assertEqual(cow.dangling_calls(arch, self.CONNUS), [])

    def test_the_same_missing_template_is_named_once(self):
        arch = "<t><t t-call='parti'/><div><t t-call='parti'/></div></t>"
        self.assertEqual(cow.dangling_calls(arch, self.CONNUS), ["parti"])


class TestRepairingTheAnchor(unittest.TestCase):
    def test_it_puts_the_anchor_back_where_the_module_holds_it(self):
        neuf = cow.repair_anchor(
            ARCH_COPIE, ARCH_MODULE, "//t[@t-set='contactus_form_values']"
        )
        self.assertIsNotNone(neuf)
        self.assertTrue(
            cow.locates(neuf, "//t[@t-set='contactus_form_values']")
        )

    def test_the_anchor_lands_inside_its_host_not_at_the_root(self):
        # `//t[@t-set='x']` le trouverait n'importe où : ce n'est donc pas
        # la preuve. Ce qui compte est la PLACE — le `t-set` porte une
        # portée, et l'enfant s'insère « after » l'ancrage. Posé à la
        # racine, le formulaire atterrirait hors de la mise en page.
        from lxml import etree

        neuf = cow.repair_anchor(
            ARCH_COPIE, ARCH_MODULE, "//t[@t-set='contactus_form_values']"
        )
        arbre = etree.fromstring(neuf.encode("utf-8"))
        ancre = arbre.xpath("//t[@t-set='contactus_form_values']")[0]
        self.assertEqual(
            "website.layout",
            ancre.getparent().get("t-call"),
            etree.tostring(arbre, encoding="unicode"),
        )

    def test_the_anchor_keeps_the_rank_the_module_gives_it(self):
        # QWeb évalue dans l'ordre du document : un `t-set` posé après le
        # contenu qui s'en sert n'est pas vu, et l'enfant qui s'insère
        # « after » l'ancrage le suit où qu'il aille.
        from lxml import etree

        neuf = cow.repair_anchor(
            ARCH_COPIE, ARCH_MODULE, "//t[@t-set='contactus_form_values']"
        )
        arbre = etree.fromstring(neuf.encode("utf-8"))
        hote = arbre.xpath("//t[@t-call='website.layout']")[0]
        rangs = {
            enfant.get("t-set") or enfant.get("id"): rang
            for rang, enfant in enumerate(hote)
        }
        self.assertLess(rangs["contactus_form_values"], rangs["wrap"], neuf)

    def test_it_goes_before_the_sibling_it_precedes_in_the_module(self):
        # Le jeu précédent ne prouve rien : la bonne place y VAUT zéro,
        # donc un repli en tête passerait pour une réussite. Ici la copie
        # porte déjà un élément avant le frère repère, et la bonne place
        # est 1 — la seule que le repli ne trouve pas.
        from lxml import etree

        copie = (
            "<t t-name='website.contactus'>"
            "<t t-call='website.layout'>"
            "<t t-set='deja_la' t-value='0'/>"
            "<div id='wrap'><h1>Ma page</h1></div>"
            "</t></t>"
        )
        neuf = cow.repair_anchor(
            copie, ARCH_MODULE, "//t[@t-set='contactus_form_values']"
        )
        hote = etree.fromstring(neuf.encode("utf-8")).xpath(
            "//t[@t-call='website.layout']"
        )[0]
        noms = [e.get("t-set") or e.get("id") for e in hote]
        self.assertEqual(
            ["deja_la", "contactus_form_values", "wrap"], noms, neuf
        )

    def test_it_keeps_the_page_written_by_the_customer(self):
        # C'est tout l'enjeu : réinitialiser la vue rendrait la page
        # fonctionnelle et effacerait son contenu.
        neuf = cow.repair_anchor(
            ARCH_COPIE, ARCH_MODULE, "//t[@t-set='contactus_form_values']"
        )
        self.assertIn("Parlons de votre projet", neuf)

    def test_it_refuses_when_the_host_element_has_no_twin(self):
        # Mieux vaut une réparation refusée qu'un bloc posé au hasard au
        # milieu de la page de quelqu'un.
        etrangere = "<t t-name='x'><section id='rien'/></t>"
        self.assertIsNone(
            cow.repair_anchor(
                etrangere, ARCH_MODULE, "//t[@t-set='contactus_form_values']"
            )
        )

    def test_it_refuses_when_the_module_has_no_anchor_either(self):
        self.assertIsNone(
            cow.repair_anchor(ARCH_COPIE, ARCH_COPIE, "//t[@t-set='absent']")
        )

    def test_it_refuses_an_unparsable_arch(self):
        self.assertIsNone(cow.repair_anchor("<t><oops", ARCH_MODULE, "//t"))


class TestRemovingTheCall(unittest.TestCase):
    def test_the_call_goes_and_the_rest_stays(self):
        neuf = cow.repair_call(ARCH_COPIE, "website.company_description")
        self.assertIsNotNone(neuf)
        self.assertNotIn("company_description", neuf)
        self.assertIn("Parlons de votre projet", neuf)
        self.assertIn("website.layout", neuf)

    def test_nothing_to_remove_means_no_change_proposed(self):
        self.assertIsNone(cow.repair_call(ARCH_COPIE, "jamais.vu"))

    def test_every_occurrence_goes(self):
        arch = "<t><t t-call='parti'/><div><t t-call='parti'/></div></t>"
        self.assertNotIn("parti", cow.repair_call(arch, "parti"))


class TestLanguages(unittest.TestCase):
    """`arch_db` porte UNE ENTRÉE PAR LANGUE depuis la 17.

    N'en lire qu'une déclare la vue saine alors qu'une autre est cassée ;
    n'en écrire qu'une laisse la page en 500. Les deux me sont arrivés :
    /contact réparé en en_US rendait toujours 500, parce que le site rend
    en fr_CA.
    """

    def test_it_sees_every_language(self):
        self.assertEqual(
            sorted(cow.langs_of({"en_US": "<t/>", "fr_CA": "<u/>"})),
            ["en_US", "fr_CA"],
        )

    def test_the_query_never_pins_one_language(self):
        # C'est ICI que le défaut est né : `arch_db->>'en_US'` ramenait
        # une seule langue, l'audit déclarait la vue saine et /contact
        # restait en 500 parce que le site rend en fr_CA. La requête doit
        # ramener l'OBJET entier.
        requete = cow.arch_expr(jsonb=True)
        self.assertNotIn("en_US", requete)
        self.assertNotIn("->>", requete)
        self.assertIn("arch_db", requete)

    def test_a_varchar_column_is_wrapped_as_one_nameless_language(self):
        # Une seule forme en aval : le reste du code n'a pas à savoir si
        # la version traduit l'arch ou non.
        requete = cow.arch_expr(jsonb=False)
        self.assertIn("json_build_object", requete)

    def test_a_plain_string_is_the_language_less_case(self):
        self.assertEqual(cow.langs_of("<t/>"), {"": "<t/>"})

    def test_a_non_string_value_is_ignored(self):
        self.assertEqual(
            cow.langs_of({"en_US": "<t/>", "x": 3}), {"en_US": "<t/>"}
        )

    def test_the_xpath_of_a_child_is_read_from_any_language(self):
        # Les xpath ne sont pas traduits : n'importe quelle langue suffit.
        self.assertEqual(
            cow.anchors_wanted(cow.any_lang({"fr_CA": ARCH_ENFANT})),
            ["//t[@t-set='contactus_form_values']"],
        )


class TestTheSqlItWrites(unittest.TestCase):
    def test_it_writes_all_the_languages_in_one_update(self):
        # Deux UPDATE sur la même vue et le second effacerait le premier ;
        # un seul portant une langue laisserait l'autre cassée.
        sql = cow.write_arch_sql(
            7, {"en_US": "<t a='1'/>", "fr_CA": "<t b='2'/>"}, jsonb=True
        )
        self.assertEqual(1, sql.count("UPDATE"), sql)
        self.assertIn("en_US", sql)
        self.assertIn("fr_CA", sql)
        self.assertIn("<t a='1'/>", sql)
        self.assertIn("<t b='2'/>", sql)
        self.assertIn("WHERE id = 7", sql)

    def test_the_varchar_case_writes_the_text_itself(self):
        sql = cow.write_arch_sql(7, {"": "<t/>"}, jsonb=False)
        self.assertNotIn("jsonb_build_object", sql)
        self.assertIn("<t/>", sql)

    def test_both_branches_survive_an_apostrophe(self):
        # La 16 stocke en varchar, la 17 et la 18 en jsonb : les DEUX
        # chemins écrivent, et n'éprouver que l'un laisse l'autre casser
        # au premier attribut cité.
        arch = "<t t-value=\"{'a': 1}\"/>"
        for jsonb, langues in ((True, {"en_US": arch}), (False, {"": arch})):
            with self.subTest(jsonb=jsonb):
                sql = cow.write_arch_sql(7, langues, jsonb=jsonb)
                self.assertIn("$elcow$" + arch + "$elcow$", sql)


class TestTheReport(unittest.TestCase):
    def rapport(self):
        return {
            "database": "essai",
            "jsonb": True,
            "views": [
                {
                    "id": 1228,
                    "key": "website.contactus",
                    "anchors": [{"enfant": 2782, "expr": "//t[@t-set='x']"}],
                    "calls": ["website.company_description"],
                }
            ],
        }

    def test_a_clean_database_says_so(self):
        texte = "\n".join(
            cow.render({"database": "x", "jsonb": True, "views": []}, [])
        )
        self.assertIn("✅", texte)

    def test_it_names_the_view_the_child_and_the_template(self):
        texte = "\n".join(cow.render(self.rapport(), []))
        self.assertIn("1228", texte)
        self.assertIn("2782", texte)
        self.assertIn("website.company_description", texte)

    def test_it_warns_that_removing_a_call_removes_a_block(self):
        # Le message passe par `t()` : le comparer à un mot anglais en
        # dur le fait tomber dès qu'on le traduit. On demande la MÊME
        # traduction que le code, ce qui éprouve l'avertissement sans
        # épouser une langue.
        gestes = [(1228, "k", "t-call", "website.company_description", "SQL")]
        texte = "\n".join(cow.render(self.rapport(), gestes))
        self.assertIn(
            cow.t("Removing a call removes its block from the page."), texte
        )

    def test_it_stays_silent_about_blocks_when_nothing_is_removed(self):
        gestes = [(1228, "k", "anchor", "//t", "SQL")]
        texte = "\n".join(cow.render(self.rapport(), gestes))
        self.assertNotIn(
            cow.t("Removing a call removes its block from the page."), texte
        )

    def test_it_says_when_a_repair_is_out_of_reach(self):
        gestes = [(1228, "k", "anchor-impossible", "//t", None)]
        texte = "\n".join(cow.render(self.rapport(), gestes))
        self.assertIn("1", texte)
        self.assertIn("⚠", texte)


if __name__ == "__main__":
    unittest.main()
