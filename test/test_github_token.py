#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Vérifier le jeton GitHub avant d'agir : portées d'un jeton classique,
jeton à granularité fine, adhésion à l'organisation, jeton refusé, et le
menu qui le vérifie une fois par organisation. GitHub est faux."""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import github_fork as gf  # noqa: E402
from script.git import manifest_repo as mr  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_pull_requests import Reponse, Session  # noqa: E402


class AvecEntetes(Reponse):
    def __init__(self, statut, corps=None, entetes=None):
        super().__init__(statut, corps)
        self.headers = entetes or {}


class Client:
    def __init__(
        self,
        portees=("repo", "workflow"),
        adhesion=("membre", "admin"),
        refuse=False,
    ):
        self.portees = None if portees is None else list(portees)
        self.etat = adhesion
        self.refuse = refuse
        self.organisations = []

    def identite(self):
        if self.refuse:
            raise gf.ErreurGitHub("GET /user : 401 Bad credentials", 401)
        return "moi", self.portees

    def adhesion(self, organisation):
        self.organisations.append(organisation)
        return self.etat


class TestLaVerification(unittest.TestCase):
    def test_a_full_classic_token_reports_nothing(self):
        rapport = gf.verifier_jeton(Client(), "Org")
        self.assertEqual(
            rapport,
            {
                "login": "moi",
                "portees": ["repo", "workflow"],
                "role": "admin",
                "codes": [],
            },
        )

    def test_scopes(self):
        self.assertEqual(
            gf.verifier_jeton(Client(portees=()))["codes"],
            ["sans_repo", "sans_workflow"],
        )
        self.assertEqual(
            gf.verifier_jeton(Client(portees=("public_repo", "workflow")))[
                "codes"
            ],
            ["public_seulement"],
        )
        self.assertEqual(
            gf.verifier_jeton(Client(portees=None))["codes"], ["jeton_fin"]
        )

    def test_membership_only_for_another_organisation(self):
        client = Client(adhesion=("absent", None))
        self.assertEqual(gf.verifier_jeton(client, "MOI")["codes"], [])
        self.assertEqual(client.organisations, [])
        for etat, code in (
            ("absent", "pas_membre"),
            ("invitation", "invitation"),
            ("illisible", "adhesion_illisible"),
        ):
            self.assertEqual(
                gf.verifier_jeton(Client(adhesion=(etat, None)), "Org")[
                    "codes"
                ],
                [code],
            )
        self.assertTrue({"pas_membre", "invitation"} <= gf.PROBLEMES_JETON)
        self.assertNotIn("adhesion_illisible", gf.PROBLEMES_JETON)

    def test_a_refused_token_stops_there_other_errors_rise(self):
        client = Client(refuse=True)
        self.assertEqual(
            gf.verifier_jeton(client, "Org")["codes"], ["jeton_refuse"]
        )
        self.assertEqual(client.organisations, [])
        client = mock.Mock()
        client.identite.side_effect = gf.ErreurGitHub("GET /user : 502", 502)
        with self.assertRaises(gf.ErreurGitHub):
            gf.verifier_jeton(client)


class TestLAPI(unittest.TestCase):
    def test_scopes_header_and_membership_states(self):
        session = Session(
            [
                AvecEntetes(
                    200, {"login": "moi"}, {"X-OAuth-Scopes": "repo, read:org"}
                ),
                AvecEntetes(200, {"login": "moi"}),
                Reponse(200, {"state": "active", "role": "member"}),
                Reponse(200, {"state": "pending", "role": "member"}),
                Reponse(404, {"message": "Not Found"}),
                Reponse(403, {"message": "Forbidden"}),
            ]
        )
        client = gf.ClientGitHub("x", session)
        self.assertEqual(client.identite(), ("moi", ["repo", "read:org"]))
        self.assertEqual(client.identite(), ("moi", None))
        self.assertEqual(client.adhesion("Org"), ("membre", "member"))
        self.assertEqual(client.adhesion("Org"), ("invitation", None))
        self.assertEqual(client.adhesion("Org"), ("absent", None))
        self.assertEqual(client.adhesion("Org"), ("illisible", None))
        self.assertEqual(session.appels[2][1], "/user/memberships/orgs/Org")

    def test_an_api_error_carries_its_status(self):
        client = gf.ClientGitHub(
            "x", Session([Reponse(401, {"message": "Bad credentials"})])
        )
        with self.assertRaises(gf.ErreurGitHub) as ctx:
            client.utilisateur()
        self.assertEqual(ctx.exception.statut, 401)


class TestLeMenu(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)

    def client(self, faux, reponses=(), organisation=None):
        with (
            mock.patch.object(gm.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                gm.github_fork, "ClientGitHub", return_value=faux
            ),
            mock.patch("builtins.input", side_effect=list(reponses)) as entree,
            mock.patch("builtins.print") as sortie,
        ):
            client = self.todo._git_client(organisation)
        texte = "\n".join(str(c.args[0]) for c in sortie.call_args_list)
        return client, entree.call_count, texte

    def test_checked_once_per_organisation(self):
        faux = Client()
        self.assertIs(self.client(faux, organisation="Org")[0], faux)
        self.assertIs(self.client(faux, organisation="org")[0], faux)
        self.assertEqual(faux.organisations, ["Org"])
        self.client(faux, organisation="Autre")
        self.assertEqual(faux.organisations, ["Org", "Autre"])

    def test_a_problem_asks_before_acting_a_warning_does_not(self):
        client, questions, texte = self.client(
            Client(adhesion=("absent", None)), ["n"], "Org"
        )
        self.assertIsNone(client)
        self.assertEqual(questions, 1)
        self.assertIn("❌ Le compte du jeton n'est pas membre", texte)
        faux = Client(adhesion=("absent", None))
        self.assertIs(self.client(faux, ["o"], "Org")[0], faux)
        faux = Client(portees=None)
        client, questions, texte = self.client(faux)
        self.assertEqual((client, questions), (faux, 0))
        self.assertIn("⚠ Jeton à granularité fine", texte)

    def test_a_refused_token_stops_without_asking(self):
        client, questions, _texte = self.client(Client(refuse=True))
        self.assertEqual((client, questions), (None, 0))

    def test_the_check_entry_shows_account_and_scopes(self):
        with (
            mock.patch.object(gm.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                gm.github_fork, "ClientGitHub", return_value=Client()
            ),
            mock.patch("builtins.input", return_value="Org"),
            mock.patch("builtins.print") as sortie,
        ):
            self.assertEqual(self.todo._git_verifier_jeton(), 0)
        texte = "\n".join(str(c.args[0]) for c in sortie.call_args_list)
        self.assertIn(
            "Compte : moi · portées : repo, workflow · rôle : admin", texte
        )
        self.assertIn(
            "✓ Le jeton permet toutes les actions de ce menu.", texte
        )


class TestLaLigneDeCommande(unittest.TestCase):
    def test_a_problem_gives_exit_code_1(self):
        for faux, attendu in ((Client(), 0), (Client(portees=()), 1)):
            with (
                mock.patch.object(mr, "_client", return_value=faux),
                mock.patch.object(
                    mr.repo_upgrade, "version_active", return_value="18.0"
                ),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(
                    mr.main(["token", "--organisation", "Org"]), attendu
                )


if __name__ == "__main__":
    unittest.main()
