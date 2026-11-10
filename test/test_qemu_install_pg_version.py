#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le PostgreSQL exigé, passé aux profils d'installation des VM.

Dans une VM neuve, « make install_os » tourne avant qu'aucune version d'Odoo
ne soit active : sans .odoo-version, l'installeur ne peut pas déduire
l'exigence du catalogue. Les profils la passent donc en PG_VERSION, et celui
de toutes les versions passe la plus haute. Proxmox lit les mêmes profils.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import version_manager  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


def profils(todo):
    return dict(todo._qemu_install_profiles())


class TestProfilsReels(unittest.TestCase):
    """Sur le catalogue du dépôt."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.profils = profils(self.todo)

    def test_a_version_with_a_requirement_passes_it(self):
        self.assertEqual(
            "make install_os PG_VERSION=18 && make install_odoo_18",
            self.profils["ERPLibre + Odoo 18"],
        )

    def test_a_version_without_requirement_keeps_the_bare_command(self):
        self.assertEqual(
            "make install_os && make install_odoo_16",
            self.profils["ERPLibre + Odoo 16"],
        )

    def test_install_dev_gets_the_default_version_requirement(self):
        cmd = [c for c in self.profils.values() if "install_dev" in c][0]
        self.assertTrue(cmd.startswith("make install_os PG_VERSION=18 && "))

    def test_the_default_deploy_command_matches_its_profile(self):
        cmd = self.todo._qemu_erplibre_remote_cmd("master")
        self.assertIn(
            "make install_os PG_VERSION=18 && make install_odoo_18", cmd
        )


class TestToutesLesVersions(unittest.TestCase):
    """Sur un catalogue jetable : la plus haute exigence l'emporte."""

    def setUp(self):
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier)
        chemin = os.path.join(dossier, "catalogue.json")
        with open(chemin, "w") as handle:
            json.dump(
                {
                    "odoo16.0_python3.10.18": {"odoo_version": "16.0"},
                    "odoo18.0_python3.12.16": {
                        "odoo_version": "18.0",
                        "postgresql_version": "18",
                        "default": True,
                    },
                    "odoo19.0_python3.12.10": {
                        "odoo_version": "19.0",
                        "postgresql_version": "19",
                    },
                },
                handle,
            )
        patch = mock.patch.object(version_manager, "VERSION_DATA_FILE", chemin)
        patch.start()
        self.addCleanup(patch.stop)
        self.todo = TODO.__new__(TODO)

    def test_all_versions_profile_takes_the_highest_requirement(self):
        cmd = [c for c in profils(self.todo).values() if "all_version" in c][0]
        self.assertEqual(
            "make install_os PG_VERSION=19 && make install_odoo_all_version",
            cmd,
        )

    def test_each_version_keeps_its_own_requirement(self):
        tous = profils(self.todo)
        self.assertIn("PG_VERSION=18 ", tous["ERPLibre + Odoo 18"])
        self.assertIn("PG_VERSION=19 ", tous["ERPLibre + Odoo 19"])
        self.assertNotIn("PG_VERSION", tous["ERPLibre + Odoo 16"])

    def test_a_catalogue_without_requirement_changes_nothing(self):
        with open(version_manager.VERSION_DATA_FILE, "w") as handle:
            json.dump({"x": {"odoo_version": "16.0", "default": True}}, handle)
        for cmd in profils(self.todo).values():
            self.assertNotIn("PG_VERSION", cmd)

    def test_proxmox_offers_the_same_profiles(self):
        # proxmox_menu passe _qemu_install_profiles tel quel à son
        # formulaire, et _qemu_pick_install_profile à son invite.
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "script",
            "todo",
            "proxmox_menu.py",
        )
        with open(source) as handle:
            texte = handle.read()
        self.assertIn(
            '"install_profiles": self._qemu_install_profiles()', texte
        )
        self.assertIn("self._qemu_pick_install_profile(distro)", texte)


if __name__ == "__main__":
    unittest.main()
