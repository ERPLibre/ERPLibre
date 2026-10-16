#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bloc qui installe le bureau d'une VM, exécuté contre de faux
gestionnaires de paquets.

Deux contrats se vérifient ici sans VM :

- le bloc rend NON NUL, sur une seule ligne claire, quand le bureau n'est pas
  là à la fin — un environnement dnf introuvable ou un téléchargement refusé
  ne laissent pas croire à un bureau installé ;
- sur la famille RHEL, EPEL est activé avant xrdp, et un xrdp que même EPEL
  ne porte pas coûte un avertissement, pas le bureau.

Le PATH ne contient QUE le répertoire des faux outils : un gnome-shell de
l'hôte qui exécute les tests ne doit pas répondre à la place de la VM.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

_FEDORA = 'ID=fedora\nVERSION_ID="42"\n'
_ALMA = 'ID="almalinux"\nID_LIKE="rhel centos fedora"\nVERSION_ID="10.1"\n'

# Faux dnf piloté par l'environnement :
#   DE_ENVS   environnements que « group install » sait installer
#   DE_NOSHELL  non vide : le groupe s'installe mais n'apporte pas le shell
#   XRDP_FROM « base » : xrdp est dans les dépôts de base ; « epel » : il
#             faut epel-release d'abord ; vide : aucun dépôt ne le porte
_FAKE_DNF = r"""#!/bin/bash
echo "dnf $*" >> "$LOG"
case "$*" in
  *"group install"*)
    e="${@: -1}"
    for ok in $DE_ENVS; do
      if [ "$ok" = "$e" ]; then
        [ -n "$DE_NOSHELL" ] || { printf '#!/bin/sh\n' > "$BIN/$SHELL_BIN"; chmod +x "$BIN/$SHELL_BIN"; }
        exit 0
      fi
    done
    echo "No match for argument: $e"; exit 1;;
  *"install -y epel-release"*)
    touch "$BIN/.epel"; exit 0;;
  *"config-manager"*) exit 0;;
  *"install -y xrdp"*)
    if [ "$XRDP_FROM" = base ] || { [ "$XRDP_FROM" = epel ] && [ -e "$BIN/.epel" ]; }; then
      printf '#!/bin/sh\n' > "$BIN/xrdp"; chmod +x "$BIN/xrdp"; exit 0
    fi
    echo "Error: Unable to find a match: xrdp"; exit 1;;
esac
exit 0
"""

_FAKE_APT = r"""#!/bin/bash
echo "apt-get $*" >> "$LOG"
case "$*" in
  *install*)
    [ -n "$DE_NOSHELL" ] || { printf '#!/bin/sh\n' > "$BIN/$SHELL_BIN"; chmod +x "$BIN/$SHELL_BIN"; }
    printf '#!/bin/sh\n' > "$BIN/xrdp"; chmod +x "$BIN/xrdp";;
esac
exit 0
"""


class _DesktopRun(unittest.TestCase):
    """Exécute le bloc du bureau avec « set -e », comme la commande distante."""

    flavour = "gnome"

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_desktop_remote_cmd(self.flavour, "deb")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = pathlib.Path(self.tmp) / "bin"
        self.bin.mkdir()
        self.log = pathlib.Path(self.tmp) / "calls.log"
        self.log.write_text("")
        for name, body in (
            # « sudo VAR=valeur commande » : l'affectation passe à
            # l'environnement, comme le fait le vrai sudo.
            (
                "sudo",
                "#!/bin/bash\n"
                'while [[ "$1" == *=* ]]; do export "$1"; shift; done\n'
                'exec "$@"\n',
            ),
            ("systemctl", '#!/bin/bash\necho "systemctl $*" >> "$LOG"\n'),
        ):
            self._tool(name, body)
        # Les seuls utilitaires externes que les branches dnf et apt
        # appellent, en plus des faux.
        for util in ("date", "sleep", "hostname", "awk", "cat", "touch"):
            real = shutil.which(util)
            if real:
                (self.bin / util).symlink_to(real)

    def _tool(self, name, body):
        p = self.bin / name
        p.write_text(body)
        p.chmod(0o755)

    def run_block(self, os_release=_FEDORA, **env):
        osr = pathlib.Path(self.tmp) / "os-release"
        osr.write_text(os_release)
        script = "set -e; " + self.cmd.replace("/etc/os-release", str(osr))
        shell_bin = self.todo._QEMU_DESKTOP[self.flavour]["probe"]
        full_env = {
            "PATH": str(self.bin),
            "HOME": self.tmp,
            "LOG": str(self.log),
            "BIN": str(self.bin),
            "SHELL_BIN": shell_bin,
            "DE_ENVS": "",
            "DE_NOSHELL": "",
            "XRDP_FROM": "base",
        }
        full_env.update(env)
        res = subprocess.run(
            [shutil.which("bash"), "-c", script],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=60,
        )
        return res, self.log.read_text()


class _DnfRun(_DesktopRun):
    """Le même banc, un faux dnf en plus : la VM est de la famille dnf."""

    def setUp(self):
        super().setUp()
        self._tool("dnf", _FAKE_DNF)


class TestTheBlockIsValidShell(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _bash_n(self, script):
        res = subprocess.run(
            ["bash", "-n"], input=script, capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_the_desktop_only_command_parses(self):
        """La commande du menu QEMU que le test long réutilise."""
        self._bash_n(
            self.todo._qemu_erplibre_remote_cmd(None, desktop="gnome")
        )

    def test_every_flavour_parses(self):
        for flavour in TODO._QEMU_DESKTOP:
            self._bash_n(self.todo._qemu_desktop_remote_cmd(flavour, "deb"))

    def test_every_flavour_names_its_probe(self):
        """La sonde est le binaire du bureau lui-même : un groupe de paquets
        peut réussir sans l'apporter."""
        self.assertEqual("gnome-shell", TODO._QEMU_DESKTOP["gnome"]["probe"])
        self.assertEqual("cinnamon", TODO._QEMU_DESKTOP["cinnamon"]["probe"])


class TestDnfDesktopFailsLoudly(_DnfRun):
    def test_the_fake_dnf_is_the_one_used(self):
        """Garde du banc : sans le faux dnf, ces tests ne prouvent rien."""
        _, calls = self.run_block(DE_ENVS="workstation-product-environment")
        self.assertIn("dnf -y group install", calls)

    def test_no_environment_installs_means_non_zero(self):
        """Tous les environnements de la cascade échouent — introuvables ou
        téléchargement refusé : le bloc s'arrête, il ne finit pas sur 0."""
        res, calls = self.run_block(DE_ENVS="")
        self.assertNotEqual(0, res.returncode, res.stdout)
        failures = [ln for ln in res.stdout.splitlines() if "✗" in ln]
        self.assertEqual(1, len(failures), res.stdout)
        self.assertIn("GNOME", failures[0])

    def test_it_stops_before_the_remote_access(self):
        """Sans bureau, installer xrdp ne sert à rien : l'échec arrive tôt."""
        _, calls = self.run_block(DE_ENVS="")
        self.assertNotIn("install -y xrdp", calls)
        self.assertNotIn("set-default graphical.target", calls)

    def test_a_group_without_the_shell_is_a_failure(self):
        """Le groupe dit avoir réussi, le binaire du bureau manque."""
        res, _ = self.run_block(
            DE_ENVS="workstation-product-environment", DE_NOSHELL="1"
        )
        self.assertNotEqual(0, res.returncode, res.stdout)
        self.assertIn("gnome-shell", res.stdout)

    def test_a_fedora_desktop_succeeds_without_epel(self):
        res, calls = self.run_block(DE_ENVS="workstation-product-environment")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertNotIn("epel-release", calls)
        self.assertIn("install -y xrdp", calls)
        self.assertIn("set-default graphical.target", calls)


class TestDnfRemoteAccessOnRhelFamily(_DnfRun):
    def test_epel_comes_before_xrdp(self):
        """xrdp n'est pas dans les dépôts de base d'AlmaLinux ni de Rocky."""
        res, calls = self.run_block(
            _ALMA, DE_ENVS="graphical-server-environment", XRDP_FROM="epel"
        )
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("install -y epel-release", calls)
        self.assertLess(
            calls.index("install -y epel-release"),
            calls.index("install -y xrdp"),
        )
        self.assertIn("RDP 3389", res.stdout)

    def test_xrdp_nowhere_is_a_warning_not_a_failure(self):
        """EPEL ne porte pas xrdp pour toutes les versions : le bureau reste
        installé, et une ligne le dit."""
        res, calls = self.run_block(
            _ALMA, DE_ENVS="graphical-server-environment", XRDP_FROM=""
        )
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        warnings = [
            ln for ln in res.stdout.splitlines() if "⚠" in ln and "xrdp" in ln
        ]
        self.assertEqual(1, len(warnings), res.stdout)
        self.assertIn("set-default graphical.target", calls)


class TestAptDesktopProbe(_DesktopRun):
    def setUp(self):
        super().setUp()
        self._tool("apt-get", _FAKE_APT)

    def test_an_installed_desktop_succeeds(self):
        res, _ = self.run_block()
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)

    def test_an_install_without_the_shell_fails(self):
        res, _ = self.run_block(DE_NOSHELL="1")
        self.assertNotEqual(0, res.returncode, res.stdout)
        self.assertIn("gnome-shell", res.stdout)


class TestCinnamonProbe(_DnfRun):
    flavour = "cinnamon"

    def test_cinnamon_is_probed_by_its_own_binary(self):
        res, _ = self.run_block(DE_ENVS="cinnamon-desktop", DE_NOSHELL="1")
        self.assertNotEqual(0, res.returncode, res.stdout)
        self.assertIn("cinnamon", res.stdout)
        self.assertNotIn("gnome-shell", res.stdout)


if __name__ == "__main__":
    unittest.main()
