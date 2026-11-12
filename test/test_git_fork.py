#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Forker un dépôt pour une organisation : l'API GitHub, la réécriture du
manifeste, et le parcours du menu Répertoire git.

GitHub est remplacé par une fausse session, les manifestes sont fabriqués
dans un répertoire jetable : rien ne va sur le réseau ni dans manifest/.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import github_fork as gf  # noqa: E402
from script.git import manifest_fork as mf  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402

GEL = "a" * 40
BASE = "b" * 40

MANIFESTE = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="OCA" fetch="https://github.com/OCA/" />
    <remote name="ERPLibre_origin_OCA" fetch="https://github.com/ERPLibre/" />

    <!-- <project name="vieux.git" path="x" remote="OCA" /> -->
    <project
        name="ai.git"
        revision="{v}_dev"
        freeze-revision="{gel}"
        path="odoo{v}/addons/OCA_ai"
        remote="ERPLibre_origin_OCA"
        fork-upstream-remote="OCA"
        fork-upstream="{v}"
        fork-upstream-freeze-revision="{base}"
        groups="addons,odoo{v}"
    />
    <project
        name="server-tools.git"
        revision="{v}"
        freeze-revision="{gel}"
        path="odoo{v}/addons/OCA_server-tools"
        remote="OCA"
        groups="addons,odoo{v}"
    />
</manifest>
"""


class Reponse:
    def __init__(self, statut, corps=None):
        self.status_code = statut
        self._corps = corps or {}

    def json(self):
        return self._corps


class FausseSession:
    """Rend, pour (méthode, chemin), la réponse de la table ; note les
    appels. Une entrée absente répond 404."""

    def __init__(self, table):
        self.table = table
        self.appels = []

    def request(self, methode, url, **kw):
        chemin = url[len(gf.API) :]
        self.appels.append((methode, chemin, kw.get("json")))
        rep = self.table.get((methode, chemin), Reponse(404))
        return rep(kw) if callable(rep) else rep


class TestLesUrls(unittest.TestCase):
    def test_github_urls_only(self):
        for url in (
            "https://github.com/OCA/ai.git",
            "https://github.com/OCA/ai",
            "git@github.com:OCA/ai.git",
            "ssh://git@github.com/OCA/ai.git",
            "https://jeton@github.com/OCA/ai.git",
        ):
            self.assertEqual(gf.depot_github(url), ("OCA", "ai"), url)
        self.assertIsNone(gf.depot_github("https://gitlab.com/OCA/ai.git"))
        self.assertIsNone(gf.depot_github(""))

    def test_token_from_environment_then_env_var_sh(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "env_var.sh"), "w") as fh:
                fh.write('#!/bin/bash\nEL_GITHUB_TOKEN="du-fichier"\n')
            self.assertEqual(gf.jeton(tmp, {}), "du-fichier")
            self.assertEqual(
                gf.jeton(tmp, {"EL_GITHUB_TOKEN": "de-env"}), "de-env"
            )
            self.assertEqual(gf.jeton("/nulle/part", {}), "")


class TestLeClient(unittest.TestCase):
    def client(self, table):
        session = FausseSession(table)
        return gf.ClientGitHub("x", session, dormir=lambda s: None), session

    def test_a_fork_into_an_organisation_names_it(self):
        client, session = self.client(
            {
                ("GET", "/repos/OCA/ai"): Reponse(
                    200, {"full_name": "OCA/ai"}
                ),
                ("GET", "/user"): Reponse(200, {"login": "moi"}),
                ("POST", "/repos/OCA/ai/forks"): Reponse(
                    202, {"full_name": "MonOrg/ai", "name": "ai"}
                ),
            }
        )
        fork, cree = client.forker(
            "OCA", "ai", "MonOrg", toutes_branches=False
        )
        self.assertTrue(cree)
        self.assertEqual(fork["full_name"], "MonOrg/ai")
        corps = [c for m, p, c in session.appels if m == "POST"][0]
        self.assertEqual(
            corps, {"default_branch_only": True, "organization": "MonOrg"}
        )

    def test_a_fork_into_ones_own_account_omits_the_organisation(self):
        client, session = self.client(
            {
                ("GET", "/repos/OCA/ai"): Reponse(
                    200, {"full_name": "OCA/ai"}
                ),
                ("GET", "/user"): Reponse(200, {"login": "Moi"}),
                ("POST", "/repos/OCA/ai/forks"): Reponse(
                    202, {"full_name": "Moi/ai"}
                ),
            }
        )
        client.forker("OCA", "ai", "moi", toutes_branches=True)
        corps = [c for m, p, c in session.appels if m == "POST"][0]
        self.assertEqual(corps, {"default_branch_only": False})

    def test_an_existing_fork_of_the_same_network_is_reused(self):
        client, session = self.client(
            {
                ("GET", "/repos/ERPLibre/ai"): Reponse(
                    200,
                    {
                        "full_name": "ERPLibre/ai",
                        "source": {"full_name": "OCA/ai"},
                    },
                ),
                ("GET", "/repos/MonOrg/ai"): Reponse(
                    200,
                    {
                        "full_name": "MonOrg/ai",
                        "fork": True,
                        "source": {"full_name": "OCA/ai"},
                    },
                ),
            }
        )
        fork, cree = client.forker("ERPLibre", "ai", "MonOrg", False)
        self.assertFalse(cree)
        self.assertNotIn("POST", [m for m, _p, _c in session.appels])

    def test_a_same_named_unrelated_repository_is_refused(self):
        client, _ = self.client(
            {
                ("GET", "/repos/OCA/ai"): Reponse(
                    200, {"full_name": "OCA/ai"}
                ),
                ("GET", "/repos/MonOrg/ai"): Reponse(
                    200, {"full_name": "MonOrg/ai", "fork": False}
                ),
            }
        )
        with self.assertRaises(gf.ErreurGitHub):
            client.forker("OCA", "ai", "MonOrg", False)

    def test_waiting_polls_until_the_fork_answers(self):
        reponses = [Reponse(404), Reponse(404), Reponse(200, {})]
        client, _ = self.client(
            {("GET", "/repos/MonOrg/ai"): lambda kw: reponses.pop(0)}
        )
        self.assertTrue(client.attendre("MonOrg/ai", delai=10, pas=1))
        client, _ = self.client({})
        self.assertFalse(client.attendre("MonOrg/ai", delai=2, pas=1))

    def test_a_branch_is_created_once_and_never_moved(self):
        client, _ = self.client(
            {("POST", "/repos/MonOrg/ai/git/refs"): Reponse(201)}
        )
        self.assertTrue(client.creer_branche("MonOrg/ai", "18.0_dev", GEL))
        client, _ = self.client(
            {
                ("POST", "/repos/MonOrg/ai/git/refs"): Reponse(422),
                ("GET", "/repos/MonOrg/ai/branches/18.0_dev"): Reponse(
                    200, {"commit": {"sha": GEL}}
                ),
            }
        )
        self.assertFalse(client.creer_branche("MonOrg/ai", "18.0_dev", GEL))
        with self.assertRaises(gf.ErreurGitHub):
            client.creer_branche("MonOrg/ai", "18.0_dev", BASE)


class Manifestes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for v in ("17.0", "18.0"):
            with open(
                os.path.join(self.tmp.name, f"git_manifest_odoo{v}.xml"), "w"
            ) as fh:
                fh.write(MANIFESTE.format(v=v, gel=GEL, base=BASE))

    def lire(self, v):
        with open(
            os.path.join(self.tmp.name, f"git_manifest_odoo{v}.xml")
        ) as fh:
            return fh.read()

    def projet(self, v, path_fin):
        remotes, liste = gm.projets_github(v, self.tmp.name)
        return remotes, next(
            p for p, *_ in liste if p["path"].endswith(path_fin)
        )


class TestLePlan(Manifestes):
    def test_keep_the_original_upstream_changes_only_the_remote(self):
        remotes, projet = self.projet("18.0", "OCA_ai")
        plan = mf.plan(projet, remotes, "MonOrg", mf.AMONT_ORIGINE)
        self.assertEqual(plan["remote"], "MonOrg_origin_OCA")
        self.assertEqual((plan["attrs"], plan["retirer"]), ({}, []))
        neuf, trouve = mf.appliquer(
            self.lire("18.0"), "ai.git", "odoo18.0/addons/OCA_ai", plan
        )
        self.assertTrue(trouve)
        self.assertIn('remote="MonOrg_origin_OCA"', neuf)
        self.assertIn('fork-upstream-remote="OCA"', neuf)
        self.assertIn(f'fork-upstream-freeze-revision="{BASE}"', neuf)
        self.assertIn(
            '<remote name="MonOrg_origin_OCA" fetch="https://github.com/MonOrg/" />',
            neuf,
        )

    def test_the_current_fork_becomes_the_upstream(self):
        remotes, projet = self.projet("18.0", "OCA_ai")
        plan = mf.plan(projet, remotes, "MonOrg", mf.AMONT_FORK)
        self.assertEqual(plan["remote"], "MonOrg_origin_ERPLibre")
        self.assertEqual(
            plan["attrs"],
            {
                "fork-upstream-remote": "ERPLibre_origin_OCA",
                "fork-upstream": "18.0_dev",
                "fork-upstream-freeze-revision": GEL,
            },
        )

    def test_a_plain_project_gets_its_source_as_upstream(self):
        remotes, projet = self.projet("18.0", "OCA_server-tools")
        for mode in (mf.AMONT_ORIGINE, mf.AMONT_FORK):
            plan = mf.plan(projet, remotes, "MonOrg", mode)
            self.assertEqual(plan["remote"], "MonOrg_origin_OCA")
            self.assertEqual(plan["attrs"]["fork-upstream-remote"], "OCA")
            self.assertEqual(plan["attrs"]["fork-upstream"], "18.0")
        neuf, _ = mf.appliquer(
            self.lire("18.0"),
            "server-tools.git",
            "odoo18.0/addons/OCA_server-tools",
            plan,
        )
        bloc = neuf[neuf.index('name="server-tools.git"') :]
        bloc = bloc[: bloc.index("/>")]
        self.assertIn('remote="MonOrg_origin_OCA"', bloc)
        self.assertLess(
            bloc.index('remote="MonOrg_origin_OCA"'),
            bloc.index('fork-upstream-remote="OCA"'),
        )
        self.assertLess(
            bloc.index('fork-upstream="18.0"'),
            bloc.index(f'fork-upstream-freeze-revision="{GEL}"'),
        )

    def test_a_renamed_fork_keeps_the_upstream_name(self):
        remotes, projet = self.projet("18.0", "OCA_server-tools")
        plan = mf.plan(
            projet, remotes, "MonOrg", mf.AMONT_FORK, "server-tools-1"
        )
        self.assertEqual(plan["name"], "server-tools-1.git")
        self.assertEqual(
            plan["attrs"]["fork-upstream-name"], "server-tools.git"
        )

    def test_only_an_origin_remote_of_the_organisation_is_reused(self):
        """Un remote simple vers l'organisation n'est pas repris : le nom
        « _origin_ » est ce qui fait reconnaître un fork."""
        remotes, projet = self.projet("18.0", "OCA_ai")
        simple = dict(remotes, MonOrg="https://github.com/MonOrg/")
        plan = mf.plan(projet, simple, "MonOrg", mf.AMONT_ORIGINE)
        self.assertEqual(plan["remote"], "MonOrg_origin_OCA")
        origine = dict(remotes, monorg_origin_oca="https://github.com/monorg")
        plan = mf.plan(projet, origine, "MonOrg", mf.AMONT_ORIGINE)
        self.assertEqual(plan["remote"], "monorg_origin_oca")
        self.assertFalse(plan["nouveau_remote"])

    def test_the_rewritten_project_is_still_seen_as_a_fork(self):
        remotes, projet = self.projet("18.0", "OCA_server-tools")
        remotes = dict(remotes, MonOrg="https://github.com/MonOrg/")
        plan = mf.plan(projet, remotes, "MonOrg", mf.AMONT_FORK)
        neuf, _ = mf.appliquer(
            self.lire("18.0"),
            "server-tools.git",
            "odoo18.0/addons/OCA_server-tools",
            plan,
        )
        chemin = os.path.join(self.tmp.name, "git_manifest_odoo18.0.xml")
        with open(chemin, "w") as fh:
            fh.write(neuf)
        relus, projets = gm.repo_upgrade.lire_manifestes("18.0", self.tmp.name)
        relu = next(
            p for p in projets.values() if p["name"] == "server-tools.git"
        )
        amont = gm.repo_upgrade.resoudre_amont(relu, relus)
        self.assertEqual(amont["remote"], "OCA")
        self.assertEqual(amont["source"], "declare")

    def test_a_remote_declared_elsewhere_is_declared_here_too(self):
        remotes, projet = self.projet("18.0", "OCA_ai")
        remotes = dict(remotes, MonOrg_origin_OCA="https://github.com/MonOrg/")
        plan = mf.plan(projet, remotes, "MonOrg", mf.AMONT_ORIGINE)
        self.assertFalse(plan["nouveau_remote"])
        neuf, _ = mf.appliquer(
            self.lire("18.0"), "ai.git", "odoo18.0/addons/OCA_ai", plan
        )
        self.assertIn('<remote name="MonOrg_origin_OCA"', neuf)

    def test_a_remote_name_taken_by_another_url_is_refused(self):
        remotes, projet = self.projet("18.0", "OCA_ai")
        remotes = dict(remotes, MonOrg_origin_OCA="https://github.com/Autre/")
        with self.assertRaises(ValueError):
            mf.plan(projet, remotes, "MonOrg", mf.AMONT_ORIGINE)

    def test_comments_and_other_projects_stay_byte_for_byte(self):
        remotes, projet = self.projet("18.0", "OCA_ai")
        texte = self.lire("18.0")
        plan = mf.plan(projet, remotes, "MonOrg", mf.AMONT_ORIGINE)
        neuf, _ = mf.appliquer(texte, "ai.git", "odoo18.0/addons/OCA_ai", plan)
        self.assertIn(
            '<!-- <project name="vieux.git" path="x" remote="OCA" /> -->', neuf
        )
        debut = texte.index('    <project\n        name="server-tools.git"')
        self.assertEqual(
            neuf[
                neuf.index('    <project\n        name="server-tools.git"') :
            ],
            texte[debut:],
        )


class TestLesVersions(Manifestes):
    def test_versions_and_files_of_a_repository(self):
        self.assertEqual(
            gm.versions_des_manifestes(self.tmp.name), ["17.0", "18.0"]
        )
        par = gm.versions_du_depot("erplibre", "AI", self.tmp.name)
        self.assertEqual(sorted(par), ["17.0", "18.0"])
        self.assertTrue(
            gm.fichier_du_projet(
                "17.0", "ai.git", "odoo17.0/addons/OCA_ai", self.tmp.name
            ).endswith("git_manifest_odoo17.0.xml")
        )
        self.assertIsNone(
            gm.fichier_du_projet("17.0", "x", "y", self.tmp.name)
        )


class TestLeParcours(Manifestes):
    def lancer(self, reponses, jeton="x"):
        """Le parcours avec `reponses` au clavier, GitHub remplacé ; rend
        (code, client)."""
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        client = mock.Mock()
        client.forker.return_value = (
            {"full_name": "MonOrg/ai", "name": "ai", "html_url": "u"},
            True,
        )
        client.attendre.return_value = True
        client.branche.return_value = None
        with (
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(gm.repo_upgrade, "DOSSIER", self.tmp.name),
            mock.patch.object(gm.github_fork, "jeton", return_value=jeton),
            mock.patch.object(
                gm.github_fork, "ClientGitHub", return_value=client
            ) as fabrique,
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch("builtins.print"),
        ):
            code = todo._git_fork_organisation()
        return code, client, fabrique

    def test_the_active_version_only_by_default(self):
        # filtre, numéro, organisation, amont [1], branche active [1],
        # confirmation, manifeste oui, versions (Entrée).
        code, client, _ = self.lancer(
            ["ai", "1", "MonOrg", "", "", "o", "o", ""]
        )
        self.assertEqual(code, 0)
        client.forker.assert_called_once_with(
            "ERPLibre", "ai", "MonOrg", False
        )
        client.creer_branche.assert_called_with("MonOrg/ai", "18.0_dev", GEL)
        self.assertIn('remote="MonOrg_origin_OCA"', self.lire("18.0"))
        self.assertNotIn("MonOrg", self.lire("17.0"))

    def test_every_version_asked_and_all_branches(self):
        code, client, _ = self.lancer(
            ["ai", "1", "MonOrg", "2", "2", "o", "o", "17.0,18.0"]
        )
        client.forker.assert_called_once_with("ERPLibre", "ai", "MonOrg", True)
        client.creer_branche.assert_not_called()
        for v in ("17.0", "18.0"):
            self.assertIn('remote="MonOrg_origin_ERPLibre"', self.lire(v))
            self.assertIn(
                'fork-upstream-remote="ERPLibre_origin_OCA"', self.lire(v)
            )

    def test_nothing_happens_without_confirmation(self):
        code, client, _ = self.lancer(["ai", "1", "MonOrg", "", "", "n"])
        client.forker.assert_not_called()
        self.assertNotIn("MonOrg", self.lire("18.0"))

    def test_the_manifest_is_untouched_when_declined(self):
        code, client, _ = self.lancer(["ai", "1", "MonOrg", "", "", "o", "n"])
        client.forker.assert_called_once()
        self.assertNotIn("MonOrg", self.lire("18.0"))

    def test_without_token_nothing_is_called(self):
        code, _, fabrique = self.lancer(
            ["ai", "1", "MonOrg", "", ""], jeton=""
        )
        self.assertEqual(code, 2)
        fabrique.assert_not_called()


if __name__ == "__main__":
    unittest.main()
