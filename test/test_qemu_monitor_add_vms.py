#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Touche « e » du suivi d'installation : ajouter des VM sans le quitter.

Le suivi monté sans affichage. Le formulaire (_collect_spec) et la création
(todo._qemu_deploie_spec) sont remplacés : aucun test ne lance sudo, virsh
ni un processus de formulaire.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from script.todo import qemu_install_monitor as mon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from async_case import AsyncCase  # noqa: E402

NOMS = ("vm-un", "vm-deux")


class FauxTodo:
    """Le TODO du menu, réduit à la création. Imprime comme le vrai : la
    sortie doit aboutir au journal de l'ajout."""

    def __init__(self, res=None, exc=None):
        self.res = res
        self.exc = exc
        self.appels = []

    def _qemu_deploie_spec(self, spec, session=None):
        self.appels.append((spec, session))
        print("[1/1] ✅ vm-trois")
        if self.exc:
            raise self.exc
        return self.res


class Base(AsyncCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for nom in NOMS + ("vm-trois",):
            (self.base / f"{nom}.log").write_text("===> install\nligne\n")
        manifeste = {
            "branch": "develop",
            "started": time.time() - 300,
            "vms": [self.entree(nom) for nom in NOMS],
        }
        self.manifest = self.base / "session.json"
        self.manifest.write_text(json.dumps(manifeste))
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("_port_open", lambda ip, port=8069, timeout=0.5: False),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)

    def entree(self, nom):
        return {
            "name": nom,
            "ip": "127.0.0.9",
            "arch": "amd64",
            "log": str(self.base / f"{nom}.log"),
            "ssh": f"ssh erplibre@{nom}",
            "disk": str(self.base / f"{nom}.qcow2"),
        }

    def app(self, todo=None):
        return mon.run_monitor(str(self.manifest), run_app=False, todo=todo)


class TestAddEntries(Base):
    async def test_a_new_entry_gets_its_row_title_and_offset(self):
        from textual.widgets import DataTable

        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            app._add_entries([self.entree("vm-trois")])
            await app._tick_table()
            await pilot.pause()
            table = app.query_one("#vms", DataTable)
            self.assertEqual(3, table.row_count)
            self.assertIn("(3 VM)", app.title)
            self.assertEqual(0, app._offsets["vm-trois"])
            self.assertEqual("3", str(table.get_cell("vm-trois", "seq")))
            # Le tick a relu le journal de la nouvelle VM : son état passe
            # de « - » (rien lu) au sablier.
            self.assertEqual("⏳", str(table.get_cell("vm-trois", "state")))

    async def test_a_monitored_name_is_signalled_not_added(self):
        from textual.widgets import DataTable

        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with mock.patch.object(app, "notify") as notify:
                app._add_entries([self.entree("vm-un")])
            self.assertEqual(2, app.query_one("#vms", DataTable).row_count)
            self.assertIn("vm-un", notify.call_args.args[0])


class TestActionAddVms(Base):
    async def test_without_todo_the_key_only_says_so(self):
        app = self.app()
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with (
                mock.patch.object(app, "notify") as notify,
                mock.patch.object(app, "_collect_spec") as collecte,
            ):
                await pilot.press("e")
            notify.assert_called_once()
            collecte.assert_not_called()

    async def test_a_cancelled_form_creates_nothing(self):
        todo = FauxTodo()
        app = self.app(todo)
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with mock.patch.object(
                app, "_collect_spec", return_value=None
            ) as collecte:
                await pilot.press("e")
            collecte.assert_called_once_with(list(NOMS))
            self.assertEqual([], todo.appels)
            self.assertFalse(app._adding)

    async def test_the_spec_is_deployed_into_this_session(self):
        from textual.widgets import DataTable, Static

        todo = FauxTodo(
            {"added": [self.entree("vm-trois")], "failed": [], "no_ip": []}
        )
        app = self.app(todo)
        spec = {"vms": [{"name": "vm-trois"}], "existing": []}
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with mock.patch.object(app, "_collect_spec", return_value=spec):
                await pilot.press("e")
                await app.workers.wait_for_complete()
                await pilot.pause()
            self.assertEqual([(spec, str(self.manifest))], todo.appels)
            self.assertEqual(3, app.query_one("#vms", DataTable).row_count)
            self.assertFalse(app._adding)
            self.assertFalse(app.query_one("#addbar", Static).display)
            journal = Path(app._add_log)
            self.assertEqual(self.base, journal.parent)
            self.assertIn("vm-trois", journal.read_text(encoding="utf-8"))

    async def test_a_failing_creation_is_reported_and_releases_the_key(self):
        todo = FauxTodo(exc=RuntimeError("sudo: a password is required"))
        app = self.app(todo)
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with (
                mock.patch.object(
                    app, "_collect_spec", return_value={"vms": []}
                ),
                mock.patch.object(app, "notify") as notify,
            ):
                await pilot.press("e")
                await app.workers.wait_for_complete()
                await pilot.pause()
            self.assertFalse(app._adding)
            self.assertEqual("error", notify.call_args.kwargs["severity"])
            self.assertIn("password", notify.call_args.args[0])

    async def test_a_second_press_during_an_add_is_refused(self):
        app = self.app(FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            app._adding = True
            with (
                mock.patch.object(app, "notify") as notify,
                mock.patch.object(app, "_collect_spec") as collecte,
            ):
                await pilot.press("e")
            notify.assert_called_once()
            collecte.assert_not_called()

    async def test_quitting_during_an_add_asks_first(self):
        app = self.app(FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            app._adding = True
            await pilot.press("q")
            await pilot.pause()
            self.assertEqual("ConfirmScreen", type(app.screen).__name__)
            self.assertTrue(app.is_running)


class TestCollectSpec(Base):
    async def test_the_form_runs_in_a_new_process_and_its_file_goes(self):
        app = self.app(FauxTodo())
        vu = {}

        def lance(argv, cwd=None, check=False):
            vu["argv"], vu["cwd"] = argv, cwd
            out = argv[argv.index("--out") + 1]
            vu["out"] = out
            vu["mode"] = os.stat(out).st_mode & 0o777
            Path(out).write_text(json.dumps({"vms": []}))
            return mock.Mock(returncode=0)

        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with (
                mock.patch.object(app, "suspend", mock.MagicMock()),
                mock.patch.object(mon.subprocess, "run", lance),
            ):
                spec = app._collect_spec(["vm-un", "vm-deux"])
        self.assertEqual({"vms": []}, spec)
        self.assertEqual(
            ["-m", "script.todo.qemu_deploy_collect"], vu["argv"][1:3]
        )
        self.assertEqual(["--monitored", "vm-un", "vm-deux"], vu["argv"][-3:])
        self.assertEqual(str(mon.REPO_ROOT), vu["cwd"])
        self.assertEqual(0o600, vu["mode"])
        self.assertFalse(os.path.exists(vu["out"]))

    async def test_a_cancelled_form_returns_none(self):
        app = self.app(FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with (
                mock.patch.object(app, "suspend", mock.MagicMock()),
                mock.patch.object(
                    mon.subprocess, "run", return_value=mock.Mock(returncode=1)
                ),
            ):
                self.assertIsNone(app._collect_spec([]))
        self.assertEqual([], list(self.base.glob(".ajout-*")))

    async def test_a_terminal_that_cannot_suspend_is_signalled(self):
        """Le pilote sans affichage ne sait pas céder le terminal : c'est
        le cas réel de SuspendNotSupported."""
        app = self.app(FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()
            with mock.patch.object(app, "notify") as notify:
                self.assertIsNone(app._collect_spec([]))
            self.assertEqual("error", notify.call_args.kwargs["severity"])
        self.assertEqual([], list(self.base.glob(".ajout-*")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
