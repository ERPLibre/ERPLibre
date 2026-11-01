#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les cibles make des entrées « Synchroniser » et « Tirer les dépôts » du
menu git de TODO : chaque recette nomme ce qui existe encore. make repo_pull
appelle une méthode du menu ; un renommage la casserait en silence."""

import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def recette(cible):
    """La recette de `cible` telle que make la lancerait, sans la lancer."""
    return subprocess.run(
        ["make", "-n", "-s", cible],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class TestMakefileRepoTargets(unittest.TestCase):
    def test_repo_pull_calls_an_existing_menu_method(self):
        from script.todo.todo import TODO

        m = re.search(r"TODO\(\)\.(\w+)\(\)", recette("repo_pull"))
        self.assertIsNotNone(m)
        self.assertTrue(callable(getattr(TODO, m.group(1), None)), m.group(1))

    def test_repo_sync_is_the_menu_command(self):
        # make -n montre la commande avant que le shell n'y remplace nproc.
        self.assertEqual(
            recette("repo_sync"), ".venv.erplibre/bin/repo sync -c -j$(nproc)"
        )

    def test_repo_pull_dry_run_moves_nothing(self):
        cmd = recette("repo_pull_dry_run")
        self.assertIn("script/git/repo_pull.py --dry-run", cmd)
        self.assertNotIn("--apply", cmd)


if __name__ == "__main__":
    unittest.main()
