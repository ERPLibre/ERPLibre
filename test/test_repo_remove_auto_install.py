#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Désactiver auto_install : la réécriture des manifestes, le commit qui
n'emporte qu'eux, le traitement en parallèle, et le menu Analyse module
qui choisit les dépôts dans le manifeste.

Les dépôts sont de vrais dépôts git jetables ; aucun push ne part.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.git import repo_remove_auto_install as rai  # noqa: E402
from script.todo import module_menu, todo_i18n  # noqa: E402

MANIFESTE = """{
    "name": "Exemple",
    "depends": ["base"],
    # 'auto_install': True, laissé en commentaire
    "auto_install": True,
    'installable': True,
}
"""


IDENTITE = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@exemple.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@exemple.invalid",
}


def git(depot, *args):
    subprocess.run(
        ["git", "-C", depot, *args],
        check=True,
        capture_output=True,
        env=dict(os.environ, **IDENTITE),
    )


class Depots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Le commit du script prend l'identité de l'environnement : un poste
        # de test sans user.email global ne doit pas le faire échouer.
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)

    def depot(self, nom, modules=("a",), auto=True):
        depot = os.path.join(self.tmp.name, nom)
        for module in modules:
            chemin = Path(depot, module, "__manifest__.py")
            chemin.parent.mkdir(parents=True)
            texte = (
                MANIFESTE
                if auto
                else MANIFESTE.replace("True,\n    '", "False,\n    '")
            )
            chemin.write_text(texte, encoding="utf-8")
        git(depot, "init", "-q", "-b", "main")
        git(depot, "add", ".")
        git(depot, "commit", "-q", "-m", "init")
        return depot


class TestLaReecriture(Depots):
    def test_only_the_live_key_turns_false(self):
        depot = self.depot("d", modules=("a", "b"))
        changes = rai.desactiver(depot)
        self.assertEqual(len(changes), 2)
        texte = Path(depot, "a", "__manifest__.py").read_text()
        self.assertIn('"auto_install": False,', texte)
        self.assertIn("# 'auto_install': True, laissé en commentaire", texte)
        self.assertIn("'installable': True,", texte)
        self.assertEqual(rai.desactiver(depot), [])

    def test_git_internals_are_never_read(self):
        depot = self.depot("d")
        cache = Path(depot, ".git", "x", "__manifest__.py")
        cache.parent.mkdir(parents=True)
        cache.write_text(MANIFESTE)
        rai.desactiver(depot)
        self.assertEqual(cache.read_text(), MANIFESTE)


class TestLeCommit(Depots):
    def test_only_the_changed_manifests_are_committed(self):
        depot = self.depot("d")
        Path(depot, "brouillon.txt").write_text("à ne pas committer")
        resultat = rai.traiter([depot], commit=True)[0]
        self.assertEqual(resultat["commit"][0], 0)
        self.assertIsNone(resultat["push"])
        etat = subprocess.run(
            ["git", "-C", depot, "status", "--porcelain"],
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(etat.strip(), "?? brouillon.txt")
        dernier = subprocess.run(
            ["git", "-C", depot, "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(dernier, rai.MESSAGE)

    def test_nothing_to_change_makes_no_commit(self):
        depot = self.depot("d", auto=False)
        resultat = rai.traiter([depot], commit=True, push=True)[0]
        self.assertEqual(resultat["fichiers"], [])
        self.assertIsNone(resultat["commit"])

    def test_every_repository_in_the_order_given(self):
        depots = [self.depot(f"d{i}") for i in range(5)]
        resultats = rai.traiter(depots, jobs=3)
        self.assertEqual([r["depot"] for r in resultats], depots)
        self.assertTrue(all(len(r["fichiers"]) == 1 for r in resultats))


class TestLaLigneDeCommande(Depots):
    def test_several_dirs_and_odoo_core_skipped(self):
        depots = [self.depot("x"), self.depot("odoo")]
        argv = ["prog", "--ignore_commit"]
        for d in depots:
            argv += ["--addons_dir", d]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(rai.main(), 0)
        self.assertIn(
            '"auto_install": False',
            Path(depots[0], "a", "__manifest__.py").read_text(),
        )
        self.assertIn(
            '"auto_install": True',
            Path(depots[1], "a", "__manifest__.py").read_text(),
        )


class TestLeMenu(Depots):
    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def projets(self):
        return {}, {
            "a": {"path": "odoo18.0/addons/OCA_a"},
            "b": {"path": "odoo18.0/addons/OCA_b"},
            "absent": {"path": "odoo18.0/addons/OCA_absent"},
            "coeur": {"path": "odoo18.0/odoo"},
        }

    def test_the_list_holds_cloned_addons_repositories_only(self):
        for chemin in (
            "odoo18.0/addons/OCA_a",
            "odoo18.0/addons/OCA_b",
            "odoo18.0/odoo",
        ):
            os.makedirs(os.path.join(self.tmp.name, chemin))
        with mock.patch.object(
            module_menu.repo_upgrade,
            "lire_manifestes",
            return_value=self.projets(),
        ):
            self.assertEqual(
                module_menu.depots_d_addons("18.0", self.tmp.name),
                ["odoo18.0/addons/OCA_a", "odoo18.0/addons/OCA_b"],
            )

    def lancer(self, reponses, confirmations=(False, False)):
        """(le double de `traiter`, celui de `click.confirm`, le port)
        après `reponses`, données au port dans l'ordre ; le port lève
        EOFError, comme Ctrl+D, quand elles manquent."""
        from script.todo import ui
        from script.todo.todo import TODO
        from script.todo.ui.port import ScriptedPort

        todo = TODO.__new__(TODO)
        depots = ["odoo18.0/addons/OCA_a", "odoo18.0/addons/OCA_b"]
        port = ScriptedPort(reponses)
        with (
            mock.patch.object(
                module_menu.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(
                module_menu, "depots_d_addons", return_value=depots
            ),
            mock.patch.object(module_menu, "RACINE", "/racine"),
            mock.patch(
                "click.confirm", side_effect=list(confirmations)
            ) as confirmer,
            mock.patch.object(
                module_menu.repo_remove_auto_install,
                "traiter",
                return_value=[],
            ) as traiter,
            mock.patch("builtins.print"),
            ui.bind(port),
        ):
            todo._module_auto_install()
        return traiter, confirmer, port

    def test_the_checked_repositories_are_handled_together(self):
        for choix in ("1,2", "1 2", "1-2", "all", "tout", "*"):
            with self.subTest(choix=choix):
                traiter, _c, port = self.lancer([choix])
                traiter.assert_called_once_with(
                    [
                        "/racine/odoo18.0/addons/OCA_a",
                        "/racine/odoo18.0/addons/OCA_b",
                    ],
                    commit=False,
                    push=False,
                )
        choix = [e for e in port.events if e.get("kind") == "choose"]
        self.assertTrue(choix[0]["multi"])

    def test_a_repository_is_checked_by_its_path(self):
        traiter, _c, _p = self.lancer(["odoo18.0/addons/OCA_b"])
        traiter.assert_called_once_with(
            ["/racine/odoo18.0/addons/OCA_b"], commit=False, push=False
        )

    def test_commit_and_push_only_when_asked(self):
        traiter, _c, _p = self.lancer(["2"], confirmations=(True, True))
        self.assertEqual(
            traiter.call_args.kwargs, {"commit": True, "push": True}
        )

    def test_a_back_runs_nothing(self):
        # [0], une réponse vide et Ctrl+D : ni réécriture, ni question de
        # commit ; la réponse de trop reste au port.
        for reponse in ("0", "", EOFError()):
            with self.subTest(reponse=reponse):
                traiter, confirmer, port = self.lancer([reponse, "de trop"])
                traiter.assert_not_called()
                confirmer.assert_not_called()
                self.assertEqual(port.answers, ["de trop"])

    def test_a_wrong_number_is_named_and_asked_again(self):
        for faute in ("9", "1,9", "OCA_a", "01"):
            with self.subTest(faute=faute):
                traiter, _c, port = self.lancer([faute, "1"])
                traiter.assert_called_once_with(
                    ["/racine/odoo18.0/addons/OCA_a"], commit=False, push=False
                )
                avis = [e for e in port.events if e.get("t") == "notice"]
                self.assertEqual(
                    [a["text"] for a in avis], [f"Choix invalide : {faute}"]
                )

    def test_entry_7_opens_it(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(TODO, "_module_auto_install") as action,
            mock.patch("click.prompt", side_effect=["7", "0"]),
            mock.patch("builtins.print"),
        ):
            todo.prompt_execute_module_analysis()
        action.assert_called_once_with()

    def test_the_report_counts_and_flags_failures(self):
        resultats = [
            {
                "depot": "/racine/a",
                "fichiers": ["x", "y"],
                "commit": (0, ""),
                "push": (1, "rejected"),
                "erreur": None,
            },
            {
                "depot": "/racine/b",
                "fichiers": [],
                "commit": None,
                "push": None,
                "erreur": None,
            },
        ]
        lignes = module_menu.rendre_auto_install(resultats, "/racine")
        self.assertIn("✓ a : 2 · commit ✓ · push ❌ (rejected)", lignes)
        self.assertIn("· b : 0", lignes)
        self.assertEqual(lignes[-1], "📋 2 manifestes modifiés")


if __name__ == "__main__":
    unittest.main()
