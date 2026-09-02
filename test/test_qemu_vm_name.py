#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le nom de VM du parc : que porte-t-il, et que retrouve-t-on dedans ?

Le nom se lit dans les deux sens. `_qemu_infra_name` le fabrique à partir de
(distro, version, archi) ; `_qemu_vm_meta` remonte de ce nom à la version en
rejouant le catalogue. Les deux doivent rester en miroir : une règle ajoutée
d'un seul côté rend une VM introuvable dans son propre parc.

Une distribution en publication continue n'a qu'une version, « latest », qui
ne distingue donc rien — elle sort du nom. Une version nommée qui coexiste
avec d'autres au catalogue, tumbleweed, reste.
"""

import unittest
from unittest.mock import patch

from script.todo.todo import TODO


class TestInfraName(unittest.TestCase):
    """Ce que le nom porte selon la distribution et l'architecture."""

    def setUp(self):
        patcher = patch.object(
            TODO, "_native_arch", staticmethod(lambda: "amd64")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rolling_release_drops_the_version(self):
        self.assertEqual(
            TODO._qemu_infra_name("arch", "latest", "amd64"), "erplibre-arch"
        )

    def test_rolling_release_keeps_the_foreign_arch(self):
        self.assertEqual(
            TODO._qemu_infra_name("arch", "latest", "arm64"),
            "erplibre-arch-arm64",
        )

    def test_named_version_stays(self):
        """tumbleweed coexiste avec Leap au catalogue : le nom doit trancher."""
        self.assertEqual(
            TODO._qemu_infra_name("opensuse", "tumbleweed", "amd64"),
            "erplibre-opensuse-tumbleweed",
        )

    def test_numbered_version_loses_only_its_dots(self):
        self.assertEqual(
            TODO._qemu_infra_name("ubuntu", "24.04", "amd64"),
            "erplibre-ubuntu-2404",
        )

    def test_every_catalogue_entry_yields_a_distinct_name(self):
        """Deux entrées du catalogue ne peuvent pas porter le même nom."""
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "script"
            / "qemu"
            / "deploy_qemu.py"
        )
        spec = importlib.util.spec_from_file_location("deploy_qemu", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        noms = [
            TODO._qemu_infra_name(distro, version, "amd64")
            for distro, (versions, _default) in mod.DISTROS.items()
            for version in versions
        ]
        self.assertEqual(len(noms), len(set(noms)), sorted(noms))


class TestNameRoundTrip(unittest.TestCase):
    """_qemu_vm_meta retrouve la version que _qemu_infra_name a effacée."""

    def test_rolling_release_resolves_back_to_latest(self):
        todo = TODO()
        with patch.object(
            TODO, "_qemu_vm_arch", lambda self, name: "amd64"
        ), patch.object(TODO, "_native_arch", staticmethod(lambda: "amd64")):

            class Catalogue:
                DISTROS = {"arch": (["latest"], "latest")}

            self.assertEqual(
                todo._qemu_vm_meta("erplibre-arch", Catalogue()),
                ("arch", "latest", "amd64"),
            )


if __name__ == "__main__":
    unittest.main()
