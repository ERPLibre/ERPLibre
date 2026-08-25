#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les colonnes vivantes d'une VM posée sur un hôte Proxmox distant.

Elles venaient toutes de virsh : état, durée, écrit/s, RAM, disque. Or virsh
ne connaît pas les VM d'un hôte Proxmox — elles restaient donc VIDES, et le
relevé d'état les déclarait même « effacées », ce qui éteignait le reste.

L'hôte sait tout cela : « pvesh get /cluster/resources --type vm » rend
l'état, la mémoire, le disque et le cumul écrit de TOUTES ses VM en un appel.
Le relevé prend la forme exacte de celui de virsh, pour que le calcul du
débit, de la RAM et des colonnes ne sache pas d'où vient la mesure.
"""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_install_monitor as mon  # noqa: E402

# Sortie RÉELLE relevée sur l'hôte d'essai (une VM, stockage en fichiers :
# Proxmox y rapporte « disk: 0 », d'où le « du » qui suit).
REPONSE = (
    '[{"cpu":0.01,"disk":0,"diskread":32633856,"diskwrite":328233472,'
    '"id":"qemu/100","maxcpu":1,"maxdisk":4294967296,"maxmem":536870912,'
    '"mem":385351680,"name":"pve-suivi","netin":190,"netout":0,'
    '"node":"erplibre-proxmox-9","status":"running","template":0,'
    '"type":"qemu","uptime":127,"vmid":100}]\n'
    "---ERPLIBRE-DU---\n"
    "4294971392\t/var/lib/vz/images/100/\n"
)


class TestLaLecture(unittest.TestCase):
    def setUp(self):
        self.releves = mon.parse_pvestats(REPONSE)

    def test_the_vm_is_keyed_by_its_name(self):
        # Le suivi raisonne en NOMS : c'est ce que porte le manifeste.
        self.assertEqual(list(self.releves), ["pve-suivi"])

    def test_the_shape_matches_the_virsh_one(self):
        # Même forme exprès : `ram_pair`, `WriteWindow` et les colonnes
        # fonctionnent alors sans distinguer la source.
        attendus = {
            "ram_used",
            "ram_total",
            "ram_at",
            "wr_bytes",
            "disk_used",
            "disk_total",
        }
        self.assertTrue(attendus <= set(self.releves["pve-suivi"]))

    def test_the_measures_are_the_ones_the_host_gave(self):
        rec = self.releves["pve-suivi"]
        self.assertEqual(rec["ram_used"], 385351680)
        self.assertEqual(rec["ram_total"], 536870912)
        self.assertEqual(rec["wr_bytes"], 328233472)
        self.assertEqual(rec["state"], "running")
        self.assertEqual(rec["uptime"], 127)

    def test_a_zero_disk_falls_back_to_the_real_size(self):
        # Sur un stockage en fichiers, Proxmox NE CALCULE PAS la taille
        # occupée et rapporte 0 : la colonne aurait affiché « 0/4G ».
        self.assertEqual(self.releves["pve-suivi"]["disk_used"], 4294971392)
        self.assertEqual(self.releves["pve-suivi"]["disk_total"], 4294967296)

    def test_the_reading_is_fresh_so_the_ram_is_shown(self):
        # `ram_pair` refuse un relevé périmé : sans horodatage, la RAM d'une
        # VM distante ne s'afficherait jamais.
        rec = self.releves["pve-suivi"]
        self.assertNotEqual(mon.ram_pair(rec, rec["ram_at"]), "-")

    def test_garbage_yields_nothing_rather_than_raising(self):
        for brut in ("", "pas du json", "{}", "---ERPLIBRE-DU---"):
            self.assertEqual(mon.parse_pvestats(brut), {})


class TestLAppel(unittest.TestCase):
    """Un appel par HÔTE, mis en cache : chaque tour coûte une poignée de
    main ssh (1 s mesuré) quand virsh coûte 0,03 s pour tout le parc."""

    def setUp(self):
        mon._PVE_CACHE.update({"at": 0.0, "stats": {}})

    def _vms(self, n=2):
        return [
            {
                "name": f"vm-{i}",
                "pve": {
                    "target": "erplibre@pve1",
                    "sudo": "sudo ",
                    "vmid": 100 + i,
                },
            }
            for i in range(n)
        ]

    def test_two_vms_of_the_same_host_cost_one_call(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, REPONSE)
        ) as appel:
            mon.read_pvestats(self._vms(2), now=1000.0)
        self.assertEqual(appel.call_count, 1)

    def test_a_local_only_plan_calls_nothing(self):
        with mock.patch("script.proxmox.proxmox_deploy.run") as appel:
            self.assertEqual(mon.read_pvestats([{"name": "locale"}]), {})
        appel.assert_not_called()

    def test_the_cache_spares_the_next_tick(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, REPONSE)
        ) as appel:
            mon.read_pvestats(self._vms(1), now=1000.0)
            mon.read_pvestats(self._vms(1), now=1000.0 + 1)
            self.assertEqual(appel.call_count, 1)
            # Passé l'intervalle, on redemande.
            mon.read_pvestats(
                self._vms(1), now=1000.0 + mon.PVE_STATS_INTERVAL + 0.1
            )
            self.assertEqual(appel.call_count, 2)

    def test_a_failing_host_yields_nothing_rather_than_wrong_numbers(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(255, "timeout")
        ):
            self.assertEqual(mon.read_pvestats(self._vms(1), now=1.0), {})


class TestLEtat(unittest.TestCase):
    """Une VM absente de « virsh list » passait pour EFFACÉE."""

    def test_proxmox_states_map_to_libvirt_ones(self):
        self.assertEqual(mon.PVE_ETATS.get("running"), "running")
        self.assertEqual(mon.PVE_ETATS.get("stopped"), "shut off")

    def test_an_unknown_state_is_really_gone(self):
        # Absente de la réponse de l'hôte : la VM a vraiment disparu.
        self.assertIsNone(mon.PVE_ETATS.get(None))
        self.assertIsNone(mon.PVE_ETATS.get("n'importe quoi"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
