#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les worktrees git (script/git/git_worktree) et leur section du menu
Git (script/todo/git_worktree_menu).

La lecture de `git worktree list --porcelain` se teste sur un texte ; la
création, le retrait et le nettoyage sur un vrai dépôt jetable, car seul
git dit ce qu'il refuse — un worktree aux fichiers modifiés, une branche
non fusionnée.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.git import git_worktree as gw  # noqa: E402
from script.todo import git_worktree_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

PORCELAINE = """worktree /src/erplibre
HEAD 1111111111111111111111111111111111111111
branch refs/heads/master

worktree /src/erplibre_fix
HEAD 2222222222222222222222222222222222222222
branch refs/heads/dev/fix
locked

worktree /src/erplibre_vieux
HEAD 3333333333333333333333333333333333333333
detached
prunable gitdir file points to non-existent location
"""

# Un commit sans l'identité ni les hooks du poste qui lance le test.
ENV_GIT = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class TestAnalyse(unittest.TestCase):
    def test_each_entry_and_its_marks(self):
        principal, fix, vieux = gw.analyser(PORCELAINE)
        self.assertEqual(principal["branch"], "master")
        self.assertEqual(fix["branch"], "dev/fix")
        self.assertEqual(fix["locked"], "locked")
        self.assertTrue(vieux["detached"])
        self.assertIsNone(vieux["branch"])
        self.assertIn("non-existent", vieux["prunable"])

    def test_the_branch_finds_its_worktree(self):
        worktrees = gw.analyser(PORCELAINE)
        self.assertEqual(
            gw.worktree_de_branche(worktrees, "dev/fix")["path"],
            "/src/erplibre_fix",
        )
        self.assertIsNone(gw.worktree_de_branche(worktrees, "absente"))

    def test_the_proposed_directory_sits_beside_the_checkout(self):
        self.assertEqual(
            gw.chemin_propose("/src/erplibre/", "dev/odoo_18 fix"),
            "/src/erplibre_odoo_18_fix",
        )

    def test_the_description_names_path_branch_and_marks(self):
        principal, fix, vieux = gw.analyser(PORCELAINE)
        principal["principal"] = True
        self.assertEqual(
            gw.decrire(principal, 2, maison="/src"),
            "~/erplibre  [master]  · main worktree, 2 modified files",
        )
        self.assertIn("locked", gw.decrire(fix, maison=""))
        ligne = gw.decrire(vieux, maison="")
        self.assertIn("33333333 detached", ligne)
        self.assertIn("directory missing", ligne)

    def test_the_create_command(self):
        self.assertEqual(
            gw.commande_creer("/d", "dev/x", "master"),
            ["worktree", "add", "-b", "dev/x", "/d", "master"],
        )
        self.assertEqual(
            gw.commande_creer("/d", "dev/x", nouvelle=False),
            ["worktree", "add", "/d", "dev/x"],
        )


class DepotJetable(unittest.TestCase):
    """Un dépôt git neuf, un commit sur master, dans un répertoire temporaire
    qui recevra aussi les worktrees."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git absent")
        env = mock.patch.dict(os.environ, ENV_GIT)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.depot = os.path.join(self.tmp, "erplibre")
        os.makedirs(self.depot)
        self.git("init", "-q", "-b", "master")
        with open(os.path.join(self.depot, "a.txt"), "w") as fh:
            fh.write("a\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "init")

    def git(self, *args, cwd=None):
        fait = subprocess.run(
            ["git", "-C", cwd or self.depot] + list(args),
            capture_output=True,
            text=True,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout


class TestDepot(DepotJetable):
    def test_create_list_and_remove(self):
        chemin = gw.chemin_propose(self.depot, "dev/essai")
        code, message = gw.creer(self.depot, chemin, "dev/essai", "master")
        self.assertEqual(code, 0, message)
        worktrees = gw.lister(self.depot)
        self.assertEqual(
            [(w["path"], w["branch"], w["principal"]) for w in worktrees],
            [
                (self.depot, "master", True),
                (chemin, "dev/essai", False),
            ],
        )
        self.assertTrue(gw.branche_existe(self.depot, "dev/essai"))
        self.assertEqual(gw.fichiers_modifies(chemin), 0)
        code, message = gw.supprimer(self.depot, chemin)
        self.assertEqual(code, 0, message)
        self.assertFalse(os.path.exists(chemin))
        # Fusionnée (au même commit que master) : -d la retire.
        self.assertEqual(gw.supprimer_branche(self.depot, "dev/essai")[0], 0)

    def test_a_worktree_with_changes_needs_force(self):
        chemin = os.path.join(self.tmp, "sale")
        gw.creer(self.depot, chemin, "dev/sale", "master")
        with open(os.path.join(chemin, "nouveau.txt"), "w") as fh:
            fh.write("x\n")
        self.assertEqual(gw.fichiers_modifies(chemin), 1)
        self.assertNotEqual(gw.supprimer(self.depot, chemin)[0], 0)
        self.assertTrue(os.path.exists(chemin))
        self.assertEqual(gw.supprimer(self.depot, chemin, forcer=True)[0], 0)

    def test_an_unmerged_branch_is_kept(self):
        chemin = os.path.join(self.tmp, "travail")
        gw.creer(self.depot, chemin, "dev/travail", "master")
        with open(os.path.join(chemin, "b.txt"), "w") as fh:
            fh.write("b\n")
        self.git("add", "b.txt", cwd=chemin)
        self.git("commit", "-q", "-m", "travail", cwd=chemin)
        gw.supprimer(self.depot, chemin)
        self.assertNotEqual(
            gw.supprimer_branche(self.depot, "dev/travail")[0], 0
        )
        self.assertTrue(gw.branche_existe(self.depot, "dev/travail"))

    def test_a_directory_deleted_by_hand_is_pruned(self):
        chemin = os.path.join(self.tmp, "efface")
        gw.creer(self.depot, chemin, "dev/efface", "master")
        shutil.rmtree(chemin)
        _p, efface = gw.lister(self.depot)
        self.assertFalse(efface["existe"])
        code, lignes = gw.nettoyer(self.depot, simuler=True)
        self.assertEqual(code, 0)
        self.assertTrue(lignes)
        self.assertEqual(len(gw.lister(self.depot)), 2)
        gw.nettoyer(self.depot, simuler=False)
        self.assertEqual(len(gw.lister(self.depot)), 1)

    def test_an_existing_branch_is_checked_out_not_recreated(self):
        self.git("branch", "dev/existante")
        chemin = os.path.join(self.tmp, "existante")
        code, message = gw.creer(
            self.depot, chemin, "dev/existante", nouvelle=False
        )
        self.assertEqual(code, 0, message)
        self.assertEqual(gw.lister(self.depot)[1]["branch"], "dev/existante")


class Menu(git_worktree_menu.GitWorktreeMenuMixin):
    @staticmethod
    def _is_yes(reponse):
        return reponse.strip().lower() in ("y", "yes", "o", "oui")


class TestMenu(DepotJetable):
    def setUp(self):
        super().setUp()
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        racine = mock.patch.object(git_worktree_menu, "RACINE", self.depot)
        racine.start()
        self.addCleanup(racine.stop)
        self.menu = Menu()

    def repondre(self, methode, *reponses):
        with (
            mock.patch("builtins.input", side_effect=list(reponses)),
            redirect_stdout(io.StringIO()) as sortie,
        ):
            rendu = getattr(self.menu, methode)()
        return rendu, sortie.getvalue()

    def test_create_proposes_a_sibling_directory_from_master(self):
        chemin, sortie = self.repondre(
            "_git_worktree_creer", "dev/neuf", "", ""
        )
        self.assertEqual(chemin, os.path.join(self.tmp, "erplibre_neuf"))
        self.assertIn("-b dev/neuf", sortie)
        self.assertIn("no venv", sortie)

    def test_create_refuses_a_branch_held_elsewhere(self):
        chemin, sortie = self.repondre("_git_worktree_creer", "master")
        self.assertIsNone(chemin)
        self.assertIn(self.depot, sortie)

    def test_delete_needs_a_yes_and_keeps_the_main_checkout(self):
        self.repondre("_git_worktree_creer", "dev/x", "", "")
        parti, _ = self.repondre("_git_worktree_supprimer", "1", "")
        self.assertFalse(parti)
        self.assertEqual(len(gw.lister(self.depot)), 2)
        parti, _ = self.repondre("_git_worktree_supprimer", "1", "y", "y")
        self.assertTrue(parti)
        self.assertEqual(len(gw.lister(self.depot)), 1)
        self.assertFalse(gw.branche_existe(self.depot, "dev/x"))

    def test_delete_with_changes_asks_twice(self):
        chemin, _ = self.repondre("_git_worktree_creer", "dev/y", "", "")
        with open(os.path.join(chemin, "z.txt"), "w") as fh:
            fh.write("z\n")
        parti, sortie = self.repondre("_git_worktree_supprimer", "1", "y", "")
        self.assertFalse(parti)
        self.assertIn("1 modified files", sortie)
        self.assertTrue(os.path.exists(chemin))

    def test_find_the_branch(self):
        tenue, sortie = self.repondre("_git_worktree_branche", "master")
        self.assertEqual(tenue["path"], self.depot)
        _rien, sortie = self.repondre("_git_worktree_branche", "inconnue")
        self.assertIn("no such local branch", sortie)


if __name__ == "__main__":
    unittest.main()
