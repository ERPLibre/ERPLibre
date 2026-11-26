#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""ISO ERPLibre Arch Linux : construction et installateur, sans mkarchiso.

Couvre script/iso/archlinux/build_iso.py (édition du profil releng, plan,
profils ERPLibre tirés de la table QEMU) et les scripts embarqués dans
l'ISO : erplibre-install-config (configuration archinstall, choix du
disque), erplibre-install et erplibre-stage.sh (syntaxe bash, fonctions
sourcées avec systemctl bouchonné).

Le profil releng utilisé ici est une miniature inventée qui a la forme de
celui d'archiso ; les sorties lsblk sont inventées elles aussi."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from script.iso.archlinux import build_iso
from script.todo import todo_i18n
from script.todo.qemu_install import QemuInstallMixin

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "script/iso/archlinux/profile"
AIROOTFS = OVERLAY / "airootfs"
SHARE = AIROOTFS / "usr/local/share/erplibre-install"
CONFIG_TOOL = AIROOTFS / "usr/local/bin/erplibre-install-config"
INSTALLER = AIROOTFS / "usr/local/bin/erplibre-install"
UI_LAUNCHER = AIROOTFS / "usr/local/bin/erplibre-installer-ui"
TODO_LAUNCHER = AIROOTFS / "usr/local/bin/erplibre-todo"
STAGE = SHARE / "erplibre-stage.sh"
TEMPLATE = SHARE / "user_configuration.template.json"
MONITOR = ROOT / "script/todo/qemu_install_monitor.py"
BASH = shutil.which("bash")

GIB = 1024**3

FAKE_PROFILEDEF = """#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="exemple"
iso_label="EXEMPLE_$(date +%Y%m)"
iso_publisher="Exemple <https://exemple.invalid>"
iso_application="Exemple Live"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
)
"""

FAKE_SYSLINUX_SYS = """INCLUDE archiso_head.cfg

DEFAULT arch
TIMEOUT 150

INCLUDE archiso_sys-linux.cfg

INCLUDE archiso_tail.cfg
"""

FAKE_LOADER = "timeout 15\ndefault 01-archiso-linux.conf\nbeep on\n"


def _load_config_tool():
    """Charge erplibre-install-config sans écrire de __pycache__ dans la
    surcouche : tout ce qui s'y trouve part dans l'ISO."""
    loader = importlib.machinery.SourceFileLoader(
        "erplibre_install_config", str(CONFIG_TOOL)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


cfg = _load_config_tool()


def _fake_releng(base):
    """Miniature de releng : juste les fichiers que build_iso édite."""
    rel = Path(base) / "releng"
    (rel / "airootfs/root").mkdir(parents=True)
    (rel / "syslinux").mkdir()
    (rel / "efiboot/loader/entries").mkdir(parents=True)
    (rel / "profiledef.sh").write_text(FAKE_PROFILEDEF)
    (rel / "packages.x86_64").write_text("base\narchinstall\nlinux\n")
    (rel / "airootfs/root/.zlogin").write_text("~/.automated_script.sh\n")
    (rel / "syslinux/archiso_sys.cfg").write_text(FAKE_SYSLINUX_SYS)
    (rel / "efiboot/loader/loader.conf").write_text(FAKE_LOADER)
    (rel / "efiboot/loader/entries/01-archiso-linux.conf").write_text(
        "title    Exemple\n"
    )
    return rel


# Le checkout embarqué par les tests de prepare_profile : quelques
# fichiers suivis du dépôt, nommés d'avance. Sans liste, prepare_profile
# lancerait git et copierait tout le dépôt à chaque test, et échouerait
# hors d'un checkout git.
SMALL_CHECKOUT = [
    "conf/git_manifest.csv",
    "private/.gitignore",
    "private/__init__.py",
    "script/todo/todo.py",
]


def _doc(auto="odoo18"):
    return build_iso.profiles_document(
        "https://exemple.invalid/erplibre.git", "branche-test", "fr", auto
    )


class TestProfileEditing(unittest.TestCase):
    def test_merge_packages_appends_missing_only(self):
        text = "# commentaire\nbase\n\npython\n"
        out = build_iso.merge_packages(text, ("python", "git"))
        self.assertEqual(out, text + "git\n")
        self.assertEqual(build_iso.merge_packages(out, ("git",)), out)

    def test_merge_packages_without_final_newline(self):
        self.assertEqual(
            build_iso.merge_packages("base", ("git",)), "base\ngit\n"
        )

    def test_edit_profiledef_values_and_permissions(self):
        out = build_iso.edit_profiledef(
            FAKE_PROFILEDEF,
            build_iso.PROFILEDEF_VALUES,
            build_iso.INSTALLER_PERMISSIONS,
        )
        self.assertIn('iso_name="erplibre-archlinux"', out)
        self.assertIn('iso_label="ERPLIBRE_$(date', out)
        self.assertIn('iso_publisher="ERPLibre', out)
        self.assertNotIn("exemple.invalid", out)
        # iso_version n'est pas touché.
        self.assertIn('iso_version="$(date --date=', out)
        block = out.split("file_permissions=(")[1].split("\n)")[0]
        for path in build_iso.INSTALLER_PERMISSIONS:
            self.assertIn(f'["{path}"]="0:0:755"', block)
        self.assertIn('["/etc/shadow"]="0:0:400"', block)
        # Réappliquer ne double rien.
        again = build_iso.edit_profiledef(
            out, build_iso.PROFILEDEF_VALUES, build_iso.INSTALLER_PERMISSIONS
        )
        self.assertEqual(again, out)

    def test_edit_profiledef_refuses_changed_shape(self):
        with self.assertRaises(ValueError):
            build_iso.edit_profiledef(
                FAKE_PROFILEDEF.replace("iso_name=", "nom="),
                build_iso.PROFILEDEF_VALUES,
                {},
            )
        with self.assertRaises(ValueError):
            build_iso.edit_profiledef(
                FAKE_PROFILEDEF.replace("file_permissions=(", "perms=("),
                {},
                build_iso.INSTALLER_PERMISSIONS,
            )

    def test_edit_zlogin_once_and_on_tty1(self):
        out = build_iso.edit_zlogin("~/.automated_script.sh")
        self.assertTrue(out.startswith("~/.automated_script.sh\n"))
        self.assertIn('$(tty) == "/dev/tty1"', out)
        self.assertIn("/usr/local/bin/erplibre-install", out)
        self.assertEqual(build_iso.edit_zlogin(out), out)

    def test_edit_syslinux_keeps_default_entry(self):
        out = build_iso.edit_syslinux_sys(FAKE_SYSLINUX_SYS)
        self.assertIn("DEFAULT arch", out)
        lines = out.splitlines()
        i = lines.index("INCLUDE archiso_sys-linux.cfg")
        self.assertEqual(lines[i + 1], "INCLUDE archiso_sys-erplibre.cfg")
        self.assertEqual(build_iso.edit_syslinux_sys(out), out)
        with self.assertRaises(ValueError):
            build_iso.edit_syslinux_sys("DEFAULT arch\n")

    def test_auto_entries_carry_profile_and_serial_console(self):
        for entry in (
            build_iso.syslinux_auto_entry("home"),
            build_iso.efiboot_auto_entry("home"),
        ):
            self.assertIn("erplibre.auto=home", entry)
            self.assertIn("console=ttyS0,115200 console=tty0", entry)
            self.assertIn("archisosearchuuid=%ARCHISO_UUID%", entry)
            self.assertIn("erases first disk", entry)
        self.assertTrue(
            build_iso.syslinux_auto_entry("x").startswith(
                "LABEL erplibreauto\n"
            )
        )

    def test_prepare_profile_on_fake_releng(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            prof = Path(tmp) / "profile"
            doc = _doc("dev")
            build_iso.prepare_profile(
                rel, OVERLAY, prof, doc, "dev", checkout=SMALL_CHECKOUT
            )
            self.assertEqual(
                (prof / "efiboot/loader/loader.conf").read_text(), FAKE_LOADER
            )
            # L'ISO d'installation n'a aucune entrée automatique : ni
            # fichier d'entrée, ni INCLUDE syslinux, ni marque autotest.
            self.assertFalse((prof / build_iso.EFIBOOT_AUTO_FILE).exists())
            self.assertFalse(
                (prof / "syslinux" / build_iso.SYSLINUX_AUTO_FILE).exists()
            )
            self.assertEqual(
                (prof / build_iso.SYSLINUX_SYS).read_text(), FAKE_SYSLINUX_SYS
            )
            self.assertFalse(
                (
                    prof / "airootfs" / build_iso.AUTOTEST_MARKER.lstrip("/")
                ).exists()
            )
            written = json.loads(
                (prof / "airootfs" / build_iso.PROFILES_JSON).read_text()
            )
            self.assertEqual(written, doc)
            for rel_path in build_iso.INSTALLER_PERMISSIONS:
                path = prof / "airootfs" / rel_path.lstrip("/")
                self.assertTrue(path.is_file(), rel_path)
            self.assertIn(
                "python", (prof / "packages.x86_64").read_text().split()
            )
            # releng n'est pas modifié.
            self.assertEqual(
                (rel / "profiledef.sh").read_text(), FAKE_PROFILEDEF
            )

    def test_prepare_profile_ships_machine_profile_modules(self):
        # Le cœur de l'installateur importe machine_profile et facts depuis
        # SHARE_DIR/machine : copiés du dépôt, jamais dupliqués dans la
        # surcouche.
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            prof = Path(tmp) / "profile"
            build_iso.prepare_profile(
                rel, OVERLAY, prof, _doc(), "odoo18", checkout=SMALL_CHECKOUT
            )
            dest = prof / "airootfs" / build_iso.MACHINE_ISO_DIR
            for nom in (
                "machine_profile.py",
                "facts.py",
                "profiles/generic.json",
                "profiles/workstation-luks.json",
            ):
                self.assertEqual(
                    (dest / nom).read_bytes(),
                    (build_iso.MACHINE_DIR / nom).read_bytes(),
                    nom,
                )
            self.assertFalse((OVERLAY / build_iso.MACHINE_ISO_DIR).exists())

    def test_prepare_profile_ships_ui_catalogue_and_todo(self):
        # L'interface lit son français dans messages.fr.json, et le TODO
        # de la clé est la copie de script/ et conf/ sous TODO_ISO_DIR.
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            prof = Path(tmp) / "profile"
            build_iso.prepare_profile(
                rel, OVERLAY, prof, _doc(), "odoo18", checkout=SMALL_CHECKOUT
            )
            airootfs = prof / "airootfs"
            catalogue = json.loads(
                (airootfs / build_iso.CATALOGUE_JSON).read_text()
            )
            self.assertEqual(catalogue["version"], 1)
            self.assertEqual(
                catalogue["fr"]["Install ERPLibre"], "Installer ERPLibre"
            )
            todo = airootfs / build_iso.TODO_ISO_DIR
            self.assertEqual(
                (todo / "script/todo/todo.py").read_bytes(),
                (ROOT / "script/todo/todo.py").read_bytes(),
            )
            self.assertTrue((todo / "conf").is_dir())
            self.assertEqual(list(todo.rglob("__pycache__")), [])
            # De private/, seuls son .gitignore et son __init__.py.
            self.assertEqual(
                sorted(
                    p.relative_to(todo).as_posix()
                    for p in (todo / "private").rglob("*")
                ),
                sorted(build_iso.CHECKOUT_PRIVATE_KEPT),
            )
            self.assertFalse((todo / "tasks").exists())
            self.assertFalse((todo / ".git").exists())
            for paquet in ("python-textual", "python-click", "python-urwid"):
                self.assertIn(
                    paquet, (prof / "packages.x86_64").read_text().split()
                )
            profiledef = (prof / "profiledef.sh").read_text()
            self.assertIn(
                f'["/{build_iso.TODO_ISO_DIR}/script/todo/todo.py"]="0:0:755"',
                profiledef,
            )
            self.assertIn(
                '["/usr/local/bin/erplibre-installer-ui"]="0:0:755"',
                profiledef,
            )

    def test_catalogue_document_reports_missing_translations(self):
        doc, manquantes = build_iso.catalogue_document(
            ["Un", "Deux"], {"Un": {"fr": "Une", "en": "Un"}, "Deux": {}}
        )
        self.assertEqual(doc, {"version": 1, "fr": {"Un": "Une"}})
        self.assertEqual(manquantes, ["Deux"])

    def test_ui_strings_reads_tr_and_n_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ecran.py"
            source.write_text(
                "x = tr('Un')\n"
                "y = self.app.tr('Deux {a}', a=1)\n"
                "z = N_('Trois' ' suite')\n"
                "w = tr(variable)\n"
                "v = print('Pas une phrase')\n"
            )
            self.assertEqual(
                build_iso.ui_strings([source]),
                ["Deux {a}", "Trois suite", "Un"],
            )

    def test_copy_machine_takes_only_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "machine"
            (src / "profiles").mkdir(parents=True)
            (src / "__pycache__").mkdir()
            (src / "machine_profile.py").write_text("x = 1\n")
            (src / "__pycache__" / "machine_profile.pyc").write_bytes(b"\0")
            (src / "profiles" / "generic.json").write_text("{}\n")
            (src / "profiles" / "notes.txt").write_text("brouillon\n")
            dest = Path(tmp) / "dest"
            copies = build_iso.copy_machine(src, dest)
            self.assertEqual(
                copies, ["machine_profile.py", "profiles/generic.json"]
            )
            self.assertEqual(list(dest.rglob("*.pyc")), [])
            self.assertFalse((dest / "profiles" / "notes.txt").exists())
            (src / "machine_profile.py").unlink()
            with self.assertRaises(LookupError):
                build_iso.copy_machine(src, Path(tmp) / "autre")

    def test_prepare_profile_leaves_python_cache_out(self):
        # Un cache Python dans la surcouche (laissé par un import) ne
        # doit jamais atteindre l'airootfs.
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            overlay = Path(tmp) / "overlay"
            shutil.copytree(OVERLAY, overlay)
            cache = overlay / "airootfs/usr/local/bin/__pycache__"
            cache.mkdir(exist_ok=True)
            (cache / "exemple.pyc").write_bytes(b"\0")
            (overlay / "airootfs/usr/local/bin/seul.pyc").write_bytes(b"\0")
            prof = Path(tmp) / "profile"
            build_iso.prepare_profile(
                rel, overlay, prof, _doc(), "odoo18", checkout=SMALL_CHECKOUT
            )
            self.assertEqual(list(prof.rglob("__pycache__")), [])
            self.assertEqual(list(prof.rglob("*.pyc")), [])
            self.assertTrue(
                (prof / "airootfs/usr/local/bin/erplibre-install").is_file()
            )

    def test_check_releng_matches_prepare_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            build_iso.check_releng(rel)
            build_iso.check_releng(rel, auto_default=True)
            (rel / "efiboot/loader/loader.conf").write_text("beep on\n")
            build_iso.check_releng(rel)
            with self.assertRaises(ValueError):
                build_iso.check_releng(rel, auto_default=True)
            (rel / "airootfs/root/.zlogin").unlink()
            with self.assertRaises(OSError):
                build_iso.check_releng(rel)

    def test_autotest_variant_boots_auto_entry_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            prof = Path(tmp) / "profile"
            build_iso.prepare_profile(
                rel,
                OVERLAY,
                prof,
                _doc("gnome"),
                "gnome",
                auto_default=True,
                checkout=SMALL_CHECKOUT,
            )
            loader = (prof / "efiboot/loader/loader.conf").read_text()
            self.assertIn("default 04-erplibre-auto-linux.conf\n", loader)
            self.assertIn("timeout 3\n", loader)
            self.assertIn("beep on\n", loader)
            sys_cfg = (prof / build_iso.SYSLINUX_SYS).read_text()
            self.assertIn("DEFAULT erplibreauto\n", sys_cfg)
            self.assertIn("TIMEOUT 30\n", sys_cfg)
            self.assertNotIn("DEFAULT arch", sys_cfg)
            for entry in (
                prof / build_iso.EFIBOOT_AUTO_FILE,
                prof / "syslinux" / build_iso.SYSLINUX_AUTO_FILE,
            ):
                text = entry.read_text()
                self.assertIn("erplibre.auto=gnome", text)
                self.assertIn(build_iso.AUTOTEST_KERNEL_PARAM, text)
            self.assertIn(
                'iso_name="erplibre-archlinux-autotest"',
                (prof / "profiledef.sh").read_text(),
            )
            self.assertIn("INCLUDE archiso_sys-erplibre.cfg", sys_cfg)
            marque = prof / "airootfs" / build_iso.AUTOTEST_MARKER.lstrip("/")
            self.assertEqual(marque.read_text(), "gnome\n")

    def test_default_directive_edits_refuse_changed_shape(self):
        with self.assertRaises(ValueError):
            build_iso.edit_loader_conf_default_auto("beep on\n")
        with self.assertRaises(ValueError):
            build_iso.edit_syslinux_default_auto("INCLUDE x.cfg\n")


GIT = shutil.which("git")


def _git_env():
    """Un git sans configuration globale ni système : ni le .gitignore
    global ni les crochets de l'hôte ne changent ce que le test voit."""
    env = dict(
        os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull
    )
    for nom in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(nom, None)
    return env


def _git(repo, *args):
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Essai",
            "-c",
            "user.email=essai@exemple.invalid",
            *args,
        ],
        check=True,
        capture_output=True,
        env=_git_env(),
    )


class TestCheckoutSelection(unittest.TestCase):
    """La règle qui choisit le checkout embarqué sous TODO_ISO_DIR. Chemins
    et dépôts inventés."""

    def test_select_checkout_rule(self):
        entree = [
            "script/todo/todo.py",
            "script/todo/todo.py",  # doublon (entrée en conflit)
            "conf/exemple.txt",
            "Makefile",
            "private/.gitignore",
            "private/__init__.py",
            "private/notes_client.md",
            "private/iso/machine/poste.json",
            "private/sous/__init__.py",
            "tasks/todo.md",
            "script/todo/__pycache__/lib.cpython-314.pyc",
            "script/vieux.pyc",
            "script/vieux.pyo",
            "depot_imbrique/",
            ".git/config",
            "sous/.git/HEAD",
            "/etc/passwd",
            "../hors_depot.txt",
            "script/../hors.txt",
            "script/./todo.py",
            "script//double.py",
            "",
            "privateish/ok.txt",
            "docs/tasks/ok.md",
        ]
        self.assertEqual(
            build_iso.select_checkout(entree),
            [
                "Makefile",
                "conf/exemple.txt",
                "docs/tasks/ok.md",
                "private/.gitignore",
                "private/__init__.py",
                "privateish/ok.txt",
                "script/todo/todo.py",
            ],
        )

    def test_list_format_round_trip(self):
        chemins = ["script/todo/todo.py", "doc/déjà vu.md", "a b/c"]
        donnees = build_iso.format_checkout_list(chemins)
        self.assertEqual(donnees.count(b"\0"), 3)
        self.assertEqual(build_iso.parse_checkout_list(donnees), chemins)
        self.assertEqual(build_iso.parse_checkout_list(b"a\0\0b"), ["a", "b"])

    def test_checkout_files_keeps_regular_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "script/todo").mkdir(parents=True)
            (repo / "script/todo/todo.py").write_text("print(1)\n")
            (repo / "lien.txt").symlink_to("/etc/hostname")
            (repo / "dossier").mkdir()
            liste = [
                "script/todo/todo.py",
                "efface_du_disque.py",
                "lien.txt",
                "dossier",
            ]
            self.assertEqual(
                build_iso.checkout_files(repo, liste), ["script/todo/todo.py"]
            )
            with self.assertRaises(LookupError):
                build_iso.checkout_files(repo, ["lien.txt"])

    def test_git_listing_argv_and_refusals(self):
        appels = []

        def run(argv, **kw):
            appels.append(argv)
            sortie = b"a\0b\0" if "--cached" in argv else b"c\0"
            return subprocess.CompletedProcess(argv, 0, sortie, b"")

        self.assertEqual(
            build_iso.git_listing("/depot", run), (["a", "b"], ["c"])
        )
        self.assertEqual(
            appels,
            [
                ["git", "-C", "/depot", "ls-files", "-z", "--cached"],
                [
                    "git",
                    "-C",
                    "/depot",
                    "ls-files",
                    "-z",
                    "--others",
                    "--exclude-standard",
                ],
            ],
        )

        def pas_un_depot(argv, **kw):
            return subprocess.CompletedProcess(argv, 128, b"", b"not a git")

        with self.assertRaises(LookupError):
            build_iso.git_listing("/depot", pas_un_depot)

        def sans_git(argv, **kw):
            raise FileNotFoundError("git")

        with self.assertRaises(LookupError):
            build_iso.git_listing("/depot", sans_git)

    def test_iso_permissions_follow_the_x_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "run.sh").write_text("#!/bin/sh\n")
            (repo / "run.sh").chmod(0o755)
            (repo / "lib.py").write_text("x = 1\n")
            (repo / "lib.py").chmod(0o644)
            droits = build_iso.iso_permissions(repo, ["run.sh", "lib.py"])
        racine = f"/{build_iso.TODO_ISO_DIR}"
        self.assertEqual(droits[f"{racine}/run.sh"], "0:0:755")
        self.assertNotIn(f"{racine}/lib.py", droits)
        for chemin, mode in build_iso.INSTALLER_PERMISSIONS.items():
            self.assertEqual(droits[chemin], mode)

    @unittest.skipUnless(GIT, "git absent")
    def test_read_checkout_on_a_real_git_repository(self):
        # Suivi modifié, non suivi non ignoré, ignoré, private/, tasks/,
        # dépôt imbriqué, suivi effacé : chaque cas de la règle sur un vrai
        # dépôt.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "depot"
            (repo / "script/todo").mkdir(parents=True)
            (repo / "private").mkdir()
            (repo / "tasks").mkdir()
            (repo / "script/todo/todo.py").write_text("v = 1\n")
            (repo / "script/todo/todo.py").chmod(0o755)
            (repo / "script/todo/efface.py").write_text("x = 1\n")
            (repo / ".gitignore").write_text("*.log\n/.venv.exemple/\n")
            (repo / "private/.gitignore").write_text("*\n!.gitignore\n")
            (repo / "private/__init__.py").write_text("")
            _git(repo, "init", "-q")
            _git(repo, "add", "-A")
            _git(repo, "add", "-f", "private/__init__.py")
            _git(repo, "commit", "-q", "-m", "init")
            (repo / "script/todo/todo.py").write_text("v = 2\n")
            (repo / "script/todo/efface.py").unlink()
            (repo / "script/todo/nouveau.py").write_text("n = 1\n")
            # Non suivis à la forme d'un secret ou d'une donnée : écartés.
            (repo / "script/todo/mail").mkdir()
            for nom in (
                ".env",
                "cle.PEM",
                "vidage.sql",
                "script/todo/mail/accounts.json",
            ):
                (repo / nom).write_text("invente\n")
            (repo / "journal.log").write_text("ignoré\n")
            (repo / ".venv.exemple").mkdir()
            (repo / ".venv.exemple/pyvenv.cfg").write_text("home = x\n")
            (repo / "private/profil_poste.json").write_text("{}\n")
            (repo / "tasks/todo.md").write_text("carnet\n")
            (repo / "imbrique").mkdir()
            _git(repo / "imbrique", "init", "-q")
            (repo / "imbrique/a.txt").write_text("a\n")

            def run(argv, **kw):
                return subprocess.run(argv, env=_git_env(), **kw)

            checkout = build_iso.read_checkout(repo=repo, run=run)
            self.assertEqual(
                checkout["files"],
                [
                    ".gitignore",
                    "private/.gitignore",
                    "private/__init__.py",
                    "script/todo/nouveau.py",
                    "script/todo/todo.py",
                ],
            )
            self.assertEqual(checkout["untracked"], 1)
            self.assertEqual(
                checkout["untracked_names"], ["script/todo/nouveau.py"]
            )
            self.assertEqual(
                checkout["denied"],
                [
                    ".env",
                    "cle.PEM",
                    "script/todo/mail/accounts.json",
                    "vidage.sql",
                ],
            )
            sortie = io.StringIO()
            with contextlib.redirect_stdout(sortie):
                build_iso._print_checkout(checkout)
            self.assertIn(
                "non suivi : script/todo/nouveau.py", sortie.getvalue()
            )
            self.assertIn("écarté    : vidage.sql", sortie.getvalue())
            self.assertEqual(
                checkout["bytes"],
                sum((repo / f).stat().st_size for f in checkout["files"]),
            )
            dest = Path(tmp) / "iso"
            self.assertEqual(
                build_iso.copy_checkout(repo, dest, checkout["files"]), 5
            )
            # L'arbre de travail fait foi : la modification non commitée.
            self.assertEqual(
                (dest / "script/todo/todo.py").read_text(), "v = 2\n"
            )
            # La même liste, relue d'un fichier comme dans le conteneur.
            liste = Path(tmp) / "checkout.list"
            liste.write_bytes(
                build_iso.format_checkout_list(checkout["files"])
            )
            relu = build_iso.read_checkout(str(liste), repo=repo)
            self.assertEqual(relu["files"], checkout["files"])
            self.assertIsNone(relu["untracked"])

    def test_read_checkout_outside_git_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LookupError):
                build_iso.read_checkout(
                    repo=tmp,
                    run=lambda argv, **kw: subprocess.CompletedProcess(
                        argv, 128, b"", b"fatal: not a git repository"
                    ),
                )

    def test_main_reports_a_missing_checkout(self):
        err = io.StringIO()
        with (
            mock.patch.object(
                build_iso,
                "read_checkout",
                side_effect=LookupError("pas un checkout"),
            ),
            contextlib.redirect_stderr(err),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            rc = build_iso.main(["--builder", "host", "--dry-run"])
        self.assertEqual(rc, 1)
        self.assertIn("pas un checkout", err.getvalue())

    def test_repository_selection_keeps_private_data_out(self):
        # Le dépôt lui-même : todo.py y est, et rien de private/ hors des
        # deux fichiers permis ni de tasks/.
        if not GIT or not (ROOT / ".git").exists():
            self.skipTest("pas un checkout git")
        fichiers = build_iso.read_checkout()["files"]
        self.assertIn("script/todo/todo.py", fichiers)
        self.assertIn("script/iso/archlinux/build_iso.py", fichiers)
        for rel in fichiers:
            if rel.startswith("private/"):
                self.assertIn(rel, build_iso.CHECKOUT_PRIVATE_KEPT)
            self.assertFalse(rel.startswith("tasks/"), rel)


class TestProfilesDocument(unittest.TestCase):
    def test_profiles_keys_and_commands(self):
        doc = _doc()
        keys = [p["key"] for p in doc["profiles"]]
        self.assertEqual(keys, ["odoo18", "home", "dev", "gnome"])
        self.assertEqual(doc["default_profile"], "odoo18")
        by_key = {p["key"]: p for p in doc["profiles"]}
        self.assertEqual(
            by_key["odoo18"]["command"],
            "make install_os && make install_odoo_18",
        )
        self.assertTrue(by_key["odoo18"]["service"])
        self.assertTrue(by_key["odoo18"]["postgresql"])
        self.assertIn("install_erplibre_home.sh", by_key["home"]["command"])
        self.assertFalse(by_key["home"]["postgresql"])
        self.assertEqual(
            by_key["dev"]["command"], "make install_os && make install_dev"
        )
        self.assertNotIn("deploy_qemu", by_key["dev"]["command"])
        self.assertEqual(by_key["gnome"]["command"], "")
        for profile in doc["profiles"]:
            self.assertTrue(profile["label"]["fr"])
            self.assertTrue(profile["label"]["en"])
            if profile["key"] != "odoo18":
                self.assertFalse(profile["service"])

    def test_commands_come_from_qemu_table(self):
        cmds = {c for _l, c in QemuInstallMixin()._qemu_install_profiles()}
        doc = _doc()
        for key in ("odoo18", "home"):
            profile = next(p for p in doc["profiles"] if p["key"] == key)
            self.assertIn(profile["command"], cmds)

    def test_labels_follow_language_and_language_restored(self):
        saved = todo_i18n._current_lang
        by_lang = build_iso.qemu_profiles_by_lang()
        self.assertEqual(todo_i18n._current_lang, saved)
        home = [l for l, c in by_lang["en"] if c.endswith("home.sh")][0]
        self.assertEqual(home, "ERPLibre Home (no Odoo)")

    def test_network_source_and_unit(self):
        doc = _doc()
        self.assertEqual(
            doc["network_source"],
            {
                "git_url": "https://exemple.invalid/erplibre.git",
                "branch": "branche-test",
            },
        )
        unit = doc["service_unit"]
        self.assertTrue(unit.startswith("[Unit]\n"))
        self.assertIn("ExecStart=/bin/bash $SVC_DIR/run.sh", unit)
        self.assertIn("User=$SVC_USER", unit)
        self.assertIn("Requires=postgresql.service", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_unknown_auto_profile_refused(self):
        with self.assertRaises(ValueError):
            _doc("inexistant")

    def test_service_unit_template_requires_heredoc(self):
        with self.assertRaises(LookupError):
            build_iso.service_unit_template("echo sans unité")


class TestPlan(unittest.TestCase):
    EPOCH = 1_700_000_000
    # Le checkout que main embarque, sans lancer git : un fichier réel du
    # dépôt, que prepare_profile copie.
    CHECKOUT = {"files": ["script/todo/todo.py"], "untracked": 0, "bytes": 1}

    def test_rootless_plan(self):
        plan = build_iso.build_plan(
            "/w", "/o", self.EPOCH, 92, keep_work=False, euid=1000
        )
        self.assertFalse(plan["sudo"])
        # « -r » : mkarchiso efface lui-même WORK/build, aux sous-UID.
        self.assertEqual(
            plan["mkarchiso"],
            [
                "mkarchiso",
                "-v",
                "-r",
                "-w",
                "/w/build",
                "-o",
                "/o",
                "/w/profile",
            ],
        )
        self.assertEqual(
            plan["env"], {"SOURCE_DATE_EPOCH": str(self.EPOCH), "TZ": "UTC"}
        )
        self.assertEqual(plan["clean"], "/w")
        name = os.path.basename(plan["iso"])
        self.assertRegex(
            name, r"^erplibre-archlinux-\d{4}\.\d{2}\.\d{2}-x86_64\.iso$"
        )
        self.assertEqual(plan["sha256"], plan["iso"] + ".sha256")

    def test_iso_name_is_utc_date_whatever_the_local_zone(self):
        """Le nom prédit suit la date UTC, celle que mkarchiso écrit sous
        TZ=UTC : 03:00 UTC le 26 est encore le 25 dans un fuseau à -5."""
        epoch = 1795662000  # 2026-11-26 03:00:00 UTC
        old = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "EST+5"
            time.tzset()
            self.assertEqual(
                build_iso.iso_basename(epoch),
                "erplibre-archlinux-2026.11.26-x86_64.iso",
            )
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_old_archiso_uses_sudo_and_keep_work(self):
        plan = build_iso.build_plan(
            "/w", "/o", self.EPOCH, 88, True, euid=1000
        )
        self.assertTrue(plan["sudo"])
        self.assertEqual(
            plan["mkarchiso"][:4],
            ["sudo", "env", f"SOURCE_DATE_EPOCH={self.EPOCH}", "TZ=UTC"],
        )
        self.assertNotIn("-r", plan["mkarchiso"])
        self.assertIsNone(plan["clean"])

    def test_root_needs_neither_sudo_nor_unshare(self):
        for version in (88, 92):
            plan = build_iso.build_plan(
                "/w", "/o", self.EPOCH, version, False, euid=0
            )
            self.assertFalse(plan["sudo"])
            self.assertEqual(plan["mkarchiso"][:3], ["mkarchiso", "-v", "-r"])
            self.assertEqual(plan["clean"], "/w")

    def test_autotest_iso_name(self):
        plan = build_iso.build_plan(
            "/w",
            "/o",
            self.EPOCH,
            92,
            False,
            euid=1000,
            iso_name=build_iso.AUTOTEST_ISO_NAME,
        )
        self.assertRegex(
            os.path.basename(plan["iso"]),
            r"^erplibre-archlinux-autotest-\d{4}\.\d{2}\.\d{2}-x86_64\.iso$",
        )

    def test_parse_archiso_version(self):
        self.assertEqual(build_iso.parse_archiso_version("archiso 92-1"), 92)
        self.assertEqual(build_iso.parse_archiso_version("mkarchiso 89\n"), 89)
        self.assertIsNone(build_iso.parse_archiso_version("absent"))

    def _main(self, *argv, run=None):
        """build_iso.main avec archiso 92 simulé et l'horloge fixée à
        EPOCH ; `run` remplace subprocess.run (mkarchiso). Rend (code,
        sortie, erreurs)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    build_iso, "archiso_version", return_value=92
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_iso.time, "time", return_value=self.EPOCH
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_iso, "read_checkout", return_value=self.CHECKOUT
                )
            )
            if run is not None:
                stack.enter_context(
                    mock.patch.object(build_iso.subprocess, "run", run)
                )
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            rc = build_iso.main(["--builder", "host"] + list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            rc, text, _err = self._main(
                "--dry-run",
                "--releng",
                str(_fake_releng(tmp)),
                "--work-dir",
                str(work),
                "--output-dir",
                str(Path(tmp) / "iso"),
                "--branch",
                "branche-test",
            )
            self.assertEqual(rc, 0)
            self.assertFalse(work.exists())
            self.assertFalse((Path(tmp) / "iso").exists())
            self.assertIn("mkarchiso -v -r -w", text)
            self.assertIn("branche-test", text)

    def test_dry_run_refuses_like_a_real_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = _fake_releng(tmp)
            work = Path(tmp) / "work"
            common = ("--dry-run", "--output-dir", str(Path(tmp) / "iso"))
            work.mkdir()
            rc, _out, err = self._main(
                *common, "--releng", str(rel), "--work-dir", str(work)
            )
            self.assertEqual(rc, 1)
            self.assertIn("existe déjà", err)
            work.rmdir()
            (rel / "profiledef.sh").write_text("iso_name=x\n")
            rc, _out, err = self._main(
                *common, "--releng", str(rel), "--work-dir", str(work)
            )
            self.assertEqual(rc, 2)
            self.assertIn("releng", err)
            self.assertFalse(work.exists())

    def test_autotest_output_dir(self):
        default = build_iso.DEFAULT_OUTPUT_DIR.expanduser()
        self.assertEqual(
            build_iso.resolve_output_dir(None, "gnome"),
            build_iso.AUTOTEST_OUTPUT_DIR.expanduser(),
        )
        self.assertEqual(build_iso.resolve_output_dir(None, None), default)
        self.assertEqual(
            build_iso.resolve_output_dir("/o", "gnome"), Path("/o")
        )
        # Le répertoire que balaie le catalogue USB est refusé à la
        # variante de test, même écrit autrement.
        for value in (str(default), str(default) + "/", "~/.erplibre/iso"):
            with self.assertRaises(ValueError):
                build_iso.resolve_output_dir(value, "gnome")
        rc, _out, err = self._main(
            "--dry-run",
            "--auto-default",
            "gnome",
            "--output-dir",
            str(default),
        )
        self.assertEqual(rc, 2)
        self.assertIn("--auto-default", err)

    def test_exit_code_of_signal(self):
        self.assertEqual(build_iso.exit_code(0), 0)
        self.assertEqual(build_iso.exit_code(3), 3)
        self.assertEqual(build_iso.exit_code(-15), 143)

    def test_archiso_version_from_pacman_only(self):
        calls = []

        def run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, "", "")

        with mock.patch.object(build_iso.shutil, "which", return_value="x"):
            self.assertEqual(build_iso.archiso_version(run), 0)
        self.assertEqual(calls, [["pacman", "-Q", "archiso"]])

    @staticmethod
    def _fake_mkarchiso(rc, content=b"iso"):
        """subprocess.run simulé : écrit l'ISO que mkarchiso produirait
        (nom tiré de SOURCE_DATE_EPOCH) et rend `rc`."""

        def run(argv, env=None, **_kw):
            out_dir = Path(argv[argv.index("-o") + 1])
            name = build_iso.iso_basename(int(env["SOURCE_DATE_EPOCH"]))
            (out_dir / name).write_bytes(content)
            return subprocess.CompletedProcess(argv, rc)

        return run

    def test_build_success_writes_sha256_and_cleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel, work = _fake_releng(tmp), Path(tmp) / "work"
            out_dir = Path(tmp) / "iso"
            rc, _out, _err = self._main(
                "--releng",
                str(rel),
                "--work-dir",
                str(work),
                "--output-dir",
                str(out_dir),
                run=self._fake_mkarchiso(0),
            )
            self.assertEqual(rc, 0)
            self.assertFalse(work.exists())
            (iso,) = out_dir.glob("*.iso")
            self.assertEqual(
                (out_dir / (iso.name + ".sha256")).read_text(),
                build_iso.sha256_line(iso),
            )
            self.assertEqual(list(out_dir.glob("*.tmp")), [])

    def test_build_failure_leaves_no_stale_sha256_nor_partial_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel, work = _fake_releng(tmp), Path(tmp) / "work"
            out_dir = Path(tmp) / "iso"
            out_dir.mkdir()
            name = build_iso.iso_basename(self.EPOCH)
            (out_dir / name).write_bytes(b"ancienne")
            (out_dir / (name + ".sha256")).write_text("ancienne\n")
            rc, _out, _err = self._main(
                "--releng",
                str(rel),
                "--work-dir",
                str(work),
                "--output-dir",
                str(out_dir),
                run=self._fake_mkarchiso(1, b"tronq"),
            )
            self.assertEqual(rc, 1)
            self.assertEqual(list(out_dir.iterdir()), [])
            # Le travail reste, pour le diagnostic.
            self.assertTrue((work / "profile").is_dir())

    def test_build_failure_before_iso_keeps_previous_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel, work = _fake_releng(tmp), Path(tmp) / "work"
            out_dir = Path(tmp) / "iso"
            out_dir.mkdir()
            name = build_iso.iso_basename(self.EPOCH)
            (out_dir / name).write_bytes(b"ancienne")
            (out_dir / (name + ".sha256")).write_text("ancienne\n")

            def run(argv, **_kw):
                return subprocess.CompletedProcess(argv, -9)

            rc, _out, _err = self._main(
                "--releng",
                str(rel),
                "--work-dir",
                str(work),
                "--output-dir",
                str(out_dir),
                run=run,
            )
            self.assertEqual(rc, 137)
            self.assertEqual([p.name for p in out_dir.iterdir()], [name])

    def test_prepare_failure_removes_work_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel, work = _fake_releng(tmp), Path(tmp) / "work"
            with mock.patch.object(
                build_iso,
                "prepare_profile",
                side_effect=ValueError("forme changée"),
            ):
                rc, _out, err = self._main(
                    "--releng",
                    str(rel),
                    "--work-dir",
                    str(work),
                    "--output-dir",
                    str(Path(tmp) / "iso"),
                    run=self._fake_mkarchiso(0),
                )
            self.assertEqual(rc, 1)
            self.assertIn("forme changée", err)
            self.assertFalse(work.exists())

    def test_missing_mkarchiso_offers_pacman_and_exits_2(self):
        out = io.StringIO()
        with (
            mock.patch.object(build_iso, "archiso_version", return_value=None),
            contextlib.redirect_stdout(out),
        ):
            rc = build_iso.main(
                ["--builder", "host", "--work-dir", "/nonexistent/w"]
            )
        self.assertEqual(rc, 2)
        self.assertIn("pacman -S --needed archiso", out.getvalue())
        self.assertIn("--builder container", out.getvalue())

    def test_sha256_line_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exemple.iso"
            path.write_bytes(b"abc")
            self.assertEqual(
                build_iso.sha256_line(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f2"
                "0015ad  exemple.iso\n",
            )


class TestInstallerConfig(unittest.TestCase):
    def setUp(self):
        self.doc = _doc()
        self.template = json.loads(TEMPLATE.read_text())
        self.stage = STAGE.read_text()

    def _profile(self, key):
        return cfg.find_profile(self.doc, key)

    def _config(self, key, uefi=True, disk=None):
        return cfg.build_config(
            self.template,
            self.doc,
            self._profile(key),
            self.stage,
            uefi,
            "/dev/tty1",
            "fr",
            disk,
        )

    def test_template_is_gnome_gdm_networkmanager(self):
        self.assertEqual(
            self.template["profile_config"]["profile"],
            {"main": "Desktop", "details": ["GNOME"]},
        )
        self.assertEqual(self.template["profile_config"]["greeter"], "gdm")
        self.assertEqual(
            self.template["profile_config"]["gfx_driver"], "All open-source"
        )
        self.assertEqual(self.template["network_config"], {"type": "nm"})
        self.assertEqual(
            self.template["app_config"]["audio_config"]["audio"], "pipewire"
        )
        self.assertNotIn("disk_config", self.template)

    def test_erplibre_profiles_get_stage_and_packages(self):
        for key in ("odoo18", "home", "dev"):
            config = self._config(key)
            json.dumps(config)
            self.assertEqual(len(config["custom_commands"]), 1, key)
            for pkg in cfg.STAGE_PACKAGES:
                self.assertIn(pkg, config["packages"])
            self.assertEqual(
                "postgresql" in config["packages"],
                self._profile(key)["postgresql"],
            )
        self.assertNotIn("disk_config", self._config("odoo18"))

    def test_gnome_only_has_no_stage(self):
        config = self._config("gnome")
        self.assertEqual(config["custom_commands"], [])
        self.assertEqual(config["packages"], [])

    def test_bootloader_follows_firmware(self):
        # « removable » : archinstall 4.5 l'ignore hors GRUB et Limine.
        for uefi in (True, False):
            self.assertFalse(
                self._config("odoo18", uefi=uefi)["bootloader_config"][
                    "removable"
                ]
            )
        self.assertEqual(
            self._config("odoo18", uefi=True)["bootloader_config"][
                "bootloader"
            ],
            "Systemd-boot",
        )
        self.assertEqual(
            self._config("odoo18", uefi=False)["bootloader_config"][
                "bootloader"
            ],
            "Grub",
        )

    def test_default_and_unknown_profile(self):
        self.assertEqual(cfg.find_profile(self.doc, "1")["key"], "odoo18")
        self.assertEqual(cfg.find_profile(self.doc, "")["key"], "odoo18")
        self.assertIsNone(cfg.find_profile(self.doc, "inexistant"))

    @unittest.skipUnless(BASH, "bash absent")
    def test_custom_command_syntax_and_prelude_values(self):
        command = self._config("odoo18")["custom_commands"][0]
        self.assertTrue(command.startswith("#!/usr/bin/env bash\n"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user-command.0.sh"
            path.write_text(command)
            subprocess.run([BASH, "-n", str(path)], check=True)
            # Sourcé, le script ne lance rien : seules ses variables
            # comptent ici.
            out = subprocess.run(
                [
                    BASH,
                    "-c",
                    'source "$1"; printf "%s\\n--\\n%s\\n--\\n%s" '
                    '"$EL_PROFILE_CMD" "$EL_GIT_BRANCH" "$EL_UNIT_TEMPLATE"',
                    "_",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        cmd, branch, unit = out.split("\n--\n")
        self.assertEqual(cmd, "make install_os && make install_odoo_18")
        self.assertEqual(branch, "branche-test")
        self.assertEqual(unit, self.doc["service_unit"])

    def test_cmdline_and_lang(self):
        params = cfg.cmdline_params(
            "initrd=x archisosearchuuid=2001-02-03-04-05-06-00 "
            "erplibre.auto=home erplibre.lang=en quiet"
        )
        self.assertEqual(params["erplibre.auto"], "home")
        self.assertEqual(params["quiet"], "")
        self.assertEqual(cfg.pick_lang(params, self.doc), "en")
        self.assertEqual(cfg.pick_lang({}, self.doc), "fr")
        self.assertEqual(cfg.pick_lang({"erplibre.lang": "xx"}, {}), "fr")
        # Découpage sur les blancs, comme el_param : une apostrophe ou un
        # guillemet isolé ne fait pas échouer l'outil.
        params = cfg.cmdline_params("erplibre.password=l'exemple x=\"y")
        self.assertEqual(params["erplibre.password"], "l'exemple")
        self.assertEqual(params["x"], '"y')

    def test_credentials(self):
        creds = cfg.credentials("erplibre", "secret-test")
        self.assertEqual(creds["users"][0]["username"], "erplibre")
        self.assertEqual(creds["users"][0]["!password"], "secret-test")
        self.assertTrue(creds["users"][0]["sudo"])

    def test_enable_ssh_once(self):
        config = {"packages": ["git"]}
        cfg.enable_ssh(cfg.enable_ssh(config))
        self.assertEqual(config["packages"], ["git", "openssh"])
        self.assertEqual(config["services"], ["sshd"])

    def test_main_list_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp) / "share"
            shutil.copytree(SHARE, share)
            (share / "profiles.json").write_text(json.dumps(self.doc))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cfg.main(["--share-dir", str(share), "--list"])
            self.assertEqual(rc, 0)
            first = out.getvalue().splitlines()[0].split("\t")
            self.assertEqual(first[:2], ["1", "odoo18"])
            target = Path(tmp) / "c.json"
            rc = cfg.main(
                [
                    "--share-dir",
                    str(share),
                    "--profile",
                    "dev",
                    "--output",
                    str(target),
                ]
            )
            self.assertEqual(rc, 0)
            written = json.loads(target.read_text())
            self.assertEqual(len(written["custom_commands"]), 1)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with contextlib.redirect_stderr(io.StringIO()):
                rc = cfg.main(
                    [
                        "--share-dir",
                        str(share),
                        "--profile",
                        "x",
                        "--output",
                        str(target),
                    ]
                )
            self.assertEqual(rc, 2)


def _disk(name, size, **kw):
    dev = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "rm": False,
        "ro": False,
        "size": size,
        "log_sec": 512,
        "uuid": None,
        "mountpoints": [None],
    }
    dev.update(kw)
    return dev


class TestAutoDisk(unittest.TestCase):
    UUID = "2001-02-03-04-05-06-00"

    def test_boot_medium_is_never_picked(self):
        # Clé USB d'installation (image hybride, UUID sur une partition)
        # listée AVANT le disque de la VM.
        usb = _disk(
            "sda",
            64 * GIB,
            rm=True,
            children=[
                {
                    "name": "sda1",
                    "type": "part",
                    "uuid": self.UUID,
                    "mountpoints": ["/run/archiso/bootmnt"],
                }
            ],
        )
        lsblk = {"blockdevices": [usb, _disk("vda", 40 * GIB)]}
        self.assertEqual(cfg.boot_disk_names(lsblk, self.UUID), {"sda"})
        self.assertEqual(
            cfg.pick_install_disk(lsblk, self.UUID)["name"], "vda"
        )

    def test_boot_medium_found_by_mount_alone(self):
        usb = _disk(
            "sdb",
            64 * GIB,
            children=[
                {
                    "name": "sdb1",
                    "type": "part",
                    "mountpoints": ["/run/archiso/bootmnt"],
                }
            ],
        )
        lsblk = {"blockdevices": [usb]}
        self.assertIsNone(cfg.pick_install_disk(lsblk, ""))

    def test_skips_rom_loop_zram_small_and_readonly(self):
        lsblk = {
            "blockdevices": [
                _disk("sr0", 1 * GIB, type="rom", uuid=self.UUID),
                _disk("loop0", 30 * GIB, type="loop"),
                _disk("zram0", 30 * GIB),
                _disk("vdb", 5 * GIB),
                _disk("vdc", 50 * GIB, ro=True),
                _disk("vdd", 50 * GIB, rm=True),
                _disk("vde", 30 * GIB),
            ]
        }
        # Le disque fixe passe avant l'amovible, même listé après.
        self.assertEqual(
            cfg.pick_install_disk(lsblk, self.UUID)["name"], "vde"
        )

    def test_unidentified_boot_medium_picks_nothing(self):
        # Clé dont les fichiers de l'ISO ont été copiés (pas d'UUID ISO)
        # et démontée par copytoram : elle ressemble à un disque fixe.
        lsblk = {
            "blockdevices": [
                _disk(
                    "sda",
                    32 * GIB,
                    children=[
                        {"name": "sda1", "type": "part", "uuid": "ABCD-1234"}
                    ],
                ),
                _disk("nvme0n1", 256 * GIB),
            ]
        }
        self.assertEqual(cfg.boot_disk_names(lsblk, self.UUID), set())
        self.assertIsNone(cfg.pick_install_disk(lsblk, self.UUID))
        self.assertIsNone(cfg.pick_install_disk(lsblk, ""))

    def test_main_auto_refuses_unidentified_boot_medium(self):
        lsblk = {"blockdevices": [_disk("vda", 40 * GIB)]}
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp) / "share"
            shutil.copytree(SHARE, share)
            (share / "profiles.json").write_text(json.dumps(_doc()))
            err = io.StringIO()
            with (
                mock.patch.object(cfg, "_read_lsblk", return_value=lsblk),
                mock.patch.object(
                    cfg, "_read_text", return_value="archisosearchuuid=x"
                ),
                contextlib.redirect_stderr(err),
            ):
                rc = cfg.main(
                    [
                        "--share-dir",
                        str(share),
                        "--auto",
                        "--output",
                        str(Path(tmp) / "c.json"),
                    ]
                )
            self.assertEqual(rc, 3)
            self.assertIn("boot medium not identified", err.getvalue())
            self.assertFalse((Path(tmp) / "c.json").exists())

    def test_no_candidate(self):
        lsblk = {"blockdevices": [_disk("vda", 8 * GIB)]}
        self.assertIsNone(cfg.pick_install_disk(lsblk, ""))

    def test_disk_layout_uefi(self):
        size = 40 * GIB
        layout = cfg.disk_layout("/dev/vda", size, 512, uefi=True)
        self.assertEqual(layout["config_type"], "default_layout")
        mod = layout["device_modifications"][0]
        self.assertEqual(mod["device"], "/dev/vda")
        self.assertTrue(mod["wipe"])
        boot, root = mod["partitions"]
        self.assertEqual(boot["mountpoint"], "/boot")
        self.assertEqual(boot["fs_type"], "fat32")
        self.assertEqual(boot["flags"], ["boot", "esp"])
        self.assertEqual(root["mountpoint"], "/")
        self.assertEqual(root["fs_type"], "ext4")
        self.assertEqual(boot["start"]["value"], 1)
        self.assertEqual(
            root["start"]["value"],
            boot["start"]["value"] + boot["size"]["value"],
        )
        end_mib = root["start"]["value"] + root["size"]["value"]
        self.assertLessEqual(end_mib, size // 1024**2 - 1)
        for part in (boot, root):
            self.assertEqual(part["status"], "create")
            self.assertEqual(part["size"]["unit"], "MiB")
            self.assertIsInstance(part["size"]["value"], int)
            self.assertEqual(part["size"]["sector_size"]["value"], 512)
        self.assertNotEqual(boot["obj_id"], root["obj_id"])

    def test_disk_layout_bios_and_too_small(self):
        layout = cfg.disk_layout("/dev/sda", 40 * GIB, 4096, uefi=False)
        boot = layout["device_modifications"][0]["partitions"][0]
        self.assertEqual(boot["flags"], ["boot"])
        self.assertEqual(boot["start"]["sector_size"]["value"], 4096)
        with self.assertRaises(ValueError):
            cfg.disk_layout("/dev/sda", 512 * 1024**2, 512, uefi=True)

    def test_auto_settings_and_disk_in_config(self):
        doc = _doc()
        disk = cfg.disk_layout("/dev/vda", 40 * GIB, 512, True)
        config = cfg.build_config(
            json.loads(TEMPLATE.read_text()),
            doc,
            cfg.find_profile(doc, "odoo18"),
            STAGE.read_text(),
            True,
            "/dev/ttyS0",
            "en",
            disk,
        )
        cfg.auto_settings(config)
        self.assertEqual(config["disk_config"], disk)
        self.assertEqual(config["timezone"], "UTC")
        self.assertEqual(config["locale_config"]["sys_lang"], "en_US.UTF-8")


@unittest.skipUnless(BASH, "bash absent")
class TestShellScripts(unittest.TestCase):
    def test_bash_syntax(self):
        for path in (INSTALLER, STAGE, TODO_LAUNCHER):
            subprocess.run([BASH, "-n", str(path)], check=True)

    @unittest.skipUnless(shutil.which("zsh"), "zsh absent")
    def test_zlogin_block_syntax(self):
        subprocess.run(["zsh", "-n", "-c", build_iso.ZLOGIN_BLOCK], check=True)

    def test_scripts_are_executable_in_repo(self):
        for path in (
            INSTALLER,
            CONFIG_TOOL,
            STAGE,
            UI_LAUNCHER,
            TODO_LAUNCHER,
        ):
            self.assertTrue(os.access(path, os.X_OK), path)

    def test_exit_marker_matches_install_monitor(self):
        marker = re.search(
            r'^EXIT_MARKER = "([^"]+)"', MONITOR.read_text(), re.M
        ).group(1)
        self.assertIn(f"EL_EXIT_MARKER={marker}\n", INSTALLER.read_text())

    def _bash(self, script, *args, env=None):
        return subprocess.run(
            [BASH, "-c", script, "_", *args],
            capture_output=True,
            text=True,
            env=env,
        )

    def _todo_launcher(
        self, tmp, fstype="tmpfs", mount_rc=0, lang="fr", env_var=None
    ):
        """Lance erplibre-todo sur un checkout inventé, findmnt et mount
        remplacés par des scripts qui lisent et écrivent la borne du tmpfs
        dans un fichier. `env_var` est le contenu initial de env_var.sh
        (absent si None). Rend (résultat, appels de mount, borne finale,
        dossier du checkout)."""
        tmp = Path(tmp)
        todo = tmp / "opt/erplibre"
        (todo / "script/todo").mkdir(parents=True)
        (todo / "conf").mkdir()
        if env_var is not None:
            (todo / "env_var.sh").write_text(env_var)
        (todo / "script/todo/todo.py").write_text(
            "import os, sys\nprint('TODO', os.getcwd(), sys.argv[1:])\n"
        )
        cow = tmp / "cowspace"
        cow.mkdir()
        borne = tmp / "borne"
        borne.write_text(str(256 * 1024**2))
        appels = tmp / "appels"
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "findmnt").write_text(
            "#!/bin/bash\n"
            'case "$*" in\n'
            f"  *FSTYPE*) echo {fstype} ;;\n"
            f"  *TARGET*) echo {cow} ;;\n"
            f"  *SIZE*) cat {borne} ;;\n"
            "esac\n"
        )
        (bin_dir / "mount").write_text(
            "#!/bin/bash\n"
            f'echo "$*" >>{appels}\n'
            f"[ {mount_rc} = 0 ] || exit {mount_rc}\n"
            'case "$2" in\n'
            f"  remount,size=75%) echo {6 * 1024**3} >{borne} ;;\n"
            f"  remount,size=*) echo ${{2#remount,size=}} >{borne} ;;\n"
            "esac\n"
        )
        for outil in ("findmnt", "mount"):
            (bin_dir / outil).chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            EL_TODO_DIR=str(todo),
            EL_PYTHON=sys.executable,
            EL_COWSPACE=str(cow),
            EL_LANG=lang,
        )
        res = subprocess.run(
            [BASH, str(TODO_LAUNCHER), "--essai"],
            capture_output=True,
            text=True,
            env=env,
        )
        faits = appels.read_text() if appels.exists() else ""
        return res, faits, int(borne.read_text()), todo

    def test_todo_launcher_grows_cowspace_and_starts_todo(self):
        with tempfile.TemporaryDirectory() as tmp:
            res, appels, borne, todo = self._todo_launcher(tmp)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn(f"TODO {todo} ['--essai']", res.stdout)
            self.assertEqual(appels, f"-o remount,size=75% {tmp}/cowspace\n")
            self.assertEqual(borne, 6 * 1024**3)
            self.assertEqual(
                (todo / "conf/python-erplibre-version").read_text(),
                "%d.%d\n" % sys.version_info[:2],
            )
            self.assertEqual(
                (todo / "env_var.sh").read_text(), 'EL_LANG="fr"\n'
            )

    def test_todo_launcher_replaces_checkout_language(self):
        # env_var.sh du dépôt porte déjà EL_LANG="fr", et todo_i18n le lit
        # avant l'environnement : la langue de l'accueil doit le remplacer.
        initial = '#!/bin/bash\nEL_LANG="fr"\nEL_AUTRE="x"\nEL_LANG="de"\n'
        with tempfile.TemporaryDirectory() as tmp:
            res, _appels, _borne, todo = self._todo_launcher(
                tmp, lang="en", env_var=initial
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(
                (todo / "env_var.sh").read_text(),
                '#!/bin/bash\nEL_LANG="en"\nEL_AUTRE="x"\nEL_LANG="de"\n',
            )

    def test_todo_launcher_leaves_other_filesystems_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            res, appels, borne, _todo = self._todo_launcher(tmp, "ext4")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(appels, "")
            self.assertEqual(borne, 256 * 1024**2)

    def test_todo_launcher_reports_a_failed_remount_and_goes_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            res, _appels, borne, _todo = self._todo_launcher(tmp, mount_rc=32)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("Live overlay not enlarged", res.stderr)
            self.assertIn("TODO", res.stdout)
            self.assertEqual(borne, 256 * 1024**2)

    def test_installer_param_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmdline = Path(tmp) / "cmdline"
            cmdline.write_text(
                "archisobasedir=arch erplibre.auto=home "
                "erplibre.nopoweroff console=ttyS0,115200\n"
            )
            env = dict(os.environ, EL_CMDLINE_FILE=str(cmdline))
            script = 'source "$1"; el_param "$2"'
            res = self._bash(script, str(INSTALLER), "erplibre.auto", env=env)
            self.assertEqual(res.stdout, "home\n")
            res = self._bash(
                script, str(INSTALLER), "erplibre.nopoweroff", env=env
            )
            self.assertEqual(res.stdout, "1\n")
            res = self._bash(
                script, str(INSTALLER), "erplibre.password", env=env
            )
            self.assertEqual(res.returncode, 1)
            self.assertEqual(res.stdout, "")

    def test_stage_find_user_and_service_unit(self):
        doc = _doc()
        with tempfile.TemporaryDirectory() as tmp:
            passwd = Path(tmp) / "passwd"
            passwd.write_text(
                "root:x:0:0::/root:/bin/bash\n"
                "nobody:x:65534:65534::/:/usr/bin/nologin\n"
                "postgres:x:968:968::/var/lib/postgres:/bin/bash\n"
                "alice:x:1000:1000::/home/alice:/bin/bash\n"
                "bob:x:1001:1001::/home/bob:/bin/bash\n"
            )
            unit_file = Path(tmp) / "erplibre.service"
            calls = Path(tmp) / "calls"
            script = (
                'source "$1"\n'
                f'systemctl() {{ echo "systemctl $*" >>{calls}; }}\n'
                "id() { echo grp-test; }\n"
                "el_find_user || exit 9\n"
                'echo "$EL_USER|$EL_HOME|$EL_DIR"\n'
                "EL_IN_CHROOT=1\n"
                "el_install_service || exit 8\n"
            )
            env = dict(
                os.environ,
                EL_PASSWD=str(passwd),
                EL_UNIT_FILE=str(unit_file),
                EL_UNIT_TEMPLATE=doc["service_unit"],
            )
            res = self._bash(script, str(STAGE), env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(
                res.stdout.strip(),
                "alice|/home/alice|/home/alice/git/erplibre",
            )
            unit = unit_file.read_text()
            self.assertIn("User=alice\n", unit)
            self.assertIn("Group=grp-test\n", unit)
            self.assertIn(
                "ExecStart=/bin/bash /home/alice/git/erplibre/run.sh\n", unit
            )
            self.assertIn("WorkingDirectory=/home/alice/git/erplibre\n", unit)
            self.assertNotIn("$", unit)
            # Dans le chroot : « enable » seul, aucun « start ».
            self.assertEqual(
                calls.read_text(), "systemctl enable erplibre.service\n"
            )

    def test_stage_without_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            passwd = Path(tmp) / "passwd"
            passwd.write_text("root:x:0:0::/root:/bin/bash\n")
            env = dict(os.environ, EL_PASSWD=str(passwd))
            res = self._bash(
                'source "$1"; el_find_user; echo "rc=$? user=$EL_USER"',
                str(STAGE),
                env=env,
            )
            self.assertEqual(res.stdout.strip(), "rc=1 user=")

    @unittest.skipUnless(BASH, "bash absent")
    def test_stage_profile_env_and_reap_only_in_chroot(self):
        # runuser et pkill bouchonnés : on lit ce qu'ils auraient reçu.
        script = (
            'source "$1"; runuser() { printf "%s\\n" "$@"; }; '
            'pkill() { echo "pkill $*"; }; '
            "EL_USER=compte-test; EL_HOME=/nulle-part; EL_PROFILE_CMD=true; "
            'el_run_profile; EL_IN_CHROOT="$2"; el_reap_user'
        )
        res = self._bash(script, str(STAGE), "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = res.stdout.splitlines()
        self.assertIn("GIO_USE_VFS=local", lines)
        self.assertIn("GVFS_DISABLE_FUSE=1", lines)
        self.assertIn("pkill -KILL -u compte-test", lines)
        # Hors chroot : même environnement, aucun processus tué.
        res = self._bash(script, str(STAGE), "0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("GIO_USE_VFS=local", res.stdout.splitlines())
        self.assertNotIn("pkill", res.stdout)

    def test_installer_refuses_second_auto_run_in_same_boot(self):
        # el_auto bouchonné : on ne lit que la décision d'el_main.
        with tempfile.TemporaryDirectory() as tmp:
            cmdline = Path(tmp) / "cmdline"
            cmdline.write_text("erplibre.auto=gnome erplibre.nopoweroff\n")
            flag = Path(tmp) / "started"
            env = dict(
                os.environ,
                EL_CMDLINE_FILE=str(cmdline),
                EL_STARTED_FLAG=str(flag),
            )
            script = 'source "$1"; el_auto() { echo AUTO; }; el_main'
            res = self._bash(script, str(INSTALLER), env=env)
            self.assertEqual(res.stdout.splitlines(), ["AUTO"])
            self.assertTrue(flag.exists())
            res = self._bash(script, str(INSTALLER), env=env)
            self.assertEqual(res.returncode, 1)
            self.assertNotIn("AUTO", res.stdout)
            self.assertNotIn("erplibre-install", res.stdout)

    def test_auto_mode_refused_without_autotest_marker(self):
        # L'ISO d'installation ne porte pas la marque : « erplibre.auto »
        # tapé à la main n'efface rien et ne crée aucun compte.
        with tempfile.TemporaryDirectory() as tmp:
            cmdline = Path(tmp) / "cmdline"
            cmdline.write_text("erplibre.auto=gnome erplibre.nopoweroff\n")
            env = dict(
                os.environ,
                EL_CMDLINE_FILE=str(cmdline),
                EL_AUTOTEST_MARKER=str(Path(tmp) / "absente"),
                EL_RUN=str(Path(tmp) / "run"),
            )
            script = (
                'source "$1"; EL_SERIAL=/dev/null; EL_TARGET="$2"; '
                "sync() { :; }; el_wait_boot() { echo ATTENTE; }; "
                "archinstall() { echo ARCHINSTALL; }; el_auto"
            )
            res = self._bash(script, str(INSTALLER), tmp, env=env)
            self.assertIn("__ERPLIBRE_EXIT__ 22", res.stdout)
            self.assertNotIn("ATTENTE", res.stdout)
            self.assertNotIn("ARCHINSTALL", res.stdout)

    def test_core_auto_waits_for_network_unless_offline_requested(self):
        # Les réponses décident, pas la clé : hors ligne demandé, le cœur
        # est lancé tout de suite (il refuse lui-même un paquet absent) ;
        # en ligne, réseau et trousseau sont attendus même si la clé porte
        # un paquet.
        with tempfile.TemporaryDirectory() as tmp:
            for demande, attendu in ((0, False), (1, True)):
                coeur = Path(tmp) / f"coeur{demande}"
                coeur.write_text(
                    "#!/bin/bash\n"
                    'echo "CORE $*"\n'
                    '[[ " $* " == *" --offline-requested "* ]] && '
                    f"exit {demande}\n"
                    "exit 0\n"
                )
                coeur.chmod(0o755)
                script = (
                    'source "$1"; EL_CORE="$2"; EL_SERIAL=/dev/null; '
                    "el_wait_boot() { echo ATTENTE; }; "
                    "el_wait_network() { echo RESEAU; return 0; }; "
                    "el_auto_poweroff() { :; }; el_core_auto"
                )
                res = self._bash(script, str(INSTALLER), str(coeur))
                self.assertEqual(res.returncode, 0, res.stderr)
                lignes = res.stdout.splitlines()
                self.assertIn("CORE --auto --offline-requested", lignes)
                self.assertIn("CORE --auto --serial /dev/null", lignes)
                self.assertEqual("RESEAU" in lignes, attendu, lignes)
                self.assertEqual("ATTENTE" in lignes, attendu, lignes)

    def test_auto_mode_password_and_creds_never_persist(self):
        # Outil de configuration et archinstall bouchonnés : le mot de
        # passe arrive par l'environnement, pas par argv, et le fichier
        # --creds, sous EL_RUN, a disparu quand archinstall rend la main.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            marque = tmp / "autotest"
            marque.write_text("gnome\n")
            cmdline = tmp / "cmdline"
            cmdline.write_text(
                "erplibre.auto=gnome erplibre.password=mdp-invente "
                "erplibre.nopoweroff\n"
            )
            outil = tmp / "outil"
            outil.write_text(
                "#!/bin/bash\n"
                f'printf "%s\\n" "$*" >{tmp}/argv\n'
                "while [[ $# -gt 0 ]]; do [[ $1 == --creds ]] && c=$2; "
                "shift; done\n"
                'printf "%s" "$ERPLIBRE_AUTO_PASSWORD" >"$c"\n'
                'printf "/dev/vdz\\t0\\n"\n'
            )
            outil.chmod(0o755)
            env = dict(
                os.environ,
                EL_CMDLINE_FILE=str(cmdline),
                EL_AUTOTEST_MARKER=str(marque),
                EL_RUN=str(tmp / "run"),
            )
            script = (
                'source "$1"; EL_SERIAL=/dev/null; EL_TARGET="$2"; '
                'EL_WORK="$2/work"; EL_CONFIG_TOOL="$2/outil"; '
                "sync() { :; }; el_wait_boot() { :; }; "
                "el_wait_network() { :; }; "
                'archinstall() { cat "$EL_CREDS"; echo; }; el_auto'
            )
            res = self._bash(script, str(INSTALLER), str(tmp), env=env)
            self.assertIn("mdp-invente", res.stdout)
            self.assertIn("__ERPLIBRE_EXIT__ 0", res.stdout)
            self.assertNotIn("mdp-invente", (tmp / "argv").read_text())
            self.assertIn(f"--creds {tmp}/run/", (tmp / "argv").read_text())
            self.assertEqual(list((tmp / "run").iterdir()), [])

    def test_auto_end_hint_never_suggests_relaunch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmdline = Path(tmp) / "cmdline"
            cmdline.write_text("erplibre.auto=gnome erplibre.nopoweroff\n")
            env = dict(os.environ, EL_CMDLINE_FILE=str(cmdline))
            script = (
                'source "$1"; EL_SERIAL=/dev/null; EL_TARGET="$2"; '
                "sync() { :; }; el_auto_end 0"
            )
            res = self._bash(script, str(INSTALLER), tmp, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("__ERPLIBRE_EXIT__ 0", res.stdout)
            self.assertNotIn("erplibre-install", res.stdout)

    @unittest.skipUnless(BASH, "bash absent")
    def test_stage_opens_tmp_only_in_chroot(self):
        # Le /tmp du service d'arch-chroot -S est en 0755 : le compte n'y
        # crée rien tant que l'étape ne l'a pas ouvert.
        script = (
            'source "$1"; EL_TMP_DIR="$2"; EL_IN_CHROOT="$3"; '
            'el_chroot_tmp; stat -c %a "$2"'
        )
        for in_chroot, mode in (("1", "1777"), ("0", "755")):
            with tempfile.TemporaryDirectory() as tmp:
                os.chmod(tmp, 0o755)
                res = self._bash(script, str(STAGE), tmp, in_chroot)
                self.assertEqual(res.stdout.strip(), mode, in_chroot)

    @unittest.skipUnless(BASH, "bash absent")
    def test_stage_copies_output_to_console_only_in_chroot(self):
        # Sous archinstall la sortie de l'étape est un pty que personne ne
        # lit : la copie vers EL_TTY dépend du chroot, pas de « -t 1 ».
        script = (
            'source "$1"; EL_LOG="$2"; EL_TTY="$3"; EL_IN_CHROOT="$4"; '
            "el_setup_output; echo ligne-test; el_flush_output"
        )
        for in_chroot, expected in (("1", "ligne-test\n"), ("0", "")):
            with tempfile.TemporaryDirectory() as tmp:
                log, tty = Path(tmp) / "log", Path(tmp) / "tty"
                tty.write_text("")
                self._bash(script, str(STAGE), str(log), str(tty), in_chroot)
                self.assertEqual(log.read_text(), "ligne-test\n")
                self.assertEqual(tty.read_text(), expected, in_chroot)


if __name__ == "__main__":
    unittest.main()
