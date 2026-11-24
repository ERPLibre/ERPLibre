#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le registre des ERP installés en VM : ses descripteurs, la
reconnaissance d'un profil par sa commande, les refus d'une spec, et
l'absence de toute comparaison à une clé d'ERP hors du registre."""

import dataclasses
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import qemu_erp as erp  # noqa: E402
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.qemu_erp import dolibarr as qd  # noqa: E402
from script.todo.qemu_erp import odoo  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

ODOO_18 = "make install_os && make install_odoo_18"
ODOO_VM = {"name": "vm-o", "ip": "192.0.2.8"}
DOLI_VM = {"name": "vm-d", "ip": "192.0.2.7", "app": "dolibarr"}


def spec(*vms, cmd=ODOO_18, offline=False, install=True):
    """Spec minimale : (nom, système, commande propre à la VM)."""
    return {
        "vms": [{"name": n, "distro": d, "install_cmd": c} for n, d, c in vms],
        "install": (
            {"branch": "develop", "cmd": cmd, "prod": False}
            if install
            else None
        ),
        "offline": offline,
    }


def refus_avant_registre(s):
    """install_refusals tel qu'il s'écrivait pour le seul Dolibarr : la
    référence de la parité."""
    install = s.get("install")
    if not install:
        return []
    refus = []
    dolibarr = False
    for vm in s.get("vms") or []:
        cmd = vm.get("install_cmd") or install.get("cmd")
        if (cmd or "").strip() != qd.INSTALL_CMD:
            continue
        dolibarr = True
        raison = qd.distro_refusal(vm.get("distro", ""))
        if raison:
            refus.append(f"{vm['name']}: {raison}")
    if dolibarr and s.get("offline"):
        refus.append(t(qd.OFFLINE_REFUSAL))
    return refus


class TestLeRegistre(unittest.TestCase):
    def test_odoo_first_then_dolibarr(self):
        self.assertEqual(
            [erp.APP_ODOO, erp.APP_DOLIBARR], [a.key for a in erp.REGISTRY]
        )
        self.assertIs(odoo.APP, erp.DEFAULT)
        self.assertIs(qd.APP, erp.REGISTRY[1])

    def test_keys_are_unique(self):
        cles = [a.key for a in erp.REGISTRY]
        self.assertEqual(len(cles), len(set(cles)))

    def test_get_falls_back_to_odoo(self):
        self.assertIs(qd.APP, erp.get("dolibarr"))
        for cle in ("odoo", "", None, "inconnu"):
            self.assertIs(odoo.APP, erp.get(cle), cle)

    def test_descriptors_are_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            qd.APP.port = 1

    def test_either_module_imports_first(self):
        # Le registre se bâtit en fin de paquet : aucun ordre d'import ne
        # doit tomber sur un module à moitié initialisé.
        for module in (
            "script.todo.qemu_erp.dolibarr",
            "script.todo.qemu_erp.odoo",
            "script.todo.qemu_erp",
        ):
            code = (
                f"import {module}, script.todo.qemu_erp as e;"
                " print(','.join(a.key for a in e.REGISTRY))"
            )
            r = subprocess.run(
                [sys.executable, "-c", code],
                cwd=RACINE,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual("odoo,dolibarr", r.stdout.strip())


class TestLaReconnaissance(unittest.TestCase):
    def test_every_listed_profile_maps_to_its_erp(self):
        profils = TODO.__new__(TODO)._qemu_install_profiles()
        self.assertTrue(profils)
        for _label, cmd in profils:
            attendu = (
                erp.APP_DOLIBARR if cmd == qd.INSTALL_CMD else erp.APP_ODOO
            )
            self.assertEqual(attendu, erp.profile_app(cmd), cmd)
            self.assertEqual(attendu, erp.app_for_cmd(cmd).key, cmd)

    def test_each_declared_profile_is_listed_once(self):
        cmds = [c for _l, c in TODO.__new__(TODO)._qemu_install_profiles()]
        for app in erp.REGISTRY:
            if app.install_cmd:
                self.assertEqual(1, cmds.count(app.install_cmd), app.key)

    def test_surrounding_blanks_still_match(self):
        self.assertIs(qd.APP, erp.app_for_cmd(f"  {qd.INSTALL_CMD}\n"))

    def test_a_substring_does_not_match(self):
        self.assertIs(odoo.APP, erp.app_for_cmd(qd.INSTALL_CMD + " && true"))

    def test_no_command_is_odoo(self):
        for cmd in ("", None):
            self.assertIs(odoo.APP, erp.app_for_cmd(cmd))

    def test_app_of_defaults_to_odoo(self):
        self.assertEqual(erp.APP_ODOO, erp.app_of(None))
        self.assertEqual(erp.APP_ODOO, erp.app_of({}))
        self.assertEqual(erp.APP_ODOO, erp.app_of({"app": ""}))
        self.assertEqual(erp.APP_DOLIBARR, erp.app_of(DOLI_VM))
        self.assertIs(odoo.APP, erp.app_for_entry(ODOO_VM))
        self.assertIs(qd.APP, erp.app_for_entry(DOLI_VM))
        self.assertIs(odoo.APP, erp.app_for_entry({"app": "inconnu"}))

    def test_the_module_reexports_the_registry_helpers(self):
        self.assertIs(erp.profile_app, qd.profile_app)
        self.assertIs(erp.app_of, qd.app_of)
        self.assertIs(erp.install_refusals, qd.install_refusals)


class TestLaPariteDesRefus(unittest.TestCase):
    CAS = (
        spec(("a", "ubuntu", "")),
        spec(("a", "nixos", "")),
        spec(("a", "ubuntu", ""), offline=True),
        spec(("a", "ubuntu", ""), cmd=qd.INSTALL_CMD),
        spec(("a", "nixos", ""), ("b", "proxmox", ""), cmd=qd.INSTALL_CMD),
        spec(("a", "nixos", ""), ("b", "arch", ""), cmd=qd.INSTALL_CMD),
        spec(
            ("a", "nixos", ""),
            ("b", "fedora", ""),
            cmd=qd.INSTALL_CMD,
            offline=True,
        ),
        spec(("a", "ubuntu", ""), ("b", "nixos", qd.INSTALL_CMD)),
        spec(
            ("a", "plan9", qd.INSTALL_CMD),
            ("b", "debian", qd.INSTALL_CMD),
            offline=True,
        ),
        spec(("a", "nixos", qd.INSTALL_CMD), install=False),
        spec(cmd=qd.INSTALL_CMD, offline=True),
    )

    def test_same_refusals_in_the_same_order(self):
        for s in self.CAS:
            self.assertEqual(
                refus_avant_registre(s), erp.install_refusals(s), s
            )

    def test_the_offline_refusal_comes_once(self):
        s = spec(
            ("a", "ubuntu", ""),
            ("b", "debian", ""),
            cmd=qd.INSTALL_CMD,
            offline=True,
        )
        self.assertEqual([t(qd.OFFLINE_REFUSAL)], erp.install_refusals(s))


class TestLesDescripteurs(unittest.TestCase):
    def test_odoo_is_reached_on_8069_and_restarted_by_its_service(self):
        a = odoo.APP
        self.assertFalse(a.guest_probe)
        self.assertEqual((8069, 18069), (a.port, a.tunnel_port))
        self.assertIsNone(a.restart_cmd)
        self.assertIsNone(a.credentials_cmd)
        self.assertIsNone(a.install_cmd)
        self.assertFalse(a.dev_only)
        self.assertIsNone(a.offline_refusal)
        self.assertEqual(mon.restart_odoo_cmd(), mon.restart_cmd_for(ODOO_VM))

    def test_odoo_refuses_no_system_and_no_action(self):
        for d in ("ubuntu", "nixos", "proxmox", ""):
            self.assertEqual("", odoo.APP.distro_refusal(d))
        for kind, parts in (("dbrestore", ()), ("update", ["python"])):
            self.assertEqual("", odoo.APP.action_refusal(kind, parts))

    def test_dolibarr_carries_its_module_values(self):
        a = qd.APP
        self.assertTrue(a.guest_probe)
        self.assertTrue(a.dev_only)
        self.assertEqual((qd.PORT, qd.TUNNEL_PORT), (a.port, a.tunnel_port))
        self.assertEqual(qd.INSTALL_CMD, a.install_cmd)
        self.assertEqual(qd.PROFILE_LABEL, a.label)
        self.assertEqual(qd.PROD_NOTE, a.prod_note)
        self.assertEqual(qd.OFFLINE_REFUSAL, a.offline_refusal)
        self.assertIs(qd.distro_refusal, a.distro_refusal)
        self.assertIs(qd.restart_cmd, a.restart_cmd)
        self.assertIs(qd.credentials_cmd, a.credentials_cmd)

    def test_the_monitor_reads_the_descriptor(self):
        self.assertIn(
            f"http://127.0.0.1:{qd.APP.port}/",
            mon.dolibarr_probe_argv(DOLI_VM)[-1],
        )
        argv, url = mon.web_target(DOLI_VM)
        self.assertIn(f"{qd.APP.tunnel_port}:127.0.0.1:{qd.APP.port}", argv)
        self.assertEqual(f"http://127.0.0.1:{qd.APP.tunnel_port}/", url)
        self.assertEqual(
            (None, "http://192.0.2.8:8069"), mon.web_target(ODOO_VM)
        )

    def test_the_web_hints_keep_their_text(self):
        self.assertEqual(
            [
                t("Dolibarr does not answer in the VM. Check it there:"),
                "   ssh x 'cd ~/el && python3 script/dolibarr/run.py status'",
            ],
            qd.APP.web_hint("ssh x", "~/el"),
        )
        (ligne,) = odoo.APP.web_hint("ssh x", "~/el")
        self.assertIn(":8069", ligne)

    def test_every_i18n_key_is_translated(self):
        for a in erp.REGISTRY:
            for champ in (
                "label",
                "prod_note",
                "offline_refusal",
                "restart_button",
                "restart_title",
                "credentials_button",
                "credentials_title",
            ):
                cle = getattr(a, champ)
                if cle is not None:
                    self.assertIn(cle, todo_i18n.TRANSLATIONS, (a.key, champ))

    def test_a_credentials_action_has_its_labels(self):
        for a in erp.REGISTRY:
            if a.credentials_cmd is not None:
                self.assertTrue(a.credentials_button, a.key)
                self.assertTrue(a.credentials_title, a.key)

    def test_a_dev_only_erp_says_why(self):
        for a in erp.REGISTRY:
            if a.dev_only:
                self.assertTrue(a.prod_note, a.key)


class TestPlusDeComparaisonHorsDuRegistre(unittest.TestCase):
    """Un ERP de plus est un descripteur de plus : les appelants lisent ses
    champs, aucun ne compare une clé d'ERP autre qu'Odoo."""

    def test_no_dolibarr_key_outside_the_registry(self):
        motif = re.compile(
            r"APP_DOLIBARR|qemu_dolibarr|[=!]=\s*[\"']dolibarr[\"']"
        )
        trouves = []
        for chemin in sorted((RACINE / "script" / "todo").glob("*.py")):
            for n, ligne in enumerate(
                chemin.read_text(encoding="utf-8").splitlines(), 1
            ):
                if motif.search(ligne):
                    trouves.append(f"{chemin.name}:{n}: {ligne.strip()}")
        self.assertEqual([], trouves)


if __name__ == "__main__":
    unittest.main()
