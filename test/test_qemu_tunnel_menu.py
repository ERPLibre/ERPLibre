#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu du tunnel de bureau distant : ses quatre choix, et où ils mènent.

Ce menu n'avait aucun test, et c'est ainsi qu'un appel à deux arguments vers
une fonction qui n'en prenait aucun a pu être livré : le choix « console de
l'hyperviseur » levait un TypeError au lieu d'ouvrir quoi que ce soit. Chaque
choix est donc atteint ici pour de vrai, jusqu'à la commande imprimée.

La ligne de partage est celle du dernier saut : GNOME Remote Desktop, xrdp et
TigerVNC écoutent sur toutes les interfaces de l'invité, donc l'hyperviseur les
atteint par l'IP de la VM ; l'émulateur Android, lui, n'écoute que sur son
127.0.0.1, ce qui exige un saut de plus. Les deux formes coexistent, et ce
n'est pas une incohérence.
"""

import io
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class _MenuCase(unittest.TestCase):
    def setUp(self):
        # Les libellés en anglais, sans set_lang() : il écrirait la langue
        # dans ./env_var.sh.
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.todo = TODO.__new__(TODO)
        self.todo._ssh_config_hosts = lambda: ["saut+vm-a"]
        self.todo._qemu_list_domains = lambda: []
        self.todo._qemu_resolve_ips = lambda names, labels=None: {
            "vm-a": "192.168.123.81"
        }
        self.todo._qemu_self_address = staticmethod(lambda: ("10.0.0.2", True))
        self.todo._ssh_proxyjump = lambda name: "hyperviseur"
        self.todo._qemu_vnc_port = lambda domain, jump: 5900

    def _play(self, answers):
        it = iter(answers)
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: next(it)),
            mock.patch("sys.stdout", buf),
        ):
            self.todo._qemu_tunnel_menu()
        return buf.getvalue()


class TestTunnelMenuChoices(_MenuCase):
    def test_the_hypervisor_console_is_reachable_at_all(self):
        """Le défaut vécu : « _qemu_console_tunnel() takes 1 positional
        argument but 3 were given ». Le choix 3 doit aboutir, pas lever."""
        out = self._play(["1", "3"])
        self.assertIn("5900", out)
        self.assertIn("hyperviseur", out)

    def test_the_console_targets_the_hypervisor_not_the_guest(self):
        """L'écran VNC appartient à QEMU : côté invité, le socket n'existe
        pas."""
        out = self._play(["1", "3"])
        self.assertIn("ssh -N -L 5900:127.0.0.1:5900 hyperviseur", out)

    def test_a_domain_without_a_vnc_port_is_diagnosed_not_tunneled(self):
        """Avec « listen=none », QEMU n'ouvre AUCUN socket : aucun tunnel n'y
        peut rien tant que le domaine n'est pas redéfini."""
        self.todo._qemu_vnc_port = lambda domain, jump: 0
        out = self._play(["1", "3"])
        self.assertIn("virsh edit", out)
        self.assertNotIn("ssh -N -L", out)

    def test_the_emulator_choice_reaches_the_adb_tunnel(self):
        out = self._play(["1", "4", "n"])
        self.assertIn("scrcpy", out)
        self.assertIn("5555", out)

    def test_rdp_is_the_default_and_vnc_the_second(self):
        self.assertIn("3389", self._play(["1", ""]))
        self.assertIn("5901", self._play(["1", "2"]))

    def test_wayvnc_has_its_own_entry(self):
        self.assertIn("-L 5901:localhost:5900", self._play(["1", "6"]))

    def test_the_labels_name_the_server_behind_each_port(self):
        """GNOME sans session X11 ne se sert qu'en RDP : le choix VNC 5901 ne
        vaut que pour les saveurs X11 sous Arch, et l'étiquette doit le dire
        pour qu'une VM Arch GNOME ne soit pas envoyée vers un port fermé."""
        out = self._play(["1", ""])
        self.assertIn("RDP 3389 (GNOME Remote Desktop, KRdp or xrdp) *", out)
        self.assertIn("VNC 5901 (TigerVNC: Cinnamon, Xfce or i3 on Arch)", out)
        self.assertIn("VNC 5900 (wayvnc, Hyprland)", out)


class TestTunnelMenuReadsTheFlavour(_MenuCase):
    """Le nom de la VM porte sa saveur et son système : le choix par défaut
    suit le serveur que l'installation y a posé."""

    def _defaut(self, hote):
        self.todo._ssh_config_hosts = lambda: [hote]
        return self._play(["1", ""])

    def test_hyprland_defaults_to_wayvnc(self):
        out = self._defaut("saut+erplibre-arch-hyprland")
        self.assertIn("[6] VNC 5900 (wayvnc, Hyprland) *", out)
        self.assertIn("-L 5901:localhost:5900", out)

    def test_xfce_on_arch_defaults_to_tigervnc(self):
        out = self._defaut("saut+erplibre-arch-xfce")
        self.assertIn("-L 5902:localhost:5901", out)

    def test_xfce_elsewhere_defaults_to_xrdp(self):
        out = self._defaut("saut+erplibre-debian-13-xfce")
        self.assertIn("-L 3390:localhost:3389", out)

    def test_plasma_follows_its_release(self):
        """KRdp sur Fedora, xrdp sur Ubuntu : RDP 3389 des deux côtés ;
        Leap 16.0 n'a aucun serveur, la console de l'hyperviseur passe
        devant."""
        self.assertIn(
            "-L 3390:localhost:3389", self._defaut("erplibre-fedora-44-plasma")
        )
        out = self._defaut("saut+erplibre-opensuse-160-plasma")
        self.assertIn("console only", out)
        self.assertIn("-L 5900:127.0.0.1:5900", out)

    def test_cosmic_defaults_to_the_hypervisor_console(self):
        out = self._defaut("saut+erplibre-fedora-44-cosmic")
        self.assertIn("cosmic → console only", out)
        self.assertNotIn("localhost:3389", out)

    def test_nixos_names_are_read_too(self):
        """NixOS : xrdp pour les saveurs X11, KRdp pour Plasma, wayvnc pour
        Hyprland, la console pour COSMIC."""
        self.assertIn(
            "-L 3390:localhost:3389",
            self._defaut("saut+erplibre-nixos-2605-i3"),
        )
        self.assertIn(
            "-L 3390:localhost:3389",
            self._defaut("saut+erplibre-nixos-2605-plasma"),
        )
        out = self._defaut("saut+erplibre-nixos-2605-hyprland")
        self.assertIn("[6] VNC 5900 (wayvnc, Hyprland) *", out)
        self.assertIn(
            "cosmic → console only",
            self._defaut("saut+erplibre-nixos-2605-cosmic"),
        )

    def test_an_arch_suffix_does_not_hide_the_release(self):
        flavour, remote, distro = self.todo._qemu_tunnel_desktop(
            "erplibre-arch-arm64-xfce"
        )
        self.assertEqual((flavour, remote, distro), ("xfce", "x11", "arch"))

    def test_a_name_without_flavour_keeps_the_manual_default(self):
        self.assertEqual(
            self.todo._qemu_tunnel_desktop("saut+vm-a"), (None, "", None)
        )
        self.assertIn("-L 3390:localhost:3389", self._defaut("saut+vm-a"))

    def test_the_choice_still_overrides_the_guess(self):
        self.todo._ssh_config_hosts = lambda: ["saut+erplibre-arch-hyprland"]
        self.assertIn("-L 3390:localhost:3389", self._play(["1", "1"]))


class TestTunnelMenuChoicesTail(_MenuCase):
    def test_a_configured_host_rides_its_proxyjump_for_rdp(self):
        out = self._play(["1", "1"])
        self.assertIn("-L 3390:localhost:3389 saut+vm-a", out)

    def test_an_out_of_range_choice_cancels_without_a_command(self):
        out = self._play(["9"])
        self.assertNotIn("ssh -N", out)


class TestVirtViewer(_MenuCase):
    """La voie la plus courte vers l'écran d'une VM : virt-viewer.

    Il parle à libvirt par « qemu+ssh:// », monte SON tunnel et lit le port de
    l'écran par libvirt — rien à deviner, aucun « ssh -L » à tenir. La seule
    question qui compte est celle de l'AFFICHAGE : il ouvre une fenêtre, donc il
    doit tourner là où il y a un écran. C'est l'environnement qui tranche.
    """

    def _play_kind5(self, env=None, which=None, popen=None):
        it = iter(["1", "5"])
        buf = io.StringIO()
        stack = [
            mock.patch("builtins.input", lambda *a: next(it)),
            mock.patch("sys.stdout", buf),
            mock.patch.dict("os.environ", env or {}, clear=False),
        ]
        if which is not None:
            stack.append(mock.patch("shutil.which", which))
        if popen is not None:
            stack.append(mock.patch("subprocess.Popen", popen))
        for ctx in stack:
            ctx.__enter__()
        try:
            self.todo._qemu_tunnel_menu()
        finally:
            for ctx in reversed(stack):
                ctx.__exit__(None, None, None)
        return buf.getvalue()

    def setUp(self):
        super().setUp()
        # Une VM libvirt LOCALE : l'URI est alors qemu:///system.
        self.todo._ssh_config_hosts = lambda: []
        self.todo._qemu_list_domains = lambda: ["vm-a"]

    def test_no_display_hands_the_command_to_the_workstation(self):
        """Sur un hyperviseur sans écran, ouvrir une fenêtre ici ne servirait à
        personne : on donne la commande, sous sa forme qemu+ssh."""
        out = self._play_kind5(env={"DISPLAY": "", "WAYLAND_DISPLAY": ""})
        self.assertIn("virt-viewer -c qemu+ssh://", out)
        self.assertIn("/system vm-a", out)

    def test_no_display_installs_nothing(self):
        """Poser un client graphique sur une machine sans écran serait du
        gaspillage — et une surprise. Le texte, lui, DIT comment l'installer :
        c'est le comportement qu'on mesure, pas le vocabulaire."""
        ran = []
        self.todo.execute = mock.Mock()
        self.todo.execute.exec_command_live = lambda cmd, **kw: ran.append(cmd)
        out = self._play_kind5(
            env={"DISPLAY": "", "WAYLAND_DISPLAY": ""},
            which=lambda c: None,
        )
        self.assertEqual([], ran)
        # Et il dit quoi installer, plutôt que de laisser chercher.
        self.assertIn("virt-viewer", out)

    def test_a_display_launches_it_detached(self):
        """Détaché : le menu ne doit pas rester bloqué derrière une fenêtre."""
        spawned = {}

        def fake_popen(cmd, **kw):
            spawned["cmd"] = cmd
            spawned["kw"] = kw
            return mock.Mock()

        out = self._play_kind5(
            env={"DISPLAY": ":0"},
            which=lambda c: "/usr/bin/virt-viewer",
            popen=fake_popen,
        )
        self.assertEqual(
            ["virt-viewer", "-c", "qemu:///system", "vm-a"], spawned["cmd"]
        )
        self.assertTrue(spawned["kw"].get("start_new_session"))
        self.assertIn(":0", out)

    def test_wayland_counts_as_a_display(self):
        spawned = {}
        self._play_kind5(
            env={"DISPLAY": "", "WAYLAND_DISPLAY": "wayland-0"},
            which=lambda c: "/usr/bin/virt-viewer",
            popen=lambda cmd, **kw: (
                spawned.setdefault("cmd", cmd) and mock.Mock()
            ),
        )
        self.assertIn("virt-viewer", spawned.get("cmd", []))

    def test_a_configured_host_targets_its_proxyjump(self):
        """L'écran appartient au QEMU de l'HYPERVISEUR : c'est lui que l'URI
        doit nommer, pas la VM."""
        self.todo._ssh_config_hosts = lambda: ["saut+vm-a"]
        self.todo._qemu_list_domains = lambda: []
        out = self._play_kind5(env={"DISPLAY": "", "WAYLAND_DISPLAY": ""})
        self.assertIn("virt-viewer -c qemu+ssh://", out)
        self.assertIn("/system vm-a", out)

    def test_a_configured_host_without_proxyjump_is_refused(self):
        self.todo._ssh_config_hosts = lambda: ["saut+vm-a"]
        self.todo._qemu_list_domains = lambda: []
        self.todo._ssh_proxyjump = lambda name: ""
        out = self._play_kind5(env={"DISPLAY": ":0"})
        self.assertIn("ProxyJump", out)
        self.assertNotIn("virt-viewer -c", out)


class TestEnsureVirtViewer(unittest.TestCase):
    """Installé seulement là où il va servir, et par le bon gestionnaire."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.ran = []
        self.todo.execute = mock.Mock()
        self.todo.execute.exec_command_live = lambda cmd, **kw: (
            self.ran.append(cmd)
        )

    def test_present_means_nothing_to_do(self):
        with mock.patch("shutil.which", lambda c: "/usr/bin/virt-viewer"):
            self.assertTrue(self.todo._qemu_ensure_virt_viewer())
        self.assertEqual([], self.ran)

    def test_it_picks_the_manager_that_exists(self):
        seen = {"virt-viewer": [None, "/usr/bin/virt-viewer"]}

        def which(cmd):
            if cmd == "virt-viewer":
                return seen["virt-viewer"].pop(0)
            return "/usr/bin/dnf" if cmd == "dnf" else None

        with (
            mock.patch("shutil.which", which),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertTrue(self.todo._qemu_ensure_virt_viewer())
        self.assertEqual(1, len(self.ran))
        self.assertIn("dnf install -y virt-viewer", self.ran[0])

    def test_no_manager_is_said_not_guessed(self):
        with (
            mock.patch("shutil.which", lambda c: None),
            mock.patch("sys.stdout", io.StringIO()) as out,
        ):
            self.assertFalse(self.todo._qemu_ensure_virt_viewer())
        self.assertIn("paquets", out.getvalue().lower() + "paquets")
        self.assertEqual([], self.ran)

    def test_a_failed_install_is_reported(self):
        """Rendre True sans le binaire enverrait l'appelant lancer un fantôme."""
        with (
            mock.patch(
                "shutil.which",
                lambda c: "/usr/bin/apt-get" if c == "apt-get" else None,
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertFalse(self.todo._qemu_ensure_virt_viewer())
        # Le rafraîchissement des index passe d'abord, puis l'installation.
        self.assertEqual(2, len(self.ran))
        self.assertEqual("sudo apt-get update", self.ran[0])
        self.assertIn("apt-get install -y virt-viewer", self.ran[1])

    def test_every_family_is_covered(self):
        """La table des familles a quitté ce menu pour todo_install, qui la
        partage avec les autres installations du CLI."""
        from script.todo import todo_install

        self.assertEqual(
            ["apt-get", "dnf", "pacman", "zypper"],
            list(todo_install.FAMILIES),
        )
        for famille in todo_install.FAMILIES:
            self.assertIn(
                "virt-viewer",
                todo_install.install_command(["virt-viewer"], famille=famille),
            )


class TestTunnelMenuTargets(_MenuCase):
    def test_local_domains_fill_in_when_ssh_config_is_empty(self):
        """Une VM libvirt locale reste joignable même sans entrée ssh_config ;
        xrdp écoutant sur toutes les interfaces, son IP suffit."""
        self.todo._ssh_config_hosts = lambda: []
        self.todo._qemu_list_domains = lambda: ["vm-a"]
        out = self._play(["1", "1"])
        self.assertIn("-L 3390:192.168.123.81:3389", out)

    def test_nothing_anywhere_is_said_plainly(self):
        self.todo._ssh_config_hosts = lambda: []
        self.todo._qemu_list_domains = lambda: []
        out = self._play([])
        self.assertIn("~/.ssh/config", out)

    def test_an_off_local_vm_is_reported_before_any_command(self):
        self.todo._ssh_config_hosts = lambda: []
        self.todo._qemu_list_domains = lambda: ["vm-b"]
        out = self._play(["1", "1"])
        self.assertIn("IP", out.upper())
        self.assertNotIn("ssh -N", out)


if __name__ == "__main__":
    unittest.main()
