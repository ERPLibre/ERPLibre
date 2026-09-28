#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que partagent `test_proxmox_form.py` et `test_proxmox_form_screen.py`.

`contexte()` : le contexte synthétique de l'écran Proxmox, aucun hôte joint.
`setUpModule` : à importer dans chaque module de tests qui déploie.

Sans préfixe `test_`, le lanceur unitaire ne le prend pas pour un fichier
de tests.
"""

import unittest
from unittest import mock


def setUpModule():
    """L'attente ssh ne part JAMAIS pour de vrai depuis les tests.

    Le déploiement attend qu'une VM fraîche réponde en ssh avant de lui poser
    le guide, le fuseau, le miroir et l'autorité — une adresse n'est pas une
    machine prête. Les harnais d'ici remplacent chaque geste distant mais
    appellent le vrai `_pve_ssh` : sans ce remplacement, chacun tenterait une
    connexion vers un alias inventé et la suite unitaire y perdrait des
    minutes. Les tests de l'attente elle-même la rappellent sur place.
    """
    from script.todo.todo import TODO

    patch = mock.patch.object(TODO, "_pve_attendre_ssh", lambda *a, **k: True)
    patch.start()
    unittest.addModuleCleanup(patch.stop)


def contexte():
    def entree(distro, version, arch="amd64"):
        return {
            "name": f"erplibre-{distro}-{version}",
            "distro": distro,
            "version": version,
            "arch": arch,
            "ram": 2048,
            "disk": "32G",
        }

    return {
        "host": {
            "target": "erplibre@10.0.0.5",
            "sudo": "sudo ",
            "label": "pve",
        },
        "node": "pve1",
        "catalog": {
            "amd64": [
                entree("ubuntu", "26.04"),
                entree("debian", "13"),
                entree("fedora", "44"),
                entree("proxmox", "9"),
            ],
            "arm64": [entree("debian", "13", "arm64")],
        },
        "arches": ["amd64", "arm64"],
        "native": "amd64",
        "names": ["erplibre-debian-13"],
        "vmids": [100, 101],
        "next_vmid": 102,
        "storages": ["local-lvm", "local"],
        "storage": "local-lvm",
        "storage_avail": {
            "local-lvm": 90 * (1 << 30),
            "local": 12 * (1 << 30),
        },
        "bridges": ["vmbr0"],
        "bridge": "vmbr0",
        # L'hôte d'essai est une VM de notre pont : la case « Sans connexion
        # internet » est donc offerte, comme sur un Proxmox imbriqué.
        "cache_offert": True,
        # L'hôte d'essai a un nœud de rendu et le VIRGL : la case 3D est
        # donc offerte, comme sur un hôte Proxmox capable.
        "gpu_offert": True,
        "ipconfig": lambda pont, vmid: f"ip=10.10.10.{50 + vmid % 200}/24",
        "build_command": lambda vm, spec: [f"qm create {vm['vmid']}"],
        "branches": ["develop", "master"],
        "install_profiles": [("ERPLibre + Odoo 18", "make install_odoo_18")],
        "distro_profiles": {
            "proxmox": (
                "Hyperviseur Proxmox VE (sans Odoo)",
                "./script/proxmox/install_proxmox.sh",
            )
        },
        "ssh_key": "/home/x/.ssh/id_ed25519.pub",
        "cpu_presets": [2, 4, 8],
        "ram_presets": [2048, 4096, 8192],
        "disk_presets": ["32G", "64G"],
        "base_vcpus": 2,
        "host_cpu": 8,
        "free_ram": 12000,
        "extra_disk_gb": 10,
    }
