#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Mémoire Swap : son entrée dans le menu Système, et l'état
en lignes.

L'état est fabriqué et subprocess.run est remplacé : un test ne lit rien
de la machine qui le lance et n'exécute rien.
"""

import ast
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_menu as sm  # noqa: E402
from script.todo import system_swap as ss  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

MIO = ss.MIO
GIO = ss.GIO
RACINE_FS = {
    "mountpoint": "/",
    "fstype": "ext4",
    "source": "/dev/vda1",
    "root": "/",
}


def setUpModule():
    ancienne = todo_i18n._current_lang
    todo_i18n._current_lang = "fr"
    unittest.addModuleCleanup(setattr, todo_i18n, "_current_lang", ancienne)


def fichier_swap(chemin="/swapfile", taille=2 * GIO, utilise=100 * MIO):
    return {
        "path": chemin,
        "type": "file",
        "size": taille,
        "used": utilise,
        "priority": -2,
        "fs": dict(RACINE_FS),
        "free": 20 * GIO,
        "hibernation": False,
    }


def persistance(mode=None, installe=False):
    return {
        "mode": mode,
        "generator_installed": installe,
        "generator": {
            "main": None,
            "dropins": [],
            "sections": {},
            "etc_dropins": [],
            "usr_dropins": [],
        },
        "generator_devices": [],
        "zram_tools_installed": False,
        "zram_tools": None,
        "both": False,
    }


def etat_fabrique(racine, swaps=(), zram=(), **autres):
    """Un état complet tel que system_swap.etat() le rend : 8 Gio de RAM,
    une racine ext4 avec 20 Gio libres."""
    swaps = list(swaps)
    etat = {
        "memory": {
            "total": 8 * GIO,
            "available": 6 * GIO,
            "swap_total": sum(s["size"] for s in swaps),
            "swap_free": sum(s["size"] - s["used"] for s in swaps),
        },
        "swaps": swaps,
        "zram": list(zram),
        "persistence": persistance(),
        "hibernation": {"resume": None, "resume_offset": None},
        "mounts": [dict(RACINE_FS)],
        "root_fs": dict(RACINE_FS),
        "root_free": 20 * GIO,
        "os_id": "arch",
        "recommendation": ss.recommandation(8 * GIO),
        "racine": racine,
    }
    etat.update(autres)
    return etat


class Banc(unittest.TestCase):
    """Un TODO sans __init__, et print capté."""

    def setUp(self):
        from script.todo.todo import TODO

        self.TODO = TODO
        self.todo = TODO.__new__(TODO)
        self.vus = []
        for patch in (
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: self.vus.append(
                    " ".join(map(str, a))
                ),
            ),
            mock.patch.object(
                sm.subprocess,
                "run",
                side_effect=AssertionError("subprocess.run inattendu"),
            ),
            mock.patch("script.todo.todo_telemetry.record", return_value=None),
        ):
            patch.start()
            self.addCleanup(patch.stop)


class TestLaNavigation(Banc):
    def test_entry_9_opens_swap_memory(self):
        with (
            mock.patch.object(self.TODO, "_system_swap") as swap,
            mock.patch("click.prompt", side_effect=["9", "0"]),
        ):
            self.todo.prompt_execute_system()
        swap.assert_called_once_with()

    def test_the_system_menu_lists_swap_memory_ninth(self):
        with mock.patch("click.prompt", side_effect=["0"]) as invite:
            self.todo.prompt_execute_system()
        self.assertIn("[9] 💾 Mémoire Swap", invite.call_args.args[0])

    def test_each_submenu_entry_calls_its_action(self):
        attendus = {
            "1": ("_system_swap_etat", ()),
        }
        for touche, (methode, args) in attendus.items():
            with (
                self.subTest(touche=touche),
                mock.patch.object(self.TODO, methode) as action,
                mock.patch("click.prompt", side_effect=[touche, "0"]),
            ):
                self.todo._system_swap()
            action.assert_called_once_with(*args)

    def test_the_breadcrumb_names_swap_memory(self):
        with mock.patch("click.prompt", side_effect=["0"]) as invite:
            self.todo._system_swap()
        self.assertIn("Swap memory", invite.call_args.args[0])
        self.assertIn("[1] 📊", invite.call_args.args[0])


class TestLesTraductions(unittest.TestCase):
    def _cles_du_menu(self):
        with open(sm.__file__, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        return [
            n.args[0].value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        ]

    def test_every_message_is_translated(self):
        cles = self._cles_du_menu() + [
            v
            for table in (sm.ALERTES_SWAP, sm.TYPES_SWAP)
            for v in table.values()
        ]
        manquantes = sorted(
            {c for c in cles if c not in todo_i18n.TRANSLATIONS}
        )
        self.assertEqual(manquantes, [])


class TestLesLignes(unittest.TestCase):
    def test_state_reads_every_section_without_none(self):
        zram = {
            "name": "zram0",
            "device": "/dev/zram0",
            "disksize": 4 * GIO,
            "algorithm": "zstd",
            "algorithms": ["lzo-rle", "zstd"],
            "orig_data": 300 * MIO,
            "compr_data": 100 * MIO,
            "mem_used": 110 * MIO,
            "ratio": 3.0,
            "active": True,
        }
        swap_zram = {
            "path": "/dev/zram0",
            "type": "zram",
            "size": 4 * GIO,
            "used": 300 * MIO,
            "priority": 100,
            "fs": None,
            "free": None,
            "hibernation": False,
        }
        etat = etat_fabrique(
            "/inexistant",
            swaps=[fichier_swap(), swap_zram],
            zram=[zram],
            hibernation={"resume": "/dev/vda1", "resume_offset": 4352},
        )
        texte = "\n".join(sm.lignes_swap(etat))
        self.assertNotIn("None", texte)
        self.assertIn("/swapfile", texte)
        self.assertIn("fichier", texte)
        self.assertIn("ratio 3.0", texte)
        self.assertIn("aucune : cette zram a été montée à la main", texte)
        self.assertIn("resume_offset=4352", texte)
        self.assertIn("priorité 100", texte)
        self.assertIn("Recommandation", texte)

    def test_no_swap_and_generator_persistence(self):
        etat = etat_fabrique("/inexistant")
        etat["persistence"] = persistance("zram-generator", installe=True)
        etat["persistence"]["generator"]["main"] = (
            "/usr/lib/systemd/zram-generator.conf"
        )
        texte = "\n".join(sm.lignes_swap(etat))
        self.assertIn("Aucun swap actif.", texte)
        self.assertIn(
            "zram-generator (/usr/lib/systemd/zram-generator.conf)", texte
        )
        self.assertIn("Non configurée", texte)


if __name__ == "__main__":
    unittest.main()
