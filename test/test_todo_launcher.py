#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La chaîne de lancement de TODO tient-elle en un seul endroit ?

« make todo » passe par todo.sh, qui passe par install.sh, qui choisit un
interpréteur capable de LIRE le code avant de le lui donner. Trois fichiers,
mais UNE seule décision : elle vit dans install.sh, qui est aussi le point
d'entrée d'une machine neuve.

Ce que ces tests gardent :

- todo.sh reste un NOM, et non une seconde copie du choix d'interpréteur.
  Deux copies dérivent, et celle qui dérive est toujours celle qu'on ne lit
  pas — ici, le chemin qu'emprunte « make » ;
- les arguments traversent. Un lanceur qui les avale rend « ./todo.sh » et
  « ./install.sh » différents sans le dire ;
- todo.sh se place dans son propre répertoire : « make -C » et un appel par
  chemin absolu partent d'ailleurs, et les chemins relatifs d'install.sh
  n'y survivraient pas.
"""

import re
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
TODO_SH = RACINE / "todo.sh"
INSTALL_SH = RACINE / "install.sh"
MAKEFILE = (RACINE / "conf/make.todo.Makefile").read_text(encoding="utf-8")
SOURCE = TODO_SH.read_text(encoding="utf-8")


class TestCible(unittest.TestCase):
    def test_make_todo_lance_todo_sh(self):
        """La recette s'affiche : elle doit nommer ce qu'elle fait."""
        recette = re.search(r"^todo:\n\t(.+)$", MAKEFILE, re.MULTILINE)
        self.assertIsNotNone(recette, MAKEFILE)
        self.assertEqual("./todo.sh", recette.group(1).strip())

    def test_make_n_rend_la_meme_chose(self):
        sortie = subprocess.run(
            ["make", "-n", "todo"],
            cwd=RACINE,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        self.assertIn("./todo.sh", sortie.stdout)


class TestLanceur(unittest.TestCase):
    def test_il_est_executable(self):
        self.assertTrue(TODO_SH.exists())
        self.assertTrue(TODO_SH.stat().st_mode & 0o111)

    def test_il_delegue_a_install_sh(self):
        self.assertTrue(INSTALL_SH.exists())
        self.assertIn("./install.sh", SOURCE)

    def test_les_arguments_traversent(self):
        self.assertIn('"$@"', SOURCE)

    def test_il_se_place_dans_son_repertoire(self):
        self.assertIn('cd "$(dirname "$0")"', SOURCE)

    def test_il_ne_choisit_pas_l_interprete_lui_meme(self):
        """Le choix vit dans install.sh. Le recopier ici en ferait deux, et
        celle qui dérive serait celle que « make » emprunte."""
        for marqueur in ("python3", "pyvenv.cfg", "sort -V", "bin/python"):
            with self.subTest(marqueur=marqueur):
                self.assertNotIn(marqueur, SOURCE)

    def test_il_reste_court(self):
        """Au-delà d'une poignée de lignes, ce n'est plus un nom mais une
        seconde implémentation."""
        code = [
            ligne
            for ligne in SOURCE.splitlines()
            if ligne.strip() and not ligne.lstrip().startswith("#")
        ]
        self.assertLessEqual(len(code), 6, code)


class TestSyntaxe(unittest.TestCase):
    def test_les_deux_scripts_se_lisent(self):
        for script in (TODO_SH, INSTALL_SH):
            with self.subTest(script=script.name):
                sortie = subprocess.run(
                    ["bash", "-n", str(script)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, sortie.returncode, sortie.stderr)


if __name__ == "__main__":
    unittest.main()
