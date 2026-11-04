#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bilan d'ouverture du TODO : versions et hooks git."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from script.todo import todo_etat
from script.todo.todo_i18n import t


def git(racine, *args):
    subprocess.run(
        ["git", "-C", racine, *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Essai",
            "GIT_AUTHOR_EMAIL": "essai@exemple.invalid",
            "GIT_COMMITTER_NAME": "Essai",
            "GIT_COMMITTER_EMAIL": "essai@exemple.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )


@unittest.skipUnless(shutil.which("git"), "git absent")
class TestBilan(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp(prefix="todo_etat_")
        self.addCleanup(shutil.rmtree, self.racine)
        # Un core.hooksPath posé par la config globale de l'utilisateur
        # fausserait le cas « hooks manquants ».
        env = mock.patch.dict(
            os.environ,
            {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        env.start()
        self.addCleanup(env.stop)
        git(self.racine, "init", "-q")
        self.hooks = os.path.join(self.racine, "script", "git", "hooks")
        os.makedirs(self.hooks)
        for hook in todo_etat.HOOKS_GIT:
            chemin = os.path.join(self.hooks, hook)
            with open(chemin, "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(chemin, 0o755)
        with open(os.path.join(self.racine, "CHANGELOG.md"), "w") as fh:
            fh.write("## [Unreleased]\n\n## [9.9.1] - 2099-01-01\n")
        git(self.racine, "add", ".")
        git(self.racine, "commit", "-q", "-m", "init")

    def test_hooks_missing_warns_and_points_to_the_menu(self):
        ligne = todo_etat.ligne_hooks_git(self.racine)
        self.assertTrue(ligne.startswith(todo_etat.ALERTE))
        self.assertIn(t("Git hooks missing: Execute › Git › Settings"), ligne)

    def test_hooks_installed_get_the_check_mark(self):
        git(self.racine, "config", "core.hooksPath", "script/git/hooks")
        self.assertEqual(
            todo_etat.ligne_hooks_git(self.racine),
            f"{todo_etat.OK} {t('Git hooks installed')}",
        )

    def test_a_hook_without_exec_bit_warns(self):
        """git saute ce hook sans rien dire : le bilan, lui, le dit."""
        git(self.racine, "config", "core.hooksPath", "script/git/hooks")
        os.chmod(os.path.join(self.hooks, "commit-msg"), 0o644)
        ligne = todo_etat.ligne_hooks_git(self.racine)
        self.assertTrue(ligne.startswith(todo_etat.ALERTE))
        self.assertTrue(ligne.endswith("commit-msg"))

    def test_hooks_pointing_elsewhere_warn(self):
        git(self.racine, "config", "core.hooksPath", "ailleurs/hooks")
        ligne = todo_etat.ligne_hooks_git(self.racine)
        self.assertTrue(ligne.startswith(todo_etat.ALERTE))
        self.assertTrue(ligne.endswith("ailleurs/hooks"))

    def test_outside_a_checkout_the_hook_line_is_omitted(self):
        dehors = tempfile.mkdtemp(prefix="todo_etat_dehors_")
        self.addCleanup(shutil.rmtree, dehors)
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": dehors}):
            self.assertEqual(todo_etat.ligne_hooks_git(dehors), "")

    def test_version_on_the_tag(self):
        git(self.racine, "tag", "v9.9.2")
        self.assertEqual(todo_etat.version_erplibre(self.racine), "9.9.2")

    def test_version_after_the_tag_names_the_gap_and_the_commit(self):
        git(self.racine, "tag", "v9.9.2")
        git(self.racine, "commit", "-q", "--allow-empty", "-m", "suite")
        commit = subprocess.run(
            ["git", "-C", self.racine, "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        version = todo_etat.version_erplibre(self.racine)
        self.assertRegex(version, r"^9\.9\.2 \+1 \([0-9a-f]+\)$")
        self.assertTrue(commit.startswith(version.split("(")[1][:7]))

    def test_without_tag_the_changelog_gives_the_version(self):
        self.assertEqual(todo_etat.version_erplibre(self.racine), "9.9.1")

    def ecrire(self, chemin, contenu):
        chemin = os.path.join(self.racine, chemin)
        os.makedirs(os.path.dirname(chemin) or self.racine, exist_ok=True)
        with open(chemin, "w") as fh:
            fh.write(contenu)

    def test_versions_lines_skip_what_is_missing(self):
        self.ecrire(".odoo-version", "18.0\n")
        self.assertEqual(
            todo_etat.lignes_versions(self.racine),
            ["ERPLibre 9.9.1", "Odoo 18.0"],
        )

    def test_other_installed_versions_follow_the_active_one(self):
        """L'état d'ERPLibre donne les versions installées et leur Python ;
        une version désinstallée n'apparaît pas, « 9.0 » se range sous
        « 18.0 »."""
        self.ecrire(".odoo-version", "16.0\n")
        self.ecrire(".python-odoo-version", "3.10.14\n")
        self.ecrire(
            todo_etat.ETAT_ERPLIBRE,
            json.dumps(
                {
                    "odoo_versions": {
                        "9.0": {"installed": True, "python": "2.7.18"},
                        "16.0": {"installed": True, "python": "3.10.14"},
                        "18.0": {"installed": True, "python": "3.12.16"},
                        "17.0": {"installed": False, "python": "3.10.18"},
                    }
                }
            ),
        )
        actif = t("(active)")
        self.assertEqual(
            todo_etat.lignes_versions(self.racine)[1:],
            [
                f"Odoo 16.0 · Python 3.10.14  {actif}",
                "Odoo 18.0 · Python 3.12.16",
                "Odoo 9.0 · Python 2.7.18",
            ],
        )

    def test_without_state_the_repo_list_and_catalogue_answer(self):
        self.ecrire(".odoo-version", "18.0\n")
        self.ecrire(todo_etat.VERSIONS_INSTALLEES, "odoo18.0\nodoo17.0\n")
        self.ecrire(
            todo_etat.CATALOGUE,
            json.dumps(
                {
                    "odoo17.0_python3.10.18": {
                        "odoo_version": "17.0",
                        "python_version": "3.10.18",
                    },
                    "odoo18.0_python3.12.16": {
                        "odoo_version": "18.0",
                        "python_version": "3.12.16",
                    },
                }
            ),
        )
        self.assertEqual(
            todo_etat.lignes_versions(self.racine)[1:],
            [
                f"Odoo 18.0 · Python 3.12.16  {t('(active)')}",
                "Odoo 17.0 · Python 3.10.18",
            ],
        )

    def test_the_tooling_python_joins_the_erplibre_line(self):
        self.ecrire(todo_etat.PYTHON_OUTILLAGE, "3.15.2\n")
        self.ecrire(".odoo-version", "18.0\n")
        self.assertEqual(
            todo_etat.lignes_versions(self.racine),
            ["ERPLibre 9.9.1 · Python 3.15.2", "Odoo 18.0"],
        )

    def test_an_unreadable_state_is_ignored(self):
        self.ecrire(".odoo-version", "18.0\n")
        self.ecrire(todo_etat.ETAT_ERPLIBRE, "{pas du json")
        self.assertEqual(
            todo_etat.lignes_versions(self.racine),
            ["ERPLibre 9.9.1", "Odoo 18.0"],
        )

    def test_a_failing_check_never_breaks_the_report(self):
        with mock.patch.object(
            todo_etat, "lignes_versions", side_effect=RuntimeError
        ):
            lignes = todo_etat.bilan(self.racine)
        self.assertEqual(len(lignes), 1)
        self.assertTrue(lignes[0].startswith(todo_etat.ALERTE))


if __name__ == "__main__":
    unittest.main()
