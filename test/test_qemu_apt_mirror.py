#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le miroir apt d'une VM Ubuntu, tel que son cloud-config l'écrit.

Derrière le cache, le miroir est fixe (« uri: ») : la recherche de
cloud-init (« search: ») écarte tout miroir derrière un résolveur qui répond
à tout nom, et une VM qui tire d'un autre miroir que les précédentes ne
retrouve rien de ce que le cache a gardé.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as DQ  # noqa: E402


class TestLeMiroirApt(unittest.TestCase):
    def _apt(self, *extra):
        args = DQ.build_parser().parse_args(
            ["--distro", "ubuntu", "--hostname", "vm", *extra]
        )
        return yaml.safe_load(DQ.build_cloud_config(args, None, []))["apt"]

    def _ca(self):
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".pem", delete=False, encoding="utf-8"
        )
        self.addCleanup(Path(f.name).unlink)
        f.write(
            "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
        )
        f.close()
        return f.name

    def test_sans_cache_cloud_init_cherche(self):
        apt = self._apt()
        for bloc in ("primary", "security"):
            self.assertEqual(apt[bloc][0]["search"], DQ.APT_MIRRORS_MAIN)
            self.assertNotIn("uri", apt[bloc][0])

    def test_derriere_le_cache_le_premier_miroir_est_fixe(self):
        apt = self._apt("--cache-ca", self._ca())
        for bloc in ("primary", "security"):
            self.assertEqual(apt[bloc][0]["uri"], DQ.APT_MIRRORS_MAIN[0])
            self.assertNotIn("search", apt[bloc][0])

    def test_un_miroir_impose_est_fixe(self):
        miroir = "http://miroir.invalid/ubuntu"
        apt = self._apt("--apt-mirror", miroir)
        self.assertEqual(apt["primary"][0]["uri"], miroir)
        self.assertNotIn("search", apt["primary"][0])

    def test_les_arches_ports_fixent_leur_propre_miroir(self):
        lignes = DQ.apt_mirror_lines("arm64", fixe=True)
        self.assertIn(f"      uri: {DQ.APT_MIRRORS_PORTS[0]}", lignes)


if __name__ == "__main__":
    unittest.main()
