#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mise à jour d'un checkout installé : le repérage des clones faits à la
main à un chemin des manifestes, leur déplacement, et la resynchronisation
dans le mode du checkout.

Les dépôts sont de vrais dépôts git jetables. Un clone « géré » imite celui
de git-repo : son « .git » est un lien vers `.repo/projects/<chemin>.git`.
Ni repo ni make ne sont lancés : la reconfiguration est remplacée.
"""

import ast
import builtins
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))

from script.todo import install_update_menu as maj  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS, t  # noqa: E402

ENV_GIT = {
    "GIT_AUTHOR_NAME": "Essai",
    "GIT_AUTHOR_EMAIL": "essai@exemple.invalid",
    "GIT_COMMITTER_NAME": "Essai",
    "GIT_COMMITTER_EMAIL": "essai@exemple.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
MAINTENANT = datetime(2026, 11, 15, 14, 30, 0)
MANUEL = "odoo18.0/addons/manuel"
GERE = "odoo18.0/addons/gere"
# Trié après MANUEL : sa reprise suit celle de MANUEL.
SUIVANT = "odoo18.0/addons/suivant"


def git(dossier, *args):
    return subprocess.run(
        ["git", "-C", dossier, *args],
        env={**os.environ, **ENV_GIT},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def ecrire(racine, chemin, texte):
    complet = os.path.join(racine, chemin)
    os.makedirs(os.path.dirname(complet), exist_ok=True)
    with open(complet, "w", encoding="utf-8") as fh:
        fh.write(texte)


def manifeste(*chemins, revision="18.0"):
    projets = "".join(
        f'  <project name="{os.path.basename(c)}.git" path="{c}"'
        f' remote="R" revision="{revision}"/>\n'
        for c in chemins
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n'
        '  <remote name="R" fetch="https://exemple.invalid/"/>\n'
        f"{projets}</manifest>\n"
    )


class Checkout:
    """Un checkout jetable : la racine, et de quoi y poser des clones."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.racine = tmp.name
        self.env = mock.patch.dict(os.environ, ENV_GIT)
        self.env.start()
        test.addCleanup(self.env.stop)

    def chemin(self, relatif):
        return os.path.join(self.racine, relatif)

    def clone_manuel(self, relatif, branches=("travail",)):
        """`git init` à `relatif` : un « .git/ » ordinaire, un commit, et
        les `branches` locales."""
        dossier = self.chemin(relatif)
        os.makedirs(dossier)
        git(dossier, "init", "-q", "-b", "18.0")
        ecrire(dossier, "un.txt", "un")
        git(dossier, "add", ".")
        git(dossier, "commit", "-q", "-m", "un")
        for branche in branches:
            git(dossier, "branch", branche)
        return dossier

    def clone_gere(self, relatif):
        """Un clone dont le « .git » pointe dans .repo/projects, comme
        celui de git-repo, HEAD détaché."""
        dossier = self.chemin(relatif)
        os.makedirs(dossier)
        git(dossier, "init", "-q", "-b", "18.0")
        ecrire(dossier, "amont.txt", "amont")
        git(dossier, "add", ".")
        git(dossier, "commit", "-q", "-m", "amont")
        git(dossier, "checkout", "-q", "--detach")
        git(dossier, "branch", "-q", "-D", "18.0")
        projet = self.chemin(f".repo/projects/{relatif}.git")
        os.makedirs(os.path.dirname(projet))
        os.rename(os.path.join(dossier, ".git"), projet)
        os.symlink(
            os.path.relpath(projet, dossier), os.path.join(dossier, ".git")
        )
        return dossier


class TestReperage(unittest.TestCase):
    def setUp(self):
        self.co = Checkout(self)

    def test_a_link_into_repo_projects_is_managed(self):
        self.co.clone_gere(GERE)
        self.co.clone_manuel(MANUEL)
        self.assertTrue(maj.clone_gere(self.co.racine, GERE))
        self.assertFalse(maj.clone_gere(self.co.racine, MANUEL))

    def test_only_hand_made_clones_are_listed(self):
        self.co.clone_gere(GERE)
        self.co.clone_manuel(MANUEL)
        fichier = "odoo18.0/addons/gitfile"
        ecrire(self.co.racine, f"{fichier}/.git", "gitdir: ailleurs\n")
        os.makedirs(self.co.chemin("odoo18.0/addons/vide"))
        chemins = {GERE, MANUEL, fichier, "odoo18.0/addons/vide", "absent"}
        self.assertEqual(
            maj.clones_manuels(self.co.racine, chemins), [fichier, MANUEL]
        )

    def test_a_link_elsewhere_is_not_managed(self):
        ailleurs = self.co.clone_manuel("ailleurs")
        os.makedirs(self.co.chemin(MANUEL))
        os.symlink(
            os.path.join(ailleurs, ".git"),
            self.co.chemin(f"{MANUEL}/.git"),
        )
        self.assertEqual(
            maj.clones_manuels(self.co.racine, {MANUEL}), [MANUEL]
        )

    def test_declared_paths_read_the_local_manifest_and_the_sources(self):
        ecrire(
            self.co.racine,
            ".repo/local_manifests/erplibre_manifest.xml",
            manifeste(GERE),
        )
        ecrire(self.co.racine, "private/m.xml", manifeste(MANUEL))
        ecrire(self.co.racine, "casse.xml", "<manifest><project")
        chemins = maj.chemins_declares(
            self.co.racine,
            sources=["private/m.xml", "casse.xml", "absent.xml"],
        )
        self.assertEqual(chemins, {GERE, MANUEL})

    def test_the_destination_sits_beside_with_a_date(self):
        self.assertEqual(
            maj.destination(MANUEL, MAINTENANT),
            f"{MANUEL}.avant_repo_20261115_143000",
        )

    def test_state_of_a_clone(self):
        dossier = self.co.clone_manuel(MANUEL, branches=("a", "b"))
        ecrire(dossier, "un.txt", "modifié")
        etat = maj.etat_clone(dossier)
        self.assertEqual(etat["modifies"], 1)
        self.assertEqual(etat["stash"], 0)
        # Aucun remote : le commit n'est sur aucun.
        self.assertEqual(etat["non_pousses"], 1)
        self.assertEqual(etat["branches"], ["18.0", "a", "b"])

    def test_state_of_what_is_not_a_clone(self):
        os.makedirs(self.co.chemin("vide"))
        etat = maj.etat_clone(self.co.chemin("vide"))
        self.assertEqual(
            etat,
            {
                "modifies": None,
                "stash": None,
                "non_pousses": None,
                "branches": None,
            },
        )


class TestResynchronisation(unittest.TestCase):
    """execute_update_repos, la reconfiguration remplacée."""

    def setUp(self):
        self.co = Checkout(self)
        self.lances = []
        ecrire(
            self.co.racine,
            ".repo/local_manifests/erplibre_manifest.xml",
            manifeste(MANUEL, revision="a" * 40),
        )

    def jouer(self, reponses, cloner=True, status=0, declares=(MANUEL,)):
        """Lance execute_update_repos ; rend (questions, code). La
        reconfiguration, remplacée, note son argument et, avec `cloner`,
        pose à MANUEL le clone que git-repo y mettrait. Une réponse
        `EOFError` est un Ctrl+D à cette question."""
        todo = TODO.__new__(TODO)
        questions = []
        suite = iter(reponses)

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                reponse = next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None
            if reponse is EOFError:
                raise EOFError
            return reponse

        def reconfigurer(freeze=False):
            self.lances.append(freeze)
            if cloner and not status:
                self.co.clone_gere(MANUEL)
            return status

        todo._git_repo_reconfigurer = reconfigurer
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(
                maj, "chemins_declares", lambda racine: set(declares)
            ),
            mock.patch.object(maj, "gel_des_sources", lambda r: (1, 1)),
            contextlib.redirect_stdout(io.StringIO()) as sortie,
        ):
            code = todo.execute_update_repos(
                racine=self.co.racine, maintenant=MAINTENANT
            )
        self.sortie = sortie.getvalue()
        return questions, code

    @property
    def ancien(self):
        return self.co.chemin(maj.destination(MANUEL, MAINTENANT))

    def branches(self, relatif):
        return git(
            self.co.chemin(relatif),
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
        ).split()

    def test_moved_aside_then_branches_copied_and_old_kept(self):
        self.co.clone_manuel(MANUEL)
        questions, code = self.jouer(["o", "", "n"])
        self.assertEqual(code, 0)
        self.assertEqual(len(questions), 3)
        # Le checkout gelé le reste : la reconfiguration reçoit freeze.
        self.assertEqual(self.lances, [True])
        self.assertTrue(os.path.isdir(os.path.join(self.ancien, ".git")))
        self.assertTrue(maj.clone_gere(self.co.racine, MANUEL))
        self.assertEqual(self.branches(MANUEL), ["18.0", "travail"])

    def test_the_old_clone_is_deleted_once_its_branches_are_copied(self):
        self.co.clone_manuel(MANUEL)
        self.jouer(["o", "", "o"])
        self.assertFalse(os.path.exists(self.ancien))

    def test_declining_the_copy_keeps_the_old_clone_without_asking(self):
        """Ses commits ne sont nulle part ailleurs : la suppression n'est
        pas offerte."""
        self.co.clone_manuel(MANUEL)
        questions, _ = self.jouer(["o", "n"])
        self.assertEqual(len(questions), 2)
        self.assertTrue(os.path.isdir(self.ancien))
        self.assertIn(
            maj.t("Old clone kept, deleting it would lose:"), self.sortie
        )

    def test_modified_files_keep_the_old_clone(self):
        dossier = self.co.clone_manuel(MANUEL)
        ecrire(dossier, "un.txt", "modifié")
        questions, _ = self.jouer(["o", ""])
        self.assertEqual(len(questions), 2)
        self.assertTrue(os.path.isdir(self.ancien))

    def test_a_branch_checkout_is_resynchronized_on_its_branches(self):
        ecrire(
            self.co.racine,
            ".repo/local_manifests/erplibre_manifest.xml",
            manifeste(MANUEL),
        )
        self.co.clone_manuel(MANUEL, branches=())
        self.jouer(["o", "n"])
        self.assertEqual(self.lances, [False])

    def test_a_frozen_checkout_without_freeze_moves_nothing(self):
        self.co.clone_manuel(MANUEL)
        with mock.patch.object(maj, "gel_des_sources", lambda r: (0, 5)):
            todo = TODO.__new__(TODO)
            todo._git_repo_reconfigurer = mock.Mock()
            with (
                mock.patch.object(
                    builtins, "input", side_effect=AssertionError("question")
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = todo.execute_update_repos(
                    racine=self.co.racine, maintenant=MAINTENANT
                )
        self.assertIsNone(code)
        todo._git_repo_reconfigurer.assert_not_called()
        self.assertTrue(os.path.isdir(self.co.chemin(f"{MANUEL}/.git")))

    def test_kept_clone_and_no_sync_runs_nothing(self):
        self.co.clone_manuel(MANUEL)
        questions, code = self.jouer(["n", "n"])
        self.assertIsNone(code)
        self.assertEqual(len(questions), 2)
        self.assertEqual(self.lances, [])
        self.assertTrue(os.path.isdir(self.co.chemin(f"{MANUEL}/.git")))

    def test_giving_up_after_keeping_one_moves_none(self):
        autre = "odoo18.0/addons/autre"
        self.co.clone_manuel(MANUEL)
        self.co.clone_manuel(autre)
        questions, code = self.jouer(["n", "o", "n"], declares=(MANUEL, autre))
        self.assertIsNone(code)
        self.assertEqual(len(questions), 3)
        self.assertTrue(os.path.isdir(self.co.chemin(f"{autre}/.git")))
        self.assertFalse(
            os.path.exists(self.co.chemin(maj.destination(autre, MAINTENANT)))
        )

    def test_kept_clone_can_still_sync_the_others(self):
        self.co.clone_manuel(MANUEL)
        questions, code = self.jouer(["n", "o"], cloner=False)
        self.assertEqual(code, 0)
        self.assertEqual(self.lances, [True])
        self.assertFalse(os.path.exists(self.ancien))

    def test_a_failed_sync_puts_the_clone_back(self):
        self.co.clone_manuel(MANUEL)
        questions, code = self.jouer(["o"], status=3)
        self.assertEqual(code, 3)
        self.assertEqual(len(questions), 1)
        self.assertFalse(os.path.exists(self.ancien))
        self.assertTrue(os.path.isdir(self.co.chemin(f"{MANUEL}/.git")))

    def test_a_path_repo_sync_did_not_clone_gets_its_clone_back(self):
        self.co.clone_manuel(MANUEL)
        questions, code = self.jouer(["o"], cloner=False)
        self.assertEqual(code, 0)
        self.assertEqual(len(questions), 1)
        self.assertFalse(os.path.exists(self.ancien))
        self.assertEqual(self.branches(MANUEL), ["18.0", "travail"])

    def test_no_hand_made_clone_asks_nothing(self):
        questions, code = self.jouer([], cloner=False)
        self.assertEqual(questions, [])
        self.assertEqual(self.lances, [True])

    # Ctrl+D : avant la synchronisation, il renonce, rien n'est déplacé ni
    # synchronisé ; après, il vaut non pour le clone qu'il vise, et chaque
    # clone déplacé suivant est repris quand même.

    def deux_clones(self):
        self.co.clone_manuel(MANUEL)
        self.co.clone_manuel(SUIVANT)
        return (MANUEL, SUIVANT)

    def assert_suivant_remis(self):
        self.assertTrue(os.path.isdir(self.co.chemin(f"{SUIVANT}/.git")))
        self.assertFalse(
            os.path.exists(
                self.co.chemin(maj.destination(SUIVANT, MAINTENANT))
            )
        )
        self.assertIn(
            maj.t("Put back, repo sync did not clone it:"), self.sortie
        )

    def assert_manuel_garde(self):
        """La ligne qui dit où l'ancien clone de MANUEL est gardé commence
        sa propre ligne : la question restée sans saut de ligne est
        refermée avant elle."""
        ligne = (
            f"⚠️  {MANUEL} : {maj.t('Kept as')} "
            f"{maj.destination(MANUEL, MAINTENANT)}\n"
        )
        self.assertIn(f"\n\n{ligne}", self.sortie)

    def test_at_the_move_question_nothing_moves_nor_syncs(self):
        declares = self.deux_clones()
        questions, code = self.jouer([EOFError], declares=declares)
        self.assertIsNone(code)
        self.assertEqual(len(questions), 1)
        self.assertEqual(self.lances, [])
        for chemin in declares:
            self.assertTrue(os.path.isdir(self.co.chemin(f"{chemin}/.git")))
            self.assertFalse(
                os.path.exists(
                    self.co.chemin(maj.destination(chemin, MAINTENANT))
                )
            )

    def test_at_the_second_move_question_the_first_does_not_move(self):
        """Le « oui » au premier clone n'est qu'un plan : Ctrl+D au
        second l'abandonne avant tout déplacement."""
        declares = self.deux_clones()
        questions, code = self.jouer(["o", EOFError], declares=declares)
        self.assertIsNone(code)
        self.assertEqual(len(questions), 2)
        self.assertEqual(self.lances, [])
        for chemin in declares:
            self.assertTrue(os.path.isdir(self.co.chemin(f"{chemin}/.git")))
            self.assertFalse(
                os.path.exists(
                    self.co.chemin(maj.destination(chemin, MAINTENANT))
                )
            )

    def test_at_synchronize_anyway_nothing_moves_nor_syncs(self):
        declares = self.deux_clones()
        questions, code = self.jouer(["o", "n", EOFError], declares=declares)
        self.assertIsNone(code)
        self.assertEqual(len(questions), 3)
        self.assertEqual(self.lances, [])
        self.assertFalse(os.path.exists(self.ancien))
        self.assertTrue(os.path.isdir(self.co.chemin(f"{MANUEL}/.git")))

    def test_at_the_copy_the_next_clone_is_still_put_back(self):
        declares = self.deux_clones()
        questions, code = self.jouer(["o", "o", EOFError], declares=declares)
        self.assertEqual(code, 0)
        # Ctrl+D à la copie rend la main : ni copie ni question de
        # suppression, l'ancien clone reste.
        self.assertEqual(len(questions), 3)
        self.assertTrue(os.path.isdir(os.path.join(self.ancien, ".git")))
        self.assert_manuel_garde()
        self.assertTrue(maj.clone_gere(self.co.racine, MANUEL))
        self.assertEqual(self.branches(MANUEL), [])
        self.assert_suivant_remis()

    def test_at_the_deletion_the_old_clone_stays_and_the_next_is_put_back(
        self,
    ):
        declares = self.deux_clones()
        questions, code = self.jouer(
            ["o", "o", "", EOFError], declares=declares
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(questions), 4)
        self.assertEqual(self.branches(MANUEL), ["18.0", "travail"])
        self.assertTrue(os.path.isdir(os.path.join(self.ancien, ".git")))
        self.assert_manuel_garde()
        self.assert_suivant_remis()


class TestPertes(unittest.TestCase):
    """Ce que supprimer l'ancien clone perdrait."""

    def setUp(self):
        self.co = Checkout(self)
        self.vieux = self.co.clone_manuel("vieux")
        self.nouveau = self.co.clone_gere("nouveau")

    def test_nothing_lost_once_every_commit_is_in_the_new_clone(self):
        git(
            self.nouveau,
            "fetch",
            "-q",
            self.vieux,
            "refs/heads/*:refs/heads/*",
        )
        self.assertEqual(
            maj.pertes_a_la_suppression(self.vieux, self.nouveau), []
        )

    def test_commits_of_a_detached_head_are_counted_and_named(self):
        git(
            self.nouveau,
            "fetch",
            "-q",
            self.vieux,
            "refs/heads/*:refs/heads/*",
        )
        git(self.vieux, "checkout", "-q", "--detach")
        ecrire(self.vieux, "deux.txt", "deux")
        git(self.vieux, "add", ".")
        git(self.vieux, "commit", "-q", "-m", "deux")
        self.assertEqual(maj.etat_clone(self.vieux)["non_pousses"], 2)
        (perte,) = maj.pertes_a_la_suppression(self.vieux, self.nouveau)
        self.assertIn("HEAD", perte)
        self.assertNotIn("travail", perte)

    def test_stash_and_modified_files_are_lost(self):
        git(
            self.nouveau,
            "fetch",
            "-q",
            self.vieux,
            "refs/heads/*:refs/heads/*",
        )
        ecrire(self.vieux, "un.txt", "modifié")
        git(self.vieux, "stash", "-q")
        ecrire(self.vieux, "un.txt", "encore")
        pertes = maj.pertes_a_la_suppression(self.vieux, self.nouveau)
        self.assertEqual(len(pertes), 2)


class TestLeMenu(unittest.TestCase):
    """Install › Update, déclaré au registre (INSTALL_UPDATE) : chaque
    numéro lance l'outil qu'il nomme, puis le menu reprend ; un numéro
    inconnu ne lance rien, et [0] rend False."""

    OUTILS = (
        "execute_python_versions",
        "execute_poetry_drift",
        "execute_update_repos",
        "_git_repo_tirer",
    )

    def jouer(self, reponses):
        todo = TODO.__new__(TODO)
        lances = []
        suite = iter(reponses)
        with contextlib.ExitStack() as pile:
            for nom in self.OUTILS:
                pile.enter_context(
                    mock.patch.object(
                        TODO, nom, lambda _self, nom=nom: lances.append(nom)
                    )
                )
            pile.enter_context(
                mock.patch.object(
                    TODO, "fill_help_info", lambda _self, _c, **_k: "menu"
                )
            )
            pile.enter_context(
                mock.patch("click.prompt", lambda *_a, **_k: next(suite))
            )
            ecran = pile.enter_context(
                contextlib.redirect_stdout(io.StringIO())
            )
            rendu = todo.prompt_install_update()
        return rendu, lances, ecran.getvalue()

    def test_each_number_runs_its_tool_then_zero_goes_back(self):
        rendu, lances, ecran = self.jouer(["4", "3", "2", "1", "0"])
        self.assertIs(rendu, False)
        self.assertEqual(lances, list(reversed(self.OUTILS)))
        self.assertIn(f"🤖 {t('Update what is installed!')}", ecran)

    def test_an_unknown_number_runs_nothing(self):
        rendu, lances, ecran = self.jouer(["5", "0"])
        self.assertIs(rendu, False)
        self.assertEqual(lances, [])
        self.assertIn(t("Command not found !"), ecran)


class TestTraductions(unittest.TestCase):
    """Chaque libellé du module a sa traduction en français et en
    anglais : une clé absente s'afficherait telle quelle."""

    def test_every_key_is_translated(self):
        source = (
            RACINE_DEPOT / "script/todo/install_update_menu.py"
        ).read_text()
        cles = {
            n.args[0].value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        }
        cles |= {"modified files", "stash entries", "commits on no remote"}
        self.assertEqual(sorted(cles - set(TRANSLATIONS)), [])
        for cle in cles:
            self.assertEqual(set(TRANSLATIONS[cle]), {"fr", "en"}, cle)


if __name__ == "__main__":
    unittest.main()
