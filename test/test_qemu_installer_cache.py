#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""debian-installer approuve l'autorité du cache, comme cloud-init ailleurs.

Debian s390x s'installe par debian-installer et non par une image cloud :
aucun cloud-init n'y pose l'autorité du cache. Le cache intercepte pourtant
ses téléchargements HTTPS, qui échouent tous sur « certificate signer not
trusted ». Le late_command du preseed copie donc l'autorité et exécute les
mêmes gestes que cache_commands ; les fichiers voyagent dans l'initrd.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as DQ  # noqa: E402

# Un certificat inventé : seul son en-tête est lu.
PEM = "-----BEGIN CERTIFICATE-----\nMIIBfaux\n-----END CERTIFICATE-----\n"


class TestPreseedCache(unittest.TestCase):
    def setUp(self):
        fd, self.ca = tempfile.mkstemp(suffix=".crt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(PEM)
        self.addCleanup(os.unlink, self.ca)

    def _args(self, *extra):
        return DQ.build_parser().parse_args(
            ["--distro", "debian", "--arch", "s390x", "--hostname", "x"] + list(extra)
        )

    def _late(self, args):
        pre = DQ.build_preseed(args, "$6$x$y", [])
        ligne = [l for l in pre.splitlines() if l.startswith("d-i preseed/late_")]
        self.assertEqual(1, len(ligne))
        return ligne[0]

    def test_the_authority_is_copied_then_approved(self):
        late = self._late(self._args("--cache-ca", self.ca))
        ancre = f"{DQ.CACHE_TRUST['apt'][0]}/{DQ.CACHE_CERT_NAME}"
        copie = late.index(f"/target{ancre}")
        script = late.index(f"in-target sh {DQ.CACHE_INSTALLER_SCRIPT}")
        self.assertLess(copie, script)

    def test_the_late_command_still_ends_on_true(self):
        """d-i s'arrête si la dernière commande échoue."""
        late = self._late(self._args("--cache-ca", self.ca))
        self.assertTrue(late.endswith("; true"), late[-80:])

    def test_the_script_runs_the_cache_commands(self):
        args = self._args("--cache-ca", self.ca)
        fichiers = dict((p, c) for p, _m, c, _o in DQ.installer_cache_files(args))
        script = fichiers[DQ.CACHE_INSTALLER_SCRIPT]
        for commande in DQ.cache_commands(args):
            self.assertIn(commande, script)

    def test_nothing_without_an_authority(self):
        args = self._args()
        self.assertEqual([], DQ.installer_cache_files(args))
        self.assertNotIn(DQ.CACHE_INSTALLER_SCRIPT, self._late(args))

    def test_nothing_when_the_vm_bypasses_the_cache(self):
        args = self._args("--cache-ca", self.ca, "--cache-bypass")
        self.assertEqual([], DQ.installer_cache_files(args))


class TestInitrdShipsWhatLateCommandCopies(unittest.TestCase):
    """Chaque « cp /erplibre-… » du late_command a son fichier dans la liste
    que l'appel range dans l'initrd."""

    def test_every_copied_source_is_shipped(self):
        fd, ca = tempfile.mkstemp(suffix=".crt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(PEM)
        self.addCleanup(os.unlink, ca)
        args = DQ.build_parser().parse_args(
            [
                "--distro",
                "debian",
                "--arch",
                "s390x",
                "--hostname",
                "x",
                "--cache-ca",
                ca,
            ]
        )
        pre = DQ.build_preseed(args, "$6$x$y", [])
        livres = {
            DQ.installer_guide_name(p)
            for p, _m, _c, _o in DQ.guide_files(args) + DQ.installer_cache_files(args)
        }
        copies = {
            mot[1:]
            for mot in pre.split()
            if mot.startswith("/" + DQ.INSTALLER_GUIDE_PREFIX)
        }
        self.assertTrue(copies)
        self.assertLessEqual(copies, livres)

    def test_the_call_site_passes_them(self):
        source = (RACINE / "script/qemu/deploy_qemu.py").read_text(encoding="utf-8")
        self.assertIn("guide=guide_files(args) + installer_cache_files(args)", source)


if __name__ == "__main__":
    unittest.main(verbosity=1)
