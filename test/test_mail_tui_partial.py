#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Refus partiel des destinataires, à l'écran du client.

Ce que ces tests figent : l'écran `o` dit qu'une entrée est un nouvel
essai, dans sa ligne et dans son aperçu ; le journal `l` et la liste des
règles montrent l'issue `partial` avec le nombre de refusés et leurs codes,
jamais leurs adresses ; la ligne d'état d'une vidange compte les départs
partiels et les nouveaux essais, et lit encore un triplet nu.
"""

import unittest
from unittest import mock

from test_mail_tui_rules import CAROLE, OWN, T0, RulesCase

from script.todo.mail.rules import storage
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.smtp_send import build_message
from script.todo.mail.tui import FlushResult
from script.todo.todo_i18n import t

TEMP = "refus.temporaire@example.net"
DEF = "refus.definitif@example.net"


class PartialTuiCase(RulesCase):
    def regle(self):
        rule = new_rule("forward", "Renvoi")
        rule.action.options.update(targets=[CAROLE, TEMP, DEF], mode="inline")
        storage.upsert_rule(
            "perso", rule, rearm=Armed(7, 1, T0), base=self.base
        )
        return rule

    def partiel(self, rule, *, retry=True):
        """Une ligne partie en partie ; avec `retry`, TEMP attend dans une
        entrée de nouvel essai. Rend l'identifiant de l'entrée, ou None."""
        self.store.rule_log_claim(
            rule.id,
            "cle-1",
            outcome="pending",
            at=T0,
            sender=OWN,
            subject="Devis",
        )
        msg = build_message(self.account, CAROLE, "Tr: Devis", "Bonjour.")
        res = self.store.rule_log_rcpt_result(
            rule.id,
            "cle-1",
            total=3,
            dropped=(550,),
            pending=(450,) if retry else (),
            sent_at=T0,
            retry_raw=msg.as_bytes() if retry else None,
            retry_to=TEMP if retry else "",
            retry_subject="Tr: Devis",
            kind="auto_forward",
            expires_at=T0 + 86400,
        )
        return res.queue_id

    def detail(self):
        return t("mail_rules_rcpt_detail").format(
            refused=2, total=3, codes="450, 550"
        )


class TestPartialScreens(PartialTuiCase):
    async def test_the_outbox_marks_a_retry_entry_in_its_line_and_preview(
        self,
    ):
        from textual.widgets import Button, Static

        essai = self.partiel(self.regle())
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await pilot.pause()
            self.q(app, f"#hold_{essai}", Button).focus()
            await self.settle(app, pilot)
            lignes = " ".join(
                str(s.content)
                for s in app.screen.query(".outbox_row Static").results(Static)
            )
            self.assertIn(t("mail_outbox_retry"), lignes)
            self.assertIn(TEMP, lignes)
            apercu = self.text_of(app, "#outbox_preview")
            self.assertIn(t("mail_outbox_retry"), apercu)

    async def test_an_ordinary_outbox_entry_says_nothing_of_a_retry(self):
        from textual.widgets import Static

        rule = self.regle()
        self.store.rule_log_claim(rule.id, "cle-2", outcome="pending", at=T0)
        msg = build_message(self.account, CAROLE, "Tr: Devis", "Bonjour.")
        self.store.queue_auto(
            msg.as_bytes(),
            CAROLE,
            "Tr: Devis",
            held=True,
            rule_id=rule.id,
            source_key="cle-2",
            expires_at=T0 + 86400,
            outcome="held",
            reason="hold_first",
            kind="auto_forward",
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await self.settle(app, pilot)
            lignes = " ".join(
                str(s.content)
                for s in app.screen.query(".outbox_row Static").results(Static)
            )
            self.assertNotIn(t("mail_outbox_retry"), lignes)
            self.assertNotIn(
                t("mail_outbox_retry"), self.text_of(app, "#outbox_preview")
            )

    async def test_the_rules_log_shows_partial_with_the_refused_count(self):
        from textual.widgets import DataTable

        self.partiel(self.regle())
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("l")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleLogScreen")
            ligne = self.q(app, "#rules_log_table", DataTable).get_row_at(0)
            texte = [str(getattr(c, "plain", c)) for c in ligne]
            self.assertEqual(texte[2], t("mail_rules_outcome_partial"))
            self.assertEqual(
                texte[3],
                f"{t('mail_rules_reason_rcpt_retry')} — {self.detail()}",
            )
            for adresse in (TEMP, DEF):
                self.assertNotIn(adresse, " ".join(texte))

    async def test_the_rule_list_last_result_shows_partial(self):
        from textual.widgets import DataTable

        rule = self.regle()
        self.partiel(rule, retry=False)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            dernier = (
                self.q(app, "#rules_table", DataTable)
                .get_row(rule.id)[5]
                .plain
            )
            self.assertIn(t("mail_rules_outcome_partial"), dernier)
            self.assertIn(t("mail_rules_reason_rcpt_refused"), dernier)
            self.assertIn(
                t("mail_rules_rcpt_detail").format(
                    refused=1, total=3, codes="550"
                ),
                dernier,
            )


class TestSyncStatus(PartialTuiCase):
    async def statuts(self, rendu):
        """Les textes passés à `set_status` par `_sync_une` quand la
        vidange rend `rendu`."""
        app = self._app()
        vus = []
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            vrai = app.set_status

            def noter(texte):
                vus.append(str(texte))
                vrai(texte)

            with (
                mock.patch.object(app, "set_status", noter),
                mock.patch(
                    "script.todo.mail.tui.flush_outbox", return_value=rendu
                ),
                mock.patch.object(
                    app.sessions[0], "sync", side_effect=OSError("hors ligne")
                ),
                self.assertLogs(level="ERROR"),
            ):
                app._sync_une(app.sessions[0])
        return vus

    async def test_the_sync_status_counts_partial_sends_and_retries(self):
        vus = await self.statuts(
            FlushResult(
                3, 0, 1, partial=1, refused=2, retried=1, served=[TEMP]
            )
        )
        attendu = (
            f"{t('mail_outbox_flushed')} 3"
            f" — {t('mail_outbox_partial')} 1"
            f" — {t('mail_outbox_retried')} 1"
            f" — {t('mail_outbox_failed')} 1"
        )
        self.assertIn(attendu, vus)
        self.assertFalse(any(TEMP in v for v in vus))

    async def test_the_sync_status_still_reads_a_plain_triple(self):
        vus = await self.statuts((2, 0, 0))
        self.assertIn(f"{t('mail_outbox_flushed')} 2", vus)


if __name__ == "__main__":
    unittest.main()
