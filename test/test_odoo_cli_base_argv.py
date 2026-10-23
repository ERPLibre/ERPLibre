#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les aides d'arguments du module erplibre_odoo_cli_base.

cli/_argv.py n'importe que la bibliothèque standard : il se charge par son
chemin, sans Odoo. Le module vit dans le dépôt d'addons de la version
active ; absent de ce checkout, le test se dit ignoré.
"""

import argparse
import importlib.util
import os
import pathlib
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[1]


def _chemin_argv():
    try:
        version = (RACINE / ".odoo-version").read_text().strip()
    except OSError:
        return None
    chemin = (
        RACINE
        / ("odoo" + version)
        / "addons"
        / "ERPLibre_erplibre_addons"
        / "erplibre_odoo_cli_base"
        / "cli"
        / "_argv.py"
    )
    return chemin if chemin.is_file() else None


CHEMIN = _chemin_argv()
A = None
if CHEMIN:
    _spec = importlib.util.spec_from_file_location("cli_base_argv", CHEMIN)
    A = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(A)


@unittest.skipIf(A is None, "erplibre_odoo_cli_base absent de ce checkout")
class TestSplitSubcommand(unittest.TestCase):
    def test_premier_mot(self):
        self.assertEqual(0, A.split_subcommand(["list"]))

    def test_globales_a_valeur(self):
        self.assertEqual(
            4,
            A.split_subcommand(["-c", "f.conf", "--db_port", "5999", "drop"]),
        )

    def test_option_egal_valeur(self):
        self.assertEqual(1, A.split_subcommand(["--config=f.conf", "list"]))

    def test_aide_en_premier(self):
        self.assertIsNone(A.split_subcommand(["-h", "list"]))
        self.assertIsNone(A.split_subcommand(["--help"]))

    def test_aucune(self):
        self.assertIsNone(A.split_subcommand([]))
        self.assertIsNone(A.split_subcommand(["-c", "f.conf"]))


@unittest.skipIf(A is None, "erplibre_odoo_cli_base absent de ce checkout")
class TestResolveImage(unittest.TestCase):
    def test_nom(self):
        self.assertEqual(
            os.path.join(".", "image_db", "img_bidon.zip"),
            A.resolve_image("img_bidon"),
        )

    def test_nom_zip(self):
        self.assertEqual(
            os.path.join(".", "image_db", "img_bidon.zip"),
            A.resolve_image("img_bidon.zip"),
        )

    def test_chemin_relatif(self):
        self.assertEqual("./x/img.zip", A.resolve_image("./x/img"))

    def test_chemin_absolu(self):
        self.assertEqual("/srv/s/img.zip", A.resolve_image("/srv/s/img"))

    def test_chemin_zip(self):
        self.assertEqual("/srv/s/img.zip", A.resolve_image("/srv/s/img.zip"))


@unittest.skipIf(A is None, "erplibre_odoo_cli_base absent de ce checkout")
class TestReplaceImageOption(unittest.TestCase):
    IMG = os.path.join(".", "image_db", "img.zip")

    def test_load_avec_base(self):
        self.assertEqual(
            ["-f", "base_bidon", self.IMG],
            A.replace_image_option(
                "load", ["-f", "base_bidon", "--image", "img"]
            ),
        )

    def test_load_sans_base(self):
        self.assertEqual(
            [self.IMG], A.replace_image_option("load", ["--image", "img"])
        )

    def test_dump(self):
        self.assertEqual(
            ["base_bidon", self.IMG],
            A.replace_image_option("dump", ["--image=img", "base_bidon"]),
        )

    def test_load_option_apres_base(self):
        # L'image suit la base, jamais l'option : « DB -n ZIP » lierait DB
        # à dump_file dans l'analyseur d'Odoo.
        for option in ("--neutralize", "-n", "-f", "--force", "--move"):
            self.assertEqual(
                ["base_bidon", self.IMG, option],
                A.replace_image_option(
                    "load", ["base_bidon", "--image", "img", option]
                ),
            )

    def test_load_options_melangees(self):
        self.assertEqual(
            ["-f", "base_bidon", self.IMG, "-n", "--move"],
            A.replace_image_option(
                "load", ["-f", "base_bidon", "-n", "--image=img", "--move"]
            ),
        )

    def test_load_sans_base_avec_option(self):
        self.assertEqual(
            ["--neutralize", self.IMG],
            A.replace_image_option("load", ["--image", "img", "--neutralize"]),
        )

    def test_load_analyse_comme_odoo(self):
        # Réplique de l'analyseur « load » d'Odoo 18 (odoo/cli/db.py) :
        # base optionnelle, puis dump_file, et trois drapeaux sans valeur.
        load = argparse.ArgumentParser(exit_on_error=False)
        load.add_argument("-f", "--force", action="store_true")
        load.add_argument("-n", "--neutralize", action="store_true")
        load.add_argument("--move", dest="copy", action="store_false")
        load.add_argument("database", nargs="?")
        load.add_argument("dump_file")
        for args in (
            ["base_bidon", "--image", "img", "--neutralize"],
            ["base_bidon", "--neutralize", "--image", "img"],
            ["-f", "base_bidon", "--image", "img", "--move", "-n"],
            ["--image", "img", "base_bidon", "-f"],
        ):
            ns = load.parse_args(A.replace_image_option("load", args))
            self.assertEqual(
                ("base_bidon", self.IMG), (ns.database, ns.dump_file)
            )
        ns = load.parse_args(
            A.replace_image_option("load", ["--image", "img", "-n"])
        )
        self.assertEqual(
            (None, self.IMG, True), (ns.database, ns.dump_file, ns.neutralize)
        )

    def test_valeur_manquante(self):
        for args in (["--image"], ["--image="]):
            with self.assertRaises(ValueError):
                A.replace_image_option("load", args)

    def test_deux_fois(self):
        with self.assertRaises(ValueError):
            A.replace_image_option("load", ["--image", "a", "--image=b"])

    def test_absent_inchange(self):
        args = ["-n", "base_bidon", "f.zip"]
        self.assertEqual(args, A.replace_image_option("load", args))

    def test_autre_sous_commande_inchangee(self):
        args = ["--image", "img", "a", "b"]
        self.assertEqual(args, A.replace_image_option("duplicate", args))


if __name__ == "__main__":
    unittest.main()
