#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Vues personnalisées : le classement, sans base.

`classify()` est une fonction pure de la ligne SQL vers une catégorie. C'est
là que se joue tout ce qui distingue un constat d'un faux positif, donc c'est
là que porte l'essentiel de ces tests.

La collecte s'éprouve sur une base synthétique portant les sept catégories, y
compris deux copies COW — l'une avec sa jumelle module, l'autre sans, qui est
une page faite dans l'éditeur web. Attendu : 11 vues, 8 constats, et des
comptes dont la somme fait exactement 11.
"""

import unittest

from script.analyse import analyse_view_custom as A
from script.todo import todo_i18n


def view(**override):
    """Une ligne de vue telle que la rend la requête, tout à zéro."""
    row = {
        "id": 1,
        "name": "Une vue",
        "key": None,
        "arch_fs": None,
        "arch_updated": False,
        "noupdate": False,
        "has_arch_prev": False,
        "active": True,
        "website_id": None,
        "theme_template_id": None,
        "xmlid_modules": None,
        "xmlids": None,
        "has_module_twin": False,
        "arch_bytes": 100,
    }
    row.update(override)
    return row


class TestClassify(unittest.TestCase):
    def test_plain_module_view(self):
        row = view(arch_fs="base/views/x.xml", xmlid_modules=["base"])
        self.assertEqual(A.classify(row)[0], "module_view")

    def test_module_view_flagged_by_arch_updated(self):
        row = view(
            arch_fs="sale/views/y.xml",
            xmlid_modules=["sale"],
            arch_updated=True,
        )
        category, reasons = A.classify(row)
        self.assertEqual(category, "module_view_flagged")
        self.assertIn("arch_updated", reasons)

    def test_noupdate_alone_is_not_a_finding(self):
        """Le faux positif à ne pas réintroduire.

        Toute vue déclarée dans un bloc <odoo noupdate="1"> porte ce drapeau —
        les données de mail, account et website en sont pleines — sans que
        personne n'y ait touché. La compter noierait la catégorie qui compte.
        """
        row = view(
            arch_fs="mail/data/z.xml", xmlid_modules=["mail"], noupdate=True
        )
        category, reasons = A.classify(row)
        self.assertEqual(category, "module_view")
        self.assertNotIn(category, A.ACTIONABLE)
        # L'information n'est pas perdue pour autant.
        self.assertIn("noupdate", reasons)

    def test_website_copy(self):
        row = view(key="website.layout", website_id=1, has_module_twin=True)
        category, reasons = A.classify(row)
        self.assertEqual(category, "website_cow_copy")
        self.assertNotIn("no_module_twin", reasons)

    def test_website_copy_without_a_twin_is_a_page_from_the_editor(self):
        row = view(key="website.page_1", website_id=1, has_module_twin=False)
        category, reasons = A.classify(row)
        self.assertEqual(category, "website_cow_copy")
        self.assertIn("no_module_twin", reasons)

    def test_studio(self):
        row = view(xmlid_modules=["studio_customization"])
        self.assertEqual(A.classify(row)[0], "studio")

    def test_studio_seen_among_several_xmlids(self):
        """Une vue peut porter plusieurs identifiants externes.

        Une jointure plate n'en rendrait qu'un, choisi au hasard : Studio
        passerait inaperçu une fois sur deux. D'où l'agrégat côté SQL, dont
        ceci vérifie que le classement sait se servir.
        """
        row = view(xmlid_modules=["aaa_module", "studio_customization"])
        self.assertEqual(A.classify(row)[0], "studio")

    def test_imported_or_exported(self):
        for module in ("__export__", "__import__", "__custom__"):
            row = view(xmlid_modules=[module])
            self.assertEqual(
                A.classify(row)[0], "imported_or_exported", module
            )

    def test_created_from_the_interface(self):
        self.assertEqual(A.classify(view())[0], "ui_created")

    def test_theme(self):
        self.assertEqual(
            A.classify(view(theme_template_id=42))[0], "theme_installed"
        )

    def test_precedence_website_beats_studio(self):
        # Une vue Studio copiée par le site web se regarde d'abord comme une
        # copie : c'est ce qui décide si elle survivra à la montée de version.
        row = view(
            website_id=1,
            has_module_twin=True,
            xmlid_modules=["studio_customization"],
        )
        self.assertEqual(A.classify(row)[0], "website_cow_copy")

    def test_precedence_theme_beats_website(self):
        row = view(theme_template_id=7, website_id=1)
        self.assertEqual(A.classify(row)[0], "theme_installed")

    def test_reasons_accumulate(self):
        row = view(
            arch_fs="x.xml",
            xmlid_modules=["base"],
            arch_updated=True,
            noupdate=True,
            has_arch_prev=True,
            active=False,
        )
        reasons = A.classify(row)[1]
        self.assertEqual(
            reasons, ["arch_updated", "noupdate", "has_arch_prev", "inactive"]
        )

    def test_the_category_is_always_a_known_one(self):
        for row in (
            view(),
            view(theme_template_id=1),
            view(website_id=1),
            view(xmlid_modules=["base"], arch_fs="x.xml"),
            view(xmlid_modules=["studio_customization"]),
        ):
            self.assertIn(A.classify(row)[0], A.CATEGORIES)


class TestCategoryTables(unittest.TestCase):
    """Les trois tables de catégories doivent rester d'accord entre elles."""

    def test_every_category_has_a_label(self):
        # PAS `set_lang()` : il PERSISTE la langue dans ./env_var.sh, un
        # fichier suivi par git. Un test qui l'appelle modifie l'arbre de
        # travail et laisse la langue changée pour tout ce qui suit —
        # `_current_lang = None` ne défait que la mémoïsation, pas le
        # fichier, et la résolution suivante relit celui-ci. On écrit donc
        # la mémoïsation directement, et on rend la valeur trouvée.
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        for name in A.CATEGORIES:
            self.assertNotEqual(
                A.category_label(name),
                name,
                f"'{name}' n'a pas de libellé traduit",
            )

    def test_actionable_is_a_subset_of_categories(self):
        self.assertEqual(set(A.ACTIONABLE) - set(A.CATEGORIES), set())

    def test_plain_module_views_are_never_a_finding(self):
        self.assertNotIn("module_view", A.ACTIONABLE)


class TestRender(unittest.TestCase):
    def setUp(self):
        # PAS `set_lang()` : il PERSISTE la langue dans ./env_var.sh, un
        # fichier suivi par git. Un test qui l'appelle modifie l'arbre de
        # travail et laisse la langue changée pour tout ce qui suit —
        # `_current_lang = None` ne défait que la mémoïsation, pas le
        # fichier, et la résolution suivante relit celui-ci. On écrit donc
        # la mémoïsation directement, et on rend la valeur trouvée.
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def data(self, **override):
        rows = [
            view(id=2, key="sale.view_order_form", arch_updated=True),
            view(id=5, key="website.layout", website_id=1),
        ]
        for row in rows:
            row["category"], row["reason"] = A.classify(row)
        data = {
            "tool": "analyse_view_custom",
            "version": 1,
            "database": "prod_18",
            "odoo_version": "18.0.1.3",
            "has_website": True,
            "compared_with_module_source": False,
            "n_views": 40,
            "counts": {name: 0 for name in A.CATEGORIES},
            "findings": rows,
        }
        data["counts"]["website_cow_copy"] = 1
        data["counts"]["module_view"] = 38
        data["counts"]["ui_created"] = 1
        data.update(override)
        return data

    def test_lists_the_findings(self):
        out = A.render(self.data())
        self.assertIn("sale.view_order_form", out)
        self.assertIn("website.layout", out)

    def test_points_at_the_existing_cow_tools(self):
        # L'inventaire ne rejuge pas les copies : il renvoie vers les outils
        # qui tranchent, plutôt que de refaire leur travail à moitié.
        out = A.render(self.data())
        self.assertIn("check_cow_views.py", out)
        self.assertIn("reset_stale_cow_views.py", out)

    def test_no_cow_note_without_cow_views(self):
        data = self.data()
        data["counts"]["website_cow_copy"] = 0
        self.assertNotIn("check_cow_views.py", A.render(data))

    def test_says_the_flags_are_not_a_verdict(self):
        # Sans comparaison, « signalée » n'est pas « modifiée » : le rapport
        # doit le dire, sinon il promet plus qu'il ne sait.
        self.assertIn("Flags say a view was touched", A.render(self.data()))

    def test_clean_database_says_so(self):
        data = self.data(findings=[])
        out = A.render(data)
        self.assertIn("Every view comes straight from a module.", out)
        self.assertNotIn("check_cow_views.py", out)

    def test_top_truncates_and_says_how_many_are_hidden(self):
        out = A.render(self.data(), top=1)
        self.assertIn("more", out)

    def test_verbose_shows_everything(self):
        self.assertNotIn("more", A.render(self.data(), verbose=True))

    def test_category_filter(self):
        out = A.render(self.data(), category="website_cow_copy")
        self.assertIn("website.layout", out)
        self.assertNotIn("sale.view_order_form", out)

    def test_french_differs(self):
        english = A.render(self.data())
        todo_i18n._current_lang = "fr"  # cf. plus haut : pas de persistance
        french = A.render(self.data())
        self.assertIn("Copie de site web", french)
        self.assertNotEqual(english, french)


if __name__ == "__main__":
    unittest.main()
