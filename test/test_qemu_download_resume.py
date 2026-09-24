#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un transfert coupé se reprend-il, et le fichier est-il intact ?

Une image de VM pèse un demi-gigaoctet : une coupure y est bien plus probable
que sur une page, et repartir de zéro à chaque fois peut ne jamais aboutir. Le
contrôle de complétude existait déjà — sans lui un .part tronqué passait pour
une image, donnant un qcow2 valide mais VIDE, et une VM qui ne démarre pas —
mais il jetait les octets reçus.

Deux pièges que ces tests gardent :

- les octets déjà écrits sont CONSERVÉS entre deux essais, et la suite est
  demandée par « Range ». Les jeter rendrait chaque reprise aussi longue que
  le premier essai ;
- un serveur qui IGNORE « Range » rend 200 et le fichier entier : il faut
  alors repartir de zéro, sans quoi les octets déjà là seraient doublés et
  l'image illisible.
"""

import http.server
import sys
import tempfile
import threading
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as d  # noqa: E402

CONTENU = b"".join(bytes([i % 251]) for i in range(60_000))


class Serveur:
    """Un serveur qui coupe ses `coupures` premiers transferts au tiers."""

    def __init__(self, coupures, honore_range=True):
        self.restantes = coupures
        self.honore_range = honore_range
        self.demandes = []
        contexte = self

        class Poignee(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                rng = self.headers.get("Range")
                contexte.demandes.append(rng)
                debut = 0
                if rng and contexte.honore_range:
                    debut = int(rng.split("=")[1].split("-")[0])
                    self.send_response(206)
                    self.send_header(
                        "Content-Range",
                        f"bytes {debut}-{len(CONTENU) - 1}/{len(CONTENU)}",
                    )
                else:
                    self.send_response(200)
                reste = CONTENU[debut:]
                self.send_header("Content-Length", str(len(reste)))
                self.end_headers()
                if contexte.restantes > 0:
                    contexte.restantes -= 1
                    self.wfile.write(reste[: len(reste) // 3])
                else:
                    self.wfile.write(reste)

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Poignee)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/image.qcow2"

    def arrete(self):
        self.httpd.shutdown()


class TestLaReprise(unittest.TestCase):
    def telecharge(self, serveur):
        self.addCleanup(serveur.arrete)
        with tempfile.TemporaryDirectory() as coin:
            dest = Path(coin) / "image.qcow2"
            d.download_image([serveur.url], dest, dry_run=False, timeout=10)
            return dest.read_bytes()

    def test_une_coupure_est_reprise(self):
        serveur = Serveur(coupures=1)
        self.assertEqual(CONTENU, self.telecharge(serveur))

    def test_deux_coupures_sont_reprises(self):
        serveur = Serveur(coupures=2)
        self.assertEqual(CONTENU, self.telecharge(serveur))

    def test_la_suite_est_demandee_par_range(self):
        """Sans Range, la reprise retéléchargerait tout."""
        serveur = Serveur(coupures=1)
        self.telecharge(serveur)
        self.assertIsNone(serveur.demandes[0])
        self.assertTrue(serveur.demandes[1].startswith("bytes="))

    def test_un_serveur_qui_ignore_range_repart_de_zero(self):
        """Sinon les octets déjà là seraient doublés, et l'image illisible."""
        serveur = Serveur(coupures=1, honore_range=False)
        self.assertEqual(CONTENU, self.telecharge(serveur))

    def test_au_dela_des_reprises_le_miroir_suivant(self):
        """Trois essais, puis on change de miroir plutôt que d'insister."""
        serveur = Serveur(coupures=d.REPRISES_MAX)
        self.addCleanup(serveur.arrete)
        with tempfile.TemporaryDirectory() as coin:
            dest = Path(coin) / "image.qcow2"
            with self.assertRaises(SystemExit):
                d.download_image([serveur.url], dest, False, timeout=10)
            self.assertFalse(
                dest.with_suffix(dest.suffix + ".part").exists(),
                "le .part tronqué doit partir, il empoisonnerait le cache",
            )


if __name__ == "__main__":
    unittest.main()
