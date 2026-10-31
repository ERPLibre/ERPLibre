#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""apt-get et dpkg sont lancés hors du terminal.

apt-get remet en fin de course les réglages du terminal qu'il a pris au
départ ; s'il n'est plus au premier plan à cet instant, le noyau le suspend
(SIGTTOU) et deploy_qemu.py attend sans fin. Ces tests gardent :

- apt-get reçoit « -o Dpkg::Use-Pty=0 » juste après son nom, et /dev/null
  pour entrée, avec ou sans sudo, avec ou sans capture de la sortie ;
- apt-get et dpkg gardent la version locale d'un fichier de configuration
  modifié, sans poser de question qu'aucun terminal ne pourrait recevoir ;
- toute autre commande est lancée telle quelle, stdin hérité ;
- le dry-run affiche la commande réellement lancée.
"""

import importlib.util
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class DetachFromTerminal(unittest.TestCase):
    def _lancer(self, cmd, use_sudo=False, capture=False, dry_run=False):
        """Runner.run sur `cmd`, subprocess.run simulé.

        Rend (argv passé à subprocess.run ou None, ses kwargs, sortie).
        """
        runner = DQ.Runner(use_sudo=use_sudo, dry_run=dry_run)
        # L'annonce sudo lit l'état de la machine : hors sujet ici.
        runner._sudo_dit = True
        sortie = io.StringIO()
        with (
            mock.patch.object(
                DQ.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout=""),
            ) as run,
            redirect_stdout(sortie),
        ):
            runner.run(cmd, privileged=True, capture=capture)
        if not run.called:
            return None, {}, sortie.getvalue()
        args, kwargs = run.call_args
        return args[0], kwargs, sortie.getvalue()

    def test_apt_get_gets_no_pty_and_null_stdin(self):
        argv, kw, _ = self._lancer(["apt-get", "install", "-y", "qemu-utils"])
        self.assertEqual(
            [
                "apt-get",
                "-o",
                "Dpkg::Use-Pty=0",
                "-o",
                "Dpkg::Options::=--force-confdef",
                "-o",
                "Dpkg::Options::=--force-confold",
                "install",
                "-y",
                "qemu-utils",
            ],
            argv,
        )
        self.assertIs(subprocess.DEVNULL, kw["stdin"])

    def test_apt_get_under_sudo_keeps_sudo_first(self):
        with mock.patch.object(DQ, "terminal_present", return_value=True):
            argv, kw, _ = self._lancer(["apt-get", "update"], use_sudo=True)
        self.assertEqual(["sudo", "apt-get", *DQ.APT_NO_PTY], argv[:4])
        self.assertEqual("update", argv[-1])
        self.assertIs(subprocess.DEVNULL, kw["stdin"])

    def test_apt_get_with_capture_is_detached_too(self):
        argv, kw, _ = self._lancer(
            ["apt-get", "install", "-f", "-y"], capture=True
        )
        self.assertEqual("Dpkg::Use-Pty=0", argv[2])
        self.assertIs(subprocess.DEVNULL, kw["stdin"])

    def test_dpkg_keeps_local_conffiles_without_asking(self):
        """Sans terminal, la question sur un fichier de configuration modifié
        lirait la fin de /dev/null et dpkg échouerait : elle est réglée
        d'avance, version locale gardée."""
        argv, kw, _ = self._lancer(["dpkg", "--configure", "-a"])
        self.assertEqual(
            [
                "dpkg",
                "--force-confdef",
                "--force-confold",
                "--configure",
                "-a",
            ],
            argv,
        )
        self.assertIs(subprocess.DEVNULL, kw["stdin"])

    def test_other_commands_keep_the_terminal(self):
        for cmd in (
            ["pacman", "-S", "--noconfirm", "qemu-base"],
            ["qemu-img", "resize", "disk.qcow2", "40G"],
            ["systemctl", "restart", "libvirtd"],
        ):
            with self.subTest(cmd=cmd[0]):
                argv, kw, _ = self._lancer(list(cmd))
                self.assertEqual(cmd, argv)
                self.assertIsNone(kw["stdin"])

    def test_caller_list_is_not_mutated(self):
        """REINSTALL_COMMANDS et PKG_MANAGERS sont réutilisés d'un appel à
        l'autre : l'option ne doit pas s'y accumuler."""
        cmd = ["apt-get", "install", "-y"]
        self._lancer(cmd)
        self.assertEqual(["apt-get", "install", "-y"], cmd)

    def test_dry_run_shows_the_command_actually_run(self):
        argv, _, sortie = self._lancer(["apt-get", "update"], dry_run=True)
        self.assertIsNone(argv)
        self.assertIn("[dry-run] apt-get -o Dpkg::Use-Pty=0 -o", sortie)

    def test_reinstall_reaches_subprocess_detached(self):
        """De bout en bout : chaque commande apt de la réinstallation forcée
        part sans terminal."""
        runner = DQ.Runner(use_sudo=False, dry_run=False)
        pm = next(
            (k, install, sudo, refresh)
            for k, _b, install, sudo, refresh in DQ.PKG_MANAGERS
            if k == "apt"
        )
        with (
            mock.patch.object(DQ, "detect_pkg_manager", return_value=pm),
            mock.patch.object(
                DQ, "host_packages", return_value=["qemu-utils"]
            ),
            mock.patch.object(
                DQ.subprocess, "run", return_value=mock.Mock(returncode=0)
            ) as run,
            redirect_stdout(io.StringIO()),
        ):
            DQ.reinstall_host_packages(runner, assume_yes=True)
        self.assertEqual(4, run.call_count)
        for call in run.call_args_list:
            argv = call.args[0]
            with self.subTest(argv=argv[:2]):
                self.assertIs(subprocess.DEVNULL, call.kwargs["stdin"])
                if argv[0] == "apt-get":
                    self.assertEqual(DQ.APT_NO_PTY, argv[1:3])
                    self.assertIn("Dpkg::Options::=--force-confold", argv)
                else:
                    self.assertIn("--force-confold", argv)


if __name__ == "__main__":
    unittest.main()
