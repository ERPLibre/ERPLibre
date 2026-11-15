#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Mettre un fork à jour depuis son amont par merge-upstream : les forks
du manifeste, les gardes (même branche, parent GitHub = amont déclaré),
les réponses de l'API, le menu. GitHub est faux, sans réseau."""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import github_fork as gf  # noqa: E402
from script.git import manifest_repo as mr  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_pull_requests import Reponse, Session  # noqa: E402

FORK = ("addons/OCA_web", "Org/web", "18.0", "OCA/web", "18.0")


class Client:
    def __init__(self, parent="OCA/web", code=200, corps=None):
        self.parent = parent
        self.code = code
        self.corps = (
            corps if corps is not None else {"merge_type": "fast-forward"}
        )
        self.synchros = []

    def depot(self, proprietaire, nom):
        if self.parent is None:
            return None
        return {"parent": {"full_name": self.parent}}

    def synchroniser_fork(self, fork, branche):
        self.synchros.append((fork, branche))
        if self.code == 500:
            raise gf.ErreurGitHub("POST : 500")
        return self.code, self.corps


class TestLesGardes(unittest.TestCase):
    def test_states_from_the_api(self):
        for code, corps, etat in (
            (200, {"merge_type": "fast-forward"}, "avance"),
            (200, {"merge_type": "merge"}, "fusion"),
            (200, {"merge_type": "none"}, "a_jour"),
            (409, {"message": "conflit"}, "conflit"),
            (422, {"message": "non"}, "refus"),
        ):
            self.assertEqual(
                mr.synchroniser_un_fork(
                    Client(code=code, corps=corps), *FORK[1:]
                )[0],
                etat,
            )

    def test_nothing_is_called_unless_parent_and_branch_match(self):
        cas = (
            (Client(), ("Org/web", "18.0", "OCA/web", "17.0")),
            (Client(), ("Org/web", "18.0", None, None)),
            (Client(), ("Org/web", None, "OCA/web", "18.0")),
            (Client(parent="Autre/web"), FORK[1:]),
            (Client(parent=None), FORK[1:]),
        )
        for client, entree in cas:
            self.assertEqual(
                mr.synchroniser_un_fork(client, *entree)[0], "ignore"
            )
            self.assertEqual(client.synchros, [])
        client = Client(parent="oca/WEB")
        self.assertEqual(
            mr.synchroniser_un_fork(client, *FORK[1:])[0], "avance"
        )

    def test_an_api_error_stays_with_its_fork(self):
        res = mr.synchroniser_forks(Client(code=500), [FORK, FORK])
        self.assertEqual([e for _f, e, _d in res], ["erreur", "erreur"])


class TestLesForks(unittest.TestCase):
    def test_only_forks_with_their_declared_upstream(self):
        remotes = {
            "OCA": {"fetch": "https://github.com/OCA/"},
            "Org_origin_OCA": {"fetch": "https://github.com/Org/"},
        }
        fork = {
            "path": "addons/OCA_web",
            "name": "web.git",
            "remote": "Org_origin_OCA",
            "revision": "18.0",
        }
        autre = {
            "path": "addons/OCA_tools",
            "name": "tools.git",
            "remote": "OCA",
            "revision": "18.0",
        }
        liste = [(fork, "Org", "web"), (autre, "OCA", "tools")]
        with (
            mock.patch.object(
                mr, "projets_github", return_value=(remotes, liste)
            ),
            mock.patch.object(
                mr.repo_upgrade,
                "resoudre_amont",
                return_value={
                    "url": "https://github.com/OCA/web.git",
                    "branche": "18.0",
                },
            ),
        ):
            self.assertEqual(mr.forks_du_manifeste("18.0"), [FORK])


class TestLAPI(unittest.TestCase):
    def test_merge_upstream_posts_the_branch_and_keeps_409(self):
        session = Session([Reponse(409, {"message": "conflit"})])
        client = gf.ClientGitHub("x", session)
        self.assertEqual(
            client.synchroniser_fork("Org/web", "18.0"),
            (409, {"message": "conflit"}),
        )
        methode, chemin, kw = session.appels[0]
        self.assertEqual(
            (methode, chemin, kw["json"]),
            ("POST", "/repos/Org/web/merge-upstream", {"branch": "18.0"}),
        )


class TestLeMenu(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, saisie, gele=False, client=None):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        client = client or Client()
        with (
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(
                gm.manifest_repo,
                "forks_du_manifeste",
                return_value=[FORK, FORK],
            ),
            mock.patch.object(
                gm.manifest_repo, "mode_gele", return_value=gele
            ),
            mock.patch.object(TODO, "_git_client", return_value=client),
            mock.patch("builtins.input", return_value=saisie),
            mock.patch("builtins.print") as sortie,
        ):
            code = todo._git_mettre_forks_a_jour()
        return (
            code,
            client,
            "\n".join(str(c.args[0]) for c in sortie.call_args_list),
        )

    def test_the_checked_forks_are_updated_and_a_frozen_checkout_is_warned(
        self,
    ):
        code, client, texte = self.lancer("2", gele=True)
        self.assertEqual((code, client.synchros), (0, [("Org/web", "18.0")]))
        self.assertIn("⏩ Org/web:18.0 · fast-forward", texte)
        self.assertIn("gelé", texte)
        code, _client, texte = self.lancer(
            "all", client=Client(code=409, corps={"message": "c"})
        )
        self.assertEqual(code, 2)
        self.assertIn("conflit : à fusionner à la main — c", texte)
        self.assertNotIn("gelé", texte)

    def test_enter_runs_nothing(self):
        code, client, _texte = self.lancer("")
        self.assertIsNone(code)
        self.assertEqual(client.synchros, [])


if __name__ == "__main__":
    unittest.main()
