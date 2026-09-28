#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Marquer lu tout un dossier.

Le geste des boîtes de listes de diffusion : trois cents non-lus dont
aucun n'appelle de réponse. Il ne détruit rien, mais rien ne le défait
commodément — « rendre non lus ceux qui l'étaient » n'existe pas, la liste
de départ étant perdue. D'où une confirmation, et une confirmation fermée
plutôt qu'un mot à taper : exiger un mot ici userait la vigilance qu'on
garde pour ce qui détruit.

Hors ligne, le client REFUSE : une passe de synchronisation relit les
drapeaux depuis le serveur, donc un marquage posé sans lui serait défait à
la passe suivante, en silence.
"""

import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


class FauxTransport:
    def __init__(self, erreur=None):
        self.erreur = erreur
        self.selections = []
        self.poses = []

    def select(self, folder):
        self.selections.append(folder)

    def store_flags_all(self, add, remove):
        if self.erreur:
            raise self.erreur
        self.poses.append((list(add), list(remove)))

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class AllSeenCase(unittest.IsolatedAsyncioTestCase):
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
                    uid=u,
                    date=1_780_000_000 + u,
                    size=10,
                    flags="\\Seen" if u == 2 else "",
                    msgid=f"<{u}@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject=f"Message {u}",
                    snippet="",
                )
                for u in (1, 2, 3)
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

    async def _app(self, transport=None, online=True):
        import textual.app

        from script.todo.mail.tui import run_tui

        self.transport = (
            transport if transport is not None else FauxTransport()
        )
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
                    Session(
                        self.account,
                        self.store,
                        FauxSyncer(self.transport) if online else None,
                        password="x",
                    )
                ],
            )
        finally:
            textual.app.App.__init__ = orig
        app = captured[-1]
        app.current_ref = MailboxRef(
            account_name="perso",
            folder_name="INBOX",
            display="Boîte",
            unseen=2,
        )
        return app

    async def _demander(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("M")
        await pilot.pause()

    async def _confirmer(self, pilot, app):
        await self._demander(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    def _non_lus(self):
        return self.store.count_unseen(self.inbox)

    def _statut(self, app):
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)


class TestTheConfirmation(AllSeenCase):
    async def test_it_asks_before_doing_anything(self):
        from textual.screen import ModalScreen

        app = await self._app()
        async with app.run_test() as pilot:
            await self._demander(pilot, app)
            self.assertIsInstance(app.screen, ModalScreen)
            self.assertEqual(self.transport.poses, [])
            self.assertEqual(self._non_lus(), 2)

    async def test_giving_up_marks_nothing(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._demander(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(self.transport.poses, [])
            self.assertEqual(self._non_lus(), 2)

    async def test_the_question_names_how_many(self):
        """Une confirmation qui ne dit pas sur quoi elle porte n'en est pas
        une."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._demander(pilot, app)
            self.assertIn("2", app.screen.question)

    async def test_a_folder_already_read_asks_nothing(self):
        from textual.screen import ModalScreen

        self.store.mark_all_seen(self.inbox)
        app = await self._app()
        async with app.run_test() as pilot:
            await self._demander(pilot, app)
            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertTrue(self._statut(app))


class TestWhatItMarks(AllSeenCase):
    async def test_the_server_is_told_first(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._confirmer(pilot, app)
            self.assertEqual(self.transport.selections, ["INBOX"])
            self.assertEqual(self.transport.poses, [(["\\Seen"], [])])

    async def test_the_cache_follows(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._confirmer(pilot, app)
            self.assertEqual(self._non_lus(), 0)

    async def test_the_count_said_is_what_changed(self):
        """Deux non-lus sur trois messages : c'est deux qu'on annonce, pas
        trois."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._confirmer(pilot, app)
            self.assertIn("2", self._statut(app))

    async def test_a_message_already_read_keeps_its_flags(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._confirmer(pilot, app)
            drapeaux = [m.flags for m in self.store.list_messages(self.inbox)]
            self.assertTrue(all(d.count("\\Seen") == 1 for d in drapeaux))


class TestWhenItRefuses(AllSeenCase):
    async def test_an_offline_account_is_refused_and_told(self):
        """Un marquage posé hors ligne serait défait à la passe suivante,
        en silence."""
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await self._demander(pilot, app)
            self.assertEqual(self._non_lus(), 2)
            self.assertTrue(self._statut(app))

    async def test_a_server_that_refuses_leaves_the_cache_alone(self):
        from script.todo.mail.imap_transport import ImapError

        app = await self._app(FauxTransport(erreur=ImapError("refus")))
        async with app.run_test() as pilot:
            await self._confirmer(pilot, app)
            self.assertIn("refus", self._statut(app))
            self.assertEqual(self._non_lus(), 2)


class TestTheTreeStopsSayingUnread(AllSeenCase):
    """Le compteur de l'arbre a sa propre source, et elle retardait.

    `folders.unseen` est une copie qu'une passe de synchronisation écrit :
    marquer lu ne la touchait pas, et l'arbre annonçait encore « 2 » à côté
    d'une ligne de statut disant « Marqués lus : 2 » — jusqu'à cinq minutes,
    le temps de la passe automatique suivante.
    """

    def _feuille(self, app):
        from textual.widgets import Tree

        arbre = app.query_one("#folders", Tree)
        for compte in arbre.root.children:
            for feuille in compte.children:
                if getattr(feuille.data, "folder_name", None) == "INBOX":
                    return feuille
        self.fail("la feuille INBOX manque à l'arbre")

    async def test_the_badge_shows_the_unread_count_to_begin_with(self):
        """Le contrôle : sans lui, un arbre qui n'affiche JAMAIS de compteur
        passerait le test suivant."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("2", str(self._feuille(app).label))

    async def test_the_badge_is_gone_once_the_folder_is_read(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._confirmer(pilot, app)
            self.assertEqual(str(self._feuille(app).label).strip(), "Boîte")

    async def test_the_tree_cursor_does_not_move(self):
        """Rebâtir l'arbre ramènerait son curseur à la racine : marquer lu
        au clavier ne doit pas déplacer la sélection de qui le fait."""
        from textual.widgets import Tree

        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            arbre = app.query_one("#folders", Tree)
            arbre.cursor_line = 2
            avant = arbre.cursor_line
            await self._confirmer(pilot, app)
            self.assertEqual(arbre.cursor_line, avant)


if __name__ == "__main__":
    unittest.main()
