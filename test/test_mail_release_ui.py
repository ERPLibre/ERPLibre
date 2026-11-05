#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les écrans et le menu des deux gestes de libération : le bouton
Relâcher de la file `o`, la touche `r` du journal des règles `l`, et les
entrées [5] et [6] du menu du service.

Le TUI est monté pour de vrai (`run_test`) ; le moteur de libération est
remplacé par un double, sauf quand un test dit le contraire. Une question
de risque ne s'accepte qu'en tapant le mot affiché. `HOME` et les caches
sont des dossiers temporaires."""

import contextlib
import io
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_mail_outbox_release import ReleaseCase
from test_mail_rules_menu import FauxTodo
from test_mail_tui_rules import RulesCase

from script.todo.mail import menu
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import release, storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.smtp_send import build_message
from script.todo.mail.store import MessageMeta, Store, default_base
from script.todo.mail.tui import Session
from script.todo.todo_i18n import TRANSLATIONS, t

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"
T0 = 1_790_000_000
DOUBLE = "script.todo.mail.rules.release.release_held"
DOUBLE_CLAIM = "script.todo.mail.rules.release.release_claim"


def mot():
    return t("mail_confirm_risk_word")


class Appels:
    """Un double de `release_held` qui rend ses issues dans l'ordre et
    note chaque appel ; `bloque` le fait attendre."""

    def __init__(self, *issues, bloque=None, leve=None):
        self.issues = list(issues)
        self.appels = []
        self.bloque = bloque
        self.leve = leve

    def __call__(self, session, queue_id, **kw):
        self.appels.append(kw)
        if self.bloque is not None:
            self.bloque.wait(10)
        if self.leve is not None:
            raise self.leve
        return self.issues.pop(0)


class OutboxUiCase(ReleaseCase):
    async def taper(self, pilot, texte):
        if texte:
            await pilot.press(*list(texte))
        await pilot.press("enter")

    def texte_question(self, app) -> str:
        from textual.widgets import Static

        return str(app.screen.query_one("#typed_hint", Static).content)


class TestOutboxRelease(OutboxUiCase):
    async def test_the_release_button_goes_through_release_held_in_a_worker(
        self,
    ):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        double = Appels(release.HeldRelease("refused", "refus du double"))
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            with mock.patch(DOUBLE, double):
                await self.appuyer(app, pilot, ident)
            self.assertEqual(len(double.appels), 1)
            self.assertIsNone(double.appels[0]["force"])
            self.assertIs(double.appels[0]["verrou"], app._sync_lock)
            self.assertTrue(self.store.outbox_held(ident))
            self.assertEqual(self.statut(app), "refus du double")

    async def test_a_release_needing_confirmation_asks_and_sends_on_the_typed_word(
        self,
    ):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        double = Appels(
            release.HeldRelease(
                "confirm", question="QUESTION-GONE", verdict="gone"
            ),
            release.HeldRelease("released", "parti"),
        )
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            with mock.patch(DOUBLE, double):
                await self.appuyer(app, pilot, ident)
                self.assertEqual(
                    type(app.screen).__name__, "TypedConfirmScreen"
                )
                question = self.texte_question(app)
                self.assertIn("QUESTION-GONE", question)
                self.assertIn(mot(), question)
                await self.taper(pilot, mot().lower())
                await self.settle(app, pilot)
            self.assertEqual(len(double.appels), 2)
            self.assertEqual(double.appels[1]["force"], "gone")
            self.assertEqual(self.statut(app), "parti")

    async def test_enter_or_another_word_does_not_confirm_a_risky_release(
        self,
    ):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            for saisie in ("", "o", "y", "oui", "autre", None):
                with self.subTest(saisie=saisie):
                    double = Appels(
                        release.HeldRelease(
                            "confirm", question="Q", verdict="uncertain"
                        )
                    )
                    with mock.patch(DOUBLE, double):
                        await self.appuyer(app, pilot, ident)
                        if saisie is None:
                            await pilot.press("escape")
                        else:
                            await self.taper(pilot, saisie)
                        await self.settle(app, pilot)
                    self.assertEqual(len(double.appels), 1)
                    self.assertEqual(
                        self.statut(app), t("mail_outbox_release_declined")
                    )
                    self.assertEqual(type(app.screen).__name__, "OutboxScreen")
                    self.assertTrue(self.store.outbox_held(ident))

    async def test_a_second_press_during_a_release_is_ignored(self):
        from textual.widgets import Button

        rule = self.regle()
        ident = self.automatique(rule, held=True)
        attente = threading.Event()
        self.addCleanup(attente.set)
        double = Appels(release.HeldRelease("refused", "fini"), bloque=attente)
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            with mock.patch(DOUBLE, double):
                bouton = app.screen.query_one(f"#hold_{ident}", Button)
                bouton.press()
                await pilot.pause(0.1)
                self.assertTrue(bouton.disabled)
                app.screen.on_button_pressed(
                    mock.Mock(button=mock.Mock(id=f"hold_{ident}"))
                )
                app.screen.reload_outbox()
                await pilot.pause(0.1)
                self.assertTrue(
                    app.screen.query_one(f"#hold_{ident}", Button).disabled
                )
                attente.set()
                await self.settle(app, pilot)
            self.assertEqual(len(double.appels), 1)
            self.assertFalse(
                app.screen.query_one(f"#hold_{ident}", Button).disabled
            )

    async def test_a_store_failure_during_a_release_is_shown_not_raised(self):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        double = Appels(leve=sqlite3.OperationalError("database is locked"))
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            with mock.patch(DOUBLE, double):
                await self.appuyer(app, pilot, ident)
            self.assertTrue(
                self.statut(app).startswith(t("mail_outbox_release_failed"))
            )
            self.assertEqual(type(app.screen).__name__, "OutboxScreen")

    async def test_a_dropped_release_says_already_claimed_and_removes_the_line(
        self,
    ):
        """Le vrai relâchement, sur une entrée dont la ligne a une origine
        et dont le message est déjà su revendiqué ailleurs."""
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        self.store._db().execute(
            "UPDATE rule_log SET sealed_origin = ?",
            (self.store._seal("1:5"),),
        )
        self.store._db().commit()
        self.store.rule_claim_set(1, 5, "lost")
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            await self.appuyer(app, pilot, ident)
            self.assertEqual(self.envois, [])
            self.assertEqual(self.store.outbox(), [])
            self.assertNotIn(f"hold_{ident}", self.boutons(app))
            self.assertEqual(
                self.statut(app), t("mail_outbox_release_claimed_elsewhere")
            )
            self.assertEqual(
                self.store.rule_log_state(rule.id, "cle-0")["reason"],
                "claimed_elsewhere",
            )

    async def test_holding_an_entry_still_happens_at_once(self):
        rule = self.regle()
        double = Appels()
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            ident = self.automatique(rule, held=False)
            await self.ouvrir_file(app, pilot)
            with mock.patch(DOUBLE, double):
                await self.appuyer(app, pilot, ident)
            self.assertTrue(self.store.outbox_held(ident))
            self.assertEqual(double.appels, [])


class RuleLogUiCase(RulesCase):
    def setUp(self):
        super().setUp()
        self.rule = new_rule("reply", "Absence")
        self.rule.action.format = "text"
        self.rule.action.body = "Absente."
        storage.upsert_rule(
            "perso", self.rule, rearm=Armed(7, 1, T0), base=self.base
        )

    def cle(self, uid):
        return self.store.message_key(f"<{uid}@example.org>", 7, uid)

    def ligne(self, uid, outcome, reason, *, at, origin="auto", cle=None):
        self.store.rule_log_claim(
            self.rule.id,
            cle or self.cle(uid),
            outcome=outcome,
            reason=reason,
            at=at,
            sender=CAROLE,
            subject=f"Sujet {uid}",
            origin=(7, uid) if origin == "auto" else origin,
        )

    async def ouvrir_journal(self, app, pilot):
        await self.open_rules(app, pilot)
        await pilot.press("l")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "RuleLogScreen")

    def curseur_sur(self, app, cle):
        from textual.widgets import DataTable

        table = app.screen.query_one("#rules_log_table", DataTable)
        table.move_cursor(row=table.get_row_index(str(cle)))

    def ident(self, uid):
        return next(
            e["id"]
            for e in self.store.rule_log_entries()
            if e["msg_key"] == self.cle(uid)
        )

    def cellule_raison(self, app, uid) -> str:
        from textual.widgets import DataTable

        table = app.screen.query_one("#rules_log_table", DataTable)
        return str(table.get_row(str(self.ident(uid)))[3])

    async def taper(self, pilot, texte):
        if texte:
            await pilot.press(*list(texte))
        await pilot.press("enter")
        await pilot.pause()


class TestRuleLogRelease(RuleLogUiCase):
    async def test_the_rules_log_hint_shows_only_with_a_releasable_line(self):
        self.ligne(1, "sent", None, at=T0)
        self.ligne(
            2,
            "skipped",
            "claim_uncertain",
            at=T0 + 1,
            origin=None,
            cle="sans-message",
        )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            self.assertEqual(self.text_of(app, "#rules_log_hint"), "")
            self.ligne(3, "skipped", "claim_uncertain", at=T0 + 2)
            app.screen._charger()
            await pilot.pause()
            self.assertEqual(
                self.text_of(app, "#rules_log_hint"),
                t("mail_rules_log_release_hint"),
            )

    async def test_a_releasable_line_older_than_the_window_is_shown_and_announced(
        self,
    ):
        from textual.widgets import DataTable

        self.ligne(1, "skipped", "claim_uncertain", at=T0)
        for rang in range(4):
            self.store.rule_log_claim(
                self.rule.id,
                f"autre-{rang}",
                outcome="sent",
                at=T0 + 10 + rang,
            )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            app.screen.LIGNES = 3
            app.screen._charger()
            await pilot.pause()
            table = app.screen.query_one("#rules_log_table", DataTable)
            self.assertEqual(table.row_count, 4)
            self.assertEqual(table.get_row_index(str(self.ident(1))), 3)
            self.assertEqual(
                self.text_of(app, "#rules_log_hint"),
                t("mail_rules_log_release_hint"),
            )

    async def test_r_on_a_line_that_is_not_releasable_says_so(self):
        self.ligne(1, "sent", None, at=T0)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            with mock.patch(DOUBLE_CLAIM) as double:
                await pilot.press("r")
                await pilot.pause()
            double.assert_not_called()
            self.assertEqual(type(app.screen).__name__, "RuleLogScreen")
            self.assertEqual(
                self.text_of(app, "#rules_log_status"),
                t("mail_rules_release_not_releasable"),
            )

    async def test_r_on_a_line_the_release_would_refuse_says_why_without_asking(
        self,
    ):
        cas = (
            (2, (6, 2), "mail_rules_release_renumbered"),
            (3, (7, 9), "mail_rules_release_absent"),
            (1, None, "mail_rules_release_no_origin"),
        )
        for uid, origine, _cle in cas:
            self.ligne(
                uid,
                "skipped",
                "claim_uncertain",
                at=T0 + uid,
                origin=origine,
                cle=f"cle-{uid}" if origine is None else None,
            )
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            self.assertEqual(self.text_of(app, "#rules_log_hint"), "")
            for uid, origine, cle_texte in cas:
                with self.subTest(cle_texte):
                    ident = next(
                        e["id"]
                        for e in self.store.rule_log_entries()
                        if e["subject"] == f"Sujet {uid}"
                    )
                    self.curseur_sur(app, ident)
                    with mock.patch(DOUBLE_CLAIM) as double:
                        await pilot.press("r")
                        await pilot.pause()
                    double.assert_not_called()
                    self.assertEqual(
                        type(app.screen).__name__, "RuleLogScreen"
                    )
                    self.assertEqual(
                        self.text_of(app, "#rules_log_status"), t(cle_texte)
                    )
            self.assertEqual(
                {e["reason"] for e in self.store.rule_log_entries()},
                {"claim_uncertain"},
            )

    async def test_only_the_reason_of_a_releasable_line_names_the_r_key(self):
        self.ligne(1, "skipped", "claim_uncertain", at=T0)
        self.ligne(2, "skipped", "claim_uncertain", at=T0 + 1, origin=(6, 2))
        self.ligne(3, "failed", "claim_failed", at=T0 + 2)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            cle_r = t("mail_rules_log_release_key")
            self.assertEqual(
                self.cellule_raison(app, 1),
                f"{t('mail_rules_reason_claim_uncertain')} {cle_r}",
            )
            self.assertEqual(
                self.cellule_raison(app, 2),
                t("mail_rules_reason_claim_uncertain"),
            )
            self.assertEqual(
                self.cellule_raison(app, 3),
                f"{t('mail_rules_reason_claim_failed')} {cle_r}",
            )
        for code in ("claim_uncertain", "claim_failed"):
            for langue in ("fr", "en"):
                with self.subTest(code=code, langue=langue):
                    self.assertNotIn(
                        "(r)",
                        TRANSLATIONS[f"mail_rules_reason_{code}"][langue],
                    )

    async def test_releasing_from_the_rules_log_asks_then_marks_released(self):
        self.ligne(1, "sent", None, at=T0 + 5)
        self.ligne(2, "skipped", "claim_uncertain", at=T0 + 3)
        self.ligne(3, "sent", None, at=T0)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            from textual.widgets import DataTable, Static

            await self.ouvrir_journal(app, pilot)
            self.curseur_sur(app, self.ident(2))
            await pilot.press("r")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "TypedConfirmScreen")
            question = str(app.screen.query_one("#typed_hint", Static).content)
            self.assertIn(t("mail_rules_release_confirm_uncertain"), question)
            self.assertIn(mot(), question)
            await self.taper(pilot, mot())
            self.assertEqual(type(app.screen).__name__, "RuleLogScreen")
            self.assertEqual(
                self.text_of(app, "#rules_log_status"),
                t("mail_rules_release_done"),
            )
            self.assertEqual(
                self.cellule_raison(app, 2), t("mail_rules_reason_released")
            )
            table = app.screen.query_one("#rules_log_table", DataTable)
            self.assertEqual(table.get_row_index(str(self.ident(2))), 1)
            self.assertEqual(table.cursor_row, 1)
            self.assertEqual(self.store.rule_claim_state(7, 2), "released")

    async def test_releasing_a_failed_claim_asks_the_failed_question(self):
        self.ligne(2, "failed", "claim_failed", at=T0)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            from textual.widgets import Static

            await self.ouvrir_journal(app, pilot)
            await pilot.press("r")
            await pilot.pause()
            question = str(app.screen.query_one("#typed_hint", Static).content)
            self.assertIn(t("mail_rules_release_confirm_failed"), question)
            await self.taper(pilot, mot())
            self.assertEqual(
                self.store.rule_log_state(self.rule.id, self.cle(2))["reason"],
                "released",
            )

    async def test_enter_does_not_release_from_the_rules_log(self):
        self.ligne(2, "skipped", "claim_uncertain", at=T0)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            for saisie in ("", "o", "y"):
                with self.subTest(saisie=saisie):
                    await pilot.press("r")
                    await pilot.pause()
                    await self.taper(pilot, saisie)
                    self.assertEqual(
                        type(app.screen).__name__, "RuleLogScreen"
                    )
                    self.assertEqual(
                        self.text_of(app, "#rules_log_status"),
                        t("mail_rules_release_declined"),
                    )
            self.assertEqual(
                self.store.rule_log_state(self.rule.id, self.cle(2))["reason"],
                "claim_uncertain",
            )

    async def test_releasing_from_the_rules_log_when_the_rules_are_busy_says_so(
        self,
    ):
        self.ligne(2, "skipped", "claim_uncertain", at=T0)
        app = self._app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.ouvrir_journal(app, pilot)
            await pilot.press("r")
            await pilot.pause()
            with file_lock(
                storage.lock_path("perso", self.base), wait=0
            ) as tenu:
                self.assertTrue(tenu)
                with mock.patch.object(release, "RELEASE_LOCK_WAIT_S", 0):
                    await self.taper(pilot, mot())
            self.assertEqual(
                self.text_of(app, "#rules_log_status"), t("mail_rules_busy")
            )
            self.assertEqual(
                self.store.rule_log_state(self.rule.id, self.cle(2))["reason"],
                "claim_uncertain",
            )


class ServiceMenuCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcheur = mock.patch.dict(os.environ, {"HOME": self.home.name})
        patcheur.start()
        self.addCleanup(patcheur.stop)
        # La base par défaut, sous le HOME temporaire : le menu du service
        # l'ouvre sans qu'on la lui passe.
        self.base = default_base()
        self.base.mkdir(parents=True)
        self.comptes = []
        patcheur = mock.patch.object(
            menu, "_load_accounts", lambda: list(self.comptes)
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)
        self.sessions = []

    def compte(self, nom):
        account = account_from_preset(nom, OWN, "generic")
        account.cache_mode = "clear"
        self.comptes.append(account)
        store = Store(account, mode="clear", base=self.base)
        store.open()
        self.addCleanup(store.close)
        rule = new_rule("reply", "Absence")
        rule.action.format = "text"
        rule.action.body = "Absente."
        storage.upsert_rule(nom, rule, rearm=Armed(7, 1, T0), base=self.base)
        return account, store, rule

    def retenue(self, store, rule, account, sujet="Devis", expires_at=None):
        cle = f"cle-{sujet}"
        store.rule_log_claim(
            rule.id,
            cle,
            outcome="pending",
            at=T0,
            fingerprint=rule.fingerprint(),
        )
        msg = build_message(account, CAROLE, sujet, "Absente pour la semaine.")
        return store.queue_auto(
            msg.as_bytes(),
            CAROLE,
            sujet,
            held=True,
            rule_id=rule.id,
            source_key=cle,
            expires_at=expires_at or int(time.time()) + 3600,
            outcome="held",
            reason="hold_first",
        )

    def ouvrir_session(self, account, secrets, base=None, config_get=None):
        store = Store(account, mode="clear", base=self.base)
        store.open()
        session = Session(account, store, None, password="x")
        self.sessions.append(session)
        return session

    def lancer(self, fonction, choix, reponses, **kw):
        """`fonction` du menu avec ces choix (`click.prompt`) et ces
        réponses (`input`) ; rend ce qui a été imprimé."""
        sortie = io.StringIO()
        reponses = list(reponses)
        self.invites = []

        def saisir(invite=""):
            self.invites.append(invite)
            return reponses.pop(0)

        with (
            mock.patch.object(menu.click, "prompt", side_effect=list(choix)),
            mock.patch("builtins.input", saisir),
            contextlib.redirect_stdout(sortie),
        ):
            fonction(FauxTodo(), **kw)
        return sortie.getvalue()

    def mot_demande(self) -> bool:
        """Vrai si une invite a affiché le mot à taper."""
        return any(mot() in invite for invite in self.invites)

    def held(self, choix, reponses):
        return self.lancer(
            menu._service_held,
            choix,
            reponses,
            open_session_fn=self.ouvrir_session,
            base=self.base,
        )

    def claims(self, choix, reponses):
        return self.lancer(
            menu._service_claims, choix, reponses, base=self.base
        )


class TestServiceMenuHeld(ServiceMenuCase):
    def test_the_service_menu_lists_held_sends_of_every_account(self):
        a, sa, ra = self.compte("perso")
        b, sb, rb = self.compte("travail")
        self.retenue(sa, ra, a, "Devis")
        self.retenue(sb, rb, b, "Facture")
        self.retenue(sb, rb, b, "Expiree", expires_at=int(time.time()) - 60)
        sortie = self.held(["0"], [])
        lignes = sortie.splitlines()
        self.assertEqual(len(lignes), 2)
        self.assertTrue(lignes[0].startswith("[1] perso — Devis — "))
        self.assertTrue(lignes[1].startswith("[2] travail — Facture — "))
        self.assertIn(t("mail_rules_reason_hold_first"), lignes[0])

    def test_the_service_menu_previews_then_releases_after_yes(self):
        a, sa, ra = self.compte("perso")
        ident = self.retenue(sa, ra, a)
        double = Appels(release.HeldRelease("released", "PARTI"))
        with mock.patch(DOUBLE, double):
            sortie = self.held(["1"], ["o"])
        self.assertIn(t("mail_outbox_preview"), sortie)
        self.assertIn("Absente pour la semaine.", sortie)
        self.assertIn("PARTI", sortie)
        self.assertEqual(len(double.appels), 1)
        self.assertIsNone(double.appels[0].get("force"))
        self.assertTrue(
            all(
                s.store is None or s.store._conn is None for s in self.sessions
            )
        )
        self.assertTrue(sa.outbox_held(ident))

    def test_the_service_menu_releases_nothing_on_no(self):
        a, sa, ra = self.compte("perso")
        self.retenue(sa, ra, a)
        double = Appels()
        with mock.patch(DOUBLE, double):
            self.held(["1"], [""])
        self.assertEqual(double.appels, [])

    def test_the_service_menu_asks_again_before_a_forced_release(self):
        a, sa, ra = self.compte("perso")
        self.retenue(sa, ra, a)
        for saisie, attendu in ((mot(), 2), ("o", 1)):
            with self.subTest(saisie=saisie):
                double = Appels(
                    release.HeldRelease(
                        "confirm", question="QUESTION-GONE", verdict="gone"
                    ),
                    release.HeldRelease("released", "PARTI"),
                )
                with mock.patch(DOUBLE, double):
                    sortie = self.held(["1"], ["o", saisie])
                self.assertIn("QUESTION-GONE", sortie)
                self.assertTrue(self.mot_demande())
                self.assertEqual(len(double.appels), attendu)
                if attendu == 2:
                    self.assertEqual(double.appels[1]["force"], "gone")
                    self.assertIn("PARTI", sortie)
                else:
                    self.assertIn(t("mail_outbox_release_declined"), sortie)

    def test_the_service_menu_asks_again_when_the_verdict_changed(self):
        a, sa, ra = self.compte("perso")
        self.retenue(sa, ra, a)
        double = Appels(
            release.HeldRelease("confirm", question="Q-GONE", verdict="gone"),
            release.HeldRelease(
                "confirm", question="Q-UNCERTAIN", verdict="uncertain"
            ),
            release.HeldRelease("released", "PARTI"),
        )
        with mock.patch(DOUBLE, double):
            sortie = self.held(["1"], ["o", mot(), mot()])
        self.assertIn("Q-GONE", sortie)
        self.assertIn("Q-UNCERTAIN", sortie)
        self.assertEqual(
            [a.get("force") for a in double.appels],
            [None, "gone", "uncertain"],
        )
        self.assertIn("PARTI", sortie)

    def test_the_service_menu_says_when_nothing_is_held_or_releasable(self):
        self.compte("perso")
        self.assertIn(t("mail_service_held_none"), self.held([], []))
        self.assertIn(t("mail_service_claims_none"), self.claims([], []))

    def test_an_unknown_number_releases_nothing(self):
        a, sa, ra = self.compte("perso")
        self.retenue(sa, ra, a)
        double = Appels()
        with mock.patch(DOUBLE, double):
            sortie = self.held(["7"], [])
        self.assertIn(t("Command not found !"), sortie)
        self.assertEqual(double.appels, [])


class TestServiceMenuClaims(ServiceMenuCase):
    def incertain(self, store, rule):
        fid = store.upsert_folder("INBOX", uidvalidity=7)
        store.upsert_messages(
            fid,
            [
                MessageMeta(
                    uid=3,
                    date=T0,
                    size=10,
                    flags="$ErpLibreRule",
                    msgid="<3@example.org>",
                    frm=CAROLE,
                    to=OWN,
                    subject="Question",
                    snippet="",
                )
            ],
        )
        cle = store.message_key("<3@example.org>", 7, 3)
        store.rule_log_claim(
            rule.id,
            cle,
            outcome="skipped",
            reason="claim_uncertain",
            at=T0,
            sender=CAROLE,
            subject="Question",
            origin=(7, 3),
        )
        store.rule_claim_intent(7, 3)
        return cle

    def test_the_service_menu_releases_an_uncertain_claim_after_the_warning(
        self,
    ):
        _a, store, rule = self.compte("perso")
        cle = self.incertain(store, rule)
        sortie = self.claims(["1"], [mot()])
        self.assertIn("[1] perso — ", sortie)
        self.assertIn(t("mail_rules_release_confirm_uncertain"), sortie)
        self.assertTrue(self.mot_demande())
        self.assertIn(t("mail_rules_release_done"), sortie)
        etat = store.rule_log_state(rule.id, cle)
        self.assertEqual(
            (etat["outcome"], etat["reason"]), ("skipped", "released")
        )
        self.assertEqual(store.rule_claim_state(7, 3), "released")

    def test_a_line_the_release_would_refuse_is_not_listed(self):
        _a, store, rule = self.compte("perso")
        cle = self.incertain(store, rule)
        store._db().execute("UPDATE folders SET uidvalidity = 8")
        store._db().commit()
        sortie = self.claims([], [])
        self.assertIn(t("mail_service_claims_none"), sortie)
        self.assertEqual(
            store.rule_log_state(rule.id, cle)["reason"], "claim_uncertain"
        )

    def test_a_line_refused_after_the_listing_says_why_without_asking(self):
        _a, store, rule = self.compte("perso")
        cle = self.incertain(store, rule)
        sortie = io.StringIO()
        invites = []

        def choisir(*_a, **_k):
            # Entre la liste et le choix, le message quitte INBOX.
            store._db().execute("DELETE FROM messages")
            store._db().commit()
            return "1"

        def saisir(invite=""):
            invites.append(invite)
            return mot()

        with (
            mock.patch.object(menu.click, "prompt", side_effect=choisir),
            mock.patch("builtins.input", saisir),
            contextlib.redirect_stdout(sortie),
        ):
            menu._service_claims(FauxTodo(), base=self.base)
        self.assertIn(t("mail_rules_release_absent"), sortie.getvalue())
        self.assertNotIn(
            t("mail_rules_release_confirm_uncertain"), sortie.getvalue()
        )
        self.assertEqual(invites, [])
        self.assertEqual(
            store.rule_log_state(rule.id, cle)["reason"], "claim_uncertain"
        )

    def test_a_claim_release_needs_the_typed_word(self):
        _a, store, rule = self.compte("perso")
        cle = self.incertain(store, rule)
        for saisie in ("", "o", "oui"):
            with self.subTest(saisie=saisie):
                sortie = self.claims(["1"], [saisie])
                self.assertIn(t("mail_rules_release_declined"), sortie)
                self.assertEqual(
                    store.rule_log_state(rule.id, cle)["reason"],
                    "claim_uncertain",
                )


class TestServiceMenuEntries(ServiceMenuCase):
    def test_the_held_lines_point_to_the_new_menu_entry(self):
        textes = TRANSLATIONS["mail_service_menu_held"]
        self.assertIn("[5]", textes["fr"])
        self.assertIn("dernière passe", textes["fr"])
        self.assertIn("[5]", textes["en"])
        self.assertIn("last pass", textes["en"])

    def test_the_sync_hint_names_the_service_menu_of_the_mail_menu(self):
        for langue in ("fr", "en"):
            self.assertIn(
                "[7] › [5]",
                TRANSLATIONS["mail_outbox_held_auto_menu_hint"][langue],
            )

    def test_a_failure_in_a_service_entry_stays_in_the_menu(self):
        from script.todo.mail import service

        a, sa, ra = self.compte("perso")
        self.retenue(sa, ra, a)
        sortie = io.StringIO()
        double = Appels(leve=sqlite3.OperationalError("database is locked"))
        ouvrir = Store.open
        refus = []

        def refuse_au_menu_six(store_self):
            if refus:
                raise sqlite3.OperationalError("disk I/O error")
            return ouvrir(store_self)

        def session(account, secrets, base=None, config_get=None):
            ouverte = self.ouvrir_session(account, secrets)
            refus.append(1)
            return ouverte

        with (
            mock.patch.object(service, "status", return_value=None),
            mock.patch.object(service, "status_text", return_value="ÉTAT"),
            mock.patch.object(
                menu.click, "prompt", side_effect=["5", "1", "6", "0"]
            ),
            mock.patch("builtins.input", side_effect=["o"]),
            mock.patch("script.todo.mail.tui.open_session", session),
            mock.patch.object(Store, "open", refuse_au_menu_six),
            mock.patch(DOUBLE, double),
            contextlib.redirect_stdout(sortie),
        ):
            menu._service_menu(FauxTodo())
        texte = sortie.getvalue()
        self.assertEqual(len(double.appels), 1)
        self.assertIn(f"{t('mail_rules_error')} OperationalError", texte)
        self.assertIn(f"perso : {t('mail_rules_error')} disk I/O error", texte)
        self.assertIn(t("mail_service_claims_none"), texte)
        self.assertTrue(all(s.store._conn is None for s in self.sessions))


if __name__ == "__main__":
    unittest.main()
