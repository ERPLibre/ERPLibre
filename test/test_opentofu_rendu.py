#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le rendu bpg/proxmox d'une spec résolue."""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import rendu_proxmox as rp  # noqa: E402

ATTENDU = Path(__file__).resolve().parent / "fixtures/opentofu/rendu_attendu.json"
CONF = {"required_version": ">= 1.10", "providers": {"bpg/proxmox": "= 0.123.1"}}


def _vm(nom, vmid, ip="192.0.2.10/24"):
    return {
        "nom": nom,
        "vmid": vmid,
        "distro": "debian",
        "version": "13",
        "arch": "amd64",
        "vcpus": 2,
        "ram": 4096,
        "disque": "20G",
        "ip": ip,
        "passerelle": "" if ip == "dhcp" else "192.0.2.1",
        "dns": [] if ip == "dhcp" else ["192.0.2.53"],
        "demarrer": True,
    }


def _donnees(fichier="debian-13_amd64.qcow2", uefi=False):
    return {
        "url": "https://images.example.test/debian-13.qcow2",
        "fichier": fichier,
        "sha256": "abc123",
        "uefi": uefi,
        "user_data": "#cloud-config\n",
    }


def _spec(*vms):
    return {
        "schema": 1,
        "nom": "parc-a",
        "moteur": "tofu",
        "cible": {
            "type": "proxmox",
            "api_url": "https://pve.example.test:8006",
            "insecure": True,
            "noeud": "pve1",
            "stockage": "local-lvm",
            "stockage_snippets": "local",
            "pont": "vmbr0",
        },
        "compte": {"user": "erplibre", "ssh_key": ""},
        "vms": list(vms),
    }


def _rendre(vms, donnees):
    return rp.rendre(_spec(*vms), donnees, copy.deepcopy(CONF))


def _simple():
    return _rendre([_vm("parc-a-vm-1", 201)], {"parc-a-vm-1": _donnees()})


def _vm_res(rendu, nom):
    return rendu["resource"]["proxmox_virtual_environment_vm"][nom]


class TestRendu(unittest.TestCase):
    def test_rendu_conforme_a_l_attendu(self):
        attendu = json.loads(ATTENDU.read_text(encoding="utf-8"))
        self.assertEqual(_simple(), attendu)

    def test_aucun_secret(self):
        texte = json.dumps(_simple())
        self.assertNotIn("api_token", texte)
        self.assertNotIn("password", texte)

    def test_image_partagee_une_seule_fois(self):
        rendu = _rendre(
            [_vm("a-1", 201), _vm("a-2", 202)],
            {"a-1": _donnees(), "a-2": _donnees()},
        )
        self.assertEqual(len(rendu["resource"]["proxmox_download_file"]), 1)
        self.assertEqual(len(rendu["resource"]["proxmox_virtual_environment_vm"]), 2)

    def test_uefi_nixos(self):
        rendu = _rendre(
            [_vm("n-1", 201)],
            {"n-1": _donnees("nixos-25_amd64.qcow2", uefi=True)},
        )
        vm = _vm_res(rendu, "vm_n_1")
        self.assertEqual(vm["bios"], "ovmf")
        self.assertEqual(vm["efi_disk"]["type"], "4m")
        self.assertNotIn("bios", _vm_res(_simple(), "vm_parc_a_vm_1"))

    def test_dhcp(self):
        rendu = _rendre([_vm("d-1", 201, ip="dhcp")], {"d-1": _donnees()})
        init = _vm_res(rendu, "vm_d_1")["initialization"]
        self.assertEqual(init["ip_config"][0]["ipv4"]["address"], "dhcp")
        self.assertNotIn("dns", init)

    def test_import_par_api(self):
        disque = _vm_res(_simple(), "vm_parc_a_vm_1")["disk"][0]
        self.assertTrue(disque["import_from"].startswith("local:import/"))
        self.assertTrue(disque["import_from"].endswith(".qcow2"))

    def test_ressource_non_depreciee(self):
        self.assertNotIn(
            "proxmox_virtual_environment_download_file", json.dumps(_simple())
        )

    def test_pas_de_registre_hashicorp(self):
        self.assertNotIn("registry.terraform.io", json.dumps(_simple()))

    def test_somme_absente_sans_sha256(self):
        d = _donnees()
        d["sha256"] = ""
        rendu = _rendre([_vm("s-1", 201)], {"s-1": d})
        img = next(iter(rendu["resource"]["proxmox_download_file"].values()))
        self.assertNotIn("checksum", img)


if __name__ == "__main__":
    unittest.main()
