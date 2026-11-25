#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Voies d'installation proposées (script/erp_common/support).

Ce qui se garde :
- l'installation native n'est proposée que sur une famille de paquets
  connue, sous systemd pour la production, et sous macOS avec Homebrew ;
- sous NixOS, la raison rendue est celle que l'ERP fournit, telle quelle ;
- la voie conteneur suit le moteur, ou la capacité d'en installer un.
Les raisons sont des clés i18n : leur texte exact fait partie du contrat.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.erp_common import support  # noqa: E402

# Raisons NixOS de deux ERP : celle de Dolibarr et une inventée, pour
# prouver que la raison vient de l'appelant.
NIXOS_REASONS = (
    "on NixOS, declare services.dolibarr in conf/nixos/erplibre.nix",
    "on NixOS, declare services.acme in conf/nixos/erplibre.nix",
)


class TestNativeSupport(unittest.TestCase):
    # (système, famille, nixos, systemd, mode) -> (proposé, raison) ; None
    # pour raison : celle de NixOS que l'appelant a fournie.
    CAS = (
        (("Linux", "apt-get", False, True, "dev"), (True, "")),
        (("Linux", "zypper", False, True, "prod"), (True, "")),
        (("Linux", "dnf", False, False, "dev"), (True, "")),
        (
            ("Linux", "pacman", False, False, "prod"),
            (False, "native production needs systemd"),
        ),
        (
            ("Linux", None, False, True, "dev"),
            (False, "unsupported system for a native install"),
        ),
        (("Linux", None, True, True, "dev"), (False, None)),
        (("Darwin", "brew", False, False, "dev"), (True, "")),
        (
            ("Darwin", "brew", False, False, "prod"),
            (False, "native production needs systemd"),
        ),
        (
            ("Darwin", None, False, False, "dev"),
            (False, "a native install on macOS needs Homebrew"),
        ),
        (
            ("Windows", None, False, False, "dev"),
            (False, "unsupported system for a native install"),
        ),
    )

    def test_matrix(self):
        for nixos in NIXOS_REASONS:
            for args, (ok, raison) in self.CAS:
                attendu = (ok, nixos if raison is None else raison)
                with self.subTest(args=args, nixos=nixos):
                    self.assertEqual(
                        support.native_support(*args, nixos), attendu
                    )


class TestContainerSupport(unittest.TestCase):
    # (système, famille, moteur utilisable) -> (proposé, raison)
    CAS = (
        # Un moteur qui répond suffit, où que l'on soit.
        (("Darwin", None, True), (True, "")),
        # Sans moteur : proposé là où install_container.sh sait l'installer.
        (("Linux", "apt-get", False), (True, "")),
        (("Linux", "pacman", False), (True, "")),
        (
            ("Linux", None, False),
            (False, "no container engine, and none can be installed here"),
        ),
        (("Darwin", "brew", False), (False, "install Docker Desktop first")),
        (("Windows", None, False), (False, "install Docker Desktop first")),
    )

    def test_matrix(self):
        for args, attendu in self.CAS:
            with self.subTest(args=args):
                self.assertEqual(support.container_support(*args), attendu)


if __name__ == "__main__":
    unittest.main()
