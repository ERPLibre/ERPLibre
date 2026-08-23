#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran de déploiement Proxmox VE.

Ce que Proxmox a en plus de QEMU/KVM, et qui doit donc être éprouvé ici : le
VMID choisi AVANT le téléchargement de l'image (l'hôte ne dit « déjà pris »
qu'après), l'adresse qui s'en déduit sur un pont interne, le stockage et le
pont lus sur l'hôte, et une VM qui existe déjà et qu'on ne doit surtout pas
écraser.

Le rendu est vérifié sans terminal (`run_test`), sur un contexte synthétique :
aucun hôte Proxmox n'est joint.
"""

import asyncio
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.proxmox_deploy_form import (  # noqa: E402
    assign_vmids,
    build_spec,
    res_label,
    run_proxmox_form,
)

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


def rangee(nom, etat="new"):
    return {
        "vm": {
            "name": nom,
            "distro": "debian",
            "version": "13",
            "arch": "amd64",
            "vcpus": 2,
            "ram": 2048,
            "disk": "32G",
        },
        "state": etat,
        "note": "",
        "disk_gb": 32,
    }


class TestVmid(unittest.TestCase):
    """Proxmox refuse un VMID déjà pris, et il le dit APRÈS avoir téléchargé
    l'image : le choix se fait donc avant, d'après ce que l'hôte déclare."""

    def test_taken_ids_are_skipped(self):
        rows = [rangee("a"), rangee("b")]
        assign_vmids(rows, [100, 101, 103], 100, lambda v: "ip=dhcp")
        self.assertEqual([r["vm"]["vmid"] for r in rows], [102, 104])

    def test_an_existing_vm_keeps_its_own(self):
        rows = [rangee("a", "exists"), rangee("b")]
        assign_vmids(rows, [], 100, lambda v: "ip=dhcp")
        self.assertNotIn("vmid", rows[0]["vm"])
        self.assertEqual(rows[1]["vm"]["vmid"], 100)

    def test_the_first_vmid_is_honoured(self):
        rows = [rangee("a")]
        assign_vmids(rows, [], 250, lambda v: "ip=dhcp")
        self.assertEqual(rows[0]["vm"]["vmid"], 250)

    def test_a_vmid_never_goes_below_100(self):
        # Proxmox réserve les VMID sous 100.
        rows = [rangee("a")]
        assign_vmids(rows, [], 7, lambda v: "ip=dhcp")
        self.assertEqual(rows[0]["vm"]["vmid"], 100)

    def test_the_address_is_derived_from_the_vmid(self):
        rows = [rangee("a"), rangee("b")]
        assign_vmids(
            rows, [], 100, lambda v: f"ip=10.10.10.{50 + v % 200}/24"
        )
        self.assertEqual(rows[0]["vm"]["ipconfig"], "ip=10.10.10.150/24")
        self.assertEqual(rows[1]["vm"]["ipconfig"], "ip=10.10.10.151/24")

    def test_without_a_bridge_rule_it_falls_back_to_dhcp(self):
        rows = [rangee("a")]
        assign_vmids(rows, [], 100, None)
        self.assertEqual(rows[0]["vm"]["ipconfig"], "ip=dhcp")


class TestSpec(unittest.TestCase):
    def _form(self, **extra):
        base = {
            "host": {"target": "erplibre@10.0.0.5"},
            "storage": "local-lvm",
            "bridge": "vmbr0",
            "res_label": "x1",
            "ssh_key": "/home/x/.ssh/id_ed25519.pub",
            "start": True,
            "add_ssh_config": True,
            "install": {"branch": "develop", "label": "Odoo 18", "cmd": "make"},
            "monitor": True,
            "parallelism": 2,
        }
        base.update(extra)
        return base

    def test_an_existing_vm_is_never_recreated(self):
        vms = [{"name": "a"}, {"name": "b"}]
        spec = build_spec(vms, ["b"], self._form())
        self.assertEqual([v["name"] for v in spec["vms"]], ["a"])
        self.assertEqual(spec["existing"], ["b"])

    def test_the_user_defaults_to_erplibre(self):
        spec = build_spec([], [], self._form())
        self.assertEqual(spec["user"], "erplibre")

    def test_the_monitor_choice_reaches_the_spec(self):
        # Le suivi est demandé au NIVEAU DU DÉPLOIEMENT : une VM sans
        # ERPLibre se suit aussi.
        spec = build_spec([], [], self._form(install=None, monitor=True))
        self.assertIsNone(spec["install"])
        self.assertTrue(spec["monitor"])

    def test_the_resource_label_names_the_common_setting(self):
        self.assertEqual(res_label("3"), "x3")
        self.assertNotEqual(res_label("custom"), "xcustom")


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
        "host": {"target": "erplibre@10.0.0.5", "sudo": "sudo ", "label": "pve"},
        "node": "pve1",
        "catalog": {
            "amd64": [
                entree("ubuntu", "26.04"),
                entree("debian", "13"),
                entree("fedora", "44"),
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
        "bridges": ["vmbr0"],
        "bridge": "vmbr0",
        "ipconfig": lambda pont, vmid: f"ip=10.10.10.{50 + vmid % 200}/24",
        "build_command": lambda vm, spec: [f"qm create {vm['vmid']}"],
        "branches": ["develop", "master"],
        "install_profiles": [("ERPLibre + Odoo 18", "make install_odoo_18")],
        "ssh_key": "/home/x/.ssh/id_ed25519.pub",
        "cpu_presets": [2, 4, 8],
        "ram_presets": [2048, 4096, 8192],
        "disk_presets": ["32G", "64G"],
        "base_vcpus": 2,
        "host_cpu": 8,
        "free_ram": 12000,
        "extra_disk_gb": 10,
    }


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestEcran(unittest.TestCase):
    """Le formulaire, monté sans terminal."""

    def _rendu(self, gestes):
        ctx = contexte()
        resultat = {}

        async def scenario():
            from textual.widgets import SelectionList

            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                for i in range(3):
                    liste.select(liste.get_option_at_index(i).value)
                await pilote.pause()
                await pilote.pause()
                await gestes(app, pilote)
                resultat["app"] = app

        asyncio.run(scenario())
        return resultat["app"]

    def test_the_plan_shows_a_row_per_selected_system(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        self.assertEqual(len(app.rows), 3)

    def test_the_head_line_carries_the_vmid_and_the_address(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        tete = app._row_head(0, app.rows[0])
        self.assertIn("VMID", tete)
        self.assertIn("10.10.10.", tete)

    def test_an_existing_vm_is_marked_and_gets_no_vmid(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        deja = [r for r in app.rows if r["state"] == "exists"]
        self.assertEqual(len(deja), 1)
        self.assertNotIn("VMID", app._row_head(1, deja[0]))

    def test_mounting_does_not_mark_every_row_as_custom(self):
        # Poser « value= » sur un Select fait émettre un Changed : pris pour
        # une saisie, il surchargeait les trois champs de CHAQUE VM et toutes
        # les rangées portaient la marque ✎ avant qu'on ne touche à rien.
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        self.assertEqual(app.overrides, {})
        self.assertNotIn("✎", app._row_head(0, app.rows[0]))

    def test_a_lock_survives_a_common_setting(self):
        async def gestes(app, pilote):
            app._set_lock(0, True)
            await pilote.pause()
            app.custom["ram"] = 8192
            app.profile = "custom"
            app._clear_overrides(("ram",))
            app._recompute()
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(app.rows[0]["vm"]["ram"], 2048)

    def test_a_copy_adds_a_vm_with_its_own_vmid(self):
        async def gestes(app, pilote):
            app._add_copy(0, 1)
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(len(app.rows), 4)
        vmids = [
            r["vm"]["vmid"] for r in app.rows if r["state"] != "exists"
        ]
        self.assertEqual(len(vmids), len(set(vmids)))

    def test_deploying_yields_a_spec_the_engine_can_run(self):
        async def gestes(app, pilote):
            app.action_deploy()

        app = self._rendu(gestes)
        spec = app.result
        self.assertEqual(len(spec["vms"]), 2)
        self.assertEqual(spec["existing"], ["erplibre-debian-13"])
        self.assertEqual(spec["storage"], "local-lvm")
        self.assertEqual(spec["bridge"], "vmbr0")
        for vm in spec["vms"]:
            self.assertIn("vmid", vm)
            self.assertIn("ip=", vm["ipconfig"])
        self.assertEqual(spec["install"]["branch"], "develop")

    def test_text_prompts_are_not_a_cancellation(self):
        # {} n'est pas None : l'appelant distingue « annulé » de
        # « pose-moi les questions à l'ancienne ».
        async def gestes(app, pilote):
            from textual.widgets import Button

            app.on_button_pressed(
                type("E", (), {"button": Button("x", id="prompts")})()
            )

        app = self._rendu(gestes)
        self.assertEqual(app.result, {})

    def test_cancelling_yields_nothing(self):
        async def gestes(app, pilote):
            app.action_cancel()

        self.assertIsNone(self._rendu(gestes).result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
