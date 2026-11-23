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
from script.todo.todo_i18n import t  # noqa: E402

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


# Le rapport de verifier_jeton() d'un jeton qui permet tout.
JETON_SAIN = {"login": "moi", "portees": ["repo"], "role": None, "codes": []}


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
                gm.github_fork, "verifier_jeton", return_value=JETON_SAIN
            ),
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
            ["ai", "1", "MonOrg", "", "", "o", "o", "", "n"]
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
            ["ai", "1", "MonOrg", "2", "2", "o", "o", "17.0,18.0", "n"]
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
            ["ai", "1", "MonOrg", "", "", "n"], jeton=""
        )
        self.assertEqual(code, 2)
        fabrique.assert_not_called()


LUNE = {
    "path": "odoo18.0/addons/Bidon_lune",
    "name": "lune.git",
    "remote": "Bidon",
    "revision": "18.0",
}
SOLEIL = {
    "path": "odoo18.0/addons/Bidon_soleil",
    "name": "soleil.git",
    "remote": "Bidon",
    "revision": "18.0",
}
PROJETS = [LUNE, SOLEIL]
URL_AJOUT = "https://github.com/Bidon/outils-fictifs"
# Ce que le menu lit dans manifest_repo sans rien écrire, lancer ni
# demander au réseau : tout autre appel est une action.
LECTEURS = {
    "versions_installees",
    "depot_de_l_url",
    "clones_non_declares",
    "lire_clone",
    "remotes_du_clone",
    "branche_poussee",
    "cibles_pull_request",
    "branche_proposee",
    "gel_par_defaut",
}
# Les trois retours d'un choix sans défaut : [0], une réponse vide, Ctrl+D.
RETOURS = ("0", "", EOFError())


class LeMenuGit(unittest.TestCase):
    """Les méthodes du menu Répertoire git, questions posées au port
    scripté ; `input` n'a que les réponses `saisies`. manifest_repo est
    un double, GitHub aussi : rien n'est écrit, lancé ni envoyé."""

    def lancer(
        self,
        methode,
        reponses,
        *args,
        saisies=(),
        branches=True,
        installees=("17.0", "18.0"),
        manifestes=("17.0", "18.0"),
        ajoute="odoo18.0/addons/outils",
    ):
        """(retour de `methode(*args)`, double de manifest_repo, port,
        fabrique du client GitHub). `branches` faux : l'hôte ne dit pas
        ses branches ; `installees`, les versions installées ;
        `manifestes`, celles qui ont un manifeste ; `ajoute`, le chemin du
        projet qu'écrit `ajouter_depot`. Le double de `print` reste dans
        `self.imprime`."""
        from script.todo import ui
        from script.todo.todo import TODO
        from script.todo.ui.port import ScriptedPort

        todo = TODO.__new__(TODO)
        double = mock.Mock(name="manifest_repo")
        double.versions_installees.return_value = list(installees)
        double.depot_de_l_url.return_value = "outils-fictifs"
        double.clones_non_declares.return_value = [("18.0", LUNE["path"])]
        double.lire_clone.return_value = {
            "url": URL_AJOUT,
            "remote": "origin",
            "branche": "18.0",
            "sha": GEL,
            "pousse": True,
        }
        double.remotes_du_clone.return_value = ["origin"]
        double.branche_proposee.return_value = "18.0"
        double.gel_par_defaut.return_value = False
        double.ajouter_depot.return_value = (
            os.path.join(gm.RACINE, "manifest", "default.dev.xml"),
            {"path": ajoute, "remote": "r", "revision": "b"},
            None,
        )
        double.retirer_depot.return_value = (
            os.path.join(gm.RACINE, "manifest", "default.dev.xml"),
            LUNE,
            None,
        )
        double.plan_nettoyage.return_value = (
            ["18.0"],
            {},
            {"locales": {"fini": "fusion"}, "distantes": {}},
        )
        port = ScriptedPort(reponses)
        lu = ({"18.0", "main"}, "18.0") if branches else None
        with (
            mock.patch.object(gm, "manifest_repo", double),
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(
                gm.repo_upgrade,
                "lire_manifestes",
                return_value=({}, {p["path"]: p for p in PROJETS}),
            ),
            mock.patch.object(
                gm.repo_upgrade, "branches_et_defaut", return_value=lu
            ),
            mock.patch.object(gm, "clones", return_value=({}, PROJETS)),
            mock.patch.object(
                gm, "versions_des_manifestes", return_value=list(manifestes)
            ),
            mock.patch.object(
                gm,
                "projets_github",
                return_value=({}, [(p, "Bidon", p["name"]) for p in PROJETS]),
            ),
            mock.patch.object(
                gm.github_fork, "depot_github", return_value=("Bidon", "x")
            ),
            mock.patch.object(gm.github_fork, "ClientGitHub") as fabrique,
            mock.patch("builtins.input", side_effect=list(saisies)),
            mock.patch("builtins.print") as self.imprime,
            ui.bind(port),
        ):
            retour = getattr(todo, methode)(*args)
        return retour, double, port, fabrique

    def assertRienNAgit(self, double, fabrique):
        appeles = {appel[0].split(".")[0] for appel in double.method_calls}
        self.assertLessEqual(appeles, LECTEURS)
        fabrique.assert_not_called()

    def choix(self, port):
        """Les questions à choix qu'a posées le port."""
        return [e for e in port.events if e.get("kind") == "choose"]

    def imprime_texte(self):
        """Tout ce que le menu a imprimé, une ligne par appel."""
        return "\n".join(
            " ".join(str(a) for a in appel.args)
            for appel in self.imprime.call_args_list
        )


class TestUnRetourNAgitPas(LeMenuGit):
    """[0], une réponse vide ou Ctrl+D au choix d'un dépôt, d'une version
    ou de la visibilité : l'appelant revient sans rien écrire, retirer,
    supprimer ni demander à GitHub."""

    # Les appelants du choix d'un clone de la version active, et ce
    # qu'ils rendent sur un retour.
    PAR_CLONE = {
        "_git_creer_branche": 0,
        "_git_ajouter_amont": 0,
        "_git_regeler_depot": 0,
        "_git_nettoyer_branches": None,
        "_git_creer_pull_request": None,
    }

    def test_each_caller_of_the_clone_choice(self):
        for methode, attendu in self.PAR_CLONE.items():
            # Filtre vide puis chaque retour, et Ctrl+D dès le filtre ; le
            # « 1 » qui suit choisirait un dépôt s'il était lu.
            cas = [["", reponse] for reponse in RETOURS] + [[EOFError()]]
            for reponses in cas:
                with self.subTest(methode=methode, reponses=reponses):
                    retour, double, port, fabrique = self.lancer(
                        methode, [*reponses, "1"]
                    )
                    self.assertEqual(retour, attendu)
                    self.assertRienNAgit(double, fabrique)
                    self.assertEqual(port.answers, ["1"])

    def test_the_repository_to_fork(self):
        for reponses in (
            ["", "0"],
            ["", ""],
            ["", EOFError()],
            [EOFError()],
        ):
            with self.subTest(reponses=reponses):
                retour, double, port, fabrique = self.lancer(
                    "_git_fork_organisation", [*reponses, "1"]
                )
                self.assertEqual(retour, 0)
                self.assertRienNAgit(double, fabrique)
                self.assertEqual(port.answers, ["1"])

    def test_remove_and_synchronise_at_the_version_or_the_repository(self):
        for methode in ("_git_retirer_depot", "_git_synchroniser_depot"):
            for reponses in (
                ["0"],
                [EOFError()],
                ["", "", "0"],
                ["", "", ""],
                ["", "", EOFError()],
            ):
                with self.subTest(methode=methode, reponses=reponses):
                    retour, double, _p, fabrique = self.lancer(
                        methode, reponses
                    )
                    self.assertEqual(retour, 0)
                    self.assertRienNAgit(double, fabrique)

    def test_add_a_repository_at_the_version_or_the_visibility(self):
        for reponses in (
            ["0"],
            [EOFError()],
            ["", "0"],
            ["", ""],
            ["", EOFError()],
        ):
            with self.subTest(reponses=reponses):
                retour, double, _p, fabrique = self.lancer(
                    "_git_ajouter_depot", reponses, saisies=[URL_AJOUT]
                )
                self.assertEqual(retour, 0)
                self.assertRienNAgit(double, fabrique)

    def test_add_an_existing_clone_at_the_version_or_the_visibility(self):
        # Un chemin hors des versions installées demande la version ; le
        # clone [1] passe directement à la visibilité.
        for saisie, reponse in (
            *(("odoo16.0/addons/Bidon_lune", r) for r in ("0", EOFError())),
            *(("1", r) for r in RETOURS),
        ):
            with self.subTest(saisie=saisie, reponse=reponse):
                retour, double, _p, fabrique = self.lancer(
                    "_git_ajouter_existant", [reponse], saisies=[saisie]
                )
                self.assertEqual(retour, 0)
                self.assertRienNAgit(double, fabrique)


class TestLesChoix(LeMenuGit):
    """Le choix d'un dépôt, d'une version et de la visibilité suit les
    règles communes : numéro affiché ou nom exact, [0], une saisie fautive
    nommée puis redemandée."""

    def test_a_typo_or_a_number_out_of_range_is_asked_again(self):
        retour, _d, port, _f = self.lancer(
            "_git_choisir_clone", ["", "9", "deux", "2"]
        )
        self.assertEqual(retour[1], SOLEIL)
        self.assertEqual(retour[2], os.path.join(gm.RACINE, SOLEIL["path"]))
        erreurs = [e for e in port.events if e.get("t") == "notice"]
        self.assertEqual(len(erreurs), 2)
        self.assertEqual(len(self.choix(port)), 3)

    def test_a_repository_by_its_path(self):
        retour, _d, _p, _f = self.lancer(
            "_git_choisir_clone", ["", SOLEIL["path"]]
        )
        self.assertEqual(retour[1], SOLEIL)

    def test_the_filter_narrows_the_list_and_back_is_offered(self):
        retour, _d, port, _f = self.lancer(
            "_git_choisir_clone", ["SOLEIL", "1"]
        )
        self.assertEqual(retour[1], SOLEIL)
        (question,) = self.choix(port)
        self.assertEqual([o["key"] for o in question["options"]], ["1", "0"])
        self.assertIsNone(question["default"])

    def test_a_filter_that_matches_nothing_asks_no_number(self):
        retour, _d, port, _f = self.lancer("_git_choisir_clone", ["mars"])
        self.assertIsNone(retour)
        self.assertEqual(self.choix(port), [])

    def test_the_fork_lists_the_owner_and_takes_the_path(self):
        # Le chemin seul choisit le projet ; l'organisation laissée vide,
        # ou Ctrl+D à sa question, arrête le parcours avant GitHub.
        from script.todo.todo import TODO

        for organisation in ("", EOFError()):
            with (
                self.subTest(organisation=organisation),
                mock.patch.object(TODO, "_git_fork_choisir_mode") as mode,
            ):
                retour, double, port, fabrique = self.lancer(
                    "_git_fork_organisation",
                    ["", LUNE["path"], organisation],
                )
                self.assertEqual(retour, 0)
                (question,) = self.choix(port)
                libelles = [o["label"] for o in question["options"]]
                self.assertEqual(
                    libelles[0], f"{LUNE['path']}  (Bidon/lune.git)"
                )
                notices = [e for e in port.events if e.get("t") == "notice"]
                self.assertFalse(notices)
                mode.assert_not_called()
                self.assertRienNAgit(double, fabrique)

    def test_a_version_by_its_number_its_name_or_the_active_one(self):
        for reponses, attendu in (
            (["17.0"], "17.0"),
            (["2"], "18.0"),
            ([""], "18.0"),
            (["16.0", "1"], "17.0"),
            (["0"], None),
            ([EOFError()], None),
        ):
            with self.subTest(reponses=reponses):
                retour, _d, port, _f = self.lancer(
                    "_git_choisir_version", reponses, "18.0"
                )
                self.assertEqual(retour, attendu)
                self.assertEqual(self.choix(port)[0]["default"], "2")

    def test_a_version_without_a_manifest_is_no_default(self):
        retour, _d, port, _f = self.lancer(
            "_git_choisir_version", [""], "16.0"
        )
        self.assertIsNone(retour)
        self.assertIsNone(self.choix(port)[0]["default"])
        self.assertIn(
            f"16.0 : {t('no manifest for this version.')}",
            self.imprime_texte(),
        )

    def test_no_manifest_at_all_asks_nothing(self):
        for methode, args, quoi in (
            ("_git_choisir_version", ("18.0",), {"manifestes": ()}),
            ("_git_choisir_version_installee", (), {"installees": ()}),
        ):
            with self.subTest(methode=methode):
                retour, _d, port, _f = self.lancer(
                    methode, ["1"], *args, **quoi
                )
                self.assertIsNone(retour)
                self.assertEqual(port.events, [])
                self.assertIn(
                    t("No Odoo version has a manifest."), self.imprime_texte()
                )

    def test_the_installed_version_defaults_to_the_active_one(self):
        for reponses, attendu in (
            ([""], "18.0"),
            (["17.0"], "17.0"),
            (["1"], "17.0"),
            (["3", "2"], "18.0"),
            (["0"], None),
            ([EOFError()], None),
        ):
            with self.subTest(reponses=reponses):
                retour, _d, port, _f = self.lancer(
                    "_git_choisir_version_installee", reponses
                )
                self.assertEqual(retour, attendu)
                self.assertEqual(self.choix(port)[0]["default"], "2")

    def test_one_installed_version_is_not_asked(self):
        retour, _d, port, _f = self.lancer(
            "_git_choisir_version_installee", [], installees=["18.0"]
        )
        self.assertEqual(retour, "18.0")
        self.assertEqual(port.events, [])

    def test_the_visibility_has_no_default(self):
        for reponses, attendu in (
            (["1"], False),
            (["2"], True),
            (["3", "2"], True),
            ([""], None),
            (["0"], None),
            ([EOFError()], None),
        ):
            with self.subTest(reponses=reponses):
                retour, _d, port, _f = self.lancer(
                    "_git_choisir_visibilite", reponses
                )
                self.assertIs(retour, attendu)
                question = self.choix(port)[0]
                self.assertIsNone(question["default"])
                self.assertEqual(
                    [o["key"] for o in question["options"]], ["1", "2", "0"]
                )


class TestCtrlDApresLeChoix(LeMenuGit):
    """Ctrl+D à une question qui suit le choix d'un dépôt revient sans
    rien écrire, retirer ni supprimer, et sans trace."""

    def test_create_a_branch_at_its_name_start_or_remote(self):
        # « origin », lu après le Ctrl+D, ferait pousser la branche.
        for reste in ([], ["b"], ["b", ""]):
            with self.subTest(reste=reste):
                retour, double, port, _f = self.lancer(
                    "_git_creer_branche",
                    ["", "1", *reste, EOFError(), "origin"],
                )
                self.assertEqual(retour, 0)
                double.brancher.assert_not_called()
                self.assertEqual(port.answers, ["origin"])

    def test_freeze_again_at_the_commit(self):
        retour, double, _p, _f = self.lancer(
            "_git_regeler_depot", ["", "1", EOFError()]
        )
        self.assertEqual(retour, 0)
        double.regeler.assert_not_called()

    def test_remove_at_the_confirmation_then_at_the_clone(self):
        retour, double, _p, _f = self.lancer(
            "_git_retirer_depot", ["", "", "1", EOFError()]
        )
        self.assertEqual(retour, 0)
        double.retirer_depot.assert_not_called()
        retour, double, _p, _f = self.lancer(
            "_git_retirer_depot", ["", "", "1", "o", EOFError()]
        )
        self.assertEqual(retour, 0)
        double.retirer_depot.assert_called_once_with("18.0", LUNE["path"])
        double.executer.assert_not_called()

    def test_clean_branches_at_each_question(self):
        for reste in ([], ["n"]):
            with self.subTest(reste=reste):
                retour, double, _p, fabrique = self.lancer(
                    "_git_nettoyer_branches", ["", "1", *reste, EOFError()]
                )
                self.assertIsNone(retour)
                double.plan_nettoyage.assert_not_called()
                fabrique.assert_not_called()
        retour, double, _p, _f = self.lancer(
            "_git_nettoyer_branches", ["", "1", "n", "", EOFError()]
        )
        self.assertEqual(retour, 0)
        double.plan_nettoyage.assert_called_once()
        double.supprimer_branches.assert_not_called()

    def test_add_a_repository_at_each_question_before_writing(self):
        # Ctrl+D à la branche, au gel, puis à « l'ajouter sans vérifier » ;
        # le « o » qui suit, s'il était lu, mènerait jusqu'à l'écriture.
        for reponses, branches in (
            (["", "1", EOFError()], True),
            (["", "1", "", EOFError()], True),
            (["", "1", EOFError()], False),
        ):
            with self.subTest(reponses=reponses, branches=branches):
                retour, double, port, _f = self.lancer(
                    "_git_ajouter_depot",
                    [*reponses, "o"],
                    saisies=[URL_AJOUT],
                    branches=branches,
                )
                self.assertEqual(retour, 0)
                double.ajouter_depot.assert_not_called()
                self.assertEqual(port.answers, ["o"])

    def test_add_a_repository_then_ctrl_d_at_the_fork(self):
        # Le projet écrit est dans la liste des projets GitHub : « o »
        # forke, Ctrl+D non.
        from script.todo.todo import TODO

        for reponse, forke in (("o", True), (EOFError(), False)):
            with (
                self.subTest(reponse=reponse),
                mock.patch.object(
                    TODO, "_git_fork_organisation", return_value=0
                ) as fork,
            ):
                retour, double, _p, _f = self.lancer(
                    "_git_ajouter_depot",
                    ["", "1", "", "", reponse],
                    saisies=[URL_AJOUT],
                    ajoute=LUNE["path"],
                )
                self.assertEqual(retour, 0)
                double.ajouter_depot.assert_called_once()
                if forke:
                    fork.assert_called_once_with(
                        "18.0", (LUNE, "Bidon", LUNE["name"])
                    )
                else:
                    fork.assert_not_called()

    def test_add_an_existing_clone_at_the_freeze(self):
        retour, double, _p, _f = self.lancer(
            "_git_ajouter_existant", ["1", EOFError()], saisies=["1"]
        )
        self.assertEqual(retour, 0)
        double.ajouter_existant.assert_not_called()


if __name__ == "__main__":
    unittest.main()
