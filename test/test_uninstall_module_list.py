#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les modules qu'un palier doit retirer AVANT de monter.

Certaines incompatibilités n'existent qu'à partir d'une version donnée.
`muk_web_theme` n'excluait que `web_enterprise` en 16 et en 17 ; la 18 y
ajoute `web_responsive`. Les deux cohabitaient donc légalement, et la
base arrive en 18 dans un état que la 18 interdit — le chargement meurt
dès qu'un module auto_install est installé, car Odoo revérifie alors
toutes les exclusions.

Le retrait doit se faire pendant qu'on est ENCORE sur l'ancienne
version, là où l'état est légal et où l'ORM fonctionne.
"""

import io
import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DOSSIER = os.path.join(RACINE, "script", "odoo", "migration")


def lecteur():
    return TodoUpgrade.__new__(TodoUpgrade)


class TestTheSeventeenToEighteenList(unittest.TestCase):
    def test_the_file_exists_where_the_driver_looks(self):
        chemin = os.path.join(
            DOSSIER, "uninstall_module_list_odoo170_to_odoo180.txt"
        )
        self.assertTrue(os.path.isfile(chemin), chemin)

    def test_it_names_web_responsive(self):
        modules, _detail = lecteur().read_uninstall_module_list(17, "peu")
        self.assertIn("web_responsive", modules)

    def test_the_removal_is_justified(self):
        # Sans justification, on retrouve un module retiré des mois plus
        # tard sans pouvoir dire pourquoi, ni s'il faut le remettre.
        _m, detail = lecteur().read_uninstall_module_list(17, "peu")
        raisons = {module: raison for module, raison, _f in detail}
        self.assertTrue(raisons.get("web_responsive"), raisons)

    def test_muk_web_theme_is_NOT_removed_here(self):
        # Les deux rendent le même service : il faut en garder un, et
        # c'est le thème qui porte l'apparence du back-office.
        modules, _d = lecteur().read_uninstall_module_list(17, "peu")
        self.assertNotIn("muk_web_theme", modules)


class TestEveryListIsWellFormed(unittest.TestCase):
    def fichiers(self):
        import glob

        return sorted(
            glob.glob(os.path.join(DOSSIER, "uninstall_module_list_*.txt"))
        )

    def test_there_is_at_least_one(self):
        # Sans cette borne, le test suivant passerait en ne vérifiant
        # rien le jour où le motif de nom change.
        self.assertGreater(len(self.fichiers()), 0)

    def test_every_entry_is_justified(self):
        for chemin in self.fichiers():
            for module, raison in TodoUpgrade.parse_module_list_file(chemin):
                self.assertTrue(
                    raison,
                    f"{os.path.basename(chemin)} : {module} sans raison",
                )

    def test_no_entry_looks_like_a_stray_comment(self):
        # Le parseur coupe à « # » : une ligne mal écrite produirait un
        # nom de module fantôme, retiré en silence de rien du tout.
        for chemin in self.fichiers():
            for module, _r in TodoUpgrade.parse_module_list_file(chemin):
                self.assertRegex(module, r"^[a-z][a-z0-9_]*$", module)

    def test_the_name_encodes_the_bump_it_serves(self):
        import re

        for chemin in self.fichiers():
            nom = os.path.basename(chemin)
            trouve = re.match(
                r"uninstall_module_list_odoo(\d+)_to_odoo(\d+)\.txt$", nom
            )
            self.assertIsNotNone(trouve, nom)
            depart, arrivee = (int(x) for x in trouve.groups())
            self.assertEqual(arrivee, depart + 10, nom)


class TestWhenItRuns(unittest.TestCase):
    def test_the_uninstall_precedes_the_openupgrade_run(self):
        # Retirer un module APRÈS la montée serait trop tard : c'est la
        # montée elle-même qui refuse l'état.
        with io.open(
            os.path.join(RACINE, "script", "todo", "todo_upgrade.py"),
            encoding="utf-8",
        ) as handle:
            src = handle.read()
        self.assertLess(
            src.index("- Uninstall module"), src.index("- Migrate database")
        )

    def test_a_private_list_wins_over_the_shared_one(self):
        # Une base peut avoir ses propres retraits sans qu'on touche à la
        # liste partagée de tout le monde.
        source = io.open(
            os.path.join(RACINE, "script", "todo", "todo_upgrade.py"),
            encoding="utf-8",
        ).read()
        debut = source.index("def read_uninstall_module_list")
        fin = source.index("def split_present_missing")
        bloc = source[debut:fin]
        self.assertLess(
            bloc.index("PATH_MIGRATION_PRIVATE"),
            bloc.index("PATH_MIGRATION_GLOBAL"),
        )


if __name__ == "__main__":
    unittest.main()
