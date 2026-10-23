#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Plusieurs installations sur la même image, et les erreurs passagères.

Des installations lancées ensemble visent la MÊME image en cache. Sans
verrou, chacune la télécharge en entier dans le même .part, et la première à
finir le renomme : les autres échouent sur « No such file or directory »
après avoir tiré tout le fichier. Ces tests gardent :

- un seul téléchargement pour N installations simultanées, qui toutes
  trouvent l'image intacte ;
- une image périmée (somme publiée différente) reprise UNE fois, et non une
  fois par installation ;
- une erreur passagère (503, délai dépassé) réessayée sur le même miroir, en
  reprenant le .part là où il s'est arrêté ;
- une erreur qui décrit le miroir (404) jamais réessayée.

Les fils d'exécution tiennent lieu de processus : flock oppose deux
descripteurs ouverts séparément, même dans un seul processus.
"""

import hashlib
import http.server
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as d  # noqa: E402

CONTENU = b"".join(bytes([i % 251]) for i in range(200_000))
SOMME = hashlib.sha256(CONTENU).hexdigest()


class Serveur:
    """Sert CONTENU lentement, et `<image>.SHA256` à côté.

    `pannes` : codes HTTP rendus aux premières demandes de l'image, dans
    l'ordre. `stalle` : nombre de transferts qui s'arrêtent au tiers et se
    taisent, pour faire expirer le délai du client."""

    def __init__(self, pannes=(), stalle=0, lent=0.002):
        self.pannes = list(pannes)
        self.stalle = stalle
        self.demandes = []
        contexte = self

        class Poignee(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.endswith(".SHA256"):
                    corps = f"{SOMME}  image.qcow2\n".encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(corps)))
                    self.end_headers()
                    self.wfile.write(corps)
                    return
                rng = self.headers.get("Range")
                contexte.demandes.append(rng)
                if contexte.pannes:
                    code = contexte.pannes.pop(0)
                    self.send_response(code)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                debut = int(rng.split("=")[1].split("-")[0]) if rng else 0
                self.send_response(206 if rng else 200)
                reste = CONTENU[debut:]
                self.send_header("Content-Length", str(len(reste)))
                self.end_headers()
                if contexte.stalle > 0:
                    contexte.stalle -= 1
                    self.wfile.write(reste[: len(reste) // 3])
                    self.wfile.flush()
                    time.sleep(2)
                    return
                for i in range(0, len(reste), 20_000):
                    self.wfile.write(reste[i : i + 20_000])
                    time.sleep(lent)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Poignee)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/image.qcow2"

    def arrete(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def en_parallele(nombre, cible):
    """Lance `cible(i)` dans `nombre` fils partis ensemble ; rend les
    exceptions levées, SystemExit compris."""
    depart = threading.Barrier(nombre)
    erreurs = []

    def fil(i):
        depart.wait()
        try:
            cible(i)
        except BaseException as exc:  # SystemExit inclus
            erreurs.append(exc)

    fils = [threading.Thread(target=fil, args=(i,)) for i in range(nombre)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(60)
    return erreurs


class TestInstallationsSimultanees(unittest.TestCase):
    def setUp(self):
        self.serveur = Serveur()
        self.addCleanup(self.serveur.arrete)
        coin = tempfile.TemporaryDirectory()
        self.addCleanup(coin.cleanup)
        self.dest = Path(coin.name) / "image.qcow2"

    def test_une_seule_image_tiree_pour_six_installations(self):
        erreurs = en_parallele(
            6,
            lambda i: d.download_image(
                [self.serveur.url], self.dest, False, timeout=10
            ),
        )
        self.assertEqual([], erreurs)
        self.assertEqual(1, len(self.serveur.demandes))
        self.assertEqual(CONTENU, self.dest.read_bytes())
        self.assertFalse(self.dest.with_suffix(".qcow2.part").exists())

    def test_une_image_perimee_reprise_une_seule_fois(self):
        """Six vérifications d'une image périmée : une reprise, pas six."""
        self.dest.write_bytes(b"ancienne version de l'image")
        erreurs = en_parallele(
            6,
            lambda i: d.verify_sha256(
                self.serveur.url,
                self.dest,
                False,
                "arch",
                (self.serveur.url,),
            ),
        )
        self.assertEqual([], erreurs)
        self.assertEqual(1, len(self.serveur.demandes))
        self.assertEqual(CONTENU, self.dest.read_bytes())

    def test_une_somme_qui_ne_correspond_jamais_borne_les_reprises(self):
        """Miroir dont l'image et la somme publiée divergent : toutes les
        installations échouent, mais aucune ne tire l'image deux fois de
        suite — au plus un téléchargement par installation."""
        self.dest.write_bytes(b"ancienne version de l'image")
        with mock.patch.object(d, "expected_sum", return_value="0" * 64):
            erreurs = en_parallele(
                6,
                lambda i: d.verify_sha256(
                    self.serveur.url,
                    self.dest,
                    False,
                    "arch",
                    (self.serveur.url,),
                ),
            )
        self.assertEqual(6, len(erreurs))
        self.assertTrue(all(isinstance(e, SystemExit) for e in erreurs))
        self.assertLessEqual(len(self.serveur.demandes), 6)
        self.assertFalse(self.dest.exists())

    def test_le_verrou_se_reprend_dans_le_meme_fil(self):
        """verify_sha256 retélécharge sous le verrou qu'il tient déjà."""
        with d.verrou_image(self.dest):
            with d.verrou_image(self.dest):
                pass
            d.download_image([self.serveur.url], self.dest, False, timeout=10)
        self.assertEqual(CONTENU, self.dest.read_bytes())


class TestErreursPassageres(unittest.TestCase):
    def setUp(self):
        # Le module « time » de deploy_qemu seul : celui du serveur de test,
        # qui ralentit ses envois, garde son vrai sommeil.
        horloge = mock.patch.object(d, "time", wraps=time)
        self.sommeil = horloge.start().sleep = mock.Mock()
        self.addCleanup(horloge.stop)
        coin = tempfile.TemporaryDirectory()
        self.addCleanup(coin.cleanup)
        self.dest = Path(coin.name) / "image.qcow2"

    def telecharge(self, serveur, timeout=10):
        self.addCleanup(serveur.arrete)
        d.download_image([serveur.url], self.dest, False, timeout=timeout)
        return self.dest.read_bytes()

    def test_un_503_est_reessaye_sur_le_meme_miroir(self):
        serveur = Serveur(pannes=[503, 502])
        self.assertEqual(CONTENU, self.telecharge(serveur))
        self.assertEqual(3, len(serveur.demandes))
        self.assertEqual(
            [mock.call(d.PAUSE_RESEAU), mock.call(2 * d.PAUSE_RESEAU)],
            self.sommeil.call_args_list,
        )

    def test_un_404_n_est_pas_reessaye(self):
        serveur = Serveur(pannes=[404])
        self.addCleanup(serveur.arrete)
        with self.assertRaises(SystemExit) as sortie:
            d.download_image([serveur.url], self.dest, False, timeout=10)
        self.assertEqual(1, len(serveur.demandes))
        self.assertIn("404", str(sortie.exception))
        self.sommeil.assert_not_called()

    def test_les_essais_sont_bornes(self):
        serveur = Serveur(pannes=[503] * d.REPRISES_MAX)
        self.addCleanup(serveur.arrete)
        with self.assertRaises(SystemExit):
            d.download_image([serveur.url], self.dest, False, timeout=10)
        self.assertEqual(d.REPRISES_MAX, len(serveur.demandes))

    def test_un_delai_depasse_reprend_le_part(self):
        """Le transfert se tait au tiers : la suite est demandée par Range,
        les octets déjà reçus ne sont pas retéléchargés."""
        serveur = Serveur(stalle=1)
        self.assertEqual(CONTENU, self.telecharge(serveur, timeout=1))
        self.assertIsNone(serveur.demandes[0])
        self.assertTrue(serveur.demandes[1].startswith("bytes="))
        self.assertGreater(int(serveur.demandes[1][6:].split("-")[0]), 0)

    def test_un_part_orphelin_n_est_pas_repris(self):
        """Le .part d'un processus mort ne sert pas de début au transfert :
        un essai qui échoue avant d'écrire le laisserait reprendre."""
        self.dest.with_suffix(".qcow2.part").write_bytes(b"x" * 1000)
        serveur = Serveur(pannes=[503])
        self.assertEqual(CONTENU, self.telecharge(serveur))
        self.assertIsNone(serveur.demandes[1])

    def test_une_erreur_locale_n_est_pas_passagere(self):
        self.assertFalse(d.erreur_passagere(PermissionError("droits")))
        self.assertFalse(d.erreur_passagere(OSError(28, "disque plein")))
        self.assertTrue(d.erreur_passagere(TimeoutError("timed out")))
        self.assertTrue(d.erreur_passagere(ConnectionResetError()))


if __name__ == "__main__":
    unittest.main()
