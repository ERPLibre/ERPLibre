#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""system_usb : la lecture du JSON de lsblk, les disques système, les clés
candidates, les refus, le plan d'écriture, la relecture et le catalogue.

Chaque arbre lsblk est fabriqué ici, avec des fabricants, des modèles et
des numéros de série inventés. Rien ne lit les disques de la machine qui
lance le test : lien_by_id reçoit une racine /dev temporaire, et ses
appels sur /dev se font sur des noms qui n'y désignent rien de connu.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_usb as su  # noqa: E402

GIO = su.GIO
RACINE_INEXISTANTE = "/chemin/inexistant/depot"


def noeud(
    nom,
    type_="part",
    tran=None,
    rm=False,
    hotplug=False,
    ro=False,
    taille=GIO,
    vendor=None,
    model=None,
    serial=None,
    label=None,
    fstype=None,
    montages=(),
    pkname=None,
    enfants=(),
):
    """Un nœud tel que lsblk -J -b le rend (util-linux ≥ 2.37)."""
    n = {
        "name": nom,
        "path": "/dev/"
        + (f"mapper/{nom}" if type_ in ("crypt", "lvm") else nom),
        "type": type_,
        "tran": tran,
        "rm": rm,
        "hotplug": hotplug,
        "ro": ro,
        "size": taille,
        "vendor": vendor,
        "model": model,
        "serial": serial,
        "label": label,
        "fstype": fstype,
        "mountpoints": list(montages) or [None],
        "pkname": pkname,
    }
    if enfants:
        n["children"] = list(enfants)
    return n


def lsblk(*disques):
    return {"blockdevices": list(disques)}


def nvme_systeme():
    """Un portable : un NVMe chiffré, LUKS puis LVM, qui porte /, /home,
    le swap, et /boot/efi en clair."""
    return noeud(
        "nvme0n1",
        "disk",
        tran="nvme",
        taille=512 * GIO,
        model="Fictional NVMe 512",
        serial="FICTNVME000001",
        enfants=[
            noeud(
                "nvme0n1p1",
                fstype="vfat",
                montages=["/boot/efi"],
                pkname="nvme0n1",
            ),
            noeud(
                "nvme0n1p2",
                fstype="crypto_LUKS",
                pkname="nvme0n1",
                taille=500 * GIO,
                enfants=[
                    noeud(
                        "luks-fictif",
                        "crypt",
                        fstype="LVM2_member",
                        pkname="nvme0n1p2",
                        enfants=[
                            noeud(
                                "vg-racine",
                                "lvm",
                                fstype="ext4",
                                montages=["/"],
                            ),
                            noeud(
                                "vg-maison",
                                "lvm",
                                fstype="ext4",
                                montages=["/home"],
                            ),
                            noeud(
                                "vg-echange",
                                "lvm",
                                fstype="swap",
                                montages=["[SWAP]"],
                            ),
                        ],
                    )
                ],
            ),
        ],
    )


def cle_montee(nom="sdb", serial="  KT0042FAKE0001  ", taille=64 * GIO):
    """Une clé USB à deux partitions montées ; le numéro de série porte les
    espaces de remplissage de certains contrôleurs."""
    return noeud(
        nom,
        "disk",
        tran="usb",
        rm=True,
        hotplug=True,
        taille=taille,
        vendor="Kestrel ",
        model="DataTwig 64",
        serial=serial,
        enfants=[
            noeud(
                f"{nom}1",
                fstype="vfat",
                label="TWIGA",
                montages=["/mnt/exemple-a"],
                pkname=nom,
            ),
            noeud(
                f"{nom}2",
                fstype="ext4",
                label="TWIGB",
                montages=["/mnt/exemple-b"],
                pkname=nom,
            ),
        ],
    )


def ssd_usb(nom="sdc", taille=500 * GIO):
    """Un SSD externe en USB : ni amovible ni « rm », mais branché à
    chaud."""
    return noeud(
        nom,
        "disk",
        tran="usb",
        rm=False,
        hotplug=True,
        taille=taille,
        vendor="Fictional",
        model="PortaSSD",
        serial="FICTSSD0000777",
        enfants=[noeud(f"{nom}1", fstype="exfat", pkname=nom)],
    )


def lecteur_sd():
    """Un lecteur de carte intégré : amovible, sans transport."""
    return noeud(
        "mmcblk0",
        "disk",
        tran=None,
        rm=True,
        taille=32 * GIO,
        serial="0xfeedf00d",
        enfants=[noeud("mmcblk0p1", fstype="vfat", pkname="mmcblk0")],
    )


def systeme_sur_usb():
    """Un poste démarré depuis un disque USB : / est dessus."""
    return noeud(
        "sdd",
        "disk",
        tran="usb",
        rm=True,
        taille=128 * GIO,
        vendor="Kestrel",
        model="BootTwig",
        serial="KT0042FAKE0099",
        enfants=[
            noeud("sdd1", fstype="vfat", montages=["/boot"], pkname="sdd"),
            noeud("sdd2", fstype="ext4", montages=["/"], pkname="sdd"),
        ],
    )


def en_chaines(n):
    """Le même nœud tel que le rend un lsblk ancien sur
    COLONNES_ANCIENNES : booléens et tailles en chaînes, pas de PATH, et
    MOUNTPOINT au singulier."""
    n = dict(n)
    n.pop("path")
    for cle in ("rm", "hotplug", "ro"):
        n[cle] = "1" if n[cle] else "0"
    n["size"] = str(n["size"])
    montages = [m for m in n.pop("mountpoints") if m]
    n["mountpoint"] = montages[0] if montages else None
    if "children" in n:
        n["children"] = [en_chaines(e) for e in n["children"]]
    return n


def cle_par_nom(liste, nom):
    return next(d for d in liste if d["nom"] == nom)


class TestLaLecture(unittest.TestCase):
    def test_lire_lsblk_parses_the_json(self):
        with mock.patch.object(
            su, "commande", return_value='{"blockdevices": []}'
        ) as c:
            self.assertEqual(su.lire_lsblk(), {"blockdevices": []})
        args = c.call_args.args[0]
        self.assertEqual(args[:3], ["lsblk", "-J", "-b"])
        self.assertIn("MOUNTPOINTS", args[-1])

    def test_lire_lsblk_none_when_missing_or_garbage(self):
        for sortie in (None, "", "pas du json"):
            with (
                self.subTest(sortie=sortie),
                mock.patch.object(su, "commande", return_value=sortie),
            ):
                self.assertIsNone(su.lire_lsblk())

    def test_disks_only_and_their_fields(self):
        d = su.disques(lsblk(cle_montee()), racine_dev=RACINE_INEXISTANTE)
        self.assertEqual(len(d), 1)
        cle = d[0]
        self.assertEqual(cle["path"], "/dev/sdb")
        self.assertEqual(cle["serial"], "KT0042FAKE0001")
        self.assertEqual(cle["vendor"], "Kestrel")
        self.assertEqual(cle["taille"], 64 * GIO)
        self.assertTrue(cle["rm"])
        self.assertIsNone(cle["by_id"])
        self.assertEqual(
            [
                (p["path"], p["label"], p["fstype"], p["mountpoints"])
                for p in cle["partitions"]
            ],
            [
                ("/dev/sdb1", "TWIGA", "vfat", ["/mnt/exemple-a"]),
                ("/dev/sdb2", "TWIGB", "ext4", ["/mnt/exemple-b"]),
            ],
        )

    def test_booleans_and_sizes_as_strings(self):
        d = su.disques(
            lsblk(en_chaines(cle_montee())), racine_dev=RACINE_INEXISTANTE
        )[0]
        self.assertIs(d["rm"], True)
        self.assertIs(d["ro"], False)
        self.assertEqual(d["taille"], 64 * GIO)
        self.assertEqual(d["path"], "/dev/sdb")
        self.assertEqual(d["partitions"][0]["path"], "/dev/sdb1")
        self.assertEqual(d["partitions"][0]["mountpoints"], ["/mnt/exemple-a"])

    def test_a_refused_column_falls_back_to_the_old_columns(self):
        with mock.patch.object(
            su, "commande", side_effect=[None, '{"blockdevices": []}']
        ) as c:
            self.assertEqual(su.lire_lsblk(), {"blockdevices": []})
        premier, second = (a.args[0] for a in c.call_args_list)
        self.assertEqual(premier, su.COMMANDE_LSBLK)
        self.assertEqual(second, su.COMMANDE_LSBLK_ANCIENNE)
        self.assertNotIn("MOUNTPOINTS", second[-1])
        self.assertNotIn("PATH", second[-1].split(","))
        self.assertIn("MOUNTPOINT", second[-1].split(","))

    def test_missing_path_and_tran_are_tolerated(self):
        n = cle_montee()
        del n["path"], n["tran"]
        d = su.disques(lsblk(n), racine_dev=RACINE_INEXISTANTE)[0]
        self.assertEqual(d["path"], "/dev/sdb")
        self.assertIsNone(d["tran"])
        self.assertFalse(su.est_cle(d))

    def test_by_id_link_found_partitions_ignored(self):
        with tempfile.TemporaryDirectory() as dev:
            os.makedirs(os.path.join(dev, "disk", "by-id"))
            for f in ("sdb", "sdb1", "sda"):
                open(os.path.join(dev, f), "w").close()
            liens = {
                "usb-Kestrel_DataTwig_KT0042FAKE0001-0:0-part1": "../../sdb1",
                "usb-Kestrel_DataTwig_KT0042FAKE0001-0:0": "../../sdb",
                "ata-Fictional_Disk_FICT0001": "../../sda",
            }
            for nom, cible in liens.items():
                os.symlink(cible, os.path.join(dev, "disk", "by-id", nom))
            self.assertEqual(
                su.lien_by_id("/dev/sdb", racine_dev=dev),
                os.path.join(
                    dev,
                    "disk",
                    "by-id",
                    "usb-Kestrel_DataTwig_KT0042FAKE0001-0:0",
                ),
            )
            self.assertIsNone(su.lien_by_id("/dev/sda", racine_dev=dev))
            d = su.disques(lsblk(cle_montee()), racine_dev=dev)[0]
            self.assertTrue(d["by_id"].endswith("KT0042FAKE0001-0:0"))


class TestLesDisquesSysteme(unittest.TestCase):
    def test_luks_lvm_nested_mounts_make_a_system_disk(self):
        donnees = lsblk(nvme_systeme(), cle_montee())
        self.assertEqual(
            su.disques_systeme(donnees, chemins_extra=()), {"nvme0n1"}
        )

    def test_each_critical_mount_alone_is_enough(self):
        for montage in su.MONTAGES_CRITIQUES:
            disque = noeud(
                "sde",
                "disk",
                tran="usb",
                enfants=[noeud("sde1", montages=[montage])],
            )
            with self.subTest(montage=montage):
                self.assertEqual(
                    su.disques_systeme(lsblk(disque), chemins_extra=()),
                    {"sde"},
                )

    def test_live_boot_key_is_not_a_target(self):
        # TODO lancé depuis la clé ERPLibre : la racine est un overlay
        # invisible de lsblk, seul le montage du support désigne la clé.
        live = noeud(
            "sdf",
            "disk",
            tran="usb",
            rm=True,
            taille=16 * GIO,
            enfants=[
                noeud(
                    "sdf1",
                    fstype="iso9660",
                    label="ERPLIBRE_203101",
                    montages=["/run/archiso/bootmnt"],
                ),
                noeud("sdf2", fstype="vfat"),
            ],
        )
        donnees = lsblk(live, cle_montee())
        cles = su.cles_usb(
            donnees, chemins_extra=(), racine_dev=RACINE_INEXISTANTE
        )
        self.assertEqual([c["nom"] for c in cles], ["sdb"])

    def test_root_on_a_usb_disk_is_system_and_not_a_key(self):
        donnees = lsblk(systeme_sur_usb(), cle_montee())
        self.assertIn("sdd", su.disques_systeme(donnees, chemins_extra=()))
        cles = su.cles_usb(
            donnees, chemins_extra=(), racine_dev=RACINE_INEXISTANTE
        )
        self.assertEqual([c["nom"] for c in cles], ["sdb"])

    def test_the_repository_disk_follows_the_longest_mount(self):
        depot = noeud(
            "sdf",
            "disk",
            tran="usb",
            enfants=[noeud("sdf1", montages=["/srv/fictif"])],
        )
        donnees = lsblk(nvme_systeme(), depot)
        self.assertEqual(
            su.disques_systeme(
                donnees, chemins_extra=("/srv/fictif/depot/erplibre",)
            ),
            {"nvme0n1", "sdf"},
        )
        # Hors de tout autre montage, c'est le disque de /.
        self.assertEqual(
            su.disques_systeme(donnees, chemins_extra=("/opt/fictif/depot",)),
            {"nvme0n1"},
        )

    def test_a_mirror_seen_under_two_disks_marks_both(self):
        md = noeud("md0", "raid1", fstype="ext4", montages=["/"])
        a = noeud(
            "sdg", "disk", tran="sata", enfants=[noeud("sdg1", enfants=[md])]
        )
        b = noeud(
            "sdh", "disk", tran="sata", enfants=[noeud("sdh1", enfants=[md])]
        )
        self.assertEqual(
            su.disques_systeme(lsblk(a, b), chemins_extra=()), {"sdg", "sdh"}
        )


class TestLesCles(unittest.TestCase):
    def cles(self, *disques):
        return su.cles_usb(
            lsblk(*disques), chemins_extra=(), racine_dev=RACINE_INEXISTANTE
        )

    def test_laptop_with_nvme_only_has_no_key(self):
        self.assertEqual(self.cles(nvme_systeme()), [])

    def test_a_usb_key_with_mounted_partitions_is_a_candidate(self):
        self.assertEqual(
            [c["nom"] for c in self.cles(nvme_systeme(), cle_montee())],
            ["sdb"],
        )

    def test_a_usb_ssd_without_rm_is_a_candidate(self):
        self.assertEqual([c["nom"] for c in self.cles(ssd_usb())], ["sdc"])

    def test_a_built_in_card_reader_is_not_a_key(self):
        # Pas de transport : un lecteur intégré se confond avec une mémoire
        # eMMC soudée, qui peut porter un système.
        self.assertEqual(self.cles(lecteur_sd()), [])

    def test_a_hotplug_sata_bay_is_not_a_key(self):
        baie = noeud("sdi", "disk", tran="sata", hotplug=True, rm=False)
        self.assertEqual(self.cles(baie), [])

    def test_an_empty_usb_card_reader_is_not_offered(self):
        vide = noeud("sdj", "disk", tran="usb", rm=True, taille=0)
        self.assertEqual(self.cles(vide), [])

    def test_strings_booleans_still_give_the_key(self):
        self.assertEqual(
            [c["nom"] for c in self.cles(en_chaines(cle_montee()))], ["sdb"]
        )


class TestLesRefus(unittest.TestCase):
    def disque(self, n):
        return su.disques(lsblk(n), racine_dev=RACINE_INEXISTANTE)[0]

    def test_codes(self):
        cle = self.disque(cle_montee())
        cas = [
            (dict(cle, type="part"), GIO, set(), "not-disk"),
            (cle, GIO, {"sdb"}, "system"),
            (self.disque(lecteur_sd()), GIO, set(), "not-usb"),
            (dict(cle, ro=True), GIO, set(), "read-only"),
            (cle, 65 * GIO, set(), "too-small"),
            (self.disque(ssd_usb(taille=1024 * GIO)), GIO, set(), "too-large"),
        ]
        for disque, taille, systeme, code in cas:
            with self.subTest(code=code):
                self.assertEqual(
                    su.refus_ecriture(disque, taille, systeme)[0], code
                )
        self.assertIsNone(su.refus_ecriture(cle, GIO, set()))
        self.assertEqual(su.refus_ecriture(None, GIO)[0], "not-disk")

    def test_the_ceiling_itself_is_accepted(self):
        cle = self.disque(ssd_usb(taille=su.PLAFOND))
        self.assertIsNone(su.refus_ecriture(cle, GIO))

    def test_an_open_luks_on_the_key_is_refused(self):
        n = cle_montee()
        n["children"][1]["children"] = [noeud("luks-cle", "crypt")]
        code, details = su.refus_ecriture(self.disque(n), GIO)
        self.assertEqual(code, "mapped")
        self.assertIn("/dev/mapper/luks-cle", details["mapped"])

    def test_a_mapping_on_the_whole_key_is_refused(self):
        """LUKS ou LVM posé sur le disque entier : le mappage est un
        enfant direct du disque, sans partition entre les deux."""
        for type_ in ("crypt", "lvm", "raid1"):
            with self.subTest(type_=type_):
                for montages in (["/mnt/exemple"], []):
                    n = noeud(
                        "sdz",
                        "disk",
                        tran="usb",
                        rm=True,
                        taille=16 * GIO,
                        model="DataTwig 16",
                        serial="KT0042FAKE0123",
                        enfants=[
                            noeud(
                                "luks-abc",
                                type_,
                                montages=montages,
                                pkname="sdz",
                            )
                        ],
                    )
                    disque = self.disque(n)
                    code, details = su.refus_ecriture(disque, GIO)
                    self.assertEqual(code, "mapped")
                    self.assertIn(
                        disque["partitions"][0]["path"], details["mapped"]
                    )
                    res = su.plan_ecriture(disque, "/i.iso", GIO, eject=True)
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["plan"], [])

    def test_read_only_as_a_string(self):
        n = cle_montee()
        n["ro"] = "1"
        self.assertEqual(
            su.refus_ecriture(self.disque(n), GIO)[0], "read-only"
        )

    def test_a_system_key_is_refused_in_the_plan(self):
        res = su.plan_ecriture(
            self.disque(systeme_sur_usb()), "/x.iso", GIO, {"sdd"}, eject=True
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "system")
        self.assertEqual(res["plan"], [])


class TestLePlan(unittest.TestCase):
    def disque(self, n, by_id=None):
        d = su.disques(lsblk(n), racine_dev=RACINE_INEXISTANTE)[0]
        d["by_id"] = by_id
        return d

    def test_exact_argv_with_two_mounted_partitions(self):
        res = su.plan_ecriture(
            self.disque(cle_montee()), "/isos/image.iso", 1234, eject=True
        )
        self.assertTrue(res["ok"])
        self.assertEqual(
            res["plan"],
            [
                ["sudo", "umount", "-A", "/dev/sdb1"],
                ["sudo", "umount", "-A", "/dev/sdb2"],
                ["sudo", "wipefs", "--all", "/dev/sdb"],
                [
                    "sudo",
                    "dd",
                    "if=/isos/image.iso",
                    "of=/dev/sdb",
                    "bs=4M",
                    "conv=fsync",
                    "oflag=direct",
                    "status=progress",
                ],
                ["sync"],
                ["sudo", "cmp", "-n", "1234", "/isos/image.iso", "/dev/sdb"],
                ["sudo", "eject", "/dev/sdb"],
            ],
        )
        self.assertEqual(res["warnings"], [])

    def test_by_id_is_preferred_and_umount_keeps_partitions(self):
        lien = "/dev/disk/by-id/usb-Kestrel_DataTwig_KT0042FAKE0001-0:0"
        res = su.plan_ecriture(
            self.disque(cle_montee(), by_id=lien), "/i.iso", 10, eject=True
        )
        self.assertEqual(res["plan"][0], ["sudo", "umount", "-A", "/dev/sdb1"])
        self.assertEqual(res["plan"][2], ["sudo", "wipefs", "--all", lien])
        self.assertIn(f"of={lien}", res["plan"][3])
        self.assertEqual(res["plan"][5][-1], lien)
        self.assertEqual(res["plan"][6], ["sudo", "eject", lien])
        self.assertEqual(res["details"]["target"], lien)

    def test_unmounted_key_has_no_umount(self):
        res = su.plan_ecriture(
            self.disque(ssd_usb()), "/i.iso", 10, eject=True
        )
        self.assertEqual(res["plan"][0][:3], ["sudo", "wipefs", "--all"])

    def test_swap_on_the_key_is_turned_off(self):
        n = ssd_usb()
        n["children"][0]["mountpoints"] = ["[SWAP]"]
        res = su.plan_ecriture(self.disque(n), "/i.iso", 10, eject=True)
        self.assertEqual(res["plan"][0], ["sudo", "swapoff", "/dev/sdc1"])
        self.assertEqual(res["plan"][1][:3], ["sudo", "wipefs", "--all"])

    def test_a_whole_disk_iso_mount_is_unmounted(self):
        n = noeud(
            "sdk",
            "disk",
            tran="usb",
            taille=8 * GIO,
            fstype="iso9660",
            montages=["/mnt/exemple-iso"],
        )
        res = su.plan_ecriture(self.disque(n), "/i.iso", 10, eject=True)
        self.assertEqual(res["plan"][0], ["sudo", "umount", "-A", "/dev/sdk"])

    def test_a_partition_mounted_twice_is_unmounted_from_every_target(self):
        """umount sans -A ne retire que le dernier montage : -A les retire
        tous, et une seule commande suffit par partition."""
        n = cle_montee()
        n["children"][1]["mountpoints"] = ["/mnt/exemple-b", "/mnt/exemple-c"]
        res = su.plan_ecriture(self.disque(n), "/i.iso", 10, eject=True)
        self.assertEqual(
            res["plan"][:3],
            [
                ["sudo", "umount", "-A", "/dev/sdb1"],
                ["sudo", "umount", "-A", "/dev/sdb2"],
                ["sudo", "wipefs", "--all", "/dev/sdb"],
            ],
        )

    def test_occupation_sees_an_extra_mount(self):
        avant = self.disque(cle_montee())
        n = cle_montee()
        n["children"][1]["mountpoints"] = ["/mnt/exemple-b", "/mnt/exemple-c"]
        apres = self.disque(n)
        self.assertEqual(su.occupation(avant), su.occupation(avant))
        self.assertNotEqual(su.occupation(avant), su.occupation(apres))

    def test_without_eject_a_warning_and_no_step(self):
        res = su.plan_ecriture(
            self.disque(cle_montee()), "/i.iso", 10, eject=False
        )
        self.assertNotIn("eject", [c[1] for c in res["plan"] if len(c) > 1])
        self.assertEqual(
            res["warnings"], [{"code": "no-eject", "device": "/dev/sdb"}]
        )

    def test_eject_looked_up_in_the_path(self):
        with mock.patch.object(su.shutil, "which", return_value=None):
            res = su.plan_ecriture(self.disque(cle_montee()), "/i.iso", 10)
        self.assertEqual(res["warnings"][0]["code"], "no-eject")

    def test_an_iso_on_the_key_itself_is_refused(self):
        res = su.plan_ecriture(
            self.disque(cle_montee()),
            "/mnt/exemple-b/sous/image.iso",
            10,
            eject=True,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "iso-on-key")
        self.assertEqual(res["details"]["mountpoint"], "/mnt/exemple-b")


class TestLaMemeCle(unittest.TestCase):
    def test_same_and_changed(self):
        d = lambda n: su.disques(lsblk(n), racine_dev=RACINE_INEXISTANTE)[0]  # noqa: E731
        avant = d(cle_montee())
        self.assertTrue(su.meme_cle(avant, d(cle_montee())))
        self.assertFalse(
            su.meme_cle(avant, d(cle_montee(serial="KT0042FAKE0002")))
        )
        self.assertFalse(su.meme_cle(avant, d(cle_montee(taille=32 * GIO))))
        self.assertFalse(su.meme_cle(avant, d(cle_montee(nom="sdc"))))
        autre = cle_montee()
        autre["model"] = "DataTwig 128"
        self.assertFalse(su.meme_cle(avant, d(autre)))
        self.assertFalse(su.meme_cle(avant, None))

    def test_trouver(self):
        liste = su.disques(
            lsblk(nvme_systeme(), cle_montee()), racine_dev=RACINE_INEXISTANTE
        )
        self.assertEqual(su.trouver(liste, "/dev/sdb")["nom"], "sdb")
        self.assertIsNone(su.trouver(liste, "/dev/sdz"))


class TestLesSommes(unittest.TestCase):
    SOMME = "ab" * 32

    def test_parse_sha256sums(self):
        texte = (
            f"{'0' * 64}  archlinux-bootstrap-x86_64.tar.zst\n"
            f"{self.SOMME.upper()}  archlinux-x86_64.iso\n"
            f"{'1' * 64} *autre.iso\n"
            f"{'2' * 64}  ./relatif.iso\n"
            "ligne cassée\n"
        )
        self.assertEqual(
            su.parse_sha256sums(texte, "archlinux-x86_64.iso"), self.SOMME
        )
        self.assertEqual(su.parse_sha256sums(texte, "autre.iso"), "1" * 64)
        self.assertEqual(su.parse_sha256sums(texte, "relatif.iso"), "2" * 64)
        self.assertIsNone(su.parse_sha256sums(texte, "absente.iso"))
        self.assertIsNone(su.parse_sha256sums("zz  x.iso", "x.iso"))
        self.assertIsNone(su.parse_sha256sums(None, "x.iso"))

    def test_sha256_fichier(self):
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"abc")
        self.addCleanup(os.remove, fh.name)
        self.assertEqual(
            su.sha256_fichier(fh.name),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertIsNone(su.sha256_fichier("/chemin/inexistant/x.iso"))


class TestLeCatalogue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def par_cle(self, dossier=None):
        return {e["cle"]: e for e in su.catalogue(dossier or self.tmp.name)}

    def test_without_a_built_iso(self):
        c = self.par_cle()
        locale = c["erplibre-archlinux-amd64"]
        self.assertFalse(locale["disponible"])
        self.assertIn(
            "Build the ERPLibre Arch Linux ISO", locale["raison_key"]
        )
        self.assertTrue(c["archlinux-amd64"]["disponible"])
        self.assertEqual(c["archlinux-amd64"]["source"], "url")
        self.assertEqual(
            c["archlinux-amd64"]["chemin"],
            os.path.join(self.tmp.name, "archlinux-x86_64.iso"),
        )
        self.assertFalse(c["erplibre-archlinux-arm64"]["disponible"])
        self.assertIn("aarch64", c["erplibre-archlinux-arm64"]["raison_key"])
        self.assertFalse(c["erplibre-archlinux-s390x"]["disponible"])
        self.assertIn("s390x", c["erplibre-archlinux-s390x"]["raison_key"])

    def test_the_newest_built_iso_is_chosen(self):
        for nom, date in (
            ("erplibre-archlinux-2026.01.01-x86_64.iso", 1000),
            ("erplibre-archlinux-2026.02.01-x86_64.iso", 2000),
            ("autre-x86_64.iso", 3000),
        ):
            chemin = os.path.join(self.tmp.name, nom)
            open(chemin, "w").close()
            os.utime(chemin, (date, date))
        locale = self.par_cle()["erplibre-archlinux-amd64"]
        self.assertTrue(locale["disponible"])
        self.assertIsNone(locale["raison_key"])
        self.assertTrue(locale["chemin"].endswith("2026.02.01-x86_64.iso"))

    def test_iso_dir_is_expanded_at_call_time(self):
        with mock.patch.dict(os.environ, {"HOME": self.tmp.name}):
            self.assertEqual(
                su.dossier_iso(),
                os.path.join(self.tmp.name, ".erplibre", "iso"),
            )

    def test_download_plan(self):
        entree = self.par_cle()["archlinux-amd64"]
        res = su.plan_telechargement(entree)
        self.assertTrue(res["ok"])
        partiel = entree["chemin"] + ".part"
        self.assertEqual(res["plan"][0][-1], su.URL_ARCH_SOMMES)
        self.assertEqual(
            res["plan"][1],
            [
                "curl",
                "-fL",
                "--retry",
                "3",
                "-C",
                "-",
                "-o",
                partiel,
                su.URL_ARCH,
            ],
        )
        self.assertEqual(res["details"]["partial"], partiel)
        refus = su.plan_telechargement(
            self.par_cle()["erplibre-archlinux-s390x"]
        )
        self.assertFalse(refus["ok"])

    def test_extension(self):
        self.assertTrue(su.extension_image("/a/B.ISO"))
        self.assertTrue(su.extension_image("/a/b.img"))
        self.assertFalse(su.extension_image("/a/b.zip"))


class TestLesProfilsEtLeRemastering(unittest.TestCase):
    """Le côté pur des profils machine : écriture privée, ISO dérivée,
    date de volume, plan xorriso. Les noms et dates sont inventés."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prive = os.path.join(self.tmp.name, "private", "iso", "machine")

    def test_uuid_to_volume_date(self):
        self.assertEqual(
            su.uuid_vers_volume_date("2026-11-25-09-29-22-00"),
            "2026112509292200",
        )
        for mauvais in (None, "", "2026-11-25", "abcd-11-25-09-29-22-00", 7):
            with self.subTest(mauvais=mauvais):
                self.assertIsNone(su.uuid_vers_volume_date(mauvais))

    def test_volume_date_from_pvd_info(self):
        texte = (
            "Volume Id    : FICTIF_209901\n"
            "Creation Time: 2099010203040500\n"
            "Modif. Time  : 2099010203040600\n"
            "Expir. Time  : 0000000000000000\n"
        )
        self.assertEqual(su.volume_date_depuis_pvd(texte), "2099010203040600")
        sans_modif = texte.replace(
            "Modif. Time  : 2099010203040600",
            "Modif. Time  : 0000000000000000",
        )
        self.assertEqual(
            su.volume_date_depuis_pvd(sans_modif), "2099010203040500"
        )
        self.assertIsNone(su.volume_date_depuis_pvd("rien"))

    def test_read_volume_date_prefers_blkid(self):
        reponses = {"blkid": "2099-01-02-03-04-05-00\n"}
        with mock.patch.object(
            su, "commande", side_effect=lambda a, **k: reponses.get(a[0])
        ):
            self.assertEqual(su.lire_volume_date("/x.iso"), "2099010203040500")
        reponses = {"xorriso": "Modif. Time  : 2099010203040700\n"}
        with mock.patch.object(
            su, "commande", side_effect=lambda a, **k: reponses.get(a[0])
        ):
            self.assertEqual(su.lire_volume_date("/x.iso"), "2099010203040700")

    def test_remaster_plan_argv(self):
        res = su.plan_remaster(
            "/iso/base.iso", "/d/p.json", "/d/a-b.iso", "2099010203040500"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(
            res["plan"],
            [
                [
                    "xorriso",
                    "-indev",
                    "/iso/base.iso",
                    "-outdev",
                    "/d/a-b.iso",
                    "-boot_image",
                    "any",
                    "replay",
                    "-boot_image",
                    "any",
                    "gpt_disk_guid=volume_date_uuid",
                    "-volume_date",
                    "uuid",
                    "2099010203040500",
                    "-map",
                    "/d/p.json",
                    "/erplibre/machine.json",
                    "-commit",
                ]
            ],
        )
        self.assertEqual(res["details"]["derived"], "/d/a-b.iso")

    def test_remaster_refusals_and_reuse(self):
        for date in (None, "", "2099-01-02", "20990102030405"):
            with self.subTest(date=date):
                res = su.plan_remaster("/b.iso", "/p.json", "/d.iso", date)
                self.assertFalse(res["ok"])
                self.assertEqual(res["reason"], "no-volume-date")
        res = su.plan_remaster("/b.iso", None, "/d.iso", None, reutiliser=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["plan"], [])
        self.assertTrue(res["details"]["reuse"])

    def test_derived_path(self):
        self.assertEqual(
            su.chemin_derive("/d", "a" * 64, "b" * 64),
            "/d/aaaaaaaaaaaa-bbbbbbbbbbbb.iso",
        )

    def test_erplibre_iso_names(self):
        self.assertTrue(
            su.est_iso_erplibre("/x/erplibre-archlinux-2099.01.02-x86_64.iso")
        )
        for nom in (
            "/x/archlinux-x86_64.iso",
            "/x/image.iso",
            None,
            # L'autotest efface le premier disque sans rien demander.
            "erplibre-archlinux-autotest-2099.01.02-x86_64.iso",
        ):
            self.assertFalse(su.est_iso_erplibre(nom))

    def test_outdated_derived_files_follow_the_naming_only(self):
        garder = os.path.join(self.tmp.name, "111111111111-222222222222.iso")
        noms = [
            "111111111111-222222222222.iso",
            "111111111111-222222222222.iso.sha256",
            "111111111111-333333333333.iso",
            "111111111111-333333333333.iso.sha256",
            "111111111111-333333333333.json",
            "111111111111-333333333333.json.tmp",
            "erplibre-archlinux-2099.01.02-x86_64.iso",
            "notes.txt",
        ]
        for nom in noms:
            with open(os.path.join(self.tmp.name, nom), "w") as fh:
                fh.write("x")
        self.assertEqual(
            [
                os.path.basename(c)
                for c in su.derives_perimes(self.tmp.name, garder)
            ],
            noms[2:6],
        )
        self.assertEqual(su.derives_perimes("/nulle/part", garder), [])

    def test_private_dir_creates_parents_0700_and_tightens_itself(self):
        cible = os.path.join(self.tmp.name, "a", "b", "c")
        su.dossier_prive(cible)
        for d in ("a", "a/b", "a/b/c"):
            chemin = os.path.join(self.tmp.name, d)
            self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o700, d)
        os.chmod(cible, 0o755)
        su.dossier_prive(cible)
        self.assertEqual(os.stat(cible).st_mode & 0o777, 0o700)

    def test_a_failed_atomic_write_leaves_no_temporary(self):
        chemin = os.path.join(self.tmp.name, "w", "f.json")
        with mock.patch.object(
            su.os, "replace", side_effect=OSError(28, "plein")
        ):
            with self.assertRaises(OSError):
                su.ecrire_atomique(chemin, "{}")
        self.assertEqual(os.listdir(os.path.dirname(chemin)), [])

    def test_a_profile_is_saved_back_to_the_given_path(self):
        chemin = os.path.join(self.prive, "boite.json")
        self.assertEqual(
            su.enregistrer_profil(
                {"schema": 1, "name": "poste-quillon"},
                prive=self.prive,
                chemin=chemin,
            ),
            chemin,
        )
        self.assertEqual(os.listdir(self.prive), ["boite.json"])

    def test_derived_iso_is_reused_only_with_a_matching_sum(self):
        derive = os.path.join(self.tmp.name, "a-b.iso")
        self.assertFalse(su.derive_valide(derive))
        with open(derive, "wb") as fh:
            fh.write(b"iso derivee")
        self.assertFalse(su.derive_valide(derive))
        su.ecrire_atomique(su.chemin_somme(derive), su.ligne_somme(derive))
        self.assertTrue(su.derive_valide(derive))
        with open(derive, "ab") as fh:
            fh.write(b"tronquee")
        self.assertFalse(su.derive_valide(derive))

    def test_private_profiles_are_written_0600_in_a_0700_dir(self):
        chemin = su.enregistrer_profil(
            {"schema": 1, "name": "poste-quillon"}, prive=self.prive
        )
        self.assertEqual(
            chemin, os.path.join(self.prive, "poste-quillon.json")
        )
        self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.prive).st_mode & 0o777, 0o700)
        self.assertEqual(os.listdir(self.prive), ["poste-quillon.json"])

    def test_a_profile_with_a_secret_is_never_written(self):
        with self.assertRaises(ValueError):
            su.enregistrer_profil(
                {"name": "x", "user": {"password": "y"}}, prive=self.prive
            )
        self.assertFalse(os.path.exists(self.prive))

    def test_profile_dirs_repository_then_private(self):
        self.assertEqual(
            su.dossiers_profils(self.prive), [su.mp.REPO_DIR, self.prive]
        )
        self.assertTrue(
            su.DOSSIER_PROFILS_PRIVES.endswith(
                os.path.join("private", "iso", "machine")
            )
        )

    def test_xorriso_package_on_arch(self):
        self.assertEqual(su.PAQUETS_XORRISO["pacman"], "libisoburn")


if __name__ == "__main__":
    unittest.main()
