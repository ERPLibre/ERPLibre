#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une VM Dolibarr dans le suivi : sondée par SSH sur sa boucle locale,
ouverte par un tunnel, redémarrée par run.py, et les actions propres à Odoo
refusées avec un message."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

from async_case import AsyncCase  # noqa: E402

from script.todo import qemu_dolibarr as qd  # noqa: E402
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

DOLI = {"name": "vm-d", "ip": "192.0.2.7", "app": "dolibarr"}
ODOO = {"name": "vm-o", "ip": "192.0.2.8"}
PVE = {"target": "root@pve.example", "addr": "198.51.100.5"}


class TestLaSonde(unittest.TestCase):
    def test_it_enters_the_vm_and_asks_its_loopback(self):
        argv = mon.dolibarr_probe_argv(DOLI)
        self.assertEqual("ssh", argv[0])
        self.assertIn("erplibre@192.0.2.7", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertEqual(
            f"curl -fs -o /dev/null -m 5 http://127.0.0.1:{qd.PORT}/",
            argv[-1],
        )

    def test_a_short_connect_timeout_wins(self):
        # ssh garde la PREMIÈRE valeur d'une option.
        argv = mon.dolibarr_probe_argv(DOLI)
        self.assertLess(
            argv.index("ConnectTimeout=4"), argv.index("ConnectTimeout=8")
        )

    def test_a_proxmox_vm_goes_through_its_host(self):
        argv = mon.dolibarr_probe_argv(dict(DOLI, pve=PVE))
        self.assertIn("root@pve.example", argv)
        self.assertIn("erplibre@198.51.100.5", argv)

    def test_the_install_key_is_presented(self):
        argv = mon.dolibarr_probe_argv(dict(DOLI, identity="/k/id"))
        self.assertEqual("/k/id", argv[argv.index("-i") + 1])

    def test_alive_is_the_exit_code(self):
        oui = lambda *a, **k: SimpleNamespace(returncode=0)  # noqa: E731
        non = lambda *a, **k: SimpleNamespace(returncode=7)  # noqa: E731
        self.assertTrue(mon.dolibarr_alive(DOLI, run=oui))
        self.assertFalse(mon.dolibarr_alive(DOLI, run=non))

    def test_a_timeout_is_a_no(self):
        def lent(*_a, **_k):
            raise subprocess.TimeoutExpired("ssh", 10)

        self.assertFalse(mon.dolibarr_alive(DOLI, run=lent))


class TestLeRythme(unittest.TestCase):
    def setUp(self):
        self.vus = []
        self.sonde = lambda vm: self.vus.append(vm) or True

    def test_not_probed_before_the_install_is_done(self):
        lu = mon.dolibarr_reading(DOLI, False, 0.0, 100.0, self.sonde, False)
        self.assertEqual((None, False), lu)
        self.assertEqual([], self.vus)

    def test_red_is_probed_at_the_slow_period(self):
        p = mon.DOLIBARR_PROBE_INTERVAL
        lire = mon.dolibarr_reading
        self.assertEqual(
            (True, True), lire(DOLI, False, 0.0, 100.0, self.sonde, True)
        )
        self.assertEqual(
            (None, False),
            lire(DOLI, False, 100.0 - p + 1, 100.0, self.sonde, True),
        )
        self.assertEqual(
            (True, True), lire(DOLI, False, 100.0 - p, 100.0, self.sonde, True)
        )

    def test_green_is_rechecked_like_odoo(self):
        lu = mon.dolibarr_reading(
            DOLI, True, 100.0 - mon.ODOO_RECHECK + 1, 100.0, self.sonde, True
        )
        self.assertEqual((None, False), lu)


class TestLaPageWeb(unittest.TestCase):
    def test_dolibarr_always_goes_through_a_tunnel(self):
        argv, url = mon.web_target(DOLI)
        self.assertIn(f"{qd.TUNNEL_PORT}:127.0.0.1:{qd.PORT}", argv)
        self.assertIn("-N", argv)
        self.assertIn("ExitOnForwardFailure=yes", argv)
        self.assertIn("erplibre@192.0.2.7", argv)
        self.assertEqual(f"http://127.0.0.1:{qd.TUNNEL_PORT}/", url)

    def test_a_local_odoo_vm_is_reached_directly(self):
        self.assertEqual((None, "http://192.0.2.8:8069"), mon.web_target(ODOO))

    def test_a_proxmox_odoo_vm_keeps_its_tunnel(self):
        argv, url = mon.web_target(dict(ODOO, pve=PVE))
        self.assertIn("18069:198.51.100.5:8069", argv)
        self.assertEqual("http://127.0.0.1:18069", url)


class TestLesActions(unittest.TestCase):
    def test_db_restore_is_refused(self):
        self.assertEqual(
            t("Dolibarr VM: no Odoo database to restore."),
            mon.vm_action_refusal(DOLI, "dbrestore", ["neutralize"]),
        )

    def test_the_python_update_is_refused(self):
        self.assertEqual(
            t(
                "Dolibarr VM: the Python dependencies update is Odoo's; untick it."
            ),
            mon.vm_action_refusal(DOLI, "update", ["system", "python"]),
        )

    def test_system_and_git_updates_pass(self):
        self.assertEqual(
            "", mon.vm_action_refusal(DOLI, "update", ["system", "git"])
        )

    def test_an_odoo_vm_refuses_nothing(self):
        for kind in ("dbrestore", "update", "restart"):
            self.assertEqual("", mon.vm_action_refusal(ODOO, kind, ["python"]))

    def test_the_restart_follows_the_app(self):
        self.assertEqual(mon.restart_odoo_cmd(), mon.restart_cmd_for(ODOO))
        self.assertEqual(qd.restart_cmd(mon.EL_DIR), mon.restart_cmd_for(DOLI))


class TestLeRedemarrage(unittest.TestCase):
    """La commande tourne pour de vrai sous bash, avec un faux python qui
    note ses appels."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(os.path.realpath(tmp.name))
        self.log = self.home / "appels.log"

    def lance(self):
        env = dict(os.environ, HOME=str(self.home), LOG=str(self.log))
        return subprocess.run(
            ["bash", "-c", qd.restart_cmd("~/git/erplibre")],
            env=env,
            capture_output=True,
        ).returncode

    def test_it_starts_the_instance_from_the_checkout(self):
        bin_ = self.home / "git/erplibre/.venv.erplibre/bin"
        bin_.mkdir(parents=True)
        faux = bin_ / "python"
        faux.write_text('#!/bin/sh\necho "$PWD $*" >> "$LOG"\n')
        faux.chmod(0o755)
        self.assertEqual(0, self.lance())
        self.assertIn(
            f"{self.home}/git/erplibre script/dolibarr/run.py start"
            f" --instance {qd.INSTANCE}",
            self.log.read_text(),
        )

    def test_without_a_checkout_it_fails_and_runs_nothing(self):
        self.assertNotEqual(0, self.lance())
        self.assertFalse(self.log.exists())


class TestLeTunnel(unittest.TestCase):
    """Un tunnel qui sort aussitôt — port local pris — n'ouvre aucune page :
    le navigateur montrerait ce qui écoute déjà sur ce port."""

    def lance(self, code):
        proc = SimpleNamespace(poll=lambda: code, returncode=code)
        return mon.open_tunnel(
            ["ssh", "-N"], popen=lambda argv: proc, sleep=lambda s: None
        )

    def test_a_live_tunnel_is_kept(self):
        proc, erreur = self.lance(None)
        self.assertIsNotNone(proc)
        self.assertEqual("", erreur)

    def test_a_tunnel_that_exits_is_an_error(self):
        proc, erreur = self.lance(255)
        self.assertIsNone(proc)
        self.assertIn("255", erreur)

    def test_ssh_missing_is_an_error(self):
        def absent(_argv):
            raise FileNotFoundError("ssh")

        proc, erreur = mon.open_tunnel(
            ["ssh"], popen=absent, sleep=lambda s: None
        )
        self.assertIsNone(proc)
        self.assertTrue(erreur)


class TestLesIdentifiants(unittest.TestCase):
    """La commande lit l'identifiant et le mot de passe DANS la VM ; elle
    tourne ici sous bash, avec un faux foyer."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(os.path.realpath(tmp.name))

    def lance(self):
        return subprocess.run(
            ["bash", "-c", qd.credentials_cmd()],
            env=dict(os.environ, HOME=str(self.home)),
            capture_output=True,
            text=True,
        )

    def test_it_shows_the_login_and_the_password(self):
        secrets = self.home / ".local/share/ERPLibre/dolibarr/dolibarr"
        secrets.mkdir(parents=True)
        # Valeurs inventées.
        (secrets / "secrets.env").write_text(
            "DB_PASSWORD=base-inventee\nADMIN_PASSWORD=Mdp=inv3nte\n"
        )
        r = self.lance()
        self.assertEqual(0, r.returncode)
        self.assertIn(qd.ADMIN_LOGIN, r.stdout)
        self.assertIn("Mdp=inv3nte", r.stdout)
        self.assertNotIn("base-inventee", r.stdout)

    def test_without_the_file_it_says_so(self):
        r = self.lance()
        self.assertNotEqual(0, r.returncode)
        self.assertIn("secrets.env", r.stdout + r.stderr)


class TestLeSuivi(AsyncCase):
    def monte(self, fini=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.ports, self.sondes = [], []
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("virsh_ip", lambda nom: ""),
            (
                "_port_open",
                lambda ip, port=8069, timeout=0.5: (
                    self.ports.append(ip) or False
                ),
            ),
            (
                "dolibarr_alive",
                lambda vm: self.sondes.append(vm["name"]) or True,
            ),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)
        vms = []
        for vm in (DOLI, ODOO):
            log = base / f"{vm['name']}.log"
            log.write_text("x\n" + (f"{mon.EXIT_MARKER} 0\n" if fini else ""))
            vms.append(dict(vm, log=str(log), ssh=f"ssh erplibre@{vm['ip']}"))
        manifeste = base / "session.json"
        manifeste.write_text(
            json.dumps(
                {"branch": "develop", "started": time.time(), "vms": vms}
            )
        )
        return mon.run_monitor(str(manifeste), run_app=False)

    async def test_the_web_column_asks_dolibarr_over_ssh(self):
        app = self.monte()
        async with app.run_test(size=(150, 40)) as pilote:
            await pilote.pause()
            odoo = app._collect_table()[4]
        self.assertTrue(odoo["vm-d"])
        self.assertIn("vm-d", self.sondes)
        self.assertNotIn(DOLI["ip"], self.ports)

    async def test_the_odoo_vm_keeps_its_port_probe(self):
        app = self.monte()
        async with app.run_test(size=(150, 40)) as pilote:
            await pilote.pause()
            app._collect_table()
        self.assertIn(ODOO["ip"], self.ports)
        self.assertNotIn("vm-o", self.sondes)

    async def test_a_paused_vm_is_not_probed(self):
        app = self.monte()
        with mock.patch.object(
            mon, "virsh_domstates", lambda: {"vm-d": "paused"}
        ):
            async with app.run_test(size=(150, 40)) as pilote:
                await pilote.pause()
                app._domstate["vm-d"] = "paused"
                del self.sondes[:]
                app._odoo_revu.clear()
                app._collect_table()
        self.assertEqual([], self.sondes)

    async def test_not_probed_while_installing(self):
        app = self.monte(fini=False)
        async with app.run_test(size=(150, 40)) as pilote:
            await pilote.pause()
            app._collect_table()
        self.assertEqual([], self.sondes)

    async def actions(self, pilote, bouton):
        await pilote.pause()
        await pilote.press("a")
        await pilote.pause()
        self.app.screen.query_one(bouton).press()
        await pilote.pause()
        await pilote.pause()

    async def test_db_restore_is_refused_with_a_message(self):
        self.app = self.monte()
        with (
            mock.patch.object(type(self.app), "_run_in_vm") as lance,
            mock.patch.object(type(self.app), "notify") as dit,
        ):
            async with self.app.run_test(size=(150, 40)) as pilote:
                await self.actions(pilote, "#a_dbrestore")
                ecran = type(self.app.screen).__name__
        lance.assert_not_called()
        self.assertNotEqual("ConfirmScreen", ecran)
        self.assertIn(
            t("Dolibarr VM: no Odoo database to restore."),
            [c.args[0] for c in dit.call_args_list],
        )

    async def test_the_credentials_button_reads_them_in_the_vm(self):
        self.app = self.monte()
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 60)) as pilote:
                await self.actions(pilote, "#a_doli_creds")
        vm, cmd, _titre = lance.call_args[0]
        self.assertEqual("vm-d", vm["name"])
        self.assertEqual(qd.credentials_cmd(), cmd)

    async def test_an_odoo_vm_has_no_credentials_button(self):
        self.app = self.monte()
        async with self.app.run_test(size=(150, 60)) as pilote:
            await pilote.pause()
            self.app._selected = "vm-o"
            await pilote.press("a")
            await pilote.pause()
            vm = self.app.screen._vm["name"]
            boutons = list(self.app.screen.query("#a_doli_creds"))
        self.assertEqual("vm-o", vm)
        self.assertEqual([], boutons)

    async def test_restart_runs_the_dolibarr_start(self):
        self.app = self.monte()
        with mock.patch.object(type(self.app), "_run_in_vm") as lance:
            async with self.app.run_test(size=(150, 40)) as pilote:
                await pilote.pause()
                await pilote.press("a")
                await pilote.pause()
                libelle = str(self.app.screen.query_one("#a_restart").label)
                self.app.screen.query_one("#a_restart").press()
                await pilote.pause()
                await pilote.pause()
        self.assertEqual(t("Restart Dolibarr"), libelle)
        vm, cmd, _titre = lance.call_args[0]
        self.assertEqual("vm-d", vm["name"])
        self.assertEqual(qd.restart_cmd(mon.EL_DIR), cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
