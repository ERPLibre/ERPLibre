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
    """Le choix multiple des clones, puis le nom, le départ et le push :
    [0], une réponse vide et Ctrl+D, au choix comme aux questions qui le
    suivent, ne créent aucune branche ; une faute est nommée et
    redemandée."""

    LISTE = [
        {"path": "odoo18.0/addons/OCA_a", "remote": "OCA"},
        {"path": "odoo18.0/addons/OCA_b", "remote": "ERPLibre_origin_OCA"},
    ]

    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, reponses):
        """(ce que rend le menu, le double de `brancher_plusieurs`, le
        port) après `reponses`, données au port dans l'ordre ; le port
        lève EOFError, comme Ctrl+D, quand elles manquent."""
        from script.todo import ui
        from script.todo.todo import TODO
        from script.todo.ui.port import ScriptedPort

        todo = TODO.__new__(TODO)
        port = ScriptedPort(reponses)
        with (
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(gm, "clones", return_value=({}, self.LISTE)),
            mock.patch.object(gm, "RACINE", "/r"),
            mock.patch.object(
                gm.manifest_repo, "brancher_plusieurs", return_value=[]
            ) as appel,
            mock.patch("builtins.print"),
            ui.bind(port),
        ):
            retour = todo._git_creer_branche_plusieurs()
        return retour, appel, port

    def test_the_checked_clones_are_branched_with_their_remote(self):
        for choix in ("all", "tout", "*", "1-2", "2 1", "1,2"):
            with self.subTest(choix=choix):
                retour, appel, _port = self.lancer([choix, "18.0_f", "", "o"])
                self.assertEqual(retour, 0)
                appel.assert_called_once_with(
                    [
                        ("/r/odoo18.0/addons/OCA_a", "OCA"),
                        ("/r/odoo18.0/addons/OCA_b", "ERPLibre_origin_OCA"),
                    ],
                    "18.0_f",
                    None,
                    True,
                )

    def test_a_clone_is_checked_by_its_path(self):
        retour, appel, port = self.lancer(
            ["odoo18.0/addons/OCA_b", "18.0_f", "HEAD~1", "n"]
        )
        self.assertEqual(retour, 0)
        appel.assert_called_once_with(
            [("/r/odoo18.0/addons/OCA_b", "ERPLibre_origin_OCA")],
            "18.0_f",
            "HEAD~1",
            False,
        )
        choix = [e for e in port.events if e.get("kind") == "choose"]
        self.assertTrue(choix[0]["multi"])
        self.assertEqual(
            [o["label"] for o in choix[0]["options"]][:-1],
            ["odoo18.0/addons/OCA_a", "odoo18.0/addons/OCA_b"],
        )

    def test_a_typo_is_named_and_asked_again(self):
        for faute in ("3", "1 3", "1,3", "OCA_a", "01"):
            with self.subTest(faute=faute):
                retour, appel, port = self.lancer([faute, "1", "b", "", ""])
                self.assertEqual(retour, 0)
                self.assertEqual(
                    appel.call_args.args[0],
                    [("/r/odoo18.0/addons/OCA_a", "OCA")],
                )
                avis = [e for e in port.events if e.get("t") == "notice"]
                self.assertEqual(
                    [a["text"] for a in avis], [f"Choix invalide : {faute}"]
                )

    def test_a_back_creates_no_branch(self):
        # [0], une réponse vide et Ctrl+D au choix ; un nom vide ; Ctrl+D
        # au nom, au départ et à la question du push. La réponse de trop
        # reste au port : rien n'est demandé après le retour.
        fin = EOFError()
        for reponses in (
            ["0"],
            [""],
            [fin],
            ["all", ""],
            ["all", fin],
            ["all", "18.0_f", fin],
            ["all", "18.0_f", "", fin],
        ):
            with self.subTest(reponses=reponses):
                retour, appel, port = self.lancer([*reponses, "de trop"])
                self.assertIsNone(retour)
                appel.assert_not_called()
                self.assertEqual(port.answers, ["de trop"])


if __name__ == "__main__":
    unittest.main()
