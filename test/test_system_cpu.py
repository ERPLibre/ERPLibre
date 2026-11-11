#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire CPU par processus : choisir top, htop, btop ou glances,
l'installer selon le système, puis le lancer.

/etc/os-release et le PATH sont fabriqués, subprocess.run est remplacé :
un test n'installe ni ne lance rien.
"""

import ast
import inspect
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_cpu as sc  # noqa: E402
from script.todo import system_menu as sm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

OS_RELEASE = {
    "debian": 'ID=debian\nNAME="Debian GNU/Linux"\n',
    "ubuntu": "ID=ubuntu\nID_LIKE=debian\n",
    "fedora": "ID=fedora\n",
    "rocky": 'ID="rocky"\nID_LIKE="rhel centos fedora"\n',
    "almalinux": 'ID="almalinux"\nID_LIKE="rhel centos fedora"\n',
    "opensuse": 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
    "arch": "ID=arch\n",
    "nixos": "ID=nixos\n",
    "proxmox": "ID=debian\n",
}

BINAIRE = {
    "debian": "apt-get",
    "ubuntu": "apt-get",
    "proxmox": "apt-get",
    "fedora": "dnf",
    "rocky": "dnf",
    "almalinux": "dnf",
    "opensuse": "zypper",
    "arch": "pacman",
    "nixos": "nix-shell",
}


def systeme(test, distro):
    """Écrit le /etc/os-release de `distro` ; rend (chemin, patch) où le
    patch ne laisse dans le PATH que son gestionnaire de paquets."""
    chemin = os.path.join(test.tmp.name, "os-release")
    with open(chemin, "w") as fh:
        fh.write(OS_RELEASE[distro])
    patch = mock.patch.object(
        sc.shutil,
        "which",
        side_effect=lambda b: (
            f"/usr/bin/{b}" if b == BINAIRE[distro] else None
        ),
    )
    return chemin, patch


class TestLesPlans(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def plan(self, distro, outil):
        chemin, patch = systeme(self, distro)
        with patch:
            return sc.plan_installation(outil, chemin)

    def test_each_family_uses_its_package_manager(self):
        attendu = {
            "debian": ["sudo", "apt-get", "install", "-y", "htop"],
            "ubuntu": ["sudo", "apt-get", "install", "-y", "htop"],
            "proxmox": ["sudo", "apt-get", "install", "-y", "htop"],
            "rocky": ["sudo", "dnf", "install", "-y", "htop"],
            "fedora": ["sudo", "dnf", "install", "-y", "htop"],
            "arch": [
                "sudo",
                "pacman",
                "-S",
                "--needed",
                "--noconfirm",
                "htop",
            ],
            "opensuse": [
                "sudo",
                "zypper",
                "--non-interactive",
                "install",
                "htop",
            ],
        }
        for distro, commande in attendu.items():
            with self.subTest(distro=distro):
                self.assertEqual(self.plan(distro, "htop")[-1], commande)

    def test_apt_refreshes_its_index_first(self):
        self.assertEqual(
            self.plan("debian", "htop")[0], ["sudo", "apt-get", "update"]
        )
        self.assertEqual(len(self.plan("arch", "htop")), 1)

    def test_the_distribution_wins_over_a_foreign_binary(self):
        """Arch empaquète apt et dnf : leur présence ne change pas de
        gestionnaire."""
        chemin, _ = systeme(self, "arch")
        with mock.patch.object(
            sc.shutil, "which", side_effect=lambda b: f"/usr/bin/{b}"
        ):
            self.assertEqual(sc.gestionnaire(chemin), "pacman")
        chemin, _ = systeme(self, "opensuse")
        with mock.patch.object(
            sc.shutil, "which", side_effect=lambda b: f"/usr/bin/{b}"
        ):
            self.assertEqual(sc.gestionnaire(chemin), "zypper")

    def test_an_unknown_distribution_falls_back_to_the_binary(self):
        chemin = os.path.join(self.tmp.name, "os-release")
        with open(chemin, "w") as fh:
            fh.write("ID=inconnue\n")
        with mock.patch.object(
            sc.shutil,
            "which",
            side_effect=lambda b: "/usr/bin/dnf" if b == "dnf" else None,
        ):
            self.assertEqual(sc.gestionnaire(chemin), "dnf")

    def test_enterprise_linux_needs_epel_first(self):
        for distro in ("rocky", "almalinux"):
            with self.subTest(distro=distro):
                plan = self.plan(distro, "btop")
                self.assertEqual(plan[0][-1], "epel-release")
                self.assertEqual(plan[1][-1], "btop")

    def test_top_comes_from_procps_without_epel(self):
        self.assertEqual(self.plan("rocky", "top")[-1][-1], "procps-ng")
        self.assertEqual(len(self.plan("rocky", "top")), 1)

    def test_nixos_installs_nothing_and_runs_in_a_nix_shell(self):
        chemin, patch = systeme(self, "nixos")
        with patch:
            self.assertEqual(sc.gestionnaire(chemin), "nix")
            self.assertEqual(sc.plan_installation("htop", chemin), [])
        self.assertEqual(
            sc.commande_nix("htop"),
            [
                "nix-shell",
                "-p",
                "htop",
                "--run",
                "htop --sort-key PERCENT_MEM",
            ],
        )
        self.assertEqual(sc.commande_nix("top")[-1], "top -o %MEM")

    def test_unknown_system_gives_no_plan(self):
        with mock.patch.object(sc.shutil, "which", return_value=None):
            self.assertIsNone(sc.gestionnaire("/nulle/part"))
            self.assertEqual(sc.plan_installation("htop", "/nulle/part"), [])


class TestLeMenu(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(
        self,
        reponses,
        installes=("top",),
        gestion="pacman",
        plan=None,
        retours=(),
        apres_installation=(),
    ):
        """Le menu avec `reponses` au clavier ; rend les commandes passées à
        subprocess.run et ce qui a été affiché."""
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        etats = [installes, tuple(installes) + tuple(apres_installation)]

        def etat():
            presents = etats.pop(0) if len(etats) > 1 else etats[0]
            return [
                {
                    "nom": nom,
                    "chemin": f"/usr/bin/{nom}" if nom in presents else None,
                    "args": args,
                    "touche": touche,
                }
                for nom, _, args, touche in sc.OUTILS
            ]

        vus = []
        codes = list(retours)
        with (
            mock.patch.object(sc, "etat", side_effect=etat),
            mock.patch.object(sc, "gestionnaire", return_value=gestion),
            mock.patch.object(
                sc,
                "plan_installation",
                return_value=(
                    plan
                    if plan is not None
                    else [["sudo", "pacman", "-S", "x"]]
                ),
            ),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: vus.append(" ".join(map(str, a))),
            ),
            mock.patch.object(
                sm.subprocess,
                "run",
                side_effect=lambda c: subprocess.CompletedProcess(
                    c, codes.pop(0) if codes else 0
                ),
            ) as run,
        ):
            todo._system_cpu()
        return [c.args[0] for c in run.call_args_list], "\n".join(vus)

    def test_an_installed_tool_runs_sorted_by_memory(self):
        lances, _ = self.lancer(["2"], installes=("top", "htop"))
        self.assertEqual(
            lances, [["/usr/bin/htop", "--sort-key", "PERCENT_MEM"]]
        )

    def test_enter_runs_nothing(self):
        self.assertEqual(self.lancer([""])[0], [])
        self.assertEqual(self.lancer(["9"])[0], [])

    def test_a_missing_tool_is_installed_only_after_a_yes(self):
        lances, vu = self.lancer(["3", "n"])
        self.assertEqual(lances, [])
        self.assertIn("sudo pacman -S x", vu)

    def test_installed_then_launched(self):
        lances, _ = self.lancer(["3", "o"], apres_installation=("btop",))
        self.assertEqual(
            lances, [["sudo", "pacman", "-S", "x"], ["/usr/bin/btop"]]
        )

    def test_a_failed_install_launches_nothing(self):
        lances, vu = self.lancer(["4", "o"], retours=[1])
        self.assertEqual(lances, [["sudo", "pacman", "-S", "x"]])
        self.assertIn("L'installation a échoué", vu)
        self.assertIn("pacman -Syu", vu)

    def test_enterprise_plan_runs_every_step(self):
        plan = [
            ["sudo", "dnf", "install", "-y", "epel-release"],
            ["sudo", "dnf", "install", "-y", "glances"],
        ]
        lances, _ = self.lancer(
            ["4", "o"],
            gestion="dnf",
            plan=plan,
            apres_installation=("glances",),
        )
        self.assertEqual(lances, plan + [["/usr/bin/glances"]])

    def test_nixos_runs_in_a_nix_shell(self):
        lances, vu = self.lancer(["2"], gestion="nix", installes=())
        self.assertEqual(lances[0][:3], ["nix-shell", "-p", "htop"])
        self.assertIn("nix-shell", vu)

    def test_unknown_system_says_so(self):
        lances, vu = self.lancer(["2"], gestion=None, plan=[])
        self.assertEqual(lances, [])
        self.assertIn("gestionnaire de paquets inconnu", vu)

    def test_every_message_is_translated(self):
        cles = []
        for methode in (
            sm.SystemMenuMixin._system_cpu,
            sm.SystemMenuMixin._system_cpu_installer,
        ):
            arbre = ast.parse(textwrap.dedent(inspect.getsource(methode)))
            cles += [
                n.args[0].value
                for n in ast.walk(arbre)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "t"
                and isinstance(n.args[0], ast.Constant)
            ]
        self.assertTrue(cles)
        for cle in cles + ["CPU memory per process"]:
            self.assertIn(cle, todo_i18n.TRANSLATIONS, cle)

    def test_entry_7_opens_cpu_memory(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(TODO, "_system_cpu") as cpu,
            mock.patch("click.prompt", side_effect=["7", "0"]),
            mock.patch("builtins.print"),
        ):
            todo.prompt_execute_system()
        cpu.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
