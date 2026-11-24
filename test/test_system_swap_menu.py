#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Mémoire Swap : l'état en lignes, les phrases des refus, le
protocole des plans (rien sans oui, arrêt au premier échec), le choix du
swap à modifier, la zram et le verdict sur l'ajout de RAM.

L'état est fabriqué et system_swap.etat() le rend tel quel ; les commandes
passent par un execute factice et subprocess.run est remplacé : un test ne
lit rien de la machine qui le lance et n'exécute rien.
"""

import ast
import os
import string
import sys
import tempfile
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
        "max_size": taille + 19 * GIO,
        "hibernation": False,
    }


def partition_swap(chemin="/dev/vda3", taille=4 * GIO):
    return {
        "path": chemin,
        "type": "partition",
        "size": taille,
        "used": 0,
        "priority": -3,
        "fs": None,
        "free": None,
        "max_size": None,
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
    une racine ext4 avec 20 Gio libres, pacman."""
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
        "fstab": "/dev/vda1 / ext4 defaults 0 1\n",
        "manager": "pacman",
        "os_id": "arch",
        "btrfs_mkswapfile": False,
        "virtualization": None,
        "recommendation": ss.recommandation(8 * GIO),
        "racine": racine,
    }
    etat.update(autres)
    return etat


class Banc(unittest.TestCase):
    """Un TODO sans __init__, un execute factice, et print/input captés."""

    def setUp(self):
        from script.todo.todo import TODO

        self.TODO = TODO
        self.todo = TODO.__new__(TODO)
        self.todo.execute = mock.Mock()
        self.todo.execute.exec_command_live.return_value = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
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
        sync = mock.patch.object(sm.os, "sync")
        self.sync = sync.start()
        self.addCleanup(sync.stop)

    def etat(self, **kw):
        return etat_fabrique(self.tmp.name, **kw)

    def lancer(self, methode, etat, reponses, *args):
        with (
            mock.patch.object(ss, "etat", return_value=etat),
            mock.patch("builtins.input", side_effect=list(reponses)),
        ):
            return getattr(self.todo, methode)(*args)

    def lances(self):
        return [
            c.args[0]
            for c in self.todo.execute.exec_command_live.call_args_list
        ]

    def texte(self):
        return "\n".join(self.vus)


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
            "2": ("_system_swap_redimensionner", ("grow",)),
            "3": ("_system_swap_redimensionner", ("shrink",)),
            "4": ("_system_swap_zram", ()),
            "5": ("_system_swap_zram_desactiver", ()),
            "6": ("_system_swap_memoire", ()),
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
        self.assertIn("[6] 🧩", invite.call_args.args[0])


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
            for table in (
                sm.RAISONS_SWAP,
                sm.ALERTES_SWAP,
                sm.VERDICTS_MEMOIRE,
                sm.TYPES_SWAP,
            )
            for v in table.values()
        ]
        manquantes = sorted(
            {c for c in cles if c not in todo_i18n.TRANSLATIONS}
        )
        self.assertEqual(manquantes, [])

    def _codes_du_module(self):
        """Les raisons de _refus("…") et les codes {"code": "…"} que
        system_swap rend, lus dans sa source."""
        with open(ss.__file__, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        raisons, alertes = set(), set()
        for n in ast.walk(arbre):
            if (
                isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "_refus"
                and isinstance(n.args[0], ast.Constant)
            ):
                raisons.add(n.args[0].value)
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values, strict=True):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "code"
                        and isinstance(v, ast.Constant)
                    ):
                        alertes.add(v.value)
        return raisons, alertes

    def test_every_code_of_system_swap_has_a_sentence(self):
        raisons, alertes = self._codes_du_module()
        self.assertGreater(len(raisons), 15)
        self.assertEqual(raisons - set(sm.RAISONS_SWAP), set())
        self.assertEqual(alertes - set(sm.ALERTES_SWAP), set())

    def test_every_field_of_a_sentence_is_filled(self):
        """Un champ {…} qu'aucun détail ne remplit s'afficherait « ? » :
        chaque phrase n'en nomme que de connus."""
        connus = sm.TAILLES_SWAP | {
            "path",
            "suggestion",
            "fstype",
            "mountpoint",
            "parent",
            "manager",
            "resume",
            "subvolume",
            "service",
            "paths",
            "virtualization",
            "free_slots",
            "slots",
            "used_slots",
            "running",
            "installed",
        }
        for table in (sm.RAISONS_SWAP, sm.ALERTES_SWAP, sm.VERDICTS_MEMOIRE):
            for cle in table.values():
                champs = {
                    f for _l, f, _s, _c in string.Formatter().parse(cle) if f
                }
                self.assertLessEqual(champs, connus, cle)


class TestLesLignes(unittest.TestCase):
    def test_state_warns_when_the_zram_module_cannot_load(self):
        etat = etat_fabrique(
            "/",
            zram_module={
                "state": "reboot",
                "running": "9.8.7-test",
                "installed": ["9.9.0-test"],
            },
        )
        texte = "\n".join(sm.lignes_swap(etat))
        self.assertIn("⚠ Le noyau en marche (9.8.7-test)", texte)
        etat["zram_module"] = {
            "state": "missing",
            "running": "9.8.7-test",
            "installed": [],
        }
        texte = "\n".join(sm.lignes_swap(etat))
        self.assertIn("n'a pas de module zram", texte)
        etat["zram_module"]["state"] = "available"
        self.assertNotIn("module", "\n".join(sm.lignes_swap(etat)))

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
            "max_size": None,
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

    def test_integer_input_takes_ascii_digits_only(self):
        self.assertEqual(sm.entier("42"), 42)
        for texte in ("", "²", "٣", "-1", "1.5", " 1"):
            with self.subTest(texte=texte):
                self.assertIsNone(sm.entier(texte))

    def verdict(self, **kw):
        v = {
            "verdict": "unknown",
            "ram": 8 * GIO,
            "installed": None,
            "max_capacity": None,
            "slots": None,
            "used_slots": None,
            "free_slots": None,
            "max_addable": None,
            "form_factors": [],
            "types": [],
            "partially_soldered": False,
            "max_understated": False,
            "firmware_note": False,
            "swap_growth": None,
            "virtualization": None,
        }
        v.update(kw)
        return "\n".join(sm.lignes_memoire(v))

    def test_each_verdict_reads_a_sentence(self):
        materiel = dict(
            installed=8 * GIO,
            slots=2,
            used_slots=1,
            free_slots=1,
            max_capacity=32 * GIO,
            max_addable=24 * GIO,
            types=["DDR4"],
            form_factors=["SODIMM"],
            firmware_note=True,
            swap_growth=19 * GIO,
        )
        cas = {
            "vm": ("Machine virtuelle (kvm)", {"virtualization": "kvm"}),
            "unknown": ("sans dmidecode", {}),
            "free_slots": ("Oui : 1 emplacement(s) libre(s) sur 2", materiel),
            "replace": ("en remplaçant des modules", materiel),
            "max": ("au maximum", materiel),
            "soldered": ("soudée", materiel),
        }
        for code, (attendu, kw) in cas.items():
            with self.subTest(code=code):
                texte = self.verdict(verdict=code, **kw)
                self.assertIn(attendu, texte)
                self.assertNotIn("None", texte)
        texte = self.verdict(verdict="free_slots", **materiel)
        self.assertIn("DDR4, SODIMM", texte)
        self.assertIn("24.0 Gio de plus", texte)
        self.assertIn("micrologiciel", texte)
        self.assertIn("19.0 Gio", texte)
        # Le titre de section est sobre comme les autres : l'emoji reste
        # à l'entrée du menu.
        self.assertTrue(texte.startswith("── Ajout de mémoire ──"))

    def test_unknown_maximum_is_said(self):
        texte = self.verdict(
            verdict="max", installed=8 * GIO, slots=2, used_slots=2
        )
        self.assertIn("capacité maximale est inconnue", texte)


class TestLeProtocoleDesPlans(Banc):
    def test_a_refusal_runs_nothing_and_says_why(self):
        res = ss._refus(
            "disk_full", needed=5 * GIO, free=2 * GIO, max_size=None
        )
        with mock.patch("builtins.input", side_effect=AssertionError):
            self.assertFalse(self.todo._system_swap_appliquer(res))
        self.assertEqual(self.lances(), [])
        self.assertIn("5.0 Gio nécessaires", self.texte())
        self.assertIn("Plus grande taille possible : ?", self.texte())

    def test_nixos_prints_the_snippet_and_runs_nothing(self):
        res = ss._nix(
            ss._resultat(True, new=GIO),
            ss.extrait_nix(swap=("/swapfile", GIO)),
        )
        with mock.patch("builtins.input", side_effect=AssertionError):
            self.todo._system_swap_appliquer(res)
        self.assertEqual(self.lances(), [])
        self.assertIn("swapDevices", self.texte())
        self.assertIn("nixos-rebuild", self.texte())

    def plan_avec_fichier(self):
        tmp = os.path.join(self.tmp.name, "zram-generator.conf")
        return tmp, ss._resultat(
            True,
            plan=[
                ["sudo", "install", "-D", "-m", "0644", tmp, "/etc/x.conf"],
                ["sudo", "systemctl", "daemon-reload"],
            ],
            files={tmp: "[zram0]\nzram-size = 4096\n"},
        )

    def test_nothing_runs_nor_is_written_without_a_yes(self):
        tmp, res = self.plan_avec_fichier()
        for reponse in ("", "n"):
            self.assertFalse(
                self.lancer(
                    "_system_swap_appliquer", self.etat(), [reponse], res
                )
            )
        self.assertEqual(self.lances(), [])
        self.assertFalse(os.path.exists(tmp))
        self.assertIn(
            "Va exécuter : sudo systemctl daemon-reload", self.texte()
        )
        self.assertIn("│ zram-size = 4096", self.texte())

    def test_files_are_written_before_the_commands_run(self):
        tmp, res = self.plan_avec_fichier()
        lus = []

        def executer(cmd, source_erplibre=True):
            with open(tmp, encoding="utf-8") as fh:
                lus.append(fh.read())
            return 0

        self.todo.execute.exec_command_live.side_effect = executer
        self.assertTrue(
            self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        )
        self.assertEqual(
            self.lances(),
            [
                f"sudo install -D -m 0644 {tmp} /etc/x.conf",
                "sudo systemctl daemon-reload",
            ],
        )
        self.assertEqual(lus[0], "[zram0]\nzram-size = 4096\n")
        for appel in self.todo.execute.exec_command_live.call_args_list:
            self.assertIs(appel.kwargs["source_erplibre"], False)
        self.assertIn("✓ Terminé.", self.texte())
        self.assertIn("── Swaps actifs ──", self.texte())

    def test_the_first_failure_stops_the_plan(self):
        _tmp, res = self.plan_avec_fichier()
        self.todo.execute.exec_command_live.return_value = 1
        self.assertFalse(
            self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        )
        self.assertEqual(len(self.lances()), 1)
        texte = self.texte()
        self.assertIn("⚠ Commande en échec : sudo install", texte)
        # La commande en échec n'est pas comptée parmi celles qui ne sont
        # pas lancées ; la suivante l'est.
        apres = texte.split("Non lancées :", 1)[1]
        self.assertIn("sudo systemctl daemon-reload", apres)
        self.assertNotIn("sudo install", apres.split("──", 1)[0])
        self.assertNotIn("✓ Terminé.", texte)

    def test_the_state_is_read_again_after_a_sync(self):
        """btrfs publie l'espace d'un fichier créé à la validation de sa
        transaction : le sync précède la relecture de l'état."""
        _tmp, res = self.plan_avec_fichier()
        ordre = []
        self.sync.side_effect = lambda: ordre.append("sync")
        with mock.patch.object(
            self.TODO,
            "_system_swap_etat",
            side_effect=lambda: ordre.append("etat"),
        ):
            self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        self.assertEqual(ordre, ["sync", "etat"])

    def test_a_failure_on_the_last_command_lists_nothing_left(self):
        _tmp, res = self.plan_avec_fichier()
        self.todo.execute.exec_command_live.side_effect = [0, 1]
        self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        self.assertIn("⚠ Commande en échec : sudo systemctl", self.texte())
        self.assertNotIn("Non lancées", self.texte())

    def test_a_file_is_announced_as_to_write_before_the_yes(self):
        """Avant le oui, rien n'est écrit : la phrase le dit au futur."""
        _tmp, res = self.plan_avec_fichier()
        self.lancer("_system_swap_appliquer", self.etat(), ["n"], res)
        self.assertIn("Contenu à écrire dans", self.texte())
        self.assertNotIn("Contenu écrit", self.texte())

    def test_ctrl_c_stops_the_plan_and_shows_the_state(self):
        """Un Ctrl-C pendant une commande arrête le plan comme un échec :
        il ne sort pas de TODO, et l'état relu s'affiche."""
        _tmp, res = self.plan_avec_fichier()
        self.todo.execute.exec_command_live.side_effect = KeyboardInterrupt
        self.assertFalse(
            self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        )
        self.assertEqual(len(self.lances()), 1)
        self.assertIn("⚠ Interrompu", self.texte())
        self.assertIn("── Swaps actifs ──", self.texte())

    def test_a_failure_after_swapoff_says_how_to_rebuild(self):
        """Le swapoff et le rm sont passés, la recréation échoue : le swap
        est éteint et son fichier manque, la reprise donne les commandes
        depuis le rm."""
        etat = self.etat(swaps=[fichier_swap()])
        res = ss.plan_redimensionner(etat, "/swapfile", 4 * GIO, "grow")
        self.todo.execute.exec_command_live.side_effect = [0, 0, 1]
        self.lancer("_system_swap_appliquer", etat, ["o"], res)
        texte = self.texte()
        self.assertIn("/swapfile n'est plus un swap actif", texte)
        reprise = texte.split("Pour le reconstruire, lancer :")[1]
        self.assertIn("sudo rm -f /swapfile", reprise)
        self.assertIn("sudo swapon /swapfile", reprise)
        self.assertNotIn("swapoff", reprise.split("──")[0])

    def test_a_failed_swapoff_needs_no_rebuild(self):
        etat = self.etat(swaps=[fichier_swap()])
        res = ss.plan_redimensionner(etat, "/swapfile", 4 * GIO, "grow")
        self.todo.execute.exec_command_live.return_value = 1
        self.lancer("_system_swap_appliquer", etat, ["o"], res)
        self.assertNotIn("reconstruire", self.texte())


class TestAgrandirReduire(Banc):
    def test_grow_a_swapfile_runs_the_full_recreation(self):
        etat = self.etat(swaps=[fichier_swap()])
        self.lancer("_system_swap_redimensionner", etat, ["4G", "o"], "grow")
        self.assertEqual(
            self.lances(),
            [
                "sudo swapoff /swapfile",
                "sudo rm -f /swapfile",
                "sudo fallocate -l 4096MiB /swapfile",
                "sudo chmod 600 /swapfile",
                "sudo mkswap /swapfile",
                "sudo swapon /swapfile",
            ],
        )
        self.assertIn("Taille : 2.0 Gio → 4.0 Gio", self.texte())

    def test_enter_takes_the_recommendation(self):
        etat = self.etat(swaps=[fichier_swap()])
        self.lancer("_system_swap_redimensionner", etat, ["", "o"], "grow")
        self.assertIn("sudo fallocate -l 8192MiB /swapfile", self.lances())
        self.assertIn("Recommandé : 8.0 Gio.", self.texte())

    def test_a_swapfile_already_at_the_recommendation_gets_no_default(self):
        """/proc/swaps compte une page de moins que le fichier : un swap
        créé à 8 Gio se lit 8 Gio - 4 Kio, et 8 Gio n'est pas « plus »."""
        taille = 8 * GIO - 4096
        etat = self.etat(swaps=[fichier_swap(taille=taille)])
        self.lancer("_system_swap_redimensionner", etat, [""], "grow")
        self.assertNotIn("Recommandé", self.texte())
        self.assertEqual(self.lances(), [])

    def test_shrink_refuses_a_larger_size(self):
        etat = self.etat(swaps=[fichier_swap()])
        self.lancer("_system_swap_redimensionner", etat, ["4G"], "shrink")
        self.assertEqual(self.lances(), [])
        self.assertIn("n'est pas plus petit", self.texte())

    def test_shrink_refused_when_ram_cannot_absorb(self):
        etat = self.etat(swaps=[fichier_swap(utilise=GIO)])
        etat["memory"]["available"] = GIO
        self.lancer("_system_swap_redimensionner", etat, ["1G"], "shrink")
        self.assertEqual(self.lances(), [])
        self.assertIn("épuiserait la mémoire", self.texte())

    def test_a_typo_is_not_a_size(self):
        etat = self.etat(swaps=[fichier_swap()])
        self.lancer("_system_swap_redimensionner", etat, ["4X"], "grow")
        self.assertEqual(self.lances(), [])
        self.assertIn("Ce n'est pas une taille : 4X", self.texte())

    def test_several_swaps_ask_which_one(self):
        etat = self.etat(
            swaps=[partition_swap(), fichier_swap("/data/swapfile")]
        )
        etat["swaps"][1]["fs"] = {
            "mountpoint": "/data",
            "fstype": "xfs",
            "source": "/dev/vdb1",
            "root": "/",
        }
        self.lancer(
            "_system_swap_redimensionner", etat, ["2", "1G", "o"], "shrink"
        )
        self.assertIn("sudo swapoff /data/swapfile", self.lances())
        self.assertIn("[2] /data/swapfile", self.texte())

    def test_a_partition_is_not_resized_but_a_swapfile_is_offered(self):
        etat = self.etat(swaps=[partition_swap()])
        with mock.patch.object(self.TODO, "_system_swap_creer") as creer:
            self.lancer("_system_swap_redimensionner", etat, ["o"], "grow")
        creer.assert_called_once_with(etat)
        self.assertEqual(self.lances(), [])
        self.assertIn("partition de swap", self.texte())

    def test_shrinking_a_partition_offers_nothing(self):
        etat = self.etat(swaps=[partition_swap()])
        with mock.patch.object(self.TODO, "_system_swap_creer") as creer:
            self.lancer("_system_swap_redimensionner", etat, [], "shrink")
        creer.assert_not_called()
        self.assertIn("ne se réduit pas d'ici", self.texte())
        self.assertNotIn("fichier d'échange", self.texte())

    def test_a_container_is_refused_before_any_question(self):
        etat = self.etat(
            swaps=[partition_swap("none")],
            virtualization="lxc",
            container=True,
        )
        with mock.patch("builtins.input", side_effect=AssertionError):
            with mock.patch.object(ss, "etat", return_value=etat):
                self.todo._system_swap_redimensionner("grow")
                self.todo._system_swap_zram()
        self.assertEqual(self.lances(), [])
        self.assertEqual(self.texte().count("Conteneur (lxc)"), 2)

    def test_no_disk_swap_grow_creates_shrink_says_so(self):
        etat = self.etat()
        with mock.patch.object(self.TODO, "_system_swap_creer") as creer:
            self.lancer("_system_swap_redimensionner", etat, [], "grow")
            creer.assert_called_once_with(etat)
            self.lancer("_system_swap_redimensionner", etat, [], "shrink")
            creer.assert_called_once()
        self.assertIn("rien à réduire", self.texte())


class TestCreer(Banc):
    def test_default_path_and_size_reach_the_plan(self):
        etat = self.etat()
        with mock.patch.object(
            ss, "plan_creer", return_value=ss._refus("exists", path="/x")
        ) as plan:
            self.lancer("_system_swap_creer", etat, ["", ""], etat)
        plan.assert_called_once_with(etat, "/swapfile", 8 * GIO)

    def test_btrfs_root_proposes_a_subvolume_and_says_why(self):
        racine = dict(RACINE_FS, fstype="btrfs")
        etat = self.etat(root_fs=racine, mounts=[racine])
        with mock.patch.object(
            ss, "plan_creer", return_value=ss._refus("exists", path="/x")
        ) as plan:
            self.lancer("_system_swap_creer", etat, ["", "2G"], etat)
        plan.assert_called_once_with(etat, "/swap/swapfile", 2 * GIO)
        self.assertIn("sous-volume à lui", self.texte())

    def test_the_fstab_line_and_its_backup_are_announced(self):
        etat = self.etat()
        res = ss._resultat(
            True,
            plan=[["sudo", "swapon", "/swapfile"]],
            new=GIO,
            fstab="added",
            backup="/etc/fstab.bak-20990101-000000",
            line="/swapfile none swap defaults 0 0",
        )
        with mock.patch.object(ss, "plan_creer", return_value=res):
            self.lancer("_system_swap_creer", etat, ["", "1G", "n"], etat)
        self.assertIn(
            "« /swapfile none swap defaults 0 0 », après une copie dans"
            " /etc/fstab.bak-20990101-000000",
            self.texte(),
        )


class TestZram(Banc):
    def test_enable_installs_the_generator_and_writes_its_conf(self):
        etat = self.etat()
        lus = {}

        def executer(cmd, source_erplibre=True):
            if " install -D " in cmd:
                source = cmd.split()[5]
                with open(source, encoding="utf-8") as fh:
                    lus["conf"] = fh.read()
            return 0

        self.todo.execute.exec_command_live.side_effect = executer
        self.lancer("_system_swap_zram", etat, ["2G", "o"])
        lances = self.lances()
        self.assertTrue(lances[0].startswith("sudo pacman -S"))
        self.assertIn("zram-generator", lances[0])
        self.assertEqual(
            lances[-2:],
            [
                "sudo systemctl restart systemd-zram-setup@zram0.service",
                "sudo systemctl start dev-zram0.swap",
            ],
        )
        self.assertIn("zram-size = 2048", lus["conf"])
        self.assertIn("swap-priority = 100", lus["conf"])
        self.assertIn("son paquet s'installe d'abord", self.texte())

    def test_the_temporary_directory_is_removed(self):
        etat = self.etat()
        vus = []

        def plan_zram(etat, taille, dossier):
            vus.append(dossier)
            return ss._refus("below_floor", floor=64 * MIO, new=taille)

        with mock.patch.object(ss, "plan_zram", side_effect=plan_zram):
            self.lancer("_system_swap_zram", etat, ["1G"])
        self.assertFalse(os.path.exists(vus[0]))

    def test_disable_a_manual_zram(self):
        swap_zram = {
            "path": "/dev/zram0",
            "type": "zram",
            "size": 4 * GIO,
            "used": 0,
            "priority": 100,
            "fs": None,
            "free": None,
            "max_size": None,
            "hibernation": False,
        }
        etat = self.etat(swaps=[swap_zram])
        self.lancer("_system_swap_zram_desactiver", etat, ["o"])
        self.assertEqual(
            self.lances(),
            ["sudo swapoff /dev/zram0", "sudo zramctl --reset /dev/zram0"],
        )

    def test_another_zram_service_refuses_before_the_size(self):
        pers = persistance("service")
        pers["service"] = "zram-config.service"
        etat = self.etat(persistence=pers)
        with mock.patch("builtins.input", side_effect=AssertionError):
            self.lancer("_system_swap_zram", etat, [])
        self.assertIn("zram-config.service gère déjà la zram", self.texte())

    def test_a_kernel_awaiting_reboot_refuses_before_the_size(self):
        module = {
            "state": "reboot",
            "running": "9.8.7-test",
            "installed": ["9.9.0-test"],
        }
        etat = self.etat(zram_module=module)
        with mock.patch("builtins.input", side_effect=AssertionError):
            self.lancer("_system_swap_zram", etat, [])
        self.assertEqual(self.lances(), [])
        self.assertIn(
            "Le noyau en marche (9.8.7-test) n'a plus ses modules",
            self.texte(),
        )
        self.assertIn("9.9.0-test", self.texte())

    def test_disable_without_zram_says_so(self):
        self.lancer("_system_swap_zram_desactiver", self.etat(), [])
        self.assertEqual(self.lances(), [])
        self.assertIn("Aucune zram n'est active ni configurée.", self.texte())


DMIDECODE = """\
Handle 0x0010, DMI type 16, 23 bytes
Physical Memory Array
\tLocation: System Board Or Motherboard
\tUse: System Memory
\tMaximum Capacity: 32 GB
\tNumber Of Devices: 2

Handle 0x0011, DMI type 17, 40 bytes
Memory Device
\tArray Handle: 0x0010
\tSize: 8 GB
\tForm Factor: SODIMM
\tLocator: DIMM A
\tType: DDR4

Handle 0x0012, DMI type 17, 40 bytes
Memory Device
\tArray Handle: 0x0010
\tSize: No Module Installed
\tForm Factor: Unknown
\tLocator: DIMM B
\tType: Unknown
"""


class TestLaMemoireVive(Banc):
    def test_a_virtual_machine_reads_nothing(self):
        etat = self.etat(virtualization="kvm")
        self.lancer("_system_swap_memoire", etat, [])
        self.assertIn("Machine virtuelle (kvm)", self.texte())

    def test_dmidecode_runs_with_sudo_after_a_yes(self):
        etat = self.etat()
        sortie = mock.Mock(returncode=0, stdout=DMIDECODE)
        with (
            mock.patch.object(ss, "plan_installer_dmidecode", return_value=[]),
            mock.patch.object(
                sm.subprocess, "run", return_value=sortie
            ) as run,
        ):
            self.lancer("_system_swap_memoire", etat, ["o"])
        self.assertEqual(
            run.call_args.args[0], ["sudo", "dmidecode", "-t", "memory"]
        )
        self.assertIn("Oui : 1 emplacement(s) libre(s) sur 2", self.texte())
        self.assertIn("24.0 Gio de plus", self.texte())

    def test_no_yes_no_sudo(self):
        etat = self.etat()
        with mock.patch.object(
            ss, "plan_installer_dmidecode", return_value=[]
        ):
            self.lancer("_system_swap_memoire", etat, ["n"])
        self.assertIn("sans dmidecode", self.texte())

    def test_a_missing_dmidecode_is_installed_first(self):
        etat = self.etat()
        plan = [["sudo", "pacman", "-S", "--needed", "dmidecode"]]
        sortie = mock.Mock(returncode=0, stdout=DMIDECODE)
        with (
            mock.patch.object(
                ss, "plan_installer_dmidecode", return_value=plan
            ),
            mock.patch.object(sm.subprocess, "run", return_value=sortie),
        ):
            self.lancer("_system_swap_memoire", etat, ["o", "o"])
        self.assertEqual(self.lances(), ["sudo pacman -S --needed dmidecode"])
        self.assertIn("Oui :", self.texte())

    def test_a_failed_install_reads_nothing(self):
        etat = self.etat()
        self.todo.execute.exec_command_live.return_value = 1
        plan = [["sudo", "pacman", "-S", "--needed", "dmidecode"]]
        with mock.patch.object(
            ss, "plan_installer_dmidecode", return_value=plan
        ):
            self.lancer("_system_swap_memoire", etat, ["o"])
        self.assertIn("L'installation a échoué", self.texte())
        self.assertIn("sans dmidecode", self.texte())


if __name__ == "__main__":
    unittest.main()
