#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'amorçage UEFI des VM créées SUR un hôte Proxmox.

Les deux chemins de déploiement ne partent pas du même firmware : celui de
qemu amorce en UEFI pour tout le monde, celui de Proxmox part en SeaBIOS.
Tant que toutes les images savaient faire les deux, la divergence ne se
voyait pas.

Mesuré sur un Proxmox 9 : une VM NixOS créée en SeaBIOS se déclare
« running » et sa console reste MUETTE ; la même en OVMF démarre — systemd,
cloud-init, réseau, invite de connexion. Debian 13, sur le même hôte, démarre
en SeaBIOS sans rien devoir à l'UEFI.

D'où ce que ces tests gardent : un marqueur PAR DISTRIBUTION, et non un
défaut renversé pour tous. Renverser le défaut aurait ajouté un disque EFI à
chaque VM du parc pour le besoin d'une seule image.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]

from script.proxmox import proxmox_deploy as pve  # noqa: E402


def _deploy_qemu():
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

SPEC = {
    "name": "essai",
    "storage": "local",
    "bridge": "vmbr0",
    "memory": 2048,
    "vcpus": 2,
    "disk": "40G",
    "image": "image.qcow2",
    "user": "erplibre",
    "start": False,
    "ipconfig": "ip=dhcp",
}


class LeCatalogueSaitQuiEnABesoin(unittest.TestCase):
    def test_the_image_with_no_bios_sector_is_named(self):
        """NixOS ne publie pas d'image cloud : celle du tiers qui la rebâtit
        n'a pas de secteur d'amorçage BIOS."""
        self.assertTrue(DQ.requiert_uefi("nixos"))

    def test_the_others_are_left_alone(self):
        """Mesuré : Debian 13 démarre en SeaBIOS sur un Proxmox 9. Les
        basculer coûterait un disque EFI par VM, pour rien."""
        for distro in ("ubuntu", "debian", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                self.assertFalse(DQ.requiert_uefi(distro))

    def test_an_unknown_distro_does_not_get_uefi(self):
        """Le doute ne vaut pas un firmware : c'est le catalogue qui sait."""
        self.assertFalse(DQ.requiert_uefi(""))
        self.assertFalse(DQ.requiert_uefi("inconnue"))


class LaSequenceDeCreation(unittest.TestCase):
    def _cmds(self, **extra):
        return pve.create_cmds(100, dict(SPEC, **extra))

    def test_without_the_marker_nothing_changes(self):
        """La VM ordinaire garde exactement la séquence d'avant."""
        joint = " ".join(self._cmds())
        self.assertNotIn("--bios", joint)
        self.assertNotIn("efidisk", joint)

    def test_with_the_marker_the_firmware_is_ovmf(self):
        creation = self._cmds(uefi=True)[0]
        self.assertIn("qm create 100", creation)
        self.assertIn("--bios ovmf", creation)

    def test_the_efi_disk_is_added(self):
        """« --bios ovmf » sans disque EFI démarre, mais ne retient RIEN :
        l'entrée d'amorçage écrite par l'invité est perdue au redémarrage."""
        efi = [c for c in self._cmds(uefi=True) if "efidisk0" in c]
        self.assertEqual(1, len(efi))
        self.assertIn("efitype=4m", efi[0])

    def test_the_efi_disk_lives_on_the_same_storage(self):
        """Un stockage inventé fait échouer « qm set » après que la VM
        existe : elle reste alors à moitié créée."""
        efi = [c for c in self._cmds(uefi=True) if "efidisk0" in c][0]
        self.assertIn(f" {SPEC['storage']}:0,", efi)

    def test_secure_boot_is_off(self):
        """Un chargeur non signé par les clés Microsoft est refusé, et
        l'image ne démarre pas du tout — la même raison que côté qemu."""
        efi = [c for c in self._cmds(uefi=True) if "efidisk0" in c][0]
        self.assertIn("pre-enrolled-keys=0", efi)

    def test_the_efi_disk_comes_before_the_start(self):
        """Ajouter un disque à une VM qui tourne déjà ne l'amorce pas
        dessus."""
        cmds = self._cmds(uefi=True, start=True)
        i_efi = next(i for i, c in enumerate(cmds) if "efidisk0" in c)
        i_start = next(
            i for i, c in enumerate(cmds) if c.endswith("qm start 100")
        )
        self.assertLess(i_efi, i_start)


class LeMenuTransmetLeMarqueur(unittest.TestCase):
    """Un catalogue qui sait et un menu qui ne dit pas laisse la VM en
    SeaBIOS : les deux points d'appel sont tenus."""

    SRC = (RACINE / "script/todo/proxmox_menu.py").read_text(encoding="utf-8")

    def test_both_call_sites_pass_it(self):
        self.assertEqual(2, self.SRC.count('"uefi": mod.requiert_uefi('))

    def test_it_is_read_from_the_catalogue_not_hardcoded(self):
        """Écrire « nixos » ici ferait deux autorités sur une même question."""
        self.assertNotIn('"uefi": True', self.SRC)
        self.assertNotIn('"uefi": "nixos"', self.SRC)


if __name__ == "__main__":
    unittest.main()
