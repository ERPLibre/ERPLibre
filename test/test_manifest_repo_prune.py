#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Nettoyer les branches fusionnées d'un clone : la base du manifeste, les
remotes de fork, les branches protégées, la fusion par squash qu'annonce
GitHub, la suppression locale et sur le serveur, le menu. Dépôts git
jetables, sans réseau ; GitHub est un faux client."""

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
PROJET = {
    "name": "web.git",
    "path": "addons/OCA_web",
    "remote": "OCA",
    "revision": "18.0",
}


def git(chemin, *args):
    return subprocess.run(
        ["git", "-C", chemin, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Clone(unittest.TestCase):
    """Un clone dont le remote du projet, OCA, porte 18.0 ; un remote
    personnel, perso ; des branches fusionnées, en cours, et protégées."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)
        self.oca = os.path.join(tmp.name, "oca.git")
        self.perso = os.path.join(tmp.name, "perso.git")
        self.c = os.path.join(tmp.name, "clone")
        for nu in (self.oca, self.perso):
            subprocess.run(["git", "init", "-q", "--bare", nu], check=True)
        os.makedirs(self.c)
        c = self.c
        git(c, "init", "-q", "-b", "18.0")
        git(c, "commit", "-q", "--allow-empty", "-m", "base")
        git(c, "remote", "add", "OCA", self.oca)
        git(c, "remote", "add", "perso", self.perso)
        git(c, "branch", "fait")
        git(c, "switch", "-q", "-c", "encours")
        git(c, "commit", "-q", "--allow-empty", "-m", "travail")
        git(c, "branch", "squash")
        git(c, "push", "-q", "perso", "fait", "encours", "squash")
        git(c, "switch", "-q", "18.0")
        git(c, "commit", "-q", "--allow-empty", "-m", "fusion de fait")
        git(c, "push", "-q", "OCA", "18.0")
        git(c, "switch", "-q", "-c", "courante", "OCA/18.0")
        git(c, "fetch", "-q", "--all")


class TestLePlan(Clone):
    def test_bases_and_fork_remotes(self):
        self.assertEqual(mr.bases_du_clone(self.c, PROJET, {}), ["OCA/18.0"])
        self.assertEqual(mr.remotes_de_fork(self.c, PROJET, {}), ["perso"])
        fork = dict(PROJET, remote="perso")
        with mock.patch.object(mr.repo_upgrade, "est_fork", return_value=True):
            self.assertEqual(
                mr.remotes_de_fork(self.c, fork, {}), ["OCA", "perso"]
            )

    def test_only_merged_unprotected_branches_are_proposed(self):
        plan = mr.branches_a_nettoyer(self.c, ["OCA/18.0"], ["perso"])
        self.assertEqual(
            plan,
            {
                "locales": {"fait": "fusion"},
                "distantes": {"perso": {"fait": "fusion"}},
            },
        )

    def test_github_adds_the_squash_merged_branch_once_per_name(self):
        appels = []

        def fusion(nom):
            appels.append(nom)
            return "PR #7" if nom == "squash" else None

        plan = mr.branches_a_nettoyer(self.c, ["OCA/18.0"], ["perso"], fusion)
        self.assertEqual(
            plan["locales"], {"fait": "fusion", "squash": "PR #7"}
        )
        self.assertEqual(
            plan["distantes"]["perso"], {"fait": "fusion", "squash": "PR #7"}
        )
        self.assertEqual(sorted(appels), ["encours", "squash"])

    def test_the_github_search_heads_and_targets(self):
        client = mock.Mock()
        client.pull_requests_de.side_effect = lambda cible, tete: (
            [{"number": 9, "merged_at": "x"}]
            if (cible, tete) == ("OCA/web", "Org:b")
            else [{"number": 1, "merged_at": None}]
        )
        chercher = mr.fusion_par_github(client, ["Moi", "Org"], ["OCA/web"])
        self.assertEqual(chercher("b"), "PR #9")
        self.assertIsNone(chercher("c"))


class TestLaSuppression(Clone):
    def test_local_and_server_branches_are_deleted(self):
        res = mr.supprimer_branches(
            self.c, {"fait": "fusion", "squash": "PR #7"}, {"perso": ["fait"]}
        )
        self.assertEqual(
            [(r, n, code) for r, n, code, _s in res],
            [(None, "fait", 0), (None, "squash", 0), ("perso", "fait", 0)],
        )
        self.assertNotIn("fait", git(self.c, "branch"))
        self.assertEqual(
            git(self.perso, "branch", "--format=%(refname:short)").split(),
            ["encours", "squash"],
        )

    def test_the_plan_with_fetch_sees_a_branch_deleted_on_the_server(self):
        git(self.perso, "branch", "-D", "fait")
        _bases, _forks, plan = mr.plan_nettoyage(
            self.c, PROJET, {}, fetch=True
        )
        self.assertEqual(plan["distantes"], {})
        self.assertEqual(plan["locales"], {"fait": "fusion"})


class TestLaLigneDeCommande(Clone):
    def lancer(self, *args):
        racine = os.path.dirname(os.path.dirname(self.c))
        projet = dict(PROJET, path=os.path.relpath(self.c, racine))
        with (
            mock.patch.object(mr, "_racine", return_value=racine),
            mock.patch.object(mr, "trouver_projet", return_value=({}, projet)),
            mock.patch("builtins.print") as sortie,
        ):
            code = mr.main(["prune", "web", "--version", "18.0", *args])
        return code, "\n".join(str(c.args[0]) for c in sortie.call_args_list)

    def test_it_lists_without_apply_and_deletes_with_it(self):
        code, texte = self.lancer()
        self.assertEqual(code, 0)
        self.assertIn("local  fait (fusion)", texte)
        self.assertIn("perso  fait (fusion)", texte)
        self.assertIn("fait", git(self.c, "branch"))
        code, _texte = self.lancer("--apply")
        self.assertEqual(code, 0)
        self.assertNotIn("fait", git(self.c, "branch"))
        self.assertIn("fait", git(self.perso, "branch"))
        code, _texte = self.lancer("--apply", "--remote")
        self.assertNotIn("fait", git(self.perso, "branch"))


class TestLeMenu(Clone):
    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, reponses):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(
                TODO, "_git_choisir_clone", return_value=({}, PROJET, self.c)
            ),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch("builtins.print"),
        ):
            return todo._git_nettoyer_branches()

    def test_local_and_server_are_confirmed_separately(self):
        self.assertEqual(self.lancer(["n", "", "o", "n"]), 1)
        self.assertNotIn("fait", git(self.c, "branch"))
        self.assertIn("fait", git(self.perso, "branch"))

    def test_nothing_is_deleted_without_a_yes(self):
        self.assertEqual(self.lancer(["", "", "", ""]), 0)
        self.assertIn("fait", git(self.c, "branch"))


if __name__ == "__main__":
    unittest.main()
