#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'état et le diagnostic d'ERPLibre Home, sur des sorties enregistrées.

collect() tourne sur un poste simulé : un HOME, un dépôt, un sysfs et un
verrou jetables, et une fonction `run` qui rend la sortie enregistrée de
chaque commande et note celles qu'on lui demande. status_lines() et
diagnosis_lines() se jouent sur des faits écrits à la main.

Ce que ces tests gardent :

- chaque sonde de la spec a sa ligne d'état ;
- chaque sonde qui n'est pas comme attendu a sa correction, et une
  installation saine n'en a aucune ;
- sans unité installée, systemctl n'est pas appelé ;
- chaque libellé a ses deux langues ;
- un PID que le verrou nomme, mais qui ne désigne plus son auteur (parti,
  ou repris par un autre processus), n'est jamais proposé à « kill » ;
- sans le clone du programme du deck, qui porte deck_lock.py, collect()
  rend un verrou libre et deck_program faux, l'état le dit à la place du
  verrou, et le diagnostic renvoie à l'installation Stream Deck ;
- un deck passé à une VM se reconnaît sans root, par le propriétaire de
  son nœud et les <hostdev> live que virsh rend en lecture seule ; l'état
  nomme la VM, et le diagnostic ne compte pas comme une panne le service
  de l'hôte qui n'a plus de deck à piloter. Un deck que le programme de
  l'hôte tient par usbfs, son nœud resté à root, reste à l'hôte.

La lecture du verrou par le vrai deck_lock.py du clone est sautée
(SANS_DECK) quand il manque.
"""

import fcntl
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from streamdeck_deck import PRESENT as DECK_PRESENT  # noqa: E402
from streamdeck_deck import SANS_DECK  # noqa: E402

from script.todo import erplibre_home_status as statut  # noqa: E402
from script.todo import qemu_usb, todo_i18n  # noqa: E402

UNITE = "erplibre-home-streamdeck.service"
INFO_ACTIVE = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'name': <'ERPLibre Home'>,"
    " 'state': <1.0>, 'error': <''>},)"
)
INFO_ERREUR = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'state': <3.0>,"
    " 'error': <\"TypeError: can't read exemple\">},)"
)
INFO_INCONNUE = "(@a{sv} {},)"
JOURNAL_SAIN = "autre ligne\n[ERPLibreHome] enabled\n"
# L'UID de l'utilisateur de QEMU sur un hôte simulé ; inventé.
UID_QEMU = 64055
UID_MOI = 1234
DOMAINE_XML = (
    "<domain type='kvm'><name>vm-essai</name><devices>"
    "<hostdev mode='subsystem' type='usb' managed='yes'><source>"
    "<vendor id='0x0fd9'/><product id='0x0080'/>"
    "<address bus='3' device='5'/></source></hostdev>"
    "<hostdev mode='subsystem' type='usb' managed='yes'>"
    "<source startupPolicy='optional' missing='yes'>"
    "<vendor id='0x0fd9'/><product id='0x006c'/>"
    "<address bus='3' device='9'/></source></hostdev>"
    "</devices></domain>"
)
JOURNAL_ECHEC = (
    "[ERPLibreHome] mount device failed: exemple\n"
    "[ERPLibreHome] mount pencil failed: exemple\n"
    "[ERPLibreHome] mount device failed: exemple\n"
    "[ERPLibreHome] enabled\n"
)


def faits(**changes):
    """Les faits d'un poste sain au niveau Stream Deck, modifiés par
    `changes`."""
    base = {
        "extension_linked": True,
        "venv": True,
        "udev_rule": True,
        "extension": {"state": 1.0, "error": ""},
        "journal": {"read": True, "failed": [], "visible": True},
        "unit_file": True,
        "unit_enabled": "enabled",
        "unit_active": "active",
        "settings": {
            "DECK_PROGRAM": "tiler",
            "DECK_PLUGINS_OFF": "",
            "DECK_SESSION_REFRESH_SEC": "1",
        },
        "plugin_ids": ["sound", "tiling"],
        "deck_program": True,
        "lock": ("4242", "tiler"),
        "lock_running": True,
        "lock_pids": [4242],
        "decks": [deck()],
    }
    base.update(changes)
    return base


def deck(**changes):
    """Un deck MK.2 branché que usbhid tient, modifié par `changes`."""
    base = {
        "product": "Stream Deck MK.2",
        "id_product": "0080",
        "model": "Stream Deck MK.2",
        "serial": "SERIE-ESSAI-1",
        "sysname": "3-2",
        "busnum": 3,
        "devnum": 5,
        "driver": "usbhid",
        "owner_uid": 0,
        "vm": None,
    }
    base.update(changes)
    return base


def ecrire_sysfs(sysfs, appareils):
    """Pose sous `sysfs` les périphériques {sysname: {fichier: valeur}} ;
    la clé "driver" d'un périphérique devient le lien du pilote de son
    interface « :1.0 »."""
    for nom, fichiers in appareils.items():
        dossier = Path(sysfs, "bus/usb/devices", nom)
        dossier.mkdir(parents=True)
        for fichier, valeur in fichiers.items():
            if fichier == "driver":
                interface = Path(sysfs, "bus/usb/devices", nom + ":1.0")
                interface.mkdir()
                pilote = Path(sysfs, "bus/usb/drivers", valeur)
                pilote.mkdir(parents=True, exist_ok=True)
                (interface / "driver").symlink_to(pilote)
            else:
                (dossier / fichier).write_text(valeur + "\n")


class LesLectures(unittest.TestCase):
    def test_extension_info(self):
        self.assertEqual(
            {"state": 1.0, "error": ""},
            statut.parse_extension_info(INFO_ACTIVE),
        )
        self.assertEqual(
            {"state": 3.0, "error": "TypeError: can't read exemple"},
            statut.parse_extension_info(INFO_ERREUR),
        )
        for sortie in (INFO_INCONNUE, "", None):
            with self.subTest(sortie=sortie):
                self.assertIsNone(statut.parse_extension_info(sortie)["state"])

    def test_journal(self):
        self.assertEqual(
            {"read": True, "failed": [], "visible": True},
            statut.parse_journal(JOURNAL_SAIN),
        )
        self.assertEqual(
            {"read": True, "failed": ["device", "pencil"], "visible": True},
            statut.parse_journal(JOURNAL_ECHEC),
        )
        self.assertEqual(
            {"read": False, "failed": [], "visible": False},
            statut.parse_journal(""),
        )

    def test_plugged_decks_read_sysfs(self):
        with tempfile.TemporaryDirectory() as sysfs:
            ecrire_sysfs(
                sysfs,
                {
                    "1-1": {"idVendor": "1d6b", "idProduct": "0002"},
                    "3-2": {
                        "idVendor": "0fd9",
                        "idProduct": "0080",
                        "product": "Stream Deck MK.2",
                        "serial": "SERIE-ESSAI-1",
                        "busnum": "3",
                        "devnum": "5",
                        "driver": "usbfs",
                    },
                    "3-4": {"idVendor": "0fd9", "idProduct": "006c"},
                },
            )
            noeuds = []

            def proprietaire(chemin):
                noeuds.append(chemin)
                return UID_QEMU

            self.assertEqual(
                [
                    deck(driver="usbfs", owner_uid=UID_QEMU),
                    {
                        "product": "",
                        "id_product": "006c",
                        "model": "Stream Deck XL",
                        "serial": "",
                        "sysname": "3-4",
                        "busnum": None,
                        "devnum": None,
                        "driver": "",
                        "owner_uid": None,
                        "vm": None,
                    },
                ],
                statut.plugged_decks(sysfs, "/devfs-essai", proprietaire),
            )
            self.assertEqual(["/devfs-essai/bus/usb/003/005"], noeuds)


class LaVmQuiTientLeDeck(unittest.TestCase):
    """deck_vm et ses deux sources : les <hostdev> live de libvirt et la
    correspondance du rattachement automatique."""

    ENTREES = [{"vid": "0fd9", "pid": "0080", "domain": "vm-correspondance"}]

    def vm(self, holders=None, entries=(), **changes):
        return statut.deck_vm(deck(**changes), holders, entries, UID_MOI)

    def test_libvirt_names_the_domain_holding_the_address(self):
        self.assertEqual(
            "vm-essai",
            self.vm({(3, 5): "vm-essai"}, driver="", owner_uid=UID_QEMU),
        )

    def test_a_deck_usbhid_holds_stays_on_the_host(self):
        self.assertIsNone(self.vm({(3, 6): "vm-essai"}, self.ENTREES))

    def test_the_host_deck_program_is_not_a_vm(self):
        """Le programme du deck de l'hôte passe par usbfs, mais le nœud
        reste à root, ou à l'utilisateur : ce n'est pas une VM, même
        quand la correspondance attribue le deck à une VM."""
        for proprio in (0, UID_MOI, None):
            with self.subTest(proprio=proprio):
                self.assertIsNone(
                    self.vm(
                        None, self.ENTREES, driver="usbfs", owner_uid=proprio
                    )
                )

    def test_a_node_owned_by_qemu_takes_the_mapping_name(self):
        for pilote in ("usbfs", ""):
            with self.subTest(pilote=pilote):
                self.assertEqual(
                    "vm-correspondance",
                    self.vm(
                        None, self.ENTREES, driver=pilote, owner_uid=UID_QEMU
                    ),
                )
        self.assertEqual(
            "", self.vm({}, [], driver="usbfs", owner_uid=UID_QEMU)
        )

    def test_libvirt_holders_skip_missing_hostdevs(self):
        appels = []

        def run(argv):
            appels.append(tuple(argv))
            if tuple(argv) == statut.CMD_DOMAINS:
                return 0, "vm-essai\n\n"
            if tuple(argv) == statut.cmd_virsh("dumpxml", "vm-essai"):
                return 0, DOMAINE_XML
            return 1, ""

        self.assertEqual({(3, 5): "vm-essai"}, statut.libvirt_usb_holders(run))
        self.assertTrue(
            all(a[:3] == ("timeout", "5", "virsh") for a in appels)
        )
        self.assertTrue(all("--readonly" in a for a in appels))
        self.assertIsNone(statut.libvirt_usb_holders(lambda argv: (None, "")))

    def test_an_unreadable_mapping_is_empty(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "usb-passthrough.json")
            self.assertEqual([], statut.read_mapping(str(chemin)))
            chemin.write_text("{pas du json")
            self.assertEqual([], statut.read_mapping(str(chemin)))
            chemin.write_text(qemu_usb.mapping_dumps(self.ENTREES))
            self.assertEqual(self.ENTREES, statut.read_mapping(str(chemin)))


class LaCollecte(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.appels = []

    def run_enregistre(self, sorties):
        def run(argv):
            self.appels.append(tuple(argv))
            return sorties.get(tuple(argv), (1, ""))

        return run

    def collecter(self, sorties, unite=False, racine=RACINE, proprio=0):
        if unite:
            fichier = self.home / ".config/systemd/user" / UNITE
            fichier.parent.mkdir(parents=True)
            fichier.write_text("[Unit]\n")
        return statut.collect(
            self.run_enregistre(sorties),
            str(racine),
            environ={"HOME": str(self.home)},
            sysfs=str(self.tmp / "sys"),
            udev_rule=str(self.tmp / "absente.rules"),
            lock_path=str(self.tmp / "deck.lock"),
            devfs=str(self.tmp / "dev"),
            owner_of=lambda chemin: proprio,
            mapping_path=str(self.tmp / "absente.json"),
            uid=UID_MOI,
        )

    def brancher_mk2(self, pilote):
        ecrire_sysfs(
            self.tmp / "sys",
            {
                "3-2": {
                    "idVendor": "0fd9",
                    "idProduct": "0080",
                    "product": "Stream Deck MK.2",
                    "busnum": "3",
                    "devnum": "5",
                    "driver": pilote,
                }
            },
        )

    def test_a_deck_in_a_vm_is_named_from_libvirt(self):
        self.brancher_mk2("usbfs")
        sorties = {
            statut.CMD_DOMAINS: (0, "vm-essai\n"),
            statut.cmd_virsh("dumpxml", "vm-essai"): (0, DOMAINE_XML),
        }
        recu = self.collecter(sorties, proprio=UID_QEMU)
        self.assertEqual(["vm-essai"], [d["vm"] for d in recu["decks"]])

    def test_virsh_is_not_called_for_a_deck_on_usbhid(self):
        self.brancher_mk2("usbhid")
        recu = self.collecter({})
        self.assertEqual([None], [d["vm"] for d in recu["decks"]])
        self.assertNotIn("timeout", [a[0] for a in self.appels])

    def test_a_bare_workstation(self):
        recu = self.collecter({})
        self.assertEqual(
            {
                "extension_linked": False,
                "venv": os.access(
                    RACINE / ".venv.streamdeck/bin/python", os.X_OK
                ),
                "udev_rule": False,
                "extension": {"state": None, "error": ""},
                "journal": {"read": False, "failed": [], "visible": False},
                "unit_file": False,
                "unit_enabled": "",
                "unit_active": "",
                "settings": {
                    "DECK_PROGRAM": "tiler",
                    "DECK_PLUGINS_OFF": "",
                    "DECK_SESSION_REFRESH_SEC": "1",
                },
                "plugin_ids": statut.service.deck_plugin_ids(
                    str(RACINE), {"HOME": str(self.home)}
                ),
                "deck_program": DECK_PRESENT,
                "lock": None,
                "lock_running": False,
                "lock_pids": [],
                "decks": [],
            },
            recu,
        )
        self.assertNotIn("systemctl", [a[0] for a in self.appels])

    def test_recorded_outputs_reach_the_facts(self):
        lien = self.home / ".local/share/gnome-shell/extensions"
        lien.mkdir(parents=True)
        (lien / "erplibre-home@technolibre.ca").symlink_to(self.tmp)
        sorties = {
            statut.CMD_EXTENSION_INFO: (0, INFO_ACTIVE),
            statut.CMD_JOURNAL: (0, JOURNAL_ECHEC),
            ("systemctl", "--user", "is-enabled", UNITE): (1, "disabled\n"),
            ("systemctl", "--user", "is-active", UNITE): (3, "inactive\n"),
        }
        recu = self.collecter(sorties, unite=True)
        self.assertTrue(recu["extension_linked"])
        self.assertEqual({"state": 1.0, "error": ""}, recu["extension"])
        self.assertEqual(["device", "pencil"], recu["journal"]["failed"])
        self.assertTrue(recu["unit_file"])
        self.assertEqual("disabled", recu["unit_enabled"])
        self.assertEqual("inactive", recu["unit_active"])

    def test_without_the_deck_clone_the_lock_is_not_read(self):
        """Un checkout sans le clone du deck : rien ne charge deck_lock.py,
        le verrou se dit libre et les plugins sont ceux de
        l'utilisateur."""
        plugins = self.home / ".config/erplibre-home/deck-plugins"
        plugins.mkdir(parents=True)
        (plugins / "perso.py").write_text("")
        recu = self.collecter({}, racine=self.tmp / "depot")
        self.assertFalse(recu["deck_program"])
        self.assertEqual(
            (None, False, []),
            (recu["lock"], recu["lock_running"], recu["lock_pids"]),
        )
        self.assertEqual(["perso"], recu["plugin_ids"])

    @SANS_DECK
    def test_a_held_lock_names_every_process_holding_it(self):
        chemin = self.tmp / "deck.lock"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(chemin.parent, 0o700)
        tenu = open(chemin, "w", encoding="utf-8")
        self.addCleanup(tenu.close)
        tenu.write("777 controller\n")
        tenu.flush()
        fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recu = self.collecter({})
        self.assertEqual(("777", "controller"), recu["lock"])
        self.assertEqual([os.getpid()], recu["lock_pids"])

    @SANS_DECK
    def test_the_lock_pid_is_running_only_with_its_start_time(self):
        """Le troisième champ du verrou, l'instant de départ, dit si le PID
        nommé désigne encore son auteur ; un texte qui n'en porte pas garde
        l'ancienne lecture."""
        chemin = self.tmp / "deck.lock"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(chemin.parent, 0o700)
        moi = os.getpid()
        with open("/proc/%d/stat" % moi, encoding="utf-8") as fh:
            depart = int(fh.read().rsplit(")", 1)[1].split()[19])
        for texte, attendu in (
            ("%d tiler %d\n" % (moi, depart), True),
            ("%d tiler %d\n" % (moi, depart + 1), False),
            ("%d tiler\n" % moi, True),
            ("4000000000 tiler\n", False),
        ):
            with self.subTest(texte=texte):
                with open(chemin, "w", encoding="utf-8") as tenu:
                    tenu.write(texte)
                    tenu.flush()
                    fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    recu = self.collecter({})
                self.assertEqual(texte.split()[:2], list(recu["lock"]))
                self.assertEqual(attendu, recu["lock_running"])


class LeNiveauInstalle(unittest.TestCase):
    """Le niveau se lit sur disque : le lien de l'extension sous le HOME,
    puis l'interpréteur de .venv.streamdeck sous la racine."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.addCleanup(shutil.rmtree, self.racine)

    def lier_extension(self):
        dossier = os.path.join(
            self.home, ".local/share/gnome-shell/extensions"
        )
        os.makedirs(dossier)
        os.symlink(self.racine, os.path.join(dossier, statut.EXTENSION_UUID))

    def poser_venv(self):
        bin_ = os.path.join(self.racine, ".venv.streamdeck", "bin")
        os.makedirs(bin_)
        python = os.path.join(bin_, "python")
        with open(python, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(python, 0o755)

    def niveau(self):
        return statut.installed_level(self.racine, {"HOME": self.home})

    def test_nothing_installed(self):
        self.assertEqual(statut.LEVEL_NONE, self.niveau())

    def test_a_venv_without_the_extension_is_nothing(self):
        self.poser_venv()
        self.assertEqual(statut.LEVEL_NONE, self.niveau())

    def test_the_extension_alone_is_the_base(self):
        self.lier_extension()
        self.assertEqual(statut.LEVEL_BASE, self.niveau())

    def test_the_extension_and_the_venv_are_the_stream_deck(self):
        self.lier_extension()
        self.poser_venv()
        self.assertEqual(statut.LEVEL_STREAM_DECK, self.niveau())


class LEtat(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def test_a_sound_stream_deck_workstation(self):
        self.assertEqual(
            [
                "Level: Stream Deck",
                "Extension: active",
                "Indicators: all mounted",
                "Service: enabled, active, program tiler",
                "Deck lock: held by tiler (PID 4242)",
                "Decks plugged in: Stream Deck MK.2",
                "udev rule: present",
                "Stream Deck venv: present",
            ],
            statut.status_lines(faits()),
        )

    def test_a_base_workstation_with_an_extension_in_error(self):
        lignes = statut.status_lines(
            faits(
                venv=False,
                udev_rule=False,
                extension={"state": 3.0, "error": "boom"},
                journal={"read": True, "failed": ["device"], "visible": True},
                unit_file=False,
                unit_enabled="",
                unit_active="",
                lock=None,
                decks=[deck(product="", id_product="006c", model="")],
            )
        )
        self.assertEqual(
            [
                "Level: base",
                "Extension: state 3, error: boom",
                "Indicators: failed to mount: device",
                "Service: not installed",
                "Deck lock: free",
                "Decks plugged in: 006c",
                "udev rule: missing",
                "Stream Deck venv: missing",
            ],
            lignes,
        )

    def test_a_deck_passed_to_a_vm_is_named_and_the_service_idle(self):
        lignes = statut.status_lines(
            faits(
                unit_active="inactive",
                lock=None,
                decks=[
                    deck(vm="vm-essai", driver="usbfs"),
                    deck(product="", model="Stream Deck XL", vm=""),
                ],
            )
        )
        self.assertIn(
            "Service: enabled, inactive, program tiler"
            " — idle, the deck is in a VM",
            lignes,
        )
        self.assertIn(
            "Decks plugged in: Stream Deck MK.2 (passed to VM vm-essai),"
            " Stream Deck XL (passed to a VM)",
            lignes,
        )

    def test_a_deck_left_on_the_host_keeps_the_service_line(self):
        lignes = statut.status_lines(
            faits(
                unit_active="inactive",
                decks=[deck(vm="vm-essai"), deck(sysname="3-3")],
            )
        )
        self.assertIn("Service: enabled, inactive, program tiler", lignes)

    def test_the_model_names_a_deck_without_product(self):
        self.assertIn(
            "Decks plugged in: Stream Deck XL",
            statut.status_lines(
                faits(decks=[deck(product="", model="Stream Deck XL")])
            ),
        )

    def test_a_lock_naming_a_process_gone_says_so(self):
        self.assertIn(
            "Deck lock: held by controller (PID 777, no longer running)",
            statut.status_lines(
                faits(lock=("777", "controller"), lock_running=False)
            ),
        )

    def test_nothing_installed_and_nothing_read(self):
        lignes = statut.status_lines(
            faits(
                extension_linked=False,
                venv=False,
                extension={"state": None, "error": ""},
                journal={"read": False, "failed": [], "visible": False},
                decks=[],
            )
        )
        self.assertEqual("Level: not installed", lignes[0])
        self.assertEqual("Extension: not loaded in this session", lignes[1])
        self.assertEqual(
            "Indicators: journal not readable by this user", lignes[2]
        )
        self.assertEqual("Decks plugged in: none", lignes[5])

    def test_a_journal_with_lines_but_no_enabled_stays_not_read(self):
        lignes = statut.status_lines(
            faits(journal={"read": False, "failed": [], "visible": True})
        )
        self.assertEqual("Indicators: journal not read", lignes[2])

    def test_empty_journal_gives_the_hint_without_sudo(self):
        problemes = statut.diagnosis_lines(
            faits(journal={"read": False, "failed": [], "visible": False})
        )
        self.assertIn(
            (
                "The journal is not readable by this user",
                statut.JOURNAL_HINT,
            ),
            problemes,
        )
        self.assertIn("systemd-journal", statut.JOURNAL_HINT)
        self.assertIn("persistent", statut.JOURNAL_HINT)

    def test_status_lists_the_plugins_that_are_off(self):
        f = faits()
        f["settings"] = dict(
            f["settings"], DECK_PLUGINS_OFF=" tiling , ,sound,"
        )
        lignes = statut.status_lines(f)
        self.assertEqual("Plugins off: tiling, sound", lignes[4])

    def test_status_has_no_plugin_line_when_none_is_off(self):
        self.assertFalse(
            [
                ligne
                for ligne in statut.status_lines(faits())
                if "Plugins" in ligne
            ]
        )


class LaPeriodeDansLEtat(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def test_status_shows_the_period_when_it_is_not_the_default(self):
        f = faits()
        f["settings"] = dict(f["settings"], DECK_SESSION_REFRESH_SEC="2.5")
        self.assertIn("Session refresh: 2.5 s", statut.status_lines(f))

    def test_status_has_no_line_for_the_default(self):
        for valeur in ("1", "1.0", "abc", "61"):
            f = faits()
            f["settings"] = dict(
                f["settings"], DECK_SESSION_REFRESH_SEC=valeur
            )
            self.assertFalse(
                [l for l in statut.status_lines(f) if "refresh" in l],
                valeur,
            )

    def test_diagnosis_names_an_invalid_period_and_the_menu_path(self):
        for valeur in ("abc", "0.4", "61", ""):
            f = faits()
            f["settings"] = dict(
                f["settings"], DECK_SESSION_REFRESH_SEC=valeur
            )
            self.assertIn(
                (
                    "Invalid DECK_SESSION_REFRESH_SEC: %r" % valeur,
                    "TODO › ERPLibre Home › Session refresh",
                ),
                statut.diagnosis_lines(f),
                valeur,
            )

    def test_diagnosis_accepts_valid_and_absent_periods(self):
        for valeur in ("1", "0.5", "60", " 2 "):
            f = faits()
            f["settings"] = dict(
                f["settings"], DECK_SESSION_REFRESH_SEC=valeur
            )
            self.assertFalse(
                [p for p in statut.diagnosis_lines(f) if "REFRESH" in p[0]]
            )
        f = faits()
        f["settings"] = {
            k: v
            for k, v in f["settings"].items()
            if k != "DECK_SESSION_REFRESH_SEC"
        }
        self.assertFalse(
            [p for p in statut.diagnosis_lines(f) if "REFRESH" in p[0]]
        )


class LeDiagnostic(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def corrections(self, **changes):
        return [
            fix for _probleme, fix in statut.diagnosis_lines(faits(**changes))
        ]

    def test_a_sound_workstation_has_nothing_to_fix(self):
        self.assertEqual([], statut.diagnosis_lines(faits(lock=None)))

    def test_a_missing_deck_clone_stops_there_with_the_install(self):
        """Sans le programme du deck, ni le service ni le verrou n'ont de
        sens : la liste s'arrête sur l'installation qui le pose."""
        f = faits(deck_program=False, lock=None, unit_file=False, decks=[])
        self.assertEqual(
            [
                (
                    "The deck program is not installed",
                    "make erplibre_home_streamdeck_install",
                )
            ],
            statut.diagnosis_lines(f),
        )
        self.assertIn("Deck program: not installed", statut.status_lines(f))
        self.assertNotIn("Deck lock: free", statut.status_lines(f))

    def test_not_installed_stops_there(self):
        self.assertEqual(
            [("ERPLibre Home is not installed", "make erplibre_home_install")],
            statut.diagnosis_lines(
                faits(extension_linked=False, venv=False, decks=[])
            ),
        )

    def test_each_probe_names_its_fix(self):
        cas = (
            (
                {"extension": {"state": None, "error": ""}},
                "log out and back in",
            ),
            (
                {"extension": {"state": 3.0, "error": "boom"}},
                statut.JOURNAL_GREP,
            ),
            (
                {
                    "journal": {
                        "read": True,
                        "failed": ["device"],
                        "visible": True,
                    }
                },
                statut.JOURNAL_GREP,
            ),
            ({"venv": False}, "make erplibre_home_streamdeck_install"),
            ({"udev_rule": False}, "make erplibre_home_streamdeck_install"),
            ({"unit_file": False}, "make erplibre_home_streamdeck_install"),
            (
                {"settings": {"DECK_PROGRAM": "exemple"}},
                "TODO › ERPLibre Home › Deck program",
            ),
            ({"decks": []}, "plug a Stream Deck in"),
            (
                {"unit_active": "inactive", "lock": None},
                f"systemctl --user start {UNITE}",
            ),
            (
                {"unit_active": "inactive", "lock": ("777", "controller")},
                "close it, or: kill 777",
            ),
            (
                {"unit_enabled": "", "unit_active": ""},
                "run it from the desktop session",
            ),
        )
        for changes, attendu in cas:
            with self.subTest(changes=changes):
                self.assertIn(attendu, self.corrections(**changes))

    def test_a_deck_in_a_vm_is_not_a_stopped_service(self):
        """Tous les decks dans une VM : le service de l'hôte, arrêté ou
        tenu, n'est pas une panne. Un deck resté à l'hôte le redevient."""
        dans_vm = [deck(vm="vm-essai", driver="usbfs")]
        for tenu in (None, ("777", "controller")):
            with self.subTest(tenu=tenu):
                self.assertEqual(
                    [],
                    statut.diagnosis_lines(
                        faits(unit_active="failed", lock=tenu, decks=dans_vm)
                    ),
                )
        self.assertIn(
            f"systemctl --user start {UNITE}",
            self.corrections(
                unit_active="failed",
                lock=None,
                decks=dans_vm + [deck(sysname="3-3")],
            ),
        )

    def test_the_holder_is_named(self):
        problemes = statut.diagnosis_lines(
            faits(unit_active="inactive", lock=("777", "controller"))
        )
        self.assertIn(
            (
                "The deck is held by controller (PID 777)",
                "close it, or: kill 777",
            ),
            problemes,
        )

    def test_a_pid_no_longer_running_is_never_killed(self):
        """Le PID du verrou peut désigner un processus parti, ou repris par
        un autre : la diagnostic ne propose « kill » que sur les processus
        qui tiennent le verrou, et rien quand elle n'en trouve aucun."""
        cas = (
            (("777", "controller"), [778], "close it, or: kill 778"),
            (("777", "controller"), [], "close it"),
        )
        for tenu, pids, attendu in cas:
            with self.subTest(tenu=tenu, pids=pids):
                self.assertIn(
                    attendu,
                    self.corrections(
                        unit_active="inactive",
                        lock=tenu,
                        lock_running=False,
                        lock_pids=pids,
                    ),
                )

    def test_a_disabled_unit_is_a_choice_not_a_problem(self):
        self.assertEqual(
            [], self.corrections(unit_enabled="disabled", lock=None)
        )

    def test_an_unreadable_state_is_not_called_wrong(self):
        problemes = statut.diagnosis_lines(
            faits(unit_enabled="", unit_active="", lock=None)
        )
        self.assertEqual(
            [
                (
                    "The deck service state could not be read",
                    "run it from the desktop session",
                )
            ],
            problemes,
        )

    def test_program_none_does_not_ask_to_start(self):
        self.assertEqual(
            [],
            self.corrections(
                settings={"DECK_PROGRAM": "none"}, unit_active="inactive"
            ),
        )

    def test_diagnosis_names_an_unknown_plugin_id(self):
        f = faits()
        f["settings"] = dict(
            f["settings"], DECK_PLUGINS_OFF="tiling, nope ,sound"
        )
        problemes = statut.diagnosis_lines(f)
        self.assertEqual(
            [
                (
                    "Unknown plugin in DECK_PLUGINS_OFF: nope",
                    "TODO › ERPLibre Home › Plugins on/off",
                )
            ],
            [p for p in problemes if "DECK_PLUGINS_OFF" in p[0]],
        )

    def test_diagnosis_accepts_known_plugin_ids(self):
        f = faits()
        f["settings"] = dict(f["settings"], DECK_PLUGINS_OFF="tiling,sound")
        self.assertFalse(
            [p for p in statut.diagnosis_lines(f) if "PLUGINS" in p[0]]
        )


class LesTraductions(unittest.TestCase):
    def test_every_label_has_fr_and_en(self):
        source = Path(statut.__file__).read_text(encoding="utf-8")
        cles = set(re.findall(r'(?<![\w.])t\(\s*"([^"]+)"\s*\)', source))
        self.assertGreater(len(cles), 30)
        for cle in sorted(cles):
            with self.subTest(cle=cle):
                entree = todo_i18n.TRANSLATIONS.get(cle)
                self.assertIsNotNone(entree, cle)
                self.assertTrue(entree.get("fr") and entree.get("en"))


if __name__ == "__main__":
    unittest.main()
