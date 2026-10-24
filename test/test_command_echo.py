#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'affichage des commandes des outils git avant leur lancement.

Ce que ces tests gardent :

- la ligne affichée est la commande à recopier depuis la racine ERPLibre :
  dossier relatif, en « git -C » pour git, sans les secrets d'une URL ;
- l'affichage suit ERPLIBRE_GIT_ECHO, sinon le terminal ; il va sur la
  sortie d'ERREUR, jamais sur la sortie standard ;
- chaque outil du menu git passe par lui : repo_state, repo_upgrade, les
  scripts de gel ;
- même forcé, il laisse intact le JSON que repo_state.py écrit sur sa sortie
  standard, celui que erplibre_info lit par un tuyau.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.git import command_echo  # noqa: E402


class _Tty(io.StringIO):
    def isatty(self):
        return True


class TestRendu(unittest.TestCase):
    def test_git_sous_la_racine_en_relatif(self):
        dossier = RACINE / "odoo18.0" / "addons" / "OCA_web"
        self.assertEqual(
            command_echo.render(["git", "fetch", "origin", "18.0"], dossier),
            "git -C odoo18.0/addons/OCA_web fetch origin 18.0",
        )

    def test_un_c_deja_present_est_rendu_relatif(self):
        dossier = str(RACINE / "odoo18.0" / "odoo")
        self.assertEqual(
            command_echo.render(["git", "-C", dossier, "status"]),
            "git -C odoo18.0/odoo status",
        )

    def test_la_racine_elle_meme(self):
        self.assertEqual(
            command_echo.render(["git", "pull"], RACINE), "git -C . pull"
        )

    def test_hors_de_la_racine_reste_absolu(self):
        self.assertEqual(
            command_echo.render(["git", "status"], "/var/fictif"),
            "git -C /var/fictif status",
        )

    def test_une_autre_commande_porte_son_dossier(self):
        self.assertEqual(
            command_echo.render(["repo", "sync", "-c"], RACINE / "odoo18.0"),
            "(cd odoo18.0) repo sync -c",
        )

    def test_les_secrets_d_une_url_disparaissent(self):
        ligne = command_echo.render(
            [
                "git",
                "ls-remote",
                "https://utilisateur:jeton-fictif@exemple.invalid/a.git",
            ]
        )
        self.assertNotIn("jeton-fictif", ligne)
        self.assertNotIn("utilisateur", ligne)
        self.assertIn("https://exemple.invalid/a.git", ligne)

    def test_les_arguments_a_espaces_sont_cites(self):
        self.assertEqual(
            command_echo.render(["git", "commit", "-m", "deux mots"]),
            "git commit -m 'deux mots'",
        )


class TestActivation(unittest.TestCase):
    def _active(self, valeur, flux):
        env = {} if valeur is None else {command_echo.VARIABLE: valeur}
        with patch.dict(os.environ, env):
            if valeur is None:
                os.environ.pop(command_echo.VARIABLE, None)
            return command_echo.active(flux)

    def test_le_terminal_decide_par_defaut(self):
        self.assertTrue(self._active(None, _Tty()))
        self.assertFalse(self._active(None, io.StringIO()))

    def test_la_variable_l_emporte(self):
        self.assertTrue(self._active("1", io.StringIO()))
        self.assertFalse(self._active("0", _Tty()))

    def test_show_ecrit_seulement_quand_actif(self):
        flux = io.StringIO()
        with patch.dict(os.environ, {command_echo.VARIABLE: "0"}):
            command_echo.show(["git", "status"], flux=flux)
        self.assertEqual(flux.getvalue(), "")
        with patch.dict(os.environ, {command_echo.VARIABLE: "1"}):
            command_echo.show(["git", "status"], flux=flux)
        self.assertEqual(flux.getvalue(), "$ git status\n")


class TestOutils(unittest.TestCase):
    """Chaque point de lancement des outils git affiche sa commande."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.depot = self.tmp.name
        subprocess.run(
            ["git", "init", "-q", self.depot], check=True, capture_output=True
        )
        env = patch.dict(os.environ, {command_echo.VARIABLE: "1"})
        env.start()
        self.addCleanup(env.stop)

    def _capture(self, appel):
        err = io.StringIO()
        with patch.object(sys, "stderr", err):
            appel()
        return err.getvalue()

    def test_repo_state(self):
        from script.git import repo_state

        sortie = self._capture(
            lambda: repo_state.git(["rev-parse", "--git-dir"], self.depot)
        )
        self.assertRegex(sortie, r"^\$ git -C \S+ .*rev-parse --git-dir\n$")

    def test_repo_upgrade(self):
        from script.git import repo_upgrade

        sortie = self._capture(
            lambda: repo_upgrade.git(["status", "--short"], self.depot)
        )
        self.assertIn("$ git -C ", sortie)
        self.assertIn("status --short", sortie)

    def test_scripts_de_gel(self):
        from script.git import git_freeze_diff, git_freeze_manifest

        for module in (git_freeze_manifest, git_freeze_diff):
            with self.subTest(module=module.__name__):
                sortie = self._capture(
                    lambda: module._git(self.depot, "rev-parse", "--git-dir")
                )
                self.assertIn("rev-parse --git-dir", sortie)


class TestJsonIntact(unittest.TestCase):
    def test_repo_state_garde_son_json_sur_la_sortie_standard(self):
        """Affichage forcé : la sortie standard reste un JSON lisible."""
        env = dict(os.environ, **{command_echo.VARIABLE: "1"})
        res = subprocess.run(
            [
                sys.executable,
                str(RACINE / "script" / "git" / "repo_state.py"),
                "snapshot",
            ],
            cwd=RACINE,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        self.assertEqual(res.returncode, 0, res.stderr[-2000:])
        json.loads(res.stdout)
        self.assertIn("$ git ", res.stderr)


if __name__ == "__main__":
    unittest.main()
