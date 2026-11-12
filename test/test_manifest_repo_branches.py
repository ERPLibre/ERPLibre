#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La même branche dans plusieurs dépôts, en parallèle : chaque clone
reçoit la branche, un échec n'arrête pas les autres, et le push va au
remote du projet. Dépôts git jetables, sans réseau."""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import manifest_repo as mr  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

IDENTITE = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@exemple.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@exemple.invalid",
}


def git(chemin, *args):
    return subprocess.run(
        ["git", "-C", chemin, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Clones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)

    def clone(self, nom, remote="OCA"):
        chemin = os.path.join(self.tmp.name, nom)
        nu = os.path.join(self.tmp.name, f"{nom}.git")
        subprocess.run(["git", "init", "-q", "--bare", nu], check=True)
        os.makedirs(chemin)
        git(chemin, "init", "-q", "-b", "18.0")
        git(chemin, "commit", "-q", "--allow-empty", "-m", "x")
        git(chemin, "remote", "add", remote, nu)
        return chemin, nu


class TestPlusieurs(Clones):
    def test_each_clone_gets_the_branch_and_its_push(self):
        a, nu_a = self.clone("a", "OCA")
        b, nu_b = self.clone("b", "ERPLibre_origin_OCA")
        res = mr.brancher_plusieurs(
            [(a, "OCA"), (b, "ERPLibre_origin_OCA")],
            "18.0_fonction",
            pousser=True,
        )
        self.assertEqual([c for c, _e in res], [a, b])
        for chemin, nu in ((a, nu_a), (b, nu_b)):
            self.assertEqual(
                git(chemin, "branch", "--show-current"), "18.0_fonction"
            )
            self.assertIn("18.0_fonction", git(nu, "branch"))

    def test_a_failing_clone_does_not_stop_the_others(self):
        a, _ = self.clone("a")
        b, _ = self.clone("b")
        git(a, "branch", "18.0_fonction")
        res = dict(
            mr.brancher_plusieurs([(a, "OCA"), (b, "OCA")], "18.0_fonction")
        )
        self.assertNotEqual(res[a][0][1], 0)
        self.assertEqual(res[b], [("branche", 0, res[b][0][2])])
        self.assertEqual(git(b, "branch", "--show-current"), "18.0_fonction")


class TestLeMenu(Clones):
    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def test_the_checked_clones_are_branched_with_their_remote(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        liste = [
            {"path": "odoo18.0/addons/OCA_a", "remote": "OCA"},
            {"path": "odoo18.0/addons/OCA_b", "remote": "ERPLibre_origin_OCA"},
        ]
        with (
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(gm, "clones", return_value=({}, liste)),
            mock.patch.object(gm, "RACINE", "/r"),
            mock.patch(
                "builtins.input", side_effect=["all", "18.0_f", "", "o"]
            ),
            mock.patch.object(
                gm.manifest_repo, "brancher_plusieurs", return_value=[]
            ) as appel,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(todo._git_creer_branche_plusieurs(), 0)
        appel.assert_called_once_with(
            [
                ("/r/odoo18.0/addons/OCA_a", "OCA"),
                ("/r/odoo18.0/addons/OCA_b", "ERPLibre_origin_OCA"),
            ],
            "18.0_f",
            None,
            True,
        )


if __name__ == "__main__":
    unittest.main()
