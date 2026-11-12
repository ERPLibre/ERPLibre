#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les dépôts des manifestes : en ajouter un, y créer une branche, poser
son remote amont, par le module, sa ligne de commande et le menu.

Les manifestes et les dépôts git sont jetables ; GitHub et les branches
distantes sont remplacés : rien ne va sur le réseau.
"""

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

GEL = "c" * 40
IDENTITE = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@exemple.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@exemple.invalid",
}

MANIFESTE = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="OCA" fetch="https://github.com/OCA/" />

    <project
        name="account-analytic.git"
        revision="18.0"
        freeze-revision="{gel}"
        path="odoo18.0/addons/OCA_account-analytic"
        remote="OCA"
        groups="addons,odoo18.0"
    />
    <project
        name="web.git"
        revision="18.0"
        freeze-revision="{gel}"
        path="odoo18.0/addons/OCA_web"
        remote="OCA"
        groups="addons,odoo18.0"
    />
</manifest>
"""


def git(chemin, *args):
    subprocess.run(
        ["git", "-C", chemin, *args],
        check=True,
        capture_output=True,
        env=dict(os.environ, **IDENTITE),
    )


class Dossier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)
        self.manifestes = os.path.join(self.tmp.name, "manifest")
        os.makedirs(self.manifestes)
        self.fichier = os.path.join(
            self.manifestes, "git_manifest_odoo18.0.xml"
        )
        with open(self.fichier, "w") as fh:
            fh.write(MANIFESTE.format(gel=GEL))

    def lire(self):
        with open(self.fichier) as fh:
            return fh.read()


class TestLAjout(Dossier):
    def ajouter(self, url, branches=("18.0", "17.0"), **kw):
        with (
            mock.patch.object(
                mr.repo_upgrade,
                "branches",
                return_value=None if branches is None else set(branches),
            ),
            mock.patch.object(mr, "tete", return_value=GEL),
        ):
            return mr.ajouter_depot(url, "18.0", dossier=self.manifestes, **kw)

    def test_a_new_organisation_gets_its_remote_and_the_project_is_sorted(
        self,
    ):
        fichier, plan, gel = self.ajouter("https://github.com/Exemple/outils")
        texte = self.lire()
        self.assertEqual(plan["path"], "odoo18.0/addons/Exemple_outils")
        self.assertEqual(gel, GEL)
        self.assertIn(
            '<remote name="Exemple" fetch="https://github.com/Exemple/" />',
            texte,
        )
        # Rangé par chemin : « exemple_outils » précède « oca_… ».
        self.assertLess(
            texte.index("Exemple_outils"), texte.index("OCA_account-analytic")
        )
        self.assertIn(
            '        name="outils.git"\n        revision="18.0"\n'
            f'        freeze-revision="{GEL}"\n'
            '        path="odoo18.0/addons/Exemple_outils"\n'
            '        remote="Exemple"\n        groups="addons,odoo18.0"\n    />',
            texte,
        )

    def test_a_known_organisation_reuses_its_remote(self):
        _f, plan, _g = self.ajouter("git@github.com:OCA/zzz-tools.git")
        self.assertEqual(plan["remote"], "OCA")
        self.assertFalse(plan["nouveau_remote"])
        texte = self.lire()
        self.assertEqual(texte.count("<remote "), 1)
        self.assertLess(texte.index("OCA_web"), texte.index("OCA_zzz-tools"))

    def test_an_unfrozen_request_writes_no_freeze(self):
        _f, _p, gel = self.ajouter(
            "https://github.com/Exemple/outils", geler=False, branche="17.0"
        )
        self.assertIsNone(gel)
        bloc = self.lire().split('name="outils.git"')[1].split("/>")[0]
        self.assertNotIn("freeze-revision", bloc)
        self.assertIn('revision="17.0"', bloc)

    def test_refusals_write_nothing(self):
        avant = self.lire()
        for url, branches in (
            ("https://github.com/OCA/web", ("18.0",)),
            ("https://github.com/Exemple/outils", ("16.0",)),
            ("https://github.com/Exemple/outils", None),
            ("https://gitlab.com/Exemple/outils", ("18.0",)),
        ):
            with self.subTest(url=url, branches=branches):
                with self.assertRaises(ValueError):
                    self.ajouter(url, branches)
                self.assertEqual(self.lire(), avant)

    def test_an_origin_remote_or_another_case_is_not_taken_for_the_owner(self):
        plan = mr.plan_ajout(
            "https://github.com/technolibre/outil",
            "18.0",
            "18.0",
            {
                "ERPLibre_origin_bemade": "https://github.com/technolibre/",
                "TechnoLibre": "https://github.com/TechnoLibre/",
            },
        )
        self.assertEqual(plan["remote"], "TechnoLibre")
        self.assertEqual(plan["path"], "odoo18.0/addons/TechnoLibre_outil")
        plan = mr.plan_ajout(
            "https://github.com/bemade/outil",
            "18.0",
            "18.0",
            {"ERPLibre_origin_bemade": "https://github.com/bemade/"},
        )
        self.assertEqual(plan["remote"], "bemade")

    def test_a_fork_of_the_repository_counts_as_already_there(self):
        with open(self.fichier, "a") as fh:
            pass
        texte = self.lire().replace(
            "</manifest>",
            '    <remote name="ERPLibre_origin_OCA" fetch="https://github.com/ERPLibre/" />\n'
            '    <project name="ai.git" revision="18.0_dev"'
            ' path="odoo18.0/addons/OCA_ai" remote="ERPLibre_origin_OCA"'
            ' fork-upstream-remote="OCA" fork-upstream="18.0" />\n</manifest>',
        )
        with open(self.fichier, "w") as fh:
            fh.write(texte)
        with self.assertRaises(ValueError):
            self.ajouter("https://github.com/OCA/ai")

    def test_a_branch_name_with_xml_characters_keeps_the_manifest_readable(
        self,
    ):
        self.ajouter(
            "https://github.com/Exemple/outils",
            branches=('fix&co"x',),
            branche='fix&co"x',
        )
        _r, projets = mr.repo_upgrade.lire_manifestes("18.0", self.manifestes)
        relu = next(p for p in projets.values() if p["name"] == "outils.git")
        self.assertEqual(relu["revision"], 'fix&co"x')

    def test_a_remote_only_in_another_file_is_declared_in_the_main_one(self):
        with open(
            os.path.join(self.manifestes, "git_manifest_odoo18.0_dev.xml"), "w"
        ) as fh:
            fh.write(
                '<?xml version="1.0" ?>\n<manifest>\n'
                '    <remote name="Exemple" fetch="https://github.com/Exemple/" />\n'
                "</manifest>\n"
            )
        _f, plan, _g = self.ajouter("https://github.com/Exemple/outils")
        self.assertFalse(plan["nouveau_remote"])
        self.assertIn('<remote name="Exemple"', self.lire())

    def test_a_remote_name_taken_by_another_url_is_refused(self):
        with self.assertRaises(ValueError):
            mr.plan_ajout(
                "https://github.com/OCA/x",
                "18.0",
                "18.0",
                {"OCA": "https://github.com/Autre/"},
            )


class Clone(Dossier):
    def depot(self, nom, nu=False):
        chemin = os.path.join(self.tmp.name, nom)
        if nu:
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "18.0", chemin],
                check=True,
                capture_output=True,
            )
            return chemin
        os.makedirs(chemin)
        git(chemin, "init", "-q", "-b", "18.0")
        open(os.path.join(chemin, "f"), "w").close()
        git(chemin, "add", "f")
        git(chemin, "commit", "-q", "-m", "init")
        return chemin


class TestLaBranche(Clone):
    def test_create_switch_and_push_with_tracking(self):
        clone = self.depot("clone")
        nu = self.depot("fork.git", nu=True)
        git(clone, "remote", "add", "fork", nu)
        etapes = mr.brancher(clone, "18.0_ma_fonction", pousser="fork")
        self.assertEqual(
            [(e, c) for e, c, _s in etapes], [("branche", 0), ("push", 0)]
        )
        courante = subprocess.run(
            ["git", "-C", clone, "branch", "--show-current"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(courante, "18.0_ma_fonction")
        suivie = subprocess.run(
            ["git", "-C", clone, "rev-parse", "--abbrev-ref", "@{u}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(suivie, "fork/18.0_ma_fonction")

    def test_an_invalid_name_or_existing_branch_stops(self):
        clone = self.depot("clone")
        self.assertEqual(mr.brancher(clone, "a..b")[0][0], "nom")
        etapes = mr.brancher(clone, "18.0", pousser="fork")
        self.assertEqual(len(etapes), 1)
        self.assertNotEqual(etapes[0][1], 0)


class TestLAmont(Clone):
    def test_the_declared_upstream_is_added_and_fetched(self):
        amont = os.path.join(self.tmp.name, "amont")
        os.makedirs(amont)
        source = self.depot("source")
        nu = os.path.join(amont, "ai.git")
        subprocess.run(
            ["git", "clone", "-q", "--bare", source, nu],
            check=True,
            capture_output=True,
        )
        clone = self.depot("clone")
        projet = {
            "name": "ai.git",
            "path": "odoo18.0/addons/OCA_ai",
            "remote": "MonOrg_origin_OCA",
            "fork-upstream-remote": "OCA",
            "fork-upstream": "18.0",
        }
        remotes = {"OCA": amont + "/", "MonOrg_origin_OCA": "https://x/"}
        etat, detail = mr.ajouter_amont(clone, projet, remotes)
        self.assertEqual((etat, detail), ("ajoute", "OCA/18.0"))
        refs = subprocess.run(
            ["git", "-C", clone, "branch", "-r"],
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("OCA/18.0", refs)
        self.assertEqual(
            mr.ajouter_amont(clone, projet, remotes)[0], "present"
        )

    def test_a_project_without_declared_upstream_says_why(self):
        clone = self.depot("clone")
        etat, detail = mr.ajouter_amont(
            clone, {"name": "x.git", "remote": "OCA"}, {"OCA": "https://x/"}
        )
        self.assertIsNone(etat)
        self.assertTrue(detail)


class TestLaLigneDeCommande(Dossier):
    def test_add_prints_the_new_project(self):
        sortie = []
        with (
            mock.patch.object(mr.repo_upgrade, "DOSSIER", self.manifestes),
            mock.patch.object(
                mr.repo_upgrade, "branches", return_value={"18.0"}
            ),
            mock.patch.object(mr, "tete", return_value=GEL),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: sortie.append(
                    " ".join(map(str, a))
                ),
            ),
        ):
            code = mr.main(
                [
                    "add",
                    "https://github.com/Exemple/outils",
                    "--version",
                    "18.0",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("odoo18.0/addons/Exemple_outils", sortie[0])

    def test_fork_without_manifest_change(self):
        client = mock.Mock()
        client.forker.return_value = (
            {"full_name": "MonOrg/web", "name": "web", "html_url": "u"},
            True,
        )
        client.attendre.return_value = True
        client.branche.return_value = None
        avant = self.lire()
        with (
            mock.patch.object(mr.repo_upgrade, "DOSSIER", self.manifestes),
            mock.patch.object(mr.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                mr.github_fork, "ClientGitHub", return_value=client
            ),
            mock.patch("builtins.print"),
        ):
            code = mr.main(
                [
                    "fork",
                    "OCA_web",
                    "--organisation",
                    "MonOrg",
                    "--version",
                    "18.0",
                    "--no-manifest",
                ]
            )
        self.assertEqual(code, 0)
        client.forker.assert_called_once_with("OCA", "web", "MonOrg", False)
        client.creer_branche.assert_called_once_with("MonOrg/web", "18.0", GEL)
        self.assertEqual(self.lire(), avant)

    def test_fork_then_manifest_and_unknown_path(self):
        client = mock.Mock()
        client.forker.return_value = (
            {"full_name": "MonOrg/web", "name": "web", "html_url": "u"},
            False,
        )
        client.branche.return_value = GEL
        with (
            mock.patch.object(mr.repo_upgrade, "DOSSIER", self.manifestes),
            mock.patch.object(mr.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                mr.github_fork, "ClientGitHub", return_value=client
            ),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(
                mr.main(
                    [
                        "fork",
                        "OCA_web",
                        "--organisation",
                        "MonOrg",
                        "--version",
                        "18.0",
                    ]
                ),
                0,
            )
            self.assertEqual(
                mr.main(
                    [
                        "fork",
                        "absent",
                        "--organisation",
                        "MonOrg",
                        "--version",
                        "18.0",
                    ]
                ),
                1,
            )
        self.assertIn('remote="MonOrg_origin_OCA"', self.lire())


class TestLesGardes(Clone):
    def test_forking_into_the_owner_is_refused_and_writes_nothing(self):
        client = mock.Mock()
        avant = self.lire()
        with (
            mock.patch.object(mr.repo_upgrade, "DOSSIER", self.manifestes),
            mock.patch.object(mr.github_fork, "jeton", return_value="x"),
            mock.patch.object(
                mr.github_fork, "ClientGitHub", return_value=client
            ),
            mock.patch("builtins.print"),
        ):
            code = mr.main(
                [
                    "fork",
                    "OCA_web",
                    "--organisation",
                    "oca",
                    "--version",
                    "18.0",
                ]
            )
        self.assertEqual(code, 1)
        client.forker.assert_not_called()
        self.assertEqual(self.lire(), avant)

    def test_a_shallow_clone_fetches_the_upstream_at_its_depth(self):
        projet = {
            "name": "ai.git",
            "remote": "X_origin_OCA",
            "fork-upstream-remote": "OCA",
            "fork-upstream": "18.0",
            "clone-depth": "1",
        }
        remotes = {"OCA": "https://github.com/OCA/"}
        with (
            mock.patch.object(
                mr.repo_upgrade,
                "preparer_remote",
                return_value=("ajoute", "u"),
            ),
            mock.patch.object(
                mr.repo_upgrade, "est_superficiel", return_value=True
            ),
            mock.patch.object(
                mr.repo_upgrade, "recuperer_amont", return_value=True
            ) as fetch,
        ):
            mr.ajouter_amont("/c", projet, remotes)
        self.assertEqual(fetch.call_args.kwargs["profondeur"], "1")

    def test_a_remote_at_another_url_says_how_to_fix_it(self):
        projet = {
            "name": "ai.git",
            "remote": "X_origin_OCA",
            "fork-upstream-remote": "OCA",
            "fork-upstream": "18.0",
        }
        with mock.patch.object(
            mr.repo_upgrade,
            "preparer_remote",
            return_value=("autre_url", "https://vieux/ai.git"),
        ):
            etat, detail = mr.ajouter_amont(
                "/c", projet, {"OCA": "https://github.com/OCA/"}
            )
        self.assertEqual(etat, "autre_url")
        self.assertIn(
            "remote set-url OCA https://github.com/OCA/ai.git", detail
        )
        self.assertIn("https://vieux/ai.git", detail)


class TestLeMenu(Dossier):
    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def todo(self):
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    def test_add_asks_url_version_branch_freeze_then_offers_the_fork(self):
        todo = self.todo()
        with (
            mock.patch.object(gm.repo_upgrade, "DOSSIER", self.manifestes),
            mock.patch.object(
                gm.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(
                mr.repo_upgrade, "branches", return_value={"18.0"}
            ),
            mock.patch.object(mr, "tete", return_value=GEL),
            mock.patch(
                "builtins.input",
                side_effect=[
                    "https://github.com/Exemple/outils",
                    "",
                    "",
                    "",
                    "o",
                ],
            ),
            mock.patch.object(
                type(todo), "_git_fork_organisation", return_value=0
            ) as fork,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(todo._git_ajouter_depot(), 0)
        self.assertIn("Exemple_outils", self.lire())
        version, choix = fork.call_args.args
        self.assertEqual(version, "18.0")
        self.assertEqual(choix[0]["path"], "odoo18.0/addons/Exemple_outils")

    def test_branch_and_upstream_commands_call_the_module(self):
        todo = self.todo()
        projet = {"path": "odoo18.0/addons/OCA_web"}
        with (
            mock.patch.object(
                type(todo),
                "_git_choisir_clone",
                return_value=({}, projet, "/c"),
            ),
            mock.patch.object(
                gm.manifest_repo, "remotes_du_clone", return_value=["origin"]
            ),
            mock.patch.object(
                gm.manifest_repo, "brancher", return_value=[("branche", 0, "")]
            ) as brancher,
            mock.patch.object(
                gm.manifest_repo,
                "ajouter_amont",
                return_value=("ajoute", "OCA/18.0"),
            ) as amont,
            mock.patch(
                "builtins.input", side_effect=["ma_branche", "", "origin"]
            ),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(todo._git_creer_branche(), 0)
            self.assertEqual(todo._git_ajouter_amont(), 0)
        brancher.assert_called_once_with("/c", "ma_branche", None, "origin")
        amont.assert_called_once_with("/c", projet, {})

    def test_an_unknown_push_remote_is_refused(self):
        todo = self.todo()
        with (
            mock.patch.object(
                type(todo), "_git_choisir_clone", return_value=({}, {}, "/c")
            ),
            mock.patch.object(
                gm.manifest_repo, "remotes_du_clone", return_value=["origin"]
            ),
            mock.patch.object(gm.manifest_repo, "brancher") as brancher,
            mock.patch("builtins.input", side_effect=["b", "", "inconnu"]),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(todo._git_creer_branche(), 2)
        brancher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
