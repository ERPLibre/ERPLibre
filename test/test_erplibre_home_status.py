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
  ou repris par un autre processus), n'est jamais proposé à « kill ».
"""

import fcntl
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import erplibre_home_status as statut  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

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
            "RESTART_AFTER_GAME": "yes",
            "GAMES": "on",
            "DECK_PLUGINS_OFF": "",
            "DECK_SESSION_REFRESH_SEC": "1",
        },
        "plugin_ids": ["sound", "tiling"],
        "lock": ("4242", "tiler"),
        "lock_running": True,
        "lock_pids": [4242],
        "decks": [{"product": "Stream Deck MK.2", "id_product": "0080"}],
    }
    base.update(changes)
    return base


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
            {"read": True, "failed": [], "visible": True}, statut.parse_journal(JOURNAL_SAIN)
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
            appareils = {
                "1-1": {"idVendor": "1d6b", "idProduct": "0002"},
                "3-2": {
                    "idVendor": "0fd9",
                    "idProduct": "0080",
                    "product": "Stream Deck MK.2",
                },
                "3-4": {"idVendor": "0fd9", "idProduct": "006c"},
            }
            for nom, fichiers in appareils.items():
                dossier = Path(sysfs, "bus/usb/devices", nom)
                dossier.mkdir(parents=True)
                for fichier, valeur in fichiers.items():
                    (dossier / fichier).write_text(valeur + "\n")
            self.assertEqual(
                [
                    {"product": "Stream Deck MK.2", "id_product": "0080"},
                    {"product": "", "id_product": "006c"},
                ],
                statut.plugged_decks(sysfs),
            )


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

    def collecter(self, sorties, unite=False):
        if unite:
            fichier = self.home / ".config/systemd/user" / UNITE
            fichier.parent.mkdir(parents=True)
            fichier.write_text("[Unit]\n")
        return statut.collect(
            self.run_enregistre(sorties),
            str(RACINE),
            environ={"HOME": str(self.home)},
            sysfs=str(self.tmp / "sys"),
            udev_rule=str(self.tmp / "absente.rules"),
            lock_path=str(self.tmp / "deck.lock"),
        )

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
                    "RESTART_AFTER_GAME": "yes",
                    "GAMES": "on",
                    "DECK_PLUGINS_OFF": "",
                    "DECK_SESSION_REFRESH_SEC": "1",
                },
                "plugin_ids": statut.service.deck_plugin_ids(
                    str(RACINE), {"HOME": str(self.home)}
                ),
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

    def test_a_held_lock_names_every_process_holding_it(self):
        chemin = self.tmp / "deck.lock"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(chemin.parent, 0o700)
        tenu = open(chemin, "w", encoding="utf-8")
        self.addCleanup(tenu.close)
        tenu.write("777 game\n")
        tenu.flush()
        fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recu = self.collecter({})
        self.assertEqual(("777", "game"), recu["lock"])
        self.assertEqual([os.getpid()], recu["lock_pids"])

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
            ("%d game %d\n" % (moi, depart), True),
            ("%d game %d\n" % (moi, depart + 1), False),
            ("%d game\n" % moi, True),
            ("4000000000 game\n", False),
        ):
            with self.subTest(texte=texte):
                with open(chemin, "w", encoding="utf-8") as tenu:
                    tenu.write(texte)
                    tenu.flush()
                    fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    recu = self.collecter({})
                self.assertEqual(texte.split()[:2], list(recu["lock"]))
                self.assertEqual(attendu, recu["lock_running"])


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
                "Games: on",
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
                decks=[{"product": "", "id_product": "006c"}],
            )
        )
        self.assertEqual(
            [
                "Level: base",
                "Extension: state 3, error: boom",
                "Indicators: failed to mount: device",
                "Service: not installed",
                "Games: on",
                "Deck lock: free",
                "Decks plugged in: 006c",
                "udev rule: missing",
                "Stream Deck venv: missing",
            ],
            lignes,
        )

    def test_a_lock_naming_a_process_gone_says_so(self):
        self.assertIn(
            "Deck lock: held by game (PID 777, no longer running)",
            statut.status_lines(
                faits(lock=("777", "game"), lock_running=False)
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
        self.assertEqual("Decks plugged in: none", lignes[6])

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

    def test_status_shows_games_even_without_a_unit(self):
        f = faits(unit_file=False)
        f["settings"] = dict(f["settings"], GAMES="off")
        self.assertIn("Games: off", statut.status_lines(f))

    def test_status_shows_a_carriage_return_visibly(self):
        f = faits()
        f["settings"] = dict(f["settings"], GAMES="on\r")
        self.assertIn(
            "Games: unknown value 'on\\r'", statut.status_lines(f)
        )

    def test_status_lists_the_plugins_that_are_off(self):
        f = faits()
        f["settings"] = dict(
            f["settings"], DECK_PLUGINS_OFF=" tiling , ,sound,"
        )
        lignes = statut.status_lines(f)
        self.assertEqual("Games: on", lignes[4])
        self.assertEqual("Plugins off: tiling, sound", lignes[5])

    def test_status_has_no_plugin_line_when_none_is_off(self):
        self.assertFalse(
            [ligne for ligne in statut.status_lines(faits())
             if "Plugins" in ligne]
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
                    "TODO › Stream Deck › Session refresh",
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
            k: v for k, v in f["settings"].items()
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
                {"journal": {"read": True, "failed": ["device"], "visible": True}},
                statut.JOURNAL_GREP,
            ),
            ({"venv": False}, "make erplibre_home_streamdeck_install"),
            ({"udev_rule": False}, "make erplibre_home_streamdeck_install"),
            ({"unit_file": False}, "make erplibre_home_streamdeck_install"),
            (
                {"settings": {"DECK_PROGRAM": "exemple"}},
                "TODO › Stream Deck › Deck program",
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

    def test_a_game_is_closed_first_and_killed_as_a_whole(self):
        """Tuer le seul PID du verrou laisserait le jeu sur le deck quand
        l'enveloppe est déjà morte : le dernier recours nomme chaque
        processus qui tient le verrou."""
        problemes = statut.diagnosis_lines(
            faits(
                unit_active="inactive",
                lock=("777", "game"),
                lock_pids=[777, 778, 779],
            )
        )
        self.assertIn(
            (
                "The deck is held by game (PID 777)",
                "close the game; as a last resort: kill 777 778 779",
            ),
            problemes,
        )

    def test_a_game_with_no_process_found_names_the_lock_pid(self):
        self.assertIn(
            "close the game; as a last resort: kill 777",
            self.corrections(
                unit_active="inactive", lock=("777", "game"), lock_pids=[]
            ),
        )

    def test_a_pid_no_longer_running_is_never_killed(self):
        """Le PID du verrou peut désigner un processus parti, ou repris par
        un autre : la diagnostic ne propose « kill » que sur les processus
        qui tiennent le verrou, et rien quand elle n'en trouve aucun."""
        cas = (
            (
                ("777", "game"),
                [778],
                "close the game; as a last resort: kill 778",
            ),
            (("777", "game"), [], "close the game"),
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

    def test_diagnosis_names_an_unknown_games_value(self):
        f = faits(unit_file=False)
        f["settings"] = dict(f["settings"], GAMES="yes")
        self.assertIn(
            (
                "Unknown GAMES value: 'yes'",
                "TODO › Stream Deck › Games on/off",
            ),
            statut.diagnosis_lines(f),
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
                    "TODO › Stream Deck › Plugins on/off",
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
