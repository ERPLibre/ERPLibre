#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les faits du matériel : snapshot() sur un faux /sys et un faux /proc
construits dans un dossier temporaire, avec un `run` qui rend un JSON de
lsblk et de nvme id-ns inventé ; puis facts_from() sur ce brut.

Aucune valeur ne vient d'une vraie machine : modèles, identifiants de
périphérique et tailles sont inventés. subprocess.run lève s'il est
appelé : seul le `run` factice répond.
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from script.iso.archlinux.machine import facts as mf

GIB = 1024**3

LSBLK = {
    "blockdevices": [
        {
            "name": "nvme0n1",
            "path": "/dev/nvme0n1",
            "type": "disk",
            "tran": "nvme",
            "rm": False,
            "ro": False,
            "rota": False,
            "size": 1000 * GIB,
            "log-sec": 512,
            "phy-sec": 512,
            "disc-gran": 512,
            "model": "Disque Fictif 1T   ",
            "label": None,
            "uuid": None,
            "mountpoints": [None],
        },
        {
            "name": "sda",
            "path": "/dev/sda",
            "type": "disk",
            "tran": "usb",
            "rm": True,
            "ro": False,
            "rota": False,
            "size": 30 * GIB,
            "log-sec": 512,
            "phy-sec": 512,
            "disc-gran": 0,
            "model": "Clé Inventée",
            "label": "ERPLIBRE_209901",
            "uuid": "2099-01-02-03-04-05-00",
            "mountpoints": [None],
            "children": [
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "label": "ERPLIBRE_209901",
                    "uuid": "2099-01-02-03-04-05-00",
                    "mountpoints": ["/run/archiso/bootmnt"],
                }
            ],
        },
        {
            "name": "sdb",
            "path": "/dev/sdb",
            "type": "disk",
            "tran": "sata",
            "rm": "0",
            "ro": "0",
            "rota": "1",
            "size": "2000000000000",
            "log-sec": "512",
            "phy-sec": "4096",
            "disc-gran": "0",
            "model": None,
            "mountpoints": [],
        },
        {"name": "zram0", "path": "/dev/zram0", "type": "disk", "size": 1},
        {"name": "sr0", "path": "/dev/sr0", "type": "rom", "size": 1},
    ]
}

NVME_ID_NS = {
    "nsze": 1953525168,
    "flbas": 0,
    "lbafs": [
        {"ms": 0, "ds": 9, "rp": 2},
        {"ms": 0, "ds": 12, "rp": 0},
        {"ms": 8, "ds": 12, "rp": 1},
    ],
}

CPUINFO = (
    "processor\t: 0\nvendor_id\t: AuthenticAMD\nflags\t\t: fpu sse2 lm\n\n"
    "processor\t: 1\nvendor_id\t: AuthenticAMD\nflags\t\t: fpu sse2 lm\n"
)
MEMINFO = "MemTotal:       16318412 kB\nMemFree:         1000000 kB\n"


def ecrire(racine, chemin, texte):
    complet = os.path.join(racine, chemin)
    os.makedirs(os.path.dirname(complet), exist_ok=True)
    with open(complet, "w", encoding="utf-8") as fh:
        fh.write(texte)


def faux_sys(racine, efi=True, portable=True):
    if efi:
        ecrire(racine, "sys/firmware/efi/fw_platform_size", "64\n")
    ecrire(racine, "proc/cpuinfo", CPUINFO)
    ecrire(racine, "proc/meminfo", MEMINFO)
    ecrire(
        racine,
        "proc/cmdline",
        "initrd=x archisobasedir=arch "
        "archisosearchuuid=2099-01-02-03-04-05-00",
    )
    pci = "sys/bus/pci/devices"
    for slot, vendeur, device, classe, vga in (
        ("0000:00:01.0", "0x1002", "0x0f0f", "0x030000", "1"),
        ("0000:01:00.0", "0x10de", "0x0b0b", "0x030200", "0"),
        ("0000:02:00.0", "0x8086", "0x0c0c", "0x020000", None),
    ):
        ecrire(racine, f"{pci}/{slot}/vendor", vendeur + "\n")
        ecrire(racine, f"{pci}/{slot}/device", device + "\n")
        ecrire(racine, f"{pci}/{slot}/class", classe + "\n")
        if vga is not None:
            ecrire(racine, f"{pci}/{slot}/boot_vga", vga + "\n")
    ecrire(racine, "sys/class/power_supply/AC/type", "Mains\n")
    ecrire(racine, "sys/class/power_supply/hidpp_battery_0/type", "Battery\n")
    ecrire(racine, "sys/class/power_supply/hidpp_battery_0/scope", "Device\n")
    if portable:
        ecrire(racine, "sys/class/power_supply/BAT0/type", "Battery\n")
    ecrire(racine, "sys/class/dmi/id/chassis_type", "3\n")
    os.makedirs(os.path.join(racine, "sys/class/net/wlan0/wireless"))
    os.makedirs(os.path.join(racine, "sys/class/net/eth0"))


class FauxRun:
    """Rend un JSON de lsblk et de nvme id-ns ; toute autre commande est
    absente (FileNotFoundError), comme sur une machine sans l'outil."""

    def __init__(self, nvme_rc=0):
        self.appels = []
        self.nvme_rc = nvme_rc

    def __call__(self, argv, **kwargs):
        self.appels.append(list(argv))
        if argv[0] == "lsblk":
            return subprocess.CompletedProcess(argv, 0, json.dumps(LSBLK), "")
        if argv[:2] == ["nvme", "id-ns"]:
            return subprocess.CompletedProcess(
                argv, self.nvme_rc, json.dumps(NVME_ID_NS), ""
            )
        raise FileNotFoundError(argv[0])


class Banc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.racine = self.tmp.name
        patch = mock.patch(
            "subprocess.run",
            side_effect=AssertionError("subprocess.run inattendu"),
        )
        patch.start()
        self.addCleanup(patch.stop)


class TestLeReleve(Banc):
    def test_snapshot_reads_the_fake_tree(self):
        faux_sys(self.racine)
        run = FauxRun()
        brut = mf.snapshot(self.racine, run=run)
        self.assertTrue(brut["efi"])
        self.assertEqual(brut["fw_platform_size"], "64")
        self.assertNotIn("processor\t: 1", brut["cpuinfo"])
        self.assertIn("/dev/nvme0n1", brut["nvme"])
        self.assertEqual(len(brut["pci"]), 3)
        self.assertIsNone(brut["lspci"])
        self.assertEqual(brut["wireless"], ["wlan0"])
        self.assertEqual(brut["chassis_type"], "3")
        self.assertEqual(run.appels[0], mf.LSBLK_COMMAND)
        self.assertIn(
            ["nvme", "id-ns", "-o", "json", "/dev/nvme0n1"], run.appels
        )
        # Seul le NVMe est interrogé par nvme-cli.
        self.assertEqual(sum(1 for a in run.appels if a[0] == "nvme"), 1)

    def test_no_serial_is_read(self):
        self.assertNotIn("SERIAL", mf.LSBLK_COLUMNS)

    def test_snapshot_without_tools_or_sys(self):
        brut = mf.snapshot(self.racine, run=FauxRun(nvme_rc=1))
        self.assertFalse(brut["efi"])
        self.assertEqual(brut["nvme"], {})
        self.assertEqual(brut["pci"], [])
        self.assertIsNone(brut["lspci"])
        self.assertIsNone(brut["meminfo"])
        faits = mf.facts_from(brut)
        self.assertEqual(faits["ram_mib"], 0)
        self.assertEqual(faits["firmware"], {"mode": "bios", "bits": None})


class TestLesFaits(Banc):
    def faits(self, **options):
        faux_sys(self.racine, **options)
        return mf.facts_from(mf.snapshot(self.racine, run=FauxRun()))

    def test_firmware_cpu_memory(self):
        f = self.faits()
        self.assertEqual(f["firmware"], {"mode": "uefi", "bits": 64})
        self.assertEqual(f["cpu"], {"vendor": "amd", "hypervisor": False})
        self.assertFalse(f["virtual"])
        self.assertEqual(f["ram_mib"], 16318412 // 1024)

    def test_disks(self):
        disques = {d["name"]: d for d in self.faits()["disks"]}
        self.assertEqual(sorted(disques), ["nvme0n1", "sda", "sdb"])
        nvme = disques["nvme0n1"]
        self.assertEqual(nvme["model"], "Disque Fictif 1T")
        self.assertFalse(nvme["rotational"])
        self.assertEqual(nvme["disc_gran"], 512)
        self.assertEqual(nvme["nvme"]["current"], 0)
        self.assertEqual(
            nvme["nvme"]["formats"][1], {"id": 1, "ds": 12, "rp": 0, "ms": 0}
        )
        self.assertFalse(nvme["boot_medium"])
        self.assertTrue(disques["sda"]["boot_medium"])
        self.assertTrue(disques["sda"]["removable"])
        sdb = disques["sdb"]
        self.assertEqual(sdb["size"], 2000000000000)
        self.assertTrue(sdb["rotational"])
        self.assertFalse(sdb["removable"])
        self.assertEqual(sdb["phy_sec"], 4096)
        self.assertIsNone(sdb["nvme"])

    def test_boot_medium_by_label_or_mount_alone(self):
        lsblk = {
            "blockdevices": [
                {
                    "name": "sdc",
                    "type": "disk",
                    "label": "ERPLIBRE_209901",
                    "mountpoints": [None],
                },
                {
                    "name": "sdd",
                    "type": "disk",
                    "children": [
                        {
                            "name": "sdd1",
                            "mountpoints": ["/run/archiso/bootmnt"],
                        }
                    ],
                },
                {"name": "sde", "type": "disk", "label": "AUTRE"},
            ]
        }
        disques = mf.disks_from(
            json.dumps(lsblk), cmdline="archisolabel=ERPLIBRE_209901"
        )
        self.assertEqual(
            [d["boot_medium"] for d in disques], [True, True, False]
        )
        self.assertEqual(disques[0]["path"], "/dev/sdc")

    def test_boot_medium_unknown_only_on_a_live(self):
        # Live archiso sans disque reconnu comme support (fichiers de
        # l'ISO copiés, copytoram) : signalé. Hors live, ou support
        # reconnu : non.
        fixe = {"name": "sda", "type": "disk", "uuid": "AUTRE"}
        cle = {
            "name": "sdb",
            "type": "disk",
            "children": [{"name": "sdb1", "uuid": "2099-01-01-00-00-00-00"}],
        }
        live = "archisobasedir=arch archisosearchuuid=2099-01-01-00-00-00-00"
        for disques, cmdline, attendu in (
            ([fixe], live, True),
            ([fixe, cle], live, False),
            ([fixe], "root=UUID=inventé rw", False),
        ):
            brut = {
                "lsblk": json.dumps({"blockdevices": disques}),
                "cmdline": cmdline,
            }
            self.assertIs(
                mf.facts_from(brut)["boot_medium_unknown"], attendu, cmdline
            )

    def test_gpus_battery_chassis_wifi(self):
        f = self.faits()
        self.assertEqual(
            [(g["vendor"], g["device_id"], g["class"]) for g in f["gpus"]],
            [("amd", "0f0f", "0300"), ("nvidia", "0b0b", "0302")],
        )
        self.assertTrue(f["gpus"][0]["boot_vga"])
        self.assertTrue(f["battery"])
        self.assertEqual(f["chassis_type"], 3)
        self.assertTrue(f["laptop"])
        self.assertTrue(f["wifi"])

    def test_a_device_battery_is_not_a_laptop(self):
        f = self.faits(portable=False)
        self.assertFalse(f["battery"])
        self.assertFalse(f["laptop"])

    def test_bios(self):
        self.assertEqual(
            self.faits(efi=False)["firmware"], {"mode": "bios", "bits": None}
        )

    def test_hypervisor_flag_means_virtual(self):
        f = mf.facts_from(
            {"cpuinfo": "vendor_id\t: GenuineIntel\nflags\t: fpu hypervisor\n"}
        )
        self.assertEqual(f["cpu"], {"vendor": "intel", "hypervisor": True})
        self.assertTrue(f["virtual"])

    def test_lspci_fallback(self):
        texte = (
            '00:02.0 "VGA compatible controller [0300]" "Fabricant [8086]" '
            '"Carte [0d0d]" -r01 "Sous [8086]" "Sous [0000]"\n'
            '00:1f.3 "Audio device [0403]" "Fabricant [8086]" "Son [0e0e]"\n'
        )
        f = mf.facts_from({"pci": [], "lspci": texte})
        self.assertEqual(
            [(g["vendor"], g["device_id"]) for g in f["gpus"]],
            [("intel", "0d0d")],
        )

    def test_nvme_from_bad_json(self):
        self.assertIsNone(mf.nvme_from("pas du json"))
        self.assertIsNone(mf.nvme_from("[]"))

    def test_lsblk_json_of_the_wrong_shape_gives_no_disk(self):
        for texte in (
            "null",
            "[]",
            '{"blockdevices": null}',
            '{"blockdevices": [null, 3]}',
            '{"blockdevices": {"name": "sda"}}',
        ):
            with self.subTest(texte=texte):
                self.assertEqual(mf.disks_from(texte), [])
                self.assertEqual(mf._nvme_paths(texte), [])
        texte = json.dumps(
            {
                "blockdevices": [
                    {"name": "sda", "type": "disk", "children": [None, 1]}
                ]
            }
        )
        self.assertEqual([d["name"] for d in mf.disks_from(texte)], ["sda"])

    def test_facts_feed_the_profile_resolution(self):
        from script.iso.archlinux.machine import machine_profile as mp

        s, _q = mp.resolve({"disk": {"layout": "lvm_on_luks"}}, self.faits())
        # Le plus grand disque fixe, jamais la clé de démarrage.
        self.assertEqual(s["disk"]["target"], "/dev/sdb")
        self.assertEqual(s["disk"]["luks"]["sector_size"], 4096)
        self.assertEqual(s["gpu"]["driver"], "nouveau")
        self.assertEqual(s["desktop"]["power"], "tlp")


if __name__ == "__main__":
    unittest.main()
