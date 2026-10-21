#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cloud-config efface l'échec de systemd-firstboot.

Une image dont la ligne de commande noyau désigne une console absente
(« console=ttyS0 » sur s390x) fait échouer systemd-firstboot au premier
démarrage : le système reste « degraded » et chaque connexion affiche
« Failed Units ». Le runcmd efface cet échec, sans dépendre de l'architecture.
"""

import sys
import unittest
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as d  # noqa: E402

COMMANDE = "systemctl reset-failed systemd-firstboot.service"


def _runcmd(*options):
    args = d.build_parser().parse_args(
        ["--distro", "fedora", "--version", "43", "--hostname", "x"]
        + list(options)
    )
    return yaml.safe_load(d.build_cloud_config(args, None, []))["runcmd"]


class TestFirstbootReset(unittest.TestCase):
    def test_the_failure_is_cleared_on_s390x(self):
        self.assertTrue(
            any(COMMANDE in c for c in _runcmd("--arch", "s390x"))
        )

    def test_it_is_harmless_elsewhere(self):
        """Sans échec à effacer, la commande ne fait rien et ne fait jamais
        échouer runcmd."""
        ligne = next(c for c in _runcmd() if COMMANDE in c)
        self.assertTrue(ligne.rstrip().endswith("|| true"), ligne)


if __name__ == "__main__":
    unittest.main(verbosity=1)
