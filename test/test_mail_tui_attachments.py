#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Choisir la pièce jointe à enregistrer.

`w` n'en connaissait qu'une : la première. Les autres étaient
inatteignables depuis le client, alors que l'aperçu affichait leur
nombre — un message à trois pièces jointes en montrait trois et n'en
donnait qu'une.

`w` ouvre maintenant la liste dès qu'il y en a plus d'une. À une seule, il
enregistre sans rien demander : la question aurait une réponse connue
d'avance.
"""
import email.message
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


def message_avec(pieces) -> bytes:
    """Un message dont les pièces jointes portent les noms demandés."""
    msg = email.message.EmailMessage()
    msg["From"] = "ana@e.ca"
    msg["To"] = "moi@x.ca"
    msg["Subject"] = "Dossier complet"
    msg["Message-ID"] = "<1@e.ca>"
    msg.set_content("voici les pièces")
    for nom, contenu in pieces:
        msg.add_attachment(
            contenu,
            maintype="application",
            subtype="octet-stream",
            filename=nom,
        )
    return msg.as_bytes()


class AttachmentCase(unittest.IsolatedAsyncioTestCase):
    PIECES = [
        ("devis.pdf", b"PDF-un"),
        ("plan.dwg", b"DWG-deux"),
        ("photo.jpg", b"JPG-trois"),
    ]

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
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=7,
                    date=1_780_000_000,
                    size=10,
                    flags="",
                    msgid="<1@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="Dossier complet",
                    snippet="",
                )
            ],
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def _corps(self, pieces):
        self.store.write_body("INBOX", 7, message_avec(pieces))

    async def _app(self):
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

    async def _presser_w(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()

    def _telecharges(self):
        dossier = Path(self.fake_home.name) / "Téléchargements"
        return (
            sorted(p.name for p in dossier.iterdir())
            if (dossier.exists())
            else []
        )


class TestWhenThereAreSeveral(AttachmentCase):
    async def test_the_list_opens(self):
        from textual.screen import ModalScreen

        self._corps(self.PIECES)
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            self.assertIsInstance(app.screen, ModalScreen)

    async def test_every_attachment_is_offered(self):
        """Le défaut d'origine : deux des trois étaient inatteignables."""
        self._corps(self.PIECES)
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            noms = [p.filename for p in app.screen.attachments]
            self.assertEqual(noms, ["devis.pdf", "plan.dwg", "photo.jpg"])

    async def test_the_chosen_one_is_written(self):
        from textual.widgets import DataTable

        self._corps(self.PIECES)
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            app.screen.query_one("#attach_list", DataTable).move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(self._telecharges(), ["plan.dwg"])

    async def test_giving_up_writes_nothing(self):
        self._corps(self.PIECES)
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(self._telecharges(), [])


class TestWhenThereIsOne(AttachmentCase):
    async def test_it_is_written_without_asking(self):
        """Poser la question serait une frappe de plus dont la réponse est
        connue d'avance."""
        from textual.screen import ModalScreen

        self._corps([("devis.pdf", b"PDF-un")])
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertEqual(self._telecharges(), ["devis.pdf"])


class TestWhenThereIsNone(AttachmentCase):
    async def test_it_says_so_and_opens_nothing(self):
        from textual.screen import ModalScreen

        self._corps([])
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertTrue(str(app.query_one("#status").content))

    async def test_a_body_not_downloaded_yet_is_said(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._presser_w(pilot, app)
            self.assertTrue(str(app.query_one("#status").content))
            self.assertEqual(self._telecharges(), [])


if __name__ == "__main__":
    unittest.main()
