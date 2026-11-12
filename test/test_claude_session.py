#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le message du hook SessionStart de Claude Code pour ce dépôt.

Le message se compose sur un dépôt git jetable, isolé de la config git du
compte.
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


def t(texte):
    return texte


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


if __name__ == "__main__":
    unittest.main()
