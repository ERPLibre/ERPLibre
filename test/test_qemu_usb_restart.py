#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Redémarrer un périphérique USB d'une VM : le détacher, puis le rattacher.

Un périphérique rebranché sur l'hôte sans rattachement auto change
d'adresse ; la vue live de la VM garde un <hostdev> à l'ancienne, ou
« missing ». Ces tests gardent :

- le détachement vise le <hostdev> tel que la vue live le porte, par son
  ancienne adresse ;
- le rattachement est calculé SANS ce <hostdev> — sur la vue lue, il
  serait sauté comme « déjà attaché » —, par VID:PID seul quand le
  périphérique est unique ;
- seule la vue live est touchée, et une VM arrêtée n'a rien à redémarrer ;
- le menu lance detach-device PUIS attach-device, sur une seule
  confirmation, et rien sans elle ;
- un périphérique débranché de l'hôte, ou une VM sans contrôleur USB,
  n'est jamais détaché pour rien ;
- le service deck de l'hôte, qui prendrait le deck entre les deux étapes,
  n'est arrêté qu'après accord, et un refus annule ;
- un rattachement qui échoue le dit et propose de relancer le service.

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
    AUTRE,
    DECK,
    HOSTDEV_CFG,
    HOSTDEV_LIVE,
    UNITE,
    VNC,
    XHCI,
    _Cas,
    domaine,
)

# Le deck rebranché : même VID:PID, nouveau numéro de périphérique.
DECK_REBRANCHE = dict(DECK, devnum=9)
# Ce que libvirt laisse en live quand le périphérique manquait au démarrage.
HOSTDEV_MISSING = (
    "<hostdev mode='subsystem' type='usb' managed='yes'>"
    "<source startupPolicy='optional' missing='yes'><vendor id='0x0fd9'/>"
    "<product id='0x0080'/></source></hostdev>"
)
VM = "vm-a"


class LePlan(unittest.TestCase):
    def _plan(self, live_xml, branche=DECK_REBRANCHE, running=True):
        etat = qu.usb_state(live_xml)
        h = etat["hostdevs"][0] if etat["hostdevs"] else {}
        detach_want = {k: h.get(k) for k in ("vid", "pid", "bus", "dev")}
        detach_want["vid"] = detach_want["vid"] or "0fd9"
        detach_want["pid"] = detach_want["pid"] or "0080"
        return qu.restart_plan(
            etat,
            detach_want,
            qu.want_for(branche, [branche]),
            running,
            VM,
        )

    def test_detach_targets_the_old_address_then_attach_by_vid_pid(self):
        detach, attach = self._plan(domaine(XHCI, VNC, HOSTDEV_LIVE))
        self.assertEqual(1, len(detach))
        self.assertIn("detach-device", detach[0]["argv"])
        self.assertIn("--live", detach[0]["argv"])
        self.assertIn("<address bus='3' device='5'/>", detach[0]["xml"])
        self.assertEqual(1, len(attach))
        self.assertIn("attach-device", attach[0]["argv"])
        self.assertIn("--live", attach[0]["argv"])
        self.assertIn("<vendor id='0x0fd9'/>", attach[0]["xml"])
        self.assertNotIn("<address", attach[0]["xml"])

    def test_attach_is_not_skipped_as_already_attached(self):
        """Sur la vue lue, le <hostdev> est présent : usb_plan seul
        sauterait l'attachement."""
        _, attach = self._plan(domaine(XHCI, VNC, HOSTDEV_LIVE))
        self.assertNotIn("skip", attach[0])

    def test_a_missing_placeholder_is_detached_once(self):
        """Le joker « missing » est retiré par le détachement ; le
        rattachement ne le retire pas une seconde fois."""
        detach, attach = self._plan(domaine(XHCI, VNC, HOSTDEV_MISSING))
        self.assertEqual(1, len(detach))
        self.assertIn("detach-device", detach[0]["argv"])
        self.assertEqual(1, len(attach))
        self.assertIn("attach-device", attach[0]["argv"])

    def test_not_attached_live_only_attaches(self):
        detach, attach = self._plan(domaine(XHCI, VNC))
        self.assertTrue(all("skip" in s for s in detach))
        self.assertIn("attach-device", attach[0]["argv"])

    def test_only_the_live_view_is_touched(self):
        detach, attach = self._plan(domaine(XHCI, VNC, HOSTDEV_LIVE))
        for step in detach + attach:
            self.assertNotIn("--config", step.get("argv", []))
            self.assertEqual("live", step["view"])

    def test_a_stopped_vm_has_nothing_to_restart(self):
        detach, attach = self._plan(
            domaine(XHCI, VNC, HOSTDEV_LIVE), running=False
        )
        self.assertEqual([], attach)
        self.assertEqual(1, len(detach))
        self.assertIn("skip", detach[0])

    def test_two_identical_devices_pin_the_new_address(self):
        jumeau = dict(DECK, devnum=11, serial="FAKE0002")
        etat = qu.usb_state(domaine(XHCI, VNC, HOSTDEV_LIVE))
        _, attach = qu.restart_plan(
            etat,
            {"vid": "0fd9", "pid": "0080", "bus": 3, "dev": 5},
            qu.want_for(DECK_REBRANCHE, [DECK_REBRANCHE, jumeau]),
            True,
            VM,
        )
        self.assertIn("<address bus='3' device='9'/>", attach[0]["xml"])


class LeMenu(_Cas):
    def setUp(self):
        super().setUp()
        self.hv.config = domaine(XHCI, VNC, HOSTDEV_CFG)
        self.hv.live = domaine(XHCI, VNC, HOSTDEV_LIVE)
        self.devices = [DECK_REBRANCHE, AUTRE]

    def test_detach_then_attach_on_one_confirmation(self):
        out = self.jouer("_qemu_usb_restart", ["1", "1", "y"])
        self.assertEqual(2, len(self.hv.commandes), out)
        detach, attach = (shlex.split(c) for c in self.hv.commandes)
        self.assertIn("detach-device", detach)
        self.assertEqual("--live", detach[-1])
        self.assertIn("attach-device", attach)
        self.assertEqual("--live", attach[-1])
        self.assertIn("<address bus='3' device='5'/>", self.hv.xml[0])
        self.assertNotIn("<address", self.hv.xml[1])
        self.assertIn(todo_i18n.t("Restarted:"), out)

    def test_no_confirmation_runs_nothing(self):
        self.jouer("_qemu_usb_restart", ["1", "1", "n"])
        self.assertEqual([], self.hv.commandes)

    def test_a_stopped_vm_runs_nothing(self):
        self.hv.etat = "shut off"
        out = self.jouer("_qemu_usb_restart", ["1"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(
            todo_i18n.t("The VM is not running: nothing to restart."), out
        )

    def test_an_unplugged_device_is_never_detached(self):
        self.devices = [AUTRE]
        out = self.jouer("_qemu_usb_restart", ["1", "1"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn("0fd9:0080", out)

    def test_a_vm_without_usb_controller_is_never_detached(self):
        """Détacher sans pouvoir rattacher retirerait le périphérique."""
        self.hv.live = domaine(VNC, HOSTDEV_LIVE)
        out = self.jouer("_qemu_usb_restart", ["1", "1"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(todo_i18n.t("Nothing to do."), out)

    def test_nothing_attached_says_so(self):
        self.hv.config = self.hv.live = domaine(XHCI, VNC)
        out = self.jouer("_qemu_usb_restart", ["1"])
        self.assertIn(
            todo_i18n.t("No USB device is attached to this VM."), out
        )

    def test_the_deck_service_is_stopped_first_on_consent(self):
        self.service = {"installed": True, "active": True}
        self.jouer("_qemu_usb_restart", ["1", "1", "y", "y"])
        self.assertEqual(
            f"systemctl --user stop {UNITE}", self.hv.commandes[0]
        )
        self.assertIn("detach-device", self.hv.commandes[1])
        self.assertIn("attach-device", self.hv.commandes[2])

    def test_refusing_to_stop_the_deck_service_cancels(self):
        self.service = {"installed": True, "active": True}
        self.jouer("_qemu_usb_restart", ["1", "1", "n"])
        self.assertEqual([], self.hv.commandes)

    def test_a_failed_attach_says_so_and_offers_the_service(self):
        """detach-device réussit, attach-device échoue : le périphérique
        n'est plus dans la VM, et le service arrêté peut le reprendre."""
        self.service = {"installed": True, "active": True}
        codes = iter([0, 0, 1, 0])
        lancer = self.hv.exec_command_live

        def lancer_puis_echouer(cmd, **kwargs):
            lancer(cmd, **kwargs)
            code = next(codes)
            if code == 0 and "stop" in cmd:
                self.service = {"installed": True, "active": False}
            return code

        self.todo.execute = type(
            "Lanceur",
            (),
            {"exec_command_live": staticmethod(lancer_puis_echouer)},
        )()
        out = self.jouer("_qemu_usb_restart", ["1", "1", "y", "y", "y"])
        self.assertIn(todo_i18n.t("The device is detached from the VM."), out)
        self.assertEqual(
            f"systemctl --user start {UNITE}", self.hv.commandes[-1]
        )

    def test_a_remote_vm_goes_through_its_proxyjump_without_sudo(self):
        self.distant()
        self.jouer("_qemu_usb_restart", ["1", "1", "y"])
        self.assertEqual(2, len(self.hv.commandes))
        for cmd in self.hv.commandes:
            self.assertTrue(cmd.startswith("virsh --connect qemu+ssh://"))


if __name__ == "__main__":
    unittest.main()
