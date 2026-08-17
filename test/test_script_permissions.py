#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un script avec shebang doit être exécutable — dans ce que git STOCKE.

Le bit d'exécution n'accorde rien : qui peut lire le fichier peut déjà faire
« python3 fichier ». Il décide seulement si « ./script/... » fonctionne.

La première version de ce test exigeait aussi l'absence d'écriture par le
groupe, mesurée sur le disque. C'était une faute : git ne stocke QUE le bit
d'exécution — 100644 ou 100755 — et le reste vient de l'umask de celui qui
fait le checkout. Sur un poste en umask 0002, chaque checkout produit 775 et
le test échouait treize fois, pour une raison qui n'est pas dans le dépôt.

On vérifie donc l'index, seul mode que le dépôt porte et propage. Le mode du
disque reste l'affaire de la machine, pas d'un test.
"""

import glob
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = (
    "script/analyse/*.py",
    "script/analyse/*/*.py",
    "script/odoo/migration/*.py",
)


def scripts():
    """(chemin, a un shebang) pour chaque script des dossiers visés."""
    found = []
    for pattern in PATTERNS:
        for path in sorted(glob.glob(os.path.join(REPO, pattern))):
            with open(path, "rb") as handle:
                found.append((path, handle.read(2) == b"#!"))
    return found


def index_mode(path):
    """Le mode que GIT porte pour ce fichier : 100644 ou 100755."""
    done = subprocess.run(
        ["git", "ls-files", "-s", "--", os.path.relpath(path, REPO)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if done.returncode or not done.stdout.strip():
        return None
    return done.stdout.split()[0]


class TestExecutableBit(unittest.TestCase):
    def test_the_inventory_is_not_empty(self):
        # Un test qui ne trouve rien passe toujours.
        self.assertGreater(len(scripts()), 10)

    def test_every_shebang_script_is_executable_in_git(self):
        # Dans l'index, pas sur le disque : c'est ce que reçoivent les
        # autres. Un fichier rendu exécutable localement sans être commité
        # marcherait ici et nulle part ailleurs.
        for path, has_shebang in scripts():
            if not has_shebang:
                continue
            relative = os.path.relpath(path, REPO)
            mode = index_mode(path)
            if mode is None:
                continue  # non suivi : rien à garantir pour personne
            with self.subTest(script=relative):
                self.assertEqual(mode, "100755", relative)

    def test_a_file_without_shebang_is_not_marked_executable(self):
        # Le symétrique : un bit d'exécution sur un fichier qu'aucun
        # interpréteur ne réclame dit une intention qui n'existe pas.
        for path, has_shebang in scripts():
            if has_shebang:
                continue
            mode = index_mode(path)
            if mode is None:
                continue
            with self.subTest(script=os.path.relpath(path, REPO)):
                self.assertEqual(mode, "100644")

    def test_the_check_reads_git_not_the_filesystem(self):
        # Le défaut corrigé : l'umask du poste décide de 755 contre 775, et
        # un test qui le lit échoue sur la machine des autres. On le vérifie
        # par les IMPORTS — chercher un nom de constante dans la source d'un
        # fichier qui contient ce test échouerait sur lui-même.
        import ast

        with open(__file__) as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertIn("subprocess", imported)
        self.assertNotIn("stat", imported)


class TestTheTuiSaysWhyItRefuses(unittest.TestCase):
    """Rendre un script lançable ouvre un chemin sans le venv.

    Le shebang est « #!/usr/bin/env python3 » : lancé directement depuis un
    shell où le venv n'est pas actif, c'est le python du système qui répond,
    et Textual n'y est pas. La TUI retombait alors sur le rapport texte sans
    rien dire — le même défaut muet que le tube de sortie.
    """

    def run_tui(self):
        import sys

        sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))
        self.addCleanup(sys.path.remove, sys.path[0])
        from cow_drift_tui import run_tui

        return run_tui

    def finding(self):
        return {
            "id": 1,
            "key": "k",
            "website_id": 1,
            "reason": "r",
            "module_id": 2,
            "module_arch": "a",
            "copy_arch": "b",
            "decl_current": None,
            "decl_target": None,
            "current_version": "odoo12.0",
            "target_version": "odoo13.0",
        }

    def test_a_pipe_is_explained_not_swallowed(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            result = self.run_tui()([self.finding()])
        self.assertFalse(result)
        self.assertTrue(out.getvalue().strip(), "refus muet")

    def test_nothing_to_show_stays_silent(self):
        # Une liste vide n'est pas un refus : il n'y a rien à annoncer.
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(self.run_tui()([]))
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
