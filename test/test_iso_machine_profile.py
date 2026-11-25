#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil machine de l'installateur ERPLibre : fusion et « extends »,
validation (dont le refus de tout secret), résolution de « auto » et
« ask » sur des faits de matériel, résumé.

Les faits sont des fixtures INVENTÉES, au format que rend
facts.facts_from() : un portable UEFI AMD à NVMe 4 KiB, un poste BIOS
Intel à disque SATA rotatif, une machine virtuelle, un petit disque où la
swap se plafonne. Aucun test ne lit le matériel de la machine qui le
lance.
"""

import json
import os
import tempfile
import unittest

from script.iso.archlinux.machine import machine_profile as mp

GIB = mp.GIB


def disque(nom, taille_gib, **champs):
    base = {
        "name": nom,
        "path": f"/dev/{nom}",
        "size": taille_gib * GIB,
        "removable": False,
        "ro": False,
        "rotational": False,
        "tran": "nvme",
        "log_sec": 512,
        "phy_sec": 512,
        "disc_gran": 512,
        "model": "Modèle fictif",
        "boot_medium": False,
        "nvme": None,
    }
    base.update(champs)
    return base


def portable_uefi_amd():
    """Portable UEFI 64 bits, AMD, 16 Gio, NVMe formaté en 4 KiB, et la
    clé de démarrage branchée à côté."""
    return {
        "firmware": {"mode": "uefi", "bits": 64},
        "cpu": {"vendor": "amd", "hypervisor": False},
        "virtual": False,
        "ram_mib": 15800,
        "disks": [
            disque(
                "nvme0n1",
                953,
                nvme={
                    "current": 1,
                    "formats": [
                        {"id": 0, "ds": 9, "rp": 2, "ms": 0},
                        {"id": 1, "ds": 12, "rp": 0, "ms": 0},
                    ],
                },
            ),
            disque(
                "sda",
                1900,
                removable=True,
                tran="usb",
                boot_medium=True,
                rotational=False,
            ),
        ],
        "gpus": [
            {
                "vendor": "amd",
                "vendor_id": "1002",
                "device_id": "0f0f",
                "class": "0300",
                "boot_vga": True,
            }
        ],
        "chassis_type": 10,
        "battery": True,
        "laptop": True,
        "wifi": True,
    }


def poste_bios_intel():
    """Poste fixe BIOS, Intel, 8 Gio, disque SATA rotatif de 2 To et un
    SSD plus petit ; une carte NVIDIA en plus de l'iGPU."""
    return {
        "firmware": {"mode": "bios", "bits": None},
        "cpu": {"vendor": "intel", "hypervisor": False},
        "virtual": False,
        "ram_mib": 7900,
        "disks": [
            disque("sda", 120, tran="sata"),
            disque(
                "sdb",
                1863,
                tran="sata",
                rotational=True,
                disc_gran=0,
                phy_sec=512,
            ),
        ],
        "gpus": [
            {
                "vendor": "intel",
                "vendor_id": "8086",
                "device_id": "0a0a",
                "class": "0300",
                "boot_vga": True,
            },
            {
                "vendor": "nvidia",
                "vendor_id": "10de",
                "device_id": "0b0b",
                "class": "0300",
                "boot_vga": False,
            },
        ],
        "chassis_type": 3,
        "battery": False,
        "laptop": False,
        "wifi": False,
    }


def machine_virtuelle():
    return {
        "firmware": {"mode": "uefi", "bits": 64},
        "cpu": {"vendor": "intel", "hypervisor": True},
        "virtual": True,
        "ram_mib": 4096,
        "disks": [disque("vda", 64, tran=None, rotational=True, disc_gran=0)],
        "gpus": [
            {
                "vendor": "other",
                "vendor_id": "1af4",
                "device_id": "1050",
                "class": "0300",
                "boot_vga": True,
            }
        ],
        "chassis_type": 1,
        "battery": False,
        "laptop": False,
        "wifi": False,
    }


def petit_disque():
    """32 Gio de mémoire sur un disque de 40 Gio : la swap « ram » en
    prendrait 80 %."""
    faits = machine_virtuelle()
    faits["virtual"] = False
    faits["cpu"] = {"vendor": "amd", "hypervisor": False}
    faits["ram_mib"] = 32000
    faits["disks"] = [disque("sda", 40, tran="sata")]
    return faits


def chiffre(**autres):
    profil = {"disk": {"layout": "lvm_on_luks"}}
    return mp.merge(profil, autres)


class Dossiers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prive = os.path.join(self.tmp.name, "prive")
        os.makedirs(self.prive)
        self.dirs = [mp.REPO_DIR, self.prive]

    def ecrire(self, nom, donnees):
        chemin = os.path.join(self.prive, nom + ".json")
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(donnees, fh)
        return chemin


class TestLaFusion(Dossiers):
    def test_merge_is_deep_and_lists_are_replaced(self):
        base = {"a": {"b": 1, "c": [1, 2]}, "d": 4}
        res = mp.merge(base, {"a": {"c": [9]}, "e": None})
        self.assertEqual(res, {"a": {"b": 1, "c": [9]}, "d": 4, "e": None})
        self.assertEqual(base["a"]["c"], [1, 2])

    def test_null_overrides_an_object(self):
        res = mp.merge(
            {"lvm": {"secret_lv": {"size_gib": 8}}},
            {"lvm": {"secret_lv": None}},
        )
        self.assertIsNone(res["lvm"]["secret_lv"])

    def test_extends_chain_last_wins(self):
        self.ecrire(
            "milieu",
            {
                "name": "milieu",
                "extends": "workstation-luks",
                "user": {"shell": "fish"},
            },
        )
        feuille = {
            "name": "feuille",
            "extends": "milieu",
            "system": {"hostname": "poste-zephyrin"},
        }
        res = mp.effective(feuille, self.dirs)
        self.assertEqual(res["user"]["shell"], "fish")
        self.assertEqual(res["disk"]["layout"], "lvm_on_luks")
        self.assertEqual(res["system"]["hostname"], "poste-zephyrin")
        self.assertEqual(res["system"]["timezone"], "ask")
        self.assertEqual(res["name"], "feuille")
        self.assertIsNone(res["extends"])

    def test_a_private_profile_masks_the_repository_one(self):
        self.ecrire("generic", {"name": "generic", "user": {"shell": "fish"}})
        self.assertEqual(
            mp.find("generic", self.dirs),
            os.path.join(self.prive, "generic.json"),
        )

    def test_a_cycle_is_detected(self):
        self.ecrire("un", {"name": "un", "extends": "deux"})
        self.ecrire("deux", {"name": "deux", "extends": "un"})
        with self.assertRaises(mp.ProfileError) as ctx:
            mp.effective({"name": "un", "extends": "deux"}, self.dirs)
        self.assertEqual(ctx.exception.code, "extends-cycle")
        self.assertIn("un → deux → un", ctx.exception.details["chain"])

    def test_self_extension_is_a_cycle(self):
        with self.assertRaises(mp.ProfileError) as ctx:
            mp.effective({"name": "seul", "extends": "seul"}, self.dirs)
        self.assertEqual(ctx.exception.code, "extends-cycle")

    def test_a_missing_parent_is_reported(self):
        with self.assertRaises(mp.ProfileError) as ctx:
            mp.effective({"name": "x", "extends": "introuvable"}, self.dirs)
        self.assertEqual(ctx.exception.code, "extends-missing")

    def test_load_reports_bad_json_and_non_objects(self):
        chemin = os.path.join(self.prive, "casse.json")
        with open(chemin, "w") as fh:
            fh.write("{pas du json")
        with self.assertRaises(mp.ProfileError) as ctx:
            mp.load(chemin)
        self.assertEqual(ctx.exception.code, "json")
        self.ecrire("liste", [1, 2])
        with self.assertRaises(mp.ProfileError) as ctx:
            mp.load(os.path.join(self.prive, "liste.json"))
        self.assertEqual(ctx.exception.code, "not-object")

    def test_list_profiles_reports_origin_and_errors(self):
        self.ecrire("perso", {"name": "perso", "extends": "generic"})
        self.ecrire("mauvais", {"name": "mauvais", "boot": {"timeout": -1}})
        with open(os.path.join(self.prive, "illisible.json"), "w") as fh:
            fh.write("[")
        entrees = {e["name"]: e for e in mp.list_profiles(self.dirs)}
        self.assertEqual(entrees["generic"]["dir"], 0)
        self.assertEqual(entrees["workstation-luks"]["errors"], [])
        self.assertEqual(entrees["perso"]["dir"], 1)
        self.assertEqual(entrees["perso"]["errors"], [])
        self.assertEqual(
            [c for c, _d in entrees["mauvais"]["errors"]], ["size"]
        )
        self.assertEqual(entrees["illisible"]["errors"][0][0], "json")
        self.assertIsNone(entrees["illisible"]["effective"])

    def test_slug_and_dump(self):
        self.assertEqual(mp.slug("Poste Zéphyrin/../x"), "poste-z-phyrin-x")
        self.assertEqual(mp.slug("../.."), "machine")
        texte = mp.dump({"b": 1, "a": [2]})
        self.assertEqual(texte, '{\n  "a": [\n    2\n  ],\n  "b": 1\n}\n')


class TestLesProfilsDuDepot(unittest.TestCase):
    def test_generic_is_the_defaults(self):
        self.assertEqual(
            mp.load(os.path.join(mp.REPO_DIR, "generic.json")), mp.DEFAULTS
        )

    def test_repository_profiles_are_valid_and_canonical(self):
        for nom in ("generic", "workstation-luks"):
            with self.subTest(nom=nom):
                chemin = os.path.join(mp.REPO_DIR, nom + ".json")
                brut = mp.load(chemin)
                self.assertEqual(mp.validate(brut), [])
                complet = mp.effective(brut, [mp.REPO_DIR])
                self.assertEqual(mp.validate(complet), [])
                with open(chemin, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), mp.dump(brut))

    def test_workstation_luks_carries_the_guide_choices(self):
        p = mp.effective(
            mp.load(os.path.join(mp.REPO_DIR, "workstation-luks.json")),
            [mp.REPO_DIR],
        )
        self.assertEqual(p["disk"]["layout"], "lvm_on_luks")
        self.assertEqual(p["disk"]["esp_mib"], 4096)
        self.assertEqual(p["disk"]["luks"]["iter_time_ms"], 3000)
        self.assertEqual(p["disk"]["lvm"]["vg"], "vg0")
        self.assertEqual(p["disk"]["lvm"]["vg_free_mib"], 1024)
        self.assertEqual(
            p["disk"]["lvm"]["secret_lv"], {"size_gib": 8, "optional": True}
        )
        self.assertEqual(p["system"]["kernels"], ["linux", "linux-lts"])
        self.assertTrue(p["system"]["kernel_headers"])
        self.assertTrue(p["system"]["dkms"])
        self.assertTrue(p["system"]["e2scrub"])
        self.assertTrue(p["system"]["zram"]["sysctl_tuning"])
        self.assertEqual(p["user"]["shell"], "zsh")
        self.assertTrue(p["security"]["apparmor"])
        self.assertIn("sshd", p["system"]["services"])
        # Aucune valeur régionale : elles se demandent.
        self.assertEqual(p["system"]["timezone"], "ask")
        self.assertEqual(p["live"]["keymap"], "ask")
        self.assertEqual(p["system"]["locales"], ["en_US.UTF-8"])

    def test_no_deferred_field_exists(self):
        texte = json.dumps(mp.DEFAULTS) + json.dumps(list(mp.FIELDS))
        for mot in ("secure_boot", "tpm2", "580"):
            self.assertNotIn(mot, texte)


class TestLaValidation(unittest.TestCase):
    def codes(self, profil):
        return [c for c, _d in mp.validate(profil)]

    def test_defaults_and_partial_profiles_are_valid(self):
        self.assertEqual(mp.validate(mp.DEFAULTS), [])
        self.assertEqual(mp.validate({"user": {"shell": "zsh"}}), [])

    def test_secret_keys_are_refused_anywhere(self):
        for profil, chemin in (
            ({"user": {"password": "x"}}, "user.password"),
            ({"user": {"password_hash": None}}, "user.password_hash"),
            ({"root_enc_password": "x"}, "root_enc_password"),
            ({"disk": {"luks": {"passphrase": "x"}}}, "disk.luks.passphrase"),
            ({"security": {"secret_key": "x"}}, "security.secret_key"),
            ({"x": {"Hash": "y"}}, "x.Hash"),
        ):
            with self.subTest(chemin=chemin):
                erreurs = mp.validate(profil)
                self.assertIn(("secret", {"path": chemin}), erreurs)
                # Le secret n'est pas AUSSI un champ inconnu.
                self.assertNotIn(
                    "unknown-key",
                    [c for c, d in erreurs if d.get("path") == chemin],
                )

    def test_a_crypt_hash_value_is_refused(self):
        erreurs = mp.validate({"system": {"hostname": "$6$sel$abcdef"}})
        self.assertIn(("secret", {"path": "system.hostname"}), erreurs)

    def test_secret_lv_is_not_a_secret(self):
        self.assertEqual(
            mp.validate(
                {
                    "disk": {
                        "lvm": {"secret_lv": {"size_gib": 8, "optional": True}}
                    }
                }
            ),
            [],
        )
        self.assertEqual(
            self.codes({"disk": {"lvm": {"secret_lv": {"size_gib": 0}}}}),
            ["size"],
        )

    def test_unknown_keys_and_types(self):
        self.assertEqual(
            self.codes({"disk": {"tagret": "auto"}}), ["unknown-key"]
        )
        self.assertEqual(self.codes({"disk": "x"}), ["type"])
        self.assertEqual(self.codes({"boot": {"timeout": "3"}}), ["type"])
        self.assertEqual(self.codes({"boot": {"editor": 0}}), ["type"])
        self.assertEqual(self.codes({"schema": 2}), ["schema"])

    def test_enums(self):
        self.assertEqual(self.codes({"disk": {"layout": "zfs"}}), ["choice"])
        self.assertEqual(
            self.codes({"disk": {"luks": {"sector_size": 1024}}}), ["choice"]
        )
        self.assertEqual(self.codes({"gpu": {"driver": "nvidia"}}), ["choice"])
        self.assertEqual(self.codes({"system": {"kernels": []}}), ["kernels"])
        self.assertEqual(
            self.codes({"system": {"kernels": ["linux", "linux"]}}),
            ["kernels"],
        )
        self.assertEqual(
            self.codes({"system": {"kernels": ["linux-rt"]}}), ["kernels"]
        )
        self.assertEqual(
            mp.validate({"system": {"kernels": list(mp.KERNELS)}}), []
        )

    def test_auto_and_ask_only_where_allowed(self):
        self.assertEqual(mp.validate({"disk": {"target": "ask"}}), [])
        self.assertEqual(mp.validate({"disk": {"layout": "ask"}}), [])
        self.assertEqual(self.codes({"disk": {"layout": "auto"}}), ["special"])
        self.assertEqual(self.codes({"user": {"name": "auto"}}), ["special"])
        self.assertEqual(self.codes({"boot": {"loader": "ask"}}), ["special"])
        self.assertEqual(
            self.codes({"disk": {"esp_mib": "auto"}}), ["special"]
        )

    def test_sizes_are_positive(self):
        self.assertEqual(self.codes({"disk": {"esp_mib": 100}}), ["size"])
        self.assertEqual(
            self.codes({"disk": {"luks": {"iter_time_ms": 0}}}), ["size"]
        )
        self.assertEqual(self.codes({"disk": {"lvm": {"swap": 0}}}), ["size"])
        self.assertEqual(mp.validate({"disk": {"lvm": {"swap": 4}}}), [])
        self.assertEqual(
            mp.validate({"disk": {"lvm": {"vg_free_mib": 0}}}), []
        )

    def test_hostname_rfc1123(self):
        for bon in ("erplibre", "poste-zephyrin", "a1.exemple-interne"):
            self.assertEqual(mp.validate({"system": {"hostname": bon}}), [])
        for mauvais in ("-poste", "poste-", "po_ste", "a" * 64, ""):
            with self.subTest(mauvais=mauvais):
                self.assertEqual(
                    self.codes({"system": {"hostname": mauvais}}), ["hostname"]
                )

    def test_user_names(self):
        self.assertEqual(mp.validate({"user": {"name": "quillon"}}), [])
        for mauvais in ("Quillon", "1abc", "root", "a b", "x" * 33):
            with self.subTest(mauvais=mauvais):
                self.assertEqual(
                    self.codes({"user": {"name": mauvais}}), ["user-name"]
                )

    def test_locales_and_lang(self):
        self.assertEqual(
            mp.validate(
                {
                    "system": {
                        "locales": ["en_US.UTF-8", "fr_FR.UTF-8"],
                        "lang": "fr_FR.UTF-8",
                        "lc_collate": "C",
                    }
                }
            ),
            [],
        )
        self.assertEqual(
            self.codes({"system": {"locales": ["en_US"]}}), ["locale"]
        )
        self.assertEqual(
            self.codes(
                {"system": {"locales": ["en_US.UTF-8"], "lang": "de_DE.UTF-8"}}
            ),
            ["lang-not-in-locales"],
        )

    def test_zram_size_grammar(self):
        for bon in ("4096", "ram / 2", "min(ram / 4, 32768)"):
            self.assertEqual(
                mp.validate({"system": {"zram": {"size": bon}}}), []
            )
        self.assertEqual(
            self.codes({"system": {"zram": {"size": "ram * 2"}}}),
            ["zram-size"],
        )

    def test_hibernation_without_swap(self):
        self.assertEqual(
            self.codes(
                {
                    "disk": {"lvm": {"swap": "none"}},
                    "boot": {"hibernation": True},
                }
            ),
            ["hibernation-without-swap"],
        )

    def test_hibernation_needs_the_lvm_layout(self):
        self.assertEqual(
            self.codes(
                {"disk": {"layout": "plain"}, "boot": {"hibernation": True}}
            ),
            ["hibernation-without-swap"],
        )

    def test_a_secret_volume_needs_a_size_and_luks(self):
        self.assertEqual(
            self.codes({"disk": {"lvm": {"secret_lv": {}}}}), ["required"]
        )
        self.assertEqual(
            self.codes({"disk": {"lvm": {"secret_lv": {"optional": False}}}}),
            ["required"],
        )
        # Un profil qui en étend un autre peut tenir la taille de lui.
        self.assertEqual(
            self.codes(
                {
                    "extends": "workstation-luks",
                    "disk": {"lvm": {"secret_lv": {"optional": False}}},
                }
            ),
            [],
        )
        self.assertEqual(
            self.codes(
                {
                    "disk": {
                        "layout": "plain",
                        "lvm": {"secret_lv": {"size_gib": 8}},
                    }
                }
            ),
            ["secret-lv-needs-luks"],
        )
        # effective() rend un profil sans « extends » : tout y est exigé.
        complet = mp.effective(
            {
                "name": "x",
                "extends": "workstation-luks",
                "disk": {"layout": "plain"},
            },
            [mp.REPO_DIR],
        )
        self.assertIn("secret-lv-needs-luks", self.codes(complet))

    def test_auto_and_ask_are_not_list_items(self):
        for chemin, liste in (
            ("system", {"extra_packages": ["vim", "ask"]}),
            ("system", {"services": ["auto"]}),
            ("desktop", {"apps": ["auto"]}),
        ):
            with self.subTest(liste=liste):
                self.assertEqual(self.codes({chemin: liste}), ["special"])

    def test_details_carry_the_path_and_value(self):
        ((code, det),) = mp.validate({"desktop": {"apps": ["Bad Name"]}})
        self.assertEqual(code, "package")
        self.assertEqual(det["path"], "desktop.apps")
        self.assertEqual(det["item"], "Bad Name")


class TestLaSaisie(unittest.TestCase):
    def test_parse_value_by_kind(self):
        self.assertIs(mp.parse_value("boot.editor", "oui"), True)
        self.assertIs(mp.parse_value("boot.editor", "no"), False)
        self.assertEqual(mp.parse_value("boot.timeout", " 5 "), 5)
        self.assertEqual(
            mp.parse_value("system.kernels", "linux, linux-lts"),
            ["linux", "linux-lts"],
        )
        self.assertEqual(mp.parse_value("desktop.apps", "[]"), [])
        self.assertEqual(mp.parse_value("disk.lvm.swap", "ram"), "ram")
        self.assertEqual(mp.parse_value("disk.lvm.swap", "16"), 16)
        self.assertEqual(
            mp.parse_value("disk.lvm.secret_lv", "8"),
            {"size_gib": 8, "optional": True},
        )
        self.assertIsNone(mp.parse_value("disk.lvm.secret_lv", "null"))
        self.assertEqual(mp.parse_value("disk.target", "AUTO"), "auto")
        self.assertEqual(mp.parse_value("user.name", "ask"), "ask")
        with self.assertRaises(ValueError):
            mp.parse_value("boot.editor", "peut-être")
        with self.assertRaises(ValueError):
            mp.parse_value("boot.timeout", "trois")

    def test_sections_cover_every_field(self):
        couverts = {p for s in mp.SECTIONS for p in mp.section_fields(s)}
        attendus = {
            p for p in mp.FIELDS if not p.startswith("disk.lvm.secret_lv.")
        }
        self.assertEqual(couverts, attendus)


class TestLaResolution(unittest.TestCase):
    def test_uefi_amd_laptop_nvme_4k(self):
        s, questions = mp.resolve(chiffre(), portable_uefi_amd())
        self.assertEqual(s["boot"]["loader"], "systemd-boot")
        self.assertEqual(s["system"]["microcode"], "amd-ucode")
        self.assertEqual(s["disk"]["target"], "/dev/nvme0n1")
        self.assertEqual(s["disk"]["luks"]["sector_size"], 4096)
        self.assertIs(s["disk"]["luks"]["discards"], True)
        # Déjà en 4 KiB : rien à proposer.
        self.assertIs(s["disk"]["nvme_lba_4k"], False)
        self.assertEqual(s["disk"]["lvm"]["swap"], 16)
        self.assertIs(s["boot"]["hibernation"], True)
        self.assertEqual(s["desktop"]["power"], "tlp")
        self.assertEqual(s["gpu"]["driver"], "mesa")
        self.assertIn("vulkan-radeon", s["derived"]["packages"])
        self.assertIn("amd-ucode", s["derived"]["packages"])
        self.assertIn("tlp", s["derived"]["packages"])
        self.assertIn("tlp.service", s["derived"]["services"])
        self.assertIn("lvm2", s["derived"]["packages"])
        self.assertIn("systemd-boot-update.service", s["derived"]["services"])
        self.assertIsNone(s["live"]["mirrors_country"])
        self.assertEqual(s["warnings"], [])
        self.assertEqual(
            questions,
            [
                "live.keymap",
                "system.timezone",
                "system.console_keymap",
                "user.name",
                "security.header_backup",
            ],
        )
        self.assertNotIn(mp.AUTO, json.dumps(s))

    def test_a_512_nvme_with_a_4k_format_is_offered(self):
        faits = portable_uefi_amd()
        faits["disks"][0]["nvme"]["current"] = 0
        faits["disks"][0]["nvme"]["formats"].append(
            {"id": 2, "ds": 12, "rp": 1, "ms": 0}
        )
        s, _q = mp.resolve(chiffre(), faits)
        self.assertEqual(s["disk"]["nvme_lba_4k"], 1)
        self.assertEqual(s["disk"]["luks"]["sector_size"], 512)

    def test_no_format_offered_beside_another_namespace(self):
        # nvme0n2 partage le contrôleur : un formatage pourrait l'effacer.
        faits = portable_uefi_amd()
        faits["disks"][0]["nvme"]["current"] = 0
        faits["disks"][0]["nvme"]["formats"].append(
            {"id": 2, "ds": 12, "rp": 1, "ms": 0}
        )
        faits["disks"].append(disque("nvme0n2", 30))
        s, _q = mp.resolve(chiffre(), faits)
        self.assertIs(s["disk"]["nvme_lba_4k"], False)
        self.assertIn(
            {"code": "nvme-format-shared", "device": "/dev/nvme0n1"},
            s["warnings"],
        )
        # Un autre contrôleur (nvme1n1) n'empêche rien.
        faits["disks"][-1] = disque("nvme1n1", 30)
        s, _q = mp.resolve(chiffre(), faits)
        self.assertEqual(s["disk"]["nvme_lba_4k"], 1)

    def test_unidentified_boot_medium_blocks_the_automatic_choice(self):
        # Live dont le support n'est pas reconnu : « auto » ne choisit
        # rien de lui-même, et la question du disque revient ; une réponse
        # explicite reste possible, la mise en garde l'accompagne.
        faits = portable_uefi_amd()
        faits["boot_medium_unknown"] = True
        s, questions = mp.resolve({}, faits)
        self.assertIsNone(s["disk"]["target"])
        self.assertIn("disk.target", questions)
        self.assertIn({"code": "boot-medium-unknown"}, s["warnings"])
        cible = faits["disks"][0]["path"]
        s, questions = mp.resolve({}, faits, {"disk.target": cible})
        self.assertEqual(s["disk"]["target"], cible)
        self.assertNotIn("disk.target", questions)
        self.assertIn({"code": "boot-medium-unknown"}, s["warnings"])

    def test_bios_intel_desktop_sata_hdd(self):
        profil = chiffre(disk={"target": "/dev/sdb"})
        s, _q = mp.resolve(profil, poste_bios_intel())
        self.assertEqual(s["boot"]["loader"], "grub")
        self.assertEqual(s["system"]["microcode"], "intel-ucode")
        self.assertEqual(s["disk"]["luks"]["sector_size"], 512)
        self.assertIs(s["disk"]["luks"]["discards"], False)
        self.assertEqual(s["desktop"]["power"], "power-profiles-daemon")
        self.assertEqual(s["gpu"]["driver"], "nouveau")
        paquets = s["derived"]["packages"]
        for p in ("vulkan-nouveau", "vulkan-intel", "intel-media-driver"):
            self.assertIn(p, paquets)
        self.assertNotIn("nvidia-open-dkms", paquets)
        self.assertNotIn(
            "systemd-boot-update.service", s["derived"]["services"]
        )

    def test_auto_takes_the_largest_fixed_disk(self):
        s, _q = mp.resolve({}, poste_bios_intel())
        self.assertEqual(s["disk"]["target"], "/dev/sdb")

    def test_vm(self):
        s, _q = mp.resolve({}, machine_virtuelle())
        self.assertEqual(s["system"]["microcode"], "none")
        self.assertNotIn("intel-ucode", s["derived"]["packages"])
        self.assertEqual(s["gpu"]["driver"], "mesa")
        self.assertEqual(s["derived"]["zram_mib"], 1024)
        self.assertIs(s["disk"]["luks"]["discards"], False)

    def test_tiny_disk_caps_swap_and_disables_hibernation(self):
        s, _q = mp.resolve(chiffre(), petit_disque())
        self.assertEqual(s["disk"]["lvm"]["swap"], 10)
        self.assertIs(s["boot"]["hibernation"], False)
        self.assertIn(
            {"code": "swap-capped", "requested": 32, "capped": 10},
            s["warnings"],
        )
        s, _q = mp.resolve(chiffre(boot={"hibernation": True}), petit_disque())
        self.assertIs(s["boot"]["hibernation"], False)
        self.assertIn({"code": "hibernation-off"}, s["warnings"])

    def test_no_eligible_disk_becomes_a_question(self):
        faits = portable_uefi_amd()
        faits["disks"] = [faits["disks"][1]]
        s, questions = mp.resolve({}, faits)
        self.assertIsNone(s["disk"]["target"])
        self.assertIn("disk.target", questions)
        self.assertIn({"code": "no-disk"}, s["warnings"])

    def test_answers_fill_ask_and_secret_lv_is_a_question(self):
        profil = chiffre(
            user={"name": "ask"},
            disk={"lvm": {"secret_lv": {"size_gib": 8, "optional": True}}},
        )
        _s, questions = mp.resolve(profil, portable_uefi_amd())
        self.assertIn("disk.lvm.secret_lv", questions)
        s, questions = mp.resolve(
            profil,
            portable_uefi_amd(),
            answers={"user.name": "quillon", "disk.lvm.secret_lv": False},
        )
        self.assertEqual(s["user"]["name"], "quillon")
        self.assertIsNone(s["disk"]["lvm"]["secret_lv"])
        self.assertNotIn("user.name", questions)
        self.assertNotIn("disk.lvm.secret_lv", questions)

    def test_a_disk_answer_unblocks_an_auto_without_candidate(self):
        faits = portable_uefi_amd()
        faits["disks"] = [disque("sdz", 30, removable=True, tran="usb")]
        s, questions = mp.resolve(
            chiffre(), faits, answers={"disk.target": "/dev/sdz"}
        )
        self.assertEqual(s["disk"]["target"], "/dev/sdz")
        self.assertNotIn("disk.target", questions)
        self.assertEqual(s["derived"]["disk"]["path"], "/dev/sdz")
        self.assertIn(
            {"code": "disk-is-usb", "device": "/dev/sdz"}, s["warnings"]
        )
        s, questions = mp.resolve(
            chiffre(), faits, answers={"disk.target": "sdz"}
        )
        self.assertIsNone(s["disk"]["target"])
        self.assertIn("disk.target", questions)
        self.assertIn("answer-invalid", [a["code"] for a in s["warnings"]])

    def test_a_disk_answer_picks_among_several_candidates(self):
        faits = portable_uefi_amd()
        faits["disks"] = [disque("nvme0n1", 900), disque("sda", 300)]
        s, _q = mp.resolve(chiffre(), faits)
        self.assertEqual(s["disk"]["target"], "/dev/nvme0n1")
        s, questions = mp.resolve(
            chiffre(), faits, answers={"disk.target": "/dev/sda"}
        )
        self.assertEqual(s["derived"]["disk"]["path"], "/dev/sda")
        self.assertNotIn("disk.target", questions)
        self.assertNotIn("no-disk", [a["code"] for a in s["warnings"]])
        s, questions = mp.resolve(
            chiffre(), faits, answers={"disk.target": "sda"}
        )
        self.assertIsNone(s["derived"]["disk"])
        self.assertIn("disk.target", questions)
        self.assertIn("answer-invalid", [a["code"] for a in s["warnings"]])

    def test_auto_never_picks_an_external_or_unusable_disk(self):
        """Chaque disque écarté est plus grand que l'interne retenu : seul
        son filtre l'écarte."""
        ecartes = {
            "usb-rm0": disque("sdb", 2000, tran="usb"),
            "boot-rm0": disque("sdc", 3000, tran="sata", boot_medium=True),
            "ro": disque("sdd", 4000, tran="sata", ro=True),
            "rm": disque("sde", 5000, tran="sata", removable=True),
        }
        interne = disque("nvme0n1", 500)
        for nom, autre in ecartes.items():
            with self.subTest(nom=nom):
                faits = portable_uefi_amd()
                faits["disks"] = [interne, autre]
                s, _q = mp.resolve({}, faits)
                self.assertEqual(s["disk"]["target"], "/dev/nvme0n1")

    def test_a_disk_under_20_gib_is_never_picked(self):
        faits = portable_uefi_amd()
        faits["disks"] = [disque("nvme0n1", 16)]
        s, questions = mp.resolve({}, faits)
        self.assertIsNone(s["disk"]["target"])
        self.assertIn("disk.target", questions)

    def test_discards_need_non_rotational_and_a_granularity(self):
        cas = (
            (dict(rotational=False, disc_gran=512), True),
            (dict(rotational=False, disc_gran=0), False),
            (dict(rotational=True, disc_gran=512), False),
        )
        for champs, attendu in cas:
            with self.subTest(**champs):
                faits = portable_uefi_amd()
                faits["disks"] = [disque("sda", 500, tran="sata", **champs)]
                s, _q = mp.resolve(chiffre(), faits)
                self.assertIs(s["disk"]["luks"]["discards"], attendu)

    def test_grub_target_follows_the_firmware(self):
        cas = (
            ({"mode": "uefi", "bits": 64}, "systemd-boot", None, []),
            (
                {"mode": "uefi", "bits": 32},
                "grub",
                "i386-efi",
                [{"code": "uefi-32bit"}],
            ),
            ({"mode": "bios", "bits": None}, "grub", "i386-pc", []),
        )
        for firmware, chargeur, cible, alertes in cas:
            with self.subTest(firmware=firmware):
                faits = machine_virtuelle()
                faits["firmware"] = firmware
                s, _q = mp.resolve({}, faits)
                self.assertEqual(s["boot"]["loader"], chargeur)
                self.assertEqual(s["derived"]["grub_target"], cible)
                self.assertEqual(s["warnings"], alertes)
        faits = machine_virtuelle()
        s, _q = mp.resolve({"boot": {"loader": "grub"}}, faits)
        self.assertEqual(s["derived"]["grub_target"], "x86_64-efi")

    def test_plain_layout_has_no_swap_nor_hibernation(self):
        s, _q = mp.resolve({}, portable_uefi_amd())
        self.assertEqual(s["derived"]["swap_gib"], 0)
        self.assertIs(s["boot"]["hibernation"], False)
        s, _q = mp.resolve(
            {"boot": {"hibernation": True}}, portable_uefi_amd()
        )
        self.assertIs(s["boot"]["hibernation"], False)
        self.assertIn({"code": "hibernation-needs-lvm"}, s["warnings"])

    def test_unknown_memory_gives_no_swap_and_a_warning(self):
        faits = portable_uefi_amd()
        faits["ram_mib"] = 0
        s, _q = mp.resolve(chiffre(), faits)
        self.assertEqual(s["derived"]["swap_gib"], 0)
        self.assertIs(s["boot"]["hibernation"], False)
        self.assertIn({"code": "ram-unknown"}, s["warnings"])

    def test_unknown_disk_falls_back_and_warns(self):
        s, questions = mp.resolve(
            chiffre(disk={"target": "ask"}), portable_uefi_amd()
        )
        self.assertIn("disk.target", questions)
        self.assertEqual(s["disk"]["luks"]["sector_size"], 512)
        self.assertIs(s["disk"]["luks"]["discards"], False)
        self.assertIn({"code": "disk-unknown"}, s["warnings"])

    def test_literal_values_are_kept(self):
        profil = {
            "boot": {"loader": "systemd-boot"},
            "system": {"microcode": "none"},
            "desktop": {"power": "none"},
        }
        s, _q = mp.resolve(profil, poste_bios_intel())
        self.assertEqual(s["system"]["microcode"], "none")
        self.assertEqual(s["desktop"]["power"], "none")
        self.assertIn({"code": "loader-needs-uefi"}, s["warnings"])

    def test_nvidia_open_pulls_headers_and_dkms(self):
        s, _q = mp.resolve(
            {"gpu": {"driver": "nvidia-open"}}, poste_bios_intel()
        )
        paquets = s["derived"]["packages"]
        for p in ("nvidia-open-dkms", "linux-headers", "dkms"):
            self.assertIn(p, paquets)

    def test_answers_are_checked_like_the_field(self):
        profil = {"user": {"name": "ask"}, "system": {"hostname": "ask"}}
        s, questions = mp.resolve(
            profil,
            machine_virtuelle(),
            answers={"user.name": "root", "system.hostname": "ask"},
        )
        self.assertEqual(s["user"]["name"], "ask")
        self.assertIn("user.name", questions)
        self.assertIn("system.hostname", questions)
        codes = {
            (a["path"], a["reason"])
            for a in s["warnings"]
            if a["code"] == "answer-invalid"
        }
        self.assertEqual(
            codes,
            {("user.name", "user-name"), ("system.hostname", "special")},
        )

    def test_explicit_large_swap_is_kept_with_a_warning(self):
        s, _q = mp.resolve(
            chiffre(disk={"lvm": {"swap": 500}}), machine_virtuelle()
        )
        self.assertEqual(s["derived"]["swap_gib"], 500)
        self.assertIn(
            {"code": "swap-large", "swap": 500, "disk": 64}, s["warnings"]
        )
        s, _q = mp.resolve(
            chiffre(disk={"lvm": {"swap": 8}}), machine_virtuelle()
        )
        self.assertEqual(s["warnings"], [])

    def test_an_nvidia_driver_without_an_nvidia_card_warns(self):
        for pilote in ("nvidia-open", "nouveau"):
            with self.subTest(pilote=pilote):
                s, _q = mp.resolve(
                    {"gpu": {"driver": pilote}}, portable_uefi_amd()
                )
                self.assertIn(
                    {"code": "gpu-no-nvidia", "driver": pilote},
                    s["warnings"],
                )
        s, _q = mp.resolve({}, poste_bios_intel())
        self.assertNotIn("gpu-no-nvidia", [a["code"] for a in s["warnings"]])

    def test_zram_expression(self):
        self.assertEqual(mp.zram_mib("min(ram / 4, 32768)", 262144), 32768)
        self.assertEqual(mp.zram_mib("min(ram / 4, 32768)", 16000), 4000)
        self.assertEqual(mp.zram_mib("ram / 2", 8000), 4000)
        self.assertEqual(mp.zram_mib("2048", 8000), 2048)
        self.assertIsNone(mp.zram_mib("ram * 2", 8000))


class TestLeResume(unittest.TestCase):
    def test_labels_are_stable_keys(self):
        s, _q = mp.resolve(chiffre(), portable_uefi_amd())
        lignes = mp.plan_summary(s)
        for libelle, valeur in lignes:
            self.assertIn(libelle, mp.SUMMARY_LABELS)
            self.assertIsInstance(valeur, str)
        resume = dict(lignes)
        self.assertEqual(resume["Target disk"], "/dev/nvme0n1 (953 GiB)")
        self.assertEqual(resume["LUKS sector size"], "4096")
        self.assertEqual(resume["Swap"], "16 GiB")
        self.assertEqual(resume["Hibernation"], "yes")
        self.assertEqual(resume["User"], "ask")

    def test_a_raw_profile_shows_auto(self):
        resume = dict(mp.plan_summary(mp.DEFAULTS))
        self.assertEqual(resume["Target disk"], "auto")
        self.assertEqual(resume["Boot loader"], "auto")
        self.assertNotIn("LUKS sector size", resume)

    def test_long_package_lists_are_shortened(self):
        apps = [f"paquet{i}" for i in range(10)]
        resume = dict(mp.plan_summary({"desktop": {"apps": apps}}))
        self.assertTrue(resume["Extra packages"].startswith("10: paquet0"))


if __name__ == "__main__":
    unittest.main()
