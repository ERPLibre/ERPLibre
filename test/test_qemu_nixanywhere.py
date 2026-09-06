#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Nix et nixos-anywhere posés dans une VM qui n'est pas NixOS.

L'option donne à une VM ordinaire — Debian, Arch, Fedora, openSUSE — le
gestionnaire de paquets de NixOS à côté du sien, et l'installateur qui s'en
sert pour porter NixOS sur une AUTRE machine, jointe par SSH.

Ce que ces tests gardent :

- l'option n'est pas offerte sur NixOS, où nix EST le système : elle n'y
  aurait rien à poser ;
- elle n'est offerte que là où l'amont bâtit, amd64 et arm64 ;
- aucune pose ne peut PENDRE : « || true » couvre l'échec, pas l'attente
  d'une réponse que personne ne donnera sur un SSH sans terminal ;
- nix est appelé par son CHEMIN ABSOLU — le PATH du shell distant a été figé
  avant que l'installateur ne pose quoi que ce soit ;
- les fonctions expérimentales sont redonnées sur la ligne de commande :
  l'écriture dans /etc/nix/nix.conf demande sudo et peut échouer, l'appel
  doit réussir quand même ;
- le disque annoncé grandit de ce que le store réclame, faute de quoi la VM
  se remplit pendant l'installation.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
SPEC = TODO._QEMU_VM_TOOLS["nixanywhere"]


class LOption(unittest.TestCase):
    def test_it_needs_no_desktop(self):
        """C'est un outil de ligne de commande : une VM serveur le prend."""
        self.assertFalse(SPEC["needs_desktop"])
        self.assertEqual((), SPEC["desktops"])

    def test_it_is_posed_before_the_clone(self):
        """Comme les autres poses amont : l'outil se garde lui-même et ne
        fait échouer ni les autres ni l'installation d'ERPLibre."""
        self.assertEqual("before", SPEC["phase"])

    def test_it_is_not_offered_on_nixos(self):
        """Sur NixOS, nix est déjà là — l'option n'y a pas de sens."""
        self.assertEqual(
            [], TODO._qemu_tools_for(("nixanywhere",), "amd64", "", "nixos")
        )

    def test_it_is_offered_on_the_imperative_distributions(self):
        for distro in ("debian", "ubuntu", "arch", "fedora", "opensuse"):
            with self.subTest(distro=distro):
                self.assertEqual(
                    ["nixanywhere"],
                    TODO._qemu_tools_for(
                        ("nixanywhere",), "amd64", "", distro
                    ),
                )

    def test_it_is_bounded_to_the_architectures_nix_builds_for(self):
        """Ailleurs, cocher la case poserait un installateur qui s'arrête."""
        self.assertEqual(("amd64", "arm64"), SPEC["arches"])
        self.assertEqual(
            [], TODO._qemu_tools_for(("nixanywhere",), "s390x", "", "debian")
        )

    def test_the_disk_grows_by_what_the_store_asks(self):
        """Le store porte la fermeture d'un système NixOS complet et le noyau
        kexec : la VM se remplirait pendant l'installation."""
        self.assertEqual(8, SPEC["disk_gb"])
        sans = TODO._qemu_tools_disk_gb((), "amd64", "", "debian")
        avec = TODO._qemu_tools_disk_gb(
            ("nixanywhere",), "amd64", "", "debian"
        )
        self.assertEqual(sans + 8, avec)


class LaCommandeDistante(unittest.TestCase):
    def setUp(self):
        self.cmd = TODO.__new__(TODO)._qemu_nixanywhere_remote_cmd()

    def test_no_pose_can_hang(self):
        """« || true » couvre l'ÉCHEC, pas l'ATTENTE."""
        bornees = [x for x in self.cmd.split("; ") if "timeout " in x]
        self.assertGreaterEqual(len(bornees), 2)
        for morceau in bornees:
            self.assertIn("</dev/null", morceau)
            self.assertIn("|| true", morceau)

    def test_the_installer_is_told_not_to_ask(self):
        """Sans « --yes », il attend une confirmation ; sans « --daemon », il
        installe en mono-utilisateur et /nix appartient à qui a installé."""
        self.assertIn("--daemon", self.cmd)
        self.assertIn("--yes", self.cmd)

    def test_nix_is_called_by_absolute_path(self):
        """Le PATH du shell distant a été figé à son ouverture, avant que
        l'installateur ne pose le binaire : « nix » nu rendrait 127 sans dire
        que rien n'a été installé."""
        self.assertIn("/nix/var/nix/profiles/default/bin/nix", self.cmd)

    def test_the_flake_features_are_given_on_the_command_line_too(self):
        """L'écriture dans /etc/nix/nix.conf demande sudo et peut échouer ;
        sans ces fonctions, « nix profile install github:… » refuse la
        référence."""
        self.assertIn("--extra-experimental-features", self.cmd)
        self.assertIn("nix-command flakes", self.cmd)

    def test_the_conf_line_is_written_once(self):
        """Sans le grep, chaque redéploiement d'une même VM rallonge
        /etc/nix/nix.conf d'une ligne identique."""
        self.assertIn("grep -qF 'experimental-features", self.cmd)

    def test_the_rc_line_is_written_once(self):
        """Même invariant sur ~/.bashrc."""
        self.assertIn("grep -qF 'for f in /etc/profile.d/nix.sh", self.cmd)

    def test_both_profile_scripts_are_sourced(self):
        """L'installateur écrit l'un OU l'autre selon sa version."""
        self.assertIn("/etc/profile.d/nix.sh", self.cmd)
        self.assertIn("/etc/profile.d/nix-daemon.sh", self.cmd)

    def test_the_verdict_looks_at_the_binary(self):
        """Toutes les poses rendent 0 par construction : leur code de retour
        ne dit rien de ce qui a été installé."""
        self.assertIn("$HOME/.nix-profile/bin/nixos-anywhere", self.cmd)

    def test_it_returns_zero_when_everything_fails(self):
        """La phase « before » ne doit pas emporter l'installation : sous
        « set -e », une seule commande non gardée y suffirait.

        Le bloc est joué pour de vrai, avec les commandes qui SORTENT de la
        machine remplacées par un échec — un test unitaire ne télécharge rien
        et n'écrit rien hors de son répertoire temporaire."""
        neutre = (
            "curl(){ return 1; }; sudo(){ return 1; }; "
            "timeout(){ return 1; }; systemctl(){ return 1; }; "
        )
        with tempfile.TemporaryDirectory() as maison:
            fini = subprocess.run(
                ["bash", "-c", "set -e; " + neutre + self.cmd],
                capture_output=True,
                text=True,
                env={"PATH": os.environ["PATH"], "HOME": maison},
            )
            self.assertEqual(0, fini.returncode, fini.stderr)
            rc = Path(maison, ".bashrc")
            self.assertIn("/etc/profile.d/nix.sh", rc.read_text())

    def test_it_is_valid_shell(self):
        """Une commande mal citée casse tout le bloc des outils, pas
        seulement le sien."""
        fini = subprocess.run(
            ["bash", "-n"],
            input="{ " + self.cmd + " }",
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)

    def test_it_reaches_the_block_of_the_checked_tools(self):
        """Déclarer l'outil sans le brancher le laisserait cochable et sans
        effet."""
        todo = TODO.__new__(TODO)
        bloc = todo._qemu_tools_remote_cmd(("nixanywhere",))
        self.assertIn("nixos-anywhere", bloc)
        self.assertNotIn("nixos-anywhere", todo._qemu_tools_remote_cmd(()))


class LesLibelles(unittest.TestCase):
    def test_every_string_shown_is_translated(self):
        """Le libellé, l'indice et chaque ligne du « ? » : les deux langues
        sont obligatoires."""
        for cle in (SPEC["label"], SPEC["hint"], *SPEC["help"]):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))

    def test_the_help_says_what_the_tool_is_for(self):
        """Le « ? » d'une option nomme ce qu'elle installe ET ce qu'elle
        permet : nix seul ne dit pas qu'on installera NixOS ailleurs."""
        aide = " ".join(SPEC["help"]).lower()
        self.assertIn("nixos-anywhere", aide)
        self.assertIn("ssh", aide)


if __name__ == "__main__":
    unittest.main()
