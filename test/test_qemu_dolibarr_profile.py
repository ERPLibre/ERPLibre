#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil Dolibarr des VM : ce qui le reconnaît, où il est refusé, et
ce que le déploiement en fait."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.dolibarr import lib_dolibarr  # noqa: E402
from script.todo import qemu_dolibarr as qd  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

ODOO_18 = "make install_os && make install_odoo_18"


def spec(*vms, cmd=ODOO_18, offline=False, install=True):
    """Spec minimale : (nom, système, commande propre à la VM)."""
    return {
        "vms": [{"name": n, "distro": d, "install_cmd": c} for n, d, c in vms],
        "existing": [],
        "install": (
            {"branch": "develop", "cmd": cmd, "prod": False, "label": "x"}
            if install
            else None
        ),
        "offline": offline,
    }


class TestLaReconnaissance(unittest.TestCase):
    def test_the_profile_command_is_recognised(self):
        self.assertEqual(qd.APP_DOLIBARR, qd.profile_app(qd.INSTALL_CMD))
        self.assertEqual(
            qd.APP_DOLIBARR, qd.profile_app(f"  {qd.INSTALL_CMD}\n")
        )

    def test_anything_else_is_odoo(self):
        for cmd in (ODOO_18, "", None, "./script/proxmox/install_proxmox.sh"):
            self.assertEqual(qd.APP_ODOO, qd.profile_app(cmd), cmd)

    def test_a_manifest_entry_without_the_key_is_odoo(self):
        self.assertEqual(qd.APP_ODOO, qd.app_of({"name": "a"}))
        self.assertEqual(qd.APP_ODOO, qd.app_of(None))
        self.assertEqual(qd.APP_DOLIBARR, qd.app_of({"app": "dolibarr"}))


class TestLaCommande(unittest.TestCase):
    def test_it_installs_mariadb_dev_unattended_unbuffered(self):
        for piece in (
            "--mode dev",
            "--db mariadb",
            f"--instance {qd.INSTANCE}",
            f"--port {qd.PORT}",
            "--yes",
            " -u ",
            "./script/install/install_erplibre.sh",
        ):
            self.assertIn(piece, qd.INSTALL_CMD)

    def test_it_ends_by_starting_the_instance(self):
        self.assertTrue(
            qd.INSTALL_CMD.endswith(
                f"script/dolibarr/run.py start --instance {qd.INSTANCE}"
            )
        )

    def test_no_password_travels(self):
        self.assertNotIn(lib_dolibarr.ENV_ADMIN_PASSWORD, qd.INSTALL_CMD)
        self.assertNotIn("password", qd.INSTALL_CMD.lower())

    def test_it_never_installs_odoo(self):
        self.assertNotIn("install_odoo", qd.INSTALL_CMD)

    def test_it_parses_as_shell(self):
        rc = subprocess.run(["bash", "-n", "-c", qd.INSTALL_CMD]).returncode
        self.assertEqual(0, rc)


class TestLesSystemes(unittest.TestCase):
    def test_every_package_family_is_offered(self):
        for d in (
            "ubuntu",
            "debian",
            "fedora",
            "almalinux",
            "rocky",
            "opensuse",
            "arch",
        ):
            self.assertEqual("", qd.distro_refusal(d), d)

    def test_nixos_gets_the_declarative_reason(self):
        self.assertIn(
            t(lib_dolibarr.NIXOS_DECLARE), qd.distro_refusal("nixos")
        )

    def test_a_hypervisor_or_an_unknown_system_is_refused(self):
        for d in ("proxmox", "plan9", ""):
            self.assertIn(t(lib_dolibarr.NO_NATIVE), qd.distro_refusal(d))

    def test_the_table_follows_the_catalog(self):
        # Un système ajouté au catalogue doit être classé exprès : offert
        # (dans la table) ou refusé (nixos, proxmox).
        mod = TODO.__new__(TODO)._qemu_import_module()
        self.assertEqual(
            set(mod.DISTROS) - {"nixos", "proxmox"}, set(qd.DISTRO_FAMILY)
        )


class TestLesRefus(unittest.TestCase):
    def test_a_supported_system_passes(self):
        s = spec(("a", "ubuntu", ""), cmd=qd.INSTALL_CMD)
        self.assertEqual([], qd.install_refusals(s))

    def test_nixos_is_refused_by_name(self):
        s = spec(("a", "ubuntu", ""), ("b", "nixos", ""), cmd=qd.INSTALL_CMD)
        refus = qd.install_refusals(s)
        self.assertEqual(1, len(refus))
        self.assertTrue(refus[0].startswith("b: "))

    def test_a_per_vm_choice_counts(self):
        s = spec(("b", "nixos", qd.INSTALL_CMD))
        self.assertEqual(1, len(qd.install_refusals(s)))

    def test_odoo_on_nixos_is_not_refused_here(self):
        self.assertEqual([], qd.install_refusals(spec(("b", "nixos", ""))))

    def test_offline_is_refused(self):
        s = spec(("a", "ubuntu", ""), cmd=qd.INSTALL_CMD, offline=True)
        self.assertIn(t(qd.OFFLINE_REFUSAL), qd.install_refusals(s))

    def test_offline_odoo_is_left_to_its_own_checks(self):
        s = spec(("a", "ubuntu", ""), offline=True)
        self.assertEqual([], qd.install_refusals(s))

    def test_nothing_installed_nothing_refused(self):
        s = spec(("b", "nixos", qd.INSTALL_CMD), install=False)
        self.assertEqual([], qd.install_refusals(s))


class TestLeProfil(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_it_is_in_the_list(self):
        self.assertIn(
            (t(qd.PROFILE_LABEL), qd.INSTALL_CMD),
            self.todo._qemu_install_profiles(),
        )

    def test_it_clones_erplibre_so_it_keeps_the_disk_margin(self):
        self.assertTrue(
            self.todo._qemu_installs_erplibre("develop", qd.INSTALL_CMD)
        )

    def test_production_never_applies(self):
        self.assertFalse(self.todo._qemu_effective_prod(True, qd.INSTALL_CMD))
        self.assertTrue(self.todo._qemu_effective_prod(True, ODOO_18))
        self.assertFalse(self.todo._qemu_effective_prod(False, ODOO_18))


class TestLaCommandeDistante(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _cmd(self, final, prod):
        return self.todo._qemu_erplibre_remote_cmd("develop", final, prod)

    def test_production_still_clones_in_home(self):
        cmd = self._cmd(qd.INSTALL_CMD, prod=True)
        self.assertIn(f"cd ~/git/erplibre && {qd.INSTALL_CMD}", cmd)
        self.assertNotIn("/opt/erplibre", cmd)

    def test_no_odoo_service(self):
        self.assertNotIn("erplibre.service", self._cmd(qd.INSTALL_CMD, False))

    def test_odoo_production_is_unchanged(self):
        self.assertIn("/opt/erplibre", self._cmd(ODOO_18, prod=True))

    def test_no_reboot_after(self):
        from script.todo import qemu_install_monitor as mon

        cmd = self._cmd(qd.INSTALL_CMD, False)
        self.assertEqual("", mon.reboot_expected(cmd))

    def test_it_parses_as_shell(self):
        cmd = self._cmd(qd.INSTALL_CMD, True)
        self.assertEqual(
            0, subprocess.run(["bash", "-n", "-c", cmd]).returncode
        )


class TestLeGuide(unittest.TestCase):
    """Les arguments du guide de connexion, VM par VM."""

    def _parts(self, cmd, prod):
        vm = {
            "name": "essai",
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "vcpus": 2,
            "ram": 2048,
            "disk": "20G",
            "desktop": "",
            "branch": "",
            "install_cmd": "",
            "install_label": "",
        }
        s = {
            "vms": [vm],
            "existing": [],
            "ssh_key": "",
            "timezone": "",
            "desktop": "",
            "vm_tools": (),
            "python_provider": "",
            "app_store": "deb",
            "install": {
                "branch": "develop",
                "prod": prod,
                "label": "x",
                "monitor": True,
                "cmd": cmd,
            },
            "monitor": True,
            "add_ssh_config": True,
            "parallelism": 1,
            "res_label": "x1",
        }
        return TODO.__new__(TODO)._qemu_deploy_parts_for(vm, s, dry_run=True)

    def test_a_dolibarr_vm_gets_its_guide_at_home(self):
        parts = self._parts(qd.INSTALL_CMD, prod=True)
        self.assertEqual("dolibarr", parts[parts.index("--app") + 1])
        self.assertEqual(
            "~/git/erplibre", parts[parts.index("--erplibre-dir") + 1]
        )
        self.assertNotIn("--erplibre-make", parts)

    def test_an_odoo_vm_passes_no_app(self):
        self.assertNotIn("--app", self._parts(ODOO_18, prod=False))


class TestLInvite(unittest.TestCase):
    def _choisit(self, reponses, systems):
        todo = TODO.__new__(TODO)
        rang = next(
            str(i)
            for i, (_l, c) in enumerate(todo._qemu_install_profiles(), 1)
            if c == qd.INSTALL_CMD
        )
        suite = iter(rang if r == "doli" else r for r in reponses)
        with (
            contextlib.redirect_stdout(io.StringIO()) as sortie,
            mock.patch("builtins.input", lambda _p="": next(suite)),
        ):
            choix = todo._qemu_pick_install_profile("", systems=systems)
        return choix, sortie.getvalue()

    def test_a_supported_system_takes_it(self):
        choix, _ = self._choisit(["doli"], ("ubuntu",))
        self.assertEqual(qd.INSTALL_CMD, choix[1])

    def test_nixos_says_why_and_asks_again(self):
        choix, sortie = self._choisit(["doli", "1"], ("ubuntu", "nixos"))
        self.assertIn("odoo_18", choix[1])
        self.assertIn("✗ nixos: ", sortie)
        self.assertIn(t(lib_dolibarr.NIXOS_DECLARE), sortie)


class TestLesGardes(unittest.TestCase):
    """Le déploiement refuse avant de créer quoi que ce soit, quelle que
    soit la voie qui a produit la spec."""

    def test_the_qemu_run_refuses_before_anything(self):
        todo = TODO.__new__(TODO)
        todo._qemu_ensure_spec_ssh_key = mock.Mock(return_value=True)
        todo._qemu_deploie_spec = mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            todo._qemu_run_spec(spec(("b", "nixos", ""), cmd=qd.INSTALL_CMD))
        todo._qemu_ensure_spec_ssh_key.assert_not_called()
        todo._qemu_deploie_spec.assert_not_called()
        self.assertIn("b: ", sortie.getvalue())

    def test_a_valid_spec_still_runs(self):
        todo = TODO.__new__(TODO)
        todo._qemu_ensure_spec_ssh_key = mock.Mock(return_value=True)
        todo._qemu_sans_internet = lambda _o: contextlib.nullcontext(False)
        todo._qemu_deploie_spec = mock.Mock()
        todo._qemu_run_spec(spec(("a", "ubuntu", ""), cmd=qd.INSTALL_CMD))
        todo._qemu_deploie_spec.assert_called_once()

    def test_the_proxmox_run_refuses_too(self):
        todo = TODO.__new__(TODO)
        todo._pve_deploy_spec = mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            todo._pve_run_spec(
                {"target": "pve"},
                spec(("a", "ubuntu", ""), cmd=qd.INSTALL_CMD, offline=True),
                None,
            )
        todo._pve_deploy_spec.assert_not_called()


class TestLeManifeste(unittest.TestCase):
    def test_each_vm_names_its_app(self):
        from script.todo import qemu_install_monitor as mon

        vu = {}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manifeste = Path(tmp.name) / "session.json"
        manifeste.write_text(json.dumps({"vms": []}))

        def lance(vms, branch, remote, **_kw):
            vu["vms"] = vms
            return str(manifeste)

        todo = TODO.__new__(TODO)
        todo._qemu_import_module = lambda: None
        meta = ("ubuntu", "24.04", "amd64")
        with (
            mock.patch.object(mon, "launch_installs", lance),
            mock.patch.object(mon, "run_monitor", lambda m, **_k: None),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._qemu_install_erplibre_monitored(
                ["a", "b"],
                "develop",
                {"a": "192.0.2.1", "b": "192.0.2.2"},
                {"a": qd.INSTALL_CMD, "b": ODOO_18},
                meta={"a": meta, "b": meta},
            )
        par = {v["name"]: v for v in vu["vms"]}
        self.assertEqual("dolibarr", par["a"]["app"])
        self.assertNotIn("app", par["b"])

    def test_a_fleet_wide_command_counts(self):
        from script.todo import qemu_install_monitor as mon

        vu = {}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manifeste = Path(tmp.name) / "session.json"
        manifeste.write_text(json.dumps({"vms": []}))
        todo = TODO.__new__(TODO)
        todo._qemu_import_module = lambda: None
        with (
            mock.patch.object(
                mon,
                "launch_installs",
                lambda vms, *_a, **_k: (
                    vu.setdefault("vms", vms) and str(manifeste)
                ),
            ),
            mock.patch.object(mon, "run_monitor", lambda m, **_k: None),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._qemu_install_erplibre_monitored(
                ["a"],
                "develop",
                {"a": "192.0.2.1"},
                qd.INSTALL_CMD,
                meta={"a": ("debian", "12", "amd64")},
            )
        self.assertEqual("dolibarr", vu["vms"][0]["app"])

    def test_launch_installs_keeps_it(self):
        from script.todo import qemu_install_monitor as mon

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with (
            mock.patch.object(mon, "_launch_one", lambda *a, **k: None),
            mock.patch.object(mon, "session_dir", lambda: Path(tmp.name)),
            mock.patch.object(mon, "local_uuid", lambda _n: ""),
        ):
            chemin = mon.launch_installs(
                [
                    {"name": "a", "ip": "192.0.2.1", "app": "dolibarr"},
                    {"name": "b", "ip": "192.0.2.2"},
                ],
                "develop",
                "true",
            )
        par = {
            v["name"]: v for v in json.loads(Path(chemin).read_text())["vms"]
        }
        self.assertEqual("dolibarr", par["a"]["app"])
        self.assertNotIn("app", par["b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
