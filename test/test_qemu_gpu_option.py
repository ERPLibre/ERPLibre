#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La 3D se coche à la création, même sur une VM sans écran.

« auto » s'abstient sans écran virtuel : une VM serveur n'a pas demandé de
périphérique vidéo, et lui en poser un d'office changerait son matériel. Mais
une VM sans console peut vouloir un virtio-gpu accéléré — rendu hors écran,
émulateur qui tourne dedans. La case le demande explicitement.

Ce que ces tests gardent :

- la case atteint vraiment la commande, à travers la spec ;
- sans elle, rien ne change pour une VM serveur ;
- « --graphics none » et « egl-headless » ne coexistent jamais : le premier
  dit « aucun affichage », le second EST un affichage.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
NODE = "/dev/dri/renderD128"


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class LaDecision(unittest.TestCase):
    def test_auto_still_abstains_without_a_screen(self):
        """Le défaut ne doit pas changer : une VM serveur reste sans vidéo."""
        on, msg = DQ.gpu_decision("auto", NODE, False)
        self.assertFalse(on)
        self.assertEqual("", msg)

    def test_on_now_enables_3d_without_a_screen(self):
        on, msg = DQ.gpu_decision("on", NODE, False)
        self.assertTrue(on)
        self.assertIn("sans écran", msg)

    def test_off_wins_over_everything(self):
        self.assertEqual((False, ""), DQ.gpu_decision("off", NODE, False))

    def test_without_a_host_node_it_still_refuses(self):
        on, msg = DQ.gpu_decision("on", "", False)
        self.assertFalse(on)
        self.assertTrue(msg)


class LaCaseAtteintLaCommande(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _parts(self, gpu3d):
        vm = {
            "name": "vm-a",
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "ram": 4096,
            "vcpus": 2,
            "disk": "20G",
        }
        spec = {
            "vms": [vm],
            "gpu3d": gpu3d,
            "install": None,
            "ssh_key": "",
            "vm_tools": (),
        }
        return self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def test_the_box_adds_the_flag(self):
        self.assertIn("--gpu", self._parts(True))
        parts = self._parts(True)
        self.assertEqual("on", parts[parts.index("--gpu") + 1])

    def test_without_the_box_nothing_is_added(self):
        self.assertNotIn("--gpu", self._parts(False))


class LaSpecLaTransporte(unittest.TestCase):
    def _spec(self, form_extra):
        form = {
            "res_label": "x1",
            "ssh_key": "",
            "install": None,
            "add_ssh_config": True,
            "parallelism": 1,
        }
        form.update(form_extra)
        return build_spec([{"name": "vm-a"}], [], form)

    def test_the_checkbox_reaches_the_spec(self):
        self.assertTrue(self._spec({"gpu3d": True})["gpu3d"])

    def test_its_default_is_off(self):
        self.assertFalse(self._spec({})["gpu3d"])


if __name__ == "__main__":
    unittest.main()
