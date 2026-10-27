#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur branché dans le TUI et le menu, sans interblocage.

Deux comptes en ligne : `_sync` les synchronise dans un pool en tenant
`_sync_lock`. Un envoi automatique fait depuis un fil du pool reprendrait
ce verrou et attendrait le fil parent, qui attend le pool. Les règles
tournent donc APRÈS la sortie du verrou, compte après compte. Les tests
lancent `_sync` dans un fil et SONDENT sa fin par `pilot.pause` : un
`join()` sur le fil de la boucle bloquerait les `set_status` du fil, qui
attendent la boucle.
"""

import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_mail_sync import FakeImapTransport

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import HeaderInfo, Syncer, SyncReport
from script.todo.mail.rules import storage
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.store import Store
from script.todo.mail.tui import Session

OWN = "boite.regles@example.org"
RELAIS = "relais.auto@example.com"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"


class Imap(FakeImapTransport):
    def __init__(self):
        super().__init__(
            {"INBOX": {"uidvalidity": 1, "messages": {}, "bodies": {}}}
        )

    def recevoir(self, uid, frm, to, recu):
        boite = self.folders["INBOX"]
        boite["messages"][uid] = HeaderInfo(
            uid=uid,
            date=recu,
            size=10,
            flags="",
            msgid=f"<{uid}.{to}>",
            frm=frm,
            to=to,
            subject="Question",
            internaldate=recu,
        )
        boite["bodies"][uid] = b"Subject: Question\r\n\r\ncorps\r\n"


class FauxSmtp:
    def quit(self):
        pass


class HooksCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.envois = []
        self.verrou_envois = threading.Lock()
        maintenant = int(time.time())
        self.sessions = []
        self.stores = []
        for nom, adresse, expediteur in (
            ("perso", OWN, CAROLE),
            ("pro", RELAIS, BRUNO),
        ):
            self.sessions.append(
                self._session(nom, adresse, expediteur, maintenant)
            )

        def envoyer(account, msg, transport):
            with self.verrou_envois:
                self.envois.append(account.name)
            return [msg["To"]]

        for patcheur in (
            mock.patch(
                "script.todo.mail.smtp_send.connect",
                lambda account, secret: FauxSmtp(),
            ),
            mock.patch("script.todo.mail.smtp_send.send", envoyer),
        ):
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def _session(self, nom, adresse, expediteur, maintenant, regle=True):
        account = account_from_preset(nom, adresse, "generic")
        store = Store(account, mode="clear", base=self.base)
        store.open()
        self.stores.append(store)
        imap = Imap()
        imap.recevoir(1, expediteur, adresse, maintenant - 60)
        if regle:
            rule = new_rule("reply", "Absence")
            rule.action.format = "text"
            rule.action.body = "Absente."
            storage.upsert_rule(
                nom,
                rule,
                rearm=Armed(1, 1, maintenant - 3600),
                base=self.base,
            )
            store.rule_log_claim(
                rule.id,
                "pre-approuvee",
                outcome="sent",
                at=maintenant - 30 * 86400,
                fingerprint=rule.fingerprint(),
            )
        return Session(account, store, Syncer(store, imap), password="x")

    def tearDown(self):
        for store in self.stores:
            try:
                store.close()
            except Exception:
                pass
        self.tmp.cleanup()
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

    def _app(self, sessions=None):
        import textual.app

        from script.todo.mail.tui import run_tui

        captured = []
        orig = textual.app.App.__init__

        def cap(app_self, *a, **k):
            orig(app_self, *a, **k)
            captured.append(app_self)

        textual.app.App.__init__ = cap
        try:
            run_tui(run_app=False, sessions=sessions or self.sessions)
        finally:
            textual.app.App.__init__ = orig
        return captured[-1]

    async def _sonder(self, pilot, fil, limite=10.0):
        debut = time.monotonic()
        while fil.is_alive() and time.monotonic() - debut < limite:
            await pilot.pause(0.05)
        return time.monotonic() - debut


class TestTwoAccountsDoNotDeadlock(HooksCase):
    async def test_a_sync_of_two_online_accounts_ends_with_one_reply_each(
        self,
    ):
        app = self._app()
        async with app.run_test() as pilot:
            fil = threading.Thread(
                target=app._sync, args=(app.sessions,), daemon=True
            )
            fil.start()
            await self._sonder(pilot, fil)
            self.assertFalse(fil.is_alive())
            await app.workers.wait_for_complete()
            await pilot.pause()
        self.assertEqual(sorted(self.envois), ["perso", "pro"])

    async def test_a_manual_send_during_the_pass_finishes_too(self):
        from textual.widgets import Input, TextArea

        app = self._app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("c")
            await pilot.pause()
            app.screen.query_one("#to", Input).value = CAROLE
            app.screen.query_one("#subject", Input).value = "Sujet"
            app.screen.query_one("#body", TextArea).text = "Corps"
            self.sessions[0].syncer.transport.recevoir(
                2, BRUNO, OWN, int(time.time()) - 5
            )
            fil = threading.Thread(
                target=app._sync, args=(app.sessions,), daemon=True
            )
            fil.start()
            await pilot.press("ctrl+s")
            duree = await self._sonder(pilot, fil)
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertFalse(fil.is_alive())
            self.assertLess(duree, 10.0)
        self.assertEqual(self.envois.count("perso"), 3)


class TestSyncHooks(HooksCase):
    async def test_sync_une_returns_its_report(self):
        app = self._app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.sessions[0].syncer.transport.recevoir(
                2, BRUNO, OWN, int(time.time()) - 5
            )
            rapport = app._sync_une(self.sessions[0])
        self.assertIsInstance(rapport, SyncReport)
        self.assertEqual([h.uid for h in rapport.inbox], [2])

    async def test_an_account_without_rules_changes_neither_status_nor_errors(
        self,
    ):
        from textual.widgets import Static

        sans = self._session(
            "calme", "denis.tri@example.org", CAROLE, 0, False
        )
        app = self._app([sans])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            rapport = sans.sync()
            app.set_status("avant")
            erreurs = {k: list(v) for k, v in app.session_errors.items()}
            app._run_rules([(sans, rapport)])
            await pilot.pause()
            statut = str(app.query_one("#status", Static).content)
            self.assertEqual(statut, "avant")
            self.assertEqual(app.session_errors, erreurs)

    async def test_the_rules_line_is_appended_to_the_status(self):
        from textual.widgets import Static

        from script.todo.todo_i18n import t

        app = self._app([self.sessions[0]])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.sessions[0].syncer.transport.recevoir(
                2, BRUNO, OWN, int(time.time()) - 5
            )
            rapport = self.sessions[0].sync()
            app.set_status("avant")
            app._run_rules([(self.sessions[0], rapport)])
            await pilot.pause()
            statut = str(app.query_one("#status", Static).content)
        self.assertTrue(statut.startswith("avant — perso : "))
        self.assertIn(t("mail_rules_status_sent"), statut)


class TestMenuSyncNow(unittest.TestCase):
    def test_run_pass_is_called_once_per_online_account(self):
        import io
        from contextlib import redirect_stdout

        import script.todo.mail.menu as menu
        from script.todo.mail.rules import engine

        comptes = [
            account_from_preset(n, a, "generic")
            for n, a in (("perso", OWN), ("pro", RELAIS), ("hors", CAROLE))
        ]

        class FakeSession:
            def __init__(self, account, online):
                self.account = account
                self.online = online
                self.error = "hors ligne"

            def sync(self):
                return SimpleNamespace(new_messages=0, errors=[], purged=[])

            def close(self):
                pass

        sessions = [
            FakeSession(comptes[0], True),
            FakeSession(comptes[1], True),
            FakeSession(comptes[2], False),
        ]
        bilan = engine.EngineReport(account="x")
        with (
            mock.patch.object(menu, "_load_accounts", return_value=comptes),
            mock.patch(
                "script.todo.mail.tui.open_sessions", return_value=sessions
            ),
            mock.patch(
                "script.todo.mail.tui.flush_outbox", return_value=(0, 0, 0)
            ),
            mock.patch.object(engine, "run_pass", return_value=bilan) as passe,
            mock.patch(
                "click.prompt", side_effect=AssertionError("aucune question")
            ),
            redirect_stdout(io.StringIO()),
        ):
            menu._sync_now(mock.MagicMock())
        self.assertEqual(passe.call_count, 2)
        appeles = [c.args[0] for c in passe.call_args_list]
        self.assertEqual(appeles, sessions[:2])
        for appel in passe.call_args_list:
            self.assertIsNone(appel.kwargs["verrou"])
            self.assertEqual(appel.kwargs["all_accounts"], comptes)

    def test_each_account_line_prints_before_slower_accounts_finish(self):
        """Le bilan d'un compte s'imprime dès qu'il est prêt : un compte
        lent (connexion qui attend son échéance) ne masque pas les
        autres."""
        import script.todo.mail.menu as menu
        from script.todo.mail.rules import engine

        comptes = [
            account_from_preset(n, a, "generic")
            for n, a in (("perso", OWN), ("pro", RELAIS))
        ]
        premier_imprime = threading.Event()

        class Sortie:
            def write(self, texte):
                if texte.startswith("perso"):
                    premier_imprime.set()
                return len(texte)

            def flush(self):
                pass

        class FakeSession:
            def __init__(self, account, attendre):
                self.account = account
                self.online = True
                self.attendre = attendre
                self.vu_avant_fin = None

            def sync(self):
                if self.attendre:
                    self.vu_avant_fin = premier_imprime.wait(10)
                return SimpleNamespace(new_messages=0, errors=[], purged=[])

            def close(self):
                pass

        rapide = FakeSession(comptes[0], False)
        lente = FakeSession(comptes[1], True)
        with (
            mock.patch.object(menu, "_load_accounts", return_value=comptes),
            mock.patch(
                "script.todo.mail.tui.open_sessions",
                return_value=[rapide, lente],
            ),
            mock.patch(
                "script.todo.mail.tui.flush_outbox", return_value=(0, 0, 0)
            ),
            mock.patch.object(
                engine, "run_pass", return_value=engine.EngineReport("x")
            ),
            redirect_stdout(Sortie()),
        ):
            menu._sync_now(mock.MagicMock())
        self.assertTrue(lente.vu_avant_fin)


if __name__ == "__main__":
    unittest.main()
