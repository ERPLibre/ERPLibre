#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'amorçage d'une installation ERPLibre sur NixOS.

Le catalogue offre NixOS et le dépôt sait y déclarer ses dépendances ; entre
les deux manquait le geste qui va du système nu au dépôt cloné. L'amorçage
posait curl, git et make par apt, dnf, pacman, zypper ou yum, et s'arrêtait
sur « Aucun gestionnaire de paquets » — avant le clone, donc avant tout.

Deux nœuds, et chacun se dénoue au même endroit : on ne peut pas être
déclaratif AVANT d'avoir le dépôt qui porte la déclaration.

- git et make sont ABSENTS de l'image NixOS (curl et sudo, eux, y sont). Ils
  sont donc posés dans le profil de l'utilisateur pour la durée du clone, et
  « make install_os » les redéclare ensuite pour le système entier ;
- « /bin/bash » n'existe pas non plus — le shell vit dans le store. Le
  Makefile l'exigeait dès sa première ligne, et make s'arrêtait avant
  d'exécuter la moindre recette, y compris celle qui installe de quoi créer
  ce chemin.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


class LAmorcage(unittest.TestCase):
    def setUp(self):
        self.cmd = TODO.__new__(TODO)._qemu_erplibre_remote_cmd("develop")

    def test_a_nixos_vm_is_no_longer_turned_away(self):
        """Le message d'arrêt nomme désormais nix : sans la branche, une VM
        NixOS n'atteignait jamais son clone."""
        self.assertIn("command -v nix-env", self.cmd)
        self.assertIn("(apt/dnf/pacman/zypper/yum/nix)", self.cmd)

    def test_the_tools_come_from_nixpkgs_not_from_a_channel(self):
        """L'utilisateur n'a aucun canal sur cette image, là où NIX_PATH est
        posé pour tout le monde et pointe les canaux de root."""
        self.assertIn("nix-env -f '<nixpkgs>' -iA", self.cmd)

    def test_make_is_asked_for_by_its_nixpkgs_name(self):
        """Dans nixpkgs, make s'appelle gnumake : demander « make » ferait
        échouer la pose sans que rien ne dise pourquoi."""
        i = self.cmd.index("nix-env -f")
        pose = self.cmd[i : self.cmd.index(";", i)]
        self.assertIn("gnumake", pose)
        self.assertNotIn(" make", pose)

    def test_python3_is_posed_here_and_only_here(self):
        """Les images des quatre autres familles l'embarquent — cloud-init
        est écrit en Python. Sur NixOS il vit dans le store, hors PATH, et la
        première recette de « make install_os » s'arrêtait sur « env:
        python3: No such file or directory »."""
        i = self.cmd.index("nix-env -f")
        pose = self.cmd[i : self.cmd.index(";", i)]
        self.assertIn("python3", pose)
        self.assertNotIn("python3", self.cmd[: self.cmd.index("PKGS=")])

    def test_the_path_is_widened_after_the_pose(self):
        """Le PATH du shell distant est figé à son ouverture : sans cette
        ligne, le contrôle qui suit déclare git manquant sur une machine où
        il vient d'être installé."""
        i = self.cmd.index("nix-env -f")
        j = self.cmd.index("for t in curl git make")
        self.assertIn('PATH="$HOME/.nix-profile/bin:$PATH"', self.cmd[i:j])

    def test_the_check_that_follows_is_unchanged(self):
        """Le même contrôle vaut pour les six familles : une erreur nette
        plutôt qu'un « command not found » cryptique plus loin."""
        self.assertIn("for t in curl git make; do command -v $t", self.cmd)

    def test_it_is_valid_shell(self):
        fini = subprocess.run(
            ["bash", "-n"], input=self.cmd, text=True, capture_output=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)


class LeShellDuMakefile(unittest.TestCase):
    PREMIERES = (RACINE / "Makefile").read_text(encoding="utf-8")[:600]

    def test_bash_is_looked_for_rather_than_assumed(self):
        """« /bin/bash » n'existe pas sur NixOS."""
        self.assertIn("command -v bash", self.PREMIERES)
        self.assertNotIn("SHELL := /bin/bash", self.PREMIERES)

    def test_a_host_without_bash_keeps_the_old_path(self):
        """Le repli ne rend pas la panne pire qu'avant sur une plateforme qui
        n'a pas bash du tout."""
        self.assertIn("|| echo /bin/bash", self.PREMIERES)

    def test_the_assignment_stays_immediate(self):
        """« = » différé ferait relancer le sous-shell à chaque recette, et
        SHELL est lu à chacune."""
        self.assertIn("SHELL := ", self.PREMIERES)

    def test_the_resolved_shell_exists_here(self):
        """L'épreuve sur la machine qui lit ce test : make doit pouvoir
        exécuter une recette."""
        ligne = next(
            x
            for x in (RACINE / "Makefile")
            .read_text(encoding="utf-8")
            .splitlines()
            if x.startswith("SHELL")
        )
        fini = subprocess.run(
            ["make", "-s", "-f", "-", "essai"],
            input=f"{ligne}\nessai:\n\techo ok\n",
            text=True,
            capture_output=True,
            cwd=RACINE,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("ok", fini.stdout)


if __name__ == "__main__":
    unittest.main()
