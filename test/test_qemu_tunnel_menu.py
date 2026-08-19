#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu du tunnel de bureau distant : ses quatre choix, et où ils mènent.

Ce menu n'avait aucun test, et c'est ainsi qu'un appel à deux arguments vers
une fonction qui n'en prenait aucun a pu être livré : le choix « console de
l'hyperviseur » levait un TypeError au lieu d'ouvrir quoi que ce soit. Chaque
choix est donc atteint ici pour de vrai, jusqu'à la commande imprimée.

La ligne de partage est celle du dernier saut : xrdp et TigerVNC écoutent sur
toutes les interfaces de l'invité, donc l'hyperviseur les atteint par l'IP de
la VM ; l'émulateur Android, lui, n'écoute que sur son 127.0.0.1, ce qui exige
un saut de plus. Les deux formes coexistent, et ce n'est pas une incohérence.
"""

import io
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402


class _MenuCase(unittest.TestCase):
    def setUp(self):
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
        with mock.patch("builtins.input", lambda *a: next(it)), mock.patch(
            "sys.stdout", buf
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

    def test_a_configured_host_rides_its_proxyjump_for_rdp(self):
        out = self._play(["1", "1"])
        self.assertIn("-L 3390:localhost:3389 saut+vm-a", out)

    def test_an_out_of_range_choice_cancels_without_a_command(self):
        out = self._play(["9"])
        self.assertNotIn("ssh -N", out)


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
