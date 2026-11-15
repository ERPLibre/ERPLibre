#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les forks orphelins d'une organisation : ceux qu'aucun manifeste, toutes
versions confondues, ne clone plus ; l'archivage, coché puis confirmé.
GitHub est faux, sans réseau."""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import github_fork as gf  # noqa: E402
from script.git import manifest_repo as mr  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_pull_requests import Reponse, Session  # noqa: E402


def depot(nom, fork=True, archive=False):
    return {
        "full_name": f"Org/{nom}",
        "fork": fork,
        "archived": archive,
        "pushed_at": "2026-01-02T00:00:00Z",
        "html_url": f"https://github.com/Org/{nom}",
    }


class TestLesOrphelins(unittest.TestCase):
    def test_forks_no_manifest_clones_archived_ones_counted(self):
        client = mock.Mock()
        client.depots_du_compte.return_value = [
            depot("web"),
            depot("zzz"),
            depot("ancien"),
            depot("propre", fork=False),
            depot("vieux", archive=True),
        ]
        with mock.patch.object(
            mr, "depots_de_tous_les_manifestes", return_value={"org/web"}
        ):
            orphelins, archives = mr.forks_orphelins(client, "Org")
        self.assertEqual(
            [d["full_name"] for d in orphelins], ["Org/ancien", "Org/zzz"]
        )
        self.assertEqual(archives, 1)
        client.depots_du_compte.return_value = None
        self.assertIsNone(mr.forks_orphelins(client, "Absent"))

    def test_every_version_counts(self):
        par_version = {
            "17.0": [({}, "Org", "Web")],
            "18.0": [({}, "Org", "tools"), ({}, "OCA", "web")],
        }
        with (
            mock.patch.object(
                mr, "versions_des_manifestes", return_value=["17.0", "18.0"]
            ),
            mock.patch.object(
                mr,
                "projets_github",
                side_effect=lambda v, d=None: ({}, par_version[v]),
            ),
        ):
            self.assertEqual(
                mr.depots_de_tous_les_manifestes(),
                {"org/web", "org/tools", "oca/web"},
            )


class TestLAPI(unittest.TestCase):
    def test_an_account_falls_back_to_users_and_pages_are_read(self):
        session = Session(
            [
                Reponse(404, {"message": "Not Found"}),
                Reponse(200, [depot(str(i)) for i in range(100)]),
                Reponse(200, [depot("dernier")]),
            ]
        )
        client = gf.ClientGitHub("x", session)
        self.assertEqual(len(client.depots_du_compte("moi")), 101)
        self.assertEqual(
            [a[1] for a in session.appels],
            ["/orgs/moi/repos", "/users/moi/repos", "/users/moi/repos"],
        )
        client = gf.ClientGitHub("x", Session([Reponse(404), Reponse(404)]))
        self.assertIsNone(client.depots_du_compte("absent"))

    def test_archive_patches_the_repository(self):
        session = Session([Reponse(200, {"archived": True})])
        gf.ClientGitHub("x", session).archiver("Org/web")
        self.assertEqual(session.appels[0][:2], ("PATCH", "/repos/Org/web"))
        self.assertEqual(session.appels[0][2]["json"], {"archived": True})


class TestLeMenu(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, reponses, client):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(TODO, "_git_client", return_value=client),
            mock.patch.object(
                gm.manifest_repo,
                "forks_orphelins",
                return_value=([depot("a"), depot("b")], 3),
            ),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch("builtins.print") as sortie,
        ):
            code = todo._git_forks_orphelins()
        return code, "\n".join(str(c.args[0]) for c in sortie.call_args_list)

    def test_listing_alone_archives_nothing(self):
        client = mock.Mock()
        code, texte = self.lancer(["Org", ""], client)
        self.assertEqual(code, 0)
        self.assertIn("[2] Org/b · dernier push 2026-01-02", texte)
        self.assertIn("2 forks orphelins · 3 déjà archivés", texte)
        client.archiver.assert_not_called()
        self.lancer(["Org", "all", "n"], client)
        client.archiver.assert_not_called()

    def test_the_checked_ones_are_archived_after_confirmation(self):
        client = mock.Mock()
        client.archiver.side_effect = [gf.ErreurGitHub("PATCH : 403", 403), {}]
        code, texte = self.lancer(["Org", "all", "o"], client)
        self.assertEqual(code, 1)
        self.assertIn("❌ Org/a : PATCH : 403", texte)
        self.assertIn("✓ Org/b", texte)


if __name__ == "__main__":
    unittest.main()
