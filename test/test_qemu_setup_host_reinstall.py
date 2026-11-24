#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La réinstallation forcée de l'hôte QEMU/libvirt.

La détection ordinaire se fonde sur la présence des binaires : une
installation interrompue après la pose de virsh passe pour complète.
« --setup-host --force-reinstall » reprend tout, et ces tests gardent :

- la commande de chaque gestionnaire réinstalle vraiment (pas de « --needed »
  sous pacman, « --reinstall » sous apt) et couvre clients ET démon ;
- les paquets qui portent les binaires sont repris, pas seulement les
  métapaquets ; un nom inconnu de cette distribution n'est jamais nommé ;
- dnf et brew, qui refusent de réinstaller un absent, installent d'abord, et
  dnf se met à jour vers la version que ses dépôts servent encore ;
- pacman écrase les fichiers qu'une extraction tuée a laissés ;
- dpkg interrompu est remis en état avant apt ;
- un verrou pacman n'est JAMAIS retiré d'office : orphelin, le message donne
  la commande ; tenu par un pacman vivant, il fait attendre ; une entrée de
  base interrompue arrête tout, avec la commande qui la retire ;
- l'option contredit --no-install-deps et exige --setup-host ;
- l'entrée du menu TODO passe l'option, ne fait rien sur un « Entrée », et
  juge la réussite au code de sortie, jamais à la présence de virsh.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
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


def _pm(key):
    """Le tuple de detect_pkg_manager() pour ce gestionnaire."""
    for k, _binary, install_cmd, use_sudo, refresh in DQ.PKG_MANAGERS:
        if k == key:
            return k, install_cmd, use_sudo, refresh
    raise KeyError(key)


class ReinstallHostPackages(unittest.TestCase):
    def _lancer(
        self,
        key,
        lock=False,
        pacman_vivant=False,
        connus=(),
        proprietaires=None,
        casses=(),
    ):
        """reinstall_host_packages sous ce gestionnaire, sans rien exécuter.

        « connus » : paquets que le gestionnaire tient pour posés.
        « proprietaires » : {chemin: [paquets]} de la base du gestionnaire.
        « casses » : entrées de base pacman sans « desc ».
        Rend (commandes lancées, SystemExit ou None, sortie affichée).
        """
        proprietaires = proprietaires or {}
        runner = mock.MagicMock()
        runner.dry_run = False
        runner.use_sudo = False
        lancees = []
        runner.run.side_effect = lambda cmd, **kw: lancees.append(cmd)
        sortie = io.StringIO()
        erreur = None
        with (
            mock.patch.object(DQ, "detect_pkg_manager", return_value=_pm(key)),
            mock.patch.object(DQ.shutil, "which", return_value=None),
            mock.patch.object(
                DQ, "_key_file_paths", return_value=list(proprietaires)
            ),
            mock.patch.object(
                DQ,
                "package_known",
                side_effect=lambda _pm_key, p: p in connus,
            ),
            mock.patch.object(
                DQ,
                "file_owner",
                side_effect=lambda _pm_key, c: proprietaires.get(c, []),
            ),
            mock.patch.object(
                DQ, "pacman_broken_entries", return_value=list(casses)
            ),
            mock.patch.object(
                DQ.os.path,
                "exists",
                side_effect=lambda p: lock and p == DQ.PACMAN_LOCK,
            ),
            mock.patch.object(
                DQ.subprocess,
                "run",
                return_value=mock.Mock(returncode=0 if pacman_vivant else 1),
            ),
            redirect_stdout(sortie),
        ):
            try:
                DQ.reinstall_host_packages(runner, assume_yes=True)
            except SystemExit as exc:
                erreur = exc
        return lancees, erreur, sortie.getvalue()

    def test_pacman_reinstalls_without_needed_and_covers_the_daemon(self):
        lancees, erreur, _ = self._lancer("pacman")
        self.assertIsNone(erreur)
        self.assertEqual(1, len(lancees), lancees)
        cmd = lancees[0]
        self.assertEqual(["pacman", "-S", "--noconfirm"], cmd[:3])
        self.assertNotIn("--needed", cmd)
        for paquet in DQ.DAEMON_PACKAGES["pacman"]:
            self.assertIn(paquet, cmd)
        self.assertIn("virt-install", cmd)
        self.assertIn("qemu-img", cmd)

    def test_pacman_overwrites_files_left_by_a_killed_extraction(self):
        """Des fichiers sur le disque que la base ignore : sans --overwrite,
        pacman refuse le paquet (« exists in filesystem »)."""
        cmd = self._lancer("pacman")[0][0]
        i = cmd.index("--overwrite")
        self.assertEqual("*", cmd[i + 1])

    def test_packages_holding_the_binaries_are_reinstalled(self):
        """qemu-desktop est un métapaquet : réinstallé seul, il ne répare
        pas qemu-system-x86, qui porte l'émulateur."""
        lancees, erreur, _ = self._lancer(
            "pacman",
            connus=("qemu-system-x86",),
            proprietaires={
                "/usr/bin/qemu-system-x86_64": ["qemu-sys-renamed"]
            },
        )
        self.assertIsNone(erreur)
        self.assertIn("qemu-system-x86", lancees[-1])
        self.assertIn("qemu-sys-renamed", lancees[-1])

    def test_unknown_extra_package_is_not_named(self):
        """Un nom absent de cette version de la distribution ferait échouer
        toute la commande : seuls les porteurs connus sont ajoutés."""
        lancees, _, _ = self._lancer("apt", connus=("libvirt-daemon",))
        self.assertIn("libvirt-daemon", lancees[-1])
        self.assertNotIn("libvirt-daemon-driver-qemu", lancees[-1])

    def test_apt_repairs_dpkg_before_reinstalling(self):
        lancees, erreur, _ = self._lancer("apt")
        self.assertIsNone(erreur)
        self.assertEqual(["dpkg", "--configure", "-a"], lancees[0])
        derniere = lancees[-1]
        self.assertIn("--reinstall", derniere)
        self.assertIn("libvirt-daemon-system", derniere)
        self.assertIn("libvirt-clients", derniere)

    def test_dnf_installs_then_upgrades_before_reinstalling(self):
        """dnf ne réinstalle ni un absent, ni une version que ses dépôts ne
        servent plus."""
        lancees, erreur, _ = self._lancer("dnf")
        self.assertIsNone(erreur)
        self.assertEqual(["dnf", "install", "-y"], lancees[0][:3])
        self.assertEqual(["dnf", "upgrade", "-y"], lancees[1][:3])
        self.assertEqual(["dnf", "reinstall", "-y"], lancees[2][:3])
        self.assertEqual(lancees[0][3:], lancees[2][3:])

    def test_stale_pacman_lock_gives_the_command_and_installs_nothing(self):
        lancees, erreur, _ = self._lancer("pacman", lock=True)
        self.assertIsNotNone(erreur)
        self.assertIn(f"sudo rm {DQ.PACMAN_LOCK}", str(erreur.code))
        self.assertEqual([], lancees)

    def test_live_pacman_lock_is_waited_for_never_removed(self):
        lancees, erreur, _ = self._lancer(
            "pacman", lock=True, pacman_vivant=True
        )
        self.assertIsNotNone(erreur)
        self.assertNotIn("rm ", str(erreur.code))
        self.assertEqual([], lancees)

    def test_interrupted_pacman_entry_gives_the_command(self):
        entree = f"{DQ.PACMAN_LOCAL_DB}/paquet-factice-1.0-1"
        lancees, erreur, _ = self._lancer("pacman", casses=(entree,))
        self.assertIsNotNone(erreur)
        self.assertIn(f"sudo rm -r {entree}", str(erreur.code))
        self.assertEqual([], lancees)

    def test_present_seed_tool_is_kept(self):
        """genisoimage présent : on réinstalle le sien, pas cloud-localds."""
        with (
            mock.patch.object(
                DQ.shutil,
                "which",
                side_effect=lambda b: (
                    "/usr/bin/x" if b == "genisoimage" else None
                ),
            ),
            mock.patch.object(DQ, "_key_file_paths", return_value=[]),
            mock.patch.object(DQ, "package_known", return_value=False),
        ):
            paquets = DQ.host_packages("apt")
        self.assertIn("genisoimage", paquets)
        self.assertNotIn("cloud-image-utils", paquets)
        self.assertEqual(len(set(paquets)), len(paquets))


class PackageQueries(unittest.TestCase):
    """La lecture des sorties des gestionnaires, sur des sorties figées."""

    def _avec(self, code, sortie):
        return mock.patch.object(DQ, "_query", return_value=(code, sortie))

    def test_dpkg_owner_with_arch_and_several_packages(self):
        with self._avec(0, "paquet-a:amd64, paquet-b: /usr/bin/outil\n"):
            self.assertEqual(
                ["paquet-a", "paquet-b"],
                DQ.file_owner("apt", "/usr/bin/outil"),
            )

    def test_dpkg_diversion_lines_name_no_owner(self):
        sortie = (
            "diversion by paquet-c from: /usr/bin/outil\n"
            "diversion by paquet-c to: /usr/bin/outil.distrib\n"
            "paquet-a: /usr/bin/outil\n"
        )
        with self._avec(0, sortie):
            self.assertEqual(
                ["paquet-a"], DQ.file_owner("apt", "/usr/bin/outil")
            )

    def test_unknown_file_has_no_owner(self):
        with self._avec(1, ""):
            self.assertEqual([], DQ.file_owner("pacman", "/usr/bin/outil"))

    def test_half_installed_apt_package_counts(self):
        """Le paquet à moitié posé est justement celui à réparer."""
        with self._avec(0, "half-installed"):
            self.assertTrue(DQ.package_known("apt", "paquet"))
        with self._avec(0, "config-files"):
            self.assertFalse(DQ.package_known("apt", "paquet"))


class SetupHostForceReinstall(unittest.TestCase):
    def _lancer(self, **kwargs):
        """setup_host sur un hôte prêt ; rend l'ordre des étapes."""
        runner = mock.MagicMock()
        runner.dry_run = False
        runner.use_sudo = False
        ordre = []
        with (
            mock.patch.object(
                DQ,
                "reinstall_host_packages",
                side_effect=lambda *a: ordre.append("reinstall"),
            ),
            mock.patch.object(
                DQ,
                "ensure_tools",
                side_effect=lambda *a, **k: ordre.append("tools"),
            ),
            mock.patch.object(DQ, "ensure_libvirt_service"),
            mock.patch.object(DQ, "ensure_libvirt_group", return_value=True),
            mock.patch.object(DQ, "ensure_ssh_key"),
            mock.patch.object(DQ, "ensure_network"),
            mock.patch.object(DQ, "kernel_modules_stale", return_value=""),
            mock.patch.object(DQ, "libvirt_ready", return_value=True),
            mock.patch.object(DQ, "network_state", return_value=(True, True)),
            mock.patch.object(DQ, "network_cidr", return_value=""),
            redirect_stdout(io.StringIO()),
        ):
            DQ.setup_host(runner, True, False, **kwargs)
        return ordre

    def test_reinstall_runs_before_the_usual_checks(self):
        self.assertEqual(
            ["reinstall", "tools"], self._lancer(force_reinstall=True)
        )

    def test_without_the_option_nothing_is_reinstalled(self):
        self.assertEqual(["tools"], self._lancer())

    def test_contradicts_no_install_deps(self):
        runner = mock.MagicMock()
        with (
            mock.patch.object(DQ, "reinstall_host_packages") as reinstall,
            redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            DQ.setup_host(runner, True, True, force_reinstall=True)
        reinstall.assert_not_called()

    def test_cli_requires_setup_host(self):
        with (
            mock.patch.object(
                sys, "argv", ["deploy_qemu.py", "--force-reinstall"]
            ),
            redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit),
        ):
            DQ.main()
        self.assertIn("--setup-host", err.getvalue())


class TodoMenuEntry(unittest.TestCase):
    def _todo(self):
        from script.todo.todo import TODO

        todo = TODO()
        todo.execute = mock.MagicMock()
        return todo

    def test_menu_command_carries_the_option(self):
        todo = self._todo()
        with mock.patch("builtins.print"):
            todo._qemu_run_setup_host(force_reinstall=True)
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("--setup-host", cmd)
        self.assertIn("--force-reinstall", cmd)
        self.assertNotIn("--assume-yes-reboot", cmd)

    def test_success_comes_from_the_exit_code_not_from_virsh(self):
        """virsh présent est l'état même d'une installation interrompue :
        un échec de deploy_qemu.py doit se dire échec."""
        todo = self._todo()
        todo.execute.exec_command_live.return_value = 1
        with (
            mock.patch("builtins.print"),
            mock.patch("builtins.input", return_value="o"),
            mock.patch.object(todo, "_qemu_warn_libvirt_access"),
            mock.patch("shutil.which", return_value="/usr/bin/virsh"),
        ):
            self.assertFalse(todo._qemu_reinstall_host())
        todo.execute.exec_command_live.return_value = 0
        with (
            mock.patch("builtins.print"),
            mock.patch("builtins.input", return_value="o"),
            mock.patch.object(todo, "_qemu_warn_libvirt_access"),
        ):
            self.assertTrue(todo._qemu_reinstall_host())

    def test_enter_alone_reinstalls_nothing(self):
        todo = self._todo()
        with (
            mock.patch("builtins.print"),
            mock.patch("builtins.input", return_value=""),
            mock.patch.object(todo, "_qemu_warn_libvirt_access"),
        ):
            self.assertFalse(todo._qemu_reinstall_host())
        todo.execute.exec_command_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
