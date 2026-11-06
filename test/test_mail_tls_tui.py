#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un certificat refusé dans le TUI : le registre des refus, l'annonce en
tête du statut, la touche `T` et son mot à taper, l'épinglage pendant
l'écriture d'un message, la reconnexion d'une session hors ligne.

L'application est montée pour de vrai (`run_test`) ; les connexions sont
des doubles. `HOME` est un dossier temporaire : `accounts.json` y vit.
"""

import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_mail_rules_hooks import Imap
from test_mail_tui_forward import ForwardCase

from script.todo.mail import accounts
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import Syncer
from script.todo.mail.smtp_send import build_message, tls
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import (
    FlushResult,
    Session,
    file_in_sent,
    flush_outbox,
)
from script.todo.todo_i18n import t

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
HOTE = "serveur.example.org"
FP_A = "ab" * 32
FP_B = "cd" * 32


def refus(
    protocol="imap",
    reason="untrusted",
    fingerprint=FP_A,
    pinned=None,
    port=993,
):
    return tls.TlsCertificateError(
        protocol=protocol,
        host=HOTE,
        port=port,
        reason=reason,
        fingerprint=fingerprint,
        pinned=pinned,
    )


class FauxSmtp:
    def quit(self):
        pass


def append_mort(*_args):
    """Un APPEND sur un lien mort."""
    raise OSError("lien mort")


class Connexions:
    """Un `connect_fn` qui rend ses issues dans l'ordre (une exception est
    levée) et note le compte reçu à chaque appel."""

    def __init__(self, *issues):
        self.issues = list(issues)
        self.appels = []

    def __call__(self, account, secret):
        self.appels.append(dict(getattr(account, "tls_pins", {}) or {}))
        issue = self.issues.pop(0) if self.issues else Imap()
        if isinstance(issue, BaseException):
            raise issue
        return issue


class TlsHomeCase(unittest.TestCase):
    """`HOME` temporaire, un compte « perso » écrit dans `accounts.json`,
    un cache en clair."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._rendre_home)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.account.imap.host = HOTE
        self.account.smtp.host = HOTE
        accounts.save([self.account])
        self.store = Store(self.account, mode="clear", base=self.base)
        self.store.open()
        self.addCleanup(self.store.close)

    def _rendre_home(self):
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

    def pins_du_fichier(self):
        return accounts.load()[0].tls_pins

    def hors_ligne(self, exc, connect_fn=None):
        return Session(
            self.account,
            self.store,
            None,
            str(exc),
            "x",
            connect_fn=connect_fn or Connexions(),
            error_kind="tls",
            exc=exc,
        )

    def en_ligne(self, connect_fn=None):
        return Session(
            self.account,
            self.store,
            Syncer(self.store, Imap()),
            password="x",
            connect_fn=connect_fn or Connexions(),
        )

    def couper(self, session):
        """Un échange sur un lien mort, dont la reprise est refusée : la
        session passe hors ligne."""

        def mort(_transport):
            raise OSError("lien mort")

        with self.assertRaises(tls.TlsCertificateError):
            session.avec_lien(mort)
        self.assertFalse(session.online)

    def manuel(self):
        msg = build_message(self.account, CAROLE, "Devis", "Bonjour")
        return self.store.queue_message(msg.as_bytes(), CAROLE, "Devis")


class TlsAppCase(TlsHomeCase, unittest.IsolatedAsyncioTestCase):
    SIZE = (120, 50)

    def setUp(self):
        TlsHomeCase.setUp(self)
        for patcheur in (
            mock.patch(
                "script.todo.mail.smtp_send.connect",
                lambda account, secret: FauxSmtp(),
            ),
            mock.patch(
                "script.todo.mail.smtp_send.send",
                lambda account, msg, transport: [CAROLE],
            ),
        ):
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def _app(self, sessions):
        import textual.app

        from script.todo.mail.tui import run_tui

        captured = []
        orig = textual.app.App.__init__

        def cap(app_self, *a, **k):
            orig(app_self, *a, **k)
            captured.append(app_self)

        textual.app.App.__init__ = cap
        try:
            run_tui(run_app=False, sessions=sessions)
        finally:
            textual.app.App.__init__ = orig
        return captured[-1]

    async def settle(self, app, pilot):
        for _ in range(4):
            await app.workers.wait_for_complete()
            await pilot.pause()

    def statut(self, app) -> str:
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)

    def question(self, app) -> str:
        from textual.widgets import Static

        return str(app.screen.query_one("#typed_hint", Static).content)

    async def taper(self, pilot, texte):
        if texte:
            await pilot.press(*list(texte))
        await pilot.press("enter")


class TestRegistry(TlsAppCase):
    async def test_a_refusal_at_startup_is_announced_with_T(self):
        exc = refus()
        app = self._app([self.hors_ligne(exc)])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            statut = self.statut(app)
            self.assertTrue(
                statut.startswith(
                    t("mail_tls_status").format(
                        account="perso", endpoint=f"{HOTE}:993"
                    )
                ),
                statut,
            )
            self.assertIn("(T)", statut)
            self.assertEqual(list(app.tls_refus.values()), [exc])

    async def test_T_asks_for_the_typed_word_with_the_fingerprint(self):
        app = self._app([self.hors_ligne(refus())])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await pilot.press("T")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "TypedConfirmScreen")
            texte = self.question(app)
        self.assertIn("perso", texte)
        self.assertIn(f"{HOTE}:993", texte)
        self.assertIn(tls.format_fingerprint(FP_A), texte)
        self.assertIn(t("mail_tls_trust_word"), texte)

    async def test_the_typed_word_pins_and_reconnects(self):
        connexions = Connexions(Imap())
        session = self.hors_ligne(refus(), connexions)
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await pilot.press("T")
            await pilot.pause()
            await self.taper(pilot, t("mail_tls_trust_word").lower())
            await self.settle(app, pilot)
            self.assertTrue(session.online)
            self.assertEqual(app.tls_refus, {})
            # La passe lancée après la reconnexion a rempli le cache.
            self.assertIsNotNone(self.store.folder_state("INBOX"))
        attendu = {f"{HOTE}:993": "sha256:" + FP_A}
        self.assertEqual(self.pins_du_fichier(), attendu)
        self.assertEqual(session.account.tls_pins, attendu)
        self.assertEqual(connexions.appels, [attendu])

    async def test_a_wrong_word_or_escape_pins_nothing(self):
        exc = refus()
        app = self._app([self.hors_ligne(exc)])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            for saisie in ("o", t("mail_confirm_risk_word"), "", None):
                with self.subTest(saisie=saisie):
                    await pilot.press("T")
                    await pilot.pause()
                    self.assertEqual(
                        type(app.screen).__name__, "TypedConfirmScreen"
                    )
                    if saisie is None:
                        await pilot.press("escape")
                    else:
                        await self.taper(pilot, saisie)
                    await self.settle(app, pilot)
                    self.assertEqual(self.pins_du_fichier(), {})
                    self.assertEqual(list(app.tls_refus.values()), [exc])
                    self.assertIn(
                        t("mail_tls_pin_declined").format(
                            endpoint=f"{HOTE}:993"
                        ),
                        self.statut(app),
                    )

    async def test_a_changed_certificate_asks_with_both_fingerprints(self):
        exc = refus(reason="changed", fingerprint=FP_B, pinned=FP_A)
        app = self._app([self.hors_ligne(exc)])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await pilot.press("T")
            await pilot.pause()
            texte = self.question(app)
        self.assertIn(tls.format_fingerprint(FP_A), texte)
        self.assertIn(tls.format_fingerprint(FP_B), texte)

    async def test_T_without_refusal_says_so(self):
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await pilot.press("T")
            await pilot.pause()
            self.assertNotEqual(
                type(app.screen).__name__, "TypedConfirmScreen"
            )
            self.assertIn(t("mail_tls_review_none"), self.statut(app))

    async def test_an_unreadable_fingerprint_is_not_offered(self):
        app = self._app([self.hors_ligne(refus(fingerprint=""))])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await pilot.press("T")
            await pilot.pause()
            self.assertNotEqual(
                type(app.screen).__name__, "TypedConfirmScreen"
            )
            self.assertIn(
                t("mail_tls_pin_unavailable").format(endpoint=f"{HOTE}:993"),
                self.statut(app),
            )

    async def test_the_help_lists_T(self):
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            touches = {b.key: b for b in app.BINDINGS}
            self.assertEqual(touches["T"].action, "review_certificate")
            await pilot.press("h")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "HelpScreen")
            self.assertIn(t("mail_help_tls"), app.screen._notes_text())

    async def test_an_smtp_refusal_from_the_outbox_is_registered(self):
        exc = refus("smtp", port=587)
        session = self.en_ligne()
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            with mock.patch(
                "script.todo.mail.tui.flush_outbox",
                return_value=FlushResult(0, 0, 1, tls_error=exc),
            ):
                app._sync_une(session)
            self.assertEqual(
                app.tls_refus, {("perso", "smtp", f"{HOTE}:587"): exc}
            )
            with mock.patch(
                "script.todo.mail.tui.flush_outbox",
                return_value=FlushResult(1, 0, 0),
            ):
                app._sync_une(session)
            self.assertEqual(app.tls_refus, {})

    async def test_a_refused_extra_link_is_registered(self):
        exc = refus()
        session = self.en_ligne()
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            rapport = session.sync()
            rapport.tls_error = exc
            with mock.patch.object(session, "sync", return_value=rapport):
                app._sync_une(session)
            self.assertEqual(list(app.tls_refus.values()), [exc])

    async def test_a_successful_sync_clears_the_imap_refusal(self):
        session = self.en_ligne()
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            app.noter_tls("perso", refus())
            app.noter_tls("perso", refus("smtp", port=587))
            app._sync_une(session)
            self.assertEqual(
                list(app.tls_refus), [("perso", "smtp", f"{HOTE}:587")]
            )

    async def test_a_refusal_in_a_rule_reply_is_registered(self):
        from script.todo.mail.rules.engine import EngineReport

        exc = refus("smtp", port=587)
        session = self.en_ligne()
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            with mock.patch(
                "script.todo.mail.rules.engine.run_pass",
                return_value=EngineReport(account="perso", tls_error=exc),
            ):
                app._run_rules([(session, object())])
            self.assertEqual(list(app.tls_refus.values()), [exc])

    async def test_pinning_an_online_session_syncs_it(self):
        session = self.en_ligne()
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            app.noter_tls("perso", refus())
            appels = []
            with mock.patch.object(
                app, "_sync", side_effect=lambda s: appels.append(list(s))
            ):
                await pilot.press("T")
                await pilot.pause()
                await self.taper(pilot, t("mail_tls_trust_word"))
                await self.settle(app, pilot)
            self.assertEqual(appels, [[session]])
        self.assertEqual(
            self.pins_du_fichier(), {f"{HOTE}:993": "sha256:" + FP_A}
        )


class TestFingerprintInStatus(TlsAppCase):
    async def test_a_fingerprint_in_the_status_is_shown_as_is(self):
        empreinte = tls.format_fingerprint("abcd" * 16)
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            app.set_status(f"perso : [bold]{empreinte}[/bold]")
            await pilot.pause()
            self.assertEqual(self.statut(app), f"perso : {empreinte}")


class TestStatusHeads(TlsAppCase):
    def retenue(self):
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import Armed, new_rule

        maintenant = int(time.time())
        rule = new_rule("reply", "Absence")
        rule.action.format = "text"
        rule.action.body = "Absente."
        storage.upsert_rule(
            "perso", rule, rearm=Armed(1, 1, maintenant - 3600), base=self.base
        )
        self.store.rule_log_claim(
            rule.id,
            "cle",
            outcome="pending",
            at=maintenant,
            fingerprint=rule.fingerprint(),
        )
        msg = build_message(self.account, CAROLE, "Auto: Devis", "Absente.")
        self.store.queue_auto(
            msg.as_bytes(),
            CAROLE,
            "Auto: Devis",
            held=True,
            rule_id=rule.id,
            source_key="cle",
            expires_at=maintenant + 86400,
            outcome="held",
            reason="hold_first",
        )

    async def test_two_syncs_without_online_session_give_the_same_status(self):
        self.retenue()
        app = self._app([self.hors_ligne(refus())])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            app._sync(app.sessions)
            premier = self.statut(app)
            app._sync(app.sessions)
            second = self.statut(app)
        self.assertEqual(premier, second)
        annonce_tls = t("mail_tls_status").format(
            account="perso", endpoint=f"{HOTE}:993"
        )
        self.assertTrue(premier.startswith(annonce_tls), premier)
        self.assertEqual(premier.count(annonce_tls), 1)
        self.assertEqual(premier.count("(o)"), 1)
        self.assertLess(premier.index("(T)"), premier.index("(o)"))

    async def test_clearing_one_announcement_keeps_the_other(self):
        self.retenue()
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            app.noter_tls("perso", refus())
            self.assertIn("(T)", self.statut(app))
            self.assertIn("(o)", self.statut(app))
            app.oublier_tls("perso", "imap")
            statut = self.statut(app)
        self.assertNotIn("(T)", statut)
        self.assertEqual(statut.count("(o)"), 1)


class TestLocking(TlsAppCase):
    async def test_noter_tls_from_a_worker_and_the_ui_does_not_hang(self):
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            sous_verrou = []
            original = app._annoncer_tetes

            def surveille():
                # Sous le verrou, l'en-tête attendrait l'interface pendant
                # que l'interface attend le verrou : noté, puis sauté, pour
                # que le test échoue au lieu de geler.
                tenu = app._tls_verrou.locked()
                sous_verrou.append(tenu)
                if not tenu:
                    original()

            app._annoncer_tetes = surveille
            fini = threading.Event()

            def fil():
                for port in range(10):
                    app.noter_tls("perso", refus(port=1000 + port))
                fini.set()

            travail = threading.Thread(target=fil, daemon=True)
            travail.start()
            for port in range(10):
                app.noter_tls("perso", refus("smtp", port=2000 + port))
                await pilot.pause()
            for _ in range(100):
                if fini.is_set():
                    break
                await pilot.pause(0.05)
            self.assertTrue(fini.is_set())
            self.assertTrue(sous_verrou)
            self.assertNotIn(True, sous_verrou)
            self.assertEqual(len(app.tls_refus), 20)


class TestCompose(TlsAppCase):
    async def ouvrir(self, app, pilot):
        from textual.widgets import Input, TextArea

        await pilot.press("c")
        await pilot.pause()
        self.assertEqual(type(app.screen).__name__, "ComposeScreen")
        app.screen.query_one("#to", Input).value = CAROLE
        app.screen.query_one("#subject", Input).value = "Devis"
        app.screen.query_one("#body", TextArea).text = "Bonjour."
        return app.screen

    def champs(self, ecran):
        from textual.widgets import Input, TextArea

        return (
            ecran.query_one("#to", Input).value,
            ecran.query_one("#cc", Input).value,
            ecran.query_one("#subject", Input).value,
            ecran.query_one("#body", TextArea).text,
        )

    def statut_ecran(self, ecran):
        from textual.widgets import Static

        return str(ecran.query_one("#compose_status", Static).content)

    async def envoyer_refuse(self, app, pilot, exc):
        with mock.patch("script.todo.mail.tui.deliver", side_effect=exc):
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)

    async def test_a_refusal_while_writing_offers_the_pin_over_the_draft(self):
        exc = refus("smtp", port=587)
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            ecran = await self.ouvrir(app, pilot)
            await self.envoyer_refuse(app, pilot, exc)
            self.assertEqual(type(app.screen).__name__, "TypedConfirmScreen")
            self.assertIs(app.screen_stack[-2], ecran)
            self.assertIn(tls.format_fingerprint(FP_A), self.question(app))
            self.assertEqual(list(app.tls_refus.values()), [exc])

    async def test_the_draft_is_intact_after_the_refusal_and_after_declining(
        self,
    ):
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            ecran = await self.ouvrir(app, pilot)
            avant = self.champs(ecran)
            await self.envoyer_refuse(app, pilot, refus("smtp", port=587))
            await pilot.press("escape")
            await self.settle(app, pilot)
            self.assertIs(app.screen, ecran)
            self.assertEqual(self.champs(ecran), avant)
            self.assertIn(t("mail_tls_compose_kept"), self.statut_ecran(ecran))
        self.assertEqual(self.pins_du_fichier(), {})

    async def test_after_pinning_ctrl_s_sends(self):
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            ecran = await self.ouvrir(app, pilot)
            await self.envoyer_refuse(app, pilot, refus("smtp", port=587))
            await self.taper(pilot, t("mail_tls_trust_word"))
            await self.settle(app, pilot)
            self.assertIs(app.screen, ecran)
            self.assertIn(
                t("mail_tls_compose_resend"), self.statut_ecran(ecran)
            )
            with mock.patch(
                "script.todo.mail.tui.deliver", return_value="parti"
            ) as envoi:
                await pilot.press("ctrl+s")
                await self.settle(app, pilot)
            envoi.assert_called_once()
            self.assertNotEqual(type(app.screen).__name__, "ComposeScreen")
            self.assertEqual(app.tls_refus, {})
        self.assertEqual(
            self.pins_du_fichier(), {f"{HOTE}:587": "sha256:" + FP_A}
        )

    async def test_a_direct_send_that_passes_clears_the_smtp_refusal(self):
        exc = refus("smtp", port=587)
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir(app, pilot)
            await self.envoyer_refuse(app, pilot, exc)
            await pilot.press("escape")
            await self.settle(app, pilot)
            self.assertEqual(list(app.tls_refus.values()), [exc])
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertNotEqual(type(app.screen).__name__, "ComposeScreen")
            self.assertEqual(app.tls_refus, {})
            self.assertNotIn("(T)", self.statut(app))
        self.assertEqual(self.pins_du_fichier(), {})

    async def test_an_unreadable_refusal_in_compose_says_so(self):
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            ecran = await self.ouvrir(app, pilot)
            await self.envoyer_refuse(
                app, pilot, refus("smtp", port=587, fingerprint="")
            )
            self.assertIs(app.screen, ecran)
            texte = self.statut_ecran(ecran)
        self.assertIn(
            t("mail_tls_pin_unavailable").format(endpoint=f"{HOTE}:587"), texte
        )
        self.assertIn(t("mail_tls_compose_kept"), texte)

    async def test_an_smtp_refusal_from_compose_is_registered(self):
        exc = refus("smtp", port=587)
        app = self._app([self.en_ligne()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir(app, pilot)
            await self.envoyer_refuse(app, pilot, exc)
            self.assertEqual(
                app.tls_refus, {("perso", "smtp", f"{HOTE}:587"): exc}
            )


class TestTrial(ForwardCase):
    async def test_a_refusal_in_a_rule_trial_is_registered(self):
        from test_mail_tui_forward import ORIGINAL
        from textual.widgets import DataTable

        exc = refus("smtp", port=587)
        self.store.write_body("INBOX", 2, ORIGINAL)
        self.forward_rule([CAROLE])
        with mock.patch("script.todo.mail.tui.deliver", side_effect=exc):
            app = self._app()
            async with app.run_test(size=self.SIZE) as pilot:
                await self.open_rules(app, pilot)
                await pilot.press("s")
                await pilot.pause()
                table = self.q(app, "#trial_messages", DataTable)
                table.focus()
                table.move_cursor(row=table.get_row_index("2"))
                await pilot.pause()
                await pilot.press("enter")
                await self.settle(app, pilot)
                await self.press(app, pilot, "#trial_send")
                await self.settle(app, pilot)
                statut = self.text_of(app, "#trial_status")
                self.assertEqual(list(app.tls_refus.values()), [exc])
        self.assertIn(str(exc), statut)


class TestReconnect(TlsHomeCase):
    def test_reconnect_builds_the_link_and_clears_the_error(self):
        imap = Imap()
        session = self.hors_ligne(refus(), Connexions(imap))
        session.reconnect()
        self.assertTrue(session.online)
        self.assertIs(session.syncer.transport, imap)
        self.assertEqual(
            (session.error, session.error_kind, session.exc), ("", "", None)
        )
        self.assertIsNotNone(session.syncer.open_transport)

    def test_reconnect_failure_changes_nothing(self):
        exc = refus()
        nouveau = refus(fingerprint=FP_B)
        session = self.hors_ligne(exc, Connexions(nouveau))
        with self.assertRaises(tls.TlsCertificateError):
            session.reconnect()
        self.assertFalse(session.online)
        self.assertIs(session.exc, exc)
        self.assertEqual(session.error_kind, "tls")

    def test_reconnect_of_an_online_session_does_nothing(self):
        connexions = Connexions()
        session = self.en_ligne(connexions)
        avant = session.syncer
        session.reconnect()
        self.assertIs(session.syncer, avant)
        self.assertEqual(connexions.appels, [])

    def test_reconnect_waits_for_the_sync_lock(self):
        connexions = Connexions(Imap())
        session = self.hors_ligne(refus(), connexions)
        verrou = threading.RLock()
        tenu, relache = threading.Event(), threading.Event()

        def tenir():
            with verrou:
                tenu.set()
                relache.wait(5)

        autre = threading.Thread(target=tenir, daemon=True)
        autre.start()
        tenu.wait(5)
        fil = threading.Thread(
            target=lambda: session.reconnect(verrou=verrou), daemon=True
        )
        fil.start()
        fil.join(0.3)
        self.assertEqual(connexions.appels, [])
        relache.set()
        fil.join(5)
        autre.join(5)
        self.assertEqual(len(connexions.appels), 1)
        self.assertTrue(session.online)

    def test_a_tls_refusal_on_link_reopen_takes_the_session_offline(self):
        exc = refus()
        connexions = Connexions(exc, Imap())
        session = self.en_ligne(connexions)

        def action(_transport):
            raise OSError("lien mort")

        with self.assertRaises(tls.TlsCertificateError):
            session.avec_lien(action)
        self.assertFalse(session.online)
        self.assertEqual(session.error_kind, "tls")
        self.assertIs(session.exc, exc)
        session.reconnect()
        self.assertTrue(session.online)


class TestOfflineMidSession(TlsHomeCase):
    """Une session coupée en cours de vie par un refus de certificat ne
    rend plus « rien » : chaque échange lève ce refus."""

    def coupee(self):
        exc = refus(reason="changed", fingerprint=FP_B, pinned=FP_A)
        session = self.en_ligne(Connexions(exc))
        self.couper(session)
        return session, exc

    def test_an_exchange_after_the_cut_raises_the_refusal(self):
        session, exc = self.coupee()
        appels = []
        with self.assertRaises(tls.TlsCertificateError) as ctx:
            session.avec_lien(appels.append)
        self.assertIs(ctx.exception, exc)
        self.assertEqual(appels, [])

    def test_a_sync_after_the_cut_raises_the_refusal(self):
        session, exc = self.coupee()
        with self.assertRaises(tls.TlsCertificateError) as ctx:
            session.sync()
        self.assertIs(ctx.exception, exc)

    def test_an_offline_session_for_another_cause_still_returns_none(self):
        session = Session(
            self.account,
            self.store,
            None,
            "réseau",
            "x",
            error_kind="network",
            exc=OSError("réseau"),
        )
        self.assertIsNone(session.avec_lien(lambda _t: 1))
        self.assertIsNone(session.sync())

    def test_the_listener_hears_the_cut_once(self):
        exc = refus()
        session = self.en_ligne(Connexions(exc))
        entendus = []
        session.on_tls = lambda protocol, err: entendus.append((protocol, err))
        self.couper(session)
        with self.assertRaises(tls.TlsCertificateError):
            session.avec_lien(lambda _t: None)
        self.assertEqual(entendus, [("imap", exc)])

    def test_a_flush_connection_that_passes_tells_the_listener(self):
        self.manuel()
        session = self.en_ligne()
        entendus = []
        session.on_tls = lambda protocol, err: entendus.append((protocol, err))
        flush_outbox(
            session,
            connect_fn=lambda a, s: FauxSmtp(),
            send_fn=lambda a, m, tr: [CAROLE],
        )
        self.assertIn(("smtp", None), entendus)


class TestOfflineMidSessionApp(TlsAppCase):
    async def test_a_refusal_while_filing_a_sent_copy_ends_the_pass_cleanly(
        self,
    ):
        exc = refus(reason="changed", fingerprint=FP_B, pinned=FP_A)
        session = self.en_ligne(Connexions(exc))
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)

            session.syncer.transport.append = append_mort
            self.manuel()
            self.assertIsNone(app._sync_une(session))
            await self.settle(app, pilot)
            self.assertFalse(session.online)
            self.assertEqual(self.store.outbox(), [])
            self.assertEqual(
                app.tls_refus, {("perso", "imap", f"{HOTE}:993"): exc}
            )
            self.assertEqual(app.session_errors["perso"], [str(exc)])

    async def test_a_refusal_met_outside_the_sync_reaches_T(self):
        exc = refus()
        session = self.en_ligne(Connexions(exc))
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            session.syncer.transport.append = append_mort
            msg = build_message(self.account, CAROLE, "Devis", "Bonjour")
            self.assertIs(file_in_sent(session, msg), exc)
            await self.settle(app, pilot)
            self.assertEqual(list(app.tls_refus.values()), [exc])
            await pilot.press("T")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "TypedConfirmScreen")
            self.assertIn(tls.format_fingerprint(FP_A), self.question(app))

    async def test_emptying_the_trash_after_the_cut_keeps_the_cache(self):
        exc = refus()
        session = self.en_ligne(Connexions(exc))
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            fid = self.store.upsert_folder("Trash", role="trash")
            self.store.upsert_messages(
                fid,
                [
                    MessageMeta(
                        uid=7,
                        date=1,
                        size=10,
                        flags="",
                        msgid="<7@example.org>",
                        frm=CAROLE,
                        to=OWN,
                        subject="Vieux",
                        snippet="",
                    )
                ],
            )
            self.couper(session)
            await asyncio.to_thread(app._vider, session, "Trash")
            await self.settle(app, pilot)
            self.assertEqual(self.store.count_messages(fid), 1)
            self.assertIn(str(exc), self.statut(app))


class TestListenerOfAnAddedAccount(TlsAppCase):
    async def test_an_account_added_in_the_client_reports_its_refusals(self):
        app = self._app([self.en_ligne()])
        exc = refus()
        ajoutee = self.en_ligne(Connexions(exc))
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            with (
                mock.patch(
                    "script.todo.mail.tui.open_session", return_value=ajoutee
                ),
                mock.patch.object(app, "_sync"),
            ):
                app._after_account_added(self.account)
                await self.settle(app, pilot)
            self.couper(ajoutee)
            await self.settle(app, pilot)
            self.assertEqual(list(app.tls_refus.values()), [exc])


class TestReopenAfterPinElsewhere(TlsAppCase):
    async def test_a_pin_set_elsewhere_reopens_the_session_at_the_next_pass(
        self,
    ):
        connexions = Connexions(Imap())
        session = self.hors_ligne(refus(), connexions)
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            # Épingles inchangées : la passe de l'ouverture ne retente rien.
            self.assertEqual(connexions.appels, [])
            accounts.pin_certificate("perso", HOTE, 993, FP_A)
            app._sync(app.sessions)
            await self.settle(app, pilot)
            self.assertTrue(session.online)
            self.assertEqual(app.tls_refus, {})
            self.assertIsNotNone(self.store.folder_state("INBOX"))
        self.assertEqual(
            connexions.appels, [{f"{HOTE}:993": "sha256:" + FP_A}]
        )

    async def test_the_reopening_itself_clears_the_refusal(self):
        session = self.hors_ligne(refus(), Connexions(Imap()))
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            accounts.pin_certificate("perso", HOTE, 993, FP_A)
            # La passe qui suit la réouverture échoue pour une autre
            # raison : le refus ne doit pas lui survivre.
            with mock.patch.object(app, "_sync_une", return_value=None):
                app._sync(app.sessions)
                await self.settle(app, pilot)
            self.assertTrue(session.online)
            self.assertEqual(app.tls_refus, {})

    async def test_a_new_refusal_after_a_pin_elsewhere_is_registered(self):
        nouveau = refus(reason="changed", fingerprint=FP_B, pinned=FP_A)
        session = self.hors_ligne(refus(), Connexions(nouveau))
        app = self._app([session])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            accounts.pin_certificate("perso", HOTE, 993, FP_A)
            app._sync(app.sessions)
            await self.settle(app, pilot)
            self.assertFalse(session.online)
            self.assertEqual(list(app.tls_refus.values()), [nouveau])
            # Une passe de plus, épingles inchangées : aucune tentative.
            app._sync(app.sessions)
            await self.settle(app, pilot)
            self.assertEqual(list(app.tls_refus.values()), [nouveau])


class TestPinRefresh(TlsHomeCase):
    def test_an_account_built_in_memory_keeps_its_pins(self):
        # `accounts.json` du HOME porte « perso » sans épingle : un compte
        # qui n'en vient pas ne doit pas le lire.
        compte = account_from_preset("perso", OWN, "generic")
        compte.tls_pins = {f"{HOTE}:993": "sha256:" + FP_A}
        connexions = Connexions(refus(), Imap())
        session = Session(
            compte,
            self.store,
            Syncer(self.store, Imap()),
            password="x",
            connect_fn=connexions,
        )
        self.couper(session)
        self.assertEqual(
            connexions.appels, [{f"{HOTE}:993": "sha256:" + FP_A}]
        )

    def test_a_pin_removed_elsewhere_stops_being_accepted(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A)
        self.account.tls_pins = {f"{HOTE}:993": "sha256:" + FP_A}
        connexions = Connexions(Imap())
        session = self.hors_ligne(refus(), connexions)
        accounts.unpin_certificate("perso", f"{HOTE}:993")
        session.reconnect()
        self.assertEqual(connexions.appels, [{}])

    def test_a_pin_added_elsewhere_is_used(self):
        connexions = Connexions(Imap())
        session = self.hors_ligne(refus(), connexions)
        accounts.pin_certificate("perso", HOTE, 993, FP_A)
        session.reconnect()
        self.assertEqual(
            connexions.appels, [{f"{HOTE}:993": "sha256:" + FP_A}]
        )

    def test_the_extra_link_rereads_the_pins(self):
        connexions = Connexions(Imap(), Imap())
        session = self.hors_ligne(refus(), connexions)
        session.reconnect()
        accounts.pin_certificate("perso", HOTE, 993, FP_A)
        session.syncer.open_transport()
        self.assertEqual(
            connexions.appels[-1], {f"{HOTE}:993": "sha256:" + FP_A}
        )


class TestFlushTls(TlsHomeCase):
    def test_flush_outbox_reports_the_first_tls_refusal(self):
        premier, second = self.manuel(), self.manuel()
        exc = refus("smtp", port=587)
        connexions = Connexions(exc, refus("smtp", port=587, fingerprint=FP_B))
        r = flush_outbox(
            self.en_ligne(),
            connect_fn=connexions,
            send_fn=lambda a, m, tr: [CAROLE],
        )
        self.assertIs(r.tls_error, exc)
        self.assertEqual(len(connexions.appels), 1)
        self.assertEqual(
            [e["id"] for e in self.store.outbox()], [premier, second]
        )

    def test_flush_outbox_without_refusal_has_no_tls_error(self):
        self.manuel()
        r = flush_outbox(
            self.en_ligne(),
            connect_fn=lambda a, s: FauxSmtp(),
            send_fn=lambda a, m, tr: [CAROLE],
        )
        self.assertIsNone(r.tls_error)
        self.assertEqual(tuple(r), (1, 0, 0))

    def test_a_manual_message_is_never_held_by_tls_refusals(self):
        ident = self.manuel()
        entree = self.store.outbox()[0]
        session = self.en_ligne()
        for _ in range(entree["max_attempts"] + 2):
            # Un texte qui commencerait par un code 5xx ne change rien : le
            # refus est transitoire par sa classe.
            exc = refus("smtp", port=587)
            exc.args = ("550 " + str(exc),)
            flush_outbox(
                session,
                connect_fn=Connexions(exc),
                send_fn=lambda a, m, tr: [CAROLE],
            )
        entree = self.store.outbox()[0]
        self.assertEqual(entree["id"], ident)
        self.assertFalse(entree["held"])
        self.assertEqual(entree["perm_attempts"], 0)


if __name__ == "__main__":
    unittest.main()
