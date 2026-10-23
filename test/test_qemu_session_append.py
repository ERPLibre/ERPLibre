#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ajouter des VM à une session de suivi déjà ouverte.

Trois pièces : `launch_installs(session=...)` qui complète le manifeste,
`_qemu_deploie_spec(session=...)` qui crée sans terminal et rend un bilan, et
`_qemu_collect_spec_for_session` qui pose les questions avant. Le programme
`qemu_deploy_collect` relie la dernière au tableau par son code de sortie.
"""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_deploy_collect  # noqa: E402
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo import qemu_privilege  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


def _session(dossier, noms=("vm-a",)):
    """Écrit un session.json comme en laisse un premier déploiement."""
    logdir = Path(dossier) / "20260101-000000"
    logdir.mkdir(parents=True)
    manifest = {
        "branch": "develop",
        "started": 1000.0,
        "deploy_started": 900.0,
        "offline": False,
        "vms": [
            {"name": n, "ip": "192.0.2.1", "log": str(logdir / f"{n}.log")}
            for n in noms
        ],
    }
    chemin = logdir / "session.json"
    chemin.write_text(json.dumps(manifest))
    return chemin


class TestLaunchInstallsSession(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = tmp.name
        self.lances = []
        for nom, val in (
            ("_launch_one", lambda *a, **k: self.lances.append(a[3])),
            ("local_uuid", lambda nom: f"uuid-{nom}"),
            # Un nouveau dossier de session serait une régression : il se
            # verrait ici, à côté de celui de la session.
            ("session_dir", lambda: Path(self.dossier)),
        ):
            patcher = mock.patch.object(mon, nom, val)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _ajoute(self, session, noms, **kw):
        vms = [{"name": n, "ip": "192.0.2.9", "arch": "amd64"} for n in noms]
        return mon.launch_installs(vms, "autre", "true", session=session, **kw)

    def test_entries_are_appended_in_the_same_directory(self):
        session = _session(self.dossier)
        rendu = self._ajoute(str(session), ["vm-b", "vm-c"])
        self.assertEqual(str(session), rendu)
        manifest = json.loads(session.read_text())
        self.assertEqual(
            ["vm-a", "vm-b", "vm-c"], [v["name"] for v in manifest["vms"]]
        )
        for vm in manifest["vms"][1:]:
            self.assertEqual(session.parent, Path(vm["log"]).parent)
            self.assertTrue(Path(vm["log"]).is_file())
            self.assertEqual(f"uuid-{vm['name']}", vm["uuid"])
        self.assertEqual(["vm-b", "vm-c"], self.lances)
        self.assertEqual([session.parent], list(Path(self.dossier).iterdir()))

    def test_session_fields_are_kept(self):
        session = _session(self.dossier)
        self._ajoute(
            str(session), ["vm-b"], deploy_started=5.0, hors_ligne=True
        )
        manifest = json.loads(session.read_text())
        self.assertEqual(1000.0, manifest["started"])
        self.assertEqual(900.0, manifest["deploy_started"])
        self.assertFalse(manifest["offline"])
        self.assertEqual("develop", manifest["branch"])

    def test_duplicate_name_is_refused_before_any_launch(self):
        session = _session(self.dossier)
        avant = session.read_text()
        with self.assertRaises(ValueError):
            self._ajoute(str(session), ["vm-b", "vm-a"])
        with self.assertRaises(ValueError):
            self._ajoute(str(session), ["vm-b", "vm-b"])
        self.assertEqual([], self.lances)
        self.assertEqual(avant, session.read_text())

    def test_no_temporary_file_is_left(self):
        session = _session(self.dossier)
        self._ajoute(str(session), ["vm-b"])
        self.assertEqual(
            ["session.json", "vm-b.log"],
            sorted(p.name for p in session.parent.iterdir()),
        )

    def test_a_concurrent_append_is_not_lost(self):
        """Un autre ajout écrit la session pendant les lancements : il est
        relu sous verrou avant l'écriture, et non écrasé."""
        session = _session(self.dossier)

        def autre_ajout(*a, **k):
            manifest = json.loads(session.read_text())
            manifest["vms"].append({"name": "vm-z"})
            session.write_text(json.dumps(manifest))

        with mock.patch.object(mon, "_launch_one", autre_ajout):
            self._ajoute(str(session), ["vm-b"])
        noms = [v["name"] for v in json.loads(session.read_text())["vms"]]
        self.assertEqual(["vm-a", "vm-z", "vm-b"], noms)

    def test_without_session_a_new_directory_is_created(self):
        rendu = mon.launch_installs(
            [{"name": "vm-x", "ip": "192.0.2.9"}], "develop", "true"
        )
        self.assertEqual(Path(self.dossier), Path(rendu).parent.parent)
        manifest = json.loads(Path(rendu).read_text())
        self.assertEqual(["vm-x"], [v["name"] for v in manifest["vms"]])


def _vm(nom):
    return {
        "name": nom,
        "distro": "debian",
        "version": "13",
        "arch": "amd64",
        "ram": 2048,
        "vcpus": 2,
        "disk": "20G",
    }


class TestDeploieSpecSession(unittest.TestCase):
    """La création qui tourne derrière le suivi : sans App, sans invite."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = tmp.name
        self.todo = todo = TODO.__new__(TODO)
        self.jobs = []
        self.tui = []

        def cli(jobs, workers, stdin=None):
            self.jobs.extend(jobs)
            return [
                (n, 1 if n == "vm-bad" else 0, "", 1.0) for _, n, _ in jobs
            ]

        todo._qemu_deploy_jobs_cli = cli
        todo._qemu_deploy_jobs_tui = lambda jobs, w: self.tui.append(1)
        todo._qemu_resolve_ips = lambda noms, labels=None: {
            "vm-new": "192.0.2.10"
        }
        todo._qemu_import_module = mock.Mock(side_effect=RuntimeError)
        todo._ssh_private_key = lambda pub: ""
        todo._qemu_cache_active = lambda: False
        for nom, val in (
            ("_launch_one", lambda *a, **k: None),
            ("local_uuid", lambda nom: ""),
            ("session_dir", lambda: Path(self.dossier)),
            ("run_monitor", mock.Mock(side_effect=AssertionError)),
        ):
            patcher = mock.patch.object(mon, nom, val)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch(
            "script.todo.todo_prefs.get",
            lambda cle, *a: "tui" if cle == "qemu_deploy_progress" else None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _spec(self):
        return {
            "vms": [_vm("vm-new"), _vm("vm-noip"), _vm("vm-bad")],
            "existing": [],
            "install": None,
            "add_ssh_config": False,
            "parallelism": 2,
            "monitor": True,
            "ssh_key": "/k.pub",
        }

    def _joue(self, session):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.todo._qemu_deploie_spec(self._spec(), session=session)

    def test_session_mode(self):
        session = _session(self.dossier)
        bilan = self._joue(str(session))
        # La préférence « tui » ne vaut pas : une App ne s'ouvre pas dans
        # le suivi.
        self.assertEqual([], self.tui)
        self.assertEqual(3, len(self.jobs))
        for _, _, parts in self.jobs:
            self.assertEqual(["sudo", "-n"], parts[:2])
        mon.run_monitor.assert_not_called()
        self.assertEqual(["vm-bad"], bilan["failed"])
        self.assertEqual(["vm-noip"], bilan["no_ip"])
        self.assertEqual(["vm-new"], [e["name"] for e in bilan["added"]])
        manifest = json.loads(session.read_text())
        self.assertEqual(
            ["vm-a", "vm-new"], [v["name"] for v in manifest["vms"]]
        )

    def test_virsh_never_prompts_in_session_mode(self):
        """Hors terminal, un virsh sous « sudo » nu demanderait un mot de
        passe que personne ne voit : en mode session, il part sous -n."""
        vus = []
        resoudre = self.todo._qemu_resolve_ips

        def espion(noms, labels=None):
            vus.append(qemu_privilege.virsh_argv("domifaddr", "x")[:2])
            return resoudre(noms, labels)

        self.todo._qemu_resolve_ips = espion
        with mock.patch.object(qemu_privilege, "needs_sudo", lambda: True):
            self._joue(str(_session(self.dossier)))
            self.assertEqual([["sudo", "-n"]], vus)
            self.assertEqual(
                ["sudo", "virsh"], qemu_privilege.virsh_argv("list")[:2]
            )

    def test_without_session_nothing_changes(self):
        suivi = []
        self.todo._qemu_install_erplibre_monitored = (
            lambda *a, **k: suivi.append(k.get("session"))
        )
        self.todo._qemu_deploy_jobs_tui = lambda jobs, w: (
            self.jobs.extend(jobs) or [(n, 0, "", 1.0) for _, n, _ in jobs]
        )
        self.assertIsNone(self._joue(None))
        self.assertEqual(3, len(self.jobs))
        for _, _, parts in self.jobs:
            self.assertEqual("sudo", parts[0])
            self.assertNotEqual("-n", parts[1])
        self.assertEqual([None], suivi)


class TestCollecteSession(unittest.TestCase):
    def setUp(self):
        self.todo = todo = TODO.__new__(TODO)
        self.appels = []
        todo._qemu_import_module = lambda: object()
        todo._qemu_check_libvirt_group = lambda: None
        todo._qemu_check_kvm = lambda: None
        self.spec = {"vms": [_vm("vm-b")], "existing": ["vm-a", "vm-c"]}
        todo._qemu_deploy_form = lambda mod, dry: self.spec
        todo._qemu_offer_orphan_removal = lambda noms: (
            self.appels.append("orphelins") or True
        )
        todo._qemu_en_ligne_malgre_la_coupure = lambda: (
            self.appels.append("coupure") or True
        )
        todo._qemu_ensure_spec_ssh_key = lambda spec: (
            self.appels.append("cle") or True
        )

    def _collecte(self, suivis):
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch("subprocess.run") as run:
                run.return_value.returncode = 0
                with mock.patch("os.geteuid", return_value=1000):
                    spec = self.todo._qemu_collect_spec_for_session(suivis)
                self.sudo = [c.args[0] for c in run.call_args_list]
        return spec

    def test_spec_is_returned_after_every_step(self):
        spec = self._collecte(["vm-a"])
        self.assertIs(self.spec, spec)
        # La VM existante déjà suivie sort de la spec, l'autre reste.
        self.assertEqual(["vm-c"], spec["existing"])
        self.assertEqual(["orphelins", "coupure", "cle"], self.appels)
        self.assertEqual([["sudo", "-v"]], self.sudo)

    def test_offline_is_refused(self):
        self.spec["offline"] = True
        self.assertIsNone(self._collecte([]))
        self.assertEqual([], self.appels)

    def test_already_monitored_name_is_refused(self):
        self.assertIsNone(self._collecte(["vm-b"]))
        self.assertEqual([], self.appels)
        self.assertEqual([], self.sudo)

    def test_each_refusal_returns_none_without_sudo(self):
        for etape in (
            "_qemu_offer_orphan_removal",
            "_qemu_en_ligne_malgre_la_coupure",
            "_qemu_ensure_spec_ssh_key",
        ):
            with self.subTest(etape=etape):
                self.setUp()
                setattr(self.todo, etape, lambda *a: False)
                self.assertIsNone(self._collecte([]))
                self.assertEqual([], self.sudo)

    def test_existing_vms_alone_take_the_ticket_when_virsh_needs_sudo(self):
        self.spec = {"vms": [], "existing": ["vm-c"]}
        with mock.patch("script.todo.qemu_deploy.needs_sudo", lambda: True):
            self.assertIsNotNone(self._collecte([]))
        self.assertEqual([["sudo", "-v"]], self.sudo)

    def test_dropped_existing_vms_are_named(self):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            with mock.patch("subprocess.run") as run:
                run.return_value.returncode = 0
                with mock.patch("os.geteuid", return_value=1000):
                    self.todo._qemu_collect_spec_for_session(["vm-a"])
        self.assertIn("vm-a", sortie.getvalue())

    def test_cancelled_form_returns_none(self):
        self.spec = None
        self.assertIsNone(self._collecte([]))
        self.spec = {}
        self.assertIsNone(self._collecte([]))
        self.assertEqual([], self.appels)


class TestCollectProgram(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = os.path.join(tmp.name, "spec.json")

    def _main(self, rendu):
        recu = []

        class Faux:
            def _qemu_collect_spec_for_session(self, suivis):
                recu.append(suivis)
                if isinstance(rendu, BaseException):
                    raise rendu
                return rendu

        with contextlib.redirect_stderr(io.StringIO()):
            rc = qemu_deploy_collect.main(
                ["--out", self.out, "--monitored", "vm-a", "vm-b"], Faux
            )
        self.assertEqual([["vm-a", "vm-b"]], recu)
        return rc

    def test_spec_written_private(self):
        self.assertEqual(0, self._main({"vms": [], "t": (1, 2)}))
        self.assertEqual(
            {"vms": [], "t": [1, 2]}, json.loads(Path(self.out).read_text())
        )
        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.out).st_mode))

    def test_cancelled(self):
        self.assertEqual(1, self._main(None))
        self.assertFalse(os.path.exists(self.out))

    def test_error(self):
        self.assertEqual(2, self._main(RuntimeError("x")))

    def test_interrupted_is_cancelled(self):
        self.assertEqual(1, self._main(KeyboardInterrupt()))


class TestSudoNonInteractif(unittest.TestCase):
    def test_block_adds_dash_n_and_restores(self):
        with mock.patch.object(qemu_privilege, "needs_sudo", lambda: True):
            self.assertEqual(
                ["sudo", "virsh"], qemu_privilege.virsh_argv()[:2]
            )
            with qemu_privilege.sudo_non_interactif():
                self.assertEqual(
                    ["sudo", "-n", "virsh"], qemu_privilege.virsh_argv()[:3]
                )
                self.assertEqual("sudo -n ", qemu_privilege.sudo_prefix())
            self.assertEqual("sudo ", qemu_privilege.sudo_prefix())


if __name__ == "__main__":
    unittest.main()
