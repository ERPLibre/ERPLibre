#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écran de statistiques du client courriel, touche `i`.

Le calcul est vérifié sans interface dans `test_mail_stats.py`. Ce fichier
ne couvre que ce qui exige un écran monté : la touche qui ouvre, celle qui
ferme, les filtres, et le fait que des adresses tirées des messages
n'atteignent jamais l'analyseur de balisage.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session

JOUR = 86400
DEPART = 1_780_000_000


class StatsScreenCase(unittest.IsolatedAsyncioTestCase):
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
        self.store.upsert_folder("Archives", "Archives", None)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def remplir(self, frm="Ana <ana@e.ca>"):
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=1,
                    date=DEPART,
                    size=1000,
                    flags="",
                    msgid="<o@e.ca>",
                    frm=frm,
                    to="moi@x.ca",
                    subject="s",
                    snippet="",
                ),
                MessageMeta(
                    uid=2,
                    date=DEPART + 2 * JOUR,
                    size=2000,
                    flags="\\Seen",
                    msgid="<r@e.ca>",
                    frm="moi@x.ca",
                    to=frm,
                    subject="Re",
                    snippet="",
                    in_reply_to="<o@e.ca>",
                ),
            ],
        )

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

    async def _ouvrir(self, pilot, app):
        await pilot.press("i")
        await pilot.pause()

    def _corps(self, app):
        from textual.widgets import Static

        return str(app.screen.query_one("#stats_body", Static).content)

    def _entete(self, app):
        from textual.widgets import Static

        return str(app.screen.query_one("#stats_head", Static).content)


class TestOpensAndCloses(StatsScreenCase):
    async def test_i_opens_the_statistics_screen(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(type(app.screen).__name__, "StatsScreen")

    async def test_escape_closes_it(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotEqual(type(app.screen).__name__, "StatsScreen")

    async def test_an_empty_cache_still_opens(self):
        """Sans message, l'écran doit s'ouvrir et le dire — une division
        par zéro sur la part de non-lus le fermerait aussitôt."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(type(app.screen).__name__, "StatsScreen")


class TestWhatItShows(StatsScreenCase):
    async def test_the_counts_and_the_histogram_are_there(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            corps = self._corps(app)
            self.assertIn("█", corps)
            self.assertIn("ana@e.ca", corps)

    async def test_a_cache_without_threads_says_so(self):
        """Les colonnes de fil datent de la v2 : un cache rempli avant n'a
        rien à relier, et un « 0 » sec se lirait comme « on répond en zéro
        seconde »."""
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=1,
                    date=DEPART,
                    size=10,
                    flags="",
                    msgid="<a@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="s",
                    snippet="",
                )
            ],
        )
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertIn("resynchronis", self._corps(app))


class TestUntrustedAddresses(StatsScreenCase):
    async def test_a_bracket_in_an_address_does_not_break_the_screen(self):
        """Les adresses viennent des messages, donc de n'importe qui. Un
        crochet contenant un « = » est lu comme une balise et fait lever
        `MarkupError` — le même défaut que l'aperçu d'un message.
        """
        self.remplir(frm="Pub <a=b@e.ca>")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(type(app.screen).__name__, "StatsScreen")
            self.assertIn("a=b@e.ca", self._corps(app))


class TestFilters(StatsScreenCase):
    async def test_m_switches_the_histogram_to_months(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("m")
            await pilot.pause()
            self.assertIn("mois", self._entete(app))

    async def test_f_restricts_to_the_open_folder_and_back(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertIn("tous les dossiers", self._entete(app))
            await pilot.press("f")
            await pilot.pause()
            self.assertIn("Boîte", self._entete(app))
            await pilot.press("f")
            await pilot.pause()
            self.assertIn("tous les dossiers", self._entete(app))


class TestMenuEntry(unittest.TestCase):
    def test_entry_five_reaches_the_statistics(self):
        """Le câblage seul : un `elif` mal branché afficherait le cache ou
        la synchronisation sans que rien ne le signale."""
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        with patch.object(menu, "_show_stats") as mock_stats, patch.object(
            menu, "_configure_mail_logging"
        ), patch("click.prompt", side_effect=["5", "0"]), patch(
            "builtins.print"
        ):
            menu.prompt_execute_mail(MagicMock())
        mock_stats.assert_called_once()


if __name__ == "__main__":
    unittest.main()
