#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire d'échange : lecture de l'état.

Chaque test fabrique sa racine (/proc, /sys, /etc) dans un répertoire
temporaire ; shutil.disk_usage est remplacé, et subprocess.run lève : un
test ne lit rien de la machine qui le lance et n'exécute rien.
"""

import collections
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_swap as ss  # noqa: E402

MIO = ss.MIO
GIO = ss.GIO
Usage = collections.namedtuple("Usage", "total used free")

MEMINFO = """\
MemTotal:       {total} kB
MemFree:          100000 kB
MemAvailable:   {available} kB
SwapTotal:       4194300 kB
SwapFree:        4194300 kB
"""

MOUNTINFO_EXT4 = (
    "22 1 254:1 / / rw,relatime shared:1 - ext4 /dev/vda1 rw\n"
    "23 22 0:21 / /proc rw shared:2 - proc proc rw\n"
    "24 22 254:2 / /data rw,relatime shared:3 - xfs /dev/vdb1 rw\n"
    "25 22 0:30 / /tmp rw shared:4 - tmpfs tmpfs rw\n"
)
MOUNTINFO_BTRFS = (
    "22 1 0:25 /@ / rw,relatime shared:1 - btrfs /dev/vda2 rw,subvol=/@\n"
    "23 22 0:25 /@home /home rw shared:2 - btrfs /dev/vda2 rw\n"
)

OS_RELEASE = {
    "arch": "ID=arch\n",
    "debian": "ID=debian\n",
    "ubuntu": "ID=ubuntu\nID_LIKE=debian\n",
    "fedora": "ID=fedora\n",
    "opensuse": 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
    "nixos": "ID=nixos\n",
}


def swaps(*lignes):
    """Un /proc/swaps : (chemin, type, Kio, Kio utilisés, priorité)."""
    entete = "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
    return entete + "".join(
        f"{c}\t{t}\t{s}\t{u}\t{p}\n" for c, t, s, u, p in lignes
    )


class Racine:
    """Une arborescence fabriquée, et les remplacements de ce qui ne se
    lit pas dans un fichier."""

    def __init__(self, test, distro="arch"):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.chemin = self.tmp.name
        self.libre = {}
        self.ecrire("/etc/os-release", OS_RELEASE[distro])
        self.ecrire("/proc/cmdline", "root=/dev/vda1 rw quiet\n")
        self.ecrire("/proc/self/mountinfo", MOUNTINFO_EXT4)
        self.ecrire("/proc/swaps", swaps())
        self.memoire(8 * GIO, 6 * GIO)
        os.makedirs(self.sous("/sys/block"), exist_ok=True)
        for patch in self.patches():
            patch.start()
            test.addCleanup(patch.stop)

    def sous(self, chemin):
        return os.path.join(self.chemin, chemin.lstrip("/"))

    def ecrire(self, chemin, texte):
        cible = self.sous(chemin)
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        with open(cible, "w") as fh:
            fh.write(texte)

    def memoire(self, total, disponible):
        self.ecrire(
            "/proc/meminfo",
            MEMINFO.format(total=total // 1024, available=disponible // 1024),
        )

    def zram(self, nom, disksize, mm_stat, algo="lzo-rle [zstd] lz4"):
        self.ecrire(f"/sys/block/{nom}/disksize", f"{disksize}\n")
        self.ecrire(f"/sys/block/{nom}/comp_algorithm", algo + "\n")
        self.ecrire(f"/sys/block/{nom}/mm_stat", mm_stat + "\n")

    def patches(self):
        def disk_usage(chemin):
            point = "/" + os.path.relpath(chemin, self.chemin).strip(".")
            point = point.rstrip("/") or "/"
            if point not in self.libre:
                raise OSError("absent")
            return Usage(100 * GIO, 0, self.libre[point])

        def interdit(*a, **k):
            raise AssertionError("subprocess.run appelé pendant un test")

        return [
            mock.patch.object(ss.shutil, "disk_usage", side_effect=disk_usage),
            mock.patch.object(subprocess, "run", side_effect=interdit),
        ]

    def etat(self):
        return ss.etat(self.chemin)


class TestLecture(unittest.TestCase):
    def test_swaps_types_sizes_and_escaped_path(self):
        texte = swaps(
            ("/swap\\040dir/swapfile", "file", 4194300, 1024, -2),
            ("/dev/vda3", "partition", 2097148, 0, -3),
            ("/dev/zram0", "partition", 4194300, 2048, 100),
        )
        lus = ss.lire_swaps(texte)
        self.assertEqual(
            [(s["path"], s["type"]) for s in lus],
            [
                ("/swap dir/swapfile", "file"),
                ("/dev/vda3", "partition"),
                ("/dev/zram0", "zram"),
            ],
        )
        self.assertEqual(lus[0]["size"], 4194300 * 1024)
        self.assertEqual(lus[0]["used"], 1024 * 1024)
        self.assertEqual(lus[2]["priority"], 100)
        self.assertEqual(ss.lire_swaps(None), [])
        self.assertEqual(ss.lire_swaps(swaps()), [])

    def test_cmdline_resume(self):
        self.assertEqual(
            ss.lire_cmdline(
                "root=/dev/vda1 resume=UUID=ab-cd resume_offset=34816"
            ),
            {"resume": "UUID=ab-cd", "resume_offset": 34816},
        )
        self.assertEqual(
            ss.lire_cmdline("quiet splash"),
            {"resume": None, "resume_offset": None},
        )

    def test_mountinfo_and_longest_prefix(self):
        montages = ss.lire_mountinfo(MOUNTINFO_EXT4)
        self.assertEqual(
            ss.montage_de("/data/swapfile", montages)["fstype"], "xfs"
        )
        self.assertEqual(
            ss.montage_de("/swapfile", montages)["fstype"], "ext4"
        )
        self.assertEqual(
            ss.montage_de("/database", montages)["mountpoint"], "/"
        )
        self.assertIsNone(ss.montage_de("/x", []))
        btrfs = ss.lire_mountinfo(MOUNTINFO_BTRFS)
        self.assertEqual(btrfs[0]["root"], "/@")
        self.assertEqual(btrfs[0]["source"], "/dev/vda2")

    def test_zram_devices(self):
        r = Racine(self)
        r.zram("zram0", 4 * GIO, "300000000 100000000 110000000 0 0 0 0 0")
        r.zram("zram1", 0, "0 0 0 0 0 0 0 0", algo="[lzo] zstd")
        os.makedirs(r.sous("/sys/block/vda"))
        lus = ss.lire_zram(r.sous("/sys/block"))
        self.assertEqual([z["name"] for z in lus], ["zram0", "zram1"])
        self.assertEqual(lus[0]["disksize"], 4 * GIO)
        self.assertEqual(lus[0]["algorithm"], "zstd")
        self.assertEqual(lus[0]["algorithms"], ["lzo-rle", "zstd", "lz4"])
        self.assertAlmostEqual(lus[0]["ratio"], 3.0)
        self.assertEqual(lus[0]["mem_used"], 110000000)
        self.assertIsNone(lus[1]["ratio"])
        self.assertEqual(ss.lire_zram(r.sous("/nulle/part")), [])

    def test_hibernation_target(self):
        fichier = {"type": "file", "path": "/swapfile"}
        partition = {"type": "partition", "path": "/dev/vda3"}
        zram = {"type": "zram", "path": "/dev/zram0"}
        aucun = {"resume": None, "resume_offset": None}
        avec_offset = {"resume": "UUID=ab", "resume_offset": 1234}
        par_uuid = {"resume": "UUID=ab", "resume_offset": None}
        par_dev = {"resume": "/dev/vda3", "resume_offset": None}
        autre_dev = {"resume": "/dev/vdb9", "resume_offset": None}
        self.assertFalse(ss.vise_hibernation(fichier, aucun))
        self.assertTrue(ss.vise_hibernation(fichier, avec_offset))
        self.assertFalse(ss.vise_hibernation(fichier, par_uuid))
        self.assertTrue(ss.vise_hibernation(partition, par_uuid))
        self.assertTrue(ss.vise_hibernation(partition, par_dev))
        self.assertFalse(ss.vise_hibernation(partition, autre_dev))
        self.assertFalse(ss.vise_hibernation(zram, avec_offset))

    def test_recommendation(self):
        rec = ss.recommandation
        self.assertEqual(rec(1 * GIO)["swap"], 2 * GIO)
        self.assertEqual(rec(2 * GIO)["swap"], 4 * GIO)
        self.assertEqual(rec(3 * GIO)["swap"], 4 * GIO)
        self.assertEqual(rec(6 * GIO)["swap"], 6 * GIO)
        self.assertEqual(rec(32 * GIO)["swap"], 8 * GIO)
        self.assertEqual(rec(4 * GIO)["zram"], 2 * GIO)
        self.assertEqual(rec(64 * GIO)["zram"], 8 * GIO)
        hib = rec(16 * GIO, hibernation=True)
        self.assertEqual(hib["swap"], 20 * GIO)
        self.assertEqual(hib["basis"], "hibernation")
        self.assertIsNone(rec(None)["swap"])


class TestPersistanceZram(unittest.TestCase):
    def test_fedora_defaults_in_usr_lib(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire(
            "/usr/lib/systemd/zram-generator.conf",
            "# défauts\n[zram0]\nzram-size = min(ram, 8192)\n",
        )
        p = ss.persistance_zram(r.chemin, "fedora")
        self.assertEqual(p["mode"], "zram-generator")
        self.assertEqual(
            p["generator"]["main"], "/usr/lib/systemd/zram-generator.conf"
        )
        self.assertEqual(
            p["generator"]["sections"]["zram0"]["zram-size"], "min(ram, 8192)"
        )
        self.assertEqual(p["generator_devices"], ["zram0"])

    def test_empty_etc_file_masks_usr_lib(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire("/usr/lib/systemd/zram-generator.conf", "[zram0]\n")
        r.ecrire("/etc/systemd/zram-generator.conf", "")
        p = ss.persistance_zram(r.chemin, "fedora")
        self.assertEqual(
            p["generator"]["main"], "/etc/systemd/zram-generator.conf"
        )
        self.assertIsNone(p["mode"])

    def test_dropins_sorted_and_etc_overrides_same_name(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire(
            "/usr/lib/systemd/zram-generator.conf.d/10-a.conf",
            "[zram0]\nzram-size = 100\n",
        )
        r.ecrire(
            "/usr/lib/systemd/zram-generator.conf.d/20-b.conf",
            "[zram0]\nswap-priority = 5\n",
        )
        r.ecrire(
            "/etc/systemd/zram-generator.conf.d/20-b.conf",
            "[zram0]\nswap-priority = 7\n",
        )
        g = ss.config_zram_generator(r.chemin)
        self.assertIsNone(g["main"])
        self.assertEqual(
            g["dropins"],
            [
                "/usr/lib/systemd/zram-generator.conf.d/10-a.conf",
                "/etc/systemd/zram-generator.conf.d/20-b.conf",
            ],
        )
        self.assertEqual(
            g["sections"]["zram0"], {"zram-size": "100", "swap-priority": "7"}
        )
        self.assertEqual(
            g["etc_dropins"], ["/etc/systemd/zram-generator.conf.d/20-b.conf"]
        )
        self.assertEqual(
            g["usr_dropins"],
            ["/usr/lib/systemd/zram-generator.conf.d/10-a.conf"],
        )

    def test_zram_tools_and_nixos_and_none(self):
        r = Racine(self, "debian")
        self.assertIsNone(ss.persistance_zram(r.chemin, "debian")["mode"])
        r.ecrire(ss.ZRAMSWAP_DEFAULT, "ALGO=lz4\nPERCENT=50\n#SIZE=256\n")
        p = ss.persistance_zram(r.chemin, "debian")
        self.assertEqual(p["mode"], "zram-tools")
        self.assertEqual(p["zram_tools"], {"ALGO": "lz4", "PERCENT": "50"})
        self.assertFalse(p["both"])
        self.assertEqual(
            ss.persistance_zram(r.chemin, "nixos")["mode"], "nixos"
        )

    def test_other_zram_services(self):
        r = Racine(self, "ubuntu")
        r.ecrire("/usr/bin/init-zram-swapping", "")
        p = ss.persistance_zram(r.chemin, "ubuntu")
        self.assertEqual(p["mode"], "service")
        self.assertEqual(p["service"], "zram-config.service")
        r = Racine(self, "opensuse")
        r.ecrire("/usr/sbin/zramswapon", "")
        p = ss.persistance_zram(r.chemin, "opensuse")
        self.assertEqual(
            (p["mode"], p["service"]), ("service", "zramswap.service")
        )
        self.assertFalse(p["zram_tools_installed"])
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire("/etc/systemd/zram-generator.conf", "[zram0]\n")
        p = ss.persistance_zram(r.chemin, "opensuse")
        self.assertEqual((p["mode"], p["service"]), ("zram-generator", None))

    def test_both_tools(self):
        r = Racine(self, "debian")
        r.ecrire(ss.ZRAMSWAP_DEFAULT, "PERCENT=50\n")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[1], "")
        r.ecrire("/etc/systemd/zram-generator.conf", "[zram0]\n")
        p = ss.persistance_zram(r.chemin, "debian")
        self.assertEqual(p["mode"], "zram-generator")
        self.assertTrue(p["both"])


class TestEtat(unittest.TestCase):
    def test_full_state(self):
        r = Racine(self)
        r.ecrire(
            "/proc/swaps",
            swaps(
                ("/swapfile", "file", 4194300, 1048576, -2),
                ("/dev/zram0", "partition", 4194300, 0, 100),
            ),
        )
        r.zram("zram0", 4 * GIO, "0 0 0 0 0 0 0 0")
        r.ecrire(
            "/proc/cmdline", "root=/dev/vda1 resume=UUID=ab resume_offset=9\n"
        )
        r.libre = {"/": 20 * GIO}
        e = r.etat()
        self.assertEqual(e["memory"]["total"], 8 * GIO)
        self.assertEqual(e["memory"]["available"], 6 * GIO)
        fichier, zram = e["swaps"]
        self.assertEqual(fichier["fs"]["fstype"], "ext4")
        self.assertEqual(fichier["free"], 20 * GIO)
        self.assertTrue(fichier["hibernation"])
        self.assertFalse(zram["hibernation"])
        self.assertIsNone(zram["fs"])
        self.assertTrue(e["zram"][0]["active"])
        self.assertEqual(e["root_fs"]["mountpoint"], "/")
        self.assertEqual(e["root_free"], 20 * GIO)
        self.assertEqual(e["recommendation"]["basis"], "hibernation")

    def test_swap_growth_uses_swapfile_filesystem(self):
        r = Racine(self)
        r.libre = {"/": 10 * GIO, "/data": 3 * GIO}
        r.ecrire(
            "/proc/swaps", swaps(("/data/swapfile", "file", 2097148, 0, -2))
        )
        self.assertEqual(ss.croissance_swap(r.etat()), 2 * GIO)
        r.libre = {}
        self.assertIsNone(ss.croissance_swap(r.etat()))


if __name__ == "__main__":
    unittest.main()
