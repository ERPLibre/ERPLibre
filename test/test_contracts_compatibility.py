#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le contrat de compatibilité avec l'app mobile, sans Odoo.

contracts/compatibility.json est ce qu'un client lit pour parler au module
erplibre_mobile_chat. Ses routes suivent celles que déclarent les
contrôleurs du module (quand le module est cloné), et chaque route porte
la note d'accès qu'une requête doit respecter : jeton CSRF, utilisateurs
internes seulement, arguments et version de charge de la marque d'un
appareil.
"""

import json
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CONTRAT = RACINE / "contracts" / "compatibility.json"
MODULE = (
    RACINE
    / "odoo18.0"
    / "addons"
    / "ERPLibre_erplibre_addons"
    / "erplibre_mobile_chat"
)


def chat():
    return json.loads(CONTRAT.read_text(encoding="utf-8"))["modules"][
        "erplibre_mobile_chat"
    ]


class TestContratChat(unittest.TestCase):
    def test_chaque_route_porte_sa_note_d_acces(self):
        module = chat()
        self.assertEqual(
            sorted(module["route_access"]), sorted(module["routes"])
        )

    def test_les_notes_disent_csrf_internes_et_charges(self):
        acces = chat()["route_access"]
        upload = acces["/erplibre_mobile_chat/attachment/upload"]
        self.assertIn("CSRF", upload)
        for route in (
            "/erplibre_mobile_chat/attachment/upload",
            "/erplibre_mobile_chat/message/update_content",
            "/erplibre_mobile_chat/message/search",
        ):
            self.assertIn("internal users only", acces[route], route)
        device = acces["/erplibre_mobile_chat/push/device"]
        for fait in ("browser_mode", "quiet_while_online", "v 1", "v 2"):
            self.assertIn(fait, device)
        self.assertIn("read and inbox_done", chat()["levels"]["1.6"])

    def test_les_routes_sont_celles_des_controleurs(self):
        controleurs = MODULE / "controllers"
        if not controleurs.is_dir():
            self.skipTest("module erplibre_mobile_chat absent")
        declarees = set()
        for source in controleurs.glob("*.py"):
            declarees.update(
                re.findall(
                    r'@http\.route\(\s*"(/erplibre_mobile_chat/[^"]+)"',
                    source.read_text(encoding="utf-8"),
                )
            )
        self.assertEqual(sorted(declarees), sorted(chat()["routes"]))


if __name__ == "__main__":
    unittest.main()
