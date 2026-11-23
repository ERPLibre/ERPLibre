#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Proxmox › Périphériques USB : la commande montrée, puis lancée.

Le nœud est simulé : pve.run répond selon la commande reçue, et les « qm
set » lancés sont relevés. Ces tests gardent :

- l'attachement prend le premier port usbN libre, et seulement après
  confirmation ;
- un périphérique déjà dans la configuration n'est pas reposé ;
- deux périphériques identiques sont épinglés par leur port physique ;
- le détachement retire le port choisi ;
- le menu dit que l'attachement Proxmox est toujours persistant ;
- à la création, True désigne les Stream Deck branchés sur le nœud.
"""

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.proxmox import proxmox_deploy as pve  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

HOTE = {
    "target": "root@hyperviseur.invalid",
    "jump": "",
    "sudo": "",
    "version": "9.2.11",
}
QM_LIST = """      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
       101 vm-essai             running    2048              16.00 2726
"""


def _usb(busnum, devnum, vid, pid, usbpath, product="Stream Deck"):
    return {
        "busnum": busnum,
        "class": 0,
        "devnum": devnum,
        "vendid": vid,
        "prodid": pid,
        "product": product,
        "manufacturer": "Elgato" if vid == "0fd9" else "",
        "usbpath": usbpath,
    }


CLAVIER = _usb(1, 3, "046d", "c31c", "4", "USB Keyboard")
MK2 = _usb(3, 5, "0fd9", "0080", "2", "Stream Deck MK.2")
MINI_A = _usb(2, 7, "0fd9", "006d", "3", "Stream Deck Mini")
MINI_B = _usb(2, 8, "0fd9", "006d", "4", "Stream Deck Mini")


class NoeudFactice:
    """pve.run simulé : répond à qm list, hostname, pvesh, qm config, et
    relève chaque « qm set »."""

    def __init__(self, usb, config="boot: order=scsi0\n"):
        self.usb = usb
        self.config = config
        self.lances = []

    def __call__(self, host, remote, timeout=120):
        if remote == "qm list":
            return 0, QM_LIST
        if remote == "hostname":
            return 0, "pve-essai\n"
        if remote.startswith("pvesh get "):
            return 0, json.dumps(self.usb)
        if remote.startswith("qm config "):
            return 0, self.config
        if remote.startswith("qm set "):
            self.lances.append(remote)
            return 0, "update VM 101: ok\n"
        return 1, f"inattendu : {remote}"


def _todo():
    todo = TODO.__new__(TODO)
    todo._pve_host_cache = dict(HOTE)
    return todo


def _jouer(noeud, reponses, appel=None):
    todo = _todo()
    sortie = io.StringIO()
    with (
        mock.patch.object(pve, "run", noeud),
        mock.patch("builtins.input", side_effect=reponses),
        contextlib.redirect_stdout(sortie),
    ):
        (appel or todo._pve_usb)()
    return sortie.getvalue()


class TestAttacher(unittest.TestCase):
    def test_the_first_free_slot_after_confirmation(self):
        noeud = NoeudFactice(
            [CLAVIER, MK2], "usb0: host=046d:c31c\nusb2: spice\n"
        )
        # VM 1, attacher, périphérique 1 (le deck, en tête), oui, retour.
        sortie = _jouer(noeud, ["1", "1", "1", "o", "0"])
        self.assertEqual(
            ["qm set 101 -usb1 host=0fd9:0080,usb3=1"], noeud.lances
        )
        self.assertIn("qm set 101 -usb1 host=0fd9:0080,usb3=1", sortie)

    def test_the_menu_says_it_is_always_persistent(self):
        sortie = _jouer(NoeudFactice([MK2]), ["1", "0"])
        self.assertIn(
            t(
                "Proxmox USB attachments are always persistent: they are"
                " written to the VM configuration and follow a replug by"
                " VID:PID, without any udev rule."
            ),
            sortie,
        )

    def test_nothing_runs_without_confirmation(self):
        noeud = NoeudFactice([MK2])
        sortie = _jouer(noeud, ["1", "1", "1", "n", "0"])
        self.assertEqual([], noeud.lances)
        self.assertIn(t("Cancelled."), sortie)

    def test_a_device_already_attached_is_not_set_twice(self):
        noeud = NoeudFactice([MK2], "usb3: host=0FD9:0080,usb3=1\n")
        sortie = _jouer(noeud, ["1", "1", "1", "0"])
        self.assertEqual([], noeud.lances)
        self.assertIn("usb3", sortie)
        self.assertIn(t("Already in this Proxmox VM:"), sortie)

    def test_identical_devices_are_pinned_to_their_port(self):
        noeud = NoeudFactice([MINI_A, MINI_B])
        sortie = _jouer(noeud, ["1", "1", "2", "o", "0"])
        self.assertEqual(["qm set 101 -usb0 host=2-4,usb3=1"], noeud.lances)
        self.assertIn(
            t(
                "Two identical devices are plugged in: this one is pinned to"
                " its physical port, and a replug on another port is not"
                " followed."
            ),
            sortie,
        )

    def test_a_full_vm_runs_nothing(self):
        pleine = "".join(f"usb{n}: spice\n" for n in range(pve.USB_SLOTS))
        noeud = NoeudFactice([MK2], pleine)
        sortie = _jouer(noeud, ["1", "1", "1", "0"])
        self.assertEqual([], noeud.lances)
        self.assertIn(t("No free usbN port on this Proxmox VM:"), sortie)

    def test_hotplug_off_is_said(self):
        noeud = NoeudFactice([MK2], "hotplug: network,disk\n")
        sortie = _jouer(noeud, ["1", "1", "1", "o", "0"])
        self.assertEqual(1, len(noeud.lances))
        self.assertIn(
            t(
                "USB hotplug is off for this Proxmox VM: the device appears"
                " at its next start."
            ),
            sortie,
        )

    def test_an_out_of_range_choice_runs_nothing(self):
        noeud = NoeudFactice([MK2])
        sortie = _jouer(noeud, ["1", "1", "9", "0"])
        self.assertEqual([], noeud.lances)
        self.assertIn(t("Invalid selection!"), sortie)


class TestDetacher(unittest.TestCase):
    def test_the_chosen_slot_is_deleted(self):
        noeud = NoeudFactice([MK2], "usb0: spice\nusb4: host=0fd9:0080\n")
        # VM 1, détacher, deuxième port listé (usb4), oui, retour.
        _jouer(noeud, ["1", "2", "2", "o", "0"])
        self.assertEqual(["qm set 101 -delete usb4"], noeud.lances)

    def test_nothing_to_detach(self):
        noeud = NoeudFactice([MK2])
        sortie = _jouer(noeud, ["1", "2", "0"])
        self.assertEqual([], noeud.lances)
        self.assertIn(t("No usbN port on this Proxmox VM."), sortie)


class TestALaCreation(unittest.TestCase):
    def _resoudre(self, usb, valeur):
        todo = _todo()
        with (
            mock.patch.object(pve, "run", NoeudFactice(usb)),
            contextlib.redirect_stdout(io.StringIO()) as sortie,
        ):
            return todo._pve_usb_hostdev(valeur), sortie.getvalue()

    def test_true_means_the_decks_of_the_node(self):
        choisis, _s = self._resoudre([CLAVIER, MK2, MINI_A, MINI_B], True)
        self.assertEqual(["2-3", "2-4", "0fd9:0080"], choisis)

    def test_a_list_passes_through(self):
        choisis, _s = self._resoudre([], ["0fd9:0080", "0fd9:0080"])
        self.assertEqual(["0fd9:0080"], choisis)

    def test_a_libvirt_bus_dev_is_translated_on_the_node(self):
        """L'écran rend « bus.périphérique » pour deux decks identiques,
        la forme libvirt ; elle devient le bus-port que « qm set » lit."""
        choisis, _s = self._resoudre([MINI_A, MINI_B], ["2.8", "0fd9:0080"])
        self.assertEqual(["2-4", "0fd9:0080"], choisis)

    def test_a_vanished_device_is_dropped_and_named(self):
        choisis, sortie = self._resoudre([MINI_A], ["2.8"])
        self.assertEqual([], choisis)
        self.assertIn(t("USB device not found on the Proxmox node:"), sortie)
        self.assertIn("2.8", sortie)

    def test_the_form_reads_the_usb_of_the_node(self):
        """La case « Stream Deck » de l'écran Proxmox lit la clé de
        l'écran QEMU/KVM, remplie ici par pvesh et non par le sysfs
        local."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "script/todo/proxmox_menu.py"
        ).read_text(encoding="utf-8")
        debut = src.index("    def _pve_form_context(")
        bloc = src[debut : src.index("\n    def ", debut + 1)]
        self.assertIn('"host_usb_devices": self._pve_usb_devices()', bloc)

    def test_no_deck_on_the_node_is_said(self):
        choisis, sortie = self._resoudre([CLAVIER], True)
        self.assertEqual([], choisis)
        self.assertIn(
            t(
                "No Stream Deck plugged into the Proxmox node: the VM is"
                " created without one."
            ),
            sortie,
        )

    def test_the_creation_commands_carry_the_spec(self):
        """_pve_vm_commands passe spec["usb_hostdev"] à create_cmds : la
        source le dit, faute de pouvoir construire un catalogue ici."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "script/todo/proxmox_menu.py"
        ).read_text(encoding="utf-8")
        debut = src.index("    def _pve_vm_commands(")
        bloc = src[debut : src.index("\n    def ", debut + 1)]
        self.assertIn('"usb_hostdev": self._pve_usb_hostdev(', bloc)


if __name__ == "__main__":
    unittest.main(verbosity=1)
