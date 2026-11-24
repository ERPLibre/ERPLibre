#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Mémoire Swap : l'état en lignes, les phrases des refus, le
protocole des plans (rien sans oui, arrêt au premier échec), le choix du
swap à modifier.

L'état est fabriqué et system_swap.etat() le rend tel quel ; les commandes
passent par un execute factice et subprocess.run est remplacé : un test ne
lit rien de la machine qui le lance et n'exécute rien.
"""

import ast
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
        self.assertIn("[3] ⬇", invite.call_args.args[0])


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
            "resume",
            "subvolume",
            "virtualization",
        }
        for table in (sm.RAISONS_SWAP, sm.ALERTES_SWAP):
            for cle in table.values():
                champs = {
                    f for _l, f, _s, _c in string.Formatter().parse(cle) if f
                }
                self.assertLessEqual(champs, connus, cle)


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

    def plan_a_deux(self):
        return ss._resultat(
            True,
            plan=[
                ["sudo", "mkswap", "/swapfile"],
                ["sudo", "swapon", "/swapfile"],
            ],
        )

    def test_nothing_runs_without_a_yes(self):
        res = self.plan_a_deux()
        for reponse in ("", "n"):
            self.assertFalse(
                self.lancer(
                    "_system_swap_appliquer", self.etat(), [reponse], res
                )
            )
        self.assertEqual(self.lances(), [])
        self.assertIn("Va exécuter : sudo swapon /swapfile", self.texte())

    def test_the_commands_run_one_by_one_after_a_yes(self):
        res = self.plan_a_deux()
        self.assertTrue(
            self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        )
        self.assertEqual(
            self.lances(), ["sudo mkswap /swapfile", "sudo swapon /swapfile"]
        )
        for appel in self.todo.execute.exec_command_live.call_args_list:
            self.assertIs(appel.kwargs["source_erplibre"], False)
        self.assertIn("✓ Terminé.", self.texte())
        self.assertIn("── Swaps actifs ──", self.texte())

    def test_the_first_failure_stops_the_plan(self):
        res = self.plan_a_deux()
        self.todo.execute.exec_command_live.return_value = 1
        self.assertFalse(
            self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        )
        self.assertEqual(len(self.lances()), 1)
        texte = self.texte()
        self.assertIn("⚠ Commande en échec : sudo mkswap", texte)
        # La commande en échec n'est pas comptée parmi celles qui ne sont
        # pas lancées ; la suivante l'est.
        apres = texte.split("Non lancées :", 1)[1]
        self.assertIn("sudo swapon /swapfile", apres)
        self.assertNotIn("sudo mkswap", apres.split("──", 1)[0])
        self.assertNotIn("✓ Terminé.", texte)

    def test_the_state_is_read_again_after_a_sync(self):
        """btrfs publie l'espace d'un fichier créé à la validation de sa
        transaction : le sync précède la relecture de l'état."""
        res = self.plan_a_deux()
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
        res = self.plan_a_deux()
        self.todo.execute.exec_command_live.side_effect = [0, 1]
        self.lancer("_system_swap_appliquer", self.etat(), ["o"], res)
        self.assertIn("⚠ Commande en échec : sudo swapon", self.texte())
        self.assertNotIn("Non lancées", self.texte())

    def test_ctrl_c_stops_the_plan_and_shows_the_state(self):
        """Un Ctrl-C pendant une commande arrête le plan comme un échec :
        il ne sort pas de TODO, et l'état relu s'affiche."""
        res = self.plan_a_deux()
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
        self.assertEqual(self.lances(), [])
        self.assertEqual(self.texte().count("Conteneur (lxc)"), 1)

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


if __name__ == "__main__":
    unittest.main()
