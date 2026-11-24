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
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


BILLET = {
    "type": "spice",
    "host": "pvespiceproxy:6566a1b2:101:pve-essai::0123abcd",
    "proxy": "http://pve-essai.invalid:3128",
    "tls-port": 61000,
    "password": "faux-billet",
    "ca": "-----BEGIN CERTIFICATE-----\\nMIIBinvente\\n",
    "delete-this-file": 1,
}
# Un deck de CE poste, à la forme de qemu_usb.read_usb_device().
DECK_POSTE = {
    "sysname": "1-4",
    "busnum": 1,
    "devnum": 9,
    "vid": "0fd9",
    "pid": "0080",
    "product": "Stream Deck MK.2",
    "manufacturer": "Elgato",
    "serial": "",
    "device_class": "00",
    "is_deck": True,
}


class NoeudSpice(NoeudFactice):
    """Le nœud de NoeudFactice, plus l'état de la VM, sa configuration en
    vigueur (« --current »), « qm reboot » / « qm start », qui appliquent
    l'attente, et le billet de spiceproxy. `billet` : vrai pour le billet
    seul, faux pour un refus, ou le texte exact de la sortie."""

    def __init__(self, config, current=None, status="running", billet=True):
        super().__init__([], config)
        self.current = config if current is None else current
        self.status = status
        self.billet = billet

    def __call__(self, host, remote, timeout=120):
        if remote.startswith("qm status "):
            return 0, f"status: {self.status}\n"
        if remote.startswith("qm config ") and remote.endswith("--current"):
            return 0, self.current
        if remote.startswith(("qm reboot ", "qm start ")):
            self.lances.append(remote)
            self.status, self.current = "running", self.config
            return 0, ""
        if remote.startswith("pvesh create "):
            self.lances.append(remote)
            if not self.billet:
                return 2, "VM 101 not running\n"
            if isinstance(self.billet, str):
                return 0, self.billet
            return 0, json.dumps(BILLET)
        if remote.startswith("qm set "):
            # Le « qm set » s'écrit dans la configuration (en attente).
            mots = remote.split()
            if "-vga" in mots:
                self.config = re.sub(r"(?m)^vga:.*\n", "", self.config)
                self.config += f"vga: {mots[mots.index('-vga') + 1]}\n"
            self.config += "".join(
                f"{o[1:]}: spice\n" for o in mots if o.startswith("-usb")
            )
        return super().__call__(host, remote, timeout)


class TestRedirectionSpice(unittest.TestCase):
    """Menu Proxmox › USB › [3] : un deck de CE poste vers la VM par
    SPICE. Le nœud, ssh, remote-viewer et le service deck sont simulés ;
    on garde ce qui est posé sur la VM, ce qui est demandé, et que le .vv,
    qui porte un billet, est privé puis effacé."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)

    def _jouer(
        self,
        noeud,
        reponses,
        decks=(DECK_POSTE,),
        service_actif=True,
        display=":0",
        viewer_echoue=False,
    ):
        todo = _todo()
        todo._PVE_VV_WAIT = 0
        todo._PVE_VIEWER_LOG = os.path.join(self.dossier, "viewer.log")
        self.tunnels, self.viewers, self.vv, self.exec = [], [], [], []

        def run(argv, **_kw):
            self.tunnels.append(list(argv))
            return subprocess.CompletedProcess(argv, 0)

        def popen(argv, **_kw):
            if viewer_echoue:
                raise FileNotFoundError(2, "remote-viewer absent")
            chemin = argv[-1]
            mode = os.stat(chemin).st_mode & 0o777
            with open(chemin, encoding="utf-8") as fh:
                self.vv.append((chemin, mode, fh.read()))
            self.viewers.append(list(argv))
            return mock.Mock()

        env = {k: v for k, v in os.environ.items() if k != "WAYLAND_DISPLAY"}
        env.pop("DISPLAY", None)
        if display:
            env["DISPLAY"] = display
        sortie = io.StringIO()
        with (
            mock.patch.object(pve, "run", noeud),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch.object(
                TODO, "_qemu_usb_host_devices", return_value=list(decks)
            ),
            mock.patch.object(
                TODO,
                "_qemu_usb_service_state",
                return_value={"installed": True, "active": service_actif},
            ),
            mock.patch.object(
                TODO, "_qemu_usb_exec", side_effect=self.exec.append
            ),
            mock.patch.object(
                TODO, "_qemu_ensure_virt_viewer", return_value=True
            ),
            mock.patch.object(
                shutil, "which", return_value="/usr/bin/remote-viewer"
            ),
            mock.patch.object(subprocess, "run", run),
            mock.patch.object(subprocess, "Popen", popen),
            mock.patch("atexit.register"),
            contextlib.redirect_stdout(sortie),
        ):
            todo._pve_usb()
        return sortie.getvalue()

    def test_a_deployed_vm_gets_spice_then_the_viewer_opens(self):
        noeud = NoeudSpice("vga: serial0\nusb0: host=046d:c31c\n")
        # VM 1, [3], poser (o), redémarrer (o), arrêter le service (o),
        # retour.
        sortie = self._jouer(noeud, ["1", "3", "o", "o", "o", "0"])
        self.assertEqual(
            [
                "qm set 101 -vga qxl -usb1 spice",
                "qm reboot 101",
                "pvesh create /nodes/pve-essai/qemu/101/spiceproxy"
                " --output-format json",
            ],
            noeud.lances,
        )
        self.assertEqual(1, len(self.exec))
        self.assertIn("systemctl --user stop", self.exec[0])
        # Le tunnel, puis remote-viewer sur le .vv qui le désigne.
        self.assertEqual(1, len(self.tunnels))
        transfert = self.tunnels[0][self.tunnels[0].index("-L") + 1]
        port = int(transfert.split(":")[1])
        self.assertEqual(f"127.0.0.1:{port}:localhost:3128", transfert)
        chemin, mode, texte = self.vv[0]
        self.assertEqual(0o600, mode)
        self.assertIn(f"proxy=http://127.0.0.1:{port}\n", texte)
        self.assertEqual(pve.remote_viewer_argv(chemin), self.viewers[0])
        self.assertFalse(os.path.exists(chemin))
        # Le billet ne s'affiche jamais ; le rappel du service, si.
        self.assertNotIn("faux-billet", sortie)
        self.assertIn(
            t(
                "The display change takes effect at the next start of the VM"
                " (qm reboot, or stop and start), not at a reboot from inside"
                " the guest."
            ),
            sortie,
        )
        self.assertIn(
            t("When the viewer is closed, restart the deck service:"), sortie
        )

    def test_nothing_is_set_without_confirmation(self):
        noeud = NoeudSpice("vga: serial0\n")
        sortie = self._jouer(noeud, ["1", "3", "n", "0"])
        self.assertEqual([], noeud.lances)
        self.assertEqual([], self.tunnels + self.viewers)
        self.assertIn(t("Cancelled."), sortie)

    def test_a_ready_vm_asks_nothing(self):
        noeud = NoeudSpice("vga: qxl\nusb2: spice\n")
        self._jouer(noeud, ["1", "3", "0"], decks=())
        self.assertEqual(1, len(noeud.lances))
        self.assertTrue(noeud.lances[0].startswith("pvesh create "))
        self.assertEqual([], self.exec)
        self.assertEqual(1, len(self.viewers))

    def test_one_spice_port_per_deck_of_the_workstation(self):
        autre = dict(DECK_POSTE, sysname="1-5", devnum=10)
        noeud = NoeudSpice("vga: virtio-gl\nusb0: spice\n")
        self._jouer(
            noeud, ["1", "3", "o", "o", "0"], decks=(DECK_POSTE, autre)
        )
        self.assertEqual("qm set 101 -usb1 spice", noeud.lances[0])
        self.assertNotIn("-vga", noeud.lances[0])

    def test_a_stopped_vm_is_started(self):
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n", status="stopped")
        self._jouer(noeud, ["1", "3", "o", "0"], decks=())
        self.assertEqual("qm start 101", noeud.lances[0])
        self.assertEqual(1, len(self.viewers))

    def test_a_refused_restart_opens_nothing(self):
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n", current="vga: std\n")
        self._jouer(noeud, ["1", "3", "n", "0"], decks=())
        self.assertEqual([], noeud.lances)
        self.assertEqual([], self.tunnels + self.viewers)

    def test_keeping_the_deck_service_cancels(self):
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n")
        sortie = self._jouer(noeud, ["1", "3", "n", "0"])
        self.assertEqual([], self.exec)
        self.assertEqual([], self.tunnels + self.viewers)
        self.assertIn(t("Cancelled."), sortie)

    def test_without_a_display_the_command_is_shown(self):
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n")
        sortie = self._jouer(noeud, ["1", "3", "0"], display="")
        self.assertEqual([], self.tunnels + self.viewers + noeud.lances)
        self.assertIn("remote-viewer", sortie)
        self.assertIn("<file.vv>", sortie)

    def test_no_ticket_opens_nothing(self):
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n", billet=False)
        sortie = self._jouer(noeud, ["1", "3", "0"], decks=())
        self.assertEqual([], self.viewers)
        self.assertIn(t("No SPICE ticket from the Proxmox node."), sortie)
        self.assertIn("VM 101 not running", sortie)

    def test_no_ticket_never_shows_the_password(self):
        """Une sortie mêlée de stderr dont l'objet JSON n'est pas un billet
        complet : rien n'est ouvert, et aucune ligne du JSON n'est
        montrée."""
        partiel = dict(BILLET, proxy="")
        noeud = NoeudSpice(
            "vga: qxl\nusb0: spice\n",
            billet=json.dumps(partiel) + "\nperl: warning: locale\n",
        )
        sortie = self._jouer(noeud, ["1", "3", "0"], decks=())
        self.assertEqual([], self.viewers)
        self.assertIn("perl: warning: locale", sortie)
        self.assertNotIn(BILLET["password"], sortie)

    def test_a_ticket_followed_by_noise_is_read(self):
        noeud = NoeudSpice(
            "vga: qxl\nusb0: spice\n",
            billet="sudo: avertissement invente\n"
            + json.dumps(BILLET)
            + "\nperl: warning: locale\n",
        )
        self._jouer(noeud, ["1", "3", "0"], decks=())
        self.assertEqual(1, len(self.viewers))

    def test_the_service_is_left_running_when_no_ticket_comes(self):
        """L'accord est demandé tôt, l'arrêt n'a lieu qu'avec le billet :
        un échec avant laisse le deck de ce poste en service."""
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n", billet=False)
        self._jouer(noeud, ["1", "3", "o", "0"])
        self.assertEqual([], self.exec)
        self.assertEqual([], self.viewers)

    def test_the_service_is_restarted_when_the_viewer_fails(self):
        noeud = NoeudSpice("vga: qxl\nusb0: spice\n")
        sortie = self._jouer(noeud, ["1", "3", "o", "0"], viewer_echoue=True)
        self.assertEqual(2, len(self.exec))
        self.assertIn("systemctl --user stop", self.exec[0])
        self.assertIn("systemctl --user start", self.exec[1])
        self.assertNotIn(
            t("When the viewer is closed, restart the deck service:"), sortie
        )


class TestJournalRemoteViewer(unittest.TestCase):
    """Le journal de remote-viewer vit dans le cache de l'utilisateur, en
    0600, et refuse un lien symbolique posé à sa place."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)

    def test_the_log_is_private_in_the_user_cache(self):
        todo = _todo()
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.dossier}):
            chemin = todo._pve_viewer_log()
        self.assertEqual(
            os.path.join(self.dossier, "erplibre", "remote-viewer.log"),
            chemin,
        )
        with todo._pve_open_log(chemin) as log:
            log.write(b"x")
        self.assertEqual(0o600, os.stat(chemin).st_mode & 0o777)
        dossier = os.path.dirname(chemin)
        self.assertEqual(0o700, os.stat(dossier).st_mode & 0o777)

    def test_a_symlink_in_place_of_the_log_is_refused(self):
        cible = os.path.join(self.dossier, "cible")
        lien = os.path.join(self.dossier, "remote-viewer.log")
        os.symlink(cible, lien)
        with self.assertRaises(OSError):
            _todo()._pve_open_log(lien)
        self.assertFalse(os.path.exists(cible))


if __name__ == "__main__":
    unittest.main(verbosity=1)
