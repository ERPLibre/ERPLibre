#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les certificats locaux du mandataire : une autorité, un certificat serveur.

Les fichiers sont réellement produits par openssl dans un répertoire
temporaire, puis relus par openssl et par le module ssl de Python.
"""

import os
import shutil
import ssl
import stat
import subprocess
import tempfile
import unittest

from script.reverse_proxy import local_cert


@unittest.skipUnless(shutil.which("openssl"), "openssl absent")
class TestCertificatsLocaux(unittest.TestCase):
    def setUp(self):
        self.dossier = os.path.join(tempfile.mkdtemp(), "tls")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.dossier))

    def texte(self, crt):
        return subprocess.run(
            ["openssl", "x509", "-in", crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def test_le_serveur_est_signe_par_l_autorite(self):
        chemins = local_cert.issue(self.dossier, ["localhost", "127.0.0.1"])
        contexte = ssl.create_default_context(cafile=chemins["ca_crt"])
        # Le chargement échoue si la clé ne correspond pas au certificat.
        serveur = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        serveur.load_cert_chain(chemins["server_crt"], chemins["server_key"])
        verif = subprocess.run(
            [
                "openssl",
                "verify",
                "-CAfile",
                chemins["ca_crt"],
                chemins["server_crt"],
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(verif.returncode, 0, verif.stdout + verif.stderr)
        self.assertIsNotNone(contexte)

    def test_les_noms_vont_dans_le_subject_alt_name(self):
        chemins = local_cert.issue(
            self.dossier, ["localhost", "127.0.0.1", "odoo.test", "::1"]
        )
        texte = self.texte(chemins["server_crt"])
        for attendu in (
            "DNS:localhost",
            "DNS:odoo.test",
            "IP Address:127.0.0.1",
            "IP Address:0:0:0:0:0:0:0:1",
        ):
            self.assertIn(attendu, texte)
        self.assertIn("TLS Web Server Authentication", texte)

    def test_les_cles_ne_sont_lisibles_que_par_leur_proprietaire(self):
        chemins = local_cert.issue(self.dossier, ["localhost"])
        for cle in (chemins["ca_key"], chemins["server_key"]):
            mode = stat.S_IMODE(os.stat(cle).st_mode)
            self.assertEqual(mode, 0o600, f"{cle} en {oct(mode)}")
        mode = stat.S_IMODE(os.stat(self.dossier).st_mode)
        self.assertEqual(mode, 0o700)

    def test_l_autorite_se_garde_d_une_emission_a_l_autre(self):
        # Importée une fois dans le navigateur, elle doit rester la même :
        # une nouvelle autorité ferait réapparaître l'alerte.
        premier = local_cert.issue(self.dossier, ["localhost"])
        with open(premier["ca_crt"], "rb") as f:
            avant = f.read()
        second = local_cert.issue(self.dossier, ["localhost", "odoo.test"])
        with open(second["ca_crt"], "rb") as f:
            self.assertEqual(f.read(), avant)
        self.assertIn("DNS:odoo.test", self.texte(second["server_crt"]))

    def test_l_existence_se_constate(self):
        self.assertFalse(local_cert.exists(self.dossier))
        local_cert.issue(self.dossier, ["localhost"])
        self.assertTrue(local_cert.exists(self.dossier))


class TestNomsParDefaut(unittest.TestCase):
    def test_la_boucle_locale_y_est_toujours(self):
        noms = local_cert.default_names()
        for attendu in ("localhost", "127.0.0.1", "::1"):
            self.assertIn(attendu, noms)
        self.assertEqual(len(noms), len(set(noms)))


if __name__ == "__main__":
    unittest.main()
