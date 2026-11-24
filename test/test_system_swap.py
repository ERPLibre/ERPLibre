#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire d'échange : lecture de l'état, plans de swap et de zram,
verdict sur l'ajout de RAM.

Chaque test fabrique sa racine (/proc, /sys, /etc) dans un répertoire
temporaire ; shutil.disk_usage, shutil.which et les commandes lues sont
remplacés, et subprocess.run lève : un test ne lit rien de la machine qui
le lance et n'exécute rien.
"""

import collections
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_swap as ss  # noqa: E402

# Le vrai subprocess.run, avant que chaque Racine ne le remplace : seul le
# test qui joue la commande de fstab sur une copie s'en sert.
REEL_RUN = subprocess.run

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
BINAIRE = {
    "arch": "pacman",
    "debian": "apt-get",
    "ubuntu": "apt-get",
    "fedora": "dnf",
    "opensuse": "zypper",
    "nixos": "nix-shell",
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
        self.binaires = {BINAIRE[distro]}
        self.sorties = {}
        self.ecrire("/etc/os-release", OS_RELEASE[distro])
        self.ecrire("/etc/fstab", "/dev/vda1 / ext4 defaults 0 1\n")
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

    def lien(self, chemin, cible):
        """Un lien symbolique `chemin` -> `cible`, écrit tel quel."""
        source = self.sous(chemin)
        os.makedirs(os.path.dirname(source), exist_ok=True)
        os.symlink(cible, source)

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

        def commande(args, timeout=5, codes_ok=(0,)):
            return self.sorties.get(args[0])

        def interdit(*a, **k):
            raise AssertionError("subprocess.run appelé pendant un test")

        return [
            mock.patch.object(ss.shutil, "disk_usage", side_effect=disk_usage),
            mock.patch.object(
                ss.shutil,
                "which",
                side_effect=lambda b: (
                    f"/usr/bin/{b}" if b in self.binaires else None
                ),
            ),
            mock.patch.object(ss, "commande", side_effect=commande),
            mock.patch.object(subprocess, "run", side_effect=interdit),
        ]

    def etat(self):
        return ss.etat(self.chemin)


class TestParseTaille(unittest.TestCase):
    def test_accepted_forms(self):
        self.assertEqual(ss.parse_taille("4G"), 4 * GIO)
        self.assertEqual(ss.parse_taille("4GiB"), 4 * GIO)
        self.assertEqual(ss.parse_taille("4 gb"), 4 * GIO)
        self.assertEqual(ss.parse_taille("512M"), 512 * MIO)
        self.assertEqual(ss.parse_taille("1.5G"), 1536 * MIO)
        self.assertEqual(ss.parse_taille("1,5G"), 1536 * MIO)
        self.assertEqual(ss.parse_taille("2048"), 2 * GIO)
        self.assertEqual(ss.parse_taille("1T"), 1024 * GIO)

    def test_french_suffixes_and_the_menu_own_output(self):
        """Le menu écrit « 8.0 Gio » : la recopier doit se relire."""
        self.assertEqual(ss.parse_taille("8.0 Gio"), 8 * GIO)
        self.assertEqual(ss.parse_taille("4 Gio"), 4 * GIO)
        self.assertEqual(ss.parse_taille("4Go"), 4 * GIO)
        self.assertEqual(ss.parse_taille("512 Mio"), 512 * MIO)
        self.assertEqual(ss.parse_taille("512mo"), 512 * MIO)
        self.assertEqual(ss.parse_taille("1 Tio"), 1024 * GIO)
        self.assertEqual(ss.parse_taille("2Gi"), 2 * GIO)

    def test_rounds_down_to_mib(self):
        self.assertEqual(ss.parse_taille("1.0001G"), 1024 * MIO)

    def test_rejects_nonsense(self):
        for texte in (
            None,
            "",
            "abc",
            "-4G",
            "0",
            "0G",
            "4X",
            "4 G G",
            "nan",
            "inf",
            "1e3",
            "100K",
            "100000T",
            "4 Gibo",
            "4 oG",
        ):
            self.assertIsNone(ss.parse_taille(texte), texte)


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

    def test_btrfs_version(self):
        self.assertEqual(ss.version_btrfs("btrfs-progs v6.6.3\n"), (6, 6))
        self.assertIsNone(ss.version_btrfs(None))


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
        self.assertEqual(p["generator"]["main"], ss.ZRAM_GENERATOR_ETC)
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
        r.ecrire(ss.ZRAM_GENERATOR_ETC, "[zram0]\n")
        p = ss.persistance_zram(r.chemin, "opensuse")
        self.assertEqual((p["mode"], p["service"]), ("zram-generator", None))

    def test_both_tools(self):
        r = Racine(self, "debian")
        r.ecrire(ss.ZRAMSWAP_DEFAULT, "PERCENT=50\n")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[1], "")
        r.ecrire(ss.ZRAM_GENERATOR_ETC, "[zram0]\n")
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
        r.sorties["systemd-detect-virt"] = "none\n"
        e = r.etat()
        self.assertEqual(e["memory"]["total"], 8 * GIO)
        self.assertEqual(e["memory"]["available"], 6 * GIO)
        fichier, zram = e["swaps"]
        self.assertEqual(fichier["fs"]["fstype"], "ext4")
        self.assertEqual(fichier["free"], 20 * GIO)
        self.assertEqual(fichier["max_size"], fichier["size"] + 19 * GIO)
        self.assertTrue(fichier["hibernation"])
        self.assertFalse(zram["hibernation"])
        self.assertIsNone(zram["fs"])
        self.assertTrue(e["zram"][0]["active"])
        self.assertEqual(e["root_fs"]["mountpoint"], "/")
        self.assertEqual(e["root_free"], 20 * GIO)
        self.assertEqual(e["manager"], "pacman")
        self.assertIsNone(e["virtualization"])
        self.assertFalse(e["btrfs_mkswapfile"])
        self.assertEqual(e["recommendation"]["basis"], "hibernation")
        self.assertEqual(
            ss.chemin_par_defaut(e), {"path": "/swapfile", "reason": None}
        )

    def test_vm_and_btrfs(self):
        r = Racine(self)
        r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        r.binaires.add("btrfs")
        r.sorties["btrfs"] = "btrfs-progs v6.1\n"
        r.sorties["systemd-detect-virt"] = "kvm\n"
        e = r.etat()
        self.assertTrue(e["btrfs_mkswapfile"])
        self.assertEqual(e["virtualization"], "kvm")
        self.assertIsNone(e["root_free"])
        self.assertEqual(ss.chemin_par_defaut(e)["path"], "/swap/swapfile")
        r.sorties["btrfs"] = "btrfs-progs v5.16.2\n"
        self.assertFalse(r.etat()["btrfs_mkswapfile"])
        self.assertFalse(e["container"])

    def test_container_refuses_every_plan(self):
        """Dans un conteneur, swapon et la zram échouent faute de droits :
        aucun plan ne se propose, pas même la création d'un fichier."""
        r = Racine(self)
        r.libre = {"/": 20 * GIO}
        r.sorties["systemd-detect-virt"] = "lxc\n"
        r.ecrire("/proc/swaps", swaps(("none", "virtual", 2097148, 0, 0)))
        e = r.etat()
        self.assertTrue(e["container"])
        self.assertEqual(e["virtualization"], "lxc")
        for res in (
            ss.plan_redimensionner(e, "none", 4 * GIO, "grow"),
            ss.plan_creer(e, "/swapfile", 2 * GIO),
            ss.plan_zram(e, 2 * GIO, "/tmp-de-test"),
            ss.plan_zram_desactiver(e, "/tmp-de-test"),
            ss.plan_swappiness(e, 100, 0),
        ):
            self.assertEqual(res["reason"], "container")
            self.assertEqual(res["details"]["virtualization"], "lxc")
            self.assertEqual(res["plan"], [])


class TestRedimensionner(unittest.TestCase):
    def setUp(self):
        self.r = Racine(self)
        self.r.libre = {"/": 20 * GIO, "/data": 3 * GIO}

    def avec(self, *lignes):
        self.r.ecrire("/proc/swaps", swaps(*lignes))
        return self.r.etat()

    def test_grow_ext4_uses_fallocate(self):
        e = self.avec(("/swapfile", "file", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/swapfile", 4 * GIO, "grow")
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            res["plan"],
            [
                ["sudo", "swapoff", "/swapfile"],
                ["sudo", "rm", "-f", "/swapfile"],
                ["sudo", "fallocate", "-l", "4096MiB", "/swapfile"],
                ["sudo", "chmod", "600", "/swapfile"],
                ["sudo", "mkswap", "/swapfile"],
                ["sudo", "swapon", "/swapfile"],
            ],
        )
        self.assertEqual(res["details"]["new"], 4 * GIO)
        self.assertEqual(res["warnings"], [])
        depuis = res["details"]["recovery_from"]
        self.assertEqual(
            res["plan"][depuis], ["sudo", "rm", "-f", "/swapfile"]
        )

    def test_shrink_keeps_explicit_priority(self):
        e = self.avec(("/swapfile", "file", 4194300, 0, 10))
        res = ss.plan_redimensionner(e, "/swapfile", 1 * GIO, "shrink")
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            res["plan"][-1], ["sudo", "swapon", "-p", "10", "/swapfile"]
        )

    def test_direction_and_floor(self):
        e = self.avec(("/swapfile", "file", 2097148, 0, -2))
        r = ss.plan_redimensionner
        self.assertEqual(
            r(e, "/swapfile", GIO, "grow")["reason"], "not_larger"
        )
        self.assertEqual(
            r(e, "/swapfile", 3 * GIO, "shrink")["reason"], "not_smaller"
        )
        self.assertEqual(r(e, "/swapfile", 2 * GIO)["reason"], "same_size")
        self.assertEqual(r(e, "/swapfile", 128 * MIO)["reason"], "below_floor")
        self.assertEqual(r(e, "/nope", 3 * GIO)["reason"], "not_active")

    def test_partition_cannot_be_resized(self):
        e = self.avec(("/dev/vda3", "partition", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/dev/vda3", 4 * GIO)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "partition")
        self.assertEqual(res["details"]["suggestion"], "/swapfile")
        self.assertEqual(res["plan"], [])
        reduire = ss.plan_redimensionner(e, "/dev/vda3", GIO, "shrink")
        self.assertEqual(reduire["reason"], "partition_shrink")
        self.assertNotIn("suggestion", reduire["details"])

    def test_zram_is_refused(self):
        e = self.avec(("/dev/zram0", "partition", 2097148, 0, 100))
        self.assertEqual(
            ss.plan_redimensionner(e, "/dev/zram0", 4 * GIO)["reason"], "zram"
        )

    def test_ram_cannot_absorb_used_swap(self):
        self.r.memoire(8 * GIO, 1 * GIO)
        e = self.avec(("/swapfile", "file", 4194300, 2 * 1024 * 1024, -2))
        res = ss.plan_redimensionner(e, "/swapfile", 6 * GIO)
        self.assertEqual(res["reason"], "ram_cannot_absorb")
        self.assertEqual(res["details"]["used"], 2 * GIO)
        self.assertEqual(res["details"]["capacity"], GIO - ss.MARGE_MEMOIRE)

    def test_free_space_in_other_disk_swap_counts_but_zram_does_not(self):
        self.r.memoire(8 * GIO, 1 * GIO)
        e = self.avec(
            ("/swapfile", "file", 4194300, 2 * 1024 * 1024, -2),
            ("/dev/zram0", "partition", 8388604, 0, 100),
        )
        self.assertEqual(
            ss.plan_redimensionner(e, "/swapfile", 6 * GIO)["reason"],
            "ram_cannot_absorb",
        )
        e = self.avec(
            ("/swapfile", "file", 4194300, 2 * 1024 * 1024, -2),
            ("/dev/vda3", "partition", 4194300, 0, -3),
        )
        self.assertTrue(ss.plan_redimensionner(e, "/swapfile", 6 * GIO)["ok"])

    def test_disk_full(self):
        e = self.avec(("/data/swapfile", "file", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/data/swapfile", 5 * GIO, "grow")
        self.assertEqual(res["reason"], "disk_full")
        self.assertEqual(res["details"]["free"], 3 * GIO)
        self.assertEqual(
            res["details"]["needed"],
            5 * GIO - 2097148 * 1024 + ss.MARGE_DISQUE,
        )
        ok = ss.plan_redimensionner(e, "/data/swapfile", 3584 * MIO, "grow")
        self.assertTrue(ok["ok"], ok)
        self.assertIn(
            ["sudo", "fallocate", "-l", "3584MiB", "/data/swapfile"],
            ok["plan"],
        )

    def test_shrink_needs_no_free_space(self):
        self.r.libre = {}
        e = self.avec(("/swapfile", "file", 4194300, 0, -2))
        self.assertTrue(ss.plan_redimensionner(e, "/swapfile", GIO)["ok"])
        self.assertEqual(
            ss.plan_redimensionner(e, "/swapfile", 8 * GIO)["reason"],
            "disk_unknown",
        )

    def test_btrfs_mkswapfile_or_nocow_fallback(self):
        self.r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        self.r.binaires.add("btrfs")
        self.r.sorties["btrfs"] = "btrfs-progs v6.6.3"
        e = self.avec(("/swap/swapfile", "file", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/swap/swapfile", 4 * GIO)
        self.assertEqual(
            res["plan"][2:],
            [
                [
                    "sudo",
                    "btrfs",
                    "filesystem",
                    "mkswapfile",
                    "--size",
                    "4096m",
                    "/swap/swapfile",
                ],
                ["sudo", "chmod", "600", "/swap/swapfile"],
                ["sudo", "swapon", "/swap/swapfile"],
            ],
        )
        self.r.sorties["btrfs"] = "btrfs-progs v5.10"
        e = self.r.etat()
        res = ss.plan_redimensionner(e, "/swap/swapfile", 4 * GIO)
        self.assertEqual(
            [c[1] for c in res["plan"]],
            [
                "swapoff",
                "rm",
                "truncate",
                "chattr",
                "fallocate",
                "chmod",
                "mkswap",
                "swapon",
            ],
        )

    def test_other_filesystem_uses_dd(self):
        self.r.ecrire(
            "/proc/self/mountinfo",
            "22 1 254:1 / / rw - f2fs /dev/vda1 rw\n",
        )
        e = self.avec(("/swapfile", "file", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/swapfile", 3 * GIO)
        self.assertIn(
            [
                "sudo",
                "dd",
                "if=/dev/zero",
                "of=/swapfile",
                "bs=1M",
                "count=3072",
                "status=progress",
            ],
            res["plan"],
        )

    def test_unsupported_filesystem(self):
        self.r.ecrire(
            "/proc/self/mountinfo",
            "22 1 0:40 / / rw - zfs pool/root rw\n",
        )
        e = self.avec(("/swapfile", "file", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/swapfile", 3 * GIO)
        self.assertEqual(res["reason"], "fs_unsupported")
        self.assertEqual(res["details"]["fstype"], "zfs")

    def test_hibernation_warning(self):
        self.r.ecrire("/proc/cmdline", "resume=UUID=ab resume_offset=1234\n")
        e = self.avec(("/swapfile", "file", 2097148, 0, -2))
        res = ss.plan_redimensionner(e, "/swapfile", 3 * GIO)
        self.assertTrue(res["ok"])
        self.assertEqual(
            res["warnings"], [{"code": "hibernation", "resume": "UUID=ab"}]
        )

    def test_nixos_gets_a_snippet(self):
        r = Racine(self, "nixos")
        r.ecrire("/proc/swaps", swaps(("/swapfile", "file", 2097148, 0, -2)))
        res = ss.plan_redimensionner(r.etat(), "/swapfile", 3 * GIO)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "nixos")
        self.assertEqual(res["plan"], [])
        self.assertIn('device = "/swapfile"; size = 3072;', res["nix"])


class TestCreer(unittest.TestCase):
    def setUp(self):
        self.r = Racine(self)
        self.r.libre = {"/": 20 * GIO, "/data": 3 * GIO}

    def test_create_on_ext4_and_add_fstab_line(self):
        res = ss.plan_creer(
            self.r.etat(), "/swapfile", 2 * GIO, "20260101-000000"
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            res["plan"],
            [
                ["sudo", "test", "!", "-e", "/swapfile"],
                ["sudo", "fallocate", "-l", "2048MiB", "/swapfile"],
                ["sudo", "chmod", "600", "/swapfile"],
                ["sudo", "mkswap", "/swapfile"],
                ["sudo", "swapon", "/swapfile"],
                [
                    "sudo",
                    "cp",
                    "-a",
                    "/etc/fstab",
                    "/etc/fstab.bak-20260101-000000",
                ],
                [
                    "sudo",
                    "sh",
                    "-c",
                    '[ -z "$(tail -c 1 /etc/fstab)" ] || echo >> /etc/fstab; '
                    "printf '%s\\n' '/swapfile none swap defaults 0 0'"
                    " >> /etc/fstab",
                ],
            ],
        )
        self.assertEqual(res["details"]["fstab"], "added")

    @unittest.skipUnless(
        shutil.which("sh") and shutil.which("tail"), "sh et tail requis"
    )
    def test_fstab_append_never_glues_onto_the_last_line(self):
        """La commande du plan, lancée sur une copie : un fstab sans saut
        de ligne final, un fstab qui en a un, un fstab vide."""
        res = ss.plan_creer(self.r.etat(), "/swapfile", 2 * GIO)
        script = res["plan"][-1][3]
        ligne = "/swapfile none swap defaults 0 0\n"
        racine_ligne = "UUID=0000-test / ext4 defaults 0 1"
        cas = {
            racine_ligne: racine_ligne + "\n" + ligne,
            racine_ligne + "\n": racine_ligne + "\n" + ligne,
            "": ligne,
        }
        for avant, apres in cas.items():
            with self.subTest(avant=avant):
                copie = os.path.join(self.r.chemin, "fstab-copie")
                with open(copie, "w") as fh:
                    fh.write(avant)
                with mock.patch.object(subprocess, "run", new=REEL_RUN):
                    subprocess.run(
                        ["sh", "-c", script.replace("/etc/fstab", copie)],
                        check=True,
                    )
                with open(copie) as fh:
                    self.assertEqual(fh.read(), apres)

    def test_creation_refuses_a_file_it_cannot_see(self):
        """lexists ne voit pas dans un répertoire non traversable : la
        première commande, lancée avec sudo, refuse un fichier existant."""
        res = ss.plan_creer(self.r.etat(), "/swapfile", 2 * GIO)
        self.assertEqual(
            res["plan"][0], ["sudo", "test", "!", "-e", "/swapfile"]
        )
        ecrit = [
            c for c in res["plan"] if c[1] in ("fallocate", "dd", "mkswap")
        ]
        self.assertTrue(ecrit)

    def test_existing_fstab_line_is_not_duplicated(self):
        self.r.ecrire(
            "/etc/fstab",
            "#/swapfile none swap defaults 0 0\n/swapfile none swap sw 0 0\n",
        )
        res = ss.plan_creer(self.r.etat(), "/swapfile", 2 * GIO)
        self.assertEqual(res["details"]["fstab"], "present")
        self.assertFalse(any("/etc/fstab" in c for c in res["plan"]))

    def test_commented_fstab_line_does_not_count(self):
        self.r.ecrire("/etc/fstab", "# /swapfile none swap defaults 0 0\n")
        res = ss.plan_creer(self.r.etat(), "/swapfile", 2 * GIO)
        self.assertEqual(res["details"]["fstab"], "added")

    def test_path_with_space_is_escaped_in_fstab(self):
        os.makedirs(self.r.sous("/swap dir"))
        res = ss.plan_creer(self.r.etat(), "/swap dir/f", 2 * GIO)
        self.assertEqual(
            res["details"]["line"], "/swap\\040dir/f none swap defaults 0 0"
        )
        self.assertTrue(
            ss.dans_fstab(res["details"]["line"] + "\n", "/swap dir/f")
        )

    def test_btrfs_default_creates_a_subvolume(self):
        self.r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        self.r.binaires.add("btrfs")
        self.r.sorties["btrfs"] = "btrfs-progs v6.6.3"
        e = self.r.etat()
        chemin = ss.chemin_par_defaut(e)["path"]
        res = ss.plan_creer(e, chemin, 2 * GIO, "x")
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            res["plan"][1], ["sudo", "btrfs", "subvolume", "create", "/swap"]
        )
        self.assertEqual(
            res["plan"][2][1:4], ["btrfs", "filesystem", "mkswapfile"]
        )
        self.assertEqual(res["warnings"], [])

    def sous_volumes(self, *chemins):
        """Les répertoires (chemins du système fabriqué) qui passent pour
        des racines de sous-volume btrfs."""
        reels = {self.r.sous(c).rstrip("/") for c in chemins}
        return mock.patch.object(
            ss,
            "_est_racine_sous_volume",
            side_effect=lambda p: p.rstrip("/") in reels,
        )

    def test_btrfs_plain_directory_warns_about_the_root_subvolume(self):
        """/swap existe, simple répertoire du sous-volume de « / » : le
        fichier y bloque les instantanés de la racine."""
        self.r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        os.makedirs(self.r.sous("/swap"))
        with self.sous_volumes():
            res = ss.plan_creer(self.r.etat(), "/swap/swapfile", 2 * GIO)
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            res["warnings"], [{"code": "btrfs_snapshot", "subvolume": "/"}]
        )

    def test_btrfs_dedicated_empty_subvolume_does_not_warn(self):
        self.r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        os.makedirs(self.r.sous("/swap"))
        with self.sous_volumes("/swap"):
            res = ss.plan_creer(self.r.etat(), "/swap/swapfile", 2 * GIO)
        self.assertEqual(res["warnings"], [])

    def test_btrfs_subvolume_holding_other_files_warns(self):
        """@home, monté sur /home, porte d'autres fichiers : un swapfile à
        sa racine en bloque les instantanés."""
        self.r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        self.r.libre["/home"] = 20 * GIO
        self.r.ecrire("/home/user-test/notes.txt", "")
        with self.sous_volumes("/home"):
            res = ss.plan_creer(self.r.etat(), "/home/swapfile", 2 * GIO)
        self.assertEqual(
            res["warnings"],
            [{"code": "btrfs_snapshot", "subvolume": "/home"}],
        )

    def test_btrfs_root_subvolume_warns_about_snapshots(self):
        self.r.ecrire("/proc/self/mountinfo", MOUNTINFO_BTRFS)
        res = ss.plan_creer(self.r.etat(), "/swapfile", 2 * GIO)
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            res["warnings"], [{"code": "btrfs_snapshot", "subvolume": "/"}]
        )

    def test_refusals(self):
        e = self.r.etat()
        self.r.ecrire("/old_swapfile", "")
        c = ss.plan_creer
        self.assertEqual(c(e, "swapfile", GIO)["reason"], "invalid_path")
        self.assertEqual(c(e, "/a/../swapfile", GIO)["reason"], "invalid_path")
        self.assertEqual(c(e, "/old_swapfile", GIO)["reason"], "exists")
        self.assertEqual(c(e, "/swapfile", 100 * MIO)["reason"], "below_floor")
        self.assertEqual(
            c(e, "/tmp/swapfile", GIO)["reason"], "fs_unsupported"
        )
        self.assertEqual(
            c(e, "/no/dir/swapfile", GIO)["reason"], "parent_missing"
        )
        os.makedirs(self.r.sous("/data"))
        full = c(e, "/data/swapfile", 3 * GIO)
        self.assertEqual(full["reason"], "disk_full")
        self.assertEqual(full["details"]["max_size"], 2 * GIO)

    def test_already_active(self):
        self.r.ecrire(
            "/proc/swaps", swaps(("/swapfile", "file", 2097148, 0, -2))
        )
        res = ss.plan_creer(self.r.etat(), "/swapfile", 2 * GIO)
        self.assertEqual(res["reason"], "already_active")

    def test_nixos(self):
        r = Racine(self, "nixos")
        res = ss.plan_creer(r.etat(), "/swapfile", 4 * GIO)
        self.assertEqual(res["reason"], "nixos")
        self.assertIn("size = 4096;", res["nix"])
        self.assertIn("nixos-rebuild switch", res["nix"])


class TestContenus(unittest.TestCase):
    def test_zram_generator_from_scratch(self):
        self.assertEqual(
            ss.contenu_zram_generator("", 4 * GIO),
            "[zram0]\nzram-size = 4096\ncompression-algorithm = zstd\n"
            "swap-priority = 100\n",
        )

    def test_zram_generator_keeps_comments_and_other_sections(self):
        avant = textwrap.dedent("""\
            # réglages locaux
            [zram0]
            # taille
            zram-size = min(ram, 8192)
            fs-type = swap

            [zram1]
            zram-size = 512
            """)
        apres = ss.contenu_zram_generator(avant, 2 * GIO)
        self.assertIn("# réglages locaux", apres)
        self.assertIn("# taille", apres)
        self.assertIn("fs-type = swap", apres)
        sections = ss.lire_ini(apres)
        self.assertEqual(
            sections["zram0"],
            {
                "zram-size": "2048",
                "fs-type": "swap",
                "compression-algorithm": "zstd",
                "swap-priority": "100",
            },
        )
        self.assertEqual(sections["zram1"], {"zram-size": "512"})

    def test_zram_generator_appends_section(self):
        apres = ss.contenu_zram_generator("[zram1]\nzram-size = 1\n", GIO)
        self.assertEqual(ss.lire_ini(apres)["zram0"]["zram-size"], "1024")
        self.assertEqual(ss.lire_ini(apres)["zram1"]["zram-size"], "1")

    def test_zramswap_comments_percent(self):
        apres = ss.contenu_zramswap(
            "# défauts\nALGO=lz4\nPERCENT=50\n#SIZE=256\n", 2 * GIO
        )
        self.assertEqual(
            apres,
            "# défauts\nALGO=zstd\n#PERCENT=50\n#SIZE=256\nSIZE=2048\n"
            "PRIORITY=100\n",
        )
        self.assertEqual(
            ss.lire_variables(apres),
            {"ALGO": "zstd", "SIZE": "2048", "PRIORITY": "100"},
        )

    def test_nix_snippet(self):
        texte = ss.extrait_nix(zram_pourcent=50)
        self.assertIn("zramSwap.enable = true;", texte)
        self.assertIn("zramSwap.memoryPercent = 50;", texte)
        self.assertIn("zramSwap.priority = 100;", texte)
        self.assertIn("zramSwap.enable = false;", ss.extrait_nix(zram=False))


class TestModuleZram(unittest.TestCase):
    """module_zram dit, avant tout plan, si le noyau en marche peut porter
    une zram. Les versions du noyau sont inventées."""

    TMP = "/tmp-de-test"
    EN_MARCHE = "9.8.7-test"

    def racine(self):
        r = Racine(self, "arch")
        r.ecrire("/proc/sys/kernel/osrelease", self.EN_MARCHE + "\n")
        return r

    def modules(self, r, version, dep="", builtin=""):
        r.ecrire(f"/lib/modules/{version}/modules.dep", dep)
        r.ecrire(f"/lib/modules/{version}/modules.builtin", builtin)

    def test_loaded(self):
        r = self.racine()
        os.makedirs(r.sous("/sys/module/zram"))
        self.assertEqual(ss.module_zram(r.chemin)["state"], "loaded")

    def test_available_loads_with_modprobe_before_the_reload(self):
        r = self.racine()
        self.modules(
            r,
            self.EN_MARCHE,
            dep="kernel/drivers/block/zram/zram.ko.zst: kernel/lib/x.ko\n",
        )
        self.assertEqual(ss.module_zram(r.chemin)["state"], "available")
        plan = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")["plan"]
        i = plan.index(["sudo", "modprobe", "zram"])
        self.assertEqual(plan[i + 1], ["sudo", "systemctl", "daemon-reload"])

    def test_builtin_needs_no_modprobe(self):
        r = self.racine()
        self.modules(
            r, self.EN_MARCHE, builtin="kernel/drivers/block/zram/zram.ko\n"
        )
        self.assertEqual(ss.module_zram(r.chemin)["state"], "builtin")
        plan = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")["plan"]
        self.assertNotIn(["sudo", "modprobe", "zram"], plan)

    def test_an_updated_kernel_package_asks_for_a_reboot(self):
        """Le paquet du noyau mis à jour sur disque emporte les modules du
        noyau en marche : rien ne se charge avant un redémarrage, et le
        plan est refusé avant d'installer quoi que ce soit."""
        r = self.racine()
        self.modules(r, "9.9.0-test", dep="x/zram.ko.zst:\n")
        module = ss.module_zram(r.chemin)
        self.assertEqual(module["state"], "reboot")
        self.assertEqual(module["installed"], ["9.9.0-test"])
        res = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "zram_reboot_required")
        self.assertEqual(res["details"]["running"], self.EN_MARCHE)
        self.assertEqual(res["details"]["installed"], "9.9.0-test")

    def test_a_kernel_without_zram_is_refused(self):
        r = self.racine()
        self.modules(r, self.EN_MARCHE, dep="kernel/fs/ext4/ext4.ko.zst:\n")
        self.assertEqual(ss.module_zram(r.chemin)["state"], "missing")
        res = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")
        self.assertEqual(res["reason"], "zram_unavailable")

    def test_no_module_directory_is_unknown_and_not_refused(self):
        """NixOS range ses modules ailleurs : l'absence de dossier ne
        prouve rien, le plan reste proposé."""
        r = self.racine()
        self.assertEqual(ss.module_zram(r.chemin)["state"], "unknown")
        res = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")
        self.assertTrue(res["ok"], res)
        self.assertNotIn(["sudo", "modprobe", "zram"], res["plan"])


class TestZram(unittest.TestCase):
    TMP = "/tmp-de-test"

    def test_arch_installs_generator_then_configures(self):
        r = Racine(self, "arch")
        res = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["details"]["tool"], "zram-generator")
        self.assertTrue(res["details"]["install"])
        tmp = os.path.join(self.TMP, "zram-generator.conf")
        self.assertEqual(
            res["plan"],
            [
                [
                    "sudo",
                    "pacman",
                    "-S",
                    "--needed",
                    "--noconfirm",
                    "zram-generator",
                ],
                [
                    "sudo",
                    "install",
                    "-D",
                    "-m",
                    "0644",
                    tmp,
                    ss.ZRAM_GENERATOR_ETC,
                ],
                ["sudo", "systemctl", "daemon-reload"],
                [
                    "sudo",
                    "systemctl",
                    "restart",
                    "systemd-zram-setup@zram0.service",
                ],
                ["sudo", "systemctl", "start", "dev-zram0.swap"],
            ],
        )
        self.assertEqual(
            ss.lire_ini(res["files"][tmp])["zram0"]["zram-size"], "4096"
        )

    def test_a_manual_zram_is_reset_before_the_generator_takes_it(self):
        """Une zram montée à la main occupe /dev/zram0 : le générateur
        n'en écrirait pas la taille. Elle s'éteint et se remet à zéro
        avant le redémarrage du service."""
        r = Racine(self, "arch")
        r.ecrire(
            "/proc/swaps", swaps(("/dev/zram0", "partition", 2097148, 0, 100))
        )
        plan = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")["plan"]
        i = plan.index(
            [
                "sudo",
                "systemctl",
                "restart",
                "systemd-zram-setup@zram0.service",
            ]
        )
        self.assertEqual(
            plan[i - 2 : i],
            [
                ["sudo", "swapoff", "/dev/zram0"],
                ["sudo", "zramctl", "--reset", "/dev/zram0"],
            ],
        )

    def test_a_generator_zram_is_only_restarted(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire("/usr/lib/systemd/zram-generator.conf", "[zram0]\n")
        r.ecrire(
            "/proc/swaps", swaps(("/dev/zram0", "partition", 2097148, 0, 100))
        )
        plan = ss.plan_zram(r.etat(), 4 * GIO, self.TMP, "s")["plan"]
        self.assertFalse(any(c[1] in ("swapoff", "zramctl") for c in plan))
        self.assertEqual(
            plan[-1], ["sudo", "systemctl", "start", "dev-zram0.swap"]
        )

    def test_another_zram_service_is_not_doubled(self):
        r = Racine(self, "ubuntu")
        r.ecrire("/usr/bin/init-zram-swapping", "")
        res = ss.plan_zram(r.etat(), 2 * GIO, self.TMP)
        self.assertEqual(res["reason"], "zram_service")
        self.assertEqual(res["details"]["service"], "zram-config.service")
        self.assertEqual(res["plan"], [])

    def test_package_names_per_family(self):
        attendu = {
            "debian": "systemd-zram-generator",
            "ubuntu": "systemd-zram-generator",
            "fedora": "zram-generator",
            "opensuse": "zram-generator",
        }
        for distro, paquet in attendu.items():
            with self.subTest(distro=distro):
                r = Racine(self, distro)
                plan = ss.plan_zram(r.etat(), GIO, self.TMP, "s")["plan"]
                installs = [c for c in plan if paquet in c]
                self.assertEqual(len(installs), 1, plan)
        r = Racine(self, "debian")
        plan = ss.plan_zram(r.etat(), GIO, self.TMP, "s")["plan"]
        self.assertEqual(plan[0], ["sudo", "apt-get", "update"])

    def test_fedora_starts_from_usr_lib_and_backs_up_etc(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire(
            "/usr/lib/systemd/zram-generator.conf",
            "[zram0]\nzram-size = min(ram, 8192)\nfs-type = swap\n",
        )
        res = ss.plan_zram(r.etat(), 2 * GIO, self.TMP, "s")
        self.assertFalse(res["details"]["install"])
        contenu = res["files"][os.path.join(self.TMP, "zram-generator.conf")]
        self.assertEqual(ss.lire_ini(contenu)["zram0"]["fs-type"], "swap")
        self.assertEqual(ss.lire_ini(contenu)["zram0"]["zram-size"], "2048")
        self.assertFalse(any(c[1] == "cp" for c in res["plan"]))
        r.ecrire(ss.ZRAM_GENERATOR_ETC, "[zram0]\n")
        res = ss.plan_zram(r.etat(), 2 * GIO, self.TMP, "s")
        self.assertIn(
            [
                "sudo",
                "cp",
                "-a",
                ss.ZRAM_GENERATOR_ETC,
                ss.ZRAM_GENERATOR_ETC + ".bak-s",
            ],
            res["plan"],
        )

    def test_dropin_override_and_disk_priority_warnings(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire(
            "/etc/systemd/zram-generator.conf.d/50-x.conf",
            "[zram0]\nzram-size = 100\n",
        )
        r.ecrire(
            "/proc/swaps", swaps(("/dev/vda3", "partition", 1000, 0, 100))
        )
        res = ss.plan_zram(r.etat(), GIO, self.TMP, "s")
        codes = {a["code"]: a for a in res["warnings"]}
        self.assertEqual(
            codes["dropin_overrides"]["paths"],
            ["/etc/systemd/zram-generator.conf.d/50-x.conf"],
        )
        self.assertEqual(codes["disk_priority"]["paths"], ["/dev/vda3"])

    def test_zram_tools(self):
        r = Racine(self, "debian")
        r.ecrire(ss.ZRAMSWAP_DEFAULT, "PERCENT=50\n")
        res = ss.plan_zram(r.etat(), 2 * GIO, self.TMP, "s")
        self.assertEqual(res["details"]["tool"], "zram-tools")
        tmp = os.path.join(self.TMP, "zramswap")
        self.assertIn("SIZE=2048", res["files"][tmp])
        self.assertEqual(
            res["plan"],
            [
                [
                    "sudo",
                    "cp",
                    "-a",
                    ss.ZRAMSWAP_DEFAULT,
                    ss.ZRAMSWAP_DEFAULT + ".bak-s",
                ],
                [
                    "sudo",
                    "install",
                    "-D",
                    "-m",
                    "0644",
                    tmp,
                    ss.ZRAMSWAP_DEFAULT,
                ],
                ["sudo", "systemctl", "enable", "zramswap.service"],
                ["sudo", "systemctl", "restart", "zramswap.service"],
            ],
        )

    def test_conflict_when_generator_configured_beside_zram_tools(self):
        r = Racine(self, "debian")
        r.ecrire(ss.ZRAMSWAP_DEFAULT, "PERCENT=50\n")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire(ss.ZRAM_GENERATOR_ETC, "[zram0]\n")
        res = ss.plan_zram(r.etat(), GIO, self.TMP, "s")
        self.assertEqual(res["details"]["tool"], "zram-generator")
        self.assertIn({"code": "zram_tools_conflict"}, res["warnings"])

    def test_nixos(self):
        r = Racine(self, "nixos")
        res = ss.plan_zram(r.etat(), 4 * GIO, self.TMP)
        self.assertEqual(res["plan"], [])
        self.assertIn("zramSwap.memoryPercent = 50;", res["nix"])

    def test_sizes_and_ram(self):
        r = Racine(self)
        e = r.etat()
        self.assertEqual(
            ss.plan_zram(e, 32 * MIO, self.TMP)["reason"], "below_floor"
        )
        self.assertEqual(
            ss.plan_zram(e, 17 * GIO, self.TMP)["reason"], "zram_too_large"
        )
        over = ss.plan_zram(e, 12 * GIO, self.TMP)
        self.assertTrue(over["ok"])
        self.assertEqual(over["warnings"][0]["code"], "zram_over_ram")
        r.memoire(8 * GIO, 1 * GIO)
        r.ecrire(
            "/proc/swaps",
            swaps(("/dev/zram0", "partition", 4194300, 2 * 1024 * 1024, 100)),
        )
        self.assertEqual(
            ss.plan_zram(r.etat(), 2 * GIO, self.TMP)["reason"],
            "ram_cannot_absorb",
        )

    def test_unknown_package_manager(self):
        r = Racine(self)
        r.binaires = set()
        res = ss.plan_zram(r.etat(), GIO, self.TMP)
        self.assertEqual(res["reason"], "no_package_manager")


class TestZramDesactiver(unittest.TestCase):
    TMP = "/tmp-de-test"

    def test_generator_masks_usr_dropins_and_stops_service(self):
        r = Racine(self, "fedora")
        r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        r.ecrire("/usr/lib/systemd/zram-generator.conf", "[zram0]\n")
        r.ecrire("/usr/lib/systemd/zram-generator.conf.d/10-a.conf", "")
        r.ecrire(
            "/etc/systemd/zram-generator.conf.d/20-b.conf",
            "[zram1]\nzram-size = 10\n",
        )
        r.ecrire(
            "/proc/swaps", swaps(("/dev/zram0", "partition", 4194300, 0, 100))
        )
        res = ss.plan_zram_desactiver(r.etat(), self.TMP, "s")
        self.assertTrue(res["ok"], res)
        principal = os.path.join(self.TMP, "zram-generator.conf")
        masque = os.path.join(self.TMP, "dropin-10-a.conf")
        self.assertEqual(ss.lire_ini(res["files"][principal]), {})
        self.assertEqual(res["files"][masque], "")
        # L'arrêt précède la configuration et daemon-reload : après le
        # rechargement, dev-zram0.swap ne dépendrait plus du service.
        self.assertEqual(
            res["plan"],
            [
                [
                    "sudo",
                    "systemctl",
                    "stop",
                    "dev-zram0.swap",
                    "systemd-zram-setup@zram0.service",
                ],
                [
                    "sudo",
                    "systemctl",
                    "stop",
                    "systemd-zram-setup@zram1.service",
                ],
                [
                    "sudo",
                    "install",
                    "-D",
                    "-m",
                    "0644",
                    principal,
                    ss.ZRAM_GENERATOR_ETC,
                ],
                [
                    "sudo",
                    "install",
                    "-D",
                    "-m",
                    "0644",
                    masque,
                    "/etc/systemd/zram-generator.conf.d/10-a.conf",
                ],
                ["sudo", "systemctl", "daemon-reload"],
            ],
        )
        self.assertEqual(
            res["warnings"],
            [
                {
                    "code": "dropin_etc",
                    "paths": ["/etc/systemd/zram-generator.conf.d/20-b.conf"],
                }
            ],
        )

    def test_zram_tools(self):
        r = Racine(self, "debian")
        r.ecrire(ss.ZRAMSWAP_DEFAULT, "SIZE=256\n")
        res = ss.plan_zram_desactiver(r.etat(), self.TMP)
        self.assertEqual(
            res["plan"],
            [["sudo", "systemctl", "disable", "--now", "zramswap.service"]],
        )

    def test_other_service_is_disabled(self):
        r = Racine(self, "opensuse")
        r.ecrire("/usr/sbin/zramswapon", "")
        r.ecrire(
            "/proc/swaps", swaps(("/dev/zram0", "partition", 4194300, 0, 100))
        )
        res = ss.plan_zram_desactiver(r.etat(), self.TMP)
        self.assertEqual(res["details"]["tool"], "service")
        self.assertEqual(
            res["plan"],
            [["sudo", "systemctl", "disable", "--now", "zramswap.service"]],
        )

    def test_manual_and_none(self):
        r = Racine(self)
        self.assertEqual(
            ss.plan_zram_desactiver(r.etat(), self.TMP)["reason"], "no_zram"
        )
        r.ecrire(
            "/proc/swaps", swaps(("/dev/zram0", "partition", 4194300, 0, 100))
        )
        res = ss.plan_zram_desactiver(r.etat(), self.TMP)
        self.assertEqual(res["details"]["tool"], "manual")
        self.assertEqual(
            res["plan"],
            [
                ["sudo", "swapoff", "/dev/zram0"],
                ["sudo", "zramctl", "--reset", "/dev/zram0"],
            ],
        )

    def test_ram_cannot_absorb(self):
        r = Racine(self)
        r.memoire(4 * GIO, 1 * GIO)
        r.ecrire(
            "/proc/swaps",
            swaps(("/dev/zram0", "partition", 4194300, 3 * 1024 * 1024, 100)),
        )
        res = ss.plan_zram_desactiver(r.etat(), self.TMP)
        self.assertEqual(res["reason"], "ram_cannot_absorb")
        self.assertEqual(res["plan"], [])

    def test_nixos(self):
        r = Racine(self, "nixos")
        res = ss.plan_zram_desactiver(r.etat(), self.TMP)
        self.assertIn("zramSwap.enable = false;", res["nix"])


def module(
    handle, taille, locator, forme="DIMM", type_="DDR4", array="0x0010"
):
    return textwrap.dedent(f"""\
        Handle {handle}, DMI type 17, 92 bytes
        Memory Device
        \tArray Handle: {array}
        \tSize: {taille}
        \tForm Factor: {forme}
        \tLocator: {locator}
        \tBank Locator: BANK 0
        \tType: {type_}
        \tSpeed: 3200 MT/s

        """)


def matrice(maximum, n, handle="0x0010", use="System Memory"):
    return textwrap.dedent(f"""\
        Handle {handle}, DMI type 16, 23 bytes
        Physical Memory Array
        \tLocation: System Board Or Motherboard
        \tUse: {use}
        \tMaximum Capacity: {maximum}
        \tNumber Of Devices: {n}

        """)


ENTETE = "# dmidecode 3.6\nGetting SMBIOS data from sysfs.\n\n"


class TestMemoireVive(unittest.TestCase):
    def setUp(self):
        self.r = Racine(self)
        self.r.libre = {"/": 10 * GIO}

    def verdict(self, texte):
        return ss.verdict_memoire(self.r.etat(), ss.analyser_dmidecode(texte))

    def test_parse(self):
        dmi = ss.analyser_dmidecode(
            ENTETE
            + matrice("64 GB", 4)
            + matrice("16 MB", 1, handle="0x0020", use="Flash Memory")
            + module("0x0011", "16 GB", "DIMM A1")
            + module(
                "0x0012",
                "No Module Installed",
                "DIMM A2",
                "Unknown",
                "Unknown",
            )
            + module("0x0021", "16 MB", "FLASH", array="0x0020")
        )
        self.assertEqual(
            dmi["arrays"],
            [
                {
                    "handle": "0x0010",
                    "use": "System Memory",
                    "max_capacity": 64 * GIO,
                    "slots": 4,
                }
            ],
        )
        self.assertEqual(len(dmi["devices"]), 2)
        self.assertEqual(dmi["devices"][0]["size"], 16 * GIO)
        self.assertEqual(dmi["devices"][0]["locator"], "DIMM A1")
        self.assertTrue(dmi["devices"][1]["empty"])

    def test_sizes(self):
        self.assertEqual(ss.taille_dmi("8192 MB"), 8 * GIO)
        self.assertEqual(ss.taille_dmi("2 TB"), 2 * ss.TIO)
        self.assertIsNone(ss.taille_dmi("No Module Installed"))
        self.assertIsNone(ss.taille_dmi("Unknown"))
        self.assertIsNone(ss.taille_dmi("0 MB"))

    def test_free_slots(self):
        v = self.verdict(
            matrice("64 GB", 2)
            + module("0x0011", "16 GB", "DIMM A1")
            + module("0x0012", "No Module Installed", "DIMM A2", "Unknown")
        )
        self.assertEqual(v["verdict"], "free_slots")
        self.assertEqual(v["installed"], 16 * GIO)
        self.assertEqual(v["max_addable"], 48 * GIO)
        self.assertEqual(
            (v["slots"], v["used_slots"], v["free_slots"]), (2, 1, 1)
        )
        self.assertEqual(v["types"], ["DDR4"])
        self.assertTrue(v["firmware_note"])
        self.assertEqual(v["swap_growth"], 9 * GIO)

    def test_replace_modules(self):
        v = self.verdict(
            matrice("64 GB", 2)
            + module("0x0011", "8 GB", "DIMM A1")
            + module("0x0012", "8 GB", "DIMM A2")
        )
        self.assertEqual(v["verdict"], "replace")
        self.assertEqual(v["max_addable"], 48 * GIO)

    def test_at_maximum(self):
        v = self.verdict(
            matrice("32 GB", 2)
            + module("0x0011", "16 GB", "DIMM A1")
            + module("0x0012", "16 GB", "DIMM A2")
        )
        self.assertEqual(v["verdict"], "max")
        self.assertEqual(v["max_addable"], 0)

    def test_soldered(self):
        v = self.verdict(
            matrice("16 GB", 1)
            + module("0x0011", "16 GB", "Onboard", forme="Row Of Chips")
        )
        self.assertEqual(v["verdict"], "soldered")

    def test_partially_soldered_replaces_the_socketed_module(self):
        v = self.verdict(
            matrice("40 GB", 2)
            + module("0x0011", "8 GB", "Onboard", forme="Row Of Chips")
            + module("0x0012", "8 GB", "DIMM B")
        )
        self.assertEqual(v["verdict"], "replace")
        self.assertTrue(v["partially_soldered"])

    def test_understated_maximum(self):
        v = self.verdict(
            matrice("8 GB", 2)
            + module("0x0011", "16 GB", "DIMM A1")
            + module("0x0012", "No Module Installed", "DIMM A2", "Unknown")
        )
        self.assertTrue(v["max_understated"])
        self.assertIsNone(v["max_capacity"])
        self.assertEqual(v["verdict"], "free_slots")
        self.assertIsNone(v["max_addable"])

    def test_vm_and_unknown(self):
        self.r.sorties["systemd-detect-virt"] = "qemu\n"
        v = ss.verdict_memoire(self.r.etat())
        self.assertEqual(v["verdict"], "vm")
        self.assertEqual(v["virtualization"], "qemu")
        self.r.sorties["systemd-detect-virt"] = "none\n"
        self.assertEqual(
            ss.verdict_memoire(self.r.etat(), None)["verdict"], "unknown"
        )
        self.assertEqual(self.verdict("")["verdict"], "unknown")

    def test_swap_growth_uses_swapfile_filesystem(self):
        self.r.libre = {"/": 10 * GIO, "/data": 3 * GIO}
        self.r.ecrire(
            "/proc/swaps", swaps(("/data/swapfile", "file", 2097148, 0, -2))
        )
        self.assertEqual(ss.croissance_swap(self.r.etat()), 2 * GIO)
        self.r.libre = {}
        self.assertIsNone(ss.croissance_swap(self.r.etat()))

    def test_dmidecode_commands(self):
        self.assertEqual(
            ss.commande_dmidecode("apt"), ["sudo", "dmidecode", "-t", "memory"]
        )
        self.assertEqual(
            ss.commande_dmidecode("nix")[:3], ["nix-shell", "-p", "dmidecode"]
        )
        e = self.r.etat()
        self.assertEqual(
            ss.plan_installer_dmidecode(e),
            [["sudo", "pacman", "-S", "--needed", "--noconfirm", "dmidecode"]],
        )
        self.r.binaires.add("dmidecode")
        self.assertEqual(ss.plan_installer_dmidecode(e), [])
        self.r.binaires = set()
        self.assertIsNone(ss.plan_installer_dmidecode(self.r.etat()))

    def test_vm_balloon_driver(self):
        """Le pilote virtio_balloon de l'invité se lit sous /sys/bus/virtio
        ou /sys/module ; hors VM, la question ne se pose pas."""
        self.r.sorties["systemd-detect-virt"] = "kvm\n"
        self.assertIs(ss.verdict_memoire(self.r.etat())["balloon"], False)
        os.makedirs(self.r.sous("/sys/module/virtio_balloon"))
        self.assertIs(ss.verdict_memoire(self.r.etat())["balloon"], True)
        shutil.rmtree(self.r.sous("/sys/module/virtio_balloon"))
        os.makedirs(self.r.sous("/sys/bus/virtio/drivers/virtio_balloon"))
        self.assertIs(ss.verdict_memoire(self.r.etat())["balloon"], True)
        self.r.sorties["systemd-detect-virt"] = "none\n"
        self.assertIsNone(ss.verdict_memoire(self.r.etat())["balloon"])

    def test_balloon_is_unknown_outside_a_virtio_hypervisor(self):
        """Un conteneur n'a pas de RAM de VM, VMware et Hyper-V ont leur
        propre pilote de ballon : balloon reste None, même si le module
        virtio_balloon est intégré au noyau de l'invité."""
        os.makedirs(self.r.sous("/sys/module/virtio_balloon"))
        for virt, verdict in (
            ("docker", "container"),
            ("lxc", "container"),
            ("vmware", "vm"),
            ("microsoft", "vm"),
        ):
            with self.subTest(virt=virt):
                self.r.sorties["systemd-detect-virt"] = f"{virt}\n"
                v = ss.verdict_memoire(self.r.etat())
                self.assertEqual(v["verdict"], verdict)
                self.assertIsNone(v["balloon"])

    def test_dmidecode_in_sbin_outside_the_path_is_installed(self):
        """Chez Debian, /usr/sbin n'est pas dans le PATH d'un compte
        ordinaire : which() ne le voit pas, le fichier si."""
        self.r.ecrire("/usr/sbin/dmidecode", "")
        self.assertEqual(ss.plan_installer_dmidecode(self.r.etat()), [])


SYSTEMD_SYSCTL = "/usr/lib/systemd/systemd-sysctl"


class TestLectureSysctl(unittest.TestCase):
    def setUp(self):
        self.r = Racine(self)
        self.r.ecrire("/proc/sys/vm/swappiness", "60\n")
        self.r.ecrire("/proc/sys/vm/page-cluster", "3\n")

    def sysctl(self):
        return ss.lire_sysctl(self.r.chemin)

    def test_key_forms(self):
        self.assertEqual(ss.chemin_sysctl("vm.swappiness"), "vm/swappiness")
        self.assertEqual(ss.chemin_sysctl("vm/swappiness"), "vm/swappiness")
        # Après une première barre, le point fait partie du nom.
        self.assertEqual(
            ss.chemin_sysctl("net/ipv4/conf/eth9.7/forwarding"),
            "net/ipv4/conf/eth9.7/forwarding",
        )
        self.assertEqual(
            ss.chemin_sysctl("net.ipv4.conf.eth9/7.forwarding"),
            "net/ipv4/conf/eth9.7/forwarding",
        )
        self.assertEqual(
            ss.lire_sysctl_conf(
                "# vm.swappiness = 1\n"
                "; vm.swappiness = 2\n"
                "vm.swappiness=3\n"
                "  -vm/swappiness =  4  \n"
                "-vm.page-cluster\n"
                "vm.page-cluster = 0\n"
            ),
            {"vm/swappiness": "4", "vm/page-cluster": "0"},
        )

    def test_kernel_default_when_nothing_sets_it(self):
        self.r.ecrire("/etc/sysctl.d/10-net.conf", "net.ipv4.ip_forward=1\n")
        s = self.sysctl()
        info = s[ss.SWAPPINESS]
        self.assertEqual(info["value"], 60)
        self.assertEqual(info["setters"], [])
        self.assertIsNone(info["source"])
        self.assertEqual(info["dead"], [])
        self.assertEqual(s[ss.PAGE_CLUSTER]["value"], 3)
        self.assertEqual(s["names"], ["10-net.conf"])

    def test_precedence_masking_and_lexicographic_order(self):
        """Un fichier de /etc masque celui du même nom plus bas ; les
        survivants s'appliquent par ordre de nom, d'où qu'ils viennent ;
        la forme en chemin compte comme la forme pointée."""
        r = self.r
        r.ecrire("/usr/lib/sysctl.d/10-vendor.conf", "vm.swappiness = 30\n")
        r.ecrire("/usr/lib/sysctl.d/50-masked.conf", "vm.swappiness = 5\n")
        r.ecrire("/etc/sysctl.d/50-masked.conf", "# vide : masque\n")
        r.ecrire("/run/sysctl.d/70-run.conf", "vm/swappiness=40\n")
        r.ecrire("/run/sysctl.d/80-other.conf", "vm.swappiness = 80\n")
        r.ecrire("/usr/lib/sysctl.d/80-other.conf", "vm.swappiness = 81\n")
        r.ecrire("/lib/sysctl.d/90-lib.conf", "vm.page-cluster = 2\n")
        r.ecrire("/etc/sysctl.d/README", "vm.swappiness = 99\n")
        r.ecrire("/proc/sys/vm/swappiness", "80\n")
        s = self.sysctl()
        info = s[ss.SWAPPINESS]
        self.assertEqual(
            [(x["path"], x["value"]) for x in info["setters"]],
            [
                ("/usr/lib/sysctl.d/10-vendor.conf", "30"),
                ("/run/sysctl.d/70-run.conf", "40"),
                ("/run/sysctl.d/80-other.conf", "80"),
            ],
        )
        self.assertEqual(info["source"], "/run/sysctl.d/80-other.conf")
        self.assertEqual(info["source_value"], "80")
        self.assertEqual(
            [x["path"] for x in info["dead"]],
            [
                "/usr/lib/sysctl.d/10-vendor.conf",
                "/run/sysctl.d/70-run.conf",
            ],
        )
        self.assertEqual(info["value"], 80)
        self.assertEqual(
            s[ss.PAGE_CLUSTER]["source"], "/lib/sysctl.d/90-lib.conf"
        )
        self.assertEqual(
            s["names"],
            [
                "10-vendor.conf",
                "50-masked.conf",
                "70-run.conf",
                "80-other.conf",
                "90-lib.conf",
            ],
        )

    def test_symlinked_sysctl_conf_counts_once(self):
        """/etc/sysctl.d/99-sysctl.conf -> ../sysctl.conf : un seul setter,
        classé à son nom de lien, et rien « hors démarrage »."""
        r = self.r
        r.ecrire(SYSTEMD_SYSCTL, "")
        r.ecrire("/etc/sysctl.conf", "vm.swappiness = 10\n")
        r.lien("/etc/sysctl.d/99-sysctl.conf", "../sysctl.conf")
        r.ecrire("/usr/lib/sysctl.d/50-vendor.conf", "vm.swappiness = 30\n")
        info = self.sysctl()[ss.SWAPPINESS]
        self.assertEqual(len(info["setters"]), 2)
        gagnant = info["setters"][-1]
        self.assertEqual(
            gagnant,
            {
                "path": "/etc/sysctl.conf",
                "link": "/etc/sysctl.d/99-sysctl.conf",
                "name": "99-sysctl.conf",
                "value": "10",
            },
        )
        self.assertIsNone(info["outside_boot"])

    def test_absolute_link_resolves_under_the_root(self):
        r = self.r
        r.ecrire("/etc/sysctl.conf", "vm.swappiness = 12\n")
        r.lien("/etc/sysctl.d/99-sysctl.conf", "/etc/sysctl.conf")
        info = self.sysctl()[ss.SWAPPINESS]
        self.assertEqual([x["value"] for x in info["setters"]], ["12"])
        self.assertEqual(info["source"], "/etc/sysctl.conf")

    def test_unlinked_sysctl_conf_with_and_without_systemd(self):
        """Sans lien, systemd-sysctl ne lit pas /etc/sysctl.conf : il est
        « hors démarrage ». Sans systemd-sysctl, procps l'applique en
        dernier : il l'emporte, même sur un nom qui se classe après."""
        r = self.r
        r.ecrire("/etc/sysctl.conf", "vm.swappiness = 15\n")
        r.ecrire("/etc/sysctl.d/99-zzz.conf", "vm.swappiness = 25\n")
        info = self.sysctl()[ss.SWAPPINESS]
        self.assertEqual(info["source"], "/etc/sysctl.conf")
        self.assertIsNone(info["setters"][-1]["name"])
        self.assertIsNone(info["outside_boot"])
        r.ecrire(SYSTEMD_SYSCTL, "")
        s = self.sysctl()
        info = s[ss.SWAPPINESS]
        self.assertTrue(s["systemd"])
        self.assertEqual(info["source"], "/etc/sysctl.d/99-zzz.conf")
        self.assertEqual(
            info["outside_boot"], {"path": "/etc/sysctl.conf", "value": "15"}
        )

    def test_state_carries_sysctl_kernel_postgresql_and_balloon(self):
        r = self.r
        r.ecrire("/proc/sys/kernel/osrelease", "6.1.0-test\n")
        r.ecrire("/proc/4242/comm", "bash\n")
        e = r.etat()
        self.assertEqual(e["kernel"], "6.1.0-test")
        self.assertFalse(e["postgresql"])
        self.assertFalse(e["balloon"])
        self.assertEqual(e["sysctl"][ss.SWAPPINESS]["value"], 60)
        r.ecrire("/proc/4343/comm", "postgres\n")
        os.makedirs(r.sous("/sys/module/virtio_balloon"))
        e = r.etat()
        self.assertTrue(e["postgresql"])
        self.assertTrue(e["balloon"])


class TestRecommandationSwappiness(unittest.TestCase):
    def setUp(self):
        self.r = Racine(self)

    def test_zram_active_or_configured(self):
        self.r.ecrire(
            "/proc/swaps", swaps(("/dev/zram0", "partition", 2097148, 0, 100))
        )
        attendu = {"swappiness": 100, "page_cluster": 0, "reason": "zram"}
        self.assertEqual(ss.recommandation_swappiness(self.r.etat()), attendu)
        self.r.ecrire("/proc/swaps", swaps())
        self.r.ecrire(ss.BINAIRES_ZRAM_GENERATOR[0], "")
        self.r.ecrire(ss.ZRAM_GENERATOR_ETC, "[zram0]\n")
        self.assertEqual(ss.recommandation_swappiness(self.r.etat()), attendu)

    def test_no_swap(self):
        rec = ss.recommandation_swappiness(self.r.etat())
        self.assertEqual(rec["reason"], "no_swap")
        self.assertIsNone(rec["page_cluster"])

    def test_swap_in_fstab_but_off_is_not_no_swap(self):
        """Un swap inscrit dans fstab mais éteint revient au prochain
        démarrage : la swappiness le concernera, la raison n'est donc pas
        « no_swap ». Une ligne commentée ne compte pas."""
        self.r.ecrire(
            "/etc/fstab",
            "/dev/vda1 / ext4 defaults 0 1\n#/dev/vda3 none swap sw 0 0\n",
        )
        rec = ss.recommandation_swappiness(self.r.etat())
        self.assertEqual(rec["reason"], "no_swap")
        self.r.ecrire(
            "/etc/fstab",
            "/dev/vda1 / ext4 defaults 0 1\n/swap\\040file none swap sw 0 0\n",
        )
        self.assertEqual(
            ss.swaps_fstab(self.r.etat()["fstab"]), ["/swap file"]
        )
        rec = ss.recommandation_swappiness(self.r.etat())
        self.assertEqual(rec["reason"], "default")

    def test_disk_swap_with_and_without_postgresql(self):
        self.r.ecrire(
            "/proc/swaps", swaps(("/swapfile", "file", 2097148, 0, -2))
        )
        self.assertEqual(
            ss.recommandation_swappiness(self.r.etat()),
            {"swappiness": 60, "page_cluster": None, "reason": "default"},
        )
        self.r.ecrire("/proc/777/comm", "postgres\n")
        self.assertEqual(
            ss.recommandation_swappiness(self.r.etat()),
            {"swappiness": 10, "page_cluster": None, "reason": "postgresql"},
        )


class TestPlanSwappiness(unittest.TestCase):
    def setUp(self):
        self.r = Racine(self)
        self.r.ecrire("/proc/sys/kernel/osrelease", "6.1.0-test\n")
        self.r.ecrire("/proc/sys/vm/swappiness", "60\n")
        self.r.ecrire("/proc/sys/vm/page-cluster", "3\n")

    def plan(self, valeur=100, page_cluster=None):
        return ss.plan_swappiness(self.r.etat(), valeur, page_cluster, "s")

    def test_etc_winner_is_edited_in_place_after_a_backup(self):
        texte = (
            "# réglage local\n"
            "vm.swappiness = 10\n"
            "-vm/swappiness=20\n"
            "vm.swappiness_other = 3\n"
        )
        self.r.ecrire("/etc/sysctl.d/60-local.conf", texte)
        self.r.ecrire("/usr/lib/sysctl.d/10-vendor.conf", "vm.swappiness=30\n")
        res = self.plan()
        self.assertTrue(res["ok"], res)
        chemin = "/etc/sysctl.d/60-local.conf"
        self.assertEqual(
            res["plan"][:2],
            [
                ["sudo", "sysctl", "-w", "vm.swappiness=100"],
                ["sudo", "cp", "-a", chemin, f"{chemin}.bak-s"],
            ],
        )
        sed = res["plan"][2]
        self.assertEqual(sed[:4], ["sudo", "sed", "-i", "-E"])
        self.assertEqual(sed[-1], chemin)
        self.assertEqual(len(res["plan"]), 3)
        self.assertIsNone(res["details"]["created"])
        self.assertEqual(
            res["details"]["edited"],
            [{"path": chemin, "backup": f"{chemin}.bak-s"}],
        )
        self.assertEqual(res["details"]["changes"], {ss.SWAPPINESS: [60, 100]})
        self.assertEqual(
            res["warnings"],
            [
                {
                    "code": "sysctl_dead",
                    "key": ss.SWAPPINESS,
                    "paths": ["/usr/lib/sysctl.d/10-vendor.conf (30)"],
                }
            ],
        )
        # L'expression, jouée par le vrai sed sur une copie.
        copie = os.path.join(self.r.chemin, "copie.conf")
        with open(copie, "w") as fh:
            fh.write(texte)
        REEL_RUN(["sed", "-i", "-E", *sed[4:-1], copie], check=True)
        with open(copie) as fh:
            self.assertEqual(
                fh.read(),
                "# réglage local\n"
                "vm.swappiness = 100\n"
                "-vm/swappiness=100\n"
                "vm.swappiness_other = 3\n",
            )

    def test_vendor_winner_gets_a_new_file_that_sorts_after_it(self):
        """Un fichier de /usr/lib ou de /run ne se modifie pas : un nouveau
        fichier de /etc/sysctl.d, classé après lui, l'écrase."""
        self.r.ecrire(
            "/usr/lib/sysctl.d/99-zzz-vendor.conf", "vm.swappiness = 30\n"
        )
        self.r.ecrire("/run/sysctl.d/50-run.conf", "vm.swappiness = 35\n")
        res = self.plan(100, 0)
        self.assertTrue(res["ok"], res)
        nouveau = "/etc/sysctl.d/99-zzz-vendor_zz-swap.conf"
        self.assertGreater(os.path.basename(nouveau), "99-zzz-vendor.conf")
        self.assertEqual(res["details"]["created"], nouveau)
        self.assertEqual(
            res["details"]["content"],
            "vm.swappiness = 100\nvm.page-cluster = 0\n",
        )
        self.assertEqual(
            res["plan"][0],
            ["sudo", "sysctl", "-w", "vm.swappiness=100", "vm.page-cluster=0"],
        )
        self.assertEqual(len(res["plan"]), 2)
        ecriture = res["plan"][1]
        self.assertEqual(ecriture[:3], ["sudo", "sh", "-c"])
        self.assertIn(f"| tee {nouveau} > /dev/null", ecriture[3])
        for cmd in res["plan"]:
            self.assertFalse(
                any(a.startswith(("/usr/lib", "/run")) for a in cmd), cmd
            )
        self.assertEqual(res["details"]["edited"], [])
        self.assertEqual(
            res["warnings"][0]["paths"],
            [
                "/run/sysctl.d/50-run.conf (35)",
                "/usr/lib/sysctl.d/99-zzz-vendor.conf (30)",
            ],
        )

    def test_the_new_file_runs_through_a_real_shell(self):
        """Le contenu, passé à printf par sh -c, arrive tel quel dans le
        fichier : la commande est jouée sur une copie, sudo ôté."""
        res = self.plan(100, 0)
        script = res["plan"][1][3].replace(
            ss.SYSCTL_D_ETC, os.path.join(self.r.chemin, "etc-sysctl.d")
        )
        REEL_RUN(["sh", "-c", script], check=True)
        cible = os.path.join(self.r.chemin, "etc-sysctl.d", ss.NOM_SYSCTL)
        with open(cible) as fh:
            self.assertEqual(
                fh.read(), "vm.swappiness = 100\nvm.page-cluster = 0\n"
            )

    def test_file_names(self):
        self.assertEqual(ss.nom_fichier_sysctl([]), "99-zz-swap.conf")
        self.assertEqual(
            ss.nom_fichier_sysctl(["10-a.conf", "99-sysctl.conf"]),
            "99-zz-swap.conf",
        )
        # Un fichier de ce nom existe ailleurs : le créer dans /etc le
        # masquerait.
        nom = ss.nom_fichier_sysctl([], ["99-zz-swap.conf"])
        self.assertEqual(nom, "99-zz-swap_zz-swap.conf")
        self.assertGreater(nom, "99-zz-swap.conf")
        nom = ss.nom_fichier_sysctl(["zz-last.conf"], ["zz-last.conf"])
        self.assertGreater(nom, "zz-last.conf")
        self.assertTrue(nom.endswith(".conf"))

    def test_no_setter_writes_the_default_file(self):
        res = self.plan(30)
        self.assertEqual(
            res["details"]["created"], f"/etc/sysctl.d/{ss.NOM_SYSCTL}"
        )
        self.assertEqual(res["warnings"], [])

    def test_linked_sysctl_conf_is_edited_through_its_real_path(self):
        self.r.ecrire(SYSTEMD_SYSCTL, "")
        self.r.ecrire("/etc/sysctl.conf", "vm.swappiness=10\n")
        self.r.lien("/etc/sysctl.d/99-sysctl.conf", "../sysctl.conf")
        res = self.plan()
        self.assertEqual(
            [e["path"] for e in res["details"]["edited"]],
            ["/etc/sysctl.conf"],
        )
        self.assertIsNone(res["details"]["created"])
        self.assertEqual(res["plan"][2][-1], "/etc/sysctl.conf")

    def test_unlinked_sysctl_conf_is_edited_too(self):
        """systemd ne le lit pas au démarrage, mais « sysctl --system »
        l'applique en dernier : il reçoit la même valeur que le nouveau
        fichier."""
        self.r.ecrire(SYSTEMD_SYSCTL, "")
        self.r.ecrire("/etc/sysctl.conf", "vm.swappiness = 15\n")
        self.r.ecrire("/usr/lib/sysctl.d/50-vendor.conf", "vm.swappiness=30\n")
        res = self.plan()
        self.assertEqual(
            [e["path"] for e in res["details"]["edited"]],
            ["/etc/sysctl.conf"],
        )
        self.assertEqual(
            res["details"]["created"], f"/etc/sysctl.d/{ss.NOM_SYSCTL}"
        )

    def test_page_cluster_goes_to_its_own_winner(self):
        self.r.ecrire("/etc/sysctl.d/60-local.conf", "vm.swappiness = 10\n")
        self.r.ecrire("/usr/lib/sysctl.d/10-io.conf", "vm.page-cluster = 4\n")
        res = self.plan(100, 0)
        self.assertEqual(
            [e["path"] for e in res["details"]["edited"]],
            ["/etc/sysctl.d/60-local.conf"],
        )
        self.assertEqual(res["details"]["content"], "vm.page-cluster = 0\n")
        self.assertEqual(
            res["details"]["changes"],
            {ss.SWAPPINESS: [60, 100], ss.PAGE_CLUSTER: [3, 0]},
        )

    def test_range_follows_the_kernel(self):
        self.assertTrue(self.plan(200)["ok"])
        for valeur in (201, -1, "100", True, None, 1.5):
            res = self.plan(valeur)
            self.assertEqual(res["reason"], "swappiness_range", valeur)
        self.assertEqual(self.plan(201)["details"]["limit"], 200)
        self.r.ecrire("/proc/sys/kernel/osrelease", "5.4.0-test\n")
        res = self.plan(150)
        self.assertEqual(res["reason"], "swappiness_range")
        self.assertEqual(res["details"]["limit"], 100)
        self.assertEqual(res["details"]["running"], "5.4.0-test")
        self.assertTrue(self.plan(100)["ok"])
        self.assertEqual(self.plan(100, 32)["reason"], "page_cluster_range")

    def test_the_kernel_is_read_when_the_state_lacks_it(self):
        e = self.r.etat()
        del e["kernel"]
        self.assertTrue(ss.plan_swappiness(e, 150)["ok"])
        self.assertEqual(e["kernel"], "6.1.0-test")
        self.assertEqual(ss.swappiness_max(None), 100)
        self.assertEqual(ss.swappiness_max("5.8.0"), 200)
        self.assertEqual(ss.swappiness_max("5.7.19"), 100)

    def test_container_is_refused(self):
        self.r.sorties["systemd-detect-virt"] = "docker\n"
        self.assertEqual(self.plan()["reason"], "container")

    def test_nixos_gets_a_snippet(self):
        r = Racine(self, "nixos")
        r.ecrire("/proc/sys/kernel/osrelease", "6.1.0-test\n")
        res = ss.plan_swappiness(r.etat(), 100, 0)
        self.assertEqual(res["plan"], [])
        self.assertEqual(res["reason"], "nixos")
        self.assertIn('boot.kernel.sysctl."vm.swappiness" = 100;', res["nix"])
        self.assertIn('boot.kernel.sysctl."vm.page-cluster" = 0;', res["nix"])
        self.assertIn("nixos-rebuild switch", res["nix"])

    def test_zram_plan_warns_about_a_low_swappiness(self):
        self.r.ecrire("/proc/sys/vm/swappiness", "10\n")
        res = ss.plan_zram(self.r.etat(), 2 * GIO, "/tmp-de-test", "s")
        self.assertIn({"code": "low_swappiness", "value": 10}, res["warnings"])
        self.r.ecrire("/proc/sys/vm/swappiness", "60\n")
        res = ss.plan_zram(self.r.etat(), 2 * GIO, "/tmp-de-test", "s")
        self.assertNotIn(
            "low_swappiness", [a["code"] for a in res["warnings"]]
        )


if __name__ == "__main__":
    unittest.main()
