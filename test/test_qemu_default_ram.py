#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""RAM par défaut d'une VM : au moins 4 Gio sur s390x, le catalogue ailleurs.

Le catalogue donne le minimum pour démarrer chaque distribution. Sur s390x,
l'installation d'ERPLibre compile presque tout, et un seul cc1plus demande
jusqu'à 2,5 Gio : 2 Gio y tuent la compilation. La CLI (deploy_qemu.py) et le
formulaire de TODO tirent ce défaut de la même fonction.
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as d  # noqa: E402
from script.todo.qemu_deploy import QemuDeployMixin  # noqa: E402


class TestDefaultRam(unittest.TestCase):
    def test_s390x_is_raised_to_4096(self):
        self.assertEqual(4096, d.default_ram("s390x", 2048))
        self.assertEqual(4096, d.default_ram("s390x", 3072))

    def test_s390x_never_lowers_a_larger_catalogue_value(self):
        self.assertEqual(8192, d.default_ram("s390x", 8192))

    def test_other_architectures_keep_the_catalogue(self):
        for arch in ("amd64", "arm64"):
            self.assertEqual(2048, d.default_ram(arch, 2048))
            self.assertEqual(3072, d.default_ram(arch, 3072))


class _Formulaire(QemuDeployMixin):
    """Juste ce qu'il faut du menu pour bâtir le catalogue."""

    def _qemu_arches_for(self, distro, arch):
        return [arch]


class TestCatalogueDuFormulaire(unittest.TestCase):
    """Le formulaire propose ce qu'un déploiement direct ferait."""

    def _entrees(self, arch):
        return _Formulaire()._qemu_catalog_entries(
            d, ["ubuntu", "fedora"], arch
        )

    def test_s390x_entries_default_to_4096(self):
        entrees = self._entrees("s390x")
        self.assertTrue(entrees)
        for e in entrees:
            self.assertGreaterEqual(e["ram"], 4096, e)

    def test_other_entries_keep_the_catalogue_minimum(self):
        for arch in ("amd64", "arm64"):
            entrees = self._entrees(arch)
            self.assertTrue(entrees, arch)
            for e in entrees:
                _c, _o, ram, _disk = d.DISTROS[e["distro"]][0][e["version"]]
                self.assertEqual(ram, e["ram"], e)


if __name__ == "__main__":
    unittest.main(verbosity=1)
