#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rafraîchissement forcé du suivi d'installation (touche F5).

Ce que ces tests gardent :

- F5 relit l'état libvirt sans attendre la période de 10 s, et le tableau
  l'affiche dans le même appui ;
- F5 resonde Odoo même sur une VM déjà verte, que le rythme régulier ne
  resonde qu'au bout de ODOO_RECHECK ;
- F5 vide le cache des statistiques Proxmox avant de relire ;
- des appuis répétés ne comptent pas d'absences : « effacée » reste au
  rythme régulier ;
- un appui pendant un rafraîchissement en cours ne relance rien ;
- la fenêtre d'aide affiche F5.
"""

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

from async_case import AsyncCase  # noqa: E402

from script.todo import qemu_install_monitor as mon  # noqa: E402


class TestF5(AsyncCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.etats = {"vm-a": "running"}
        self.port = True
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: dict(self.etats)),
            ("virsh_ip", lambda nom: ""),
            ("_port_open", lambda ip, port=8069, timeout=0.5: self.port),
            ("record_duration", lambda *a, **k: None),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)

    def app(self):
        log = self.base / "vm-a.log"
        log.write_text("===> install\n")
        manifeste = {
            "branch": "develop",
            "started": time.time() - 600,
            "vms": [
                {
                    "name": "vm-a",
                    "ip": "127.0.0.9",
                    "arch": "amd64",
                    "log": str(log),
                    "ssh": "ssh erplibre@127.0.0.9",
                    "disk": str(self.base / "vm-a.qcow2"),
                }
            ],
        }
        chemin = self.base / "session.json"
        chemin.write_text(json.dumps(manifeste))
        return mon.run_monitor(str(chemin), run_app=False)

    async def ouvre(self, app, pilot):
        await pilot.pause()
        await app.workers.wait_for_complete()
        await app._tick_table()
        await pilot.pause()

    async def f5(self, app, pilot):
        await pilot.press("f5")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_l_etat_est_relu_sans_attendre(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertEqual("running", app._domstate["vm-a"])
            self.etats = {"vm-a": "paused"}
            await self.f5(app, pilot)
            self.assertEqual("paused", app._domstate["vm-a"])
            # Le tableau suit la relecture de l'état, il l'affiche donc
            # dans le même appui.
            self.assertEqual(
                f"⏸ {mon.t('paused')}", app._cells[("vm-a", "state")]
            )

    async def test_odoo_deja_vert_est_resonde(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertIn("vm-a", app._odoo_up)
            self.port = False
            # Le rythme régulier garde le vert jusqu'à ODOO_RECHECK.
            await app._tick_table()
            self.assertIn("vm-a", app._odoo_up)
            await self.f5(app, pilot)
            self.assertNotIn("vm-a", app._odoo_up)

    async def test_le_cache_proxmox_est_vide_avant_la_relecture(self):
        vu = []

        def detail(vms):
            vu.append(mon._PVE_CACHE["at"])
            return {}, False

        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.dict(mon._PVE_CACHE, {"at": time.time()}):
                with mock.patch.object(mon, "read_pvestats_detail", detail):
                    await self.f5(app, pilot)
        self.assertEqual([0.0], vu)

    async def test_les_appuis_repetes_ne_comptent_pas_d_absence(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            # « virsh list » muet : seul le rythme régulier compte.
            self.etats = {}
            for _ in range(mon.PVE_ABSENCES_AVANT_EFFACEE + 2):
                await self.f5(app, pilot)
            self.assertEqual("running", app._domstate["vm-a"])
            self.assertNotIn("vm-a", app._final)
            self.assertEqual(0, app._pve_absences.get("vm-a", 0))
            # Le rythme régulier, lui, compte toujours.
            await app._tick_domstate()
            self.assertEqual(1, app._pve_absences["vm-a"])

    async def test_un_appui_pendant_un_rafraichissement_ne_relance_rien(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._rafraichit = True
            with mock.patch.object(app, "_tick_domstate") as tick:
                await pilot.press("f5")
                await app.workers.wait_for_complete()
            tick.assert_not_called()

    async def test_le_drapeau_retombe_meme_sur_erreur(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._rafraichit = True
            with mock.patch.object(
                app, "_tick_table", side_effect=RuntimeError("x")
            ):
                with self.assertRaises(RuntimeError):
                    await app._force_refresh()
            self.assertFalse(app._rafraichit)

    async def test_l_aide_affiche_f5(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            await pilot.press("h")
            await pilot.pause()
            textes = [str(w.render()) for w in app.screen.query("Static")]
            ligne = next(x for x in textes if mon.t("Refresh") in x)
            self.assertIn("F5", ligne)


if __name__ == "__main__":
    import unittest

    unittest.main()
