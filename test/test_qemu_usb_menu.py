#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu USB de QEMU/KVM : ce qu'il lance, et sur quel hôte.

Chaque action se joue sur un TODO sans __init__. Un hyperviseur factice
répond aux sondes virsh (domstate, dumpxml) et tient l'état que les
commandes lancées changent : un « virsh define » remplace sa définition,
un « virsh shutdown » l'éteint. Le lanceur retient chaque commande et le
contenu du fichier XML qu'elle nomme. Aucune commande ne part.

Ce que ces tests gardent :

- l'attachement lance attach-device par vue choisie, saute la vue qui a
  déjà le périphérique, et ne lance rien sans confirmation ;
- sudo ne précède virsh que pour qemu:///system local, jamais qemu+ssh ;
- un hôte de ~/.ssh/config se joint par son ProxyJump, et un Proxmox VE
  est refusé en disant que son attribution est toujours persistante ;
- le service deck de l'hôte n'est arrêté qu'après accord, et un refus
  annule ; le détachement d'un deck propose de le relancer ;
- la redirection SPICE place l'affichage SPICE avant le VNC, éteint la VM
  en marche sur accord et la relance ;
- virt-viewer reçoit les options usbredir seulement quand on les demande ;
- le rattachement auto copie le CLI sur l'hyperviseur et le lance sous
  sudo par ssh -t ;
- le source envoyé à « python3 -I - » sur un hyperviseur s'exécute seul ;
- chaque libellé du menu a ses deux langues.

Valeurs inventées : hôtes en .invalid, VM vm-a et vm-b, série FAKE0001.
"""

import ast
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo import qemu_usb as qu  # noqa: E402
from script.todo import (
    qemu_usb_menu,  # noqa: E402
    todo_i18n,  # noqa: E402
)
from script.todo.todo import TODO  # noqa: E402

UNITE = "erplibre-home-streamdeck.service"
SAUT = "saut.invalid"

VNC = (
    "<graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'>"
    "<listen type='address' address='127.0.0.1'/></graphics>"
)
SPICE = (
    "<graphics type='spice' autoport='yes' listen='127.0.0.1'>"
    "<listen type='address' address='127.0.0.1'/></graphics>"
)
XHCI = "<controller type='usb' index='0' model='qemu-xhci' ports='15'/>"
REDIR = "<redirdev bus='usb' type='spicevmc'/>"
HOSTDEV_CFG = (
    "<hostdev mode='subsystem' type='usb' managed='yes'>"
    "<source startupPolicy='optional'><vendor id='0x0fd9'/>"
    "<product id='0x0080'/></source></hostdev>"
)
HOSTDEV_LIVE = (
    "<hostdev mode='subsystem' type='usb' managed='yes'>"
    "<source startupPolicy='optional'><vendor id='0x0fd9'/>"
    "<product id='0x0080'/><address bus='3' device='5'/></source></hostdev>"
)


def domaine(*devices, name="vm-a"):
    return (
        f"<domain type='kvm'><name>{name}</name>"
        "<os><type arch='x86_64' machine='q35'>hvm</type></os>"
        f"<devices>{''.join(devices)}</devices></domain>"
    )


DECK = {
    "sysname": "3-2",
    "busnum": 3,
    "devnum": 5,
    "vid": "0fd9",
    "pid": "0080",
    "product": "Stream Deck MK.2",
    "manufacturer": "Elgato",
    "serial": "FAKE0001",
    "device_class": "00",
    "is_deck": True,
}
AUTRE = {
    "sysname": "1-4",
    "busnum": 1,
    "devnum": 2,
    "vid": "1234",
    "pid": "5678",
    "product": "Gadget",
    "manufacturer": "Exemple",
    "serial": "",
    "device_class": "00",
    "is_deck": False,
}


class Hyperviseur:
    """Les sondes virsh et le lanceur, sur un seul état.

    capture() répond à domstate et dumpxml, et note chaque argv ;
    exec_command_live() retient la commande, le XML du fichier qu'elle
    nomme, et applique define, shutdown et start à l'état."""

    def __init__(self, etat="running", config="", live=None, code=0):
        self.etat = etat
        self.config = config
        self.live = config if live is None else live
        self.code = code
        self.sondes = []
        self.commandes = []
        self.xml = []
        self.capture_extra = {}

    def capture(self, argv, stdin_text=None, timeout=30):
        argv = list(argv)
        self.sondes.append(argv)
        for cle, reponse in self.capture_extra.items():
            if cle in argv:
                return reponse
        if "domstate" in argv:
            return 0, self.etat + "\n"
        if "dumpxml" in argv:
            return 0, self.config if "--inactive" in argv else self.live
        return 1, ""

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        mots = shlex.split(cmd)
        for mot in mots:
            if mot.endswith(".xml") and os.path.isfile(mot):
                with open(mot, encoding="utf-8") as fh:
                    self.xml.append(fh.read())
        if self.code == 0 and "virsh" in mots:
            if "define" in mots:
                self.config = self.xml[-1]
            elif "shutdown" in mots:
                self.etat = "shut off"
            elif "start" in mots:
                self.etat = "running"
        return self.code


class _Cas(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.hv = Hyperviseur(config=domaine(XHCI, VNC))
        self.todo.execute = self.hv
        self.todo._qemu_usb_capture = self.hv.capture
        self.todo._qemu_list_domains = lambda: ["vm-a"]
        self.todo._ssh_config_hosts = lambda: []
        self.todo._ssh_proxyjump = lambda name: SAUT
        self.todo._hypervisor_is_proxmox = lambda jump: False
        self.devices = [DECK, AUTRE]
        self.todo._qemu_usb_host_devices = lambda jump="": list(self.devices)
        self.service = {"installed": False, "active": False}
        self.services_lus = []

        def etat_service(jump=""):
            self.services_lus.append(jump)
            return dict(self.service)

        self.todo._qemu_usb_service_state = etat_service
        patch = mock.patch.object(qemu_usb_menu, "sudo_prefix", lambda: "")
        patch.start()
        self.addCleanup(patch.stop)

    def jouer(self, methode, reponses, *args, **kwargs):
        sortie = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=list(reponses)),
            redirect_stdout(sortie),
        ):
            getattr(self.todo, methode)(*args, **kwargs)
        return sortie.getvalue()

    def distant(self):
        """La seule cible est un hôte de ssh_config derrière SAUT."""
        self.todo._qemu_list_domains = lambda: []
        self.todo._ssh_config_hosts = lambda: [f"{SAUT}+vm-b"]


class TestAttacher(_Cas):
    def test_both_views_run_attach_device_with_the_xml_file(self):
        """VM, deck, « live et config », oui : deux attach-device."""
        self.hv.live = domaine(XHCI, VNC)
        out = self.jouer("_qemu_usb_attach", ["1", "1", "1", "y"])
        self.assertEqual(2, len(self.hv.commandes), out)
        live, config = (shlex.split(c) for c in self.hv.commandes)
        self.assertEqual(
            ["virsh", "--connect", "qemu:///system", "attach-device"],
            live[:4],
        )
        self.assertEqual("--live", live[-1])
        self.assertEqual("--config", config[-1])
        self.assertNotIn(qu.XML_PLACEHOLDER, self.hv.commandes[0])
        self.assertIn("<vendor id='0x0fd9'/>", self.hv.xml[0])
        self.assertIn("startupPolicy='optional'", self.hv.xml[0])

    def test_the_temporary_xml_file_is_removed(self):
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "y"])
        for cmd in self.hv.commandes:
            fichier = shlex.split(cmd)[-2]
            self.assertFalse(os.path.exists(fichier), fichier)

    def test_a_view_that_has_it_already_is_skipped(self):
        self.hv.config = domaine(XHCI, VNC, HOSTDEV_CFG)
        self.hv.live = domaine(XHCI, VNC)
        out = self.jouer("_qemu_usb_attach", ["1", "1", "1", "y"])
        self.assertEqual(1, len(self.hv.commandes))
        self.assertIn("--live", self.hv.commandes[0])
        self.assertIn(todo_i18n.t("already attached"), out)

    def test_no_confirmation_runs_nothing(self):
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "n"])
        self.assertEqual([], self.hv.commandes)

    def test_live_only_on_a_stopped_vm_has_nothing_to_do(self):
        self.hv.etat = "shut off"
        out = self.jouer("_qemu_usb_attach", ["1", "1", "2"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(todo_i18n.t("the VM is not running"), out)
        self.assertIn(todo_i18n.t("Nothing to do."), out)

    def test_local_virsh_gets_sudo_when_the_group_is_missing(self):
        with mock.patch.object(qemu_usb_menu, "sudo_prefix", lambda: "sudo "):
            self.jouer("_qemu_usb_attach", ["1", "1", "3", "y"])
        self.assertTrue(self.hv.commandes[0].startswith("sudo virsh "))
        # Les sondes passent aussi par sudo : la définition se lit en root.
        self.assertEqual("sudo", self.hv.sondes[0][0])

    def test_a_remote_vm_goes_through_its_proxyjump_without_sudo(self):
        self.distant()
        with mock.patch.object(qemu_usb_menu, "sudo_prefix", lambda: "sudo "):
            self.jouer("_qemu_usb_attach", ["1", "1", "3", "y"])
        argv = shlex.split(self.hv.commandes[0])
        self.assertEqual(
            ["virsh", "--connect", f"qemu+ssh://{SAUT}/system"], argv[:3]
        )
        self.assertIn("vm-b", argv)

    def test_a_proxmox_hypervisor_is_refused_and_said_persistent(self):
        self.distant()
        self.todo._hypervisor_is_proxmox = lambda jump: True
        out = self.jouer("_qemu_usb_attach", ["1"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(
            todo_i18n.t("is always persistent (no live or config choice)."),
            out,
        )

    def test_two_identical_decks_pin_the_address(self):
        jumeau = dict(DECK, sysname="3-3", devnum=6, serial="FAKE0002")
        self.devices = [DECK, jumeau]
        self.jouer("_qemu_usb_attach", ["1", "1", "3", "y"])
        self.assertIn("<address bus='3' device='5'/>", self.hv.xml[0])

    def test_a_non_deck_device_never_asks_about_the_deck_service(self):
        self.service = {"installed": True, "active": True}
        self.jouer("_qemu_usb_attach", ["1", "2", "3", "y"])
        self.assertEqual([], self.services_lus)
        self.assertEqual(1, len(self.hv.commandes))


class TestServiceDeckDeLHote(_Cas):
    def setUp(self):
        super().setUp()
        self.service = {"installed": True, "active": True}

    def test_refusing_to_stop_it_cancels_the_passthrough(self):
        out = self.jouer("_qemu_usb_attach", ["1", "1", "1", "n"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(UNITE, out)

    def test_accepting_stops_it_before_the_attach(self):
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "y", "y"])
        self.assertEqual(
            f"systemctl --user stop {UNITE}", self.hv.commandes[0]
        )
        self.assertIn("attach-device", self.hv.commandes[1])

    def test_on_a_remote_host_it_is_stopped_over_ssh(self):
        self.distant()
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "y", "y"])
        self.assertEqual([SAUT], self.services_lus)
        self.assertEqual(
            f"ssh {SAUT} systemctl --user stop {UNITE}", self.hv.commandes[0]
        )

    def test_declining_the_final_question_stops_nothing(self):
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "y", "n"])
        self.assertEqual([], self.hv.commandes)

    def test_config_only_leaves_the_service_alone(self):
        """Sans étape live, la VM ne prend pas le deck maintenant : rien
        n'est demandé ni arrêté."""
        self.jouer("_qemu_usb_attach", ["1", "1", "3", "y"])
        self.assertEqual([], self.services_lus)
        self.assertEqual(1, len(self.hv.commandes))
        self.assertIn("--config", self.hv.commandes[0])

    def test_a_stopped_vm_leaves_the_service_alone(self):
        self.hv.etat = "shut off"
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "y"])
        self.assertEqual([], self.services_lus)
        self.assertNotIn(f"systemctl --user stop {UNITE}", self.hv.commandes)

    def test_a_failed_attach_offers_to_restart_it(self):
        etats = iter(
            [
                {"installed": True, "active": True},
                {"installed": True, "active": False},
            ]
        )
        self.todo._qemu_usb_service_state = lambda jump="": next(etats)
        self.hv.code = 1
        self.jouer("_qemu_usb_attach", ["1", "1", "1", "y", "y", "y"])
        self.assertEqual(
            f"systemctl --user stop {UNITE}", self.hv.commandes[0]
        )
        self.assertEqual(
            f"systemctl --user start {UNITE}", self.hv.commandes[-1]
        )


class TestDetacher(_Cas):
    def setUp(self):
        super().setUp()
        self.hv.config = domaine(XHCI, VNC, HOSTDEV_CFG)
        self.hv.live = domaine(XHCI, VNC, HOSTDEV_LIVE)

    def test_one_row_per_device_across_both_views(self):
        lignes = self.todo._qemu_usb_attached(
            {
                "live": qu.usb_state(self.hv.live),
                "config": qu.usb_state(self.hv.config),
            }
        )
        self.assertEqual(1, len(lignes))
        self.assertEqual(["live", "config"], lignes[0]["views"])
        self.assertEqual((3, 5), (lignes[0]["bus"], lignes[0]["dev"]))

    def test_both_views_are_detached(self):
        self.jouer("_qemu_usb_detach", ["1", "1", "1", "y"])
        self.assertEqual(2, len(self.hv.commandes))
        self.assertTrue(all("detach-device" in c for c in self.hv.commandes))

    def test_a_deck_back_on_the_host_offers_to_restart_its_service(self):
        self.service = {"installed": True, "active": False}
        self.jouer("_qemu_usb_detach", ["1", "1", "1", "y", "y"])
        self.assertEqual(
            f"systemctl --user start {UNITE}", self.hv.commandes[-1]
        )

    def test_config_only_does_not_offer_the_restart(self):
        """En config seule, le deck reste dans la VM en marche."""
        self.service = {"installed": True, "active": False}
        self.jouer("_qemu_usb_detach", ["1", "1", "3", "y"])
        self.assertEqual(1, len(self.hv.commandes))
        self.assertEqual([], self.services_lus)

    def test_nothing_attached_says_so(self):
        self.hv.config = self.hv.live = domaine(XHCI, VNC)
        out = self.jouer("_qemu_usb_detach", ["1"])
        self.assertIn(
            todo_i18n.t("No USB device is attached to this VM."), out
        )


class TestVoir(_Cas):
    def test_a_vnc_only_vm_is_not_ready(self):
        self.hv.config = self.hv.live = domaine(XHCI, VNC, HOSTDEV_LIVE)
        out = self.jouer("_qemu_usb_show", ["1"])
        self.assertIn("hostdev 0fd9:0080 @ 003.005", out)
        self.assertIn(
            todo_i18n.t("Not ready: entry 6 enables it (VM shut off)."), out
        )

    def test_spice_first_with_slots_is_ready(self):
        self.hv.config = self.hv.live = domaine(XHCI, SPICE, VNC, REDIR)
        out = self.jouer("_qemu_usb_show", ["1"])
        self.assertIn("spice → vnc", out)
        self.assertIn(
            todo_i18n.t("Ready: virt-viewer offers USB redirection."), out
        )


class TestRedirectionSpice(_Cas):
    def test_a_shut_off_vm_is_redefined_spice_before_vnc(self):
        self.hv.etat = "shut off"
        self.jouer("_qemu_usb_enable_spice", ["1", "n", "y"])
        self.assertEqual(1, len(self.hv.commandes))
        self.assertIn(" define ", self.hv.commandes[0])
        etat = qu.usb_state(self.hv.config)
        self.assertEqual(["spice", "vnc"], etat["graphics"])
        self.assertIn("spicevmc", etat["redirdevs"])

    def test_a_running_vm_is_left_alone_without_consent(self):
        self.jouer("_qemu_usb_enable_spice", ["1", "n", "n"])
        self.assertEqual([], self.hv.commandes)
        self.assertEqual("running", self.hv.etat)

    def test_a_running_vm_is_shut_down_redefined_and_restarted(self):
        self.jouer("_qemu_usb_enable_spice", ["1", "y", "y", "y"])
        verbes = [shlex.split(c)[3] for c in self.hv.commandes]
        self.assertEqual(["shutdown", "define", "start"], verbes)
        self.assertEqual("running", self.hv.etat)
        etat = qu.usb_state(self.hv.config)
        self.assertEqual(
            ["0fd9"], [r["vendor"] for r in etat["redirfilter"] if r["allow"]]
        )

    def test_nothing_missing_runs_nothing(self):
        self.hv.etat = "shut off"
        self.hv.config = qu.spice_usbredir_xml(domaine(XHCI, VNC))[0]
        out = self.jouer("_qemu_usb_enable_spice", ["1", "n"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(
            todo_i18n.t("SPICE USB redirection is already set up."), out
        )


class TestVirtViewer(_Cas):
    def lancer(self, reponses):
        lance = {}

        def popen(cmd, **kw):
            lance["cmd"] = cmd
            return mock.Mock()

        with (
            mock.patch.dict("os.environ", {"DISPLAY": ":0"}),
            mock.patch("shutil.which", lambda c: "/usr/bin/virt-viewer"),
            mock.patch("subprocess.Popen", popen),
        ):
            out = self.jouer("_qemu_usb_viewer", reponses)
        return lance.get("cmd"), out

    def test_a_vm_without_redirection_opens_nothing(self):
        cmd, out = self.lancer(["1"])
        self.assertIsNone(cmd)
        self.assertIn(todo_i18n.t("entry 6 enables it."), out)

    def test_a_ready_vm_gets_the_usbredir_options(self):
        self.hv.config = self.hv.live = domaine(XHCI, SPICE, VNC, REDIR)
        self.devices = [AUTRE]
        cmd, _out = self.lancer(["1"])
        filtre = qu.usbredir_filter()
        self.assertEqual(
            [
                "virt-viewer",
                "-c",
                "qemu:///system",
                f"--spice-usbredir-auto-redirect-filter={filtre}",
                f"--spice-usbredir-redirect-on-connect={filtre}",
                "vm-a",
            ],
            cmd,
        )

    def test_a_deck_here_with_its_service_running_asks_first(self):
        self.hv.config = self.hv.live = domaine(XHCI, SPICE, VNC, REDIR)
        self.service = {"installed": True, "active": True}
        cmd, _out = self.lancer(["1", "n"])
        self.assertIsNone(cmd)
        cmd, _out = self.lancer(["1", "y"])
        self.assertEqual(
            f"systemctl --user stop {UNITE}", self.hv.commandes[0]
        )
        self.assertIsNotNone(cmd)

    def test_the_tunnel_menu_argv_is_unchanged(self):
        """Sans usbredir, l'argv reste celui du menu des tunnels."""
        lance = {}

        def popen(cmd, **kw):
            lance["cmd"] = cmd
            return mock.Mock()

        with (
            mock.patch.dict("os.environ", {"DISPLAY": ":0"}),
            mock.patch("shutil.which", lambda c: "/usr/bin/virt-viewer"),
            mock.patch("subprocess.Popen", popen),
            redirect_stdout(io.StringIO()),
        ):
            self.todo._qemu_virt_viewer("vm-a", "virsh")
        self.assertEqual(
            ["virt-viewer", "-c", "qemu:///system", "vm-a"], lance["cmd"]
        )

    def test_without_display_the_workstation_line_carries_the_filter(self):
        self.todo._qemu_self_address = staticmethod(
            lambda: ("192.0.2.10", True)
        )
        sortie = io.StringIO()
        with (
            mock.patch.dict(
                "os.environ",
                {"DISPLAY": "", "WAYLAND_DISPLAY": "", "USER": "compte"},
            ),
            redirect_stdout(sortie),
        ):
            self.todo._qemu_virt_viewer("vm-a", "virsh", usbredir=True)
        ligne = next(
            ligne.strip()
            for ligne in sortie.getvalue().splitlines()
            if ligne.strip().startswith("virt-viewer ")
        )
        # La ligne se colle dans un shell : relue par lui, elle rend l'argv.
        self.assertEqual(
            qu.virt_viewer_argv(
                "qemu+ssh://compte@192.0.2.10/system", "vm-a", usbredir=True
            ),
            shlex.split(ligne),
        )


class TestRattachementAuto(_Cas):
    def test_local_install_runs_the_repository_cli_under_sudo(self):
        with mock.patch("os.geteuid", lambda: 1000):
            self.jouer("_qemu_usb_autoreattach", ["1", "1", "y"])
        self.assertEqual(
            shlex.join(
                [
                    "sudo",
                    "python3",
                    "-I",
                    "-B",
                    qemu_usb_menu.CLI,
                    "install-autoreattach",
                ]
            ),
            self.hv.commandes[0],
        )

    def test_remote_install_copies_both_files_then_cleans_up(self):
        self.distant()
        tmp = "/tmp/erplibre-usb.AbC123"
        self.hv.capture_extra["mktemp"] = (0, tmp + "\n")
        self.jouer("_qemu_usb_autoreattach", ["1", "1", "y"])
        scp, install = self.hv.commandes
        self.assertEqual(
            shlex.join(
                ["scp", qemu_usb_menu.CLI, qemu_usb_menu.LIB, f"{SAUT}:{tmp}/"]
            ),
            scp,
        )
        self.assertEqual(
            shlex.join(
                [
                    "ssh",
                    "-t",
                    SAUT,
                    f"sudo python3 -I -B {tmp}/usb_qemu.py"
                    " install-autoreattach",
                ]
            ),
            install,
        )
        self.assertIn(
            ["ssh", *qemu_usb_menu.SSH_OPTS, SAUT, "rm", "-rf", tmp],
            self.hv.sondes,
        )

    def test_remote_install_cancelled_still_cleans_up(self):
        self.distant()
        tmp = "/tmp/erplibre-usb.AbC123"
        self.hv.capture_extra["mktemp"] = (0, tmp + "\n")
        self.jouer("_qemu_usb_autoreattach", ["1", "1", "n"])
        self.assertEqual([], self.hv.commandes)
        self.assertEqual(["rm", "-rf", tmp], self.hv.sondes[-1][-3:])

    def test_mapping_on_a_hypervisor_needs_the_installed_cli(self):
        self.distant()
        self.todo._qemu_usb_cli_installed = lambda jump="": False
        out = self.jouer("_qemu_usb_autoreattach", ["1", "2"])
        self.assertEqual([], self.hv.commandes)
        self.assertIn(
            todo_i18n.t("install the udev rule and the unit first."), out
        )

    def test_mapping_a_remote_deck_uses_the_installed_copy(self):
        self.distant()
        self.todo._qemu_usb_cli_installed = lambda jump="": True
        self.jouer("_qemu_usb_autoreattach", ["1", "2", "1", "y"])
        self.assertEqual(
            shlex.join(
                [
                    "ssh",
                    "-t",
                    SAUT,
                    f"sudo python3 -I -B {qu.LIBEXEC_CLI} mapping add"
                    " vm-b 0fd9:0080",
                ]
            ),
            self.hv.commandes[0],
        )

    def test_a_remote_serial_reaches_the_cli_as_one_inert_argument(self):
        """ssh recolle ses arguments et le shell distant les relit : la
        commande locale relue deux fois (shell local, puis distant) rend
        le numéro de série entier, espace et point-virgule compris."""
        self.distant()
        self.todo._qemu_usb_cli_installed = lambda jump="": True
        serie = "AB 12;touch /tmp/x.invalid"
        jumeau = dict(DECK, sysname="3-3", devnum=6, serial="FAKE0002")
        self.devices = [dict(DECK, serial=serie), jumeau]
        self.jouer("_qemu_usb_autoreattach", ["1", "2", "1", "y"])
        local = shlex.split(self.hv.commandes[0])
        self.assertEqual(["ssh", "-t", SAUT], local[:3])
        self.assertEqual(4, len(local))
        distant = shlex.split(local[3])
        self.assertEqual(["--serial", serie], distant[-2:])

    def test_the_serial_enters_only_to_tell_twins_apart(self):
        self.todo._qemu_usb_cli_installed = lambda jump="": True
        jumeau = dict(DECK, sysname="3-3", devnum=6, serial="FAKE0002")
        self.devices = [DECK, jumeau]
        with mock.patch("os.geteuid", lambda: 1000):
            self.jouer("_qemu_usb_autoreattach", ["1", "2", "1", "y"])
        self.assertTrue(
            self.hv.commandes[0].endswith("--serial FAKE0001"),
            self.hv.commandes[0],
        )

    def test_unmap_lists_only_this_vm(self):
        self.todo._qemu_usb_read_mapping = lambda jump="": qu.mapping_loads(
            json.dumps(
                [
                    {"vid": "0fd9", "pid": "0080", "domain": "vm-z"},
                    {
                        "vid": "0fd9",
                        "pid": "006c",
                        "domain": "vm-a",
                        "serial": "FAKE0001",
                    },
                ]
            )
        )
        with mock.patch("os.geteuid", lambda: 0):
            self.jouer("_qemu_usb_autoreattach", ["1", "3", "1", "y"])
        self.assertEqual(
            shlex.join(
                [
                    "python3",
                    "-I",
                    "-B",
                    qemu_usb_menu.CLI,
                    "mapping",
                    "remove",
                    "0fd9:006c",
                    "--domain",
                    "vm-a",
                    "--serial",
                    "FAKE0001",
                ]
            ),
            self.hv.commandes[0],
        )


class TestRetraitSansSerie(_Cas):
    def test_unmapping_the_entry_without_serial_spares_the_twins(self):
        """L'entrée sans série part par --serial "" : le CLI garde alors
        celle du même modèle qui porte une série."""
        self.todo._qemu_usb_read_mapping = lambda jump="": qu.mapping_loads(
            json.dumps(
                [
                    {"vid": "0fd9", "pid": "0080", "domain": "vm-a"},
                    {
                        "vid": "0fd9",
                        "pid": "0080",
                        "domain": "vm-a",
                        "serial": "FAKE0001",
                    },
                ]
            )
        )
        with mock.patch("os.geteuid", lambda: 0):
            self.jouer("_qemu_usb_autoreattach", ["1", "3", "1", "y"])
        mots = shlex.split(self.hv.commandes[0])
        self.assertEqual(["--serial", ""], mots[-2:])


class TestLeContratDuCli(_Cas):
    """Chaque commande que le menu compose se lit par l'analyseur du CLI
    lui-même : une option renommée là-bas fait tomber ce test-ci."""

    @classmethod
    def setUpClass(cls):
        chemin = RACINE / "script" / "qemu" / "usb_qemu.py"
        spec = importlib.util.spec_from_file_location("usb_qemu_cli", chemin)
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def lire(self, cmd):
        mots = shlex.split(cmd)
        reste = mots[mots.index(qemu_usb_menu.CLI) + 1 :]
        return self.cli.build_parser().parse_args(reste)

    def test_every_composed_command_parses(self):
        self.todo._qemu_usb_cli_installed = lambda jump="": True
        self.todo._qemu_usb_read_mapping = lambda jump="": [
            {"vid": "0fd9", "pid": "0080", "domain": "vm-a"}
        ]
        jumeau = dict(DECK, sysname="3-3", devnum=6, serial="FAKE0002")
        self.devices = [DECK, jumeau]
        with mock.patch("os.geteuid", lambda: 1000):
            for action in (["1"], ["2", "1"], ["3", "1"], ["5"]):
                self.jouer("_qemu_usb_autoreattach", ["1", *action, "y"])
        install, add, remove, desinstalle = map(self.lire, self.hv.commandes)
        self.assertEqual("install-autoreattach", install.cmd)
        self.assertEqual(
            ("add", "vm-a", "0fd9:0080", "FAKE0001"),
            (add.mapping_cmd, add.domain, add.selector, add.serial),
        )
        self.assertEqual(
            ("remove", "0fd9:0080", "vm-a"),
            (remove.mapping_cmd, remove.selector, remove.domain),
        )
        self.assertEqual("remove-autoreattach", desinstalle.cmd)


class TestSondes(unittest.TestCase):
    def test_systemctl_show_is_parsed(self):
        lire = TODO._qemu_usb_parse_service
        self.assertEqual(
            {"installed": True, "active": True},
            lire("LoadState=loaded\nActiveState=active\n"),
        )
        self.assertEqual(
            {"installed": True, "active": False},
            lire("LoadState=loaded\nActiveState=inactive\n"),
        )
        self.assertEqual(
            {"installed": False, "active": False},
            lire("LoadState=not-found\nActiveState=inactive\n"),
        )
        self.assertEqual({"installed": False, "active": False}, lire(""))

    def test_the_remote_listing_source_runs_on_its_own(self):
        """Le source envoyé à ssh … python3 -I - est joué ici, sans ssh :
        il doit s'exécuter hors du dépôt et imprimer une liste JSON."""
        todo = TODO.__new__(TODO)
        recu = {}

        def capture(argv, stdin_text=None, timeout=30):
            recu["argv"] = argv
            res = subprocess.run(
                [sys.executable, "-I", "-"],
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=30,
                cwd="/",
            )
            return res.returncode, res.stdout

        todo._qemu_usb_capture = capture
        devs = todo._qemu_usb_host_devices(SAUT)
        self.assertIsInstance(devs, list)
        self.assertEqual(
            ["ssh", *qemu_usb_menu.SSH_OPTS, SAUT, "python3", "-I", "-"],
            recu["argv"],
        )

    def test_an_unreachable_hypervisor_lists_nothing(self):
        todo = TODO.__new__(TODO)
        todo._qemu_usb_capture = lambda argv, stdin_text=None: (255, "")
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(todo._qemu_usb_host_devices(SAUT))


class TestLeMenu(unittest.TestCase):
    def test_entry_one_lists_then_zero_leaves(self):
        todo = TODO.__new__(TODO)
        todo._qemu_usb_host_devices = lambda jump="": [AUTRE]
        todo._menu_header = lambda: ""
        sortie = io.StringIO()
        with (
            mock.patch("click.prompt", side_effect=["1", "0"]),
            redirect_stdout(sortie),
        ):
            self.assertFalse(todo._qemu_usb_menu())
        self.assertIn("001.002  1234:5678  Exemple Gadget", sortie.getvalue())
        self.assertIn(
            todo_i18n.t("No Stream Deck plugged in here."), sortie.getvalue()
        )

    def test_the_breadcrumb_names_it(self):
        self.assertEqual("USB", TODO._MENU_LABELS["_qemu_usb_menu"])

    def test_every_label_has_both_languages(self):
        source = (RACINE / "script/todo/qemu_usb_menu.py").read_text("utf-8")
        cles = {
            n.args[0].value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        }
        self.assertGreater(len(cles), 50)
        manques = sorted(
            c
            for c in cles
            if set(todo_i18n.TRANSLATIONS.get(c, {})) < {"fr", "en"}
        )
        self.assertEqual([], manques)


if __name__ == "__main__":
    unittest.main()
