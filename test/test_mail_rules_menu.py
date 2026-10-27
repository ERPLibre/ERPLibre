#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Courriel [6] : les règles d'un compte sans ouvrir le TUI.

`click.prompt` est piloté par `side_effect`, le choix du compte par
`input`. Les règles vivent sous la base d'un cache placé dans un dossier
temporaire : le vrai dossier personnel n'est jamais touché.
"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.todo.mail import menu
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import storage
from script.todo.mail.rules.model import (
    Armed,
    Condition,
    Group,
    new_rule,
)
from script.todo.mail.store import Store
from script.todo.todo_i18n import t

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
T0 = 1_780_000_000


class FauxTodo:
    config_file = None

    def _menu_header(self):
        return "--"


class RulesMenuCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.account.cache_mode = "clear"
        patcheur = mock.patch.object(
            menu, "_load_accounts", lambda: [self.account]
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def tearDown(self):
        self.tmp.cleanup()
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

    def regles(self, *noms):
        for nom in noms:
            rule = new_rule("reply", nom)
            storage.upsert_rule(
                "perso", rule, rearm=Armed(7, 40, T0), base=self.base
            )
        return storage.load("perso", base=self.base)

    def ordre(self):
        return [r.name for r in storage.load("perso", base=self.base)]

    def lancer(self, *reponses) -> str:
        """`prompt_mail_rules` avec ces réponses à `click.prompt` ; rend
        ce qui a été imprimé."""
        sortie = io.StringIO()
        with (
            mock.patch("builtins.input", return_value="1"),
            mock.patch.object(
                menu.click, "prompt", side_effect=list(reponses)
            ) as invite,
            contextlib.redirect_stdout(sortie),
        ):
            menu.prompt_mail_rules(FauxTodo(), base=self.base)
        self.invite = invite
        return sortie.getvalue()


class TestMenuEntry(RulesMenuCase):
    def test_six_reaches_prompt_mail_rules(self):
        with (
            mock.patch.object(menu, "prompt_mail_rules") as regles,
            mock.patch.object(menu, "_configure_mail_logging"),
            mock.patch.object(menu.click, "prompt", side_effect=["6", "0"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            menu.prompt_execute_mail(FauxTodo())
        regles.assert_called_once()

    def test_the_mail_menu_lists_entry_six(self):
        sortie = io.StringIO()
        with (
            mock.patch.object(menu, "_configure_mail_logging"),
            mock.patch.object(
                menu.click, "prompt", side_effect=["0"]
            ) as invite,
            contextlib.redirect_stdout(sortie),
        ):
            menu.prompt_execute_mail(FauxTodo())
        self.assertIn(f"[6] {t('mail_rules_menu')}", invite.call_args[0][0])

    def test_creation_is_sent_to_the_tui(self):
        sortie = self.lancer("0")
        self.assertIn(t("mail_rules_menu_edit_in_tui"), sortie)

    def test_an_ephemeral_cache_has_no_rules(self):
        self.account.cache_mode = "ephemeral"
        sortie = self.lancer()
        self.assertIn(t("mail_rules_ephemeral"), sortie)
        self.assertFalse((self.base / storage.RULES_DIRNAME).exists())

    def test_no_account_chosen_returns(self):
        with mock.patch("builtins.input", return_value="9"):
            with mock.patch.object(menu.click, "prompt") as invite:
                with contextlib.redirect_stdout(io.StringIO()):
                    menu.prompt_mail_rules(FauxTodo(), base=self.base)
        invite.assert_not_called()


class TestListAndChange(RulesMenuCase):
    def test_list_prints_order_state_and_filter(self):
        rule = new_rule("reply", "Absence")
        rule.filter = Group(
            children=[Condition("from", "*@example.net", op="glob")]
        )
        storage.upsert_rule("perso", rule, base=self.base)
        self.regles("Vacances")
        sortie = self.lancer("1", "0")
        self.assertIn("[1] ☑ Absence", sortie)
        self.assertIn("[2] ☑ Vacances", sortie)
        self.assertIn(t("mail_rules_kind_reply"), sortie)
        self.assertIn('"*@example.net"', sortie)
        self.assertIn(t("mail_rules_match_all"), sortie)

    def test_an_empty_list_says_so(self):
        sortie = self.lancer("1", "0")
        self.assertIn(t("mail_rules_none"), sortie)

    def test_toggle_disables_then_enables_unarmed(self):
        self.regles("A")
        self.lancer("2", "1", "0")
        regle = storage.load("perso", base=self.base)[0]
        self.assertFalse(regle.enabled)
        self.assertIsNone(regle.armed)
        self.lancer("2", "1", "0")
        regle = storage.load("perso", base=self.base)[0]
        self.assertTrue(regle.enabled)
        # Armée par le moteur à sa passe suivante, jamais sur l'arriéré.
        self.assertIsNone(regle.armed)

    def test_move_up_and_down(self):
        self.regles("A", "B", "C")
        self.lancer("3", "3", "1", "0")
        self.assertEqual(self.ordre(), ["A", "C", "B"])
        self.lancer("3", "1", "2", "0")
        self.assertEqual(self.ordre(), ["C", "A", "B"])

    def test_a_bad_direction_changes_nothing(self):
        self.regles("A", "B")
        sortie = self.lancer("3", "1", "x", "0")
        self.assertIn(t("Command not found !"), sortie)
        self.assertEqual(self.ordre(), ["A", "B"])

    def test_delete_after_confirmation(self):
        self.regles("A", "B")
        self.lancer("4", "1", "o", "0")
        self.assertEqual(self.ordre(), ["B"])

    def test_delete_refused_keeps_the_rule(self):
        self.regles("A", "B")
        self.lancer("4", "1", "n", "0")
        self.assertEqual(self.ordre(), ["A", "B"])

    def test_an_unknown_number_changes_nothing(self):
        self.regles("A")
        for numero in ("0", "5", "x"):
            sortie = self.lancer("2", numero, "0")
            self.assertIn(t("mail_rules_menu_unknown_rule"), sortie)
        self.assertTrue(storage.load("perso", base=self.base)[0].enabled)

    def test_a_busy_lock_is_reported(self):
        from script.todo.mail.rules.lock import file_lock

        self.regles("A")
        with file_lock(storage.lock_path("perso", self.base)) as tenu:
            self.assertTrue(tenu)
            sortie = self.lancer("2", "1", "0")
        self.assertIn(t("mail_rules_busy"), sortie)
        self.assertTrue(storage.load("perso", base=self.base)[0].enabled)

    def test_an_unreadable_file_is_reported(self):
        storage.rules_path("perso", self.base).write_text("{")
        sortie = self.lancer("1", "0")
        self.assertIn(t("mail_rules_err_bad_json"), sortie)


class TestJournal(RulesMenuCase):
    def test_journal_prints_translated_outcome_and_rule_name(self):
        regle = self.regles("Absence")[0]
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            store.rule_log_claim(
                regle.id,
                "cle-1",
                outcome="skipped",
                reason="throttled",
                at=T0,
                sender=CAROLE,
                subject="Devis",
            )
        finally:
            store.close()
        sortie = self.lancer("5", "0")
        self.assertIn("Absence", sortie)
        self.assertIn(t("mail_rules_outcome_skipped"), sortie)
        self.assertIn(t("mail_rules_reason_throttled"), sortie)
        self.assertIn(CAROLE, sortie)

    def test_journal_strips_terminal_escapes_from_message_text(self):
        """Un sujet décodé RFC 2047 peut porter ESC : imprimé tel quel, il
        écrirait dans le presse-papiers (OSC 52) ou réécrirait l'écran."""
        regle = self.regles("Absence")[0]
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            store.rule_log_claim(
                regle.id,
                "cle-1",
                outcome="skipped",
                reason="throttled",
                at=T0,
                sender=f"{CAROLE}\x1b[2J",
                subject="Devis\x1b]52;c;ZXZpbA==\x07\u202efin\x9b",
            )
        finally:
            store.close()
        sortie = self.lancer("5", "0")
        for controle in ("\x1b", "\x07", "\u202e", "\x9b"):
            self.assertNotIn(controle, sortie)
        self.assertIn("Devis]52;c;ZXZpbA==fin", sortie)
        self.assertIn(f"{CAROLE}[2J", sortie)

    def test_printable_turns_control_whitespace_into_a_space(self):
        self.assertEqual(menu._printable("a\tb\nc\x00d"), "a b cd")
        self.assertEqual(menu._printable(None), "")
        self.assertEqual(menu._printable("Réponse"), "Réponse")

    def test_an_empty_journal_says_so(self):
        self.regles("Absence")
        sortie = self.lancer("5", "0")
        self.assertIn(t("mail_rules_log_empty"), sortie)

    def test_a_clear_cache_does_not_open_the_vault(self):
        with mock.patch.object(menu, "secret_store_for") as coffre:
            self.lancer("5", "0")
        coffre.assert_not_called()


if __name__ == "__main__":
    unittest.main()
