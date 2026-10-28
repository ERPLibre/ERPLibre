#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écrans du rapport de statistiques : fenêtre `I`, formulaire d'une règle
stats, essai d'une règle (`s` dans la liste des règles).

L'application est montée pour de vrai (`run_test`) sur le socle de
`test_mail_tui_rules` : HOME et cache sous des dossiers temporaires. La
boîte de réception reçoit deux messages au cours du dernier jour clos,
dont un lu et répondu par une copie dans `Sent` deux heures plus tard ;
les chiffres attendus se lisent sur la ligne de ce jour dans les
tableaux. Les fils de travail s'attendent par `settle`.
"""

import time
import unittest
from pathlib import Path
from unittest import mock

from test_mail_tui_rules import BRUNO, CAROLE, OWN, T0, RulesCase

from script.todo.mail.imap_sync import HeaderInfo, SelectInfo
from script.todo.mail.rules import report, storage
from script.todo.mail.rules.filter import sole_address
from script.todo.mail.rules.model import (
    STATS_VARIABLES,
    Action,
    Armed,
    Condition,
    Group,
    new_rule,
)
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import rule_node_label
from script.todo.todo_i18n import t

HEURE = 3600
# Premier UID d'une demande récente : la règle armée l'attend.
NEUF = 20


def meta(uid, frm, recu, *, flags="", sujet="Question", msgid=None, **kw):
    return MessageMeta(
        uid=uid,
        date=recu,
        size=100,
        flags=flags,
        msgid=msgid or f"<{uid}@example.org>",
        frm=frm,
        to=OWN,
        subject=sujet,
        snippet="",
        received_at=recu,
        **kw,
    )


class FauxTransport:
    """Le lien IMAP d'un essai en ligne : en-têtes complets et corps."""

    def __init__(self, entetes, corps=b"", uidvalidity=7):
        self.entetes = entetes
        self.corps = corps
        self.uidvalidity = uidvalidity

    def select(self, _dossier):
        return SelectInfo(self.uidvalidity, 42, len(self.entetes))

    def fetch_headers(self, uids):
        return [h for h in self.entetes if h.uid in uids]


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport

    def fetch_body(self, _dossier, _uid):
        return self.transport.corps


class ReportCase(RulesCase):
    def setUp(self):
        super().setUp()
        self.now = int(time.time())
        # Midi local d'hier : loin des deux bords de la tranche.
        self.hier = report.day_starts(self.now, 1)[0] + 12 * HEURE
        self.etiquette_hier = time.strftime(
            "%Y-%m-%d", time.localtime(self.hier)
        )
        self.store.upsert_messages(
            self.inbox,
            [
                meta(10, CAROLE, self.hier, flags="\\Seen", sujet="Devis"),
                meta(11, BRUNO, self.hier + 60, sujet="Réunion"),
            ],
        )
        sent = self.store.upsert_folder("Sent", "Envoyés", "sent")
        self.store.upsert_messages(
            sent,
            [
                MessageMeta(
                    uid=1,
                    date=self.hier + 2 * HEURE,
                    size=100,
                    flags="\\Seen",
                    msgid="<r10@example.org>",
                    frm=OWN,
                    to=CAROLE,
                    subject="Re: Devis",
                    snippet="",
                    in_reply_to="<10@example.org>",
                    received_at=self.hier + 2 * HEURE,
                )
            ],
        )

    def ligne_hier(self, texte: str) -> list:
        """Les cellules de la ligne d'hier d'un tableau texte."""
        for ligne in texte.splitlines():
            cellules = ligne.split()
            if cellules and cellules[0] == self.etiquette_hier:
                return cellules[1:]
        self.fail(f"aucune ligne {self.etiquette_hier} dans :\n{texte}")

    async def open_settings(self, app, pilot):
        await pilot.press("I")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "ReportSettingsScreen")
        await self.settle(app, pilot)

    async def open_trial(self, app, pilot):
        await self.open_rules(app, pilot)
        await pilot.press("s")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "TrialScreen")

    async def choose_message(self, app, pilot, uid):
        from textual.widgets import DataTable

        table = self.q(app, "#trial_messages", DataTable)
        table.focus()
        table.move_cursor(row=table.get_row_index(str(uid)))
        await pilot.pause()
        await pilot.press("enter")
        await self.settle(app, pilot)

    async def open_stats_form(self, app, pilot):
        from textual.widgets import Select

        await self.open_new_editor(app, pilot)
        self.q(app, "#rule_kind", Select).value = "stats"
        await pilot.pause()
        await self.press(app, pilot, "#reply_form")
        self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")
        await self.settle(app, pilot)

    def regle(self, kind="reply", *, armee=False, **champs):
        rule = new_rule(kind, champs.pop("name", "Essai"))
        rule.filter = Group(
            children=[Condition("from", "carole", op="contains")]
        )
        for cle, valeur in champs.items():
            setattr(rule, cle, valeur)
        storage.upsert_rule(
            "perso",
            rule,
            rearm=Armed(7, NEUF, T0) if armee else None,
            base=self.base,
        )
        return rule


class TestReportSettings(ReportCase):
    async def test_shift_i_opens_the_report_settings(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            courant = app.current_meta()
            await self.open_settings(app, pilot)
            attendu = sole_address(courant.frm) if courant else ""
            self.assertEqual(
                self.q(app, "#report_requester", Input).value, attendu
            )
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotEqual(
                type(app.screen).__name__, "ReportSettingsScreen"
            )

    async def test_the_settings_load_and_show_the_timezone(self):
        from textual.widgets import Input, Select

        storage.save_report(
            "perso",
            storage.ReportSettings(
                days=5, weeks=2, lang="en", auth_serv_id="mx.example.org"
            ),
            base=self.base,
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            self.assertEqual(self.q(app, "#report_days", Input).value, "5")
            self.assertEqual(self.q(app, "#report_weeks", Input).value, "2")
            self.assertEqual(self.q(app, "#report_window", Input).value, "30")
            self.assertEqual(self.q(app, "#report_lang", Select).value, "en")
            self.assertEqual(
                self.q(app, "#report_auth_serv", Input).value,
                "mx.example.org",
            )
            self.assertIn(time.strftime("%z"), self.text_of(app, "#report_tz"))
            self.assertEqual(self.text_of(app, "#report_auth_warn"), "")

    async def test_the_preview_shows_the_daily_table(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            apercu = self.text_of(app, "#report_preview")
            self.assertIn(t("mail_stats_report_col_answered"), apercu)
            self.assertEqual(self.ligne_hier(apercu), ["2", "1", "1"])
            self.assertNotIn(CAROLE, apercu)
            self.assertNotIn("Devis", apercu)

    async def test_the_preview_uses_the_typed_requester(self):
        from textual.widgets import Input

        tete = t("mail_stats_report_requester_delay").replace("{n}", "30")
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            self.q(app, "#report_requester", Input).value = ""
            await self.press(app, pilot, "#report_refresh")
            await self.settle(app, pilot)
            self.assertNotIn(tete, self.text_of(app, "#report_preview"))
            self.q(app, "#report_requester", Input).value = CAROLE.upper()
            await self.press(app, pilot, "#report_refresh")
            await self.settle(app, pilot)
            apercu = self.text_of(app, "#report_preview")
            self.assertIn(f"{tete} 2 h", apercu)

    async def test_save_writes_the_report_key_and_keeps_the_rules(self):
        from textual.widgets import Input, Select

        self.stored(new_rule("reply", "Absence"))
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            self.q(app, "#report_days", Input).value = "10"
            self.q(app, "#report_lang", Select).value = "fr"
            self.q(app, "#report_auth_serv", Input).value = "mx.example.org"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertIn(
                t("mail_stats_report_saved"),
                self.text_of(app, "#report_status"),
            )
            self.assertEqual(type(app.screen).__name__, "ReportSettingsScreen")
        donnees = self.rules_file()
        self.assertEqual(donnees["report"]["days"], 10)
        self.assertEqual(donnees["report"]["lang"], "fr")
        self.assertEqual(donnees["report"]["auth_serv_id"], "mx.example.org")
        self.assertEqual([r["name"] for r in donnees["rules"]], ["Absence"])

    async def test_an_out_of_range_value_is_refused_and_nothing_is_written(
        self,
    ):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            for valeur in ("40", "sept"):
                self.q(app, "#report_days", Input).value = valeur
                await pilot.pause()
                await pilot.press("ctrl+s")
                await self.settle(app, pilot)
                statut = self.text_of(app, "#report_status")
                self.assertIn(t("mail_rules_err_invalid"), statut)
                self.assertIn("report.days", statut)
        self.assertFalse(storage.rules_path("perso", self.base).exists())

    async def test_an_ephemeral_account_shows_the_banner_only(self):
        from textual.css.query import NoMatches

        store = Store(self.account, mode="ephemeral", base=self.base)
        store.open()
        self.addCleanup(store.close)
        app = self._app(store)
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            self.assertIn(
                t("mail_rules_ephemeral"), self.text_of(app, "#report_banner")
            )
            with self.assertRaises(NoMatches):
                app.screen.query_one("#report_days")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
        self.assertFalse((self.base / storage.RULES_DIRNAME).exists())

    async def test_an_empty_authserv_setting_shows_the_warning(self):
        from textual.widgets import Input

        avertissement = t("mail_stats_report_auth_serv_unset")
        self.regle("stats", armee=True)
        self.store.upsert_messages(
            self.inbox, [meta(NEUF, CAROLE, self.now - 60)]
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_settings(app, pilot)
            self.assertIn(
                avertissement, self.text_of(app, "#report_auth_warn")
            )
            self.q(app, "#report_auth_serv", Input).value = "mx.example.org"
            await pilot.pause()
            self.assertEqual(self.text_of(app, "#report_auth_warn"), "")
            await pilot.press("escape")
            await pilot.pause()
            # L'essai d'une règle stats le dit aussi.
            await self.open_trial(app, pilot)
            await self.choose_message(app, pilot, NEUF)
            self.assertIn(avertissement, self.text_of(app, "#trial_result"))


class TestRuleEditorKind(ReportCase):
    async def test_choosing_stats_switches_the_throttle_default_and_the_button(
        self,
    ):
        from textual.widgets import Button, Input, Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            minutes = self.q(app, "#rule_minutes", Input)
            self.assertEqual(minutes.value, "10080")
            self.q(app, "#rule_kind", Select).value = "stats"
            await pilot.pause()
            self.assertEqual(minutes.value, "1440")
            self.assertEqual(
                str(self.q(app, "#reply_form", Button).label),
                t("mail_rules_action_stats"),
            )
            self.q(app, "#rule_kind", Select).value = "reply"
            await pilot.pause()
            self.assertEqual(minutes.value, "10080")
            self.assertEqual(
                str(self.q(app, "#reply_form", Button).label),
                t("mail_rules_action_reply"),
            )

    async def test_a_hand_set_limit_is_kept_on_a_kind_change(self):
        from textual.widgets import Input, Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.q(app, "#rule_minutes", Input).value = "60"
            await pilot.pause()
            self.q(app, "#rule_kind", Select).value = "stats"
            await pilot.pause()
            self.assertEqual(self.q(app, "#rule_minutes", Input).value, "60")

    async def test_a_new_stats_rule_gets_the_default_template_and_format(
        self,
    ):
        from textual.widgets import Input, Select, TextArea

        storage.save_report(
            "perso", storage.ReportSettings(format="html"), base=self.base
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_stats_form(app, pilot)
            self.assertEqual(
                self.q(app, "#reply_format", Select).value, "html"
            )
            self.assertEqual(
                self.q(app, "#reply_body", TextArea).text,
                t("mail_stats_default_body"),
            )
            self.assertEqual(
                self.text_of(app, "#reply_title"),
                t("mail_rules_action_stats"),
            )
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.q(app, "#rule_name", Input).value = "Rapport"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
        regle = storage.load("perso", base=self.base)[0]
        self.assertEqual(regle.action.kind, "stats")
        self.assertEqual(regle.action.format, "html")
        self.assertEqual(regle.action.body, t("mail_stats_default_body"))
        self.assertEqual(regle.throttle_minutes, 1440)

    async def test_switching_kind_replaces_an_untouched_default_body(self):
        from textual.widgets import Select

        self.stored(new_rule("stats", "Rapport"))
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.q(app, "#rule_kind", Select).value = "reply"
            await pilot.pause()
            self.assertEqual(
                app.screen.rule.action.body, new_rule("reply").action.body
            )

    async def test_a_hand_written_body_is_kept_and_refused_as_a_reply(self):
        from textual.widgets import Select

        rule = new_rule("stats", "Rapport")
        rule.action.body = "Mon texte : {{rapport}}"
        self.stored(rule)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.q(app, "#rule_kind", Select).value = "reply"
            await pilot.pause()
            self.assertEqual(
                app.screen.rule.action.body, "Mon texte : {{rapport}}"
            )
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.assertIn(
                t("mail_rules_err_template_reply_var"),
                self.text_of(app, "#rule_status"),
            )
        self.assertEqual(
            storage.load("perso", base=self.base)[0].action.kind, "stats"
        )

    async def test_a_forward_rule_shows_its_kind_greyed(self):
        from textual.widgets import Select

        self.stored(new_rule("forward", "Renvoi"))
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            choix = self.q(app, "#rule_kind", Select)
            self.assertEqual(choix.value, "forward")
            self.assertTrue(choix.disabled)


class TestStatsForm(ReportCase):
    async def test_the_stats_form_lists_the_variables(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_stats_form(app, pilot)
            liste = self.text_of(app, "#stats_vars")
            for nom in STATS_VARIABLES:
                self.assertIn("{{" + nom + "}}", liste)
            self.assertIn(t("mail_stats_var_rapport"), liste)
            self.assertIn(
                t("mail_rules_stats_preview_note"),
                self.text_of(app, "#stats_preview_note"),
            )

    async def test_insert_puts_the_variable_at_the_cursor(self):
        from textual.widgets import Select, TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_stats_form(app, pilot)
            corps = self.q(app, "#reply_body", TextArea)
            corps.text = "Avant  après"
            corps.cursor_location = (0, 6)
            self.q(app, "#stats_var_pick", Select).value = "recus_total"
            await pilot.pause()
            await self.press(app, pilot, "#stats_var_insert")
            self.assertEqual(corps.text, "Avant {{recus_total}} après")

    async def test_the_stats_form_preview_computes_real_figures(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_stats_form(app, pilot)
            apercu = self.text_of(app, "#reply_preview")
            self.assertNotIn(t("mail_stats_computing"), apercu)
            self.assertEqual(self.ligne_hier(apercu), ["2", "1", "1"])
            # Sans demandeur : ni sa ligne, ni sa valeur.
            tete = t("mail_stats_report_requester_delay").replace("{n}", "30")
            self.assertNotIn(tete, apercu)

    async def test_an_unknown_variable_blocks_the_save(self):
        from textual.widgets import TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_stats_form(app, pilot)
            self.q(app, "#reply_body", TextArea).text = "Voici {{inconnue}}"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ReplyFormScreen")
            statut = self.text_of(app, "#reply_status")
            self.assertIn(t("mail_rules_err_template_var"), statut)
            self.assertIn("{{inconnue}}", statut)

    async def test_the_reply_form_of_a_reply_rule_has_no_variables(self):
        from textual.css.query import NoMatches

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            await self.press(app, pilot, "#reply_form")
            self.assertEqual(
                self.text_of(app, "#reply_title"),
                t("mail_rules_action_reply"),
            )
            with self.assertRaises(NoMatches):
                app.screen.query_one("#stats_vars")


class TestTrial(ReportCase):
    async def test_s_opens_the_trial_with_recent_inbox_messages(self):
        from textual.widgets import Button, DataTable

        self.regle()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_trial(app, pilot)
            table = self.q(app, "#trial_messages", DataTable)
            self.assertEqual(table.row_count, 5)
            self.assertEqual(table.get_row_index("11"), 0)
            self.assertTrue(self.q(app, "#trial_send", Button).disabled)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RulesScreen")

    async def test_s_without_a_rule_does_nothing(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RulesScreen")

    async def test_the_trial_shows_filter_verdict_target_and_body(self):
        self.regle(action=Action(kind="reply", body="Bonjour, absent."))
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_trial(app, pilot)
            await self.choose_message(app, pilot, 10)
            resultat = self.text_of(app, "#trial_result")
        self.assertIn(t("mail_rules_trial_filter"), resultat)
        etiquette = rule_node_label(Condition("from", "carole", op="contains"))
        self.assertIn(f"✓ {etiquette}", resultat)
        self.assertIn(t("mail_rules_trial_match"), resultat)
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_reason_not_armed')}",
            resultat,
        )
        self.assertIn(
            f"{t('mail_rules_trial_verdict_if_new')} "
            f"{t('mail_rules_trial_would_send')}",
            resultat,
        )
        self.assertIn(f"{t('mail_rules_trial_target')} {CAROLE}", resultat)
        self.assertIn("Bonjour, absent.", resultat)
        self.assertIn(t("mail_rules_trial_headers_partial"), resultat)

    async def test_the_trial_send_button_sends_to_oneself(self):
        from textual.widgets import Button

        self.regle(action=Action(kind="reply", body="Bonjour, absent."))
        with mock.patch(
            "script.todo.mail.tui.deliver", return_value="parti"
        ) as espion:
            app = self._app()
            async with app.run_test(size=self.SIZE) as pilot:
                await self.open_trial(app, pilot)
                await self.choose_message(app, pilot, 10)
                bouton = self.q(app, "#trial_send", Button)
                self.assertFalse(bouton.disabled)
                await self.press(app, pilot, "#trial_send")
                await self.settle(app, pilot)
                statut = self.text_of(app, "#trial_status")
                # Hors du journal des règles.
                self.assertEqual(self.store.rule_log_entries(None, 10), [])
        espion.assert_called_once()
        msg = espion.call_args[0][1]
        self.assertEqual(msg["To"], OWN)
        self.assertTrue(
            msg["Subject"].startswith(t("mail_rules_trial_subject_prefix"))
        )
        self.assertIsNone(msg["In-Reply-To"])
        self.assertEqual(espion.call_args[1]["queue_offline"], False)
        self.assertIn(f"{t('mail_rules_trial_sent')} parti", statut)

    async def test_the_trial_send_is_disabled_without_a_rendering(self):
        from textual.widgets import Button

        self.regle("forward")
        with mock.patch("script.todo.mail.tui.deliver") as espion:
            app = self._app()
            async with app.run_test(size=self.SIZE) as pilot:
                await self.open_trial(app, pilot)
                await self.choose_message(app, pilot, 10)
                self.assertTrue(self.q(app, "#trial_send", Button).disabled)
                self.assertIn(
                    t("mail_rules_trial_kind"),
                    self.text_of(app, "#trial_result"),
                )
                await self.press(app, pilot, "#trial_send")
                await self.settle(app, pilot)
        espion.assert_not_called()

    async def test_literal_brackets_in_a_subject_show_in_the_trial(self):
        sujet = "[bold]Devis[/bold] [x=1]"
        self.store.upsert_messages(
            self.inbox, [meta(12, CAROLE, self.hier + 120, sujet=sujet)]
        )
        self.regle(action=Action(kind="reply", body="Absent."))
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_trial(app, pilot)
            await self.choose_message(app, pilot, 12)
            self.assertEqual(type(app.screen).__name__, "TrialScreen")
            resultat = self.text_of(app, "#trial_result")
        self.assertIn(
            f"{t('mail_rules_trial_subject')} Auto: {sujet}", resultat
        )

    async def test_the_trial_says_a_first_report_would_be_held(self):
        """En ligne : en-têtes complets relus du serveur, authentifiés
        pour le domaine du From ; le premier rapport réel est retenu."""
        self.store.upsert_messages(
            self.inbox, [meta(NEUF, CAROLE, self.now - 60)]
        )
        self.regle("stats", armee=True, name="Rapport")
        entete = HeaderInfo(
            uid=NEUF,
            date=self.now - 60,
            size=100,
            flags="",
            msgid=f"<{NEUF}@example.org>",
            frm=CAROLE,
            to=OWN,
            subject="Question",
            internaldate=self.now - 60,
            extra={
                "authentication-results": (
                    "mx.example.org; dmarc=pass header.from=example.org"
                )
            },
        )
        corps = b"Subject: Question\r\n\r\nBonjour\r\n"
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            # En ligne une fois l'application montée : aucune passe de
            # synchronisation ne part sur ce faux lien.
            app.sessions[0].syncer = FauxSyncer(FauxTransport([entete], corps))
            await self.open_trial(app, pilot)
            await self.choose_message(app, pilot, NEUF)
            resultat = self.text_of(app, "#trial_result")
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_trial_would_send')}",
            resultat,
        )
        self.assertIn(
            f"{t('mail_rules_trial_held')} {t('mail_rules_reason_hold_first')}",
            resultat,
        )
        self.assertIn(
            f"{t('mail_rules_trial_authserv')} mx.example.org", resultat
        )
        self.assertIn(t("mail_rules_trial_authenticated"), resultat)
        self.assertNotIn(t("mail_rules_trial_headers_partial"), resultat)
        # Le rapport rendu porte la ligne d'hier, pas l'adresse d'un tiers.
        self.assertEqual(self.ligne_hier(resultat), ["2", "1", "1"])
        self.assertNotIn(BRUNO, resultat)

    async def test_a_renumbered_inbox_falls_back_to_the_cache_row(self):
        """Sous une autre UIDVALIDITY, le numéro du cache peut désigner un
        autre message : ses en-têtes ne sont pas relus, l'essai prend la
        ligne du cache et le dit."""
        self.store.upsert_messages(
            self.inbox, [meta(NEUF, CAROLE, self.now - 60)]
        )
        self.regle("stats", armee=True, name="Rapport")
        autre = HeaderInfo(
            uid=NEUF,
            date=self.now - 60,
            size=100,
            flags="",
            msgid=f"<{NEUF}@example.net>",
            frm=BRUNO,
            to=OWN,
            subject="Autre message",
            internaldate=self.now - 60,
            extra={
                "authentication-results": (
                    "mx.example.org; dmarc=pass header.from=example.net"
                )
            },
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            app.sessions[0].syncer = FauxSyncer(
                FauxTransport([autre], b"", uidvalidity=8)
            )
            await self.open_trial(app, pilot)
            await self.choose_message(app, pilot, NEUF)
            resultat = self.text_of(app, "#trial_result")
        self.assertIn(t("mail_rules_trial_headers_partial"), resultat)
        self.assertIn(f"{t('mail_rules_trial_target')} {CAROLE}", resultat)
        self.assertNotIn(BRUNO, resultat)

    async def test_the_trial_without_inbox_says_so_and_lists_nothing(self):
        from textual.widgets import DataTable

        autre = Path(self.tmp.name) / "autre"
        store = Store(self.account, mode="clear", base=autre)
        store.open()
        self.addCleanup(store.close)
        store.upsert_folder("Archives", "Archives", None)
        rule = new_rule("reply", "Essai")
        storage.upsert_rule("perso", rule, base=autre)
        app = self._app(store)
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_trial(app, pilot)
            self.assertEqual(
                self.q(app, "#trial_messages", DataTable).row_count, 0
            )
            self.assertIn(
                t("mail_rules_no_inbox"), self.text_of(app, "#trial_status")
            )


class TestTrialLines(unittest.TestCase):
    """`rule_trial_lines` sans écran : ce que le menu imprime aussi."""

    def sim(self, **champs):
        from script.todo.mail.rules.engine import Simulation

        valeurs = dict(
            rule_enabled=True,
            executable=True,
            filter_lines=[],
            matched=None,
            reason="",
            reason_if_new="",
            target="",
            subject="",
            rendered=None,
            error="",
            headers_complete=True,
            auth_serv_id="",
            authenticated=None,
        )
        valeurs.update(champs)
        return Simulation(**valeurs)

    def textes(self, sim):
        from script.todo.mail.tui import rule_trial_lines

        return [texte for texte, _ in rule_trial_lines(sim)]

    def test_a_disabled_rule_is_announced_first(self):
        self.assertEqual(
            self.textes(self.sim(rule_enabled=False))[0],
            t("mail_rules_trial_disabled"),
        )

    def test_no_authserv_and_no_target_are_said(self):
        textes = self.textes(
            self.sim(authenticated=False, auth_serv_unset=True)
        )
        self.assertIn(t("mail_rules_trial_no_authserv"), textes)
        self.assertIn(t("mail_rules_trial_not_authenticated"), textes)
        self.assertIn(t("mail_stats_report_auth_serv_unset"), textes)
        self.assertIn(t("mail_rules_trial_no_target"), textes)

    def test_the_new_verdict_is_shown_only_when_it_differs(self):
        textes = self.textes(self.sim(reason="send", reason_if_new="send"))
        self.assertFalse(
            any(
                x.startswith(t("mail_rules_trial_verdict_if_new"))
                for x in textes
            )
        )

    def test_the_daily_stats_cap_is_a_verdict_not_a_hold(self):
        """Le plafond quotidien écarte la demande : rien n'arrive dans la
        file d'envoi, l'essai ne promet donc aucune retenue."""
        textes = self.textes(self.sim(reason="send", hold="stats_cap"))
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_reason_stats_cap')}",
            textes,
        )
        self.assertFalse(
            any(x.startswith(t("mail_rules_trial_held")) for x in textes)
        )
        self.assertNotIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_trial_would_send')}",
            textes,
        )

    def test_a_real_hold_keeps_its_line(self):
        textes = self.textes(self.sim(reason="send", hold="hold_first"))
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_trial_would_send')}",
            textes,
        )
        self.assertIn(
            f"{t('mail_rules_trial_held')} "
            f"{t('mail_rules_reason_hold_first')}",
            textes,
        )


if __name__ == "__main__":
    unittest.main()
