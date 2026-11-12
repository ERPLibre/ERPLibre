#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lister et ouvrir des pull requests : l'API GitHub, la branche poussée
d'un clone, la cible (dépôt du manifeste ou amont déclaré), le menu
Répertoire git et la ligne de commande.

GitHub est une fausse session ; les clones sont de vrais dépôts git
jetables, sans réseau.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import github_fork as gf  # noqa: E402
from script.git import manifest_repo as mr  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

IDENTITE = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@exemple.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@exemple.invalid",
}


class Reponse:
    def __init__(self, statut, corps=None):
        self.status_code = statut
        self._corps = corps if corps is not None else {}

    def json(self):
        return self._corps


class Session:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    def request(self, methode, url, **kw):
        self.appels.append((methode, url[len(gf.API) :], kw))
        return self.reponses.pop(0)


class TestLAPI(unittest.TestCase):
    def client(self, reponses):
        session = Session(reponses)
        return gf.ClientGitHub("x", session), session

    def test_every_page_is_read_and_a_missing_repo_is_none(self):
        client, session = self.client(
            [
                Reponse(200, [{"number": i} for i in range(100)]),
                Reponse(200, [{"number": 100}]),
            ]
        )
        self.assertEqual(len(client.pull_requests("Org/web")), 101)
        self.assertEqual(session.appels[1][2]["params"]["page"], 2)
        client, _ = self.client([Reponse(404, {"message": "Not Found"})])
        self.assertIsNone(client.pull_requests("Org/absent"))

    def test_a_pull_request_is_opened_with_head_base_and_draft(self):
        client, session = self.client([Reponse(201, {"html_url": "u"})])
        pr = client.creer_pull_request(
            "OCA/web", "Org:feat", "18.0", "T", "C", True
        )
        self.assertEqual(pr["html_url"], "u")
        self.assertEqual(
            session.appels[0][2]["json"],
            {
                "title": "T",
                "head": "Org:feat",
                "base": "18.0",
                "body": "C",
                "draft": True,
            },
        )

    def test_the_reason_of_a_refusal_is_kept(self):
        client, _ = self.client(
            [
                Reponse(
                    422,
                    {
                        "message": "Validation Failed",
                        "errors": [
                            {
                                "message": "A pull request already exists for Org:feat."
                            }
                        ],
                    },
                )
            ]
        )
        with self.assertRaises(gf.ErreurGitHub) as ctx:
            client.creer_pull_request("OCA/web", "Org:feat", "18.0", "T")
        self.assertIn("A pull request already exists", str(ctx.exception))


class TestLaListe(unittest.TestCase):
    def test_one_query_per_repository_and_absent_ones_counted(self):
        projets = [
            ({"path": "odoo18.0/addons/OCA_web"}, "OCA", "web"),
            ({"path": "odoo18.0/addons/ERPLibre_web"}, "ERPLibre", "web"),
            ({"path": "odoo18.0/addons/OCA_ai"}, "OCA", "ai"),
        ]
        client = mock.Mock()
        client.pull_requests.side_effect = lambda nom: (
            None
            if nom.endswith("/ai")
            else [
                {
                    "number": 1,
                    "title": "T",
                    "html_url": "u",
                    "user": {"login": "a"},
                }
            ]
        )
        with mock.patch.object(
            mr, "projets_github", return_value=({}, projets)
        ):
            res = mr.lister_pull_requests(client, "Org", "18.0")
        self.assertEqual([n for _c, n, _l in res], ["Org/web", "Org/ai"])
        lignes = gm.lignes_pull_requests(res)
        self.assertIn("  #1 T (a) — u", lignes)
        self.assertTrue(lignes[-1].startswith("📋 1 "))


class Clone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)
        self.clone = os.path.join(self.tmp.name, "web")
        os.makedirs(self.clone)
        self.git("init", "-q", "-b", "18.0")
        open(os.path.join(self.clone, "f"), "w").close()
        self.git("add", "f")
        self.git("commit", "-q", "-m", "init")

    def git(self, *args):
        subprocess.run(
            ["git", "-C", self.clone, *args], check=True, capture_output=True
        )

    def pousser(
        self, branche, remote="fork", url="https://github.com/MonOrg/web.git"
    ):
        """Simule une branche poussée et suivie, sans réseau."""
        # « -C » crée la branche, ou reprend la courante si c'est elle.
        self.git("switch", "-q", "-C", branche)
        self.git("remote", "add", remote, url)
        self.git("update-ref", f"refs/remotes/{remote}/{branche}", "HEAD")
        self.git("branch", f"--set-upstream-to={remote}/{branche}")


class TestLOuverture(Clone):
    def test_an_untracked_branch_is_refused(self):
        self.assertIsNone(mr.branche_poussee(self.clone))
        with self.assertRaises(ValueError):
            mr.ouvrir_pull_request(
                mock.Mock(), self.clone, "OCA/web", "18.0", "T"
            )

    def test_the_head_is_the_pushed_branch_of_its_remote_owner(self):
        self.pousser("18.0_ma_fonction")
        self.assertEqual(
            mr.branche_poussee(self.clone),
            ("18.0_ma_fonction", "fork", "18.0_ma_fonction"),
        )
        client = mock.Mock()
        client.creer_pull_request.return_value = {"html_url": "u"}
        mr.ouvrir_pull_request(client, self.clone, "OCA/web", "18.0", "T", "C")
        client.creer_pull_request.assert_called_once_with(
            "OCA/web", "MonOrg:18.0_ma_fonction", "18.0", "T", "C", False
        )

    def test_the_base_branch_itself_is_refused(self):
        self.pousser("18.0")
        with self.assertRaises(ValueError):
            mr.ouvrir_pull_request(
                mock.Mock(), self.clone, "MonOrg/web", "18.0", "T"
            )

    def test_targets_of_a_fork_and_of_a_plain_project(self):
        remotes = {
            "OCA": "https://github.com/OCA/",
            "MonOrg_origin_OCA": "https://github.com/MonOrg/",
        }
        fork = {
            "name": "web.git",
            "revision": "18.0_dev",
            "remote": "MonOrg_origin_OCA",
            "fork-upstream-remote": "OCA",
            "fork-upstream": "18.0",
        }
        self.assertEqual(
            mr.cibles_pull_request(fork, remotes),
            {
                "manifeste": ("MonOrg/web", "18.0_dev"),
                "amont": ("OCA/web", "18.0"),
            },
        )
        simple = {"name": "web.git", "revision": "18.0", "remote": "OCA"}
        self.assertEqual(
            mr.cibles_pull_request(simple, remotes),
            {"manifeste": ("OCA/web", "18.0")},
        )


class TestLeMenu(Clone):
    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def test_open_asks_target_title_body_draft_and_confirms(self):
        from script.todo.todo import TODO

        self.pousser("18.0_ma_fonction")
        todo = TODO.__new__(TODO)
        projet = {
            "name": "web.git",
            "revision": "18.0_dev",
            "remote": "MonOrg_origin_OCA",
            "fork-upstream-remote": "OCA",
            "fork-upstream": "18.0",
        }
        remotes = {
            "OCA": "https://github.com/OCA/",
            "MonOrg_origin_OCA": "https://github.com/MonOrg/",
        }
        client = mock.Mock()
        client.creer_pull_request.return_value = {
            "html_url": "https://github.com/OCA/web/pull/9"
        }
        with (
            mock.patch.object(
                type(todo),
                "_git_choisir_clone",
                return_value=(remotes, projet, self.clone),
            ),
            mock.patch.object(gm.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                gm.github_fork, "ClientGitHub", return_value=client
            ),
            mock.patch("builtins.input", side_effect=["", "", "", "", "o"]),
            mock.patch("builtins.print"),
        ):
            url = todo._git_creer_pull_request()
        self.assertEqual(url, "https://github.com/OCA/web/pull/9")
        cible, tete, base, titre, _corps, brouillon = (
            client.creer_pull_request.call_args.args
        )
        self.assertEqual(
            (cible, tete, base, titre, brouillon),
            ("OCA/web", "MonOrg:18.0_ma_fonction", "18.0", "init", False),
        )

    def test_nothing_is_opened_without_confirmation(self):
        from script.todo.todo import TODO

        self.pousser("18.0_ma_fonction")
        todo = TODO.__new__(TODO)
        projet = {"name": "web.git", "revision": "18.0", "remote": "OCA"}
        with (
            mock.patch.object(
                type(todo),
                "_git_choisir_clone",
                return_value=(
                    {"OCA": "https://github.com/OCA/"},
                    projet,
                    self.clone,
                ),
            ),
            mock.patch.object(gm.github_fork, "ClientGitHub") as fabrique,
            mock.patch("builtins.input", side_effect=["", "", "", "", "n"]),
            mock.patch("builtins.print"),
        ):
            self.assertIsNone(todo._git_creer_pull_request())
        fabrique.assert_not_called()


class TestLaLigneDeCommande(unittest.TestCase):
    def test_pulls_prints_each_and_the_total(self):
        client = mock.Mock()
        sortie = []
        with (
            mock.patch.object(
                mr,
                "lister_pull_requests",
                return_value=[
                    (
                        "p",
                        "Org/web",
                        [{"number": 3, "title": "T", "html_url": "u"}],
                    ),
                    ("q", "Org/ai", None),
                ],
            ),
            mock.patch.object(mr.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                mr.github_fork, "ClientGitHub", return_value=client
            ),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: sortie.append(
                    " ".join(map(str, a))
                ),
            ),
        ):
            code = mr.main(
                ["pulls", "--organisation", "Org", "--version", "18.0"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            sortie,
            ["Org/web#3 T — u", "1 pull request(s); 1 repositories not found"],
        )


if __name__ == "__main__":
    unittest.main()
