#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le firmware UEFI des VM est un firmware en flash.

libvirt choisit le firmware parmi les descripteurs de
/usr/share/qemu/firmware/, par ordre de nom. Un descripteur de firmware
chargé en mémoire (AMD SEV, Intel TDX) peut se trier avant le firmware
ordinaire ; virt-aa-helper refuse ce chemin, le profil AppArmor ne se charge
pas, et la VM ne démarre pas en laissant son disque sans domaine. Ces tests
gardent :

- le « --boot » UEFI restreint la sélection aux firmwares en flash ;
- il garde Secure Boot désactivé ;
- x86 et arm64 passent la même valeur ; « --bios » et s390x n'en passent
  aucune.
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


class UefiBootValue(unittest.TestCase):
    def test_selection_is_restricted_to_flash_firmware(self):
        self.assertIn("loader.type=pflash", DQ.UEFI_BOOT.split(","))

    def test_secure_boot_stays_disabled(self):
        parts = DQ.UEFI_BOOT.split(",")
        self.assertEqual("uefi", parts[0])
        self.assertIn("firmware.feature0.name=secure-boot", parts)
        self.assertIn("firmware.feature0.enabled=no", parts)


class VirtInstallBoot(unittest.TestCase):
    """La valeur de « --boot » que virt_install passe à virt-install."""

    def _boot(self, arch="amd64", bios=False):
        """Rend la valeur qui suit « --boot », ou None s'il n'y en a pas."""
        args = SimpleNamespace(
            name="vm-a",
            memory=4096,
            vcpus=2,
            arch=arch,
            network="network=default,model=virtio",
            graphics="none",
            desktop=False,
            gpu="off",
            gpu_node=None,
            attach_console=False,
            bios=bios,
        )
        lances = []

        class FauxRunner:
            dry_run = False
            use_sudo = False

            def run(
                self,
                cmd,
                *,
                privileged=False,
                libvirt=False,
                check=True,
                capture=False,
            ):
                lances.append(list(cmd))
                return (0, "") if capture else None

        with (
            mock.patch.object(DQ, "host_arch", return_value=arch),
            mock.patch.object(DQ, "kvm_available", return_value=True),
            mock.patch.object(DQ, "os") as faux_os,
        ):
            faux_os.getuid.return_value = 1000
            with redirect_stdout(io.StringIO()):
                DQ.virt_install(
                    args,
                    Path("/tmp/d.qcow2"),
                    Path("/tmp/s.iso"),
                    "archlinux",
                    FauxRunner(),
                )
        cmd = next(c for c in lances if "virt-install" in c)
        if "--boot" not in cmd:
            return None
        return cmd[cmd.index("--boot") + 1]

    def test_x86_uses_flash_firmware(self):
        self.assertEqual(DQ.UEFI_BOOT, self._boot("amd64"))

    def test_arm64_uses_flash_firmware(self):
        self.assertEqual(DQ.UEFI_BOOT, self._boot("arm64"))

    def test_bios_passes_no_firmware(self):
        self.assertIsNone(self._boot("amd64", bios=True))

    def test_s390x_passes_no_firmware(self):
        self.assertIsNone(self._boot("s390x"))


if __name__ == "__main__":
    unittest.main()
