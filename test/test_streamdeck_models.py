#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La table des modèles Stream Deck et son usage par qemu_usb.

Ce que ces tests gardent :

- model_name lit un idProduct sous toutes ses formes, et rend "" pour un
  PID inconnu ou illisible ;
- la table et le registre du pilote mobile du deck (DeckRegistry.java)
  portent les mêmes PID : un modèle ajouté d'un côté se nomme de l'autre.
  Sans mobile/erplibre_home_mobile, ce test se dit sauté ;
- qemu_usb.device_label prend le nom du modèle pour un deck qui n'annonce
  pas le sien, jamais pour un autre vendeur, et garde le nom annoncé.
"""

import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import qemu_usb  # noqa: E402
from script.todo import streamdeck_models as modeles  # noqa: E402

REGISTRE = (
    RACINE
    / "mobile/erplibre_home_mobile/android/app/src/main/java"
    / "ca/erplibre/home/streamdeck/DeckRegistry.java"
)


class LaTable(unittest.TestCase):
    def test_every_spelling_of_a_pid(self):
        for pid in ("0080", "0x0080", "0X0080", "80", " 0080\n", 0x80):
            with self.subTest(pid=pid):
                self.assertEqual("Stream Deck MK.2", modeles.model_name(pid))

    def test_unknown_or_unreadable_is_empty(self):
        for pid in ("ffff", "", None, "00800", -1, 0x10000, "zz"):
            with self.subTest(pid=pid):
                self.assertEqual("", modeles.model_name(pid))

    def test_keys_are_four_lowercase_hex(self):
        for cle in modeles.DECK_MODELS:
            self.assertRegex(cle, r"^[0-9a-f]{4}$")

    @unittest.skipUnless(
        REGISTRE.is_file(),
        "mobile/erplibre_home_mobile absent : le registre du pilote mobile"
        " ne se relit pas",
    )
    def test_same_pids_as_the_mobile_registry(self):
        texte = REGISTRE.read_text(encoding="utf-8")
        pids = {
            p.lower().zfill(4)
            for p in re.findall(r"\.productId\(0x([0-9a-fA-F]+)\)", texte)
        }
        self.assertTrue(pids)
        self.assertEqual(pids, set(modeles.DECK_MODELS))


class LeLibelle(unittest.TestCase):
    def test_a_deck_without_product_takes_its_model(self):
        self.assertEqual(
            "Stream Deck +",
            qemu_usb.device_label({"vid": "0fd9", "pid": "0084"}),
        )
        self.assertEqual(
            "Elgato Stream Deck XL",
            qemu_usb.device_label(
                {"vid": "0FD9", "pid": "006c", "manufacturer": "Elgato"}
            ),
        )

    def test_the_announced_name_wins(self):
        self.assertEqual(
            "Nom annoncé",
            qemu_usb.device_label(
                {"vid": "0fd9", "pid": "0084", "product": "Nom annoncé"}
            ),
        )

    def test_unknown_pid_or_other_vendor_keeps_vid_pid(self):
        self.assertEqual(
            "0fd9:ffff", qemu_usb.device_label({"vid": "0fd9", "pid": "ffff"})
        )
        self.assertEqual(
            "1234:0084", qemu_usb.device_label({"vid": "1234", "pid": "0084"})
        )


if __name__ == "__main__":
    unittest.main()
