#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Désactiver la redirection USB SPICE d'une VM : l'inverse de l'activer.

Ces tests gardent :

- les emplacements <redirdev type='spicevmc'> et le <redirfilter> sont
  retirés ; l'affichage SPICE, le contrôleur USB, le canal de l'agent et
  les <hostdev> passés directement restent ;
- une redirection d'un autre type que spicevmc n'est pas touchée ;
- le retrait est idempotent, et désactiver puis réactiver revient à une
  VM prête ;
- le menu redéfinit une VM éteinte sur confirmation, arrête une VM en
  marche seulement sur accord et la relance, et ne lance rien quand il n'y
  a rien à retirer ;
- l'activation, qui partage le même parcours, ne change pas.

Valeurs inventées, celles de test_qemu_usb_menu.py.
"""

import shlex
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo import qemu_usb as qu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_qemu_usb_menu import (  # noqa: E402
    HOSTDEV_CFG,
    VNC,
    XHCI,
    _Cas,
    domaine,
)

VM = "vm-a"
# Une VM prête, filtre de vendeurs compris, avec un deck passé directement.
PRETE = qu.spice_usbredir_xml(
    domaine(XHCI, VNC, HOSTDEV_CFG), allow_vendors=(qu.DECK_VENDOR,)
)[0]


class LeRetrait(unittest.TestCase):
    def test_slots_and_filter_leave(self):
        xml, changes = qu.spice_usbredir_disable_xml(PRETE)
        etat = qu.usb_state(xml)
        self.assertEqual([], etat["redirdevs"])
        self.assertEqual([], etat["redirfilter"])
        self.assertEqual(2, len(changes))

    def test_display_controller_channel_and_hostdev_stay(self):
        etat = qu.usb_state(qu.spice_usbredir_disable_xml(PRETE)[0])
        self.assertEqual(["spice", "vnc"], etat["graphics"])
        self.assertEqual(["qemu-xhci"], etat["usb_controllers"])
        self.assertTrue(etat["spice_channel"])
        self.assertEqual(["0fd9"], [h["vid"] for h in etat["hostdevs"]])

    def test_another_redirection_type_is_left_alone(self):
        tcp = (
            "<redirdev bus='usb' type='tcp'>"
            "<source mode='connect' host='hote.invalid' service='4000'/>"
            "</redirdev>"
        )
        xml, _ = qu.spice_usbredir_disable_xml(
            qu.spice_usbredir_xml(domaine(XHCI, VNC, tcp))[0]
        )
        self.assertEqual(["tcp"], qu.usb_state(xml)["redirdevs"])

    def test_nothing_to_remove_returns_the_input(self):
        nu = domaine(XHCI, VNC)
        self.assertEqual((nu, []), qu.spice_usbredir_disable_xml(nu))
        self.assertEqual([], qu.spice_usbredir_disable_plan(nu, VM))

    def test_it_is_idempotent(self):
        une_fois = qu.spice_usbredir_disable_xml(PRETE)[0]
        self.assertEqual([], qu.spice_usbredir_disable_xml(une_fois)[1])

    def test_enable_after_disable_is_ready_again(self):
        sans = qu.spice_usbredir_disable_xml(PRETE)[0]
        etat = qu.usb_state(qu.spice_usbredir_xml(sans)[0])
        self.assertTrue(qu.usbredir_ready(etat))
        self.assertTrue(qu.spice_first(etat))

    def test_the_plan_is_one_virsh_define(self):
        plan = qu.spice_usbredir_disable_plan(PRETE, VM)
        self.assertEqual(1, len(plan))
        self.assertEqual("config", plan[0]["view"])
        self.assertIn("define", plan[0]["argv"])

    def test_an_unreadable_xml_raises(self):
        with self.assertRaises(ValueError):
            qu.spice_usbredir_disable_xml("<domain")


class LeMenu(_Cas):
    def setUp(self):
        super().setUp()
        self.hv.config = self.hv.live = PRETE

    def test_a_shut_off_vm_is_redefined_without_redirection(self):
        self.hv.etat = "shut off"
        out = self.jouer("_qemu_usb_disable_spice", ["1", "y"])
        self.assertEqual(1, len(self.hv.commandes), out)
        self.assertIn(" define ", self.hv.commandes[0])
        etat = qu.usb_state(self.hv.config)
        self.assertEqual([], etat["redirdevs"])
        self.assertEqual([], etat["redirfilter"])
        self.assertEqual(["0fd9"], [h["vid"] for h in etat["hostdevs"]])
        self.assertIn(todo_i18n.t("SPICE USB redirection disabled."), out)

    def test_a_running_vm_is_left_alone_without_consent(self):
        self.jouer("_qemu_usb_disable_spice", ["1", "n"])
        self.assertEqual([], self.hv.commandes)
        self.assertEqual("running", self.hv.etat)

    def test_a_running_vm_is_shut_down_redefined_and_restarted(self):
        self.jouer("_qemu_usb_disable_spice", ["1", "y", "y"])
        verbes = [shlex.split(c)[3] for c in self.hv.commandes]
        self.assertEqual(["shutdown", "define", "start"], verbes)
        self.assertEqual("running", self.hv.etat)

    def test_declining_the_commands_still_restarts_the_vm(self):
        self.jouer("_qemu_usb_disable_spice", ["1", "y", "n"])
        verbes = [shlex.split(c)[3] for c in self.hv.commandes]
        self.assertEqual(["shutdown", "start"], verbes)

    def test_nothing_set_up_runs_nothing(self):
        self.hv.config = self.hv.live = domaine(XHCI, VNC)
        out = self.jouer("_qemu_usb_disable_spice", ["1"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(todo_i18n.t("SPICE USB redirection is not set up."), out)

    def test_enable_still_asks_the_vendor_filter_first(self):
        """L'activation passe par le même parcours : la question du filtre
        vient toujours avant celle de l'arrêt."""
        self.hv.config = self.hv.live = domaine(XHCI, VNC)
        self.jouer("_qemu_usb_enable_spice", ["1", "y", "y", "y"])
        etat = qu.usb_state(self.hv.config)
        self.assertEqual(
            ["0fd9"], [r["vendor"] for r in etat["redirfilter"] if r["allow"]]
        )


if __name__ == "__main__":
    unittest.main()
