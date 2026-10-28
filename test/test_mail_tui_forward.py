#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écrans d'une règle de redirection : formulaire, essai, aperçu de la
file.

L'application est montée pour de vrai (`run_test`) sur le socle de
`test_mail_tui_rules` : HOME et cache sous des dossiers temporaires, les
règles sous la base du cache. L'autre compte configuré est fourni par un
remplacement d'`engine.other_account_addresses` : `accounts.json` n'est
jamais lu. L'essai tourne hors ligne : le message complet vient du cache,
où chaque test le dépose. Les fils de travail s'attendent par `settle`.
"""

import json
import threading
import unittest
from unittest import mock

from test_mail_send_forward import ORIGINAL as ORIGINAL_PDF
from test_mail_tui_rules import BRUNO, CAROLE, DENIS, OWN, T0, RulesCase

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import storage
from script.todo.mail.rules.model import (
    FORWARD_MAX_TARGETS,
    Armed,
    new_rule,
)
from script.todo.mail.smtp_send import (
    build_forward_attached,
    build_forward_inline,
    build_message,
    build_redirect,
)
from script.todo.todo_i18n import t

AUTRE = "relais.auto@example.com"
ORIGINAL = (
    f"From: Bruno <{BRUNO}>\r\n"
    f"To: {OWN}\r\n"
    "Subject: =?utf-8?q?R=C3=A9union?=\r\n"
    "Message-ID: <2@example.org>\r\n"
    "Date: Tue, 27 Oct 2026 10:00:00 +0000\r\n"
    "MIME-Version: 1.0\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Voici l'ordre du jour.\r\n"
).encode()


def autres_comptes():
    return mock.patch(
        "script.todo.mail.rules.engine.other_account_addresses",
        return_value=frozenset({AUTRE}),
    )


class ForwardCase(RulesCase):
    def setUp(self):
        super().setUp()
        patcheur = autres_comptes()
        patcheur.start()
        self.addCleanup(patcheur.stop)

    async def open_forward_form(self, app, pilot):
        from textual.widgets import Select

        await self.open_new_editor(app, pilot)
        self.q(app, "#rule_kind", Select).value = "forward"
        await pilot.pause()
        await self.press(app, pilot, "#reply_form")
        self.assertEqual(type(app.screen).__name__, "ForwardFormScreen")

    async def add_target(self, app, pilot, address):
        from textual.widgets import Input

        self.q(app, "#fwd_target_input", Input).value = address
        await self.press(app, pilot, "#fwd_target_add")

    def listed(self, app) -> list:
        from textual.widgets import Static

        return [
            str(s.content)
            for s in app.screen.query(".fwd_target_item Static").results(
                Static
            )
        ]

    def status(self, app) -> str:
        return self.text_of(app, "#fwd_status")

    def forward_rule(self, targets, mode="inline", body=""):
        rule = new_rule("forward", "Renvoi")
        rule.action.options.update({"targets": list(targets), "mode": mode})
        rule.action.body = body
        storage.upsert_rule("perso", rule, base=self.base)
        return rule


class TestForwardForm(ForwardCase):
    async def test_choosing_forward_unchecks_the_throttle_and_relabels_the_button(
        self,
    ):
        from textual.widgets import Button, Checkbox, Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_new_editor(app, pilot)
            self.assertTrue(self.q(app, "#rule_throttle", Checkbox).value)
            choix = self.q(app, "#rule_kind", Select)
            self.assertFalse(choix.disabled)
            choix.value = "forward"
            await pilot.pause()
            self.assertFalse(self.q(app, "#rule_throttle", Checkbox).value)
            self.assertEqual(
                str(self.q(app, "#reply_form", Button).label),
                t("mail_rules_action_forward"),
            )

    async def test_the_forward_form_adds_and_removes_targets(self):
        from textual.widgets import Button, Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, f"  {CAROLE} ")
            # Entrée dans le champ ajoute aussi ; le domaine part en ACE.
            champ = self.q(app, "#fwd_target_input", Input)
            champ.value = "bruno.filtre@filtré.example.net"
            champ.focus()
            await pilot.press("enter")
            await pilot.pause()
            await self.add_target(app, pilot, DENIS)
            self.assertEqual(
                self.listed(app),
                [CAROLE, "bruno.filtre@xn--filtr-fsa.example.net", DENIS],
            )
            self.assertEqual(champ.value, "")
            self.assertEqual(self.status(app), "")
            boutons = list(app.screen.query(".remove_target").results(Button))
            boutons[1].press()
            await pilot.pause()
            self.assertEqual(self.listed(app), [CAROLE, DENIS])

    async def test_an_invalid_target_is_refused_with_its_reason(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, "carole regle@example.org")
            self.assertIn(t("mail_rules_err_fwd_address"), self.status(app))
            self.assertEqual(self.listed(app), [])
            # Le champ est gardé pour être corrigé.
            self.assertEqual(
                self.q(app, "#fwd_target_input", Input).value,
                "carole regle@example.org",
            )

    async def test_own_and_other_account_targets_are_refused(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, OWN.upper())
            self.assertIn(t("mail_rules_err_fwd_self"), self.status(app))
            await self.add_target(app, pilot, AUTRE)
            self.assertIn(
                f"{t('mail_rules_err_fwd_other_account')} {AUTRE}",
                self.status(app),
            )
            self.assertEqual(self.listed(app), [])

    async def test_a_duplicate_target_is_refused(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, CAROLE)
            await self.add_target(app, pilot, CAROLE.upper())
            self.assertIn(t("mail_rules_err_fwd_duplicate"), self.status(app))
            self.assertEqual(self.listed(app), [CAROLE])

    async def test_the_eleventh_target_is_refused(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            for n in range(FORWARD_MAX_TARGETS):
                await self.add_target(
                    app, pilot, f"carole.regle+{n}@example.org"
                )
            self.assertEqual(self.status(app), "")
            await self.add_target(app, pilot, DENIS)
            self.assertIn(
                f"{t('mail_rules_err_fwd_too_many')} {FORWARD_MAX_TARGETS}",
                self.status(app),
            )
            self.assertEqual(len(self.listed(app)), FORWARD_MAX_TARGETS)

    async def test_the_redirect_warning_shows_only_in_redirect_mode(self):
        from textual.widgets import Select, Static

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            avis = self.q(app, "#fwd_redirect_warning", Static)
            self.assertFalse(avis.display)
            self.assertIn(
                t("mail_rules_fwd_redirect_warning"), str(avis.content)
            )
            mode = self.q(app, "#fwd_mode", Select)
            mode.value = "redirect"
            await pilot.pause()
            self.assertTrue(avis.display)
            mode.value = "attachment"
            await pilot.pause()
            self.assertFalse(avis.display)

    async def test_the_intro_is_greyed_in_redirect_mode_and_kept(self):
        from textual.widgets import Select, TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            intro = self.q(app, "#fwd_intro", TextArea)
            intro.text = "Pour suite à donner."
            await self.add_target(app, pilot, CAROLE)
            self.q(app, "#fwd_mode", Select).value = "redirect"
            await pilot.pause()
            self.assertTrue(intro.disabled)
            self.assertEqual(intro.text, "Pour suite à donner.")
            self.q(app, "#fwd_mode", Select).value = "inline"
            await pilot.pause()
            self.assertFalse(intro.disabled)
            self.q(app, "#fwd_mode", Select).value = "redirect"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            action = app.screen.rule.action
        self.assertEqual(action.body, "Pour suite à donner.")
        self.assertEqual(action.options["mode"], "redirect")

    async def test_save_without_target_is_refused(self):
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ForwardFormScreen")
            self.assertIn(t("mail_rules_err_fwd_no_target"), self.status(app))

    async def test_a_typed_but_not_added_target_blocks_the_save(self):
        from textual.widgets import Input

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, CAROLE)
            self.q(app, "#fwd_target_input", Input).value = DENIS
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "ForwardFormScreen")
            self.assertEqual(self.status(app), t("mail_rules_err_fwd_pending"))

    async def test_a_saved_forward_rule_round_trips(self):
        from textual.widgets import Checkbox, Input, Select, TextArea

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, CAROLE)
            await self.add_target(app, pilot, DENIS)
            self.q(app, "#fwd_mode", Select).value = "attachment"
            self.q(app, "#fwd_intro", TextArea).text = "Reçu pour vous."
            self.q(app, "#fwd_skip_lists", Checkbox).value = True
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.q(app, "#rule_name", Input).value = "Vers l'équipe"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
            fichier = self.rules_file()
            await pilot.press("enter")
            await pilot.pause()
            await self.press(app, pilot, "#reply_form")
            self.assertEqual(type(app.screen).__name__, "ForwardFormScreen")
            self.assertEqual(self.listed(app), [CAROLE, DENIS])
            self.assertEqual(
                self.q(app, "#fwd_mode", Select).value, "attachment"
            )
            self.assertEqual(
                self.q(app, "#fwd_intro", TextArea).text, "Reçu pour vous."
            )
            self.assertTrue(self.q(app, "#fwd_skip_lists", Checkbox).value)
        action = fichier["rules"][0]["action"]
        self.assertEqual(action["kind"], "forward")
        self.assertEqual(action["format"], "text")
        self.assertEqual(action["subject"], "")
        self.assertEqual(action["images"], [])
        self.assertEqual(action["body"], "Reçu pour vous.")
        self.assertEqual(
            action["options"],
            {
                "targets": [CAROLE, DENIS],
                "mode": "attachment",
                "skip_lists": True,
            },
        )
        self.assertFalse(fichier["rules"][0]["throttle_enabled"])

    async def test_switching_back_to_reply_drops_the_forward_options_at_save(
        self,
    ):
        from textual.widgets import Select

        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_forward_form(app, pilot)
            await self.add_target(app, pilot, CAROLE)
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "RuleEditorScreen")
            self.q(app, "#rule_kind", Select).value = "reply"
            await pilot.pause()
            # Rien n'est perdu tant que l'éditeur reste ouvert.
            self.assertEqual(
                app.screen.rule.action.options["targets"], [CAROLE]
            )
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "RulesScreen")
        action = self.rules_file()["rules"][0]["action"]
        self.assertEqual(action["kind"], "reply")
        for cle in ("targets", "mode", "skip_lists"):
            self.assertNotIn(cle, action["options"])

    async def test_hand_edited_options_open_with_their_error(self):
        rule = new_rule("forward", "Main")
        rule.action.options.update({"targets": [CAROLE], "mode": "inline"})
        storage.upsert_rule("perso", rule, base=self.base)
        brut = self.rules_file()
        brut["rules"][0]["action"]["options"]["mode"] = "copie"
        storage.rules_path("perso", self.base).write_text(json.dumps(brut))
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_rules(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            await self.press(app, pilot, "#reply_form")
            self.assertEqual(type(app.screen).__name__, "ForwardFormScreen")
            self.assertIn(t("mail_rules_err_fwd_mode"), self.status(app))
            self.assertEqual(self.listed(app), [CAROLE])


class TestForwardTrial(ForwardCase):
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

    async def test_the_trial_of_a_forward_rule_shows_targets_mode_size_and_headers(
        self,
    ):
        self.store.write_body("INBOX", 2, ORIGINAL)
        self.forward_rule([CAROLE, BRUNO], body="Pour information.")
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.open_trial(app, pilot)
            await self.choose_message(app, pilot, 2)
            resultat = self.text_of(app, "#trial_result")
        self.assertIn(
            f"{t('mail_rules_trial_fwd_mode')} "
            f"{t('mail_rules_fwd_mode_inline')}",
            resultat,
        )
        self.assertIn(
            f"{t('mail_rules_trial_fwd_targets')} {CAROLE}", resultat
        )
        self.assertIn(
            f"{t('mail_rules_trial_fwd_removed')} {BRUNO} — "
            f"{t('mail_rules_fwd_removed_sender')}",
            resultat,
        )
        self.assertIn(f"{t('mail_rules_trial_fwd_size')} 100", resultat)
        self.assertIn(t("mail_rules_trial_fwd_headers"), resultat)
        self.assertIn("Subject: Fwd: Réunion", resultat)
        self.assertIn("To: undisclosed-recipients:;", resultat)
        self.assertIn(f"Bcc: {CAROLE}", resultat)
        self.assertIn(f"Reply-To: {BRUNO}", resultat)
        self.assertIn("Voici l'ordre du jour.", resultat)
        self.assertNotIn(t("mail_rules_trial_target"), resultat)

    async def test_the_trial_send_forwards_to_oneself(self):
        from textual.widgets import Button

        self.store.write_body("INBOX", 2, ORIGINAL)
        self.forward_rule([CAROLE, DENIS])
        with mock.patch(
            "script.todo.mail.tui.deliver", return_value="parti"
        ) as espion:
            app = self._app()
            async with app.run_test(size=self.SIZE) as pilot:
                await self.open_trial(app, pilot)
                await self.choose_message(app, pilot, 2)
                self.assertFalse(self.q(app, "#trial_send", Button).disabled)
                await self.press(app, pilot, "#trial_send")
                await self.settle(app, pilot)
                statut = self.text_of(app, "#trial_status")
        espion.assert_called_once()
        msg = espion.call_args[0][1]
        self.assertEqual(msg["X-ERPLibre-Bcc"], OWN)
        self.assertNotIn(CAROLE, msg.as_string())
        self.assertNotIn(DENIS, msg.as_string())
        self.assertTrue(
            msg["Subject"].startswith(
                f"{t('mail_rules_trial_subject_prefix')} Fwd:"
            )
        )
        self.assertEqual(espion.call_args[1]["queue_offline"], False)
        self.assertIn(f"{t('mail_rules_trial_sent')} parti", statut)

    async def test_the_trial_send_is_disabled_without_the_message(self):
        from textual.widgets import Button

        self.forward_rule([CAROLE])
        with mock.patch("script.todo.mail.tui.deliver") as espion:
            app = self._app()
            async with app.run_test(size=self.SIZE) as pilot:
                await self.open_trial(app, pilot)
                await self.choose_message(app, pilot, 2)
                self.assertTrue(self.q(app, "#trial_send", Button).disabled)
                self.assertIn(
                    t("mail_rules_reason_body_unavailable"),
                    self.text_of(app, "#trial_result"),
                )
        espion.assert_not_called()


class TestForwardOutbox(ForwardCase):
    def entree(self, raw, to, subject, kind, source):
        rule = new_rule("reply", "Support")
        storage.upsert_rule(
            "perso", rule, rearm=Armed(7, 1, T0), base=self.base
        )
        self.store.rule_log_claim(rule.id, source, outcome="pending", at=T0)
        return self.store.queue_auto(
            raw,
            to,
            subject,
            held=True,
            rule_id=rule.id,
            source_key=source,
            expires_at=T0 + 86400,
            outcome="held",
            reason="hold_first",
            kind=kind,
        )

    def redirection(self):
        sortant = build_redirect(self.account, ORIGINAL, [CAROLE, DENIS])
        return self.entree(
            sortant.as_bytes(),
            ", ".join(sortant.envelope),
            sortant.subject,
            "auto_redirect",
            "cle-r",
        )

    def transfert(self, corps):
        msg = build_message(self.account, CAROLE, "Fwd: Devis", corps)
        return self.entree(
            msg.as_bytes(), CAROLE, "Fwd: Devis", "auto_forward", corps
        )

    async def test_the_outbox_preview_names_a_redirect_entry(self):
        from textual.widgets import Button

        ident = self.redirection()
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "OutboxScreen")
            self.q(app, f"#hold_{ident}", Button).focus()
            await self.settle(app, pilot)
            apercu = self.text_of(app, "#outbox_preview")
        self.assertIn(f"{CAROLE}, {DENIS} — Réunion", apercu)
        self.assertIn(t("mail_rules_outbox_redirect"), apercu)
        self.assertIn("Voici l'ordre du jour.", apercu)
        self.assertIn(t("mail_outbox_expires"), apercu)
        self.assertNotIn(t("mail_rules_outbox_loading"), apercu)

    async def test_the_outbox_preview_names_a_forward_entry(self):
        self.transfert("Texte transféré.")
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("o")
            await self.settle(app, pilot)
            apercu = self.text_of(app, "#outbox_preview")
        self.assertIn(t("mail_rules_outbox_forward"), apercu)
        self.assertIn("Texte transféré.", apercu)

    async def test_the_outbox_preview_ignores_a_stale_result(self):
        from textual.widgets import Button

        from script.todo.mail import tui

        lent = self.transfert("Premier texte.")
        rapide = self.transfert("Second texte.")
        libere = threading.Event()
        vrai = tui.outbox_entry_preview

        def apercu_lent(raw):
            # L'aperçu de la première entrée arrive après celui de la
            # seconde, demandé ensuite.
            if b"Premier" in raw:
                libere.wait(10)
            return vrai(raw)

        with mock.patch.object(
            tui, "outbox_entry_preview", side_effect=apercu_lent
        ):
            app = self._app()
            async with app.run_test(size=self.SIZE) as pilot:
                await pilot.press("o")
                await pilot.pause()
                self.q(app, f"#hold_{lent}", Button).focus()
                await pilot.pause()
                self.assertIn(
                    t("mail_rules_outbox_loading"),
                    self.text_of(app, "#outbox_preview"),
                )
                self.q(app, f"#hold_{rapide}", Button).focus()
                for _ in range(50):
                    await pilot.pause(0.02)
                    if "Second texte." in self.text_of(app, "#outbox_preview"):
                        break
                libere.set()
                await self.settle(app, pilot)
                apercu = self.text_of(app, "#outbox_preview")
        self.assertIn("Second texte.", apercu)
        self.assertNotIn("Premier texte.", apercu)


class TestForwardTrialLines(unittest.TestCase):
    """La section forward de `rule_trial_lines`, sans écran."""

    def setUp(self):
        self.account = account_from_preset("perso", OWN, "generic")

    def sim(self, preview, **champs):
        from script.todo.mail.rules.engine import Simulation

        valeurs = dict(
            rule_enabled=True,
            executable=True,
            filter_lines=[],
            matched=True,
            reason="not_armed",
            reason_if_new="send",
            target=BRUNO,
            subject="",
            rendered=None,
            error="",
            headers_complete=True,
            auth_serv_id="",
            authenticated=None,
            forward=preview,
        )
        valeurs.update(champs)
        return Simulation(**valeurs)

    def textes(self, sim):
        from script.todo.mail.tui import rule_trial_lines

        return [texte for texte, _ in rule_trial_lines(sim)]

    def test_removed_targets_are_listed_with_their_reason(self):
        from script.todo.mail.rules.engine import ForwardPreview

        lignes = self.textes(
            self.sim(
                ForwardPreview(
                    mode="attachment",
                    targets=(CAROLE,),
                    removed=((BRUNO, "sender"), (AUTRE, "other_account")),
                )
            )
        )
        self.assertIn(
            f"{t('mail_rules_trial_fwd_mode')} "
            f"{t('mail_rules_fwd_mode_attachment')}",
            lignes,
        )
        self.assertIn(f"{t('mail_rules_trial_fwd_targets')} {CAROLE}", lignes)
        self.assertIn(
            f"  {t('mail_rules_trial_fwd_removed')} {BRUNO} — "
            f"{t('mail_rules_fwd_removed_sender')}",
            lignes,
        )
        self.assertIn(
            f"  {t('mail_rules_trial_fwd_removed')} {AUTRE} — "
            f"{t('mail_rules_fwd_removed_other_account')}",
            lignes,
        )

    def test_a_redirect_preview_lists_the_resent_block(self):
        from script.todo.mail.rules.engine import ForwardPreview

        sortant = build_redirect(self.account, ORIGINAL, [OWN])
        lignes = self.textes(
            self.sim(
                ForwardPreview(
                    mode="redirect",
                    removed=((BRUNO, "sender"),),
                    size=len(ORIGINAL),
                    outgoing=sortant,
                    preview_self=True,
                    raw=ORIGINAL,
                )
            )
        )
        self.assertIn(t("mail_rules_trial_fwd_no_target"), lignes)
        self.assertIn(t("mail_rules_trial_fwd_preview_self"), lignes)
        self.assertIn(
            f"{t('mail_rules_trial_fwd_size')} {len(ORIGINAL)}", lignes
        )
        self.assertTrue(any(ln.startswith("Resent-From: ") for ln in lignes))
        self.assertTrue(any(ln.startswith("Resent-Date: ") for ln in lignes))
        self.assertIn(f"From: Bruno <{BRUNO}>", lignes)
        self.assertIn("Subject: Réunion", lignes)
        self.assertIn(t("mail_rules_trial_fwd_unchanged"), lignes)
        self.assertIn("Voici l'ordre du jour.", lignes)

    def test_no_recipient_line_for_a_forward(self):
        from script.todo.mail.rules.engine import ForwardPreview

        lignes = self.textes(
            self.sim(ForwardPreview(mode="inline", error="indisponible"))
        )
        self.assertFalse(
            any(
                ln.startswith(t("mail_rules_trial_target"))
                or ln == t("mail_rules_trial_no_target")
                for ln in lignes
            )
        )
        self.assertIn(t("mail_rules_trial_fwd_no_target"), lignes)
        self.assertEqual(lignes[-1], "indisponible")

    def test_the_send_verdict_of_a_forward_reads_would_forward(self):
        from script.todo.mail.rules.engine import ForwardPreview

        lignes = self.textes(
            self.sim(
                ForwardPreview(mode="inline", targets=(CAROLE,)),
                reason="send",
                kind="forward",
            )
        )
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_trial_would_forward')}",
            lignes,
        )
        self.assertFalse(
            any(t("mail_rules_trial_would_send") in ln for ln in lignes)
        )

    def test_no_target_of_a_forward_names_the_sender(self):
        lignes = self.textes(
            self.sim(None, reason="no_target", target="", kind="forward")
        )
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_trial_fwd_no_sender')}",
            lignes,
        )
        self.assertNotIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_reason_no_target')}",
            lignes,
        )

    def test_a_reply_rule_still_reads_would_reply(self):
        lignes = self.textes(self.sim(None, reason="send", kind="reply"))
        self.assertIn(
            f"{t('mail_rules_trial_verdict')} "
            f"{t('mail_rules_trial_would_send')}",
            lignes,
        )
        self.assertIn(f"{t('mail_rules_trial_target')} {BRUNO}", lignes)

    def test_a_forward_without_preview_names_no_recipient(self):
        erreur = "Règle invalide : mode inconnu"
        lignes = self.textes(
            self.sim(None, target=BRUNO, kind="forward", error=erreur)
        )
        self.assertFalse(
            any(
                ln.startswith(t("mail_rules_trial_target"))
                or ln == t("mail_rules_trial_no_target")
                or BRUNO in ln
                for ln in lignes
            )
        )
        self.assertEqual(lignes[-1], erreur)

    def test_an_attached_original_is_one_attachment_in_the_preview(self):
        from script.todo.mail.rules.engine import ForwardPreview
        from script.todo.mail.tui import outbox_entry_preview

        msg = build_forward_attached(self.account, ORIGINAL_PDF, [CAROLE])
        _texte, en_ligne, jointes = outbox_entry_preview(msg.as_bytes())
        self.assertEqual(jointes, ["message.eml"])
        self.assertEqual(en_ligne, [])
        lignes = self.textes(
            self.sim(
                ForwardPreview(
                    mode="attachment",
                    targets=(CAROLE,),
                    size=len(ORIGINAL_PDF),
                    outgoing=msg,
                    raw=ORIGINAL_PDF,
                ),
                reason="send",
                kind="forward",
            )
        )
        self.assertIn(
            f"  message.eml — {t('mail_rules_image_attached')}", lignes
        )
        self.assertFalse(any("devis.pdf" in ln for ln in lignes))
        self.assertFalse(any("logo.png" in ln for ln in lignes))

    def test_forward_preview_headers_of_a_forward(self):
        from script.todo.mail.tui import forward_preview_headers

        msg = build_forward_inline(
            self.account, ORIGINAL, [CAROLE, DENIS], reply_to=BRUNO
        )
        entetes = forward_preview_headers(msg)
        self.assertEqual(
            [nom for nom, _ in entetes],
            ["From", "To", "Reply-To", "Subject", "Auto-Submitted", "Bcc"],
        )
        valeurs = dict(entetes)
        self.assertEqual(valeurs["To"], "undisclosed-recipients:;")
        self.assertEqual(valeurs["Reply-To"], BRUNO)
        self.assertEqual(valeurs["Subject"], "Fwd: Réunion")
        self.assertEqual(valeurs["Auto-Submitted"], "auto-generated")
        self.assertEqual(valeurs["Bcc"], f"{CAROLE}, {DENIS}")
        self.assertIn(OWN, valeurs["From"])


class TestForwardSummary(unittest.TestCase):
    def test_a_forward_rule_reads_mode_and_targets(self):
        from script.todo.mail.tui import rule_forward_summary

        rule = new_rule("forward", "Renvoi")
        rule.action.options.update(
            {"targets": [CAROLE, DENIS], "mode": "redirect"}
        )
        self.assertEqual(
            rule_forward_summary(rule),
            f"{t('mail_rules_fwd_mode_redirect')} : {CAROLE}, {DENIS}",
        )
        self.assertEqual(rule_forward_summary(new_rule("reply")), "")
        rule.action.options["mode"] = "copie"
        self.assertIn(t("mail_rules_err_fwd_mode"), rule_forward_summary(rule))

    def test_every_constructed_forward_label_has_a_translation(self):
        from script.todo.mail.rules.model import FORWARD_MODES
        from script.todo.todo_i18n import TRANSLATIONS

        cles = [f"mail_rules_fwd_mode_{m}" for m in FORWARD_MODES] + [
            f"mail_rules_fwd_removed_{c}"
            for c in ("sender", "self", "other_account")
        ]
        self.assertEqual([c for c in cles if c not in TRANSLATIONS], [])


if __name__ == "__main__":
    unittest.main()
