#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Champs hors module : l'attribution et le rendu, sans base.

Ce qui décide d'un blocage vit dans `collect()`, qui a besoin de PostgreSQL.
Il s'éprouve sur une base synthétique portant les cinq cas qui comptent :

* un champ Studio dont la colonne existe — rien à signaler ;
* un champ fait main SANS colonne — bloquant, le registre ne chargerait pas ;
* un one2many non stocké — PAS un bloquant, il n'a jamais de colonne ;
* un champ sur `ir.actions.act_window`, dont la table est `ir_act_window` —
  `replace('.', '_')` crierait à la colonne manquante ;
* un many2one vers un modèle absent — bloquant.

Attendu : 6 champs, 2 bloquants, 1 modèle manuel. Rejoué ensuite sur la forme
12.0 — `company_dependent` retirée, `field_description` en text, pas de
`ir_model_fields_selection` — pour la même sortie.
"""

import unittest

from script.analyse import analyse_custom_field as A
from script.todo import todo_i18n


def field(**override):
    row = {
        "id": 1,
        "model": "res.partner",
        "name": "x_champ",
        "ttype": "char",
        "relation": None,
        "store": True,
        "xmlid_modules": None,
        "origin": "handmade",
        "blocker": None,
    }
    row.update(override)
    return row


class TestFieldOrigin(unittest.TestCase):
    def test_no_xmlid_at_all_means_hand_made(self):
        # Un champ créé en mode développeur n'a AUCUNE ligne ir_model_data.
        # C'est ce qui le distingue, pas son nom : il s'appelle « x_… » lui
        # aussi.
        self.assertEqual(A.field_origin(field(xmlid_modules=None)), "handmade")
        self.assertEqual(A.field_origin(field(xmlid_modules=[])), "handmade")

    def test_studio_module_means_studio(self):
        self.assertEqual(
            A.field_origin(field(xmlid_modules=["studio_customization"])),
            "studio",
        )

    def test_studio_seen_among_several_xmlids(self):
        # Un champ peut porter plusieurs identifiants externes. Une jointure
        # plate n'en rendrait qu'un, choisi au hasard : Studio passerait
        # inaperçu une fois sur deux. D'où l'agrégat côté SQL.
        self.assertEqual(
            A.field_origin(
                field(xmlid_modules=["aaa", "studio_customization"])
            ),
            "studio",
        )

    def test_a_module_xmlid_means_a_module(self):
        self.assertEqual(
            A.field_origin(field(xmlid_modules=["mon_module"])), "module"
        )

    def test_the_x_studio_prefix_is_never_the_only_signal(self):
        # Le préfixe ressemble à Studio mais ne prouve rien : sans identifiant
        # externe, le champ a été fait à la main.
        self.assertEqual(
            A.field_origin(field(name="x_studio_faux", xmlid_modules=None)),
            "handmade",
        )


class TestLabels(unittest.TestCase):
    def setUp(self):
        todo_i18n.set_lang("en")
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def test_every_origin_has_a_label(self):
        for name in ("studio", "handmade", "module"):
            self.assertNotEqual(A.origin_label(name), name)

    def test_every_blocker_has_a_label(self):
        for name in (
            "missing_column",
            "dangling_relation",
            "model_gone",
            "table_unknown",
        ):
            self.assertNotEqual(A.blocker_label(name), name)

    def test_unknown_key_falls_back_to_itself(self):
        self.assertEqual(A.origin_label("inconnu"), "inconnu")


class TestNoColumnTypes(unittest.TestCase):
    def test_to_many_fields_have_no_column_by_design(self):
        # Le faux positif à ne pas produire : un one2many n'a jamais de
        # colonne, il vit dans une table de relation. Le compter manquant
        # ferait un bloquant sur chaque relation d'une base ordinaire.
        self.assertIn("one2many", A.NO_COLUMN_TYPES)
        self.assertIn("many2many", A.NO_COLUMN_TYPES)
        self.assertNotIn("char", A.NO_COLUMN_TYPES)
        self.assertNotIn("many2one", A.NO_COLUMN_TYPES)


class TestRender(unittest.TestCase):
    def setUp(self):
        todo_i18n.set_lang("en")
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def data(self, **override):
        fields = [
            field(id=1, name="x_studio_code", origin="studio"),
            field(
                id=2,
                name="x_fait_main",
                origin="handmade",
                blocker="missing_column",
            ),
        ]
        data = {
            "tool": "analyse_custom_field",
            "version": 1,
            "database": "prod_18",
            "odoo_version": "18.0.1.3",
            "n_fields": 2,
            "n_models": 1,
            "counts": {
                "studio": 1,
                "handmade": 1,
                "module": 0,
                "blockers": 1,
                "models": 1,
            },
            "fields": fields,
            "models": [{"model": "x_contrat", "description": "Contrat"}],
            "blockers": [fields[1]],
        }
        data.update(override)
        return data

    def test_blockers_come_first_and_say_why(self):
        out = A.render(self.data())
        self.assertIn("Blocking (1)", out)
        self.assertIn("stored, but its column is missing", out)
        self.assertLess(out.index("Blocking"), out.index("To carry over"))

    def test_says_the_registry_will_not_load(self):
        self.assertIn("stops the registry from loading", A.render(self.data()))

    def test_no_blocker_block_when_there_is_none(self):
        data = self.data(blockers=[])
        data["counts"]["blockers"] = 0
        self.assertNotIn("Blocking", A.render(data))

    def test_counts_say_how_many_of_the_list_are_blocking(self):
        # Les bloquants sont AUSSI dans la liste à reporter : le dire, sinon
        # deux populations dont les comptes ne s'additionnent pas.
        self.assertIn("(2, 1 blocking)", A.render(self.data()))

    def test_clean_database_says_so(self):
        data = self.data(
            n_fields=0, n_models=0, fields=[], models=[], blockers=[]
        )
        out = A.render(data)
        self.assertIn("No field or model was added outside a module.", out)

    def test_says_nothing_will_recreate_them(self):
        # La raison d'être de l'outil : ces champs ne sont dans aucun fichier.
        self.assertIn("no module will recreate", A.render(self.data()))

    def test_hint_is_absent_in_verbose_and_in_the_menu(self):
        self.assertIn("Use -v", A.render(self.data()))
        self.assertNotIn("Use -v", A.render(self.data(), verbose=True))
        self.assertNotIn("Use -v", A.render(self.data(), hints=False))

    def test_french_differs(self):
        english = A.render(self.data())
        todo_i18n.set_lang("fr")
        french = A.render(self.data())
        self.assertIn("Fait à la main", french)
        self.assertNotEqual(english, french)


if __name__ == "__main__":
    unittest.main()
