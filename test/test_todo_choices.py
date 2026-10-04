#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les choix des écrans de todo.py suivent les règles des sélecteurs.

Un numéro tel que la liste l'écrit, ou le nom exact qu'elle affiche ;
[0] Retour ; une réponse vide qui prend le défaut marqué, ou revient sans
lui ; une réponse invalide dite, puis la question reposée ; Ctrl+D qui
revient. Chaque réponse vient d'un double d'`input`, qui finit par une
réponse acceptée ou par « 0 » ; rien n'écrit dans env_var.sh ni dans les
préférences, et ce qu'un choix lancerait est un double qui note son appel.
"""

import contextlib
import io
import unittest
from unittest.mock import patch

from script.todo import todo as todo_module
from script.todo.todo import TODO
from script.todo.todo_i18n import t


def joue(action, *reponses):
    """(ce que rend `action()`, ce qu'elle imprime), chaque `input`
    répondu par `reponses`, dans l'ordre ; une réponse qui est une
    exception est levée à sa place, EOFError pour Ctrl+D."""
    with (
        patch("builtins.input", side_effect=reponses),
        contextlib.redirect_stdout(io.StringIO()) as sortie,
    ):
        rendu = action()
    return rendu, sortie.getvalue()


class TestLaLangue(unittest.TestCase):
    """La langue du premier lancement, puis Configuration › Language /
    Langue ; `set_lang`, qui écrit env_var.sh, est un double."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        patcher = patch.object(todo_module, "set_lang")
        self.set_lang = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_first_launch_takes_a_number_or_a_shown_name(self):
        cas = (
            (["1"], "fr"),
            (["English"], "en"),
            (["01", "2"], "en"),
            (["français", "Français"], "fr"),
        )
        with patch.object(
            todo_module, "lang_is_configured", return_value=False
        ):
            for reponses, langue in cas:
                with self.subTest(reponses=reponses):
                    self.set_lang.reset_mock()
                    _, sortie = joue(self.todo._ask_language, *reponses)
                    self.set_lang.assert_called_once_with(langue)
                    fautes = sortie.count(t("Invalid choice: "))
                    self.assertEqual(fautes, len(reponses) - 1)

    def test_the_first_launch_left_open_keeps_no_language(self):
        # [0], une réponse vide ou Ctrl+D : rien n'est gardé, et TODO
        # redemande au lancement suivant.
        with patch.object(
            todo_module, "lang_is_configured", return_value=False
        ):
            for reponse in ("0", "", EOFError()):
                with self.subTest(reponse=reponse):
                    _, sortie = joue(self.todo._ask_language, reponse)
                    self.assertIn("[0] ", sortie)
        self.set_lang.assert_not_called()

    def test_a_configured_language_asks_nothing(self):
        with patch.object(
            todo_module, "lang_is_configured", return_value=True
        ):
            _, sortie = joue(self.todo._ask_language)
        self.assertEqual(sortie, "")
        self.set_lang.assert_not_called()

    def test_the_language_changes_by_number_or_shown_name(self):
        for reponses, langue in (
            (["2"], "en"),
            ([t("French")], "fr"),
            (["x", "+1", "1"], "fr"),
        ):
            with self.subTest(reponses=reponses):
                self.set_lang.reset_mock()
                rendu, sortie = joue(self.todo._change_language, *reponses)
                self.set_lang.assert_called_once_with(langue)
                self.assertIsNone(rendu)
                fautes = sortie.count(t("Invalid choice: "))
                self.assertEqual(fautes, len(reponses) - 1)

    def test_back_or_an_empty_answer_changes_nothing(self):
        for reponse in ("0", "", EOFError()):
            with self.subTest(reponse=reponse):
                rendu, _ = joue(self.todo._change_language, reponse)
                self.assertIs(rendu, False)
        self.set_lang.assert_not_called()


class TestLesPreferences(unittest.TestCase):
    """Configuration › QEMU deployment interface : la valeur courante est
    le défaut marqué ; les préférences sont un dict."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.prefs = {"qemu_deploy_ui": "tui"}
        prefs = todo_module.todo_prefs
        for patcher in (
            patch.object(prefs, "get", side_effect=self.prefs.get),
            patch.object(prefs, "set", side_effect=self.prefs.__setitem__),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def edit(self, *reponses):
        return joue(lambda: self.todo._pref_edit("qemu_deploy_ui"), *reponses)

    def test_a_value_by_its_number_as_shown(self):
        _, sortie = self.edit("03", "+3", "3")
        self.assertEqual(self.prefs["qemu_deploy_ui"], "cli")
        self.assertEqual(sortie.count(t("Invalid choice: ")), 2)
        self.assertIn(f"✅ {t('QEMU deployment interface')} :", sortie)

    def test_the_current_value_is_the_default_an_empty_answer_keeps(self):
        _, sortie = self.edit("")
        self.assertIn(f"[2] {t('TUI form')} {t('(default)')}\n", sortie)
        self.assertEqual(self.prefs["qemu_deploy_ui"], "tui")

    def test_back_writes_nothing(self):
        for reponse in ("0", EOFError()):
            with self.subTest(reponse=reponse):
                with patch.object(todo_module.todo_prefs, "set") as ecrit:
                    _, sortie = self.edit(reponse)
                ecrit.assert_not_called()
                self.assertNotIn("✅", sortie)


if __name__ == "__main__":
    unittest.main()
