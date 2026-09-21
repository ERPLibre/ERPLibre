#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une sauvegarde qui n'a pas eu lieu ne doit pas s'annoncer réussie.

C'EST LA PANNE QUI SE PAIE LE PLUS TARD. Un refus de mot de passe maître,
une base absente, un Odoo en erreur : le serveur répond une page HTML, et
`curl` SANS `--fail` la reçoit comme un corps de réponse ordinaire. Il rend
zéro, écrit la page dans le fichier de sortie, et le script annonce
« Backup completed successfully! ».

Il reste alors, sous le nom d'une sauvegarde, quelques dizaines d'octets de
HTML. Rien ne le distingue d'une vraie tant qu'on ne l'ouvre pas — et on ne
l'ouvre que le jour où l'on en a besoin.

Le contrôle porte sur le COMPORTEMENT : un serveur de banc répond ce qu'on
lui dit, et l'épreuve regarde le code de sortie, l'écran et ce qui reste sur
le disque.
"""

import http.server
import os
import subprocess
import sys
import tempfile
import threading
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(RACINE, "script", "database", "download_remote.sh")

# Un vrai fichier ZIP minimal : l'en-tête que tout outil reconnaît, suivi
# d'un catalogue central vide. C'est ce qu'un Odoo en bonne santé renvoie.
ZIP_VIDE = b"PK\x05\x06" + b"\x00" * 18


class ServeurDeBanc(http.server.BaseHTTPRequestHandler):
    """Répond ce que la classe lui dit. Ne journalise rien."""

    code = 200
    corps = ZIP_VIDE

    def do_POST(self):
        self.send_response(type(self).code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(type(self).corps)))
        self.end_headers()
        self.wfile.write(type(self).corps)

    def log_message(self, *args):
        pass


class CasDeSauvegarde(unittest.TestCase):
    def lancer(self, code, corps):
        ServeurDeBanc.code = code
        ServeurDeBanc.corps = corps
        serveur = http.server.HTTPServer(("127.0.0.1", 0), ServeurDeBanc)
        port = serveur.server_address[1]
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        dossier = tempfile.mkdtemp()
        sortie = os.path.join(dossier, "base.zip")
        try:
            vu = subprocess.run(
                ["bash", SCRIPT, "--quiet"],
                env=dict(
                    os.environ,
                    MASTER_PWD="motdepasse",
                    DATABASE_NAME="base",
                    OUTPUT_FILE_PATH=sortie,
                    ODOO_URL=f"http://127.0.0.1:{port}",
                ),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=60,
            )
        finally:
            serveur.shutdown()
        existe = os.path.exists(sortie)
        contenu = open(sortie, "rb").read() if existe else b""
        return vu, existe, contenu


class TestUneSauvegardeQuiNaPasEuLieu(CasDeSauvegarde):
    """Le serveur refuse, et le script doit le dire."""

    def test_a_refused_backup_does_not_exit_zero(self):
        """Sortir zéro fait passer la panne inaperçue d'un automate, et
        c'est ainsi qu'on découvre l'absence le jour de la restauration."""
        vu, _e, _c = self.lancer(500, b"<html>Access Denied</html>")
        self.assertNotEqual(0, vu.returncode)

    def test_a_refused_backup_never_says_it_succeeded(self):
        vu, _e, _c = self.lancer(500, b"<html>Access Denied</html>")
        self.assertNotIn("successfully", vu.stdout)

    def test_a_refused_backup_leaves_no_file_under_the_backup_name(self):
        """Quelques dizaines d'octets de HTML sous le nom d'une sauvegarde
        ne se distinguent d'une vraie qu'en l'ouvrant — et on ne l'ouvre
        que le jour où l'on en a besoin."""
        _v, existe, contenu = self.lancer(500, b"<html>Access Denied</html>")
        self.assertFalse(existe, f"reste {contenu[:40]!r}")

    def test_a_wrong_master_password_page_is_not_a_backup(self):
        """Odoo répond 200 avec une page d'erreur quand le mot de passe
        maître est faux : le code HTTP seul ne suffit donc pas."""
        vu, existe, _c = self.lancer(
            200, b"<html><body>Access Denied</body></html>"
        )
        self.assertNotEqual(0, vu.returncode)
        self.assertFalse(existe)


class TestLeCodeHttpEtLeContenuSeCouvrentLUnLAutre(CasDeSauvegarde):
    """Deux gardes, et aucune ne recouvre l'autre.

    Le contrôle du contenu attrape un 200 qui porte une page d'erreur —
    Odoo répond ainsi sur un mot de passe maître refusé. Le contrôle du
    code HTTP attrape un refus dont le corps ressemble à une archive, ce
    qu'un mandataire ou un pare-feu applicatif produit sans peine.

    Retirer « --fail » ne faisait rougir AUCUNE épreuve tant que ce cas
    manquait : la mutation l'a montré, et c'est elle qui a écrit cette
    classe.
    """

    def test_a_refusal_whose_body_looks_like_an_archive_is_caught(self):
        vu, existe, _c = self.lancer(500, b"PK\x03\x04 pas une archive")
        self.assertNotEqual(0, vu.returncode)
        self.assertFalse(existe)

    def test_a_two_hundred_that_is_not_an_archive_is_caught(self):
        """Le code HTTP seul ne suffit pas : c'est la réponse d'Odoo à un
        mot de passe maître refusé."""
        vu, existe, _c = self.lancer(200, b"<html>Access Denied</html>")
        self.assertNotEqual(0, vu.returncode)
        self.assertFalse(existe)


class TestUneVraieSauvegarde(CasDeSauvegarde):
    """Contrôle positif : refuser toujours ne serait pas mieux."""

    def test_a_real_archive_is_kept_and_announced(self):
        vu, existe, contenu = self.lancer(200, ZIP_VIDE)
        self.assertEqual(0, vu.returncode, vu.stdout + vu.stderr)
        self.assertTrue(existe)
        self.assertEqual(ZIP_VIDE, contenu)
        self.assertIn("successfully", vu.stdout)


class TestCeQueLeScriptDemandeAvantDePartir(unittest.TestCase):
    """Sans mot de passe maître, rien ne part — et c'est déjà tenu."""

    def test_a_missing_master_password_is_refused(self):
        vu = subprocess.run(
            ["bash", SCRIPT, "--quiet"],
            env={
                k: v for k, v in os.environ.items() if k not in ("MASTER_PWD",)
            },
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        self.assertNotEqual(0, vu.returncode)
        self.assertIn("MASTER_PWD", vu.stderr)


if __name__ == "__main__":
    unittest.main()
