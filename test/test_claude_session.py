#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages Claude Code du dépôt et le message de son hook
SessionStart.

Les réglages s'écrivent dans un dossier jetable ; le message se compose sur
un dépôt git jetable, isolé de la config git du compte.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from script.todo import claude_reglages as c

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_spec = importlib.util.spec_from_file_location(
    "session_start",
    os.path.join(RACINE, "script", "claude", "session_start.py"),
)
session = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(session)

ENV_GIT = {
    "GIT_AUTHOR_NAME": "Essai",
    "GIT_AUTHOR_EMAIL": "essai@exemple.invalid",
    "GIT_COMMITTER_NAME": "Essai",
    "GIT_COMMITTER_EMAIL": "essai@exemple.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}

AUTRE_HOOK = {
    "matcher": "startup",
    "hooks": [{"type": "command", "command": "echo autre"}],
}


def t(texte):
    return texte


class TestReglages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = tmp.name

    def test_ultracode_toggles_without_touching_other_keys(self):
        depart = {"enabledPlugins": {"p": True}}
        actif = c.avec_ultracode(depart, True)
        self.assertTrue(c.ultracode_actif(actif))
        self.assertEqual(actif["enabledPlugins"], {"p": True})
        # Désactiver retire la clé, pour laisser décider le réglage du compte.
        self.assertEqual(c.avec_ultracode(actif, False), depart)
        self.assertNotIn("ultracode", depart)

    def test_the_hook_covers_startup_and_resume_and_installs_once(self):
        une_fois = c.avec_hook({}, True)
        self.assertTrue(c.hook_installe(une_fois))
        self.assertEqual(
            [e["matcher"] for e in une_fois["hooks"]["SessionStart"]],
            list(c.SOURCES_HOOK),
        )
        self.assertEqual(c.avec_hook(une_fois, True), une_fois)

    def test_another_session_hook_stays_and_removal_cleans_up(self):
        depart = {"hooks": {"SessionStart": [AUTRE_HOOK]}}
        pose = c.avec_hook(depart, True)
        self.assertIn(AUTRE_HOOK, pose["hooks"]["SessionStart"])
        self.assertEqual(c.avec_hook(pose, False), depart)
        self.assertEqual(c.avec_hook(c.avec_hook({}, True), False), {})

    def test_reading_and_writing_the_file(self):
        self.assertEqual(c.lire(self.racine), {})
        c.ecrire(self.racine, c.avec_ultracode({}, True))
        chemin = os.path.join(self.racine, c.FICHIER)
        with open(chemin) as fh:
            self.assertEqual(fh.read(), '{\n  "ultracode": true\n}\n')
        self.assertEqual(c.lire(self.racine), {"ultracode": True})

    def test_a_file_that_is_not_an_object_is_never_overwritten(self):
        os.makedirs(os.path.join(self.racine, ".claude"))
        with open(os.path.join(self.racine, c.FICHIER), "w") as fh:
            fh.write("[1, 2]")
        with self.assertRaises(ValueError):
            c.lire(self.racine)

    def test_the_repository_runs_the_session_message(self):
        """Le hook du dépôt vise un script qui existe."""
        reglages = c.lire(RACINE)
        self.assertTrue(c.hook_installe(reglages))
        self.assertTrue(
            os.path.isfile(
                os.path.join(RACINE, "script", "claude", "session_start.py")
            )
        )


class TestMessage(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, ENV_GIT)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = tmp.name

    def ecrire(self, chemin, texte):
        complet = os.path.join(self.racine, chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w", encoding="utf-8") as fh:
            fh.write(texte)

    def git(self, *args):
        subprocess.run(
            ["git", "-C", self.racine, *args], check=True, capture_output=True
        )

    def test_branch_uncommitted_files_and_unpushed_commits(self):
        self.git("init", "-q", "-b", "travail")
        self.ecrire("a.txt", "a")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "a")
        self.ecrire("b.txt", "b")
        self.assertEqual(
            session.lignes_travail(self.racine, t),
            ["🌿 Branch: travail · 1 uncommitted files · 1 unpushed commits"],
        )

    def test_outside_a_checkout_there_is_no_branch_line(self):
        with mock.patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": self.racine}
        ):
            self.assertEqual(session.lignes_travail(self.racine, t), [])

    def test_only_unchecked_boxes_of_the_plan_are_listed(self):
        cases = "".join(f"- [ ] tâche {n}\n" for n in range(10))
        self.ecrire("tasks/todo.md", "# Plan\n- [x] faite\n" + cases)
        lignes = session.lignes_plan(self.racine, t)
        self.assertEqual(lignes[0], "📋 Plan in progress (tasks/todo.md) : 10")
        self.assertEqual(lignes[1], "   - [ ] tâche 0")
        self.assertEqual(len(lignes), 1 + session.CASES_MAX + 1)
        self.assertEqual(lignes[-1], "   … +2")
        self.assertNotIn("faite", "\n".join(lignes))

    def test_the_reminder_and_the_resume_title(self):
        self.ecrire(".claude/session_start_message.txt", "Fait /context\n\n")
        texte = session.message(self.racine, "resume")
        self.assertIn("📌 Fait /context", texte)
        from script.todo.todo_i18n import t as traduire

        self.assertTrue(
            texte.startswith(traduire("ERPLibre — session resumed"))
        )
        self.assertTrue(
            session.message(self.racine, "startup").startswith(
                traduire("ERPLibre — new session")
            )
        )

    def test_the_same_text_goes_to_the_terminal_and_to_claude(self):
        sortie = session.sortie_hook("texte")
        self.assertEqual(sortie["systemMessage"], "texte")
        self.assertEqual(
            sortie["hookSpecificOutput"],
            {"hookEventName": "SessionStart", "additionalContext": "texte"},
        )

    def test_an_unreadable_hook_input_has_no_source(self):
        self.assertIsNone(session.lire_source(io.StringIO("pas du json")))
        self.assertEqual(
            session.lire_source(io.StringIO('{"source": "resume"}')),
            "resume",
        )

    def test_the_hook_always_prints_json_and_exits_zero(self):
        fait = subprocess.run(
            [
                sys.executable,
                os.path.join(RACINE, "script/claude/session_start.py"),
            ],
            input='{"source": "startup"}',
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("systemMessage", json.loads(fait.stdout))


class TestMenu(unittest.TestCase):
    """L'entrée « Réglages du dépôt » de Claude configs, sur une racine
    jetable : un oui écrit, un non laisse le fichier tel quel."""

    def setUp(self):
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = tmp.name
        self.todo = TODO.__new__(TODO)
        self.todo._claude_context_root = lambda: self.racine

    def menu(self, choix, reponses):
        with (
            mock.patch("click.prompt", side_effect=choix),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch("builtins.print") as affiche,
        ):
            self.todo._claude_reglages_depot()
        return "\n".join(
            " ".join(str(a) for a in appel.args)
            for appel in affiche.call_args_list
        )

    def test_a_yes_writes_and_a_no_leaves_the_file_alone(self):
        self.menu(["1", "0"], ["n"])
        self.assertEqual(c.lire(self.racine), {})
        self.menu(["1", "2", "0"], ["y", "y"])
        reglages = c.lire(self.racine)
        self.assertTrue(c.ultracode_actif(reglages))
        self.assertTrue(c.hook_installe(reglages))

    def test_the_preview_prints_the_session_message(self):
        with mock.patch.object(
            subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(session.sortie_hook("aperçu du message")), ""
            ),
        ):
            texte = self.menu(["3", "0"], [])
        self.assertIn("aperçu du message", texte)
        self.assertEqual(c.lire(self.racine), {})


if __name__ == "__main__":
    unittest.main()
