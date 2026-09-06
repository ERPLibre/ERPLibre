#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long qui installe ERPLibre sur NixOS.

Lui crée une VM et prend des heures ; ceux-ci gardent sa forme en quelques
millisecondes. Ce qu'ils tiennent :

- il envoie la commande du MENU, pas une chaîne à lui. Un test qui
  installerait par ses propres soins prouverait SON chemin, et c'est
  précisément là que se cachaient les pannes ;
- le verdict porte sur l'ÉTAT de la machine, pas sur un code de retour :
  « nixos-rebuild switch » rend 4 sur un système pourtant activé, et chaque
  bloc d'outil du menu rend 0 par construction ;
- l'installation part en UNE session ssh, comme le déploiement le fait. C'est
  la condition qui expose la panne du premier passage — celle qui disparaît
  dès qu'on rejoue dans une session neuve ;
- il est dans long_test/ et le lanceur unitaire ne le ramasse pas ;
- « --dry-run » ne crée rien et le dit.
"""

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "long_test/install_nixos.py"
SRC = SCRIPT.read_text(encoding="utf-8")


class LaPlace(unittest.TestCase):
    def test_it_lives_out_of_the_unit_runner(self):
        """Le lanceur balaie « test/test_*.py » et doit rester lançable en
        quelques secondes, même sans virtualisation."""
        self.assertTrue(SCRIPT.exists())
        self.assertFalse((RACINE / "test/test_install_nixos_long.py").exists())

    def test_it_is_executable(self):
        """Le menu et le README l'appellent directement."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_parses(self):
        ast.parse(SRC)


class LeCheminEprouve(unittest.TestCase):
    def test_the_install_command_comes_from_the_menu(self):
        """Deux copies d'une chaîne d'installation divergent, et c'est la
        copie du test qui reste verte pendant que le produit casse."""
        self.assertIn("_qemu_erplibre_remote_cmd", SRC)
        # Aucune chaîne d'installation écrite ici.
        self.assertNotIn("make install_odoo", SRC)
        self.assertNotIn("git clone", SRC)

    def test_the_block_goes_in_one_ssh_session(self):
        """La session est ouverte AVANT que « make install_os » n'applique le
        module : c'est ce qui expose la panne du premier passage."""
        self.assertIn('["bash -s"]', SRC.replace("'", '"'))

    def test_the_verdict_is_the_state_not_the_return_code(self):
        """Le code de retour est noté, pas cru."""
        self.assertIn("all(controles.values())", SRC)

    def test_what_must_compile_is_named(self):
        """Les paquets sans roue amont sont ceux qui tombent quand les
        en-têtes manquent, et eux seuls."""
        for module in ("psycopg2", "ldap", "cups", "MySQLdb"):
            with self.subTest(module=module):
                self.assertIn(module, SRC)

    def test_a_missing_answer_is_not_a_success(self):
        """« 000 » est l'absence de réponse : l'accepter ferait passer une VM
        où rien n'écoute."""
        self.assertNotIn('"000"', SRC)
        self.assertIn('"303"', SRC)


class LEssaiABlanc(unittest.TestCase):
    def test_it_creates_nothing_and_says_so(self):
        fini = subprocess.run(
            [
                str(RACINE / ".venv.erplibre/bin/python"),
                str(SCRIPT),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=RACINE,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("--dry-run", fini.stdout)
        # Le plan montre la commande de création, sans la lancer.
        self.assertIn("deploy_qemu.py", fini.stdout)
        self.assertIn("--distro nixos", fini.stdout)

    def test_the_dry_run_report_is_named_apart(self):
        """Un rapport d'essai à blanc n'a rien créé : le confondre avec un
        vrai ferait détruire d'après une liste vide."""
        self.assertIn("-dryrun.json", SRC)


class LeVerrouEtLeMenu(unittest.TestCase):
    def test_it_shares_the_lock_of_the_other_long_tests(self):
        """Deux tests longs se disputent la RAM, le disque et ~/.ssh/config
        aussi sûrement que deux descentes de la même pile."""
        src = (RACINE / "long_test/descente.py").read_text(encoding="utf-8")
        self.assertIn('"install_nixos.py"', src)

    def test_the_menu_offers_it_dry_and_for_real(self):
        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        menu = (RACINE / "script/todo/longtest_menu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ERPLibre on NixOS: run it", menu)
        self.assertIn("ERPLibre on NixOS: plan only (dry-run)", menu)
        self.assertIn("install_nixos.py", SCRIPTS_DEFAISABLES)

    def test_the_menu_does_not_pass_a_depth(self):
        """Une seule machine : « --depth » n'a pas de sens ici, et le script
        le refuserait."""
        menu = (RACINE / "script/todo/longtest_menu.py").read_text(
            encoding="utf-8"
        )
        bloc = menu.split('if script == "install_nixos.py":')[1][:400]
        self.assertNotIn("--depth", bloc)

    def test_every_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "ERPLibre on NixOS: plan only (dry-run)",
            "ERPLibre on NixOS: run it",
            "Where does the install run?",
            "Create a fresh NixOS VM",
            "Use a NixOS machine you already have",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))


if __name__ == "__main__":
    unittest.main()
