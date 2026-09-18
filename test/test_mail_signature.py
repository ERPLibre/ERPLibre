#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La signature : un texte par compte, au bas de ce qu'on écrit.

Elle arrive dans le FORMULAIRE, pas au dernier moment : ajoutée à l'envoi,
personne ne l'aurait relue, et une signature fausse part alors sans que son
auteur l'ait vue une seule fois.

Le délimiteur est « -- » suivi d'une espace puis d'un saut de ligne. Cette
espace n'est pas une coquille : c'est elle qui fait du délimiteur ce qu'il
est, et les clients s'en servent pour replier ou griser ce qui suit.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import Account, account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


class SignatureCase(unittest.IsolatedAsyncioTestCase):
    SIGNATURE = "Ana Tremblay\nCoopérative du Nord"

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def _message(self):
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=7,
                    date=1_780_000_000,
                    size=10,
                    flags="",
                    msgid="<7@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="Question",
                    snippet="",
                )
            ],
        )
        self.store.write_body(
            "INBOX",
            7,
            b"From: ana@e.ca\r\nTo: moi@x.ca\r\nSubject: Question\r\n"
            b"Message-ID: <7@e.ca>\r\n\r\nune question\r\n",
        )

    async def _app(self, signature=""):
        import textual.app

        from script.todo.mail.tui import run_tui

        self.account.signature = signature
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
                    Session(self.account, self.store, None, password="x")
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

    def _corps(self, app):
        from textual.widgets import TextArea

        return app.screen.query_one("#body", TextArea).text


class TestWritingANewMessage(SignatureCase):
    async def test_the_signature_is_already_there(self):
        app = await self._app(self.SIGNATURE)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            self.assertIn("Ana Tremblay", self._corps(app))

    async def test_the_delimiter_keeps_its_trailing_space(self):
        """Sans cette espace, ce ne sont plus que deux tirets : les clients
        cessent de reconnaître une signature."""
        app = await self._app(self.SIGNATURE)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            self.assertIn("\n-- \n", self._corps(app))

    async def test_an_account_without_one_gets_nothing(self):
        app = await self._app("")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            self.assertEqual(self._corps(app).strip(), "")


class TestReplying(SignatureCase):
    async def test_the_signature_follows_the_quoted_text(self):
        self._message()
        app = await self._app(self.SIGNATURE)
        async with app.run_test() as pilot:
            app.select_ref(app.current_ref)
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            corps = self._corps(app)
            self.assertIn("Ana Tremblay", corps)
            self.assertLess(corps.index("une question"), corps.index("-- "))


class TestTheFieldItself(unittest.TestCase):
    def test_it_defaults_to_nothing(self):
        compte = account_from_preset("perso", "moi@x.ca", "generic")
        self.assertEqual(compte.signature, "")

    def test_it_survives_a_round_trip(self):
        compte = account_from_preset("perso", "moi@x.ca", "generic")
        compte.signature = "Ana\nCoop"
        self.assertEqual(
            Account.from_dict(compte.to_dict()).signature, "Ana\nCoop"
        )

    def test_a_file_written_before_it_existed_still_loads(self):
        """Un compte écrit par une version qui ignorait le champ garde tout
        le reste : le défaut est ce que cette version-là faisait."""
        compte = account_from_preset("perso", "moi@x.ca", "generic")
        vieux = {k: v for k, v in compte.to_dict().items() if k != "signature"}
        self.assertEqual(Account.from_dict(vieux).signature, "")

    def test_it_is_not_a_secret_and_stays_in_the_file(self):
        """Contrairement au mot de passe : une signature se lit dans le
        courriel envoyé, la cacher au coffre ne protégerait rien."""
        compte = account_from_preset("perso", "moi@x.ca", "generic")
        compte.signature = "Ana"
        self.assertIn("signature", compte.to_dict())


if __name__ == "__main__":
    unittest.main()
