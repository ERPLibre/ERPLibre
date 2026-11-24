#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le préflight firmware de deploy_qemu.py.

Avant tout téléchargement et toute écriture de disque, un domaine jetable
est démarré avec les réglages d'amorçage de la VM. Ces tests gardent :

- la sonde reçoit exactement les arguments d'amorçage de virt_install ;
- le domaine de sonde est retiré après un échec, un succès ou Ctrl+C, et
  JAMAIS quand « define » a échoué — un homonyme préexistant reste intact ;
- l'état se lit sous locale C, borné par « timeout » ;
- le préflight est sauté sans « --boot », avec --no-preflight et en
  dry-run, et il passe avant le téléchargement et le disque ;
- l'échec affiche l'ordre des descripteurs et signale le firmware chargé
  en mémoire qui passe avant le premier en flash.
"""

import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.argv = ["todo.py"]
RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

XML = "<domain type='kvm'><name>x</name></domain>"


class FauxRunner:
    """Retient chaque appel et répond selon la sous-commande virsh."""

    def __init__(self, reponses=None, leve=None, dry_run=False):
        self.dry_run = dry_run
        self.use_sudo = False
        self.reponses = {"print-xml": (0, XML), **(reponses or {})}
        self.leve = leve or {}
        self.appels = []

    @staticmethod
    def sous_commande(cmd):
        if "--print-xml" in cmd:
            return "print-xml"
        if cmd[:1] == ["rm"]:
            return "rm"
        for mot in ("define", "start", "domstate", "destroy", "undefine"):
            if mot in cmd:
                return mot
        return "?"

    def run(self, cmd, *, privileged=False, check=True, capture=False):
        sc = self.sous_commande(cmd)
        self.appels.append((sc, list(cmd), privileged, check, capture))
        if sc in self.leve:
            raise self.leve[sc]()
        if self.dry_run:
            return (0, "") if capture else None
        return self.reponses.get(sc, (0, ""))

    def faits(self):
        return [a[0] for a in self.appels]


def _sonder(runner):
    with (
        mock.patch.object(DQ.shutil, "which", return_value="/bin/timeout"),
        mock.patch.object(DQ, "virtinst_env", return_value=["env"]),
        mock.patch.object(DQ, "sonde_nom", return_value="erplibre-fwprobe-x"),
        redirect_stdout(io.StringIO()),
    ):
        return DQ.sonde_firmware("ubuntu24.04", ["--boot", "u"], runner)


class AmorcageArgs(unittest.TestCase):
    def test_amd64_uefi(self):
        self.assertEqual(
            ["--boot", DQ.UEFI_BOOT], DQ.amorcage_args("amd64", False, False)
        )

    def test_amd64_bios(self):
        self.assertEqual([], DQ.amorcage_args("amd64", True, False))

    def test_arm64(self):
        self.assertEqual(
            [
                "--arch",
                "aarch64",
                "--machine",
                "virt",
                "--boot",
                DQ.UEFI_BOOT,
                "--virt-type",
                "qemu",
            ],
            DQ.amorcage_args("arm64", False, True),
        )
        # arm64 n'a pas de BIOS : --bios n'y change rien.
        self.assertIn("--boot", DQ.amorcage_args("arm64", True, False))

    def test_s390x(self):
        self.assertEqual(
            [
                "--arch",
                "s390x",
                "--machine",
                "s390-ccw-virtio",
                "--virt-type",
                "qemu",
            ],
            DQ.amorcage_args("s390x", False, True),
        )

    def test_emulated_appends_virt_type(self):
        self.assertEqual(
            ["--boot", DQ.UEFI_BOOT, "--virt-type", "qemu"],
            DQ.amorcage_args("amd64", False, True),
        )


class Emulation(unittest.TestCase):
    def _emu(self, arch, kvm):
        with (
            mock.patch.object(DQ, "host_arch", return_value="amd64"),
            mock.patch.object(DQ, "kvm_available", return_value=kvm),
        ):
            return DQ.emulation(arch)

    def test_foreign_arch(self):
        self.assertEqual((True, False), self._emu("arm64", True))
        self.assertEqual((True, False), self._emu("arm64", False))

    def test_no_kvm(self):
        self.assertEqual((True, True), self._emu("amd64", False))

    def test_native_kvm(self):
        self.assertEqual((False, False), self._emu("amd64", True))


class SondeCmd(unittest.TestCase):
    def _virt_install_argv(self, arch, bios):
        args = SimpleNamespace(
            name="vm-a",
            memory=4096,
            vcpus=2,
            arch=arch,
            network="network=default,model=virtio",
            graphics="none",
            desktop=False,
            gpu="off",
            gpu_node=None,
            attach_console=False,
            bios=bios,
        )
        lances = []

        class Runner:
            dry_run = False
            use_sudo = False

            def run(self, cmd, *, privileged=False, check=True, capture=False):
                lances.append(list(cmd))
                return (0, "") if capture else None

        with (
            mock.patch.object(DQ, "host_arch", return_value="amd64"),
            mock.patch.object(DQ, "kvm_available", return_value=True),
            mock.patch.object(DQ, "os") as faux_os,
            redirect_stdout(io.StringIO()),
        ):
            faux_os.getuid.return_value = 1000
            DQ.virt_install(
                args,
                Path("/tmp/d.qcow2"),
                Path("/tmp/s.iso"),
                "ubuntu24.04",
                Runner(),
            )
        return next(c for c in lances if "virt-install" in c)

    def test_probe_mirrors_virt_install_boot_args(self):
        for arch, bios in (("amd64", False), ("arm64", False)):
            with self.subTest(arch=arch):
                cmd = self._virt_install_argv(arch, bios)
                debut = cmd.index("--arch" if "--arch" in cmd else "--boot")
                fin = cmd.index("--noautoconsole")
                queue = cmd[debut:fin]
                emulated = arch != "amd64"
                self.assertEqual(DQ.amorcage_args(arch, bios, emulated), queue)
                sonde = DQ.sonde_xml_cmd(
                    "erplibre-fwprobe-x", "ubuntu24.04", queue
                )
                self.assertEqual(queue, sonde[-len(queue) :])
                for paire in (
                    ["--disk", "none"],
                    ["--network", "none"],
                    ["--graphics", "none"],
                    ["--memory", "512"],
                    ["--connect", DQ.LIBVIRT_URI],
                ):
                    i = sonde.index(paire[0])
                    self.assertEqual(paire, sonde[i : i + 2])
                self.assertIn("--print-xml", sonde)
                texte = " ".join(sonde)
                self.assertNotIn("accel3d", texte)
                self.assertNotIn("egl-headless", texte)


class SondeNom(unittest.TestCase):
    def test_prefix_and_uniqueness(self):
        noms = {DQ.sonde_nom() for _ in range(50)}
        self.assertEqual(50, len(noms))
        for nom in noms:
            self.assertTrue(nom.startswith(DQ.SONDE_PREFIXE))
            self.assertRegex(nom[len(DQ.SONDE_PREFIXE) :], r"^[0-9a-f]{8}$")


class XmlDuDomaine(unittest.TestCase):
    def test_strips_warnings(self):
        corps = '<domain type="kvm"><name>n</name></domain>'
        self.assertEqual(
            corps,
            DQ.xml_du_domaine(f"WARNING  x\n{corps}\nWARNING  y\n"),
        )

    def test_no_domain(self):
        self.assertEqual("", DQ.xml_du_domaine("ERROR  something"))


class SondeCause(unittest.TestCase):
    def test_causes(self):
        self.assertEqual(
            "apparmor",
            DQ.sonde_cause("error: internal error: virt-aa-helper failed"),
        )
        self.assertEqual("firmware", DQ.sonde_cause("Unable to find firmware"))
        self.assertEqual("delai", DQ.sonde_cause(f"\n{DQ.SONDE_DEPASSEE}"))
        self.assertEqual("", DQ.sonde_cause("cannot allocate memory"))


class SondeFirmware(unittest.TestCase):
    def _nettoyage_apres(self, runner, etape):
        faits = runner.faits()
        return faits[faits.index(etape) + 1 :]

    def test_cleanup_runs_when_start_fails(self):
        runner = FauxRunner(
            {
                "start": (
                    1,
                    "error: internal error: virt-aa-helper: skipped"
                    " restricted file",
                )
            }
        )
        ok, sortie = _sonder(runner)
        self.assertFalse(ok)
        self.assertIn("virt-aa-helper", sortie)
        self.assertEqual(
            ["destroy", "undefine", "rm"],
            self._nettoyage_apres(runner, "start"),
        )
        par_nom = {a[0]: a for a in runner.appels}
        nom = "erplibre-fwprobe-x"
        self.assertEqual(["destroy", nom], par_nom["destroy"][1][-2:])
        self.assertEqual(
            ["undefine", nom, "--nvram"], par_nom["undefine"][1][-3:]
        )
        rm = par_nom["rm"][1]
        self.assertIn(f"/var/log/libvirt/qemu/{nom}.log", rm)
        self.assertIn(f"/var/lib/libvirt/qemu/nvram/{nom}_VARS.fd", rm)
        for sc in ("destroy", "undefine", "rm"):
            self.assertFalse(par_nom[sc][3], sc)
            self.assertTrue(par_nom[sc][4], sc)
        for sc, cmd, privileged, _check, capture in runner.appels:
            self.assertTrue(privileged, sc)
            self.assertTrue(capture, sc)
            if sc != "rm":
                self.assertEqual("timeout", cmd[0], sc)

    def test_cleanup_runs_on_success(self):
        runner = FauxRunner({"domstate": (0, "running\n")})
        self.assertEqual((True, ""), _sonder(runner))
        self.assertEqual(
            ["destroy", "undefine", "rm"],
            self._nettoyage_apres(runner, "domstate"),
        )

    def test_cleanup_runs_on_exception(self):
        runner = FauxRunner(leve={"start": KeyboardInterrupt})
        with self.assertRaises(KeyboardInterrupt):
            _sonder(runner)
        self.assertEqual(
            ["destroy", "undefine", "rm"],
            self._nettoyage_apres(runner, "start"),
        )

    def test_no_cleanup_when_define_failed(self):
        runner = FauxRunner({"define": (1, "error: already exists")})
        ok, sortie = _sonder(runner)
        self.assertFalse(ok)
        self.assertIn("already exists", sortie)
        self.assertEqual(["print-xml", "define"], runner.faits())

    def test_no_define_without_xml(self):
        runner = FauxRunner({"print-xml": (1, "ERROR  osinfo inconnu")})
        ok, _sortie = _sonder(runner)
        self.assertFalse(ok)
        self.assertEqual(["print-xml"], runner.faits())

    def test_domstate_not_running_fails(self):
        runner = FauxRunner({"domstate": (0, "shut off\n")})
        ok, _sortie = _sonder(runner)
        self.assertFalse(ok)
        self.assertEqual(
            ["destroy", "undefine", "rm"],
            self._nettoyage_apres(runner, "domstate"),
        )

    def test_domstate_reads_in_c_locale(self):
        runner = FauxRunner({"domstate": (0, "running\n")})
        _sonder(runner)
        cmd = next(a[1] for a in runner.appels if a[0] == "domstate")
        i = cmd.index("env")
        self.assertEqual(["env", "LC_ALL=C", "LANG=C"], cmd[i : i + 3])

    def test_timeout_is_marked(self):
        runner = FauxRunner({"start": (124, "")})
        ok, sortie = _sonder(runner)
        self.assertFalse(ok)
        self.assertEqual("delai", DQ.sonde_cause(sortie))

    def test_dry_run_runs_only_the_first_command(self):
        runner = FauxRunner(dry_run=True)
        self.assertEqual((True, ""), _sonder(runner))
        self.assertEqual(["print-xml"], runner.faits())

    def test_without_timeout_binary_the_command_is_bare(self):
        with mock.patch.object(DQ.shutil, "which", return_value=None):
            self.assertEqual(["virsh", "x"], DQ.sonde_borne(["virsh", "x"]))


class Preflight(unittest.TestCase):
    def _preflight(self, **kw):
        args = SimpleNamespace(
            **{"arch": "amd64", "bios": False, "no_preflight": False, **kw}
        )
        runner = FauxRunner()
        sortie = io.StringIO()
        with (
            mock.patch.object(DQ, "host_arch", return_value="amd64"),
            mock.patch.object(DQ, "kvm_available", return_value=True),
            redirect_stdout(sortie),
        ):
            DQ.preflight_firmware(args, "x", runner)
        return runner, sortie.getvalue()

    def test_skipped_for_bios(self):
        runner, _ = self._preflight(bios=True)
        self.assertEqual([], runner.appels)

    def test_skipped_for_s390x(self):
        runner, _ = self._preflight(arch="s390x")
        self.assertEqual([], runner.appels)

    def test_skipped_with_flag(self):
        runner, texte = self._preflight(no_preflight=True)
        self.assertEqual([], runner.appels)
        self.assertIn("--no-preflight", texte)

    def test_failure_exits_with_descriptor_order(self):
        descs = [
            {
                "fichier": "60-edk2-x86_64-amdsev.json",
                "device": "memory",
                "archs": ["x86_64"],
                "features": ["amd-sev"],
                "masque": False,
            },
            {
                "fichier": "60-edk2-x86_64.json",
                "device": "flash",
                "archs": ["x86_64"],
                "features": ["acpi-s3"],
                "masque": False,
            },
        ]
        with (
            mock.patch.object(
                DQ,
                "sonde_firmware",
                return_value=(
                    False,
                    "virt-aa-helper: skipped restricted file",
                ),
            ),
            mock.patch.object(DQ, "descripteurs_firmware", return_value=descs),
            self.assertRaises(SystemExit) as cm,
        ):
            self._preflight()
        texte = str(cm.exception.code)
        self.assertIn("ÉCHEC", texte)
        self.assertIn("--no-preflight", texte)
        lignes = texte.splitlines()
        sev = next(x for x in lignes if "60-edk2-x86_64-amdsev.json" in x)
        plain = next(x for x in lignes if "60-edk2-x86_64.json" in x)
        self.assertLess(lignes.index(sev), lignes.index(plain))
        self.assertIn("chargé en mémoire", sev)
        self.assertNotIn("chargé en mémoire", plain)

    def test_success_returns(self):
        with mock.patch.object(DQ, "sonde_firmware", return_value=(True, "")):
            _runner, texte = self._preflight()
        self.assertIn("0/5", texte)


class Descripteurs(unittest.TestCase):
    """Valeurs inventées, absentes du reste du dépôt."""

    @staticmethod
    def _ecrire(dossier, nom, device=None, brut=None):
        chemin = os.path.join(dossier, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            if brut is not None:
                fh.write(brut)
            else:
                json.dump(
                    {
                        "interface-types": ["uefi"],
                        "mapping": {"device": device},
                        "targets": [
                            {"architecture": "x86_64", "machines": ["pc-*"]}
                        ],
                        "features": [f"trait-{nom[:-5]}"],
                    },
                    fh,
                )

    def test_order_override_mask_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            etc = os.path.join(tmp, "etc")
            usr = os.path.join(tmp, "usr")
            os.mkdir(etc)
            os.mkdir(usr)
            self._ecrire(usr, "33-sondeq-a.json", "memory")
            self._ecrire(usr, "33-sondeq-b.json", "memory")
            self._ecrire(etc, "33-sondeq-b.json", "flash")
            self._ecrire(usr, "37-sondeq-c.json", brut="{pas du json")
            self._ecrire(usr, "39-sondeq-d.json", "flash")
            self._ecrire(etc, "39-sondeq-d.json", brut="")
            descs = DQ.descripteurs_firmware((etc, usr))
            par_nom = {d["fichier"]: d for d in descs}
            self.assertEqual(
                [
                    "33-sondeq-a.json",
                    "33-sondeq-b.json",
                    "37-sondeq-c.json",
                    "39-sondeq-d.json",
                ],
                [d["fichier"] for d in descs],
            )
            self.assertTrue(
                par_nom["33-sondeq-b.json"]["chemin"].startswith(etc)
            )
            self.assertNotEqual("", par_nom["37-sondeq-c.json"]["erreur"])
            self.assertTrue(par_nom["39-sondeq-d.json"]["masque"])
            lignes = DQ.ordre_firmware_lignes(descs, "amd64")
        self.assertEqual(2, len(lignes))
        self.assertIn("33-sondeq-a.json", lignes[0])
        self.assertIn("chargé en mémoire", lignes[0])
        self.assertIn("33-sondeq-b.json", lignes[1])
        self.assertNotIn("chargé en mémoire", lignes[1])
        self.assertFalse(any("39-sondeq-d" in x for x in lignes))

    def test_no_descriptor_for_arch(self):
        lignes = DQ.ordre_firmware_lignes([], "arm64")
        self.assertEqual(1, len(lignes))
        self.assertIn("arm64", lignes[0])


class Parser(unittest.TestCase):
    def test_no_preflight_flag(self):
        base = ["--distro", "ubuntu", "--name", "vm-a"]
        p = DQ.build_parser()
        self.assertFalse(p.parse_args(base).no_preflight)
        self.assertTrue(p.parse_args(base + ["--no-preflight"]).no_preflight)


class MainOrder(unittest.TestCase):
    """main() entier : le préflight passe avant tout téléchargement."""

    def _lancer(self, *extra):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        argv = [
            "deploy_qemu.py",
            "--distro",
            "ubuntu",
            "--name",
            "vm-a",
            "--disk-dir",
            tmp.name,
            "--seed-dir",
            tmp.name,
            "--no-verify",
            "--no-wait-ip",
            *extra,
            os.path.join(tmp.name, "image.qcow2"),
        ]
        self.mocks = {
            nom: mock.Mock(side_effect=SystemExit(f"stop-{nom}"))
            for nom in (
                "download_image",
                "prepare_disk",
                "create_blank_disk",
                "build_seed",
            )
        }
        self.preflight = mock.Mock(side_effect=SystemExit("stop-preflight"))
        faux = {
            **self.mocks,
            "preflight_firmware": self.preflight,
            "ensure_tools": mock.Mock(),
            "ensure_emulator": mock.Mock(),
            "host_arch": lambda: "amd64",
            "image_candidates": lambda *a, **k: ["https://x.invalid/i"],
            "verify_pinned_sha256": mock.Mock(),
            "image_en_cache": lambda _p: True,
            "resolve_password": lambda _a: "$6$faux",
            "load_ssh_keys": lambda _p: [],
            "osinfo_arg": lambda *a: "ubuntu24.04",
            "domaine_present": lambda *_a: False,
        }
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.multiple(DQ, **faux),
            mock.patch.object(DQ.os, "geteuid", return_value=1000),
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
            self.assertRaises(SystemExit) as cm,
        ):
            DQ.main()
        return cm.exception

    def test_preflight_runs_before_download_and_disk(self):
        vue = self._lancer()
        self.assertEqual("stop-preflight", vue.code)
        self.preflight.assert_called_once()
        self.assertEqual("ubuntu24.04", self.preflight.call_args[0][1])
        for nom, m in self.mocks.items():
            m.assert_not_called()

    def test_dry_run_skips_preflight(self):
        vue = self._lancer("--dry-run")
        self.preflight.assert_not_called()
        self.assertEqual("stop-download_image", vue.code)


if __name__ == "__main__":
    unittest.main()
