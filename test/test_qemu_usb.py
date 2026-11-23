#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Logique pure du passage USB vers les VM : sysfs, XML, plans, textes.

Tout se joue sur un sysfs jetable et des XML écrits à la main, de la forme
que « virsh dumpxml » rend pour une VM de bureau. Aucune commande libvirt
n'est lancée, sauf virt-xml-validate qui contrôle les XML produits contre
le schéma de libvirt ; sans lui, ces cas se disent sautés.

Ce que ces tests gardent :

- les decks (0fd9) passent en tête ; concentrateurs, racines et interfaces
  sont écartés ;
- deux decks identiques rendent le VID:PID ambigu, et l'attachement est
  alors épinglé par bus/numéro ;
- chaque plan est idempotent par vue (attach-device ne l'est pas), saute
  --live sur une VM arrêtée, et refuse une VM sans USB ;
- SPICE est posé AVANT le VNC existant, une seule fois ;
- virt-viewer sans redirection garde l'argv exact qu'attend le menu ;
- le module se charge hors du dépôt, par son chemin, en Python isolé.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from script.todo import qemu_usb as u

MODULE = Path(u.__file__)
VALIDATE = shutil.which("virt-xml-validate")
URI_DISTANT = "qemu+ssh://saut.invalid/system"
VM = "vm-essai"

# Forme de « virsh dumpxml --inactive » d'une VM de bureau créée par
# deploy_qemu.py : VNC sur la boucle locale, contrôleur qemu-xhci, métadonnée
# libosinfo dans son espace de noms.
DOMAINE_VNC = """<domain type='kvm'>
  <name>vm-essai</name>
  <uuid>00000000-0000-4000-8000-000000000001</uuid>
  <metadata>
    <libosinfo:libosinfo \
xmlns:libosinfo="http://libosinfo.org/xmlns/libvirt/domain/1.0">
      <libosinfo:os id="http://debian.org/debian/12"/>
    </libosinfo:libosinfo>
  </metadata>
  <memory unit='KiB'>2097152</memory>
  <currentMemory unit='KiB'>2097152</currentMemory>
  <vcpu placement='static'>2</vcpu>
  <os>
    <type arch='x86_64' machine='q35'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <cpu mode='host-passthrough'/>
  <clock offset='utc'>
    <timer name='rtc' tickpolicy='catchup'/>
    <timer name='pit' tickpolicy='delay'/>
    <timer name='hpet' present='no'/>
  </clock>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <controller type='usb' index='0' model='qemu-xhci' ports='15'/>
    <controller type='pci' index='0' model='pcie-root'/>
    <controller type='virtio-serial' index='0'/>
    <serial type='pty'>
      <target port='0'/>
    </serial>
    <console type='pty'>
      <target type='serial' port='0'/>
    </console>
    <channel type='unix'>
      <target type='virtio' name='org.qemu.guest_agent.0'/>
    </channel>
    <input type='tablet' bus='usb'/>
    <graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'>
      <listen type='address' address='127.0.0.1'/>
    </graphics>
    <video>
      <model type='virtio' heads='1' primary='yes'/>
    </video>
    <memballoon model='virtio'/>
    <rng model='virtio'>
      <backend model='random'>/dev/urandom</backend>
    </rng>
  </devices>
</domain>
"""

# La même VM, prête, telle que libvirt la réécrit après « define » : il
# omet les champs « -1 » du filtre et met le vendeur en majuscules.
DOMAINE_PRET = DOMAINE_VNC.replace(
    "    <graphics type='vnc'",
    "    <graphics type='spice' autoport='yes' listen='127.0.0.1'>\n"
    "      <listen type='address' address='127.0.0.1'/>\n"
    "    </graphics>\n"
    "    <graphics type='vnc'",
).replace(
    "    <memballoon",
    "    <redirdev bus='usb' type='spicevmc'>\n"
    "    </redirdev>\n"
    "    <redirdev bus='usb' type='spicevmc'>\n"
    "    </redirdev>\n"
    "    <redirfilter>\n"
    "      <usbdev vendor='0x0FD9' allow='yes'/>\n"
    "      <usbdev allow='no'/>\n"
    "    </redirfilter>\n"
    "    <channel type='spicevmc'>\n"
    "      <target type='virtio' name='com.redhat.spice.0'/>\n"
    "    </channel>\n"
    "    <memballoon",
)


def _avec_hostdevs(*hostdevs):
    return DOMAINE_VNC.replace(
        "    <memballoon", "".join(hostdevs) + "    <memballoon"
    )


HD_CONFIG = (
    "    <hostdev mode='subsystem' type='usb' managed='yes'>\n"
    "      <source startupPolicy='optional'>\n"
    "        <vendor id='0x0fd9'/>\n"
    "        <product id='0x0080'/>\n"
    "      </source>\n"
    "    </hostdev>\n"
)
HD_LIVE = (
    "    <hostdev mode='subsystem' type='usb' managed='yes'>\n"
    "      <source startupPolicy='optional'>\n"
    "        <vendor id='0x0fd9'/>\n"
    "        <product id='0x0080'/>\n"
    "        <address bus='3' device='5'/>\n"
    "      </source>\n"
    "      <alias name='hostdev0'/>\n"
    "      <address type='usb' bus='0' port='2'/>\n"
    "    </hostdev>\n"
)
HD_MANQUANT = (
    "    <hostdev mode='subsystem' type='usb' managed='yes'>\n"
    "      <source startupPolicy='optional' missing='yes'>\n"
    "        <vendor id='0x0fd9'/>\n"
    "        <product id='0x0080'/>\n"
    "      </source>\n"
    "    </hostdev>\n"
)


def _hd_addr(bus, dev, pid="0080"):
    return (
        "    <hostdev mode='subsystem' type='usb' managed='yes'>\n"
        "      <source>\n"
        "        <vendor id='0x0fd9'/>\n"
        f"        <product id='0x{pid}'/>\n"
        f"        <address bus='{bus}' device='{dev}'/>\n"
        "      </source>\n"
        "    </hostdev>\n"
    )


# Périphériques du sysfs jetable. Les noms de série sont inventés.
APPAREILS = {
    # Racine du bus 1 : écartée par son nom.
    "usb1": {
        "idVendor": "1d6b",
        "idProduct": "0002",
        "busnum": "1",
        "devnum": "1",
        "bDeviceClass": "09",
    },
    # Racine qui porterait un nom de périphérique : écartée par son vendeur.
    "4-1": {
        "idVendor": "1d6b",
        "idProduct": "0003",
        "busnum": "4",
        "devnum": "2",
    },
    # Interface : écartée par son nom.
    "1-2:1.0": {"idVendor": "0fd9", "idProduct": "0080"},
    # Concentrateur : écarté par sa classe.
    "1-1": {
        "idVendor": "05e3",
        "idProduct": "0608",
        "busnum": "1",
        "devnum": "2",
        "bDeviceClass": "09",
        "product": "USB2.0 Hub",
    },
    # Clavier.
    "1-2": {
        "idVendor": "046d",
        "idProduct": "c31c",
        "busnum": "1",
        "devnum": "3",
        "bDeviceClass": "00",
        "manufacturer": "Logitech",
        "product": "USB Keyboard",
    },
    "3-2": {
        "idVendor": "0fd9",
        "idProduct": "0080",
        "busnum": "3",
        "devnum": "5",
        "bDeviceClass": "00",
        "manufacturer": "Elgato",
        "product": "Stream Deck MK.2",
        "serial": "SERIE-MK2",
    },
    "3-4": {
        "idVendor": "0fd9",
        "idProduct": "006c",
        "busnum": "3",
        "devnum": "2",
        "bDeviceClass": "00",
        "product": "Stream Deck XL",
    },
    # Deux decks identiques, départagés par leur série.
    "1-3.1": {
        "idVendor": "0fd9",
        "idProduct": "0084",
        "busnum": "1",
        "devnum": "8",
        "bDeviceClass": "00",
        "serial": "SERIE-B2",
    },
    "1-3.2": {
        "idVendor": "0fd9",
        "idProduct": "0084",
        "busnum": "1",
        "devnum": "7",
        "bDeviceClass": "00",
        "serial": "SERIE-A1",
    },
}


class _Sysfs(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.sysfs = self._dir.name
        for nom, fichiers in APPAREILS.items():
            dossier = Path(self.sysfs, "bus/usb/devices", nom)
            dossier.mkdir(parents=True)
            for fichier, valeur in fichiers.items():
                (dossier / fichier).write_text(valeur + "\n")
        self.devs = u.host_usb_devices(self.sysfs)


class LeBalayageDeLHote(_Sysfs):
    def test_decks_first_then_bus_and_device(self):
        self.assertEqual(
            ["1-3.2", "1-3.1", "3-4", "3-2", "1-2"],
            [d["sysname"] for d in self.devs],
        )

    def test_device_fields(self):
        mk2 = next(d for d in self.devs if d["sysname"] == "3-2")
        self.assertEqual(
            {
                "sysname": "3-2",
                "busnum": 3,
                "devnum": 5,
                "vid": "0fd9",
                "pid": "0080",
                "product": "Stream Deck MK.2",
                "manufacturer": "Elgato",
                "serial": "SERIE-MK2",
                "device_class": "00",
                "is_deck": True,
            },
            mk2,
        )
        clavier = next(d for d in self.devs if d["sysname"] == "1-2")
        self.assertFalse(clavier["is_deck"])

    def test_invalid_sysnames_are_refused(self):
        for nom in ("usb1", "1-2:1.0", "../../etc", "1-2/..", "", None):
            self.assertIsNone(u.read_usb_device(nom, self.sysfs), nom)
        self.assertIsNone(u.read_usb_device("9-9", self.sysfs))
        self.assertEqual("0080", u.read_usb_device("3-2", self.sysfs)["pid"])

    def test_labels(self):
        mk2 = next(d for d in self.devs if d["sysname"] == "3-2")
        self.assertEqual("Elgato Stream Deck MK.2", u.device_label(mk2))
        self.assertEqual(
            "003.005  0fd9:0080  Elgato Stream Deck MK.2  [SERIE-MK2]",
            u.device_line(mk2),
        )
        nu = next(d for d in self.devs if d["sysname"] == "1-3.2")
        self.assertEqual("0fd9:0084", u.device_label(nu))
        self.assertEqual(
            "Elgato Stream Deck",
            u.device_label(
                {"manufacturer": "Elgato", "product": "Elgato Stream Deck"}
            ),
        )


class LaSelection(_Sysfs):
    def test_parse_selector(self):
        self.assertEqual(
            {"vid": "0fd9", "pid": "0080"}, u.parse_selector("0FD9:0080")
        )
        self.assertEqual(
            {"vid": "0fd9", "pid": "0080"}, u.parse_selector("0x0fd9:0x0080")
        )
        self.assertEqual({"bus": 3, "dev": 5}, u.parse_selector("003.005"))
        self.assertEqual({"bus": 3, "dev": 5}, u.parse_selector(" 3.5 "))
        for texte in ("3-5", "fd9:80", "0fd9", "", None, "a.b"):
            self.assertIsNone(u.parse_selector(texte), texte)

    def test_select_and_find(self):
        self.assertEqual(
            ["3-2"], [d["sysname"] for d in u.select_devices(self.devs, "3.5")]
        )
        self.assertEqual(
            ["1-3.2", "1-3.1"],
            [d["sysname"] for d in u.select_devices(self.devs, "0fd9:0084")],
        )
        self.assertEqual([], u.select_devices(self.devs, "nimporte"))
        self.assertEqual(
            ["1-3.1"],
            [
                d["sysname"]
                for d in u.find_devices(
                    self.devs, "0fd9", "0084", serial="SERIE-B2"
                )
            ],
        )

    def test_identical_decks_are_pinned(self):
        self.assertTrue(u.ambiguous(self.devs, "0fd9", "0084"))
        self.assertFalse(u.ambiguous(self.devs, "0fd9", "0080"))
        a1 = next(d for d in self.devs if d["serial"] == "SERIE-A1")
        self.assertEqual(
            {"vid": "0fd9", "pid": "0084", "bus": 1, "dev": 7},
            u.want_for(a1, self.devs),
        )
        mk2 = next(d for d in self.devs if d["sysname"] == "3-2")
        self.assertEqual(
            {"vid": "0fd9", "pid": "0080", "bus": None, "dev": None},
            u.want_for(mk2, self.devs),
        )


def _valide(test, xml_domaine):
    """Contrôle `xml_domaine` contre le schéma domain de libvirt."""
    if not VALIDATE:
        test.skipTest("virt-xml-validate absent")
    with tempfile.NamedTemporaryFile("w", suffix=".xml") as fh:
        fh.write(xml_domaine)
        fh.flush()
        res = subprocess.run(
            [VALIDATE, fh.name, "domain"], capture_output=True, text=True
        )
    test.assertEqual(0, res.returncode, res.stderr + res.stdout)


class LeHostdev(unittest.TestCase):
    def test_vendor_product_optional(self):
        self.assertEqual(
            "<hostdev mode='subsystem' type='usb' managed='yes'>\n"
            "  <source startupPolicy='optional'>\n"
            "    <vendor id='0x0fd9'/>\n"
            "    <product id='0x0080'/>\n"
            "  </source>\n"
            "</hostdev>\n",
            u.hostdev_xml("0fd9", "0080"),
        )

    def test_pinned_without_policy(self):
        xml = u.hostdev_xml("0FD9", "0x84", bus=1, dev=7, optional=False)
        self.assertIn("<source>", xml)
        self.assertIn("<product id='0x0084'/>", xml)
        self.assertIn("<address bus='1' device='7'/>", xml)

    def test_address_only_and_refusal(self):
        xml = u.hostdev_xml(bus=3, dev=5)
        self.assertNotIn("vendor", xml)
        self.assertIn("<address bus='3' device='5'/>", xml)
        with self.assertRaises(ValueError):
            u.hostdev_xml("0fd9", None)

    def test_schema(self):
        for xml in (
            u.hostdev_xml("0fd9", "0080"),
            u.hostdev_xml("0fd9", "0080", 3, 5, optional=False),
            u.hostdev_xml(bus=3, dev=5),
        ):
            with self.subTest(xml=xml):
                _valide(
                    self,
                    DOMAINE_VNC.replace("</devices>", xml + "</devices>"),
                )


class LEtatUsb(unittest.TestCase):
    def test_vnc_only(self):
        self.assertEqual(
            {
                "hostdevs": [],
                "redirdevs": [],
                "usb_controllers": ["qemu-xhci"],
                "graphics": ["vnc"],
                "spice_channel": False,
                "redirfilter": [],
                "arch": "x86_64",
            },
            u.usb_state(DOMAINE_VNC),
        )

    def test_ready_domain(self):
        etat = u.usb_state(DOMAINE_PRET)
        self.assertEqual(["spice", "vnc"], etat["graphics"])
        self.assertEqual(["spicevmc", "spicevmc"], etat["redirdevs"])
        self.assertTrue(etat["spice_channel"])
        self.assertTrue(u.usbredir_ready(etat))
        self.assertTrue(u.spice_first(etat))
        self.assertEqual(
            [
                {
                    "class": "-1",
                    "vendor": "0fd9",
                    "product": "-1",
                    "version": "-1",
                    "allow": True,
                },
                {
                    "class": "-1",
                    "vendor": "-1",
                    "product": "-1",
                    "version": "-1",
                    "allow": False,
                },
            ],
            etat["redirfilter"],
        )
        self.assertFalse(u.usbredir_ready(u.usb_state(DOMAINE_VNC)))

    def test_hostdevs_read_source_address_only(self):
        etat = u.usb_state(_avec_hostdevs(HD_LIVE, HD_MANQUANT))
        self.assertEqual(
            [
                {
                    "vid": "0fd9",
                    "pid": "0080",
                    "bus": 3,
                    "dev": 5,
                    "startup_policy": "optional",
                    "missing": False,
                },
                {
                    "vid": "0fd9",
                    "pid": "0080",
                    "bus": None,
                    "dev": None,
                    "startup_policy": "optional",
                    "missing": True,
                },
            ],
            etat["hostdevs"],
        )

    def test_empty_or_unreadable(self):
        for xml in ("", None, "<domain"):
            etat = u.usb_state(xml)
            self.assertEqual([], etat["usb_controllers"])
            self.assertFalse(u.has_usb_controller(etat))


class LePlanUsb(unittest.TestCase):
    WANT = {"vid": "0fd9", "pid": "0080", "action": "attach"}

    def plan(
        self,
        live_xml,
        config_xml,
        want=None,
        live=True,
        config=True,
        running=True,
        uri=u.DEFAULT_URI,
    ):
        return u.usb_plan(
            u.usb_state(live_xml) if live_xml is not None else None,
            u.usb_state(config_xml) if config_xml is not None else None,
            want or self.WANT,
            live,
            config,
            running,
            VM,
            uri,
        )

    def test_attach_both_views(self):
        plan = self.plan(DOMAINE_VNC, DOMAINE_VNC)
        self.assertEqual(["live", "config"], [s["view"] for s in plan])
        self.assertEqual(
            [
                "virsh",
                "--connect",
                "qemu:///system",
                "attach-device",
                VM,
                u.XML_PLACEHOLDER,
                "--live",
            ],
            plan[0]["argv"],
        )
        self.assertEqual("--config", plan[1]["argv"][-1])
        self.assertEqual(u.hostdev_xml("0fd9", "0080"), plan[1]["xml"])
        self.assertIn("0fd9:0080", plan[0]["what"])

    def test_attach_is_idempotent_per_view(self):
        plan = self.plan(_avec_hostdevs(HD_LIVE), DOMAINE_VNC)
        self.assertIn("skip", plan[0])
        self.assertIn("argv", plan[1])
        plan = self.plan(_avec_hostdevs(HD_LIVE), _avec_hostdevs(HD_CONFIG))
        self.assertTrue(all("skip" in s for s in plan))

    def test_missing_live_hostdev_is_detached_before_attach(self):
        # Le joker « missing » est un usb-host sans critère dans QEMU : il
        # part avant l'attachement, sinon l'invité voit le deck deux fois.
        plan = self.plan(
            _avec_hostdevs(HD_MANQUANT), DOMAINE_VNC, config=False
        )
        self.assertEqual(
            ["detach-device", "attach-device"], [s["argv"][3] for s in plan]
        )
        self.assertEqual(
            u.hostdev_xml("0fd9", "0080", optional=False), plan[0]["xml"]
        )
        self.assertEqual("--live", plan[0]["argv"][-1])

    def test_missing_live_hostdev_is_detachable(self):
        want = dict(self.WANT, action="detach")
        plan = self.plan(
            _avec_hostdevs(HD_MANQUANT), DOMAINE_VNC, want=want, config=False
        )
        self.assertEqual(["detach-device"], [s["argv"][3] for s in plan])

    def test_missing_only_counts_in_live_view(self):
        # Dans la vue config, missing n'existe pas : rien à détacher avant.
        plan = self.plan(
            None, _avec_hostdevs(HD_MANQUANT), live=False, config=True
        )
        self.assertIn("skip", plan[0])

    def test_not_running_skips_live(self):
        plan = self.plan(None, DOMAINE_VNC, running=False)
        self.assertIn("skip", plan[0])
        self.assertEqual("live", plan[0]["view"])
        self.assertIn("argv", plan[1])

    def test_no_usb_refused(self):
        sans = DOMAINE_VNC.replace(
            "<controller type='usb' index='0' model='qemu-xhci' ports='15'/>",
            "",
        )
        aucun = DOMAINE_VNC.replace(
            "model='qemu-xhci' ports='15'", "model='none'"
        )
        for xml in (sans, aucun):
            plan = self.plan(xml, xml)
            self.assertTrue(all("skip" in s for s in plan), plan)

    def test_pinned_attach_ignores_other_identical_deck(self):
        want = {
            "vid": "0fd9",
            "pid": "0084",
            "bus": 1,
            "dev": 8,
            "action": "attach",
        }
        live = _avec_hostdevs(_hd_addr(1, 7, "0084"))
        plan = self.plan(live, None, want=want, config=False)
        self.assertIn("<address bus='1' device='8'/>", plan[0]["xml"])

    def test_detach_uses_the_view_definition(self):
        want = {**self.WANT, "action": "detach"}
        plan = self.plan(
            _avec_hostdevs(HD_LIVE),
            _avec_hostdevs(HD_CONFIG),
            want=want,
            uri=URI_DISTANT,
        )
        self.assertEqual(
            [
                "virsh",
                "--connect",
                URI_DISTANT,
                "detach-device",
                VM,
                u.XML_PLACEHOLDER,
                "--live",
            ],
            plan[0]["argv"],
        )
        self.assertIn("<address bus='3' device='5'/>", plan[0]["xml"])
        self.assertNotIn("address", plan[1]["xml"])
        self.assertNotIn("startupPolicy", plan[1]["xml"])

    def test_detach_absent_is_skipped(self):
        want = {**self.WANT, "action": "detach"}
        plan = self.plan(DOMAINE_VNC, DOMAINE_VNC, want=want)
        self.assertTrue(all("skip" in s for s in plan))

    def test_bind_xml(self):
        argv = self.plan(DOMAINE_VNC, None, config=False)[0]["argv"]
        lie = u.bind_xml(argv, "/tmp/x.xml")
        self.assertNotIn(u.XML_PLACEHOLDER, lie)
        self.assertEqual("/tmp/x.xml", lie[5])

    def test_virsh_helpers(self):
        self.assertEqual(
            [
                "virsh",
                "--connect",
                URI_DISTANT,
                "dumpxml",
                VM,
                "--inactive",
                "--security-info",
            ],
            u.dumpxml_argv(URI_DISTANT, VM, inactive=True),
        )
        self.assertEqual(
            ["virsh", "--connect", "qemu:///system", "dumpxml", VM],
            u.dumpxml_argv("", VM),
        )
        self.assertEqual(
            ["virsh", "--connect", "qemu:///system", "domstate", VM],
            u.domstate_argv(None, VM),
        )
        self.assertEqual(
            [
                "virsh",
                "--connect",
                "qemu:///system",
                "define",
                u.XML_PLACEHOLDER,
            ],
            u.define_argv(u.DEFAULT_URI),
        )


class LaRedirectionSpice(unittest.TestCase):
    def test_vnc_only_gets_spice_first(self):
        xml, changes = u.spice_usbredir_xml(DOMAINE_VNC)
        etat = u.usb_state(xml)
        self.assertEqual(["spice", "vnc"], etat["graphics"])
        self.assertEqual(["spicevmc", "spicevmc"], etat["redirdevs"])
        self.assertTrue(etat["spice_channel"])
        self.assertEqual([], etat["redirfilter"])
        self.assertEqual(3, len(changes))
        self.assertIn("vnc", changes[0])
        self.assertIn(
            '<graphics type="spice" autoport="yes" listen="127.0.0.1">',
            xml,
        )
        self.assertIn('<listen type="address" address="127.0.0.1" />', xml)
        _valide(self, xml)

    def test_vnc_password_is_carried_to_spice(self):
        protege = DOMAINE_VNC.replace(
            "<graphics type='vnc' port='-1' autoport='yes'",
            "<graphics type='vnc' port='-1' autoport='yes' passwd='essaiXyz'",
        )
        self.assertNotEqual(DOMAINE_VNC, protege)
        xml, _ = u.spice_usbredir_xml(protege)
        racine = ET.fromstring(xml)
        spice = racine.find("./devices/graphics[@type='spice']")
        self.assertEqual("essaiXyz", spice.get("passwd"))
        _valide(self, xml)
        sans, _ = u.spice_usbredir_xml(DOMAINE_VNC)
        spice = ET.fromstring(sans).find("./devices/graphics[@type='spice']")
        self.assertIsNone(spice.get("passwd"))

    def test_idempotent(self):
        xml, _ = u.spice_usbredir_xml(DOMAINE_VNC, allow_vendors=("0fd9",))
        encore, changes = u.spice_usbredir_xml(xml, allow_vendors=("0fd9",))
        self.assertEqual([], changes)
        self.assertEqual(xml, encore)
        self.assertEqual(
            (DOMAINE_PRET, []),
            u.spice_usbredir_xml(DOMAINE_PRET, allow_vendors=["0x0FD9"]),
        )
        self.assertEqual([], u.spice_usbredir_plan(DOMAINE_PRET, VM))

    def test_namespaces_kept(self):
        xml, _ = u.spice_usbredir_xml(DOMAINE_VNC)
        self.assertIn("<libosinfo:os ", xml)
        self.assertNotIn("ns0", xml)

    def test_spice_after_vnc_is_moved_first(self):
        apres = DOMAINE_PRET.replace(
            "    <graphics type='spice' autoport='yes' listen='127.0.0.1'>\n"
            "      <listen type='address' address='127.0.0.1'/>\n"
            "    </graphics>\n",
            "",
        ).replace(
            "  </devices>",
            "    <graphics type='spice' autoport='yes'/>\n  </devices>",
        )
        self.assertEqual(["vnc", "spice"], u.usb_state(apres)["graphics"])
        xml, changes = u.spice_usbredir_xml(apres)
        self.assertEqual(["spice", "vnc"], u.usb_state(xml)["graphics"])
        self.assertEqual(1, len(changes))
        self.assertTrue(xml.rstrip().endswith("  </devices>\n</domain>"))
        _valide(self, xml)

    def test_usb_controller_added_or_enabled(self):
        sans = DOMAINE_VNC.replace(
            "<controller type='usb' index='0' model='qemu-xhci' ports='15'/>",
            "",
        )
        xml, _ = u.spice_usbredir_xml(sans)
        self.assertEqual(["qemu-xhci"], u.usb_state(xml)["usb_controllers"])
        _valide(self, xml)
        aucun = DOMAINE_VNC.replace(
            "model='qemu-xhci' ports='15'", "model='none'"
        )
        xml, changes = u.spice_usbredir_xml(aucun)
        self.assertEqual(["qemu-xhci"], u.usb_state(xml)["usb_controllers"])
        self.assertTrue(any("none" in c for c in changes))

    def test_filter_set_and_removed(self):
        xml, _ = u.spice_usbredir_xml(DOMAINE_VNC, allow_vendors=("0fd9",))
        self.assertEqual(2, len(u.usb_state(xml)["redirfilter"]))
        _valide(self, xml)
        retire, changes = u.spice_usbredir_xml(xml, allow_vendors=())
        self.assertEqual([], u.usb_state(retire)["redirfilter"])
        self.assertEqual(1, len(changes))
        garde, changes = u.spice_usbredir_xml(xml)
        self.assertEqual([], changes)

    def test_redir_slots_topped_up(self):
        xml, changes = u.spice_usbredir_xml(DOMAINE_PRET, redir_slots=4)
        self.assertEqual(4, len(u.usb_state(xml)["redirdevs"]))
        self.assertIn("2", changes[0])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            u.spice_usbredir_xml(DOMAINE_VNC.replace("x86_64", "s390x"))
        with self.assertRaises(ValueError):
            u.spice_usbredir_xml("<domain")

    def test_plan_defines(self):
        plan = u.spice_usbredir_plan(DOMAINE_VNC, VM, URI_DISTANT)
        self.assertEqual(1, len(plan))
        self.assertEqual(
            ["virsh", "--connect", URI_DISTANT, "define", u.XML_PLACEHOLDER],
            plan[0]["argv"],
        )
        self.assertEqual("config", plan[0]["view"])
        self.assertEqual(3, len(plan[0]["changes"]))


class VirtViewer(unittest.TestCase):
    def test_without_usbredir_exact(self):
        self.assertEqual(
            ["virt-viewer", "-c", "qemu:///system", "vm-a"],
            u.virt_viewer_argv("qemu:///system", "vm-a"),
        )

    def test_with_usbredir(self):
        filtre = "-1,0x0fd9,-1,-1,1|-1,-1,-1,-1,0"
        self.assertEqual(filtre, u.usbredir_filter())
        self.assertEqual(
            [
                "virt-viewer",
                "-c",
                URI_DISTANT,
                f"--spice-usbredir-auto-redirect-filter={filtre}",
                f"--spice-usbredir-redirect-on-connect={filtre}",
                "vm-a",
            ],
            u.virt_viewer_argv(URI_DISTANT, "vm-a", usbredir=True),
        )
        self.assertEqual(
            ["virt-viewer", "-c", URI_DISTANT, "vm-a"],
            u.virt_viewer_argv(URI_DISTANT, "vm-a", True, auto_vendors=()),
        )
        self.assertEqual(
            "-1,0x0fd9,-1,-1,1|-1,0x046d,-1,-1,1|-1,-1,-1,-1,0",
            u.usbredir_filter(["0fd9", "46d"]),
        )


class LaCorrespondance(unittest.TestCase):
    ENTREES = [
        {"vid": "0fd9", "pid": "0084", "domain": "vm-b", "serial": "SERIE-B2"},
        {"vid": "0FD9", "pid": "0x0084", "domain": "vm-a"},
        {
            "vid": "0fd9",
            "pid": "0080",
            "domain": "vm-c",
            "uri": "qemu:///system",
        },
    ]

    def test_roundtrip(self):
        texte = u.mapping_dumps(self.ENTREES)
        self.assertTrue(texte.endswith("\n"))
        self.assertEqual(
            {"vid": "0fd9", "pid": "0084", "domain": "vm-a"},
            json.loads(texte)["entries"][1],
        )
        self.assertEqual(json.loads(texte)["entries"], u.mapping_loads(texte))
        self.assertEqual(
            u.mapping_loads(texte),
            u.mapping_loads(json.dumps(self.ENTREES)),
        )

    def test_loads_tolerance(self):
        self.assertEqual([], u.mapping_loads(""))
        self.assertEqual(
            [],
            u.mapping_loads(
                '{"entries": [{"vid": "zz", "pid": "0080", '
                '"domain": "x"}, {"vid": "0fd9"}, 3]}'
            ),
        )
        with self.assertRaises(ValueError):
            u.mapping_loads("{pas du json")

    def test_set_and_remove(self):
        entrees = u.mapping_set(
            self.ENTREES, {"vid": "0fd9", "pid": "0084", "domain": "vm-d"}
        )
        self.assertEqual(3, len(entrees))
        self.assertEqual("vm-d", entrees[-1]["domain"])
        with self.assertRaises(ValueError):
            u.mapping_set(entrees, {"vid": "0fd9"})
        self.assertEqual(
            ["vm-c"],
            [e["domain"] for e in u.mapping_remove(entrees, "0fd9", "0084")],
        )
        self.assertEqual(
            ["vm-a", "vm-c"],
            [
                e["domain"]
                for e in u.mapping_remove(
                    self.ENTREES, "0fd9", "0084", serial="SERIE-B2"
                )
            ],
        )

    def test_remove_empty_serial_keeps_the_serial_entries(self):
        """serial="" ne retire que l'entrée sans série du modèle ; None,
        toutes."""
        entrees = [
            {"vid": "0fd9", "pid": "0080", "domain": "vm-a"},
            {
                "vid": "0fd9",
                "pid": "0080",
                "domain": "vm-a",
                "serial": "FAKE0001",
            },
        ]
        reste = u.mapping_remove(entrees, "0fd9", "0080", "", "vm-a")
        self.assertEqual(["FAKE0001"], [e.get("serial") for e in reste])
        self.assertEqual(
            [], u.mapping_remove(entrees, "0fd9", "0080", None, "vm-a")
        )

    def test_serial_wins(self):
        b2 = {"vid": "0fd9", "pid": "0084", "serial": "SERIE-B2"}
        a1 = {"vid": "0fd9", "pid": "0084", "serial": "SERIE-A1"}
        self.assertEqual("vm-b", u.mapping_match(self.ENTREES, b2)["domain"])
        self.assertEqual("vm-a", u.mapping_match(self.ENTREES, a1)["domain"])
        self.assertIsNone(
            u.mapping_match(self.ENTREES, {"vid": "046d", "pid": "c31c"})
        )


class LeRattachement(unittest.TestCase):
    DEV = {
        "sysname": "1-3.1",
        "busnum": 1,
        "devnum": 9,
        "vid": "0fd9",
        "pid": "0084",
        "serial": "SERIE-B2",
    }
    ENTREE = {"vid": "0fd9", "pid": "0084", "domain": VM}

    def test_not_running(self):
        plan = u.reattach_plan(self.DEV, self.ENTREE, False, None)
        self.assertEqual(1, len(plan))
        self.assertIn("skip", plan[0])

    def test_already_there(self):
        live = u.usb_state(_avec_hostdevs(_hd_addr(1, 9, "0084")))
        plan = u.reattach_plan(self.DEV, self.ENTREE, True, live, [self.DEV])
        self.assertEqual(1, len(plan))
        self.assertIn("skip", plan[0])

    def test_stale_detached_then_pinned_attach(self):
        live = u.usb_state(_avec_hostdevs(_hd_addr(1, 4, "0084")))
        entree = {**self.ENTREE, "uri": URI_DISTANT}
        plan = u.reattach_plan(self.DEV, entree, True, live, [self.DEV])
        self.assertEqual(
            ["detach-device", "attach-device"], [s["argv"][3] for s in plan]
        )
        self.assertTrue(all(s["argv"][-1] == "--live" for s in plan))
        self.assertTrue(all(s["argv"][2] == URI_DISTANT for s in plan))
        self.assertIn("<address bus='1' device='4'/>", plan[0]["xml"])
        self.assertIn("<address bus='1' device='9'/>", plan[1]["xml"])
        self.assertNotIn("startupPolicy", plan[1]["xml"])

    def test_other_plugged_identical_deck_is_kept(self):
        autre = {
            **self.DEV,
            "sysname": "1-3.2",
            "devnum": 4,
            "serial": "SERIE-A1",
        }
        live = u.usb_state(_avec_hostdevs(_hd_addr(1, 4, "0084")))
        plan = u.reattach_plan(
            self.DEV, self.ENTREE, True, live, [self.DEV, autre]
        )
        self.assertEqual(["attach-device"], [s["argv"][3] for s in plan])

    def test_missing_placeholder_detached_then_pinned_attach(self):
        manquant = HD_MANQUANT.replace("0x0080", "0x0084")
        live = u.usb_state(_avec_hostdevs(manquant))
        plan = u.reattach_plan(self.DEV, self.ENTREE, True, live, [self.DEV])
        self.assertEqual(
            ["detach-device", "attach-device"], [s["argv"][3] for s in plan]
        )
        self.assertNotIn("<address", plan[0]["xml"])
        self.assertIn("<address", plan[1]["xml"])


class LesTextesSysteme(unittest.TestCase):
    def test_udev_rule(self):
        texte = u.udev_rule_text(["0FD9", "0fd9", "046d"])
        regles = [l for l in texte.splitlines() if not l.startswith("#")]
        self.assertEqual(
            [
                'ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", '
                'ATTR{idVendor}=="046d", TAG+="systemd", '
                'ENV{SYSTEMD_WANTS}+="erplibre-usb-reattach@%k.service"',
                'ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", '
                'ATTR{idVendor}=="0fd9", TAG+="systemd", '
                'ENV{SYSTEMD_WANTS}+="erplibre-usb-reattach@%k.service"',
            ],
            regles,
        )
        with self.assertRaises(ValueError):
            u.udev_rule_text([])
        self.assertTrue(
            u.UDEV_RULE_PATH.endswith("/85-erplibre-usb-passthrough.rules")
        )
        # Après la règle du deck, pour que les deux s'appliquent.
        self.assertGreater(u.UDEV_RULE_NAME, "70-streamdeck.rules")

    def test_unit(self):
        texte = u.unit_text()
        self.assertIn("Type=oneshot\n", texte)
        self.assertIn("After=libvirtd.service virtqemud.service\n", texte)
        self.assertIn(
            "ExecStart=/usr/bin/python3 -I -B "
            "/usr/local/libexec/erplibre-usb/usb_qemu.py reattach "
            "--sysname %i\n",
            texte,
        )
        self.assertNotIn("%I", texte)
        for mauvais in ("relatif/usb_qemu.py", "/chemin avec espace.py"):
            with self.assertRaises(ValueError):
                u.unit_text(mauvais)

    def test_locations(self):
        self.assertEqual("/etc/erplibre/usb-passthrough.json", u.MAPPING)
        self.assertEqual(
            "/etc/systemd/system/erplibre-usb-reattach@.service", u.UNIT_PATH
        )
        self.assertTrue(u.LIBEXEC_CLI.startswith(u.LIBEXEC_DIR))
        self.assertTrue(u.LIBEXEC_LIB.startswith(u.LIBEXEC_DIR))


class HorsDuDepot(unittest.TestCase):
    def test_loads_by_path_in_isolated_python(self):
        with tempfile.TemporaryDirectory() as libexec:
            copie = os.path.join(libexec, "qemu_usb.py")
            shutil.copy(MODULE, copie)
            code = (
                "import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location("
                "'qemu_usb', sys.argv[1])\n"
                "m = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(m)\n"
                "print(m.DECK_VENDOR, m.t('the VM is not running'))\n"
            )
            res = subprocess.run(
                [sys.executable, "-I", "-c", code, copie],
                capture_output=True,
                text=True,
                cwd=libexec,
            )
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("0fd9 the VM is not running\n", res.stdout)

    def test_module_loads_spec(self):
        spec = importlib.util.spec_from_file_location("qemu_usb_x", MODULE)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual("0fd9", m.DECK_VENDOR)


if __name__ == "__main__":
    unittest.main()
