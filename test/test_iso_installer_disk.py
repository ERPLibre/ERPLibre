#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Étape disque de l'installateur ERPLibre (erplibre_disk) : disposition,
plan de commandes, relecture avant effacement, exécution, démontage.

Les réglages sortent de machine_profile.resolve() sur des faits
INVENTÉS ; aucune commande n'est lancée, `run` est simulé partout.
"""

import json
import subprocess
import unittest

from test import iso_installer_modules as m

mp, facts, dk, _ai, _pl, _ei = m.load()

MIB = 1024**2


def resolved(profile, fx, answers=None):
    settings, questions = mp.resolve(profile, fx, answers or {})
    assert not questions, questions
    return settings


def argvs(result):
    return [step["argv"] for step in result["plan"]]


def first(result, *prefix):
    for argv in argvs(result):
        if argv[: len(prefix)] == list(prefix):
            return argv
    return None


class FakeRun:
    """Rend un code par commande (0 par défaut) et garde chaque appel."""

    def __init__(self, codes=None, stdout=b""):
        self.calls = []
        self.codes = codes or {}
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        code = self.codes.get(argv[0], 0)
        return subprocess.CompletedProcess(argv, code, self.stdout, None)


class TestPartitionPath(unittest.TestCase):
    def test_digit_ending_disks_take_p(self):
        self.assertEqual(
            dk.partition_path("/dev/nvme0n1", 2), "/dev/nvme0n1p2"
        )
        self.assertEqual(
            dk.partition_path("/dev/mmcblk0", 1), "/dev/mmcblk0p1"
        )
        self.assertEqual(dk.partition_path("/dev/sda", 3), "/dev/sda3")
        self.assertEqual(dk.partition_path("/dev/vda", 1), "/dev/vda1")


class TestLayout(unittest.TestCase):
    def test_uefi_luks_esp_then_8309_root(self):
        lay = dk.layout(resolved(m.luks_profile(), m.uefi_laptop()))
        roles = [(p["role"], p["code"]) for p in lay["partitions"]]
        self.assertEqual(roles, [("esp", "ef00"), ("root", "8309")])
        self.assertEqual(lay["partitions"][0]["mib"], 2048)
        self.assertEqual(lay["boot_fs"], "vfat")
        self.assertEqual(lay["root_dev"], "/dev/vgtest/root")
        self.assertEqual(lay["swap_dev"], "/dev/vgtest/swap")
        self.assertEqual(lay["secret_dev"], "/dev/vgtest/secret")
        self.assertEqual(lay["root_part"], "/dev/nvme0n1p2")

    def test_root_end_is_rounded_down_one_mib_before_the_end(self):
        fx = m.uefi_laptop()
        # Une taille qui ne tombe pas sur un MiB : la fin de la racine est
        # arrondie au MiB inférieur, puis un MiB est laissé à la GPT.
        fx["disks"][0]["size"] = 500 * m.GIB + 12345
        lay = dk.layout(resolved(m.luks_profile(), fx))
        total = sum(p["mib"] for p in lay["partitions"])
        self.assertEqual(lay["size_mib"], 500 * 1024)
        self.assertEqual(total + dk.HEAD_MIB + dk.TAIL_MIB, lay["size_mib"])

    def test_bios_has_bios_grub_and_plain_boot(self):
        lay = dk.layout(resolved(m.luks_profile(), m.bios_desktop()))
        roles = [(p["role"], p["code"], p["mib"]) for p in lay["partitions"]]
        self.assertEqual(
            roles[:2], [("bios_grub", "ef02", 1), ("boot", "8300", 2048)]
        )
        self.assertEqual(roles[2][:2], ("root", "8309"))
        self.assertEqual(lay["boot_fs"], "ext4")
        self.assertEqual(lay["boot_dev"], "/dev/sda2")
        self.assertTrue(lay["bios"])

    def test_plain_root_is_the_partition_without_swap(self):
        lay = dk.layout(resolved(m.plain_profile(), m.uefi_laptop()))
        self.assertFalse(lay["luks"])
        self.assertEqual(lay["partitions"][-1]["code"], "8300")
        self.assertEqual(lay["root_dev"], "/dev/nvme0n1p2")
        self.assertIsNone(lay["swap_dev"])
        self.assertIsNone(lay["vg"])
        self.assertEqual(lay["vg_free_mib"], 0)

    def test_root_estimate_subtracts_volumes(self):
        settings = resolved(m.luks_profile(), m.uefi_laptop())
        lay = dk.layout(settings)
        swap = settings["derived"]["swap_gib"]
        attendu = (
            lay["partitions"][-1]["mib"]
            - dk.LUKS_OVERHEAD_MIB
            - dk.LVM_OVERHEAD_MIB
            - swap * 1024
            - 4 * 1024
            - 512
        )
        self.assertEqual(lay["root_mib"], attendu)


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.settings = resolved(m.luks_profile(), m.uefi_laptop())
        self.result = dk.plan(self.settings)

    def test_plan_ok_and_never_carries_a_secret(self):
        self.assertTrue(self.result["ok"], self.result)
        texte = json.dumps(self.result["plan"])
        for interdit in ("passphrase", "password"):
            self.assertNotIn(interdit, texte)
        lecteurs = [s["stdin"] for s in self.result["plan"] if s["stdin"]]
        self.assertEqual(
            sorted(set(lecteurs)), sorted([dk.SECRET_LUKS, dk.SECRET_LV])
        )

    def test_zap_then_partitions_with_relative_sizes(self):
        a = argvs(self.result)
        self.assertEqual(a[0], ["wipefs", "--all", "/dev/nvme0n1"])
        self.assertEqual(a[1], ["sgdisk", "--zap-all", "/dev/nvme0n1"])
        sg = a[2]
        self.assertEqual(sg[0], "sgdisk")
        self.assertIn("1:0:+2048M", sg)
        self.assertIn("1:ef00", sg)
        self.assertIn("2:8309", sg)
        self.assertEqual(sg[-1], "/dev/nvme0n1")

    def test_luks_format_options_and_stdin_key(self):
        fmt = first(self.result, "cryptsetup", "luksFormat")
        self.assertEqual(
            fmt,
            [
                "cryptsetup",
                "luksFormat",
                "--type",
                "luks2",
                "--sector-size",
                "512",
                "--iter-time",
                "2500",
                "--batch-mode",
                "--key-file=-",
                "/dev/nvme0n1p2",
            ],
        )
        ouvrir = first(self.result, "cryptsetup", "open")
        self.assertIn("--allow-discards", ouvrir)
        self.assertIn("--persistent", ouvrir)
        self.assertEqual(ouvrir[-2:], ["/dev/nvme0n1p2", dk.LUKS_MAPPER])

    def test_no_discards_on_a_rotational_disk(self):
        res = dk.plan(resolved(m.luks_profile(), m.bios_desktop()))
        ouvrir = first(res, "cryptsetup", "open")
        self.assertNotIn("--allow-discards", ouvrir)

    def test_lvm_volumes_then_free_space(self):
        a = argvs(self.result)
        swap = self.settings["derived"]["swap_gib"]
        self.assertIn(
            ["lvcreate", "--yes", "-L", f"{swap}G", "-n", "swap", "vgtest"], a
        )
        self.assertIn(
            ["lvcreate", "--yes", "-L", "4G", "-n", "secret", "vgtest"], a
        )
        racine = a.index(
            ["lvcreate", "--yes", "-l", "100%FREE", "-n", "root", "vgtest"]
        )
        self.assertEqual(
            a[racine + 1], ["lvreduce", "--yes", "-L", "-512M", "vgtest/root"]
        )

    def test_no_lvreduce_without_free_space(self):
        profil = m.luks_profile()
        profil["disk"]["lvm"]["vg_free_mib"] = 0
        res = dk.plan(resolved(profil, m.uefi_laptop()))
        self.assertIsNone(first(res, "lvreduce"))

    def test_secret_volume_is_formatted_then_closed(self):
        a = argvs(self.result)
        i = a.index(
            [
                "cryptsetup",
                "luksFormat",
                "--type",
                "luks2",
                "--sector-size",
                "512",
                "--iter-time",
                "2500",
                "--batch-mode",
                "--key-file=-",
                "/dev/vgtest/secret",
            ]
        )
        self.assertEqual(a[i + 1][:3], ["cryptsetup", "open", "--key-file=-"])
        self.assertEqual(a[i + 2][0], "mkfs.ext4")
        self.assertEqual(a[i + 3], ["cryptsetup", "close", dk.SECRET_MAPPER])
        self.assertEqual(self.result["plan"][i]["stdin"], dk.SECRET_LV)

    def test_mounts_last_with_esp_masks_and_swapon(self):
        a = argvs(self.result)
        self.assertEqual(a[-4], ["udevadm", "settle"])
        self.assertEqual(
            a[-3],
            ["mount", "--mkdir", "-t", "ext4", "/dev/vgtest/root", dk.TARGET],
        )
        self.assertEqual(
            a[-2],
            [
                "mount",
                "--mkdir",
                "-t",
                "vfat",
                "-o",
                "fmask=0077,dmask=0077",
                "/dev/nvme0n1p1",
                dk.TARGET + "/boot",
            ],
        )
        self.assertEqual(a[-1], ["swapon", "/dev/vgtest/swap"])
        self.assertIn(
            ["mkfs.fat", "-F", "32", "-n", "ESP", "/dev/nvme0n1p1"], a
        )

    def test_nvme_format_needs_explicit_confirmation(self):
        self.assertIsNone(first(self.result, "nvme"))
        self.assertEqual(
            self.result["warnings"],
            [{"code": "nvme-format-skipped", "lbaf": 1}],
        )
        res = dk.plan(self.settings, {"nvme_format": True})
        self.assertEqual(
            argvs(res)[0],
            ["nvme", "format", "/dev/nvme0n1", "--lbaf=1", "--force"],
        )
        # Reformaté en 4 KiB, l'espace de noms exige des secteurs LUKS de
        # 4096 même si les réglages avaient retenu 512.
        fmt = first(res, "cryptsetup", "luksFormat")
        self.assertEqual(fmt[fmt.index("--sector-size") + 1], "4096")
        self.assertEqual(res["warnings"], [])

    def test_confirmation_without_proposal_formats_nothing(self):
        profil = m.luks_profile()
        profil["disk"]["nvme_lba_4k"] = False
        res = dk.plan(resolved(profil, m.uefi_laptop()), {"nvme_format": True})
        self.assertIsNone(first(res, "nvme"))

    def test_plain_plan_has_no_luks_nor_lvm(self):
        res = dk.plan(resolved(m.plain_profile(), m.uefi_laptop()))
        self.assertTrue(res["ok"])
        outils = {a[0] for a in argvs(res)}
        self.assertFalse(
            outils & {"cryptsetup", "pvcreate", "lvcreate", "swapon"}
        )
        self.assertIn(
            ["mkfs.ext4", "-F", "-L", "root", "/dev/nvme0n1p2"], argvs(res)
        )
        self.assertEqual(dk.required_secrets(res["layout"]), [])

    def test_bios_boot_is_ext4_without_masks(self):
        res = dk.plan(resolved(m.luks_profile(), m.bios_desktop()))
        a = argvs(res)
        self.assertIn(["mkfs.ext4", "-F", "-L", "boot", "/dev/sda2"], a)
        self.assertIn(
            [
                "mount",
                "--mkdir",
                "-t",
                "ext4",
                "/dev/sda2",
                dk.TARGET + "/boot",
            ],
            a,
        )
        self.assertIn("1:ef02", first(res, "sgdisk", "-n"))

    def test_xfs_root(self):
        profil = m.luks_profile()
        profil["disk"]["lvm"]["root_fs"] = "xfs"
        res = dk.plan(resolved(profil, m.uefi_laptop()))
        self.assertIn(
            ["mkfs.xfs", "-f", "-L", "root", "/dev/vgtest/root"], argvs(res)
        )

    def test_refusals(self):
        petit = m.uefi_laptop()
        petit["disks"][0]["size"] = 21 * m.GIB
        res = dk.plan(resolved(m.luks_profile(), petit))
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "disk-too-small")
        self.assertEqual(res["plan"], [])
        self.assertEqual(
            dk.plan({"derived": {"disk": None}})["reason"], "no-target"
        )

    def test_required_secrets(self):
        self.assertEqual(
            dk.required_secrets(self.result["layout"]),
            [dk.SECRET_LUKS, dk.SECRET_LV],
        )


def lsblk(*disks):
    return json.dumps({"blockdevices": list(disks)})


def node(name, size_gib, model="Disque fictif 9000", children=None, **kw):
    n = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": size_gib * m.GIB,
        "rm": False,
        "ro": False,
        "rota": False,
        "model": model,
        "mountpoints": [None],
        "children": children or [],
    }
    n.update(kw)
    return n


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.attendu = m.disk("nvme0n1", 500)

    def test_unchanged_disk_passes(self):
        self.assertIsNone(
            dk.preflight(self.attendu, lsblk(node("nvme0n1", 500)))
        )

    def test_gone_changed_or_read_only(self):
        self.assertEqual(
            dk.preflight(self.attendu, lsblk(node("sda", 500)))[0],
            "target-gone",
        )
        self.assertEqual(
            dk.preflight(self.attendu, lsblk(node("nvme0n1", 256)))[0],
            "target-changed",
        )
        self.assertEqual(
            dk.preflight(
                self.attendu, lsblk(node("nvme0n1", 500, model="Autre modèle"))
            ),
            ("target-changed", {"device": "/dev/nvme0n1", "field": "model"}),
        )
        self.assertEqual(
            dk.preflight(self.attendu, lsblk(node("nvme0n1", 500, ro=True)))[
                0
            ],
            "target-read-only",
        )

    def test_boot_medium_is_refused(self):
        enfant = {
            "name": "nvme0n1p1",
            "type": "part",
            "mountpoints": ["/run/archiso/bootmnt"],
        }
        res = dk.preflight(
            self.attendu, lsblk(node("nvme0n1", 500, children=[enfant]))
        )
        self.assertEqual(res[0], "target-is-boot-medium")

    def test_mounted_or_swap_partition_is_refused(self):
        enfant = {
            "name": "nvme0n1p3",
            "type": "part",
            "mountpoints": ["[SWAP]"],
        }
        res = dk.preflight(
            self.attendu, lsblk(node("nvme0n1", 500, children=[enfant]))
        )
        self.assertEqual(
            res,
            (
                "target-in-use",
                {"device": "/dev/nvme0n1", "mounts": ["[SWAP]"]},
            ),
        )

    def test_open_luks_or_lvm_is_refused(self):
        enfant = {
            "name": "nvme0n1p2",
            "type": "part",
            "mountpoints": [None],
            "children": [
                {"name": "ancien", "type": "crypt", "mountpoints": [None]}
            ],
        }
        res = dk.preflight(
            self.attendu, lsblk(node("nvme0n1", 500, children=[enfant]))
        )
        self.assertEqual(res[0], "target-has-holders")
        self.assertEqual(res[1]["holders"], ["ancien"])

    def test_any_stacked_device_is_a_holder(self):
        # RAID6/10, multipath, dmraid, dm générique : tout ce qui n'est pas
        # une partition retient le disque, même sans montage.
        for sorte in ("raid6", "raid10", "linear", "mpath", "dmraid", "dm"):
            enfant = {
                "name": "nvme0n1p1",
                "type": "part",
                "mountpoints": [None],
                "children": [
                    {"name": "md-test", "type": sorte, "mountpoints": [None]}
                ],
            }
            res = dk.preflight(
                self.attendu, lsblk(node("nvme0n1", 500, children=[enfant]))
            )
            self.assertEqual(res[0], "target-has-holders", sorte)

    def test_nvme_format_refused_beside_another_namespace(self):
        voisin = node("nvme0n2", 100)
        autre_ctrl = node("nvme1n1", 100)
        self.assertIsNone(
            dk.preflight(
                self.attendu, lsblk(node("nvme0n1", 500), voisin), None
            )
        )
        self.assertEqual(
            dk.preflight(
                self.attendu,
                lsblk(node("nvme0n1", 500), voisin),
                nvme_format=True,
            ),
            (
                "nvme-shared-controller",
                {"device": "/dev/nvme0n1", "namespaces": ["nvme0n2"]},
            ),
        )
        self.assertIsNone(
            dk.preflight(
                self.attendu,
                lsblk(node("nvme0n1", 500), autre_ctrl),
                nvme_format=True,
            )
        )

    def test_nvme_siblings_and_plan_detection(self):
        disques = [{"name": n} for n in ("nvme0n1", "nvme0n2", "nvme10n1")]
        self.assertEqual(dk.nvme_siblings("nvme0n1", disques), ["nvme0n2"])
        self.assertEqual(dk.nvme_siblings("sda", disques), [])
        self.assertTrue(
            dk.plan_formats_nvme(
                [{"argv": ["nvme", "format", "/dev/x"], "stdin": None}]
            )
        )
        self.assertFalse(
            dk.plan_formats_nvme([{"argv": ["wipefs"], "stdin": None}])
        )


class TestExecute(unittest.TestCase):
    def test_secret_goes_to_stdin_without_newline(self):
        run = FakeRun()
        steps = [
            {"argv": ["cryptsetup", "luksFormat", "/dev/x"], "stdin": "luks"},
            {"argv": ["pvcreate", "/dev/y"], "stdin": None},
        ]
        lignes = []
        ok = dk.execute(steps, {"luks": "phrase inventée"}, run, lignes.append)
        self.assertEqual(ok, (True, None, 0))
        self.assertEqual(run.calls[0][1]["input"], "phrase inventée".encode())
        self.assertNotIn("stdin", run.calls[0][1])
        self.assertIs(run.calls[1][1]["stdin"], subprocess.DEVNULL)
        self.assertNotIn("phrase inventée", "\n".join(lignes))
        self.assertIn("$ cryptsetup luksFormat /dev/x  < [luks]", lignes)

    def test_stops_at_first_failure(self):
        run = FakeRun(codes={"sgdisk": 4})
        steps = [
            {"argv": ["wipefs", "--all", "/dev/x"], "stdin": None},
            {"argv": ["sgdisk", "--zap-all", "/dev/x"], "stdin": None},
            {"argv": ["mkfs.ext4", "/dev/x1"], "stdin": None},
        ]
        self.assertEqual(
            dk.execute(steps, run=run, log=lambda _l: None), (False, 1, 4)
        )
        self.assertEqual(len(run.calls), 2)

    def test_missing_secret_runs_nothing(self):
        run = FakeRun()
        steps = [{"argv": ["cryptsetup", "open"], "stdin": "luks"}]
        self.assertEqual(
            dk.execute(steps, {}, run, lambda _l: None), (False, 0, 2)
        )
        self.assertEqual(run.calls, [])

    def test_missing_tool(self):
        def run(argv, **_kw):
            raise FileNotFoundError(argv[0])

        steps = [{"argv": ["introuvable"], "stdin": None}]
        self.assertEqual(
            dk.execute(steps, run=run, log=lambda _l: None), (False, 0, 127)
        )


class TestTeardownAndUuids(unittest.TestCase):
    def test_teardown_order_and_keeps_going(self):
        lay = dk.layout(resolved(m.luks_profile(), m.uefi_laptop()))
        self.assertEqual(
            [s["argv"] for s in dk.teardown_steps(lay)],
            [
                ["swapoff", "/dev/vgtest/swap"],
                ["umount", "--recursive", dk.TARGET],
                ["cryptsetup", "close", dk.SECRET_MAPPER],
                ["vgchange", "--activate", "n", "vgtest"],
                ["cryptsetup", "close", dk.LUKS_MAPPER],
            ],
        )
        run = FakeRun(codes={"swapoff": 1, "umount": 32})
        dk.teardown(lay, run=run, log=lambda _l: None)
        self.assertEqual(len(run.calls), 5)

    def test_plain_teardown_only_unmounts(self):
        lay = dk.layout(resolved(m.plain_profile(), m.uefi_laptop()))
        self.assertEqual(
            [s["argv"] for s in dk.teardown_steps(lay)],
            [["umount", "--recursive", dk.TARGET]],
        )

    def test_read_uuids(self):
        lay = dk.layout(resolved(m.luks_profile(), m.uefi_laptop()))

        def run(argv, **_kw):
            return subprocess.CompletedProcess(
                argv, 0, f"uuid-de-{argv[-1].rsplit('/', 1)[-1]}\n", ""
            )

        uuids = dk.read_uuids(lay, run)
        self.assertEqual(uuids["luks_uuid"], "uuid-de-nvme0n1p2")
        self.assertEqual(uuids["root_uuid"], "uuid-de-root")
        self.assertEqual(uuids["swap_uuid"], "uuid-de-swap")
        self.assertEqual(uuids["secret_luks_uuid"], "uuid-de-secret")
        self.assertEqual(uuids["boot_uuid"], "uuid-de-nvme0n1p1")

    def test_missing_uuids(self):
        lay = dk.layout(resolved(m.luks_profile(), m.uefi_laptop()))
        tous = {
            "luks_uuid": "u1",
            "root_uuid": "u2",
            "secret_luks_uuid": "u3",
        }
        self.assertEqual(dk.missing_uuids(lay, tous), [])
        self.assertEqual(
            dk.missing_uuids(lay, dict(tous, luks_uuid=None)), ["luks_uuid"]
        )
        self.assertEqual(
            dk.missing_uuids(lay, dict(tous, secret_luks_uuid=None)),
            ["secret_luks_uuid"],
        )
        plain = dk.layout(resolved(m.plain_profile(), m.uefi_laptop()))
        self.assertEqual(dk.missing_uuids(plain, {}), ["root_uuid"])
        self.assertEqual(dk.missing_uuids(plain, {"root_uuid": "u"}), [])

    def test_blkid_failure_is_none(self):
        def run(argv, **_kw):
            return subprocess.CompletedProcess(argv, 2, "", "")

        self.assertIsNone(dk.blkid_uuid("/dev/x", run))


if __name__ == "__main__":
    unittest.main()
