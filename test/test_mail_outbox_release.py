#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Relâcher une entrée de la file l'envoie aussitôt ; une entrée retenue
s'annonce dans le statut.

Le bouton Relâcher de l'écran `o` envoie l'entrée dans un fil de travail,
par `flush_outbox` limitée à cette entrée : réservation, contrôles de la
règle, journal et classement dans Envoyés restent les siens, et une
vidange concurrente qui a réservé l'entrée l'envoie seule. Après chaque
passe des règles, la ligne de statut du TUI et le menu [3] disent combien
d'envois automatiques attendent d'être relâchés.

L'application est montée pour de vrai (`run_test`) sur un IMAP simulé ;
SMTP est remplacé au niveau du module `smtp_send`.
"""

import io
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_mail_rules_hooks import Imap

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import Syncer
from script.todo.mail.rules import storage
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.smtp_send import build_message
from script.todo.mail.store import Store
from script.todo.mail.tui import (
    Session,
    flush_outbox,
    held_auto_counts,
    held_auto_text,
    send_released,
)
from script.todo.todo_i18n import t

OWN = "boite.relache@example.org"
CAROLE = "carole.relache@example.net"
BRUNO = "bruno.relache@example.com"


class FauxSmtp:
    def quit(self):
        pass


class ReleaseCase(unittest.IsolatedAsyncioTestCase):
    SIZE = (120, 50)

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.maintenant = int(time.time())
        self.account = account_from_preset("perso", OWN, "generic")
        self.store = Store(self.account, mode="clear", base=self.base)
        self.store.open()
        self.imap = Imap()
        self.envois = []
        self.verrou_envois = threading.Lock()
        # Remplacé par un test pour simuler un serveur qui refuse.
        self.connexion = lambda account, secret: FauxSmtp()

        def envoyer(account, msg, transport):
            with self.verrou_envois:
                self.envois.append(msg)
            return [msg["To"]]

        for patcheur in (
            mock.patch(
                "script.todo.mail.smtp_send.connect",
                lambda account, secret: self.connexion(account, secret),
            ),
            mock.patch("script.todo.mail.smtp_send.send", envoyer),
        ):
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        self.tmp.cleanup()
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

    def session(self, online=True):
        syncer = Syncer(self.store, self.imap) if online else None
        return Session(self.account, self.store, syncer, password="x")

    def regle(self, approuvee=False):
        """Une règle de réponse armée ; `approuvee` lui donne un envoi
        réel passé, qui lève la retenue du premier envoi."""
        rule = new_rule("reply", "Absence")
        rule.action.format = "text"
        rule.action.body = "Absente."
        storage.upsert_rule(
            "perso",
            rule,
            rearm=Armed(1, 1, self.maintenant - 3600),
            base=self.base,
        )
        if approuvee:
            self.store.rule_log_claim(
                rule.id,
                "pre-approuvee",
                outcome="sent",
                at=self.maintenant - 30 * 86400,
                fingerprint=rule.fingerprint(),
            )
        return rule

    def automatique(self, rule, *, held=True, expires_at=None):
        cle = f"cle-{len(self.store.outbox())}"
        self.store.rule_log_claim(
            rule.id,
            cle,
            outcome="pending",
            at=self.maintenant,
            fingerprint=rule.fingerprint(),
        )
        msg = build_message(self.account, CAROLE, "Auto: Devis", "Absente.")
        return self.store.queue_auto(
            msg.as_bytes(),
            CAROLE,
            "Auto: Devis",
            held=held,
            rule_id=rule.id,
            source_key=cle,
            expires_at=expires_at or self.maintenant + 86400,
            outcome="held" if held else "queued",
            reason="hold_first" if held else "offline",
        )

    def manuel(self, sujet="Devis"):
        msg = build_message(self.account, BRUNO, sujet, "Bonjour")
        return self.store.queue_message(msg.as_bytes(), BRUNO, sujet)

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
        await app.workers.wait_for_complete()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    def statut(self, app) -> str:
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)

    async def ouvrir_file(self, app, pilot):
        from script.todo.mail.tui import MailboxRef

        app.current_ref = MailboxRef(
            account_name="perso",
            folder_name="INBOX",
            display="Boîte",
            unseen=0,
        )
        await pilot.press("o")
        await self.settle(app, pilot)
        self.assertEqual(type(app.screen).__name__, "OutboxScreen")

    async def appuyer(self, app, pilot, ident):
        from textual.widgets import Button

        app.screen.query_one(f"#hold_{ident}", Button).press()
        await self.settle(app, pilot)

    def boutons(self, app) -> list:
        from textual.widgets import Button

        return [
            b.id
            for b in app.screen.query(Button).results(Button)
            if str(b.id or "").startswith("hold_")
        ]


class TestHeldAutoCount(ReleaseCase):
    def test_only_held_automatic_entries_count(self):
        rule = self.regle()
        self.automatique(rule, held=True)
        self.automatique(rule, held=False)
        manuel = self.manuel()
        self.store.set_held(manuel, True)
        self.assertEqual(self.store.outbox_auto_held_count(), 1)

    def test_an_expired_entry_is_not_counted_with_now(self):
        rule = self.regle()
        self.automatique(rule, expires_at=self.maintenant - 10)
        self.assertEqual(self.store.outbox_auto_held_count(), 1)
        self.assertEqual(
            self.store.outbox_auto_held_count(now=self.maintenant), 0
        )

    def test_counts_per_account_and_plural(self):
        rule = self.regle()
        self.automatique(rule)
        self.automatique(rule)
        self.assertEqual(held_auto_counts([self.session()]), [("perso", 2)])
        self.assertEqual(
            held_auto_text(1), t("mail_outbox_held_auto_one").format(n=1)
        )
        self.assertEqual(
            held_auto_text(2), t("mail_outbox_held_auto_many").format(n=2)
        )
        self.assertNotEqual(
            t("mail_outbox_held_auto_one"), t("mail_outbox_held_auto_many")
        )


class TestFlushOnlyIds(ReleaseCase):
    def test_only_the_named_entry_leaves(self):
        premier = self.manuel("Premier")
        second = self.manuel("Second")
        partis = flush_outbox(self.session(), only_ids=[second])
        self.assertEqual(partis, (1, 0, 0))
        self.assertEqual([m["Subject"] for m in self.envois], ["Second"])
        self.assertEqual([e["id"] for e in self.store.outbox()], [premier])


class TestSendReleased(ReleaseCase):
    def test_a_released_auto_reply_leaves_and_is_logged_sent(self):
        rule = self.regle()
        ident = self.automatique(rule, held=False)
        statut = send_released(self.session(), ident)
        self.assertEqual(statut, f"{t('mail_sent_to')} {CAROLE}")
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_outcome(rule.id, "cle-0"), "sent")
        self.assertEqual(len(self.imap.appended), 1)

    def test_offline_keeps_the_entry(self):
        rule = self.regle()
        ident = self.automatique(rule, held=False)
        statut = send_released(self.session(online=False), ident)
        self.assertEqual(statut, t("mail_outbox_release_offline"))
        self.assertEqual([e["id"] for e in self.store.outbox()], [ident])
        self.assertEqual(self.envois, [])

    def test_a_transient_failure_keeps_the_entry_and_says_why(self):
        def refuse(account, secret):
            raise OSError("421 serveur occupé")

        self.connexion = refuse
        rule = self.regle()
        ident = self.automatique(rule, held=False)
        statut = send_released(self.session(), ident)
        self.assertTrue(statut.startswith(t("mail_outbox_release_failed")))
        self.assertIn("421 serveur occupé", statut)
        self.assertEqual([e["id"] for e in self.store.outbox()], [ident])

    def test_a_disabled_rule_drops_the_entry_without_sending(self):
        rule = self.regle()
        ident = self.automatique(rule, held=False)
        rule.enabled = False
        storage.upsert_rule("perso", rule, base=self.base)
        statut = send_released(self.session(), ident)
        self.assertEqual(statut, t("mail_outbox_release_dropped"))
        self.assertEqual(self.envois, [])
        self.assertEqual(self.store.outbox(), [])

    def test_held_again_before_leaving_sends_nothing(self):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        statut = send_released(self.session(), ident)
        self.assertEqual(statut, t("mail_outbox_release_held"))
        self.assertEqual(self.envois, [])


class TestConcurrentFlush(ReleaseCase):
    def test_a_release_during_a_flush_does_not_send_twice(self):
        """Une vidange de passe tient la réservation pendant son envoi :
        l'envoi du relâchement n'envoie rien, l'entrée part une fois."""
        rule = self.regle()
        ident = self.automatique(rule, held=False)
        dans_envoi = threading.Event()
        continuer = threading.Event()
        lent = []

        def envoi_lent(account, msg, transport):
            lent.append(msg)
            dans_envoi.set()
            continuer.wait(10)
            return [CAROLE]

        fil = threading.Thread(
            target=flush_outbox,
            args=(self.session(),),
            kwargs={"send_fn": envoi_lent},
            daemon=True,
        )
        fil.start()
        self.assertTrue(dans_envoi.wait(10))
        statut = send_released(self.session(), ident)
        continuer.set()
        fil.join(10)
        self.assertEqual(statut, t("mail_outbox_release_waiting"))
        self.assertEqual(len(lent), 1)
        self.assertEqual(self.envois, [])
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_outcome(rule.id, "cle-0"), "sent")

    def test_a_flush_that_sends_before_the_reread_says_sent(self):
        """La vidange concurrente finit son envoi entre la vidange de
        celui-ci, qui ne peut pas réserver, et la relecture de la file :
        le statut dit l'envoi, pas un retrait."""
        import script.todo.mail.tui as tui

        rule = self.regle()
        ident = self.automatique(rule, held=False)
        dans_envoi = threading.Event()
        continuer = threading.Event()

        def envoi_lent(account, msg, transport):
            dans_envoi.set()
            continuer.wait(10)
            return [CAROLE]

        fil = threading.Thread(
            target=flush_outbox,
            args=(self.session(),),
            kwargs={"send_fn": envoi_lent},
            daemon=True,
        )
        fil.start()
        self.assertTrue(dans_envoi.wait(10))
        originale = tui.flush_outbox

        def puis_finir(*a, **k):
            resultat = originale(*a, **k)
            continuer.set()
            fil.join(10)
            return resultat

        with mock.patch.object(tui, "flush_outbox", puis_finir):
            statut = send_released(self.session(), ident)
        self.assertEqual(statut, f"{t('mail_sent_to')} {CAROLE}")
        self.assertEqual(self.store.outbox(), [])

    def test_sent_before_the_first_read_says_sent(self):
        rule = self.regle()
        ident = self.automatique(rule, held=False)
        lue = self.store.outbox()[0]
        self.assertEqual(flush_outbox(self.session()), (1, 0, 0))
        statut = send_released(self.session(), ident, entree=lue)
        self.assertEqual(statut, f"{t('mail_sent_to')} {CAROLE}")

    def test_a_manual_entry_gone_elsewhere_is_not_called_dropped(self):
        ident = self.manuel()
        lue = self.store.outbox()[0]
        self.assertEqual(flush_outbox(self.session()), (1, 0, 0))
        statut = send_released(self.session(), ident, entree=lue)
        self.assertEqual(statut, t("mail_outbox_release_gone"))


class TestOutboxScreenRelease(ReleaseCase):
    async def test_release_sends_at_once_and_the_entry_disappears(self):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(self.envois, [])
            await self.ouvrir_file(app, pilot)
            self.assertIn(f"hold_{ident}", self.boutons(app))
            await self.appuyer(app, pilot, ident)
            self.assertEqual(len(self.envois), 1)
            self.assertEqual(self.store.outbox(), [])
            self.assertNotIn(f"hold_{ident}", self.boutons(app))
            self.assertEqual(self.statut(app), f"{t('mail_sent_to')} {CAROLE}")
            self.assertEqual(
                self.store.rule_log_outcome(rule.id, "cle-0"), "sent"
            )

    async def test_release_offline_keeps_the_entry(self):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        app = self._app([self.session(online=False)])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            await self.appuyer(app, pilot, ident)
            self.assertEqual(self.envois, [])
            entrees = self.store.outbox()
            self.assertEqual([e["id"] for e in entrees], [ident])
            self.assertFalse(entrees[0]["held"])
            self.assertIn(f"hold_{ident}", self.boutons(app))
            self.assertEqual(
                self.statut(app), t("mail_outbox_release_offline")
            )

    async def test_holding_again_sends_nothing(self):
        rule = self.regle()
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            # Mise en file après la passe d'ouverture, qui l'aurait vidée.
            ident = self.automatique(rule, held=False)
            await self.ouvrir_file(app, pilot)
            await self.appuyer(app, pilot, ident)
            self.assertEqual(self.envois, [])
            self.assertTrue(self.store.outbox_held(ident))

    async def test_an_entry_claimed_by_a_pass_is_not_sent_twice(self):
        rule = self.regle()
        ident = self.automatique(rule, held=True)
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            await self.ouvrir_file(app, pilot)
            # Une vidange de passe a réservé l'entrée et l'envoie.
            self.assertTrue(self.store.outbox_claim(ident, int(time.time())))
            await self.appuyer(app, pilot, ident)
            self.assertEqual(self.envois, [])
            self.assertEqual([e["id"] for e in self.store.outbox()], [ident])
            self.assertEqual(
                self.statut(app), t("mail_outbox_release_waiting")
            )


class TestHeldAnnouncement(ReleaseCase):
    async def _passe(self, app, pilot):
        fil = threading.Thread(
            target=app._sync, args=(app.sessions,), daemon=True
        )
        fil.start()
        debut = time.monotonic()
        while fil.is_alive() and time.monotonic() - debut < 10:
            await pilot.pause(0.05)
        self.assertFalse(fil.is_alive())
        await self.settle(app, pilot)

    async def test_a_pass_that_holds_says_so_first(self):
        self.regle()
        self.imap.recevoir(1, CAROLE, OWN, self.maintenant - 60)
        app = self._app([self.session()])
        annonce = f"perso : {held_auto_text(1)} (o)"
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(self.store.outbox_auto_held_count(), 1)
            self.assertTrue(self.statut(app).startswith(annonce))
            self.assertIn(t("mail_rules_status_held"), self.statut(app))
            # Une passe suivante la remet en tête, sans la redoubler.
            await self._passe(app, pilot)
            self.assertTrue(self.statut(app).startswith(annonce))
            self.assertEqual(self.statut(app).count(annonce), 1)

    async def test_the_announcement_is_shown_at_opening(self):
        rule = self.regle()
        self.automatique(rule)
        self.automatique(rule)
        app = self._app([self.session(online=False)])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(
                self.statut(app), f"perso : {held_auto_text(2)} (o)"
            )

    async def test_the_announcement_leaves_when_nothing_is_held(self):
        rule = self.regle()
        ident = self.automatique(rule)
        app = self._app([self.session(online=False)])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(
                self.statut(app), f"perso : {held_auto_text(1)} (o)"
            )
            self.store.set_held(ident, False)
            await self._passe(app, pilot)
            self.assertEqual(self.statut(app), "")

    async def test_no_announcement_without_a_held_entry(self):
        self.regle(approuvee=True)
        self.imap.recevoir(1, CAROLE, OWN, self.maintenant - 60)
        app = self._app([self.session()])
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(len(self.envois), 1)
            self.assertIn(t("mail_rules_status_sent"), self.statut(app))
            self.assertNotIn(held_auto_text(1), self.statut(app))
            self.assertNotIn("(o)", self.statut(app))


class TestMenuSyncAnnouncement(ReleaseCase):
    def _sync_now(self):
        import script.todo.mail.menu as menu

        sortie = io.StringIO()
        with (
            mock.patch.object(
                menu, "_load_accounts", return_value=[self.account]
            ),
            mock.patch(
                "script.todo.mail.tui.open_sessions",
                return_value=[self.session()],
            ),
            redirect_stdout(sortie),
        ):
            menu._sync_now(mock.MagicMock())
        return sortie.getvalue()

    def test_a_held_reply_prints_one_line_for_the_account(self):
        self.regle()
        self.imap.recevoir(1, CAROLE, OWN, self.maintenant - 60)
        sortie = self._sync_now()
        ligne = (
            f"perso : {held_auto_text(1)}"
            f" — {t('mail_outbox_held_auto_menu_hint')}"
        )
        self.assertIn(ligne, sortie.splitlines())
        self.assertEqual(self.envois, [])

    def test_nothing_held_prints_no_line(self):
        self.regle(approuvee=True)
        self.imap.recevoir(1, CAROLE, OWN, self.maintenant - 60)
        sortie = self._sync_now()
        self.assertEqual(len(self.envois), 1)
        self.assertNotIn(t("mail_outbox_held_auto_menu_hint"), sortie)


if __name__ == "__main__":
    unittest.main()
