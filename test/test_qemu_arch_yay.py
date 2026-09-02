#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'invité Arch : yay et bash-completion, puis leur trace dans l'accueil.

Une image cloud Arch est nue : ni bash-completion, ni accès à l'AUR. Les deux
s'ajoutent à l'amorçage d'installation, sur la seule branche pacman.

Ce que ces tests gardent :

- makepkg REFUSE de construire en root : la construction ne passe jamais par
  sudo, et un « sudo makepkg » repasserait le test au rouge.
- yay est un bonus : sous « set -e », son échec ne doit pas emporter une
  installation par ailleurs complète.
- L'accueil de session n'annonce yay que sur une VM qui l'aura vraiment —
  la règle déjà tenue par le bloc ERPLibre, appliquée au même signal.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class ArchGuestBootstrap(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, False, "", "deb", ()
        )

    def test_bash_completion_rides_the_pacman_branch(self):
        self.assertIn("bash-completion", self.cmd)
        # Sur la branche pacman et nulle part ailleurs : les images Debian et
        # Fedora l'embarquent déjà, l'ajouter là serait du bruit.
        pacman = self.cmd.index("command -v pacman")
        zypper = self.cmd.index("command -v zypper", pacman)
        self.assertIn("bash-completion", self.cmd[pacman:zypper])

    def test_yay_is_installed_from_the_prebuilt_package(self):
        """yay-bin plutôt que yay : le paquet source compile Go, et le
        compilateur avec, pour le même outil."""
        self.assertIn("aur.archlinux.org/yay-bin.git", self.cmd)

    def test_makepkg_never_runs_under_sudo(self):
        """makepkg sort en erreur sous root : « running makepkg as root is
        not allowed ». La construction reste sous l'utilisateur de la VM."""
        yay = self.todo._qemu_yay_install_cmd()
        self.assertIn("makepkg -si --noconfirm", yay)
        self.assertNotIn("sudo makepkg", yay)

    def test_a_failing_aur_does_not_break_the_chain(self):
        """Sous « set -e », un groupe qui échoue arrête tout. Le bloc doit
        rendre 0 même sans réseau, sans quoi une VM par ailleurs installée
        serait comptée en échec."""
        yay = self.todo._qemu_yay_install_cmd()
        script = "set -e\nPATH=/nonexistent\n" + yay + "\necho SURVECU"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".sh", delete=False
        ) as fh:
            fh.write(script)
            chemin = fh.name
        res = subprocess.run(
            ["bash", chemin], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SURVECU", res.stdout)

    def test_the_whole_remote_command_is_valid_shell(self):
        """Une erreur de syntaxe ne se verrait qu'une fois la VM déployée."""
        res = subprocess.run(
            ["bash", "-n"],
            input=self.cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(res.returncode, 0, res.stderr)


class AurInTheMotd(unittest.TestCase):
    def test_arch_with_an_install_announces_yay(self):
        motd = DQ.build_motd(
            "arch", "latest", "amd64", "fr", "~/git/erplibre", "install", "vi"
        )
        self.assertIn("AUR — yay", motd)
        self.assertIn("yay -Syu", motd)

    def test_arch_without_an_install_announces_nothing(self):
        motd = DQ.build_motd("arch", "latest", "amd64", "fr")
        self.assertNotIn("yay", motd)

    def test_another_distro_never_gets_the_block(self):
        for distro, version in (
            ("ubuntu", "24.04"),
            ("debian", "13"),
            ("fedora", "43"),
            ("opensuse", "tumbleweed"),
        ):
            with self.subTest(distro=distro):
                motd = DQ.build_motd(
                    distro,
                    version,
                    "amd64",
                    "fr",
                    "~/git/erplibre",
                    "install",
                    "vi",
                )
                self.assertNotIn("yay", motd)

    def test_the_block_is_translated(self):
        motd = DQ.build_motd(
            "arch", "latest", "amd64", "en", "~/git/erplibre", "install", "vi"
        )
        self.assertIn("search the AUR", motd)
        self.assertNotIn("chercher dans l'AUR", motd)

    def test_the_block_stays_under_a_standard_terminal(self):
        for lang in ("fr", "en"):
            motd = DQ.build_motd(
                "arch",
                "latest",
                "amd64",
                lang,
                "~/git/erplibre",
                "install",
                "vi",
            )
            for line in motd.splitlines():
                self.assertLessEqual(len(line), 80, line)


if __name__ == "__main__":
    unittest.main()
