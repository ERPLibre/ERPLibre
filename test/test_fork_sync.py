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
    """Le choix multiple des forks à avancer : [0], une réponse vide et
    Ctrl+D ne demandent rien à GitHub ; une faute est nommée et
    redemandée ; un fork se coche aussi par son chemin."""

    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, reponses, gele=False, client=None, forks=(FORK, FORK)):
        """(ce que rend le menu, le client, le double de `_git_client`,
        ce qui s'est imprimé, le port) après `reponses`, données au port
        dans l'ordre ; le port lève EOFError, comme Ctrl+D, quand elles
        manquent."""
        from script.todo import ui
        from script.todo.todo import TODO
        from script.todo.ui.port import ScriptedPort

        todo = TODO.__new__(TODO)
        client = client or Client()
        port = ScriptedPort(reponses)
        with (
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(
                gm.manifest_repo,
                "forks_du_manifeste",
                return_value=list(forks),
            ),
            mock.patch.object(
                gm.manifest_repo, "mode_gele", return_value=gele
            ),
            mock.patch.object(
                TODO, "_git_client", return_value=client
            ) as fabrique,
            mock.patch("builtins.print") as sortie,
            ui.bind(port),
        ):
            code = todo._git_mettre_forks_a_jour()
        return (
            code,
            client,
            fabrique,
            "\n".join(
                " ".join(str(a) for a in c.args) for c in sortie.call_args_list
            ),
            port,
        )

    def test_the_checked_forks_are_updated_and_a_frozen_checkout_is_warned(
        self,
    ):
        code, client, _f, texte, port = self.lancer(["2"], gele=True)
        self.assertEqual((code, client.synchros), (0, [("Org/web", "18.0")]))
        self.assertIn("⏩ Org/web:18.0 · fast-forward", texte)
        self.assertIn("gelé", texte)
        choix = [e for e in port.events if e.get("kind") == "choose"]
        self.assertTrue(choix[0]["multi"])
        self.assertEqual(
            choix[0]["options"][0]["label"],
            "addons/OCA_web · Org/web:18.0 ← OCA/web:18.0",
        )
        for tous in ("all", "tout", "*", "1-2"):
            with self.subTest(tous=tous):
                code, client, _f, texte, _p = self.lancer(
                    [tous], client=Client(code=409, corps={"message": "c"})
                )
                self.assertEqual(code, 2)
                self.assertEqual(len(client.synchros), 2)
                self.assertIn("conflit : à fusionner à la main — c", texte)
                self.assertNotIn("gelé", texte)

    def test_a_fork_is_checked_by_its_path(self):
        brume = ("addons/Brume_lanterne", "Org/lanterne", "18.0", "", "")
        code, client, _f, texte, _p = self.lancer(
            ["addons/OCA_web"], forks=(FORK, brume)
        )
        self.assertEqual((code, client.synchros), (0, [("Org/web", "18.0")]))
        code, client, _f, texte, _p = self.lancer(
            ["addons/Brume_lanterne"], forks=(FORK, brume)
        )
        self.assertEqual(client.synchros, [])
        self.assertIn("Org/lanterne:18.0", texte)

    def test_a_path_two_forks_carry_is_no_name(self):
        # Deux forks au même chemin : ce chemin n'en coche aucun, la
        # réponse est nommée invalide, et seul le numéro les départage.
        sorbier = ("addons/OCA_web", "Sorbier/web", "18.0", "OCA/web", "18.0")
        code, client, _f, _t, port = self.lancer(
            ["addons/OCA_web", "2", "de trop"], forks=(FORK, sorbier)
        )
        self.assertEqual(
            (code, client.synchros), (0, [("Sorbier/web", "18.0")])
        )
        avis = [e for e in port.events if e.get("t") == "notice"]
        self.assertEqual(
            [a["text"] for a in avis], ["Choix invalide : addons/OCA_web"]
        )
        self.assertEqual(port.answers, ["de trop"])

    def test_a_typo_is_named_and_asked_again(self):
        for faute in ("3", "1 3", "web", "2-3"):
            with self.subTest(faute=faute):
                code, client, _f, _t, port = self.lancer([faute, "1"])
                self.assertEqual(
                    (code, client.synchros), (0, [("Org/web", "18.0")])
                )
                avis = [e for e in port.events if e.get("t") == "notice"]
                self.assertEqual(
                    [a["text"] for a in avis], [f"Choix invalide : {faute}"]
                )

    def test_a_back_asks_nothing_of_github(self):
        # [0], une réponse vide et Ctrl+D : aucun client, donc aucun
        # jeton lu ni appel réseau ; la réponse de trop reste au port.
        for reponse in ("0", "", EOFError()):
            with self.subTest(reponse=reponse):
                code, client, fabrique, _t, port = self.lancer(
                    [reponse, "de trop"]
                )
                self.assertIsNone(code)
                self.assertEqual(client.synchros, [])
                fabrique.assert_not_called()
                self.assertEqual(port.answers, ["de trop"])


if __name__ == "__main__":
    unittest.main()
