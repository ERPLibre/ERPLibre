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


if __name__ == "__main__":
    unittest.main()
