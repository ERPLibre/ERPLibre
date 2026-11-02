#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lecture de conf/module_list_image_db_odoo.json pour le menu Image Odoo :
les versions qui ont des images, et les images d'une version."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from script.database import image_db as I  # noqa: E402

CONFIG = {
    "odoo16.0_base": {"image_list": []},
    "odoo16.0_website": {"base": "odoo16.0_base", "image_list": []},
    "odoo16.0_old": {"disable": True, "image_list": []},
    "odoo9.0_base": {"image_list": []},
    "odoo18.0_base": {"image_list": []},
    "odoo17.0_base": {"disable": True, "image_list": []},
    "erplibre_code_generator": {"image_list": []},
}


class TestImageDbConfig(unittest.TestCase):
    def test_versions_sorted_numerically_disabled_left_out(self):
        self.assertEqual(
            I.versions_with_images(CONFIG), ["9.0", "16.0", "18.0"]
        )

    def test_images_of_a_version_in_file_order(self):
        self.assertEqual(
            I.images_of_version(CONFIG, "16.0"),
            ["odoo16.0_base", "odoo16.0_website"],
        )

    def test_a_version_is_not_the_prefix_of_another(self):
        config = {"odoo1.0_base": {}, "odoo16.0_base": {}}
        self.assertEqual(I.images_of_version(config, "1.0"), ["odoo1.0_base"])

    def test_missing_or_broken_file_gives_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(I.load_image_config(os.path.join(tmp, "x")), {})
            casse = os.path.join(tmp, "casse.json")
            with open(casse, "w") as f:
                f.write("{")
            self.assertEqual(I.load_image_config(casse), {})

    def test_the_repository_configuration_reads(self):
        config = I.load_image_config(os.path.join(ROOT, I.CONFIG_IMAGE_DB))
        self.assertIn("18.0", I.versions_with_images(config))
        self.assertIn("odoo18.0_base", I.images_of_version(config, "18.0"))


class TestChoixDeVersion(unittest.TestCase):
    """Le choix de version du menu Image Odoo. get_odoo_version y est simulé
    avec son vrai format : des noms de dossier, « odoo18.0 », là où les
    versions des images sont nues, « 18.0 »."""

    def setUp(self):
        from unittest.mock import MagicMock, patch

        from script.todo import todo

        self.todo = todo.TODO.__new__(todo.TODO)
        self.todo.execute = MagicMock()
        self.todo.execute.exec_command_live.return_value = 0
        p = patch.object(
            todo,
            "get_odoo_version",
            return_value=([], ["odoo17.0", "odoo18.0"], "odoo18.0"),
        )
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(I, "load_image_config", return_value=CONFIG)
        p.start()
        self.addCleanup(p.stop)
        self.invite = []
        self.reponses = []

        def repondre(question=""):
            self.invite.append(question)
            return self.reponses.pop(0)

        p = patch("builtins.input", side_effect=repondre)
        p.start()
        self.addCleanup(p.stop)
        p = patch("builtins.print")
        p.start()
        self.addCleanup(p.stop)

    def choisir(self, *reponses, generer=True):
        self.reponses = list(reponses)
        return self.todo._image_db_choose_version(generer=generer)

    def test_la_version_active_ne_propose_pas_de_basculer(self):
        # 3 : 18.0 dans ["9.0", "16.0", "18.0"]
        self.assertEqual("18.0", self.choisir("3"))
        self.assertEqual(1, len(self.invite), self.invite)
        self.todo.execute.exec_command_live.assert_not_called()

    def test_une_autre_version_installee_bascule_apres_accord(self):
        from unittest.mock import patch

        config = dict(CONFIG, **{"odoo17.0_base": {"image_list": []}})
        with patch.object(I, "load_image_config", return_value=config):
            # ["9.0", "16.0", "17.0", "18.0"] : 3 vaut 17.0
            self.assertEqual("17.0", self.choisir("3", "o"))
        self.todo.execute.exec_command_live.assert_called_once_with(
            "make switch_odoo_17", source_erplibre=False
        )

    def test_une_version_absente_est_refusee(self):
        self.assertIsNone(self.choisir("2"))
        self.todo.execute.exec_command_live.assert_not_called()

    def test_lister_ne_bascule_jamais(self):
        self.assertEqual("16.0", self.choisir("2", generer=False))
        self.todo.execute.exec_command_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
