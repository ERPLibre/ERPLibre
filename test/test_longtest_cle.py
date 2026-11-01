#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La clé ssh que les tests longs donnent à leurs VM.

Sans ~/.ssh/id_ed25519.pub ni id_rsa.pub, une VM démarre sans accès ssh :
la clé jetable des tests longs prend alors le relais, créée une fois puis
réutilisée, sans toucher ~/.ssh.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "long_test"))

import descente  # noqa: E402


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen absent")
class TestCleJetable(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.maison)
        patch = mock.patch.dict(os.environ, {"HOME": self.maison})
        patch.start()
        self.addCleanup(patch.stop)

    def test_sans_cle_par_defaut_une_cle_jetable_est_creee(self):
        pub = descente.cle_publique()
        attendu = os.path.join(
            self.maison, ".erplibre/longtest/ssh/id_ed25519.pub"
        )
        self.assertEqual(pub, attendu)
        self.assertTrue(os.path.exists(pub[:-4]))
        self.assertFalse(os.path.exists(os.path.join(self.maison, ".ssh")))
        mode = os.stat(os.path.dirname(pub)).st_mode & 0o777
        self.assertEqual(mode, 0o700)

    def test_la_cle_jetable_est_reutilisee(self):
        premiere = descente.cle_publique()
        contenu = Path(premiere).read_text()
        self.assertEqual(descente.cle_publique(), premiere)
        self.assertEqual(Path(premiere).read_text(), contenu)

    def test_la_cle_par_defaut_passe_avant(self):
        ssh = os.path.join(self.maison, ".ssh")
        os.makedirs(ssh)
        Path(ssh, "id_ed25519.pub").write_text("ssh-ed25519 AAAA test\n")
        self.assertEqual(
            descente.cle_publique(), os.path.join(ssh, "id_ed25519.pub")
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.maison, ".erplibre"))
        )

    def test_sans_creer_le_chemin_seul(self):
        """Un essai à blanc nomme la clé sans la créer ni rien lancer."""
        with mock.patch.object(
            descente.subprocess, "run", side_effect=AssertionError("lancé")
        ):
            pub = descente.cle_publique(creer=False)
        self.assertEqual(
            pub,
            os.path.join(self.maison, ".erplibre/longtest/ssh/id_ed25519.pub"),
        )
        self.assertEqual(os.listdir(self.maison), [])

    def test_echec_de_ssh_keygen_rend_vide(self):
        with mock.patch.object(
            descente.subprocess, "run", side_effect=OSError("absent")
        ):
            self.assertEqual(descente.cle_publique(), "")


if __name__ == "__main__":
    unittest.main()
