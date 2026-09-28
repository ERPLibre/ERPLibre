#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le choix des fichiers de tests par --changed et --failed.

Chaque cas bâtit un petit dépôt git jetable : le graphe se lit dans le
code et la liste des fichiers vient de git, les deux doivent être réels.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import unit_selection as sel  # noqa: E402


class Depot(unittest.TestCase):
    """Un dépôt git dont chaque test écrit les fichiers."""

    FICHIERS = {
        "pkg/__init__.py": "",
        "pkg/bas.py": "VALEUR = 1\n",
        "pkg/haut.py": "from pkg.bas import VALEUR\n",
        "pkg/relatif.py": "from .bas import VALEUR\n",
        "pkg/isole.py": "X = 2\n",
        "pkg/menu.py": (
            'AIDE = "Relancer isole.py pour voir"\n'
            'CMD = "bash outils/lancer.sh --vite"\n'
        ),
        "pkg/chargeur.py": 'CHEMIN = "charge_par_chemin.py"\n',
        "outils/charge_par_chemin.py": "Y = 3\n",
        "outils/lancer.sh": "echo ok\n",
        "aide/appui.py": "Z = 4\n",
        "test/test_haut.py": "from pkg.haut import VALEUR\n",
        "test/test_relatif.py": "from pkg.relatif import VALEUR\n",
        "test/test_nu.py": (
            "import sys\nsys.path.insert(0, 'aide')\nimport appui\n"
        ),
        "test/test_script.py": 'SCRIPT = "outils/lancer.sh"\n',
        "test/test_menu.py": "from pkg import menu\n",
        "test/test_chargeur.py": "from pkg.chargeur import CHEMIN\n",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.racine = self.tmp.name
        for chemin, contenu in self.FICHIERS.items():
            self.ecrire(chemin, contenu)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git(
            "-c",
            "user.name=essai",
            "-c",
            "user.email=essai@exemple.invalid",
            "commit",
            "-qm",
            "base",
        )
        self.tests = sorted(c for c in self.FICHIERS if c.startswith("test/"))

    def ecrire(self, chemin, contenu):
        complet = os.path.join(self.racine, chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(contenu))

    def git(self, *args):
        subprocess.run(
            ["git", *args], cwd=self.racine, check=True, capture_output=True
        )

    def choisis(self, *modifies):
        return sel.concernes(self.racine, self.tests, list(modifies))


class TestLeGraphe(Depot):
    def test_un_module_importe_de_loin_retient_son_test(self):
        self.assertEqual(
            self.choisis("pkg/bas.py"),
            [
                "test/test_haut.py",
                "test/test_relatif.py",
            ],
        )

    def test_un_module_que_rien_n_importe_ne_retient_rien(self):
        self.assertEqual(self.choisis("pkg/isole.py"), [])

    def test_un_test_modifie_se_retient_lui_meme(self):
        self.assertEqual(self.choisis("test/test_nu.py"), ["test/test_nu.py"])

    def test_un_nom_nu_rendu_visible_par_sys_path(self):
        self.assertEqual(self.choisis("aide/appui.py"), ["test/test_nu.py"])

    def test_un_script_que_le_test_nomme(self):
        self.assertEqual(
            self.choisis("outils/lancer.sh"), ["test/test_script.py"]
        )

    def test_un_script_que_le_code_cite_ne_lie_pas_ses_importeurs(self):
        """menu.py cite lancer.sh dans une commande : ses tests ne
        l'exécutent pas pour autant. Seul test_script, qui le nomme, reste."""
        self.assertNotIn("test/test_menu.py", self.choisis("outils/lancer.sh"))

    def test_une_phrase_qui_nomme_un_module_n_en_depend_pas(self):
        self.assertNotIn("test/test_menu.py", self.choisis("pkg/isole.py"))

    def test_un_module_charge_par_son_chemin(self):
        self.assertEqual(
            self.choisis("outils/charge_par_chemin.py"),
            ["test/test_chargeur.py"],
        )

    def test_rien_de_modifie_rien_de_choisi(self):
        self.assertEqual(self.choisis(), [])


class TestLesFichiersModifies(Depot):
    def test_modifies_indexes_ou_non_et_non_suivis(self):
        self.ecrire("pkg/bas.py", "VALEUR = 2\n")
        self.ecrire("pkg/haut.py", "from pkg.bas import VALEUR  # vu\n")
        self.git("add", "pkg/haut.py")
        self.ecrire("pkg/neuf.py", "N = 1\n")
        self.assertEqual(
            sel.fichiers_modifies(self.racine),
            ["pkg/bas.py", "pkg/haut.py", "pkg/neuf.py"],
        )

    def test_une_reference_inconnue_leve(self):
        with self.assertRaises(ValueError):
            sel.fichiers_modifies(self.racine, "n-existe-pas")


class TestLesEchecsRetenus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.chemin = os.path.join(tmp.name, "cache", "echecs")

    def test_absent_rien_n_est_retenu(self):
        self.assertEqual(sel.echecs_retenus(self.chemin), set())

    def test_un_echec_entre_un_succes_sort_le_reste_demeure(self):
        sel.retenir_echecs(self.chemin, passes=[], echoues=["a.py", "b.py"])
        # c.py n'a pas tourné, b.py passe : seul a.py, non relancé, reste.
        retenus = sel.retenir_echecs(
            self.chemin, passes=["b.py"], echoues=["c.py"]
        )
        self.assertEqual(retenus, {"a.py", "c.py"})
        self.assertEqual(sel.echecs_retenus(self.chemin), {"a.py", "c.py"})


if __name__ == "__main__":
    unittest.main()
