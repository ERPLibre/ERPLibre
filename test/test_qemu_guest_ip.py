#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'adresse et le nom de l'invité, lus sans « hostname ».

L'image cloud d'Arch n'a pas « hostname », et son « -I » n'existe que dans
net-tools : l'adresse sortait vide dans la ligne du tunnel RDP, et le
certificat de GNOME Remote Desktop sans nom. L'adresse vient de « ip »
(iproute2, présent dans toutes les images du catalogue), le nom de
« uname -n ».
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo.qemu_install import QEMU_GUEST_IP_SH  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# Sortie de « ip -4 -o addr show scope global » sur un invité à deux
# interfaces : la première adresse est celle du réseau libvirt.
IP_OUT = (
    "2: enp1s0    inet 10.0.0.15/24 metric 100 brd 10.0.0.255 scope global "
    "dynamic enp1s0\\       valid_lft 3524sec preferred_lft 3524sec\n"
    "3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global "
    "docker0\\       valid_lft forever preferred_lft forever\n"
)


def _todo():
    return TODO.__new__(TODO)


def _adresse(ip_script):
    """Évalue l'expression avec un « ip » bouchonné, sans « hostname »."""
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp)
        # « sudo » doublé aussi : le PATH garde /usr/bin, où le vrai
        # demanderait un mot de passe si l'expression venait à l'appeler.
        for nom, corps in (("ip", ip_script), ("sudo", 'exec "$@"')):
            (bin_dir / nom).write_text(f"#!/bin/bash\n{corps}\n")
            (bin_dir / nom).chmod(0o755)
        res = subprocess.run(
            ["bash", "-c", f'echo "$({QEMU_GUEST_IP_SH})"'],
            capture_output=True,
            text=True,
            env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin"),
            timeout=30,
        )
    return res.stdout.strip()


class TestGuestAddress(unittest.TestCase):
    def test_the_first_global_ipv4_without_its_prefix(self):
        out = IP_OUT.replace("\n", "\\n")
        self.assertEqual(_adresse(f"printf '{out}'"), "10.0.0.15")

    def test_no_address_gives_an_empty_string(self):
        self.assertEqual(_adresse("exit 1"), "")


class TestNoHostnameInGuestCommands(unittest.TestCase):
    def test_desktop_tunnel_and_start_up_commands(self):
        todo = _todo()
        for cmd in (
            todo._qemu_desktop_remote_cmd("gnome", "deb", distro="arch"),
            todo._qemu_desktop_remote_cmd("cinnamon", "deb", distro="arch"),
            todo._qemu_tunnel_hint(3389, "RDP"),
            todo._qemu_vm_ready_report(),
        ):
            self.assertNotRegex(cmd, r"\bhostname\b")
            self.assertIn(QEMU_GUEST_IP_SH, cmd)

    def test_the_rdp_certificate_is_named_by_uname(self):
        cmd = _todo()._qemu_desktop_remote_cmd("gnome", "deb", distro="arch")
        self.assertIn('-subj "/CN=$(uname -n)"', cmd)


if __name__ == "__main__":
    unittest.main()
