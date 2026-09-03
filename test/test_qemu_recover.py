#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Récupérer des fichiers dans le disque d'une VM, sans la démarrer.

Une VM qui ne démarre plus garde ses fichiers, et libguestfs sait monter son
qcow2 sans elle. Le risque n'est pas la lecture : c'est d'ouvrir en ÉCRITURE
le disque d'une machine allumée, ce qui corrompt son système de fichiers.

Ce que ces tests gardent :

- « --ro » sur CHAQUE commande, sans exception : c'est lui qui rend l'opération
  sûre sur une VM en marche ;
- le nom du paquet suit la distribution — celui de Debian n'existe nulle part
  ailleurs ;
- les chemins saisis par l'utilisateur sont échappés avant d'atteindre le
  shell.
"""

import re
import shlex
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_recover as qr  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

DISQUE = "/var/lib/libvirt/images/vm-a.qcow2"


class LesOutils(unittest.TestCase):
    def test_each_package_manager_gets_its_own_name(self):
        """« libguestfs-tools » est le nom Debian : il n'existe ni sur Arch,
        ni sur Fedora, ni sur openSUSE."""
        attendu = {
            "apt-get": "libguestfs-tools",
            "dnf": "guestfs-tools",
            "pacman": "libguestfs",
            "zypper": "guestfs-tools",
        }
        for binaire, paquet in attendu.items():
            with self.subTest(binaire=binaire):
                with mock.patch.object(
                    qr.shutil,
                    "which",
                    side_effect=lambda b, cible=binaire: (
                        "/usr/bin/x" if b == cible else None
                    ),
                ):
                    cmd, nom = qr.guestfs_install_cmd()
                self.assertEqual(paquet, nom)
                self.assertIn(paquet, cmd)

    def test_an_unknown_host_proposes_nothing(self):
        """Proposer une commande qui échouera vaut moins que de dire qu'on ne
        sait pas — sur macOS, libguestfs ne tourne pas."""
        with mock.patch.object(qr.shutil, "which", return_value=None):
            self.assertEqual((None, None), qr.guestfs_install_cmd())


class LaLectureEstToujoursSeule(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_every_command_carries_read_only(self):
        """Sans « --ro », ouvrir le disque d'une VM allumée corrompt son
        système de fichiers. Aucune commande n'a de raison de s'en passer."""
        cmds = [
            self.todo._qemu_guestfish_cmd(DISQUE),
            self.todo._qemu_guestfish_cmd(DISQUE, "run", "list-filesystems"),
            self.todo._qemu_guestfish_cmd(
                DISQUE, "run", "mount /dev/sda3 /", "ls /home"
            ),
        ]
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                self.assertIn("--ro", cmd)
                self.assertIn(shlex.quote(DISQUE), cmd)

    def test_the_commands_are_chained_the_guestfish_way(self):
        cmd = self.todo._qemu_guestfish_cmd(
            DISQUE, "run", "mount /dev/sda3 /", "ls /home"
        )
        self.assertIn("run : mount /dev/sda3 / : ls /home", cmd)

    def test_a_hostile_path_cannot_escape_the_shell(self):
        """Le chemin vient de l'utilisateur : sans échappement, « ; » ouvre
        une seconde commande."""
        cmd = self.todo._qemu_guestfish_cmd("/tmp/x.qcow2; rm -rf /", "run")
        # Le chemin entier tient dans UNE apostrophe : le « ; » y est du
        # texte, pas un séparateur de commande.
        self.assertIn("'/tmp/x.qcow2; rm -rf /'", cmd)
        self.assertNotIn(
            "qcow2; rm", cmd.replace("'/tmp/x.qcow2; rm -rf /'", "")
        )


class LaVmAllumee(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_a_stopped_vm_goes_straight_through(self):
        self.todo._qemu_domstate = lambda n: "shut off"
        self.assertTrue(self.todo._qemu_recover_ready("vm-a"))

    def test_a_running_vm_offers_three_ways(self):
        self.todo._qemu_domstate = lambda n: "running"
        vus = {}

        def faux_pick(titre, valeurs, defaut, labels=None):
            vus["valeurs"] = valeurs
            vus["defaut"] = defaut
            return "read"

        self.todo._qemu_pick = faux_pick
        with mock.patch("builtins.print"):
            self.assertTrue(self.todo._qemu_recover_ready("vm-a"))
        self.assertEqual(["read", "shutdown", "cancel"], vus["valeurs"])
        # L'arrêt propre est le défaut : c'est la seule voie qui donne une
        # copie fidèle.
        self.assertEqual("shutdown", vus["defaut"])

    def test_cancelling_stops_everything(self):
        self.todo._qemu_domstate = lambda n: "running"
        self.todo._qemu_pick = lambda *a, **k: "cancel"
        with mock.patch("builtins.print"):
            self.assertFalse(self.todo._qemu_recover_ready("vm-a"))

    def test_choosing_shutdown_waits_for_it(self):
        self.todo._qemu_domstate = lambda n: "running"
        self.todo._qemu_pick = lambda *a, **k: "shutdown"
        appels = []
        self.todo._qemu_shutdown_wait = lambda n: appels.append(n) or True
        with mock.patch("builtins.print"):
            self.assertTrue(self.todo._qemu_recover_ready("vm-a"))
        self.assertEqual(["vm-a"], appels)


class LExtraction(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.lances = []
        self.todo.execute = mock.MagicMock()
        self.todo.execute.exec_command_live.side_effect = (
            lambda cmd, **k: self.lances.append(cmd) or 0
        )

    def test_copy_out_names_both_ends(self):
        with mock.patch.object(qr.os, "makedirs"), mock.patch(
            "builtins.print"
        ):
            ok = self.todo._qemu_recover_copy_out(
                DISQUE, "/dev/sda3", "/home/erplibre", "/tmp/vm-a-backup"
            )
        self.assertTrue(ok)
        cmd = self.lances[0]
        self.assertIn("copy-out /home/erplibre /tmp/vm-a-backup", cmd)
        self.assertIn("mount /dev/sda3 /", cmd)
        self.assertIn("--ro", cmd)

    def test_an_uncreatable_destination_stops_before_running(self):
        """guestfish s'arrêterait sur une erreur qui ne dit pas laquelle des
        deux extrémités manque."""
        with mock.patch.object(
            qr.os, "makedirs", side_effect=OSError("lecture seule")
        ), mock.patch("builtins.print"):
            ok = self.todo._qemu_recover_copy_out(
                DISQUE, "/dev/sda3", "/home", "/interdit"
            )
        self.assertFalse(ok)
        self.assertEqual([], self.lances)


class LesDiagnostics(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.lances = []
        self.todo.execute = mock.MagicMock()
        self.todo.execute.exec_command_live.side_effect = (
            lambda cmd, **k: self.lances.append(cmd) or 0
        )

    def test_the_four_probes_answer_four_questions(self):
        with mock.patch("builtins.print"):
            self.todo._qemu_recover_diagnostics(DISQUE)
        joint = " ".join(self.lances)
        for attendu in (
            "virt-filesystems",
            "virt-df",
            "inspect-os",
            "libguestfs-test-tool",
        ):
            self.assertIn(attendu, joint)

    def test_no_diagnostic_writes_to_the_disk(self):
        with mock.patch("builtins.print"):
            self.todo._qemu_recover_diagnostics(DISQUE)
        for cmd in self.lances:
            if "guestfish" in cmd:
                self.assertIn("--ro", cmd)


class LeMenu(unittest.TestCase):
    def test_the_entry_is_wired_in_the_manage_section(self):
        from pathlib import Path

        source = Path("script/todo/qemu_menu.py").read_text(encoding="utf-8")
        self.assertIn("Recover files from a VM disk (libguestfs)", source)
        self.assertIn("self._qemu_recover_files()", source)

    def test_the_config_entry_still_reaches_its_command(self):
        """L'entrée du catalogue vient de todo.json : elle n'a pas de branche
        « elif » et dépend du repli par indice. Insérer une entrée codée en
        dur la décale, et un décalage manqué lancerait la mauvaise. Le numéro
        se lit sur le menu rendu plutôt qu'écrit ici en dur."""
        from unittest import mock as m

        from script.todo.todo_i18n import set_lang

        set_lang("fr")
        todo = TODO()
        todo._menu_header = lambda: "x"
        lancees = []
        todo.execute_from_configuration = lambda e: lancees.append(e)
        # Le numéro se DÉDUIT du menu : l'entrée de config est la dernière
        # des entrées numérotées. L'écrire en dur ferait passer le test au
        # premier réarrangement de sections, sans rien prouver.
        with m.patch("script.todo.qemu_menu.click") as click, m.patch.object(
            todo, "_qemu_ensure_tools", return_value=True
        ), m.patch("builtins.print"):
            click.prompt.side_effect = ["0"]
            todo.prompt_execute_qemu()
            aide = click.prompt.call_args[0][0]
        numeros = re.findall(r"^\[(\d+)\]", aide, re.M)
        dernier = max(int(n) for n in numeros)
        with m.patch("script.todo.qemu_menu.click") as click, m.patch.object(
            todo, "_qemu_ensure_tools", return_value=True
        ), m.patch("builtins.print"):
            click.prompt.side_effect = [str(dernier), "0"]
            todo.prompt_execute_qemu()
        self.assertEqual(1, len(lancees), lancees)
        self.assertIn("dry-run", lancees[0].get("bash_command", ""))

    def test_the_branches_stay_in_order_and_unique(self):
        """Insérer une entrée décale tout ce qui suit : un numéro en double
        rendrait une commande inatteignable."""
        import re
        from pathlib import Path

        source = Path("script/todo/qemu_menu.py").read_text(encoding="utf-8")
        debut = source.index("def prompt_execute_qemu")
        corps = source[debut : source.index("\n    def ", debut + 10)]
        nums = [int(n) for n in re.findall(r'status == "(\d+)"', corps)]
        self.assertEqual(sorted(nums), nums, nums)
        self.assertEqual(len(set(nums)), len(nums), nums)


if __name__ == "__main__":
    unittest.main()
