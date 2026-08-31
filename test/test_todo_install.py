#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La composante d'installation partagée : familles, noms, ordre de décision.

Trois écritures séparées faisaient ce travail avant, chacune couvrant un
sous-ensemble différent : on pouvait installer virt-viewer sous openSUSE, mais
ni navigateur CLI ni lm-sensors. Ce qui se garde ici est donc surtout de la
COUVERTURE — qu'aucune famille ne retombe dans le trou — plus les deux règles
que la composante tient à la place des appelants : l'ID de la distribution
décide avant le PATH, et la commande s'affiche avant la question.

Rien n'est installé : le PATH et /etc/os-release sont simulés.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import mock_open, patch

sys.argv = ["todo.py"]
from script.todo import todo_install  # noqa: E402


def _only(*present):
    """shutil.which qui ne trouve que `present`."""
    return lambda b: f"/usr/bin/{b}" if b in present else None


class TestFamilyDetection(unittest.TestCase):
    def test_every_family_has_a_non_interactive_command(self):
        """Un menu qui rend la main à un prompt apt reste bloqué."""
        for famille in todo_install.FAMILIES:
            cmd = todo_install.install_command(["p"], famille=famille)
            self.assertEqual(cmd[0], "sudo")
            self.assertEqual(cmd[-1], "p")
            self.assertTrue(
                {"-y", "--noconfirm", "--non-interactive"} & set(cmd),
                f"{famille} : commande interactive {cmd}",
            )

    def test_the_distribution_id_decides_before_the_path(self):
        """Une machine peut porter deux gestionnaires ; l'ID dit lequel
        possède le système."""
        with patch(
            "builtins.open", mock_open(read_data='ID="debian"\n')
        ), patch(
            "script.todo.todo_install.shutil.which", _only("apt-get", "dnf")
        ):
            self.assertEqual(todo_install.family(), "apt-get")

    def test_the_path_decides_when_the_id_is_unknown(self):
        with patch(
            "builtins.open", mock_open(read_data='ID="nonesuch"\n')
        ), patch("script.todo.todo_install.shutil.which", _only("zypper")):
            self.assertEqual(todo_install.family(), "zypper")

    def test_an_id_whose_manager_is_absent_falls_back(self):
        """Un conteneur Debian minimal sans apt-get ne doit pas mener à une
        commande apt-get qui n'existe pas."""
        with patch(
            "builtins.open", mock_open(read_data='ID="debian"\n')
        ), patch("script.todo.todo_install.shutil.which", _only("dnf")):
            self.assertEqual(todo_install.family(), "dnf")

    def test_no_manager_is_none_not_a_guess(self):
        with patch("builtins.open", mock_open(read_data="")), patch(
            "script.todo.todo_install.shutil.which", _only()
        ):
            self.assertIsNone(todo_install.family())
            self.assertIsNone(todo_install.install_command(["p"]))

    def test_the_four_supported_families_are_all_mapped(self):
        """Les plateformes annoncées par le dépôt doivent toutes tomber sur
        une famille, sans quoi l'installation leur est fermée."""
        for os_id, attendu in (
            ("ubuntu", "apt-get"),
            ("linuxmint", "apt-get"),
            ("debian", "apt-get"),
            ("almalinux", "dnf"),
            ("rocky", "dnf"),
            ("opensuse-leap", "zypper"),
            ("opensuse-tumbleweed", "zypper"),
            ("arch", "pacman"),
        ):
            with patch(
                "builtins.open", mock_open(read_data=f'ID="{os_id}"\n')
            ), patch(
                "script.todo.todo_install.shutil.which",
                _only(*todo_install.FAMILIES),
            ):
                self.assertEqual(todo_install.family(), attendu, os_id)


class TestPackageNames(unittest.TestCase):
    def test_a_dict_picks_the_name_of_the_current_family(self):
        """lm-sensors chez Debian, lm_sensors ailleurs."""
        noms = {
            "apt-get": ["lm-sensors"],
            "dnf": ["lm_sensors"],
            "pacman": ["lm_sensors"],
            "zypper": ["sensors"],
        }
        for famille, attendu in (
            ("apt-get", "lm-sensors"),
            ("dnf", "lm_sensors"),
            ("zypper", "sensors"),
        ):
            cmd = todo_install.install_command(noms, famille=famille)
            self.assertEqual(cmd[-1], attendu)

    def test_a_family_absent_from_the_dict_installs_nothing(self):
        """Mieux vaut rien proposer qu'un paquet qui n'existe pas ici."""
        self.assertIsNone(
            todo_install.install_command({"apt-get": ["p"]}, famille="pacman")
        )

    def test_resolve_maps_binaries_and_deduplicates(self):
        paquets, inconnus = todo_install.resolve(
            ["e2fsck", "resize2fs", "sgdisk"],
            commun={"e2fsck": "e2fsprogs", "resize2fs": "e2fsprogs"},
            par_famille={"pacman": {"sgdisk": "gptfdisk"}},
            famille="pacman",
        )
        self.assertEqual(paquets, ["e2fsprogs", "gptfdisk"])
        self.assertEqual(inconnus, [])

    def test_resolve_says_what_it_cannot_map(self):
        """À dire, jamais à deviner : un nom inventé installerait au hasard."""
        paquets, inconnus = todo_install.resolve(
            ["sgdisk"], commun={}, par_famille={}, famille="apt-get"
        )
        self.assertEqual(paquets, [])
        self.assertEqual(inconnus, ["sgdisk"])


class TestAskAndInstall(unittest.TestCase):
    class _Exec:
        def __init__(self, status=0):
            self.ran, self.status = [], status

        def exec_command_live(self, cmd, source_erplibre=False):
            self.ran.append(cmd)
            return self.status

    def _play(self, cmd, answer, status=0):
        ex = self._Exec(status)
        buf = io.StringIO()

        def demande(invite=""):
            print(invite, end="")
            return answer

        with patch("builtins.input", demande), redirect_stdout(buf):
            got = todo_install.ask_and_install(
                ex, cmd, "Installer? (y/N): ", lambda a: a.strip() == "y"
            )
        return ex.ran, got, buf.getvalue()

    def test_the_command_is_printed_before_the_question(self):
        """Centralisé ici pour qu'aucun appelant ne puisse l'inverser."""
        ran, got, out = self._play(
            ["sudo", "apt-get", "install", "-y", "p"], "n"
        )
        self.assertLess(
            out.index("sudo apt-get install -y p"),
            out.index("Installer? (y/N): "),
        )
        self.assertEqual(ran, [])
        self.assertIsNone(got)

    def test_accepting_runs_it_and_gives_the_exit_code_back(self):
        """exec_command_live REND le code, il ne lève rien : l'appelant doit
        pouvoir le tester."""
        ran, got, _ = self._play(["sudo", "dnf", "install", "-y", "p"], "y")
        self.assertEqual(ran, ["sudo dnf install -y p"])
        self.assertEqual(got, 0)
        ran, got, _ = self._play(
            ["sudo", "dnf", "install", "-y", "p"], "y", status=127
        )
        self.assertEqual(got, 127)

    def test_no_command_is_said_not_silently_skipped(self):
        ran, got, out = self._play(None, "y")
        self.assertEqual(ran, [])
        self.assertIsNone(got)
        self.assertTrue(out.strip())

    def test_a_name_with_a_space_survives_the_display(self):
        """shlex.join, pour que la commande affichée soit celle qui tourne."""
        ran, _, out = self._play(
            ["sudo", "apt-get", "install", "-y", "a b"], "y"
        )
        self.assertIn("'a b'", out)
        self.assertIn("'a b'", ran[0])


if __name__ == "__main__":
    unittest.main()
