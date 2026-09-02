#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les outils de shell du menu Git et Shell : starship, Claude Code, opencode.

Trois installations, un même piège : poser le binaire ne suffit pas. Starship
ne change rien au prompt sans sa ligne d'initialisation ; les deux assistants
posent leur binaire dans un répertoire du HOME que le PATH ne porte pas
toujours. La seconde étape est celle qu'on oublie, et son absence ne se voit
qu'au prochain shell.

Le fichier de configuration à modifier ne se demande que devant un vrai
choix : plusieurs fichiers présents. Aucun, ou un seul, ne laisse rien à
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
LIGNE_FISH = "starship init fish | source"


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
        self.racine = Path(self.tmp.name)
        self.fichiers = {
            "bash": self.racine / "bashrc",
            "zsh": self.racine / "zshrc",
            "fish": self.racine / "fish" / "config.fish",
        }
        patcher = patch.dict(
            TODO._SHELL_RC,
            {nom: str(p) for nom, p in self.fichiers.items()},
            clear=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.todo = TODO()

    def cree(self, *shells, contenu=""):
        for shell in shells:
            chemin = self.fichiers[shell]
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(contenu, encoding="utf-8")


class TestRcTarget(ShellFixture):
    """Quel fichier, et quand la question se pose."""

    def choisit(self, shell_env="/bin/bash", reponse=None):
        entree = refuse_input if reponse is None else (lambda *a: reponse)
        with patch.dict(os.environ, {"SHELL": shell_env}), patch(
            "builtins.input", entree
        ), redirect_stdout(io.StringIO()):
            return self.todo._shell_rc_target()

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


class TestRcAppend(ShellFixture):
    """L'écriture d'une ligne dans le fichier du shell, une seule fois."""

    def test_it_appends_and_returns_the_path(self):
        self.cree("bash", contenu="export EDITOR=vim\n")
        chemin = self.todo._shell_rc_append("bash", "LIGNE", "LIGNE")
        self.assertEqual(chemin, str(self.fichiers["bash"]))
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            "export EDITOR=vim\nLIGNE\n",
        )

    def test_a_present_marker_writes_nothing(self):
        self.cree("bash", contenu="déjà LIGNE ici\n")
        self.assertIsNone(self.todo._shell_rc_append("bash", "LIGNE", "LIGNE"))
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            "déjà LIGNE ici\n",
        )

    def test_a_marker_written_otherwise_still_counts(self):
        """Une variante à la main compte : c'est l'effet qui importe."""
        self.cree("bash", contenu='PATH="$HOME/.local/bin:$PATH"\n')
        self.assertIsNone(
            self.todo._shell_rc_append(
                "bash", "export PATH=...", "/.local/bin"
            )
        )

    def test_a_file_without_a_final_newline_keeps_its_last_command(self):
        self.cree("bash", contenu="export EDITOR=vim")
        self.todo._shell_rc_append("bash", "LIGNE", "LIGNE")
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            "export EDITOR=vim\nLIGNE\n",
        )

    def test_a_missing_parent_directory_is_created(self):
        """config.fish vit sous ~/.config/fish, que rien ne garantit."""
        self.todo._shell_rc_append("fish", "LIGNE", "LIGNE")
        self.assertEqual(
            self.fichiers["fish"].read_text(encoding="utf-8"), "LIGNE\n"
        )


class TestPathLine(unittest.TestCase):
    """La syntaxe du PATH n'est pas la même partout."""

    def test_posix_shells_export(self):
        todo = TODO()
        for shell in ("bash", "zsh"):
            self.assertEqual(
                todo._shell_path_line(shell, "~/.local/bin"),
                'export PATH="~/.local/bin:$PATH"',
            )

    def test_fish_has_its_own_builtin(self):
        self.assertEqual(
            TODO()._shell_path_line("fish", "~/.local/bin"),
            "fish_add_path ~/.local/bin",
        )


class TestHookStarship(ShellFixture):
    """L'écriture de la ligne d'initialisation, qui ne demande rien."""

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

    def test_each_shell_gets_its_own_line(self):
        self.cree("fish")
        self.hook()
        self.assertEqual(
            self.fichiers["fish"].read_text(encoding="utf-8"),
            f"{LIGNE_FISH}\n",
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


class TestUpstreamTools(ShellFixture):
    """Claude Code et opencode : l'installateur, puis le PATH."""

    def setUp(self):
        super().setUp()
        self.todo.execute = MagicMock()
        # Chaque outil pose son binaire dans un répertoire du faux HOME.
        self.repertoires = {
            "claude": self.racine / "local" / "bin",
            "opencode": self.racine / "opencode" / "bin",
        }
        patcher = patch.dict(
            TODO._UPSTREAM_TOOLS,
            {
                nom: (
                    TODO._UPSTREAM_TOOLS[nom][0],
                    str(chemin),
                )
                for nom, chemin in self.repertoires.items()
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def pose_le_binaire(self, outil):
        chemin = self.repertoires[outil]
        chemin.mkdir(parents=True, exist_ok=True)
        (chemin / outil).write_text("", encoding="utf-8")

    def installe(self, outil, status=0):
        self.todo.execute.exec_command_live.return_value = status
        out = io.StringIO()
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}), patch(
            "builtins.input", refuse_input
        ), redirect_stdout(out):
            self.todo._shell_install_upstream_tool(outil)
        return out.getvalue()

    def test_the_documented_installers_are_the_ones_run(self):
        self.assertEqual(
            TODO._UPSTREAM_TOOLS["claude"][0],
            "curl -fsSL https://claude.ai/install.sh | bash",
        )
        self.assertEqual(
            TODO._UPSTREAM_TOOLS["opencode"][0],
            "curl -fsSL https://opencode.ai/install | bash",
        )

    def test_a_failed_install_touches_no_shell_file(self):
        self.cree("bash", contenu="export EDITOR=vim\n")
        sortie = self.installe("claude", status=1)
        self.assertIn("❌", sortie)
        self.assertEqual(
            self.fichiers["bash"].read_text(encoding="utf-8"),
            "export EDITOR=vim\n",
        )

    def test_a_success_puts_the_directory_on_the_path(self):
        self.cree("bash")
        self.pose_le_binaire("claude")
        self.installe("claude")
        contenu = self.fichiers["bash"].read_text(encoding="utf-8")
        self.assertIn(str(self.repertoires["claude"]), contenu)
        self.assertIn("export PATH=", contenu)

    def test_each_tool_gets_its_own_directory(self):
        self.cree("bash")
        self.pose_le_binaire("opencode")
        self.installe("opencode")
        contenu = self.fichiers["bash"].read_text(encoding="utf-8")
        self.assertIn(str(self.repertoires["opencode"]), contenu)
        self.assertNotIn(str(self.repertoires["claude"]), contenu)

    def test_a_directory_already_on_the_path_is_not_added_twice(self):
        """L'installateur amont écrit souvent la ligne lui-même."""
        ligne = f'export PATH="{self.repertoires["opencode"]}:$PATH"\n'
        self.cree("bash", contenu=ligne)
        self.pose_le_binaire("opencode")
        self.installe("opencode")
        contenu = self.fichiers["bash"].read_text(encoding="utf-8")
        self.assertEqual(contenu.count(str(self.repertoires["opencode"])), 1)

    def test_a_binary_that_did_not_land_is_said(self):
        self.cree("bash")
        sortie = self.installe("claude")
        self.assertIn("⚠", sortie)

    def test_the_two_menu_entries_reach_the_shared_path(self):
        for methode, outil in (
            ("_shell_install_claude_code", "claude"),
            ("_shell_install_opencode", "opencode"),
        ):
            with patch.object(TODO, "_shell_install_upstream_tool") as partage:
                getattr(self.todo, methode)()
            partage.assert_called_once_with(outil)


if __name__ == "__main__":
    unittest.main()
