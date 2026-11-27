#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Cœur de l'installateur ERPLibre (erplibre_installer) et configuration
archinstall (erplibre_archinstall) : document de réponses, refus de
prepare(), configuration pré-montée, justificatifs, et une installation
entière jouée avec chaque commande simulée.

Faits, profils, noms, UUID et phrases secrètes sont INVENTÉS ; rien ne
lit le matériel ni ne lance de commande.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from test import iso_installer_modules as m

mp, facts, dk, ai, pl, ei = m.load()

ERPLIBRE_KEYS = ["odoo18", "home", "dev", "gnome"]
SECRETS = {
    "user_password": "mot-de-passe-inventé",
    "root_password": "racine-inventée",
    "luks_passphrase": "phrase-luks-inventée",
    "secret_lv_passphrase": "phrase-secrète-inventée",
}


def answers(**extra):
    doc = {
        "schema": 1,
        "answers": {"live.keymap": "us"},
        "confirm": {"disk": "nvme0n1"},
        "secrets": dict(SECRETS),
    }
    doc.update(extra)
    return doc


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def complete(profile):
    return mp.effective(profile, [str(m.PROFILES_DIR)])


class TestAnswersDocument(unittest.TestCase):
    def test_inline_roundtrip_allows_secrets(self):
        doc = answers()
        valeur = ei.encode_answers(doc)
        self.assertTrue(valeur.startswith(ei.INLINE_PREFIX))
        self.assertFalse(any(c.isspace() for c in valeur))
        self.assertEqual(ei.decode_answers(valeur), (doc, True))

    def test_file_allows_secrets_only_under_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "run")
            os.makedirs(run_dir)
            dedans = os.path.join(run_dir, "answers.json")
            dehors = os.path.join(tmp, "answers.json")
            for chemin in (dedans, dehors):
                with open(chemin, "w") as fh:
                    json.dump(answers(), fh)
            self.assertTrue(ei.decode_answers(dedans, run_dir)[1])
            self.assertFalse(ei.decode_answers(dehors, run_dir)[1])

    def test_unreadable_answers(self):
        with self.assertRaises(ValueError):
            ei.decode_answers("b64:%%%")
        with self.assertRaises(ValueError):
            ei.decode_answers("/chemin/inexistant/answers.json")

    def test_check_answers(self):
        self.assertEqual(ei.check_answers(answers(), True), [])
        codes = [c for c, _d in ei.check_answers(answers(), False)]
        self.assertEqual(codes, ["secrets-not-allowed"])
        mauvais = answers(schema=2, root="aucun", extra=1)
        mauvais["secrets"]["luks_passphrase"] = "avec\nfin de ligne"
        mauvais["secrets"]["autre"] = "x"
        codes = sorted(c for c, _d in ei.check_answers(mauvais, True))
        self.assertEqual(
            codes,
            [
                "root-policy",
                "schema",
                "secret-format",
                "unknown-key",
                "unknown-key",
            ],
        )
        self.assertEqual(ei.check_answers([], True), [("not-object", {})])
        identite = answers(
            confirm={"disk": "nvme0n1", "disk_size": "500", "disk_model": 3}
        )
        self.assertEqual(
            sorted(d["key"] for _c, d in ei.check_answers(identite, True)),
            ["confirm.disk_model", "confirm.disk_size"],
        )

    def test_disk_confirmation_by_name_or_path(self):
        disque = m.disk("nvme0n1", 500)
        self.assertTrue(ei.disk_confirmed({"disk": "nvme0n1"}, disque))
        self.assertTrue(ei.disk_confirmed({"disk": "/dev/nvme0n1 "}, disque))
        self.assertFalse(ei.disk_confirmed({"disk": "nvme0"}, disque))
        self.assertFalse(ei.disk_confirmed({}, disque))
        self.assertFalse(ei.disk_confirmed({"disk": "nvme0n1"}, None))


class TestPrepare(unittest.TestCase):
    def prepare(
        self, profile=None, fx=None, doc=None, keys=ERPLIBRE_KEYS, allowed=True
    ):
        return ei.prepare(
            complete(profile or m.luks_profile()),
            fx or m.uefi_laptop(),
            doc or answers(),
            keys,
            allowed,
        )

    def test_ready(self):
        res = self.prepare()
        self.assertTrue(res["ok"], res["reason"])
        self.assertEqual(res["root_policy"], ai.ROOT_LOCK)
        self.assertEqual(res["erplibre_profile"], "odoo18")
        self.assertEqual(
            res["settings"]["derived"]["disk"]["path"], "/dev/nvme0n1"
        )
        self.assertTrue(res["disk"]["ok"])
        self.assertIn(
            ("Target disk", "/dev/nvme0n1 (500 GiB)"), res["summary"]
        )
        # Le clavier de la console reprend celui du live.
        self.assertEqual(
            mp.get(res["settings"], "system.console_keymap"), "us"
        )

    def test_generic_profile_lists_its_questions(self):
        res = ei.prepare(
            complete(
                {"schema": 1, "name": "essai-vide", "extends": "generic"}
            ),
            m.uefi_laptop(),
            {"schema": 1},
            ERPLIBRE_KEYS,
        )
        self.assertEqual(res["reason"], "questions")
        for question in ("live.keymap", "system.timezone", "user.name"):
            self.assertIn(question, res["questions"])
        self.assertIsNone(res["disk"])

    def test_blocking_warning_on_usb_target(self):
        doc = answers(answers={"live.keymap": "us", "disk.target": "/dev/sdz"})
        profil = m.luks_profile()
        profil["disk"]["target"] = "ask"
        res = self.prepare(profil, doc=doc)
        self.assertEqual(res["reason"], "blocking-warnings")
        self.assertEqual(
            [w["code"] for w in res["blocking"]], ["disk-is-boot-medium"]
        )

    def test_unknown_erplibre_profile(self):
        res = self.prepare(doc=answers(erplibre_profile="inconnu"))
        self.assertEqual(res["reason"], "erplibre-profile-unknown")
        res = self.prepare(doc=answers(erplibre_profile="gnome"))
        self.assertTrue(res["ok"])
        self.assertEqual(res["erplibre_profile"], "gnome")

    def test_missing_secrets(self):
        doc = answers()
        del doc["secrets"]["secret_lv_passphrase"]
        res = self.prepare(doc=doc)
        self.assertEqual(res["reason"], "secrets-missing")
        self.assertEqual(res["details"]["missing"], ["secret_lv_passphrase"])
        doc = answers(root="password")
        del doc["secrets"]["root_password"]
        self.assertEqual(
            self.prepare(doc=doc)["details"]["missing"], ["root_password"]
        )

    def test_plain_needs_no_passphrase(self):
        doc = answers(secrets={"user_password": "x"})
        self.assertTrue(self.prepare(m.plain_profile(), doc=doc)["ok"])

    def test_secrets_refused_from_disk_source(self):
        self.assertEqual(
            self.prepare(allowed=False)["reason"], "answers-invalid"
        )

    def test_root_lock_needs_sudo(self):
        profil = m.luks_profile()
        profil["user"]["sudo"] = False
        res = self.prepare(profil, doc=answers())
        self.assertEqual(res["root_policy"], ai.ROOT_PASSWORD)
        self.assertTrue(res["ok"])
        res = self.prepare(profil, doc=answers(root="lock"))
        self.assertEqual(res["reason"], "root-lock-needs-sudo")

    def test_disk_confirmation_comes_last_with_the_full_plan(self):
        res = self.prepare(doc=answers(confirm={"disk": "sda"}))
        self.assertEqual(res["reason"], "disk-not-confirmed")
        self.assertEqual(res["details"]["expected"], "nvme0n1")
        self.assertTrue(res["disk"]["plan"])
        self.assertTrue(res["summary"])

    def test_confirmed_nvme_format_shows_the_sector_it_uses(self):
        avant = self.prepare()
        self.assertIn(("LUKS sector size", "512"), avant["summary"])
        res = self.prepare(
            doc=answers(confirm={"disk": "nvme0n1", "nvme_format": True})
        )
        self.assertTrue(res["ok"], res["reason"])
        # Le plan formate en 4 KiB : récapitulatif et réglages le disent.
        self.assertIn(("LUKS sector size", "4096"), res["summary"])
        self.assertEqual(
            mp.get(res["settings"], "disk.luks.sector_size"), 4096
        )
        fmt = next(
            s["argv"]
            for s in res["disk"]["plan"]
            if s["argv"][:2] == ["cryptsetup", "luksFormat"]
        )
        self.assertEqual(fmt[fmt.index("--sector-size") + 1], "4096")

    def test_disk_shown_on_the_summary_must_still_be_there(self):
        # Le nom confirmé désigne maintenant un disque d'une autre taille ou
        # d'un autre modèle : refusé, rien n'est effacé.
        vu = {"disk": "nvme0n1", "disk_size": 500 * m.GIB}
        self.assertTrue(self.prepare(doc=answers(confirm=vu))["ok"])
        vu_modele = dict(vu, disk_model="Disque fictif 9000")
        self.assertTrue(self.prepare(doc=answers(confirm=vu_modele))["ok"])
        res = self.prepare(doc=answers(confirm=dict(vu, disk_size=1)))
        self.assertEqual(res["reason"], "disk-changed")
        self.assertEqual(res["details"]["fields"], ["size"])
        res = self.prepare(
            doc=answers(confirm=dict(vu, disk_model="Autre modèle"))
        )
        self.assertEqual(res["details"]["fields"], ["model"])
        self.assertEqual(ei.REASON_EXIT["disk-changed"], ei.EXIT_DISK_REFUSED)

    def test_disk_too_small(self):
        fx = m.uefi_laptop()
        fx["disks"][0]["size"] = 21 * m.GIB
        self.assertEqual(self.prepare(fx=fx)["reason"], "disk-too-small")

    def test_invalid_profile(self):
        profil = m.luks_profile()
        profil["user"]["password"] = "interdit"
        self.assertEqual(
            ei.prepare(profil, m.uefi_laptop(), answers(), ERPLIBRE_KEYS)[
                "reason"
            ],
            "profile-invalid",
        )


class TestArchinstallConfig(unittest.TestCase):
    def setUp(self):
        res = ei.prepare(
            complete(m.luks_profile()),
            m.uefi_laptop(),
            answers(),
            ERPLIBRE_KEYS,
        )
        self.settings = res["settings"]
        self.base = {
            "packages": ["git", "make"],
            "services": [],
            "custom_commands": ["#!/bin/bash\n"],
            "app_config": {"audio_config": {"audio": "pipewire"}},
            "bootloader_config": {"bootloader": "Grub"},
        }

    def test_pre_mounted_config(self):
        c = ai.machine_config(self.base, self.settings, "/mnt/archinstall")
        self.assertEqual(
            c["disk_config"],
            {
                "config_type": "pre_mounted_config",
                "mountpoint": "/mnt/archinstall",
            },
        )
        self.assertEqual(
            c["bootloader_config"],
            {"bootloader": "Systemd-boot", "uki": False, "removable": False},
        )
        self.assertEqual(c["swap"]["enabled"], False)
        self.assertEqual(c["kernels"], ["linux"])
        self.assertEqual(c["packages"][:2], ["git", "make"])
        self.assertNotIn("linux", c["packages"])
        for paquet in ("lvm2", "cryptsetup", "amd-ucode"):
            self.assertIn(paquet, c["packages"])
        self.assertIn("systemd-boot-update.service", c["services"])
        self.assertEqual(
            c["locale_config"],
            {"kb_layout": "us", "sys_lang": "en_US.UTF-8", "sys_enc": "UTF-8"},
        )
        self.assertEqual(c["timezone"], "UTC")
        self.assertEqual(c["profile_config"]["greeter"], "gdm")
        self.assertEqual(
            c["app_config"]["print_service_config"], {"enabled": True}
        )
        self.assertEqual(
            c["app_config"]["audio_config"], {"audio": "pipewire"}
        )
        self.assertEqual(c["custom_commands"], ["#!/bin/bash\n"])
        self.assertEqual(
            self.base["bootloader_config"], {"bootloader": "Grub"}
        )

    def test_grub_minimal_apparmor_aur(self):
        s = ei.prepare(
            complete(m.luks_profile()),
            m.bios_desktop(),
            answers(confirm={"disk": "sda"}),
            ERPLIBRE_KEYS,
        )["settings"]
        mp.put(s, "desktop.env", "none")
        mp.put(s, "security.apparmor", True)
        mp.put(s, "firstboot.aur_helper", "yay")
        c = ai.machine_config({}, s, "/mnt/x")
        self.assertEqual(c["bootloader_config"]["bootloader"], "Grub")
        self.assertEqual(c["profile_config"], {"profile": {"main": "Minimal"}})
        for paquet in ("audit", "git", "base-devel"):
            self.assertIn(paquet, c["packages"])
        self.assertIn("auditd.service", c["services"])

    def test_credentials(self):
        lock = ai.credentials(self.settings, SECRETS, ai.ROOT_LOCK)
        self.assertEqual(
            lock,
            {
                "users": [
                    {
                        "username": "camille",
                        "!password": SECRETS["user_password"],
                        "sudo": True,
                        "groups": [],
                    }
                ]
            },
        )
        mdp = ai.credentials(self.settings, SECRETS, ai.ROOT_PASSWORD)
        self.assertEqual(mdp["!root-password"], SECRETS["root_password"])

    def test_private_json_and_shred(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "run", "creds.json")
            ai.write_private_json(chemin, {"a": 1})
            ai.write_private_json(chemin, {"a": 2})
            self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)
            self.assertEqual(read_json(chemin), {"a": 2})
            self.assertTrue(ai.shred(chemin))
            self.assertFalse(os.path.exists(chemin))
            self.assertFalse(ai.shred(chemin))


class TestStatusFiles(unittest.TestCase):
    def test_plugin_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "status.json")
            self.assertEqual(ei.plugin_failures(chemin), ["missing"])
            with open(chemin, "w") as fh:
                json.dump(
                    {"on_install": {"ok": True}, "on_genfstab": {"ok": False}},
                    fh,
                )
            self.assertEqual(ei.plugin_failures(chemin), ["on_genfstab"])

    def test_stage_rc(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ei.stage_rc(tmp, False), 0)
            self.assertEqual(ei.stage_rc(tmp, True), ei.EXIT_STAGE_MISSING)
            os.makedirs(os.path.join(tmp, "var/lib/erplibre-install"))
            with open(
                os.path.join(tmp, "var/lib/erplibre-install/status"), "w"
            ) as fh:
                fh.write("rc=13\nprofile=odoo18\n")
            self.assertEqual(ei.stage_rc(tmp, True), 13)

    def test_archinstall_argv(self):
        paths = dict(ei.DEFAULT_PATHS)
        argv = ei.archinstall_argv(paths)
        self.assertEqual(
            argv[:3], ["archinstall", "--silent", "--skip-version-check"]
        )
        self.assertEqual(argv[argv.index("--plugin") + 1], paths["plugin"])
        self.assertEqual(argv[argv.index("--mountpoint") + 1], dk.TARGET)
        self.assertNotIn("--skip-ntp", argv)
        self.assertIn("--skip-ntp", ei.archinstall_argv(paths, offline=True))


ERPLIBRE_DOC = {
    "version": 1,
    "lang": "fr",
    "default_profile": "odoo18",
    "auto_profile": "odoo18",
    "network_source": {
        "git_url": "https://example.invalid/erplibre",
        "branch": "master",
    },
    "profiles": [
        {
            "key": "odoo18",
            "label": {"fr": "Odoo 18", "en": "Odoo 18"},
            "command": "make install_odoo_18",
            "service": True,
            "postgresql": True,
        },
        {
            "key": "gnome",
            "label": {"fr": "GNOME", "en": "GNOME"},
            "command": "",
            "service": False,
            "postgresql": False,
        },
    ],
    "service_unit": "[Unit]\nDescription=fictif\n",
}

UUID_ISO = "2001-02-03-04-05-06-00"


def raw_lsblk():
    return json.dumps(
        {
            "blockdevices": [
                {
                    "name": "nvme0n1",
                    "path": "/dev/nvme0n1",
                    "type": "disk",
                    "tran": "nvme",
                    "rm": False,
                    "ro": False,
                    "rota": False,
                    "size": 500 * m.GIB,
                    "log-sec": 512,
                    "phy-sec": 512,
                    "disc-gran": 512,
                    "model": "Disque fictif 9000",
                    "mountpoints": [None],
                },
                {
                    "name": "sdz",
                    "path": "/dev/sdz",
                    "type": "disk",
                    "tran": "usb",
                    "rm": True,
                    "ro": False,
                    "rota": False,
                    "size": 32 * m.GIB,
                    "model": "Clé fictive",
                    "mountpoints": [None],
                    "children": [
                        {
                            "name": "sdz1",
                            "path": "/dev/sdz1",
                            "type": "part",
                            "uuid": UUID_ISO,
                            "mountpoints": ["/run/archiso/bootmnt"],
                        }
                    ],
                },
            ]
        }
    )


def raw_facts(cmdline):
    return {
        "efi": True,
        "fw_platform_size": "64",
        "cpuinfo": "vendor_id\t: AuthenticAMD\nflags\t\t: fpu sse\n",
        "meminfo": "MemTotal:       16179200 kB\n",
        "cmdline": cmdline,
        "lsblk": raw_lsblk(),
        "nvme": {},
        "pci": [],
        "lspci": None,
        "power_supply": [],
        "chassis_type": "3",
        "wireless": [],
    }


class FakeSystem:
    """Le `run` d'une installation simulée : lsblk et blkid répondent,
    archinstall laisse les verdicts que le vrai laisserait, toute autre
    commande réussit. Chaque appel est gardé."""

    def __init__(self, paths, stage_rc=0, archinstall_rc=0, plugin_ok=True):
        self.paths = paths
        self.calls = []
        self.stage_rc = stage_rc
        self.archinstall_rc = archinstall_rc
        self.plugin_ok = plugin_ok
        self.creds_seen = None

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        texte = kw.get("text")
        sortie = ""
        if argv[0] == "lsblk":
            sortie = raw_lsblk()
        elif argv[0] == "blkid":
            sortie = "uuid-" + argv[-1].rsplit("/", 1)[-1] + "\n"
        elif argv[0] == "archinstall":
            self._archinstall(kw)
            return subprocess.CompletedProcess(argv, self.archinstall_rc)
        if not texte and kw.get("stdout") is not None:
            sortie = sortie.encode()
        return subprocess.CompletedProcess(argv, 0, sortie, "")

    def _archinstall(self, kw):
        run_dir = self.paths["run"]
        creds = os.path.join(run_dir, "creds.json")
        self.creds_seen = (
            stat.S_IMODE(os.stat(creds).st_mode),
            read_json(creds),
        )
        etat = read_json(kw["env"][pl.STATE_ENV])
        self.state_seen = etat
        with open(etat["status_path"], "w") as fh:
            json.dump({"on_install": {"ok": self.plugin_ok}}, fh)
        cible = os.path.join(self.paths["target"], "var/lib/erplibre-install")
        os.makedirs(cible, exist_ok=True)
        with open(os.path.join(cible, "status"), "w") as fh:
            fh.write(f"rc={self.stage_rc}\n")
        os.makedirs(
            os.path.join(self.paths["target"], "var/log"), exist_ok=True
        )

    def commands(self):
        return [a for a, _kw in self.calls]


class TestRunInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        racine = Path(self.tmp.name)
        share = racine / "share"
        share.mkdir()
        (share / "profiles.json").write_text(json.dumps(ERPLIBRE_DOC))
        for nom in ("user_configuration.template.json", "erplibre-stage.sh"):
            shutil.copy(m.SHARE_DIR / nom, share / nom)
        boot = racine / "bootmnt"
        (boot / "erplibre").mkdir(parents=True)
        (boot / "erplibre" / "machine.json").write_text(
            json.dumps(m.luks_profile())
        )
        self.paths = {
            "share": str(share),
            "profiles": str(m.PROFILES_DIR),
            "config_tool": str(m.CONFIG_TOOL),
            "plugin": str(m.SHARE_DIR / "erplibre_plugin.py"),
            "run": str(racine / "run"),
            "log": str(racine / "log"),
            "boot_mount": str(boot),
            "target": str(racine / "target"),
        }
        self.cmdline = f"archisolabel=FICTIF archisosearchuuid={UUID_ISO}"

    def install(self, doc=None, dry_run=False, system=None, version="4.5.1"):
        system = system or FakeSystem(self.paths)
        rc = ei.run_install(
            doc or answers(),
            True,
            paths=self.paths,
            serial=None,
            dry_run=dry_run,
            run=system,
            raw_facts=raw_facts(self.cmdline),
            version=version,
            echo=False,
        )
        return rc, system

    def logs(self):
        texte = ""
        for nom in os.listdir(self.paths["log"]):
            texte += Path(self.paths["log"], nom).read_text()
        return texte

    def test_dry_run_runs_nothing(self):
        rc, system = self.install(dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(system.calls, [])
        self.assertIn("plan: sgdisk --zap-all /dev/nvme0n1", self.logs())

    def test_full_install(self):
        rc, system = self.install()
        self.assertEqual(rc, 0, self.logs())
        cmds = system.commands()
        outils = [c[0] for c in cmds]
        self.assertEqual(outils[0], "lsblk")
        self.assertLess(outils.index("wipefs"), outils.index("blkid"))
        self.assertLess(outils.index("blkid"), outils.index("archinstall"))
        self.assertEqual(
            outils[-5:],
            ["swapoff", "umount", "cryptsetup", "vgchange", "cryptsetup"],
        )
        # Justificatifs : 0600 pendant archinstall, effacés après.
        mode, creds = system.creds_seen
        self.assertEqual(mode, 0o600)
        self.assertEqual(creds["users"][0]["username"], "camille")
        self.assertFalse(
            os.path.exists(os.path.join(self.paths["run"], "creds.json"))
        )
        # Le greffon reçoit les UUID et aucun secret.
        etat = system.state_seen
        self.assertEqual(etat["disk"]["luks_uuid"], "uuid-nvme0n1p2")
        self.assertEqual(etat["root_policy"], "lock")
        texte_etat = json.dumps(etat)
        config = Path(self.paths["run"], "config.json").read_text()
        for secret in SECRETS.values():
            self.assertNotIn(secret, texte_etat)
            self.assertNotIn(secret, config)
            self.assertNotIn(secret, self.logs())
        self.assertIn('"config_type": "pre_mounted_config"', config)
        # La phrase LUKS n'a voyagé que par l'entrée standard.
        format_luks = next(
            kw
            for a, kw in system.calls
            if a[:2] == ["cryptsetup", "luksFormat"]
        )
        self.assertEqual(
            format_luks["input"], SECRETS["luks_passphrase"].encode()
        )
        # Les journaux sont recopiés dans la cible.
        self.assertTrue(
            Path(
                self.paths["target"], "var/log/erplibre-install/installer.log"
            ).is_file()
        )

    def test_stage_code_is_returned(self):
        rc, _s = self.install(system=FakeSystem(self.paths, stage_rc=13))
        self.assertEqual(rc, 13)

    def test_archinstall_and_plugin_failures(self):
        rc, _s = self.install(system=FakeSystem(self.paths, archinstall_rc=1))
        self.assertEqual(rc, ei.EXIT_ARCHINSTALL)
        rc, system = self.install(
            system=FakeSystem(self.paths, plugin_ok=False)
        )
        self.assertEqual(rc, ei.EXIT_PLUGIN)
        self.assertFalse(
            os.path.exists(os.path.join(self.paths["run"], "creds.json"))
        )

    def test_wrong_archinstall_version_touches_nothing(self):
        rc, system = self.install(version="4.6")
        self.assertEqual(rc, ei.EXIT_ARCHINSTALL_VERSION)
        self.assertEqual(system.calls, [])

    def test_refusal_touches_nothing(self):
        rc, system = self.install(doc=answers(confirm={"disk": "sdz"}))
        self.assertEqual(rc, ei.EXIT_ANSWERS)
        self.assertEqual(system.calls, [])

    def test_preflight_refusal(self):
        class Change(FakeSystem):
            def __call__(self, argv, **kw):
                if argv[0] == "lsblk":
                    self.calls.append((list(argv), kw))
                    donnees = json.loads(raw_lsblk())
                    donnees["blockdevices"][0]["size"] = 250 * m.GIB
                    return subprocess.CompletedProcess(
                        argv, 0, json.dumps(donnees), ""
                    )
                return super().__call__(argv, **kw)

        rc, system = self.install(system=Change(self.paths))
        self.assertEqual(rc, ei.EXIT_DISK_REFUSED)
        self.assertEqual([c[0] for c in system.commands()], ["lsblk"])

    def test_disk_failure_tears_down(self):
        class Echec(FakeSystem):
            def __call__(self, argv, **kw):
                if argv[0] == "pvcreate":
                    self.calls.append((list(argv), kw))
                    return subprocess.CompletedProcess(argv, 5, b"", None)
                return super().__call__(argv, **kw)

        rc, system = self.install(system=Echec(self.paths))
        self.assertEqual(rc, ei.EXIT_DISK_FAILED)
        outils = [c[0] for c in system.commands()]
        self.assertNotIn("archinstall", outils)
        self.assertEqual(
            outils[-4:], ["umount", "cryptsetup", "vgchange", "cryptsetup"]
        )

    def test_interrupted_disk_stage_releases_the_disk(self):
        # Ctrl-C pendant lvcreate : le disque est rendu (LUKS fermé, groupe
        # désactivé), puis l'interruption remonte à main().
        class Coupure(FakeSystem):
            def __call__(self, argv, **kw):
                if argv[0] == "lvcreate":
                    self.calls.append((list(argv), kw))
                    raise KeyboardInterrupt
                return super().__call__(argv, **kw)

        system = Coupure(self.paths)
        with self.assertRaises(KeyboardInterrupt):
            self.install(system=system)
        outils = [c[0] for c in system.commands()]
        self.assertNotIn("archinstall", outils)
        self.assertEqual(
            outils[-4:], ["umount", "cryptsetup", "vgchange", "cryptsetup"]
        )
        self.assertIn("disk stage interrupted", self.logs())

    def test_missing_uuid_stops_before_archinstall(self):
        # blkid muet sur l'en-tête LUKS : rd.luks.name=None démarrerait
        # une machine qui attend à jamais ; refus avant archinstall.
        class SansUuid(FakeSystem):
            def __call__(self, argv, **kw):
                if argv[0] == "blkid" and argv[-1].endswith("p2"):
                    self.calls.append((list(argv), kw))
                    return subprocess.CompletedProcess(argv, 2, "", "")
                return super().__call__(argv, **kw)

        rc, system = self.install(system=SansUuid(self.paths))
        self.assertEqual(rc, ei.EXIT_DISK_FAILED)
        outils = [c[0] for c in system.commands()]
        self.assertNotIn("archinstall", outils)
        self.assertEqual(outils[-1], "cryptsetup")
        self.assertIn("blkid gave no UUID for: luks_uuid", self.logs())


class TestMachineProfileLookup(unittest.TestCase):
    def test_remounts_the_medium_by_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = dict(
                ei.DEFAULT_PATHS,
                boot_mount=os.path.join(tmp, "absent"),
                run=os.path.join(tmp, "run"),
                profiles=str(m.PROFILES_DIR),
            )
            appels = []

            def run(argv, **_kw):
                appels.append(argv)
                if argv[0] == "mount":
                    dossier = os.path.join(argv[-1], "erplibre")
                    os.makedirs(dossier, exist_ok=True)
                    with open(
                        os.path.join(dossier, "machine.json"), "w"
                    ) as fh:
                        json.dump(m.plain_profile(), fh)
                return subprocess.CompletedProcess(argv, 0, "", "")

            origine, profil = ei.machine_profile(
                paths, {"archisosearchuuid": UUID_ISO}, run=run
            )
            self.assertEqual(
                origine, f"/dev/disk/by-uuid/{UUID_ISO}:/erplibre/machine.json"
            )
            self.assertEqual(profil["name"], "essai-plain")
            self.assertEqual(appels[0][:3], ["mount", "-o", "ro"])
            self.assertEqual(appels[-1][0], "umount")

    def test_generic_without_machine_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = dict(
                ei.DEFAULT_PATHS,
                boot_mount=os.path.join(tmp, "absent"),
                run=os.path.join(tmp, "run"),
                profiles=str(m.PROFILES_DIR),
            )
            origine, profil = ei.machine_profile(paths, {})
            self.assertTrue(origine.endswith("generic.json"))
            self.assertEqual(profil["name"], "generic")


class TestMainAuto(unittest.TestCase):
    def test_unreadable_answers_reach_the_serial_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmdline = os.path.join(tmp, "cmdline")
            serie = os.path.join(tmp, "ttyS0")
            Path(cmdline).write_text(
                "archisobasedir=arch erplibre.answers=b64:@@@\n"
            )
            paths = dict(ei.DEFAULT_PATHS, cmdline=cmdline)
            with unittest.mock.patch.object(ei, "DEFAULT_PATHS", paths):
                with (
                    unittest.mock.patch("sys.stdout"),
                    unittest.mock.patch("sys.stderr"),
                ):
                    rc = ei.main(["--auto", "--serial", serie])
            self.assertEqual(rc, ei.EXIT_ANSWERS)
            lignes = Path(serie).read_text().splitlines()
            self.assertTrue(
                lignes[0].startswith("[erplibre] inline answers unreadable")
            )
            self.assertEqual(lignes[-1], f"{ei.EXIT_MARKER} {ei.EXIT_ANSWERS}")


if __name__ == "__main__":
    unittest.main()
