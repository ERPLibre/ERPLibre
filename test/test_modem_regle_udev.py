#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La regle udev reserve un port AT sans se lier a un seul modele de carte.

Elle designe le port par ce que ModemManager en dit, et borne sa portee par
une liste de vendeurs. Les deux moities vivent a deux endroits — le fichier
de regle et `udev.VENDEURS` — et une divergence entre elles ne se voit sur
aucun ecran : le lien manque, sans rien dire de plus.
"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import device, udev  # noqa: E402


def regle():
    with open(udev.source(), encoding="utf-8") as fh:
        return fh.read()


class TestRegle(unittest.TestCase):
    def test_designe_le_port_par_son_role(self):
        """Le port vient de ModemManager, pas d'un numero d'interface USB.

        Un numero d'interface vaut pour une composition de ports, donc pour
        une famille de cartes ; le role vaut pour toutes celles que
        ModemManager reconnait.
        """
        texte = regle()
        self.assertIn('ENV{ID_MM_PORT_TYPE_AT_SECONDARY}=="1"', texte)
        self.assertNotIn("ID_USB_INTERFACE_NUM", texte)

    def test_vendeurs_accordes_avec_la_regle(self):
        """`udev.VENDEURS` dit ce que la regle accepte, sans decalage.

        Le diagnostic s'en sert pour annoncer « vendeur absent de la regle ».
        Une liste en avance sur le fichier ferait annoncer un port reserve
        qui ne l'est pas.
        """
        listes = re.findall(r'ATTRS\{idVendor\}=="([^"]+)"', regle())
        self.assertTrue(listes, "la regle ne borne aucun vendeur")
        for liste in listes:
            self.assertEqual(tuple(liste.split("|")), udev.VENDEURS)


class TestCauseAbsence(unittest.TestCase):
    """Un lien absent nomme sa cause : elles n'ont pas le meme remede."""

    def _cause(self, ports, posee=True):
        with mock.patch.object(udev, "port_reserve", return_value=None), \
                mock.patch.object(udev, "ports_at", return_value=ports), \
                mock.patch.object(udev, "posee", return_value=posee):
            return udev.cause_absence_lien()

    def test_lien_present_aucune_cause(self):
        with mock.patch.object(udev, "port_reserve", return_value="/dev/x"):
            self.assertIsNone(udev.cause_absence_lien())

    def test_aucun_port_at(self):
        self.assertIn("pas branche", self._cause([]))

    def test_carte_a_port_at_unique(self):
        """Poser la regle ne donnerait rien : il n'y a rien a lui prendre."""
        cause = self._cause([
            {"port": "/dev/ttyUSB0", "role": "primaire", "vendeur": "2c7c"},
        ])
        self.assertIn("UN port AT", cause)
        self.assertIn("/dev/ttyUSB0", cause)

    def test_vendeur_hors_liste(self):
        """Le cas d'une carte neuve : tout est la sauf l'autorisation."""
        cause = self._cause([
            {"port": "/dev/ttyUSB3", "role": "secondaire", "vendeur": "1bc7"},
        ])
        self.assertIn("1bc7", cause)
        self.assertIn("idVendor", cause)

    def test_regle_absente(self):
        cause = self._cause([
            {"port": "/dev/ttyUSB3", "role": "secondaire", "vendeur": "2c7c"},
        ], posee=False)
        self.assertIn("n'est pas posee", cause)

    def test_un_second_modem_borne_ne_masque_pas_le_premier(self):
        """Un vendeur inconnu a cote d'un vendeur connu n'est pas la cause."""
        cause = self._cause([
            {"port": "/dev/ttyUSB3", "role": "secondaire", "vendeur": "1bc7"},
            {"port": "/dev/ttyUSB7", "role": "secondaire", "vendeur": "2c7c"},
        ])
        self.assertNotIn("1bc7", cause)


class TestPortsAt(unittest.TestCase):
    def test_lit_le_role_et_le_vendeur(self):
        sortie = (
            "ID_VENDOR_ID=2c7c\n"
            "ID_MM_PORT_TYPE_AT_SECONDARY=1\n"
            "DEVNAME=/dev/ttyUSB3\n"
        )
        faux = mock.Mock(returncode=0, stdout=sortie)
        with mock.patch.object(udev.glob, "glob",
                               side_effect=[["/dev/ttyUSB3"], []]), \
                mock.patch.object(udev.subprocess, "run", return_value=faux):
            self.assertEqual(udev.ports_at(), [
                {"port": "/dev/ttyUSB3", "role": "secondaire",
                 "vendeur": "2c7c"},
            ])

    def test_udevadm_absent_ne_leve_rien(self):
        """Le diagnostic tourne aussi sur un hote sans udev."""
        with mock.patch.object(udev.glob, "glob", return_value=["/dev/ttyUSB3"]), \
                mock.patch.object(udev.subprocess, "run",
                                  side_effect=FileNotFoundError):
            self.assertEqual(udev.ports_at(), [])


class TestPortParDefaut(unittest.TestCase):
    """A defaut du lien reserve, le port vient aussi de ModemManager."""

    def test_prend_le_primaire_designe(self):
        ports = [
            {"port": "/dev/ttyACM0", "role": "primaire", "vendeur": "1e0e"},
            {"port": "/dev/ttyACM1", "role": "secondaire", "vendeur": "1e0e"},
        ]
        with mock.patch.object(device.udev, "ports_at", return_value=ports):
            self.assertEqual(device.port_primaire(), "/dev/ttyACM0")

    def test_aucun_role_connu_rend_none(self):
        """Le rang fixe reste, mais en dernier recours et non en premier."""
        with mock.patch.object(device.udev, "ports_at", return_value=[]):
            self.assertIsNone(device.port_primaire())
        self.assertEqual(device.PORTS_AT[0], "/dev/ttyUSB2")


if __name__ == "__main__":
    unittest.main()
