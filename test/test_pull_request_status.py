#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'état des pull requests d'un auteur : la CI d'un commit, la revue qui
compte, le filtre aux dépôts des manifestes, le rapport et le menu. GitHub
est un faux client, sans réseau."""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import github_fork as gf  # noqa: E402
from script.git import manifest_repo as mr  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def check(status, conclusion=None):
    return {"status": status, "conclusion": conclusion}


class TestLaCI(unittest.TestCase):
    def test_no_ci_at_all_is_none(self):
        self.assertIsNone(
            mr.etat_ci({"total_count": 0, "state": "pending"}, [])
        )

    def test_one_failure_wins_over_success_and_running(self):
        checks = [
            check("completed", "success"),
            check("in_progress"),
            check("completed", "timed_out"),
        ]
        self.assertEqual(mr.etat_ci({"total_count": 0}, checks), "echec")
        statut = {"total_count": 1, "state": "failure"}
        self.assertEqual(
            mr.etat_ci(statut, [check("completed", "success")]), "echec"
        )

    def test_running_then_success(self):
        self.assertEqual(
            mr.etat_ci({"total_count": 1, "state": "pending"}, []), "en_cours"
        )
        self.assertEqual(mr.etat_ci(None, [check("queued")]), "en_cours")
        checks = [check("completed", "success"), check("completed", "skipped")]
        self.assertEqual(
            mr.etat_ci({"total_count": 1, "state": "success"}, checks),
            "succes",
        )


class TestLaRevue(unittest.TestCase):
    def avis(self, *paires):
        return [{"user": {"login": u}, "state": e} for u, e in paires]

    def test_the_last_decisive_review_of_each_reviewer_counts(self):
        self.assertIsNone(mr.etat_revue([]))
        self.assertIsNone(mr.etat_revue(self.avis(("a", "COMMENTED"))))
        avis = self.avis(
            ("a", "CHANGES_REQUESTED"), ("a", "COMMENTED"), ("a", "APPROVED")
        )
        self.assertEqual(mr.etat_revue(avis), "approuvee")
        avis = self.avis(("a", "APPROVED"), ("a", "COMMENTED"))
        self.assertEqual(mr.etat_revue(avis), "approuvee")

    def test_one_reviewer_asking_changes_wins(self):
        avis = self.avis(("a", "APPROVED"), ("b", "CHANGES_REQUESTED"))
        self.assertEqual(mr.etat_revue(avis), "changements")
        avis = self.avis(("b", "CHANGES_REQUESTED"), ("b", "DISMISSED"))
        self.assertIsNone(mr.etat_revue(avis))


def item(depot, numero, etat="open", fusion=None, draft=False):
    return {
        "repository_url": f"{gf.API}/repos/{depot}",
        "number": numero,
        "title": f"T{numero}",
        "html_url": f"https://github.com/{depot}/pull/{numero}",
        "state": etat,
        "draft": draft,
        "pull_request": {"merged_at": fusion},
    }


class Client:
    def __init__(self, items):
        self.items = items
        self.details = []

    def mes_pull_requests(self, auteur):
        self.auteur = auteur
        return self.items

    def pull_request(self, depot, numero):
        self.details.append((depot, numero))
        return {"head": {"sha": f"sha{numero}"}}

    def avis(self, depot, numero):
        return (
            [{"user": {"login": "r"}, "state": "APPROVED"}]
            if numero == 1
            else []
        )

    def verifications(self, depot, sha):
        return {
            "total_count": 1,
            "state": "success" if sha == "sha1" else "failure",
        }, []


class TestLeStatut(unittest.TestCase):
    def test_states_details_only_for_open_and_the_manifest_filter(self):
        client = Client(
            [
                item("OCA/web", 1),
                item("OCA/web", 2, draft=True),
                item("OCA/web", 3, "closed", fusion="2026-01-01T00:00:00Z"),
                item("OCA/web", 4, "closed"),
                item("Autre/projet", 5),
            ]
        )
        prs = mr.statut_pull_requests(client, "moi", {"oca/web"})
        self.assertEqual(client.auteur, "moi")
        self.assertEqual(
            [(p["numero"], p["etat"], p["revue"], p["ci"]) for p in prs],
            [
                (1, "ouverte", "approuvee", "succes"),
                (2, "brouillon", None, "echec"),
                (3, "fusionnee", None, None),
                (4, "fermee", None, None),
            ],
        )
        self.assertEqual(
            sorted(client.details), [("OCA/web", 1), ("OCA/web", 2)]
        )
        self.assertEqual(
            len(
                mr.statut_pull_requests(
                    Client([item("Autre/projet", 5)]), "moi"
                )
            ),
            1,
        )

    def test_the_manifest_repos_include_the_fork_upstream(self):
        remotes = {"Org": {"fetch": "https://github.com/Org/"}}
        projet = {"name": "web.git", "remote": "Org", "path": "p"}
        with (
            mock.patch.object(
                mr,
                "projets_github",
                return_value=(remotes, [(projet, "Org", "web")]),
            ),
            mock.patch.object(
                mr,
                "cibles_pull_request",
                return_value={"amont": ("OCA/web", "18.0")},
            ),
        ):
            self.assertEqual(
                mr.depots_des_manifestes("18.0"), {"org/web", "oca/web"}
            )


class TestLAPI(unittest.TestCase):
    def test_search_pages_and_the_two_ci_systems(self):
        from test.test_pull_requests import Reponse, Session

        session = Session(
            [
                Reponse(200, {"items": [{"number": i} for i in range(100)]}),
                Reponse(200, {"items": [{"number": 100}]}),
                Reponse(200, {"state": "success", "total_count": 1}),
                Reponse(200, {"check_runs": [check("queued")]}),
            ]
        )
        client = gf.ClientGitHub("x", session)
        self.assertEqual(len(client.mes_pull_requests("moi")), 101)
        self.assertEqual(
            session.appels[0][2]["params"]["q"], "is:pr author:moi"
        )
        statut, checks = client.verifications("OCA/web", "abc")
        self.assertEqual(
            (statut["state"], checks), ("success", [check("queued")])
        )
        self.assertEqual(
            session.appels[3][1], "/repos/OCA/web/commits/abc/check-runs"
        )


class TestLeMenu(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def test_open_ones_come_first_with_review_and_ci(self):
        prs = [
            {
                "depot": "OCA/web",
                "numero": 3,
                "titre": "F",
                "url": "u3",
                "etat": "fusionnee",
                "revue": None,
                "ci": None,
            },
            {
                "depot": "OCA/web",
                "numero": 1,
                "titre": "O",
                "url": "u1",
                "etat": "ouverte",
                "revue": "changements",
                "ci": "en_cours",
            },
        ]
        lignes = gm.lignes_statut("moi", prs)
        self.assertIn("✋ changements demandés · ⏳ CI en cours", lignes[1])
        self.assertTrue(lignes[1].startswith("  🟢 OCA/web#1"))
        self.assertTrue(lignes[2].startswith("  🟣 OCA/web#3 F — u3"))
        self.assertEqual(lignes[-1], "🟢 1 · 📝 0 · 🟣 1 · ⚫ 0")

    def test_the_menu_restricts_to_the_manifests_unless_refused(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        client = mock.Mock()
        client.utilisateur.return_value = "moi"
        for reponse, depots in (("", {"oca/web"}), ("n", None)):
            with (
                mock.patch.object(
                    gm.repo_upgrade, "version_active", return_value="18.0"
                ),
                mock.patch.object(TODO, "_git_client", return_value=client),
                mock.patch.object(
                    gm.manifest_repo,
                    "depots_des_manifestes",
                    return_value={"oca/web"},
                ),
                mock.patch.object(
                    gm.manifest_repo, "statut_pull_requests", return_value=[]
                ) as appel,
                mock.patch("builtins.input", return_value=reponse),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(todo._git_statut_mes_pull_requests(), 0)
            appel.assert_called_once_with(client, "moi", depots)


if __name__ == "__main__":
    unittest.main()
