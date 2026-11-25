#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Greffon ERPLibre pour archinstall (erplibre_plugin) : constructeurs purs
(HOOKS, ligne noyau, systemd-boot, GRUB, fstab, locales, zram, premier
démarrage) et accroches jouées sur une fausse installation dont la cible
est un dossier temporaire. archinstall n'est pas requis ; les UUID, noms
et réglages sont INVENTÉS.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from test import iso_installer_modules as m

mp, _facts, _dk, _ai, pl, _ei = m.load()

DISK_LUKS = {
    "disk": "/dev/nvme0n1",
    "vg": "vgtest",
    "luks_uuid": "11111111-2222-3333-4444-555555555555",
    "root_uuid": "66666666-7777-8888-9999-aaaaaaaaaaaa",
    "swap_uuid": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
    "swap_dev": "/dev/vgtest/swap",
    "secret_luks_uuid": "12121212-3434-5656-7878-909090909090",
}
DISK_PLAIN = {
    "disk": "/dev/sda",
    "vg": None,
    "luks_uuid": None,
    "root_uuid": "abababab-cdcd-efef-0101-232323232323",
    "swap_uuid": None,
    "swap_dev": None,
    "secret_luks_uuid": None,
}


def resolved(profile, fx, answers=None):
    settings, questions = mp.resolve(profile, fx, answers or {})
    assert not questions, questions
    return settings


def luks_settings(**changes):
    profil = m.luks_profile()
    for chemin, valeur in changes.items():
        mp.put(profil, chemin, valeur)
    return resolved(profil, m.uefi_laptop())


class TestVersion(unittest.TestCase):
    def test_accepts_the_supported_major_minor_only(self):
        for ok in ("4.5", "4.5.1", "4.5-1", " 4.5.0"):
            self.assertTrue(pl.version_ok(ok), ok)
        for refuse in ("4.4", "4.6", "5.5", "", None, "inconnue"):
            self.assertFalse(pl.version_ok(refuse), refuse)
        self.assertEqual(pl.__archinstall__version__, 4.5)

    def test_plugin_refuses_another_archinstall(self):
        with self.assertRaises(SystemExit) as ctx:
            pl.Plugin(state={"settings": {}}, version="4.6")
        self.assertIn("4.6", str(ctx.exception))

    def test_plugin_refuses_without_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[pl.STATE_ENV] = os.path.join(tmp, "absent.json")
            try:
                with self.assertRaises(SystemExit):
                    pl.Plugin(version="4.5")
            finally:
                del os.environ[pl.STATE_ENV]

    def test_system_exit_escapes_archinstall_plugin_loader(self):
        # load_plugin d'archinstall 4.5 n'attrape que Exception autour de
        # Plugin() : SystemExit arrête l'installation au lieu de la laisser
        # continuer sans greffon.
        self.assertFalse(issubclass(SystemExit, Exception))


class TestHooks(unittest.TestCase):
    def test_luks_hooks(self):
        self.assertEqual(
            pl.mkinitcpio_hooks(luks_settings()),
            [
                "base",
                "systemd",
                "autodetect",
                "microcode",
                "modconf",
                "kms",
                "keyboard",
                "sd-vconsole",
                "block",
                "sd-encrypt",
                "lvm2",
                "filesystems",
                "fsck",
            ],
        )

    def test_plain_hooks_have_no_encrypt(self):
        hooks = pl.mkinitcpio_hooks(
            resolved(m.plain_profile(), m.uefi_laptop())
        )
        self.assertNotIn("sd-encrypt", hooks)
        self.assertNotIn("lvm2", hooks)
        self.assertIn("sd-vconsole", hooks)

    def test_nvidia_open_drops_kms(self):
        self.assertNotIn(
            "kms",
            pl.mkinitcpio_hooks(
                luks_settings(**{"gpu.driver": "nvidia-open"})
            ),
        )

    def test_edit_mkinitcpio_conf(self):
        texte = (
            "MODULES=()\n# HOOKS=(commentaire)\n"
            "HOOKS=(base udev)\nCOMPRESSION=zstd\n"
        )
        out = pl.edit_mkinitcpio_conf(texte, ["base", "systemd"])
        self.assertIn("\nHOOKS=(base systemd)\n", out)
        self.assertIn("# HOOKS=(commentaire)", out)
        self.assertTrue(out.endswith("COMPRESSION=zstd\n"))
        self.assertEqual(
            pl.edit_mkinitcpio_conf("", ["base"]), "\nHOOKS=(base)\n"
        )

    def test_vconsole(self):
        self.assertEqual(pl.vconsole_conf("cf"), "KEYMAP=cf\n")
        # FONT= et XKBLAYOUT= posés avant le greffon restent.
        texte = "KEYMAP=us\nFONT=ter-v16n\nXKBLAYOUT=ca\n"
        self.assertEqual(
            pl.vconsole_conf("cf", texte),
            "KEYMAP=cf\nFONT=ter-v16n\nXKBLAYOUT=ca\n",
        )
        self.assertEqual(
            pl.vconsole_conf("cf", "FONT=ter-v16n"),
            "FONT=ter-v16n\nKEYMAP=cf\n",
        )


class TestKernelOptions(unittest.TestCase):
    def test_luks_with_hibernation_and_zram(self):
        s = luks_settings(**{"boot.hibernation": True, "disk.lvm.swap": 16})
        self.assertTrue(mp.get(s, "boot.hibernation"))
        self.assertEqual(
            pl.kernel_options(s, DISK_LUKS),
            [
                f"rd.luks.name={DISK_LUKS['luks_uuid']}=cryptlvm",
                "root=/dev/vgtest/root",
                "resume=/dev/vgtest/swap",
                "rw",
                "zswap.enabled=0",
            ],
        )

    def test_no_resume_without_hibernation(self):
        s = luks_settings(**{"boot.hibernation": False})
        self.assertFalse(
            any(
                o.startswith("resume=")
                for o in pl.kernel_options(s, DISK_LUKS)
            )
        )

    def test_plain_uses_root_uuid_and_apparmor(self):
        profil = m.plain_profile()
        profil["security"]["apparmor"] = True
        profil["system"]["zram"] = {"enabled": False}
        s = resolved(profil, m.uefi_laptop())
        self.assertEqual(
            pl.kernel_options(s, DISK_PLAIN),
            [
                f"root=UUID={DISK_PLAIN['root_uuid']}",
                "rw",
                f"lsm={pl.APPARMOR_LSM}",
            ],
        )


class TestBootFiles(unittest.TestCase):
    def test_loader_conf(self):
        self.assertEqual(
            pl.loader_conf("erplibre-linux.conf", 3, False),
            "default erplibre-linux.conf\ntimeout 3\n"
            "console-mode max\neditor no\n",
        )
        self.assertIn("editor yes", pl.loader_conf("x", 0, True))

    def test_loader_entries(self):
        normal = pl.loader_entry("linux-lts", ["root=/dev/vg/root", "rw"])
        self.assertEqual(
            normal,
            "title   Arch Linux (linux-lts)\n"
            "linux   /vmlinuz-linux-lts\n"
            "initrd  /initramfs-linux-lts.img\n"
            "options root=/dev/vg/root rw\n",
        )
        secours = pl.loader_entry("linux", ["rw"], fallback=True)
        self.assertIn("initrd  /initramfs-linux-fallback.img", secours)
        self.assertEqual(
            pl.entry_name("linux", True), "erplibre-linux-fallback.conf"
        )

    def test_uki_preset(self):
        texte = pl.uki_preset("linux")
        self.assertIn('default_uki="/boot/EFI/Linux/arch-linux.efi"', texte)
        self.assertIn(
            'fallback_uki="/boot/EFI/Linux/arch-linux-fallback.efi"', texte
        )
        self.assertNotIn("default_image", texte)

    def test_image_preset_builds_the_fallback(self):
        texte = pl.image_preset("linux-lts")
        self.assertIn("PRESETS=('default' 'fallback')", texte)
        self.assertIn(
            'fallback_image="/boot/initramfs-linux-lts-fallback.img"', texte
        )
        self.assertIn('fallback_options="-S autodetect"', texte)

    def test_grub_default_edit(self):
        texte = (
            "GRUB_DEFAULT=0\nGRUB_TIMEOUT=5\n"
            'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n'
            'GRUB_CMDLINE_LINUX=""\n'
        )
        out = pl.edit_grub_default(texte, ["root=/dev/vg/root", "rw"], 2)
        self.assertIn('GRUB_CMDLINE_LINUX="root=/dev/vg/root rw"\n', out)
        self.assertIn("GRUB_TIMEOUT=2\n", out)
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="quiet"', out)
        vide = pl.edit_grub_default("", ["rw"], 1)
        self.assertIn('GRUB_CMDLINE_LINUX="rw"', vide)

    def test_grub_efi_falls_back_to_the_removable_path(self):
        efi = {"derived": {"grub_target": "x86_64-efi"}}
        essais = pl.grub_install_attempts(efi, {"disk": "/dev/sda"})
        self.assertEqual(len(essais), 2)
        self.assertEqual(essais[1][: len(essais[0])], essais[0])
        self.assertEqual(
            essais[1][len(essais[0]) :], ["--removable", "--no-nvram"]
        )
        bios = {"derived": {"grub_target": "i386-pc"}}
        self.assertEqual(
            pl.grub_install_attempts(bios, {"disk": "/dev/sda"}),
            [["grub-install", "--target=i386-pc", "/dev/sda"]],
        )

    def test_grub_install_targets(self):
        bios = resolved(m.luks_profile(), m.bios_desktop())
        self.assertEqual(
            pl.grub_install_argv(bios, {"disk": "/dev/sda"}),
            ["grub-install", "--target=i386-pc", "/dev/sda"],
        )
        efi = {"derived": {"grub_target": "x86_64-efi"}}
        self.assertEqual(
            pl.grub_install_argv(efi, {"disk": "/dev/sda"}),
            [
                "grub-install",
                "--target=x86_64-efi",
                "--efi-directory=/boot",
                "--bootloader-id=GRUB",
            ],
        )


class TestSystemFiles(unittest.TestCase):
    def test_fstab_swap(self):
        avec = "UUID=a / ext4 rw 0 1\nUUID=b none swap defaults 0 0\n"
        self.assertEqual(pl.fstab_with_swap(avec, "c", "/dev/vg/swap"), avec)
        sans = "UUID=a / ext4 rw 0 1\n# UUID=z none swap defaults 0 0\n"
        self.assertTrue(
            pl.fstab_with_swap(sans, "c", "/dev/vg/swap").endswith(
                "UUID=c none swap defaults 0 0\n"
            )
        )
        self.assertIn(
            "/dev/vg/swap none swap",
            pl.fstab_with_swap(sans, None, "/dev/vg/swap"),
        )

    def test_enable_locales(self):
        texte = "#en_US.UTF-8 UTF-8\n#fr_CA.UTF-8 UTF-8\n#fr_CA ISO-8859-1\n"
        out = pl.enable_locales(
            texte, ["en_US.UTF-8", "fr_CA.UTF-8", "xx_YY.UTF-8"]
        )
        lignes = out.splitlines()
        self.assertIn("en_US.UTF-8 UTF-8", lignes)
        self.assertIn("fr_CA.UTF-8 UTF-8", lignes)
        self.assertIn("#fr_CA ISO-8859-1", lignes)
        self.assertEqual(lignes[-1], "xx_YY.UTF-8 UTF-8")

    def test_locale_conf(self):
        self.assertEqual(pl.locale_conf("fr_CA.UTF-8"), "LANG=fr_CA.UTF-8\n")
        self.assertEqual(
            pl.locale_conf("fr_CA.UTF-8", "C"),
            "LANG=fr_CA.UTF-8\nLC_COLLATE=C\n",
        )

    def test_small_files(self):
        self.assertEqual(
            pl.zram_conf("min(ram / 4, 32768)", "zstd"),
            "[zram0]\nzram-size = min(ram / 4, 32768)\n"
            "compression-algorithm = zstd\n",
        )
        self.assertIn("vm.swappiness = 180\n", pl.zram_sysctl())
        self.assertEqual(pl.e2scrub_conf(1024), "snap_size_mb=1024\n")
        self.assertEqual(
            pl.crypttab_secret("u-1"),
            "erplibre-secret UUID=u-1 none luks,noauto\n",
        )
        self.assertIn("-march=native", pl.makepkg_native_conf())

    def test_firstboot(self):
        script = pl.firstboot_script("camille", "yay")
        self.assertIn("aur.archlinux.org/yay-bin.git", script)
        self.assertIn("runuser -u camille -- makepkg", script)
        self.assertIn(f"trap 'rm -f {pl.FIRSTBOOT_SUDOERS}' EXIT", script)
        self.assertIn(f"systemctl disable {pl.FIRSTBOOT_UNIT}", script)
        unite = pl.firstboot_unit()
        self.assertIn(f"ConditionPathExists=!{pl.FIRSTBOOT_DONE}", unite)
        self.assertIn("After=network-online.target", unite)

    def test_early_packages(self):
        self.assertEqual(
            pl.early_packages(luks_settings()),
            ["e2fsprogs", "dosfstools", "lvm2", "cryptsetup"],
        )
        plain = resolved(m.plain_profile(), m.uefi_laptop())
        mp.put(plain, "disk.lvm.root_fs", "xfs")
        self.assertEqual(
            pl.early_packages(plain), ["e2fsprogs", "dosfstools", "xfsprogs"]
        )


class FakePacman:
    def __init__(self, journal):
        self.journal = journal

    def strap(self, packages):
        self.journal.append(("strap", list(packages)))


class FakeInstallation:
    """Ce que le greffon lit d'archinstall.Installer : target, kernels,
    pacman.strap, arch_chroot (chaîne de commande), enable_service,
    _helper_flags. `fail` fait échouer les commandes qui commencent ainsi."""

    def __init__(self, target, kernels=("linux",), fail=()):
        self.target = Path(target)
        self.kernels = list(kernels)
        self.journal = []
        self.pacman = FakePacman(self.journal)
        self._helper_flags = {"base": False, "bootloader": None}
        self.fail = fail

    def arch_chroot(self, cmd):
        self.journal.append(("chroot", cmd))
        if any(cmd.startswith(f) for f in self.fail):
            raise RuntimeError(f"failed: {cmd}")
        return ""

    def enable_service(self, service):
        self.journal.append(("enable", service))

    def chroots(self):
        return [c for k, c in self.journal if k == "chroot"]


class TestPluginRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / "cible"
        (self.target / "etc").mkdir(parents=True)
        (self.target / "boot").mkdir()
        (self.target / "etc/mkinitcpio.conf").write_text(
            "MODULES=()\nHOOKS=(base udev)\n"
        )
        (self.target / "etc/locale.gen").write_text("#en_US.UTF-8 UTF-8\n")
        (self.target / "etc/default").mkdir()
        (self.target / "etc/default/grub").write_text(
            'GRUB_CMDLINE_LINUX=""\nGRUB_TIMEOUT=5\n'
        )
        self.status = self.root / "status.json"

    def plugin(self, settings, disk=DISK_LUKS, **extra):
        etat = {
            "settings": settings,
            "facts": {"ram_mib": 15800},
            "disk": disk,
            "keymap": "cf",
            "status_path": str(self.status),
            "log_path": str(self.root / "log" / "plugin.log"),
        }
        etat.update(extra)
        return pl.Plugin(state=etat, version="4.5.1", echo=False)

    def test_on_pacstrap_only_extends_the_base_strap(self):
        p = self.plugin(luks_settings())
        self.assertEqual(
            p.on_pacstrap(["base", "sudo", "linux"]),
            [
                "base",
                "sudo",
                "linux",
                "e2fsprogs",
                "dosfstools",
                "lvm2",
                "cryptsetup",
            ],
        )
        self.assertIsNone(p.on_pacstrap(["base", "gnome"]))
        p2 = self.plugin(luks_settings())
        self.assertIsNone(p2.on_pacstrap(["gnome"]))

    def test_on_mkinitcpio_writes_hooks_and_vconsole(self):
        inst = FakeInstallation(self.target)
        p = self.plugin(luks_settings())
        self.assertIs(p.on_mkinitcpio(inst), True)
        conf = (self.target / "etc/mkinitcpio.conf").read_text()
        self.assertIn("HOOKS=(base systemd autodetect", conf)
        self.assertIn("sd-encrypt lvm2 filesystems fsck)", conf)
        self.assertEqual(
            (self.target / "etc/vconsole.conf").read_text(), "KEYMAP=cf\n"
        )
        self.assertEqual(inst.chroots(), ["mkinitcpio -P"])
        # La police posée avant le greffon survit à un second passage.
        (self.target / "etc/vconsole.conf").write_text(
            "KEYMAP=us\nFONT=ter-v16n\n"
        )
        self.plugin(luks_settings()).on_mkinitcpio(inst)
        self.assertEqual(
            (self.target / "etc/vconsole.conf").read_text(),
            "KEYMAP=cf\nFONT=ter-v16n\n",
        )
        self.assertEqual(
            (self.target / "etc/mkinitcpio.d/linux.preset").read_text(),
            pl.image_preset("linux"),
        )
        self.assertEqual(
            json.loads(self.status.read_text())["on_mkinitcpio"]["ok"], True
        )

    def test_on_mkinitcpio_failure_is_recorded_and_raised(self):
        inst = FakeInstallation(self.target, fail=("mkinitcpio",))
        p = self.plugin(luks_settings())
        with self.assertRaises(RuntimeError):
            p.on_mkinitcpio(inst)
        self.assertFalse(
            json.loads(self.status.read_text())["on_mkinitcpio"]["ok"]
        )

    def test_uki_writes_cmdline_and_presets(self):
        s = luks_settings(**{"boot.uki": True})
        inst = FakeInstallation(self.target, kernels=("linux", "linux-lts"))
        self.plugin(s).on_mkinitcpio(inst)
        cmdline = (self.target / "etc/kernel/cmdline").read_text()
        self.assertTrue(
            cmdline.startswith(
                f"rd.luks.name={DISK_LUKS['luks_uuid']}=cryptlvm "
            )
        )
        self.assertTrue(
            (self.target / "etc/mkinitcpio.d/linux-lts.preset").is_file()
        )
        self.assertTrue((self.target / "boot/EFI/Linux").is_dir())

    def test_systemd_boot_entries_and_fallback_only_if_image(self):
        (self.target / "boot/initramfs-linux-fallback.img").write_bytes(b"\0")
        inst = FakeInstallation(self.target, kernels=("linux", "linux-lts"))
        s = luks_settings()
        self.assertEqual(mp.get(s, "boot.loader"), "systemd-boot")
        self.assertIs(self.plugin(s).on_add_bootloader(inst), True)
        entrees = sorted(os.listdir(self.target / "boot/loader/entries"))
        self.assertEqual(
            entrees,
            [
                "erplibre-linux-fallback.conf",
                "erplibre-linux-lts.conf",
                "erplibre-linux.conf",
            ],
        )
        loader = (self.target / "boot/loader/loader.conf").read_text()
        self.assertEqual(
            loader, pl.loader_conf("erplibre-linux.conf", 3, False)
        )
        self.assertEqual(
            inst.chroots(),
            ["bootctl --variables=yes --esp-path=/boot install"],
        )
        self.assertIn(("enable", "systemd-boot-update.service"), inst.journal)
        self.assertEqual(
            inst._helper_flags["bootloader"], "erplibre-systemd-boot"
        )

    def test_bootctl_falls_back_without_efi_variables(self):
        inst = FakeInstallation(self.target, fail=("bootctl --variables=yes",))
        self.plugin(luks_settings()).on_add_bootloader(inst)
        self.assertEqual(
            inst.chroots(),
            [
                "bootctl --variables=yes --esp-path=/boot install",
                "bootctl --variables=no --esp-path=/boot install",
            ],
        )

    def test_uki_loader_defaults_to_the_uki(self):
        inst = FakeInstallation(self.target)
        self.plugin(luks_settings(**{"boot.uki": True})).on_add_bootloader(
            inst
        )
        self.assertFalse((self.target / "boot/loader/entries").exists())
        self.assertIn(
            "default arch-linux.efi\n",
            (self.target / "boot/loader/loader.conf").read_text(),
        )

    def test_grub_in_bios(self):
        s = resolved(m.luks_profile(), m.bios_desktop())
        inst = FakeInstallation(self.target)
        self.plugin(
            s, disk=dict(DISK_LUKS, disk="/dev/sda")
        ).on_add_bootloader(inst)
        self.assertIn(("strap", ["grub"]), inst.journal)
        self.assertEqual(
            inst.chroots(),
            [
                "grub-install --target=i386-pc /dev/sda",
                "grub-mkconfig -o /boot/grub/grub.cfg",
            ],
        )
        grub = (self.target / "etc/default/grub").read_text()
        self.assertIn(
            'GRUB_CMDLINE_LINUX="rd.luks.name='
            f"{DISK_LUKS['luks_uuid']}=cryptlvm",
            grub,
        )
        self.assertIn("GRUB_TIMEOUT=3", grub)
        # grub-mkconfig écrit root= et rw lui-même : jamais deux fois.
        ligne = next(
            x for x in grub.splitlines() if x.startswith("GRUB_CMDLINE_LINUX=")
        )
        self.assertNotIn("root=", ligne)
        self.assertNotIn(" rw", ligne)

    def test_grub_efi_retries_without_nvram(self):
        # efibootmgr refusé dans le chroot : le second essai pose le chemin
        # de repli EFI/BOOT sans toucher la NVRAM, puis grub-mkconfig.
        s = {
            "boot": {"loader": "grub", "timeout": 3},
            "derived": {"grub_target": "x86_64-efi"},
            "disk": {"layout": "plain"},
        }

        class Nvram(FakeInstallation):
            def arch_chroot(self, cmd):
                if cmd.startswith("grub-install") and "--removable" not in cmd:
                    self.journal.append(("chroot", cmd))
                    raise RuntimeError("efibootmgr failed")
                return super().arch_chroot(cmd)

        inst = Nvram(self.target)
        self.plugin(
            s, disk=dict(DISK_LUKS, disk="/dev/sda")
        ).on_add_bootloader(inst)
        chroots = inst.chroots()
        self.assertEqual(len(chroots), 3)
        self.assertTrue(chroots[1].endswith("--removable --no-nvram"))
        self.assertEqual(chroots[2], "grub-mkconfig -o /boot/grub/grub.cfg")

    def test_grub_cmdline_drops_root_and_rw(self):
        self.assertEqual(
            pl.grub_cmdline(
                ["root=UUID=abcd", "rw", "zswap.enabled=0", "lsm=x"]
            ),
            ["zswap.enabled=0", "lsm=x"],
        )
        self.assertEqual(
            pl.grub_cmdline(["rd.luks.name=u=cryptlvm", "root=/dev/vg/root"]),
            ["rd.luks.name=u=cryptlvm"],
        )

    def test_on_genfstab_adds_swap_once(self):
        (self.target / "etc/fstab").write_text("UUID=r / ext4 rw 0 1\n")
        p = self.plugin(luks_settings())
        inst = FakeInstallation(self.target)
        p.on_genfstab(inst)
        p.on_genfstab(inst)
        fstab = (self.target / "etc/fstab").read_text()
        self.assertEqual(fstab.count(" swap "), 1)
        self.assertIn(f"UUID={DISK_LUKS['swap_uuid']} none swap", fstab)

    def test_on_user_created_sets_the_shell(self):
        s = luks_settings(**{"user.shell": "zsh"})
        inst = FakeInstallation(self.target)
        p = self.plugin(s)

        class User:
            username = "camille"

        class Autre:
            username = "autre"

        p.on_user_created(inst, Autre())
        self.assertEqual(inst.journal, [])
        p.on_user_created(inst, User())
        self.assertEqual(
            inst.journal,
            [
                ("strap", ["zsh"]),
                ("chroot", "usermod --shell /usr/bin/zsh camille"),
            ],
        )

    def test_on_install_writes_system_files(self):
        s = luks_settings(
            **{
                "system.locales": ["en_US.UTF-8", "fr_CA.UTF-8"],
                "system.lang": "fr_CA.UTF-8",
                "system.lc_collate": "C",
                "system.e2scrub": True,
                "system.zram.sysctl_tuning": True,
                "firstboot.aur_helper": "paru",
                "firstboot.makepkg_native": True,
            }
        )
        inst = FakeInstallation(self.target, fail=("hwclock",))
        self.plugin(s, root_policy="lock").on_install(inst)
        t = self.target
        self.assertIn(
            "fr_CA.UTF-8 UTF-8",
            (t / "etc/locale.gen").read_text().splitlines(),
        )
        self.assertEqual(
            (t / "etc/locale.conf").read_text(),
            "LANG=fr_CA.UTF-8\nLC_COLLATE=C\n",
        )
        self.assertIn(
            "zram-size = min(ram / 4, 32768)",
            (t / "etc/systemd/zram-generator.conf").read_text(),
        )
        self.assertTrue((t / "etc/sysctl.d/99-zram.conf").is_file())
        self.assertEqual(
            (t / "etc/e2scrub.conf").read_text(), "snap_size_mb=512\n"
        )
        self.assertIn(
            DISK_LUKS["secret_luks_uuid"], (t / "etc/crypttab").read_text()
        )
        self.assertEqual(os.stat(t / "etc/crypttab").st_mode & 0o777, 0o600)
        self.assertTrue(
            (t / "etc/makepkg.conf.d/erplibre-native.conf").is_file()
        )
        script = t / pl.FIRSTBOOT_SCRIPT.lstrip("/")
        self.assertEqual(os.stat(script).st_mode & 0o777, 0o755)
        self.assertIn(("enable", pl.FIRSTBOOT_UNIT), inst.journal)
        self.assertIn(("strap", ["zram-generator"]), inst.journal)
        chroots = inst.chroots()
        self.assertEqual(chroots[0], "locale-gen")
        # hwclock échoue dans ce faux chroot : ignoré, la suite a lieu.
        self.assertIn("usermod --lock root", chroots)
        reglages = json.loads(
            (t / "var/lib/erplibre-install/settings.json").read_text()
        )
        self.assertEqual(reglages["user"]["name"], "camille")
        self.assertTrue((t / "var/lib/erplibre-install/facts.json").is_file())
        self.assertTrue(
            json.loads(self.status.read_text())["on_install"]["ok"]
        )

    def test_on_install_password_policy_does_not_lock_root(self):
        inst = FakeInstallation(self.target)
        self.plugin(luks_settings(), root_policy="password").on_install(inst)
        self.assertNotIn("usermod --lock root", inst.chroots())

    def test_settings_copied_to_target_carry_no_secret(self):
        s = luks_settings()
        self.assertEqual(mp._secrets(s), [])


if __name__ == "__main__":
    unittest.main()
