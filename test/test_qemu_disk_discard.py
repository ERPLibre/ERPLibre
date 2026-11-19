#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le disque de travail rend à l'hôte ce que l'invité libère.

Le qcow2 est creux : il ne grossit qu'à l'écriture. Sans « discard=unmap »,
il ne rapetisse jamais — un fstrim de l'invité n'atteint pas l'hôte, et un
invité qui crée puis détruit des disques à la chaîne (un Proxmox imbriqué)
remplit l'hôte de blocs morts jusqu'à ce que qemu mette la VM en pause.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.argv = ["todo.py"]
RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()
DISQUE = Path("/tmp/travail.qcow2")
SEED = Path("/tmp/graine.iso")


def _disques(installer=None):
    """Rend les options de chaque « --disk » lancé, en dictionnaires."""
    lances = []

    class FauxRunner:
        dry_run = False
        use_sudo = False

        def run(self, cmd, *, privileged=False, check=True, capture=False):
            lances.append(list(cmd))
            return (0, "") if capture else None

    args = SimpleNamespace(
        name="vm-a",
        memory=2048,
        vcpus=2,
        arch="amd64",
        network="network=default,model=virtio",
        graphics="none",
        desktop=False,
        gpu="off",
        gpu_node="",
        attach_console=False,
        bios=False,
    )
    with (
        mock.patch.object(DQ, "host_arch", return_value="amd64"),
        mock.patch.object(DQ, "kvm_available", return_value=True),
        mock.patch.object(DQ, "os") as faux_os,
    ):
        faux_os.getuid.return_value = 1000
        faux_os.makedirs.return_value = None
        with redirect_stdout(io.StringIO()):
            DQ.virt_install(
                args, DISQUE, SEED, "debian13", FauxRunner(), installer
            )
    disques = []
    for cmd in lances:
        for i, mot in enumerate(cmd[:-1]):
            if mot == "--disk":
                options = dict(
                    p.split("=", 1) for p in cmd[i + 1].split(",") if "=" in p
                )
                disques.append(options)
    return disques


def _travail(disques):
    return [d for d in disques if d.get("path") == str(DISQUE)]


class LeDisqueDeTravailRendSesBlocs(unittest.TestCase):
    def test_an_imported_image_passes_discard_to_the_host(self):
        travail = _travail(_disques())
        self.assertTrue(travail)
        for options in travail:
            self.assertEqual(options.get("discard"), "unmap", options)

    def test_an_installed_system_passes_discard_to_the_host(self):
        installer = (Path("/tmp/linux"), Path("/tmp/initrd.gz"))
        travail = _travail(_disques(installer))
        self.assertTrue(travail)
        for options in travail:
            self.assertEqual(options.get("discard"), "unmap", options)


if __name__ == "__main__":
    unittest.main()
