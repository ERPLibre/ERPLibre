#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écrans des règles du courrier entrant : touche `e`, éditeurs, file.

L'application est montée pour de vrai (`run_test`), HOME et cache sous
des dossiers temporaires : les règles s'écrivent sous la base du cache
(`storage.base_of`), jamais dans le vrai dossier personnel. Les champs se
règlent par affectation directe, les boutons par `Button.press()`, et les
écritures, qui tournent dans des fils de travail, s'attendent par
`app.workers.wait_for_complete()`. Aucun test ne passe par
`browse_one_path`, qui suspend l'application.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import (
    ACTION_KINDS,
    FIELDS,
    FORMATS,
    GROUP_OPS,
    MODES,
    OPS,
    Armed,
    Condition,
    Group,
    new_rule,
)
from script.todo.mail.smtp_send import build_message
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session
from script.todo.todo_i18n import TRANSLATIONS, t

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"
DENIS = "denis.tri@example.org"
T0 = 1_780_000_000
# Le plus petit PNG valide : l'import ne lit que l'extension et la taille,
# l'aperçu n'en lit que le nom.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44"
    "ae426082"
)


class RulesCase(unittest.IsolatedAsyncioTestCase):
    SIZE = (120, 50)

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.store = Store(self.account, mode="clear", base=self.base)
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")
        self.store.set_folder_state("INBOX", uidvalidity=7, uidnext=42)
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=uid,
                    date=T0 + uid,
                    size=100,
                    flags="",
                    msgid=f"<{uid}@example.org>",
                    frm=frm,
                    to=OWN,
                    subject=sujet,
                    snippet="",
                )
                for uid, frm, sujet in (
                    (1, CAROLE, "Devis"),
                    (2, BRUNO, "Réunion"),
                    (3, BRUNO, "Facture"),
                )
            ],
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

    def _app(self, store=None):
        import textual.app

        from script.todo.mail.tui import run_tui

        captured = []
        orig = textual.app.App.__init__

        def cap(app_self, *a, **k):
            orig(app_self, *a, **k)
            captured.append(app_self)

        textual.app.App.__init__ = cap
        try:
            run_tui(
                run_app=False,
                sessions=[
                    Session(
                        self.account,
                        store or self.store,
                        None,
                        password="x",
                    )
                ],
            )
        finally:
            textual.app.App.__init__ = orig
        app = captured[-1]
        app.current_ref = MailboxRef(
            account_name="perso",
            folder_name="INBOX",
            display="Boîte",
            unseen=0,
        )
        return app

    def rules_file(self) -> dict:
        return json.loads(storage.rules_path("perso", self.base).read_text())

    def stored(self, *rules):
        for rule in rules:
            storage.upsert_rule("perso", rule, base=self.base)
        return storage.load("perso", base=self.base)

    async def settle(self, app, pilot):
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def open_rules(self, app, pilot):
        await pilot.press("e")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "RulesScreen")

    async def open_new_editor(self, app, pilot):
        await self.open_rules(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")

    def q(self, app, selector, kind=None):
        if kind is None:
            return app.screen.query_one(selector)
        return app.screen.query_one(selector, kind)

    def text_of(self, app, selector) -> str:
        from textual.widgets import Static

        return str(self.q(app, selector, Static).content)

    async def press(self, app, pilot, selector):
        from textual.widgets import Button

        self.q(app, selector, Button).press()
        await pilot.pause()

    async def add_condition(
        self, app, pilot, field, op, value, mode="substring_ci"
    ):
        from textual.widgets import Input, Select

        await self.press(app, pilot, "#add_condition")
        self.assertEqual(type(app.screen).__name__, "ConditionScreen")
        self.q(app, "#cond_field", Select).value = field
        self.q(app, "#cond_op", Select).value = op
        self.q(app, "#cond_mode", Select).value = mode
        self.q(app, "#cond_value", Input).value = value
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")

    async def add_group(self, app, pilot, op):
        from textual.widgets import Select

        self.q(app, "#new_group_op", Select).value = op
        await pilot.pause()
        await self.press(app, pilot, "#add_group")

    async def cursor_to_root(self, app, pilot):
        from textual.widgets import Tree

        tree = self.q(app, "#rule_filter", Tree)
        tree.move_cursor(tree.root)
        await pilot.pause()


class TestOpening(RulesCase):
    async def test_e_opens_the_rules_screen(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            self.assertIn(
                t("mail_rules_none"), self.text_of(app, "#rules_status")
            )

    async def test_n_opens_the_editor(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)

    async def test_the_hint_lists_the_screen_bindings(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            hint = self.text_of(app, "#rules_hint")
            for key in (
                "mail_rules_new",
                "mail_rules_trial",
                "mail_rules_journal",
            ):
                self.assertIn(t(key), hint)

    async def test_an_ephemeral_account_shows_the_banner_only(self):
        from textual.css.query import NoMatches

        store = Store(self.account, mode="ephemeral", base=self.base)
        store.open()
        self.addCleanup(store.close)
        app = self._app(store)
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            self.assertIn(
                t("mail_rules_ephemeral"), self.text_of(app, "#rules_banner")
            )
            with self.assertRaises(NoMatches):
                app.screen.query_one("#rules_table")
            await pilot.press("n")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIn(type(app.screen).__name__, ("RulesScreen",))
        self.assertFalse((self.base / storage.RULES_DIRNAME).exists())

    async def test_a_cache_that_failed_to_open_names_its_error(self):
        from textual.css.query import NoMatches

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            # Les écrans naissent dans `run_tui` : la classe se prend sur
            # l'écran ouvert par `e`.
            await self.open_rules(app, pilot)
            ecran = type(app.screen)
            await pilot.press("escape")
            await pilot.pause()
            app.push_screen(
                ecran(Session(self.account, None, None, "cache illisible", ""))
            )
            await pilot.pause()
            banniere = self.text_of(app, "#rules_banner")
            self.assertIn(t("mail_rules_no_cache"), banniere)
            self.assertIn("cache illisible", banniere)
            self.assertNotIn(t("mail_rules_ephemeral"), banniere)
            with self.assertRaises(NoMatches):
                app.screen.query_one("#rules_table")


class TestFilterEditor(RulesCase):
    async def test_a_nested_filter_is_written_as_expected(self):
        """ET(De glob, NON(Sujet mot), OU(À/Cc exact, Corps contient))."""
        from textual.widgets import Input, Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.q(app, "#rule_name", Input).value = "Absence"
            await self.add_condition(
                app, pilot, "from", "glob", "*@example.net"
            )
            await self.add_group(app, pilot, "not")
            await self.add_condition(
                app, pilot, "subject", "contains", "facture", "word"
            )
            await self.cursor_to_root(app, pilot)
            await self.add_group(app, pilot, "all")
            self.q(app, "#group_op", Select).value = "any"
            await pilot.pause()
            await self.add_condition(
                app, pilot, "to_cc", "contains", DENIS, "exact"
            )
            await self.add_condition(app, pilot, "body", "contains", "devis")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RulesScreen")

        regle = self.rules_file()["rules"][0]
        self.assertEqual(regle["name"], "Absence")

        def cond(field, op, value, mode="substring_ci"):
            return {
                "type": "condition",
                "field": field,
                "op": op,
                "value": value,
                "mode": mode,
            }

        self.assertEqual(
            regle["filter"],
            {
                "type": "group",
                "op": "all",
                "children": [
                    cond("from", "glob", "*@example.net"),
                    {
                        "type": "group",
                        "op": "not",
                        "children": [
                            cond("subject", "contains", "facture", "word")
                        ],
                    },
                    {
                        "type": "group",
                        "op": "any",
                        "children": [
                            cond("to_cc", "contains", DENIS, "exact"),
                            cond("body", "contains", "devis"),
                        ],
                    },
                ],
            },
        )
        # Activée à l'enregistrement : armée sur l'UIDNEXT connu.
        self.assertEqual(regle["armed"]["uidvalidity"], 7)
        self.assertEqual(regle["armed"]["uidnext"], 42)

    async def test_add_is_disabled_under_a_not_that_has_its_child(self):
        from textual.widgets import Button

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_group(app, pilot, "not")
            self.assertFalse(self.q(app, "#add_condition", Button).disabled)
            await self.add_condition(app, pilot, "subject", "contains", "x")
            self.assertTrue(self.q(app, "#add_condition", Button).disabled)
            self.assertTrue(self.q(app, "#add_group", Button).disabled)
            await self.cursor_to_root(app, pilot)
            self.assertFalse(self.q(app, "#add_condition", Button).disabled)

    async def test_not_is_refused_for_a_group_of_two(self):
        from textual.widgets import Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_condition(app, pilot, "subject", "contains", "a")
            await self.add_condition(app, pilot, "subject", "contains", "b")
            await self.cursor_to_root(app, pilot)
            self.q(app, "#group_op", Select).value = "not"
            await pilot.pause()
            self.assertIn(
                t("mail_rules_err_not_one_child"),
                self.text_of(app, "#rule_status"),
            )
            self.assertEqual(app.screen.rule.filter.op, "all")
            self.assertEqual(self.q(app, "#group_op", Select).value, "all")

    async def test_delete_on_the_root_empties_it(self):
        from textual.widgets import Tree

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_condition(app, pilot, "subject", "contains", "a")
            await self.add_group(app, pilot, "any")
            await self.cursor_to_root(app, pilot)
            await self.press(app, pilot, "#delete_node")
            self.assertEqual(app.screen.rule.filter.children, [])
            tree = self.q(app, "#rule_filter", Tree)
            self.assertEqual(tree.root.label.plain, t("mail_rules_match_all"))

    async def test_delete_on_a_condition_moves_the_cursor_to_its_group(self):
        from textual.widgets import Tree

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_group(app, pilot, "any")
            await self.add_condition(app, pilot, "subject", "contains", "a")
            await self.press(app, pilot, "#delete_node")
            tree = self.q(app, "#rule_filter", Tree)
            self.assertEqual(tree.cursor_node.data, (0,))
            self.assertEqual(app.screen.rule.filter.children[0].children, [])

    async def test_edit_node_replaces_the_condition(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_condition(app, pilot, "subject", "contains", "a")
            await self.press(app, pilot, "#edit_node")
            self.assertEqual(type(app.screen).__name__, "ConditionScreen")
            self.assertEqual(self.q(app, "#cond_value", Input).value, "a")
            self.q(app, "#cond_value", Input).value = "b"
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(app.screen.rule.filter.children[0].value, "b")

    async def test_the_preview_counts_cached_matches(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.assertIn("3/3", self.text_of(app, "#filter_preview"))
            await self.add_condition(
                app, pilot, "from", "glob", "*@example.net"
            )
            self.assertIn("2/3", self.text_of(app, "#filter_preview"))

    def test_a_slow_regex_bounds_the_preview_and_says_so(self):
        """L'aperçu s'évalue dans le fil de l'interface : passé son budget,
        il s'arrête et le dit, au lieu de geler l'écran."""
        from unittest import mock

        from script.todo.mail import tui
        from script.todo.mail.rules import regex_worker

        appels = []

        def lente(pattern, texts, timeout):
            appels.append(timeout)
            time.sleep(0.2)
            return False

        racine = Group(
            children=[Condition("subject", "x", op="contains", mode="regex")]
        )
        with (
            mock.patch.object(tui, "RULES_PREVIEW_REGEX_S", 0.3),
            mock.patch.object(regex_worker._WORKER, "search", lente),
        ):
            texte = tui.rules_filter_preview(self.store, racine)
        self.assertIn(t("mail_rules_err_regex_timeout"), texte)
        self.assertLessEqual(len(appels), 2)
        self.assertTrue(all(budget <= 0.3 for budget in appels))

    async def test_a_body_condition_is_counted_unknown(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_condition(app, pilot, "body", "contains", "devis")
            apercu = self.text_of(app, "#filter_preview")
            self.assertIn(t("mail_rules_preview_body_unknown"), apercu)
            self.assertIn("0/3", apercu)

    async def test_a_to_cc_condition_says_cc_is_not_cached(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.add_condition(app, pilot, "to_cc", "contains", OWN)
            self.assertIn(
                t("mail_rules_preview_to_only"),
                self.text_of(app, "#filter_preview"),
            )


class TestConditionScreen(RulesCase):
    async def test_a_glob_on_the_subject_is_refused(self):
        from textual.widgets import Input, Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.press(app, pilot, "#add_condition")
            self.q(app, "#cond_field", Select).value = "subject"
            self.q(app, "#cond_op", Select).value = "glob"
            self.q(app, "#cond_value", Input).value = "*x*"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ConditionScreen")
            self.assertIn(
                t("mail_rules_err_glob_field"),
                self.text_of(app, "#cond_status"),
            )

    async def test_the_mode_is_greyed_for_a_glob(self):
        from textual.widgets import Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.press(app, pilot, "#add_condition")
            self.q(app, "#cond_op", Select).value = "glob"
            await pilot.pause()
            self.assertTrue(self.q(app, "#cond_mode", Select).disabled)
            self.q(app, "#cond_op", Select).value = "contains"
            await pilot.pause()
            self.assertFalse(self.q(app, "#cond_mode", Select).disabled)

    async def test_an_empty_value_is_refused(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.press(app, pilot, "#add_condition")
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertIn(
                t("mail_rules_err_empty_value"),
                self.text_of(app, "#cond_status"),
            )


class TestThrottleField(RulesCase):
    def regle_decochee(self):
        rule = new_rule("reply", "Sans limite")
        rule.throttle_enabled = False
        rule.throttle_minutes = 30
        return self.stored(rule)[0]

    async def open_editor_on_first(self, app, pilot):
        await self.open_rules(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")

    async def test_unchecked_rule_opens_with_minutes_greyed(self):
        from textual.widgets import Input

        self.regle_decochee()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_editor_on_first(app, pilot)
            self.assertTrue(self.q(app, "#rule_minutes", Input).disabled)
            self.assertEqual(self.q(app, "#rule_minutes", Input).value, "30")

    async def test_unchecking_greys_and_rechecking_enables(self):
        from textual.widgets import Checkbox, Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            champ = self.q(app, "#rule_minutes", Input)
            self.assertFalse(champ.disabled)
            self.assertEqual(champ.value, "10080")
            self.q(app, "#rule_throttle", Checkbox).value = False
            await pilot.pause()
            self.assertTrue(champ.disabled)
            self.q(app, "#rule_throttle", Checkbox).value = True
            await pilot.pause()
            self.assertFalse(champ.disabled)

    async def test_unchecking_with_zero_restores_a_valid_value(self):
        from textual.widgets import Checkbox, Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            champ = self.q(app, "#rule_minutes", Input)
            champ.value = "15"
            await pilot.pause()
            champ.value = "0"
            await pilot.pause()
            self.q(app, "#rule_throttle", Checkbox).value = False
            await pilot.pause()
            self.assertEqual(champ.value, "15")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
        regle = self.rules_file()["rules"][0]
        self.assertFalse(regle["throttle_enabled"])
        self.assertEqual(regle["throttle_minutes"], 15)

    async def _refused(self, valeur, cle):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.q(app, "#rule_minutes", Input).value = valeur
            await pilot.pause()
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.assertIn(t(cle), self.text_of(app, "#rule_status"))
        self.assertFalse(storage.rules_path("perso", self.base).exists())

    async def test_zero_minutes_while_checked_is_refused(self):
        await self._refused("0", "mail_rules_err_minutes")

    async def test_non_numeric_minutes_are_refused(self):
        await self._refused("abc", "mail_rules_err_minutes")

    async def test_max_age_and_hold_first_are_checked(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.q(app, "#rule_max_age", Input).value = "9999"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertIn(
                t("mail_rules_err_max_age"), self.text_of(app, "#rule_status")
            )
            self.q(app, "#rule_max_age", Input).value = "24"
            self.q(app, "#rule_hold_first", Input).value = "x"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertIn(
                t("mail_rules_err_hold_first"),
                self.text_of(app, "#rule_status"),
            )


class TestReplyForm(RulesCase):
    async def open_reply_form(self, app, pilot):
        await self.open_new_editor(app, pilot)
        await self.press(app, pilot, "#reply_form")
        self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")

    def png(self, name="logo.png") -> Path:
        chemin = Path(self.home.name) / name
        chemin.write_bytes(PNG)
        return chemin

    async def add_image(self, app, pilot, path):
        from textual.widgets import Input

        self.q(app, "#image_paths", Input).value = str(path)
        await self.press(app, pilot, "#add_images")
        await self.settle(app, pilot)

    async def test_html_with_an_added_image_previews_it_inline(self):
        from textual.widgets import Input, Select, TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            self.q(app, "#reply_format", Select).value = "html"
            self.q(
                app, "#reply_body", TextArea
            ).text = '<p>Absente.</p><img src="logo.png">'
            await pilot.pause()
            await self.add_image(app, pilot, self.png())
            apercu = self.text_of(app, "#reply_preview")
            self.assertIn("Absente.", apercu)
            self.assertIn(f"logo.png — {t('mail_rules_image_inline')}", apercu)
            self.assertEqual(self.q(app, "#image_paths", Input).value, "")
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            action = app.screen.rule.action
            self.assertEqual(action.format, "html")
            self.assertEqual([r.file for r in action.images], ["logo.png"])
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
        image = self.rules_file()["rules"][0]["action"]["images"][0]
        self.assertEqual(image["file"], "logo.png")
        self.assertEqual(image["mime"], "image/png")

    async def test_text_format_sends_every_image_attached(self):
        from textual.widgets import Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            self.q(app, "#reply_format", Select).value = "text"
            await pilot.pause()
            await self.add_image(app, pilot, self.png())
            self.assertIn(
                f"logo.png — {t('mail_rules_image_attached')}",
                self.text_of(app, "#reply_preview"),
            )

    async def test_a_refused_image_stays_in_the_field(self):
        from textual.widgets import Input

        texte = Path(self.home.name) / "notes.txt"
        texte.write_text("x")
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            await self.add_image(app, pilot, texte)
            self.assertIn(
                t("mail_rules_err_image_type"),
                self.text_of(app, "#reply_status"),
            )
            self.assertEqual(
                self.q(app, "#image_paths", Input).value, str(texte)
            )
            self.assertEqual(app.screen.action.images, [])

    async def test_remove_image_takes_it_off_the_list(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            await self.add_image(app, pilot, self.png())
            bouton = app.screen.query(".remove_image").first()
            bouton.press()
            await pilot.pause()
            self.assertEqual(app.screen.action.images, [])

    async def test_escape_returns_without_changing_the_action(self):
        from textual.widgets import TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            self.q(app, "#reply_body", TextArea).text = "Changé"
            await pilot.pause()
            await self.press(app, pilot, "#reply_cancel")
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.assertEqual(app.screen.rule.action.body, "")

    async def test_the_image_label_shows_its_role_once_added(self):
        from textual.widgets import Select, Static, TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            self.q(app, "#reply_format", Select).value = "html"
            self.q(
                app, "#reply_body", TextArea
            ).text = '<p>Absente.</p><img src="logo.png">'
            await pilot.pause()
            await self.add_image(app, pilot, self.png())
            libelles = [
                str(s.content)
                for s in app.screen.query(".reply_image_label").results(Static)
            ]
            self.assertEqual(
                libelles, [f"logo.png — {t('mail_rules_image_inline')}"]
            )

    async def test_a_reopened_form_labels_its_images_with_their_role(self):
        from textual.widgets import Static

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            await self.add_image(app, pilot, self.png())
            await pilot.press("ctrl+s")
            await pilot.pause()
            await self.press(app, pilot, "#reply_form")
            self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")
            await pilot.pause()
            libelles = [
                str(s.content)
                for s in app.screen.query(".reply_image_label").results(Static)
            ]
            self.assertEqual(
                libelles, [f"logo.png — {t('mail_rules_image_attached')}"]
            )

    async def test_paths_typed_but_not_added_block_the_save(self):
        from textual.widgets import Input

        chemin = self.png()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            self.q(app, "#image_paths", Input).value = str(chemin)
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")
            self.assertIn(
                t("mail_rules_err_images_pending"),
                self.text_of(app, "#reply_status"),
            )
            self.assertEqual(app.screen.action.images, [])

    async def test_a_reply_that_cannot_be_built_is_refused(self):
        from script.todo.mail.rules import markup

        chemins = []
        for numero in range(3):
            chemin = Path(self.home.name) / f"img{numero}.png"
            chemin.write_bytes(PNG + bytes([numero]) * 100)
            chemins.append(chemin)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            for chemin in chemins:
                await self.add_image(app, pilot, chemin)
            self.assertEqual(len(app.screen.action.images), 3)
            # Plafond abaissé sous la somme des trois : même refus qu'au
            # vrai plafond, sans écrire des mégaoctets.
            ancien = markup.MAX_IMAGES_TOTAL_BYTES
            markup.MAX_IMAGES_TOTAL_BYTES = 3 * len(PNG)
            try:
                await pilot.press("ctrl+s")
                await pilot.pause()
            finally:
                markup.MAX_IMAGES_TOTAL_BYTES = ancien
            self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")
            self.assertNotEqual(self.text_of(app, "#reply_status"), "")

    async def test_an_image_changed_on_disk_is_named_as_changed(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_reply_form(app, pilot)
            await self.add_image(app, pilot, self.png())
            stocke = storage.media_dir("perso", self.base) / "logo.png"
            stocke.write_bytes(PNG + b"autre")
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")
            statut = self.text_of(app, "#reply_status")
            self.assertIn(t("mail_rules_err_image_changed"), statut)
            self.assertNotIn(t("mail_rules_err_image_missing"), statut)
            self.assertIn(
                t("mail_rules_err_image_changed"),
                self.text_of(app, "#reply_preview"),
            )


class TestRuleEditorSaving(RulesCase):
    async def test_the_form_is_inert_while_the_lock_is_awaited(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            with file_lock(storage.lock_path("perso", self.base)) as tenu:
                self.assertTrue(tenu)
                await pilot.press("ctrl+s")
                await pilot.pause()
                self.assertTrue(self.q(app, "#rule_form").disabled)
                await self.press(app, pilot, "#reply_form")
                await self.press(app, pilot, "#add_condition")
                self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
        self.assertEqual(len(storage.load("perso", base=self.base)), 1)

    async def test_a_save_finished_under_another_screen_closes_on_return(
        self,
    ):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            editeur = app.screen
            await self.press(app, pilot, "#add_condition")
            self.assertEqual(type(app.screen).__name__, "ConditionScreen")
            # Fin d'écriture rapportée pendant que la condition couvre
            # l'éditeur : l'ordre que le grisé empêche au clavier.
            editeur._enregistrement = True
            editeur._enregistree(editeur.rule.id)
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ConditionScreen")
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RulesScreen")

    async def test_a_busy_lock_reenables_the_form(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.q(app, "#rule_name", Input).focus()
            await pilot.pause()
            with file_lock(storage.lock_path("perso", self.base)) as tenu:
                self.assertTrue(tenu)
                await pilot.press("ctrl+s")
                await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.assertFalse(self.q(app, "#rule_form").disabled)
            self.assertIn(
                t("mail_rules_busy"), self.text_of(app, "#rule_status")
            )
            self.assertEqual(app.focused.id, "rule_name")
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
        self.assertEqual(storage.load("perso", base=self.base), [])


class TestLiteralText(RulesCase):
    async def test_brackets_show_in_the_table_and_the_tree(self):
        from textual.widgets import DataTable, Tree

        rule = new_rule("reply", "[auto] z")
        rule.filter = Group(
            op="all", children=[Condition(field="subject", value="[x] y")]
        )
        self.stored(rule)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            table = self.q(app, "#rules_table", DataTable)
            self.assertEqual(table.get_row(rule.id)[2].plain, "[auto] z")
            await pilot.press("enter")
            await pilot.pause()
            tree = self.q(app, "#rule_filter", Tree)
            self.assertIn('"[x] y"', tree.root.children[0].label.plain)


class TestRuleList(RulesCase):
    def trois(self):
        regles = [new_rule("reply", nom) for nom in ("A", "B", "C")]
        return self.stored(*regles)

    def ordre(self):
        return [r.name for r in storage.load("perso", base=self.base)]

    def curseur(self, app):
        from textual.widgets import DataTable

        table = self.q(app, "#rules_table", DataTable)
        cle = table.coordinate_to_cell_key(table.cursor_coordinate)
        return cle.row_key.value

    async def test_space_enables_and_arms_on_the_known_uidnext(self):
        rule = new_rule("reply", "Absence")
        rule.enabled = False
        self.stored(rule)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("space")
            await self.settle(app, pilot)
            self.assertEqual(self.curseur(app), rule.id)
        relue = storage.load("perso", base=self.base)[0]
        self.assertTrue(relue.enabled)
        self.assertEqual(
            (relue.armed.uidvalidity, relue.armed.uidnext), (7, 42)
        )

    async def test_space_disables_and_disarms(self):
        rule = new_rule("reply", "Absence")
        storage.upsert_rule(
            "perso", rule, rearm=Armed(7, 40, T0), base=self.base
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("space")
            await self.settle(app, pilot)
        relue = storage.load("perso", base=self.base)[0]
        self.assertFalse(relue.enabled)
        self.assertIsNone(relue.armed)

    async def test_k_and_j_reorder_and_the_cursor_follows(self):
        from textual.widgets import DataTable

        regles = self.trois()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            table = self.q(app, "#rules_table", DataTable)
            table.move_cursor(row=2)
            await pilot.pause()
            await pilot.press("k")
            await self.settle(app, pilot)
            self.assertEqual(self.ordre(), ["A", "C", "B"])
            self.assertEqual(self.curseur(app), regles[2].id)
            self.assertEqual(table.cursor_row, 1)
            await pilot.press("j")
            await self.settle(app, pilot)
            self.assertEqual(self.ordre(), ["A", "B", "C"])
            self.assertEqual(self.curseur(app), regles[2].id)

    async def test_t_toggles_stop_here(self):
        self.trois()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("t")
            await self.settle(app, pilot)
        self.assertTrue(storage.load("perso", base=self.base)[0].stop_after)

    async def test_enter_on_a_row_opens_its_editor(self):
        from textual.widgets import DataTable, Input

        regles = self.trois()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            self.q(app, "#rules_table", DataTable).move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.assertEqual(app.screen.rule.id, regles[1].id)
            self.assertEqual(self.q(app, "#rule_name", Input).value, "B")
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RulesScreen")

    async def test_editing_keeps_the_engine_arming(self):
        from textual.widgets import Input

        rule = new_rule("reply", "Absence")
        storage.upsert_rule(
            "perso", rule, rearm=Armed(7, 40, T0), base=self.base
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.q(app, "#rule_name", Input).value = "Vacances"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertIn(
                t("mail_rules_saved"), self.text_of(app, "#rules_status")
            )
        relue = storage.load("perso", base=self.base)[0]
        self.assertEqual(relue.name, "Vacances")
        self.assertEqual(relue.armed.uidnext, 40)

    async def test_x_with_confirmation_deletes(self):
        regles = self.trois()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("x")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ConfirmScreen")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
        self.assertNotIn(
            regles[0].id, [r.id for r in storage.load("perso", base=self.base)]
        )
        self.assertEqual(self.ordre(), ["B", "C"])

    async def test_x_refused_keeps_the_rule(self):
        self.trois()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("escape")
            await self.settle(app, pilot)
        self.assertEqual(self.ordre(), ["A", "B", "C"])

    async def test_l_shows_a_translated_reason(self):
        from textual.widgets import DataTable

        regle = self.trois()[0]
        self.store.rule_log_claim(
            regle.id,
            "cle-1",
            outcome="skipped",
            reason="throttled",
            at=T0,
            sender=CAROLE,
            subject="[urgent] Devis",
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            self.assertIn(
                t("mail_rules_reason_throttled"),
                self.q(app, "#rules_table", DataTable)
                .get_row(regle.id)[5]
                .plain,
            )
            await pilot.press("l")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleLogScreen")
            ligne = self.q(app, "#rules_log_table", DataTable).get_row_at(0)
            texte = [str(getattr(c, "plain", c)) for c in ligne]
            self.assertEqual(texte[1], "A")
            self.assertEqual(texte[2], t("mail_rules_outcome_skipped"))
            self.assertEqual(texte[3], t("mail_rules_reason_throttled"))
            self.assertEqual(texte[4], CAROLE)
            self.assertEqual(texte[5], "[urgent] Devis")

    async def test_a_held_lock_shows_busy_without_loss_or_freeze(self):
        rule = new_rule("reply", "Absence")
        rule.enabled = False
        self.stored(rule)
        avant = storage.rules_path("perso", self.base).read_bytes()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            with file_lock(storage.lock_path("perso", self.base)) as tenu:
                self.assertTrue(tenu)
                debut = time.monotonic()
                await pilot.press("space")
                # L'interface répond pendant que le fil attend le verrou.
                await pilot.pause()
                self.assertLess(time.monotonic() - debut, 1.0)
                self.assertEqual(type(app.screen).__name__, "RulesScreen")
                await self.settle(app, pilot)
            self.assertIn(
                t("mail_rules_busy"), self.text_of(app, "#rules_status")
            )
        self.assertEqual(
            storage.rules_path("perso", self.base).read_bytes(), avant
        )

    async def test_the_caps_are_saved_into_rules_json(self):
        from textual.widgets import Input

        self.trois()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            self.assertEqual(self.q(app, "#caps_per_pass", Input).value, "20")
            self.assertEqual(self.q(app, "#caps_per_hour", Input).value, "60")
            self.q(app, "#caps_per_pass", Input).value = "5"
            self.q(app, "#caps_per_hour", Input).value = "12"
            await self.press(app, pilot, "#caps_save")
            await self.settle(app, pilot)
            self.assertIn(
                t("mail_rules_caps_saved"), self.text_of(app, "#rules_status")
            )
        self.assertEqual(
            self.rules_file()["caps"], {"per_pass": 5, "per_hour": 12}
        )
        self.assertEqual(self.ordre(), ["A", "B", "C"])

    async def test_a_zero_cap_is_refused(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            self.q(app, "#caps_per_pass", Input).value = "0"
            await self.press(app, pilot, "#caps_save")
            await self.settle(app, pilot)
            self.assertIn(
                t("mail_rules_err_invalid"), self.text_of(app, "#rules_status")
            )
        self.assertEqual(
            storage.load_caps("perso", base=self.base), storage.Caps()
        )


class TestOutboxPreview(RulesCase):
    def automatique(self):
        rule = new_rule("reply", "Absence")
        storage.upsert_rule(
            "perso", rule, rearm=Armed(7, 1, T0), base=self.base
        )
        self.store.rule_log_claim(rule.id, "cle-1", outcome="pending", at=T0)
        msg = build_message(
            self.account,
            CAROLE,
            "Auto: Devis",
            "Je suis absente.\nRetour lundi.",
        )
        return self.store.queue_auto(
            msg.as_bytes(),
            CAROLE,
            "Auto: Devis",
            held=True,
            rule_id=rule.id,
            source_key="cle-1",
            expires_at=T0 + 86400,
            outcome="held",
            reason="hold_first",
        )

    async def test_the_preview_shows_the_text_of_an_auto_entry(self):
        from textual.widgets import Static

        self.automatique()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "OutboxScreen")
            apercu = self.text_of(app, "#outbox_preview")
            self.assertIn(t("mail_outbox_preview"), apercu)
            self.assertIn("Je suis absente.", apercu)
            self.assertIn("Retour lundi.", apercu)
            self.assertIn(t("mail_outbox_expires"), apercu)
            lignes = " ".join(
                str(s.content)
                for s in app.screen.query(".outbox_row Static").results(Static)
            )
            self.assertIn(t("mail_outbox_auto"), lignes)

    async def test_focus_on_a_manual_entry_clears_the_preview(self):
        from textual.widgets import Button

        from script.todo.mail.tui import deliver

        auto = self.automatique()
        msg = build_message(self.account, BRUNO, "Manuel", "Corps manuel")
        deliver(Session(self.account, self.store, None, password="x"), msg)
        manuel = next(
            e["id"] for e in self.store.outbox() if e["kind"] == "manual"
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await pilot.pause()
            self.q(app, f"#hold_{auto}", Button).focus()
            await self.settle(app, pilot)
            apercu = self.text_of(app, "#outbox_preview")
            self.assertIn(f"{CAROLE} — Auto: Devis", apercu)
            self.q(app, f"#hold_{manuel}", Button).focus()
            await self.settle(app, pilot)
            self.assertEqual(self.text_of(app, "#outbox_preview"), "")

    async def test_a_manual_entry_has_no_preview(self):
        from script.todo.mail.tui import deliver

        msg = build_message(self.account, CAROLE, "Devis", "Bonjour")
        deliver(Session(self.account, self.store, None, password="x"), msg)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await self.settle(app, pilot)
            self.assertEqual(self.text_of(app, "#outbox_preview"), "")


class TestOutboxPreviewParts(unittest.TestCase):
    def test_inline_and_attached_images_are_named(self):
        from script.todo.mail.smtp_send import AttachmentPart, InlineImage
        from script.todo.mail.tui import outbox_entry_preview

        msg = build_message(
            account_from_preset("perso", OWN, "generic"),
            CAROLE,
            "Auto: x",
            "Texte",
            html='<p>x</p><img src="cid:img-1@localhost">',
            inline_images=[
                InlineImage("img-1@localhost", PNG, "image", "png", "logo.png")
            ],
            attachment_parts=[AttachmentPart(PNG, "image", "png", "plan.png")],
        )
        lignes, en_ligne, jointes = outbox_entry_preview(msg.as_bytes())
        self.assertEqual(lignes, ["Texte"])
        self.assertEqual(en_ligne, ["logo.png"])
        self.assertEqual(jointes, ["plan.png"])

    def test_garbage_does_not_raise(self):
        from script.todo.mail.tui import outbox_entry_preview

        self.assertEqual(outbox_entry_preview(b""), ([], [], []))


class TestDynamicLabelKeys(unittest.TestCase):
    def test_every_constructed_label_has_a_translation(self):
        familles = {
            "field": FIELDS,
            "op": OPS,
            "mode": MODES,
            "group": GROUP_OPS,
            "kind": ACTION_KINDS,
            "format": FORMATS,
        }
        manquantes = [
            f"mail_rules_{famille}_{valeur}"
            for famille, valeurs in familles.items()
            for valeur in valeurs
            if f"mail_rules_{famille}_{valeur}" not in TRANSLATIONS
        ]
        self.assertEqual(manquantes, [])


class TestFilterSummary(unittest.TestCase):
    def test_an_empty_all_reads_all_messages(self):
        from script.todo.mail.tui import rule_filter_summary

        self.assertEqual(
            rule_filter_summary(Group()), t("mail_rules_match_all")
        )

    def test_nested_groups_are_spelled_out(self):
        from script.todo.mail.tui import rule_filter_summary

        texte = rule_filter_summary(
            Group(
                op="any",
                children=[
                    Condition(field="from", value="*@example.net", op="glob"),
                    Group(op="not", children=[Condition("subject", "x")]),
                ],
            )
        )
        self.assertIn(t("mail_rules_group_any"), texte)
        self.assertIn(t("mail_rules_group_not"), texte)
        self.assertIn('"*@example.net"', texte)
        # Le mode n'a pas de sens pour un motif : il n'est pas écrit.
        self.assertEqual(texte.count(t("mail_rules_mode_substring_ci")), 1)


if __name__ == "__main__":
    unittest.main()
