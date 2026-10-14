#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Home en VM : les deux cases et le profil sans Odoo.

Une seule autorité installe ERPLibre Home :
script/install/install_erplibre_home.sh. La case « erplibre_home » l'appelle
pour la base, la case « erplibre_home_streamdeck » avec --stream-deck, pour
le niveau Stream Deck, base comprise. Les deux passent APRÈS l'installation,
dans le checkout de la VM, quel que soit le profil ; le profil « ERPLibre
Home (no Odoo) » appelle la base SEULE, sans « make install_os ».

Ce que ces tests gardent :

- les deux cases sont au catalogue, juste après « gnome_ext », bornées à
  GNOME, à amd64 et aux quatre familles impératives, et chaque chaîne
  affichée existe dans les deux langues ;
- chaque bloc appelle sa commande DANS le checkout, lié par « && » :
  ERPLibre Home qui ne s'installe pas fait échouer la VM ;
- cochées ensemble, seule la commande du Stream Deck passe : elle inclut la
  base ;
- le profil est offert juste après « ERPLibre mobile (home) » et lance la
  base seule, après le bureau ;
- ce profil ne pose aucun service Odoo et n'annonce aucune cible make, mais
  la VM garde la marge du bureau et celle du checkout cloné.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS, t  # noqa: E402

BASE = "erplibre_home"
DECK = "erplibre_home_streamdeck"
OUTILS = (BASE, DECK)
INSTALLEUR = "./script/install/install_erplibre_home.sh"
STREAM_DECK = INSTALLEUR + " --stream-deck"
# La commande que chaque case lance, et son option.
COMMANDES = {BASE: INSTALLEUR, DECK: STREAM_DECK}
OPTIONS = {BASE: "", DECK: "--stream-deck"}
PROFIL = "ERPLibre Home (no Odoo)"


def bash_n(script):
    """« bash -n » : le shell accepte-t-il ce script, sans l'exécuter ?"""
    return subprocess.run(
        ["bash", "-n"],
        input="mstep() { :; }; mdiag() { :; };\n" + script,
        capture_output=True,
        text=True,
    )


class LesCases(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_they_follow_the_gnome_extensions(self):
        """Le formulaire suit l'ordre du catalogue : les cases qui touchent
        aux extensions GNOME se lisent ensemble, la base d'abord."""
        keys = [k for k, _l, _h in TODO._qemu_vm_tool_choices()]
        rang = keys.index("gnome_ext")
        self.assertEqual(rang + 1, keys.index(BASE))
        self.assertEqual(rang + 2, keys.index(DECK))

    def test_they_run_after_the_clone(self):
        """L'installateur vit dans le dépôt : il n'existe qu'après le clone."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                self.assertEqual("after", TODO._QEMU_VM_TOOLS[outil]["phase"])

    def test_they_need_a_gnome_desktop(self):
        """L'extension vise GNOME Shell : sans lui, l'installateur rend 2."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                spec = TODO._QEMU_VM_TOOLS[outil]
                self.assertTrue(spec["needs_desktop"])
                self.assertEqual(("gnome",), spec["desktops"])
                self.assertEqual(
                    [outil],
                    self.todo._qemu_tools_for(
                        (outil,), "amd64", "gnome", "ubuntu"
                    ),
                )
                for bureau in ("", "cinnamon"):
                    self.assertEqual(
                        [],
                        self.todo._qemu_tools_for(
                            (outil,), "amd64", bureau, "ubuntu"
                        ),
                    )

    def test_they_are_amd64_only(self):
        for outil in OUTILS:
            with self.subTest(outil=outil):
                self.assertEqual(
                    ("amd64",), TODO._QEMU_VM_TOOLS[outil]["arches"]
                )
                self.assertEqual(
                    [],
                    self.todo._qemu_tools_for(
                        (outil,), "arm64", "gnome", "ubuntu"
                    ),
                )

    def test_every_imperative_family_gets_them(self):
        """L'installateur connaît apt, dnf, zypper et pacman ; NixOS n'a pas
        de chemin de bureau GNOME dans l'installateur QEMU."""
        for outil in OUTILS:
            self.assertEqual(
                ("apt", "dnf", "pacman", "zypper"),
                TODO._QEMU_VM_TOOLS[outil]["families"],
            )
            for distro in (
                "ubuntu",
                "debian",
                "fedora",
                "almalinux",
                "rocky",
                "opensuse",
                "arch",
            ):
                with self.subTest(outil=outil, distro=distro):
                    self.assertEqual(
                        [outil],
                        self.todo._qemu_tools_for(
                            (outil,), "amd64", "gnome", distro
                        ),
                    )
            self.assertEqual(
                [],
                self.todo._qemu_tools_for((outil,), "amd64", "gnome", "nixos"),
            )

    def test_their_disk_cost_is_counted_in_the_plan(self):
        """La base : quelques paquets et les traductions. Le Stream Deck : le
        venv en plus, opencv-python et Pillow."""
        sans = self.todo._qemu_tools_disk_gb((), "amd64", "gnome", "ubuntu")
        for outil, taille in ((BASE, 1), (DECK, 2)):
            with self.subTest(outil=outil):
                self.assertEqual(taille, TODO._QEMU_VM_TOOLS[outil]["disk_gb"])
                avec = self.todo._qemu_tools_disk_gb(
                    (outil,), "amd64", "gnome", "ubuntu"
                )
                self.assertEqual(sans + taille, avec)


class LesBlocs(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_each_calls_its_command_in_the_checkout(self):
        """L'installateur se place lui-même à la racine du checkout ; le bloc
        y entre quand même, pour que le chemin relatif du profil et celui des
        cases soient la même commande."""
        for prod, racine in (
            (False, "$HOME/git/erplibre"),
            (True, "/opt/erplibre"),
        ):
            with self.subTest(prod=prod):
                base = self.todo._qemu_erplibre_home_remote_cmd(prod)
                self.assertIn(f'cd "{racine}" && {INSTALLEUR})', base)
                self.assertNotIn("--stream-deck", base)
                deck = self.todo._qemu_erplibre_home_remote_cmd(
                    prod, stream_deck=True
                )
                self.assertIn(f'cd "{racine}" && {STREAM_DECK})', deck)

    def test_the_after_phase_reaches_each(self):
        """Déclarer l'outil sans le brancher le laisserait cochable et sans
        effet. Seul, il n'entraîne pas le SDK Android."""
        for outil, commande in COMMANDES.items():
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_after_remote_cmd((outil,), False)
                self.assertIn(commande + ")", cmd)
                self.assertNotIn("sdkmanager", cmd)
        self.assertNotIn(INSTALLEUR, self.todo._qemu_after_remote_cmd(()))

    def test_both_ticked_run_the_stream_deck_command_only(self):
        """Le niveau Stream Deck inclut la base : la lancer avant lui
        serait une installation de trop."""
        cmd = self.todo._qemu_after_remote_cmd((BASE, DECK), False)
        self.assertEqual(1, cmd.count(INSTALLEUR))
        self.assertIn(STREAM_DECK, cmd)

    def test_they_are_not_posed_before_the_clone(self):
        for outil in OUTILS:
            with self.subTest(outil=outil):
                self.assertEqual(
                    "",
                    self.todo._qemu_tools_remote_cmd(
                        (outil,), False, "before"
                    ),
                )

    def test_they_come_after_forgejo_and_before_the_android_sdk(self):
        """Quelques minutes de paquets et de venv : après la minute de
        Forgejo, avant l'heure du SDK. Un échec rapide se voit tôt."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_after_remote_cmd(
                    ("forgejo", outil, "mobile"), False
                )
                self.assertLess(
                    cmd.index("install_forgejo.sh"), cmd.index(INSTALLEUR)
                )
                self.assertLess(cmd.index(INSTALLEUR), cmd.index("gradlew"))

    def test_a_failure_still_fails_the_vm(self):
        """Lié par « && », jamais par « ; » ni gardé par « || true » : une VM
        qui devait recevoir ERPLibre Home et ne l'a pas reçu n'est pas la VM
        demandée."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_after_remote_cmd(
                    (outil, "mobile"), False
                )
                entre = cmd[
                    cmd.index(INSTALLEUR) : cmd.index("ERPLibre mobile")
                ]
                self.assertIn("&&", entre)
                self.assertNotIn("|| true", entre)

    def _joue(self, outil, code):
        """Joue la phase « after » comme la chaîne d'installation la lie, avec
        un installateur doublure qui note son répertoire et ses options, et
        rend `code`. Rend (résultat, répertoire vu, options vues, dépôt)."""
        cmd = self.todo._qemu_after_remote_cmd((outil,), False)
        with tempfile.TemporaryDirectory() as maison:
            depot = Path(maison) / "git" / "erplibre"
            script = depot / "script" / "install" / "install_erplibre_home.sh"
            script.parent.mkdir(parents=True)
            script.write_text(
                "#!/bin/bash\n"
                'pwd > "$HOME/vu"\n'
                'echo "$*" > "$HOME/options"\n'
                f"exit {code}\n"
            )
            script.chmod(0o755)
            res = subprocess.run(
                ["bash", "-c", "set -e; true && { " + cmd + " }"],
                capture_output=True,
                text=True,
                cwd=maison,
                env={"PATH": os.environ["PATH"], "HOME": maison},
            )
            vu = (Path(maison) / "vu").read_text().strip()
            options = (Path(maison) / "options").read_text().strip()
            return res, vu, options, str(depot)

    def test_the_installer_runs_from_the_checkout_with_its_option(self):
        for outil, option in OPTIONS.items():
            with self.subTest(outil=outil):
                res, vu, options, depot = self._joue(outil, 0)
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertEqual(os.path.realpath(depot), os.path.realpath(vu))
                self.assertEqual(option, options)

    def test_its_exit_code_is_the_vm_verdict(self):
        """Le code 2 d'un système non pris en charge remonte tel quel : le
        tableau de bord le lit pour peindre la VM en rouge."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                res, _vu, _options, _depot = self._joue(outil, 2)
                self.assertEqual(2, res.returncode, res.stdout + res.stderr)

    def test_valid_shell_in_every_combination(self):
        for tools in (
            (BASE,),
            (DECK,),
            (BASE, DECK),
            (BASE, "forgejo"),
            ("aidev", "forgejo", BASE, DECK, "mobile", "avd"),
        ):
            with self.subTest(tools=tools):
                res = bash_n(self.todo._qemu_after_remote_cmd(tools, True))
                self.assertEqual(0, res.returncode, res.stderr)

    def test_a_desktop_only_vm_names_them_as_skipped(self):
        """Sans clone, l'installateur n'existe pas : une case cochée est
        NOMMÉE plutôt qu'écartée en silence."""
        cmd = self.todo._qemu_erplibre_remote_cmd(
            None, None, False, "gnome", "", "deb", OUTILS
        )
        self.assertIn(t("needs the ERPLibre install, skipped:"), cmd)
        self.assertIn(f"{BASE} {DECK}", cmd)
        self.assertNotIn(INSTALLEUR, cmd)

    def test_with_an_odoo_profile_they_come_after_the_make(self):
        for outil in OUTILS:
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_erplibre_remote_cmd(
                    "develop", None, False, "gnome", "", "deb", (outil,)
                )
                self.assertLess(
                    cmd.index("make install_os"), cmd.index(INSTALLEUR)
                )
                self.assertEqual(0, bash_n(cmd).returncode)


class LeProfil(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.profils = self.todo._qemu_install_profiles()
        self.libelle = t(PROFIL)

    def test_it_is_offered_and_runs_the_base_alone(self):
        """Ni « make install_os » ni Odoo ni --stream-deck : l'installateur
        apporte ses paquets, et la VM est prête en quelques minutes."""
        self.assertEqual(INSTALLEUR, dict(self.profils)[self.libelle])

    def test_it_follows_the_mobile_profile(self):
        libelles = [libelle for libelle, _cmd in self.profils]
        self.assertEqual(
            libelles.index(t("ERPLibre mobile (home)")) + 1,
            libelles.index(self.libelle),
        )

    def test_odoo_stays_the_default(self):
        """Ajouter un profil ne doit pas déplacer le défaut de la réponse
        vide, le premier de la liste."""
        self.assertIn("install_odoo_18", self.profils[0][1])

    def test_the_vm_gets_the_desktop_first_and_no_odoo_service(self):
        """Le bureau est posé avant la commande du profil, sans quoi
        l'installateur ne trouve pas gnome-shell. Aucune cible install_odoo :
        aucun service erplibre.service."""
        cmd = self.todo._qemu_erplibre_remote_cmd(
            "develop", INSTALLEUR, False, "gnome", "", "deb", ()
        )
        self.assertIn(f"cd ~/git/erplibre && {INSTALLEUR}", cmd)
        self.assertLess(
            cmd.index(t("Installing the desktop (long):")),
            cmd.index(INSTALLEUR),
        )
        self.assertNotIn("make install_os", cmd)
        self.assertNotIn("erplibre.service", cmd)
        self.assertNotIn("--stream-deck", cmd)
        self.assertEqual(0, bash_n(cmd).returncode)

    def _avec(self, outil):
        return self.todo._qemu_erplibre_remote_cmd(
            "develop", INSTALLEUR, False, "gnome", "", "deb", (outil,)
        )

    def test_the_base_tool_with_the_profile_runs_it_twice(self):
        """Le second passage ne change rien : l'installateur est idempotent.
        Le bloc de la case n'est pas retiré pour autant — il porterait sinon
        une exception par profil."""
        cmd = self._avec(BASE)
        self.assertEqual(2, cmd.count(INSTALLEUR))
        self.assertNotIn("--stream-deck", cmd)

    def test_the_stream_deck_tool_adds_its_level_to_the_profile(self):
        """La base du profil d'abord ; la case n'y ajoute que le niveau
        Stream Deck, ses étapes de base n'ayant plus rien à faire."""
        cmd = self._avec(DECK)
        self.assertEqual(2, cmd.count(INSTALLEUR))
        self.assertEqual(1, cmd.count(STREAM_DECK))
        self.assertLess(
            cmd.index(f"cd ~/git/erplibre && {INSTALLEUR}"),
            cmd.index(STREAM_DECK),
        )

    def test_no_make_target_is_announced(self):
        """Le guide de connexion s'arrête à « git pull »."""
        self.assertEqual("", self.todo._qemu_make_target(INSTALLEUR))

    def test_the_checkout_is_still_cloned(self):
        """Le profil installe DEPUIS le dépôt : il le clone, et le guide le
        nomme. Il n'entre donc pas dans les commandes sans ERPLibre."""
        self.assertTrue(
            self.todo._qemu_installs_erplibre("develop", INSTALLEUR)
        )
        self.assertNotIn(INSTALLEUR, self.todo._qemu_no_erplibre_cmds())

    def _parts(self, bureau):
        vm = {
            "name": "essai",
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "vcpus": 2,
            "ram": 4096,
            "disk": "20G",
            "desktop": bureau,
            "branch": "",
            "install_cmd": INSTALLEUR,
            "install_label": self.libelle,
        }
        spec = {
            "vms": [vm],
            "existing": [],
            "ssh_key": "",
            "timezone": "",
            "desktop": bureau,
            "vm_tools": (),
            "python_provider": "",
            "app_store": "deb",
            "install": {
                "branch": "develop",
                "prod": False,
                "label": self.libelle,
                "monitor": True,
                "cmd": INSTALLEUR,
            },
        }
        return self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def test_the_disk_keeps_the_desktop_and_checkout_margins(self):
        parts = self._parts("gnome")
        attendu = (
            20 + TODO.ERPLIBRE_EXTRA_DISK_GB + TODO.QEMU_DESKTOP_EXTRA_DISK_GB
        )
        self.assertEqual(f"{attendu}G", parts[parts.index("--disk-size") + 1])
        self.assertIn("--erplibre-dir", parts)
        self.assertNotIn("--erplibre-make", parts)


class LesLibelles(unittest.TestCase):
    def test_every_string_shown_is_translated(self):
        """Le libellé, l'indice, chaque ligne du « ? » et le profil : les
        deux langues sont obligatoires."""
        cles = [PROFIL]
        for outil in OUTILS:
            spec = TODO._QEMU_VM_TOOLS[outil]
            cles += [spec["label"], spec["hint"], *spec["help"]]
        for cle in cles:
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))

    def test_each_label_names_its_level(self):
        self.assertEqual("ERPLibre Home", TODO._QEMU_VM_TOOLS[BASE]["label"])
        self.assertEqual(
            "ERPLibre Home Stream Deck", TODO._QEMU_VM_TOOLS[DECK]["label"]
        )

    def test_the_help_names_the_command_and_the_logout(self):
        """GNOME Shell ne charge une extension neuve qu'au début d'une session
        sous Wayland : le « ? » le dit avant qu'on cherche une panne."""
        for outil, commande in COMMANDES.items():
            with self.subTest(outil=outil):
                aide = " ".join(TODO._QEMU_VM_TOOLS[outil]["help"])
                self.assertIn(commande[2:] + " in the VM's checkout", aide)
                self.assertIn("log out", aide)
        self.assertNotIn(
            "--stream-deck", " ".join(TODO._QEMU_VM_TOOLS[BASE]["help"])
        )


if __name__ == "__main__":
    unittest.main()
