#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La verification de la carte son du modem, avec un faux arecord.

Le vrai arecord ecrit du son brut sur sa sortie standard. Un faux qui ecrit
des octets invalides en UTF-8 reproduit ce qu'une ligne un peu bruyante
produit, sans carte son.
"""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import audio  # noqa: E402


def faux_arecord(dossier, code_sortie, erreur=b""):
    chemin = os.path.join(dossier, "arecord")
    with open(chemin, "wb") as flux:
        flux.write(b"#!/usr/bin/env python3\n")
        flux.write(b"import sys\n")
        # Du son bruite : des octets qui ne sont pas de l'UTF-8 valide.
        flux.write(b"sys.stdout.buffer.write(bytes([0xf8, 0x00, 0xff, 0x7f] * 4000))\n")
        flux.write(b"sys.stderr.buffer.write(%r)\n" % erreur)
        flux.write(b"sys.exit(%d)\n" % code_sortie)
    os.chmod(chemin, os.stat(chemin).st_mode | stat.S_IEXEC)


class TestCarteLibre(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        chemin = self.tmp.name + os.pathsep + os.environ.get("PATH", "")
        self.enterContext(mock.patch.dict(os.environ, {"PATH": chemin}))

    def test_un_son_bruite_ne_fait_pas_planter_le_bandeau(self):
        """Le plantage survenait des qu'un octet capte n'etait pas de l'UTF-8."""
        faux_arecord(self.tmp.name, 0)
        self.assertEqual(audio.carte_libre("hw:9,0"), (True, "carte libre"))

    def test_une_carte_occupee_donne_la_derniere_ligne_d_erreur(self):
        faux_arecord(self.tmp.name, 1,
                     b"arecord: main: audio open error: Device or resource busy\n")
        ok, motif = audio.carte_libre("hw:9,0")
        self.assertFalse(ok)
        self.assertIn("busy", motif)

    def test_une_erreur_mal_encodee_reste_lisible(self):
        faux_arecord(self.tmp.name, 1, b"erreur \xf8 illisible\n")
        ok, motif = audio.carte_libre("hw:9,0")
        self.assertFalse(ok)
        self.assertIn("illisible", motif)


if __name__ == "__main__":
    unittest.main()
