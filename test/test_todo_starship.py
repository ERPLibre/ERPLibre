#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Installer starship : deux étapes qui échouent séparément.

Poser le binaire ne change pas le prompt ; c'est la ligne d'initialisation
dans le fichier du shell qui le fait. Un menu qui confond les deux annonce un
succès devant un prompt inchangé, ou réécrit la ligne à chaque passage.

Le fichier à modifier ne se demande que devant un vrai choix : plusieurs
fichiers de configuration présents. Aucun, ou un seul, ne laisse rien à
trancher — une question posée là n'attend qu'une frappe pour rien.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from script.todo.todo import TODO

LIGNE_BASH = 'eval "$(starship init bash)"'
LIGNE_ZSH = 'eval "$(starship init zsh)"'


def refuse_input(*args, **kwargs):
    raise AssertionError("aucune question ne devait être posée")


class TestShellName(unittest.TestCase):
    """Le shell se lit dans $SHELL, dont seul le nom de base compte."""

    def test_basename_of_shell(self):
        with patch.dict(os.environ, {"SHELL": "/usr/bin/zsh"}):
            self.assertEqual(TODO._shell_name(), "zsh")

    def test_empty_when_unset(self):
        with patch.dict(os.environ, {"SHELL": ""}):
            self.assertEqual(TODO._shell_name(), "")


class ShellFixture(unittest.TestCase):
    """Un faux HOME où l'on pose les fichiers de configuration voulus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        racine = Path(self.tmp.name)
        self.fichiers = {
            "bash": racine / "bashrc",
            "zsh": racine / "zshrc",
            "fish": racine / "fish" / "config.fish",
        }
        table = {
            "bash": (str(self.fichiers["bash"]), LIGNE_BASH),
            "zsh": (str(self.fichiers["zsh"]), LIGNE_ZSH),
            "fish": (
                str(self.fichiers["fish"]),
                "starship init fish | source",
            ),
        }
        patcher = patch.dict(TODO._STARSHIP_SHELLS, table, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.todo = TODO()

    def cree(self, *shells, contenu=""):
        for shell in shells:
            chemin = self.fichiers[shell]
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(contenu, encoding="utf-8")


class TestStarshipTarget(ShellFixture):
    """Quel fichier, et quand la question se pose."""

    def choisit(self, shell_env="/bin/bash", reponse=None):
        entree = refuse_input if reponse is None else (lambda *a: reponse)
        with patch.dict(os.environ, {"SHELL": shell_env}), patch(
            "builtins.input", entree
        ), redirect_stdout(io.StringIO()):
            return self.todo._shell_starship_target()

    def test_no_file_means_bash_without_asking(self):
        self.assertEqual(self.choisit(), "bash")

    def test_a_single_file_is_taken_without_asking(self):
        self.cree("zsh")
        self.assertEqual(self.choisit(), "zsh")

    def test_a_single_file_wins_over_the_current_shell(self):
        """Le fichier présent l'emporte : $SHELL n'en a pas, lui."""
        self.cree("fish")
        self.assertEqual(self.choisit(shell_env="/bin/bash"), "fish")

    def test_several_files_ask_and_default_to_the_current_shell(self):
        self.cree("bash", "zsh")
        self.assertEqual(
            self.choisit(shell_env="/usr/bin/zsh", reponse=""), "zsh"
        )

    def test_several_files_answered_by_number(self):
        self.cree("bash", "zsh")
        self.assertEqual(self.choisit(reponse="2"), "zsh")

    def test_several_files_answered_by_name(self):
        self.cree("bash", "zsh")
        self.assertEqual(self.choisit(reponse="zsh"), "zsh")

    def test_a_nonsense_answer_falls_back_on_the_default(self):
        self.cree("bash", "zsh")
        self.assertEqual(self.choisit(reponse="42"), "bash")


class TestHookStarship(ShellFixture):
    """L'écriture de la ligne, qui ne demande rien."""

    def hook(self, shell_env="/bin/bash"):
        out = io.StringIO()
        with patch.dict(os.environ, {"SHELL": shell_env}), patch(
            "builtins.input", refuse_input
        ), redirect_stdout(out):
            self.todo._shell_hook_starship()
        return out.getvalue()

    def test_it_appends_the_line(self):
        self.cree("bash", contenu="export EDITOR=vim\n")
        self.hook()
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            f"export EDITOR=vim\n{LIGNE_BASH}\n",
        )

    def test_a_file_without_a_final_newline_keeps_its_last_command(self):
        self.cree("bash", contenu="export EDITOR=vim")
        self.hook()
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            f"export EDITOR=vim\n{LIGNE_BASH}\n",
        )

    def test_it_writes_only_once(self):
        self.cree("bash", contenu=f"{LIGNE_BASH}\n")
        sortie = self.hook()
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            f"{LIGNE_BASH}\n",
        )
        self.assertIn("✅", sortie)

    def test_no_file_at_all_creates_the_bash_one(self):
        self.hook()
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            f"{LIGNE_BASH}\n",
        )

    def test_a_missing_parent_directory_is_created(self):
        """config.fish vit sous ~/.config/fish, que rien ne garantit."""
        self.todo._STARSHIP_SHELLS["bash"] = (
            str(self.fichiers["fish"]),
            LIGNE_BASH,
        )
        self.hook()
        self.assertEqual(
            self.fichiers["fish"].read_text(encoding="utf-8"),
            f"{LIGNE_BASH}\n",
        )


class TestInstallStarship(unittest.TestCase):
    """L'enchaînement des deux étapes, et ce qui l'arrête."""

    def test_an_installed_binary_goes_straight_to_the_shell(self):
        todo = TODO()
        todo.execute = MagicMock()
        with patch(
            "script.todo.todo.shutil.which", return_value="/usr/bin/starship"
        ), patch.object(TODO, "_shell_hook_starship") as hook, patch.object(
            TODO, "_shell_install_starship_binary"
        ) as poser:
            todo._shell_install_starship()
        poser.assert_not_called()
        hook.assert_called_once()

    def test_a_missing_binary_leaves_the_shell_alone(self):
        todo = TODO()
        todo.execute = MagicMock()
        out = io.StringIO()
        with patch(
            "script.todo.todo.shutil.which", return_value=None
        ), patch.object(TODO, "_shell_hook_starship") as hook, patch.object(
            TODO, "_shell_install_starship_binary"
        ), redirect_stdout(
            out
        ):
            todo._shell_install_starship()
        hook.assert_not_called()
        self.assertIn("❌", out.getvalue())

    def test_a_refused_package_does_not_chain_to_upstream(self):
        """Un refus est une décision : il n'appelle pas une seconde offre."""
        todo = TODO()
        todo.execute = MagicMock()
        appels = []
        with patch(
            "script.todo.todo.todo_install.install_command",
            return_value=["sudo", "pacman", "-S", "starship"],
        ), patch(
            "script.todo.todo.todo_install.ask_and_install",
            side_effect=lambda *a, **k: appels.append(a[1]) or None,
        ):
            todo._shell_install_starship_binary()
        self.assertEqual(len(appels), 1)

    def test_no_package_falls_back_upstream(self):
        todo = TODO()
        todo.execute = MagicMock()
        appels = []
        with patch(
            "script.todo.todo.todo_install.install_command", return_value=None
        ), patch(
            "script.todo.todo.todo_install.ask_and_install",
            side_effect=lambda *a, **k: appels.append(a[1]) or 0,
        ), redirect_stdout(
            io.StringIO()
        ):
            todo._shell_install_starship_binary()
        self.assertEqual(appels, [TODO._STARSHIP_UPSTREAM])


if __name__ == "__main__":
    unittest.main()
