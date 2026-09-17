#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ranger un message dans un AUTRE compte, depuis le client.

`m` proposait les dossiers du compte du message ; il propose maintenant
aussi ceux des autres comptes ouverts. Rien ne relie deux serveurs : le
message est relu en entier, déposé chez l'autre par APPEND, et retiré
d'ici seulement ensuite.

Ce que ces tests couvrent d'abord, c'est cet ORDRE et ce qui l'interrompt.
Un retrait qui précéderait le dépôt, ou qui suivrait un dépôt non
confirmé, perdrait le message définitivement : il ne passerait par aucune
corbeille et aucun serveur ne le rendrait.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session

CORPS = (
    b"From: Ana <ana@e.ca>\r\nTo: moi@x.ca\r\nSubject: Devis\r\n"
    b"Message-ID: <devis-42@e.ca>\r\n\r\ncorps du devis\r\n"
)


class FauxTransport:
    def __init__(self, arrive=True, vide=True, erreur=None):
        self.arrive = arrive
        self.vide = vide
        self.erreur = erreur
        self.depots = []
        self.retires = []
        self.selections = []
        self.demandes = []

    def select(self, folder):
        self.selections.append(folder)

    def append(self, folder, raw, flags, date=None):
        if self.erreur:
            raise self.erreur
        self.depots.append((folder, raw, list(flags), date))

    def contient_message_id(self, folder, msgid):
        self.demandes.append((folder, msgid))
        return self.arrive

    def discard(self, uids):
        self.retires.append(list(uids))
        return self.vide

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport, corps=CORPS):
        self.transport = transport
        self.corps = corps
        self.relectures = []

    def fetch_body(self, folder, uid):
        return self.corps

    def sync_one(self, folder):
        self.relectures.append(folder)


class DeuxComptesCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.comptes, self.stores = {}, {}
        for nom in ("perso", "travail"):
            compte = account_from_preset(nom, f"{nom}@x.ca", "generic")
            store = Store(compte, mode="clear", base=Path(self.tmp.name) / nom)
            store.open()
            store.upsert_folder("INBOX", "Boîte", "inbox")
            store.upsert_folder("Archives", "Archives", None)
            self.comptes[nom], self.stores[nom] = compte, store
        self.boite = self.stores["perso"].folder_state("INBOX")["id"]
        self.stores["perso"].upsert_messages(
            self.boite,
            [
                MessageMeta(
                    uid=7,
                    date=1_500_000_000,
                    size=10,
                    flags="\\Seen",
                    msgid="<devis-42@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="Devis",
                    snippet="",
                )
            ],
        )

    def tearDown(self):
        for store in self.stores.values():
            store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    async def _app(self, ici=None, ailleurs=None, autre_en_ligne=True):
        import textual.app

        from script.todo.mail.tui import run_tui

        self.ici = ici if ici is not None else FauxTransport()
        self.ailleurs = ailleurs if ailleurs is not None else FauxTransport()
        self.syncer_ici = FauxSyncer(self.ici)
        self.syncer_ailleurs = FauxSyncer(self.ailleurs)
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
                        self.comptes["perso"],
                        self.stores["perso"],
                        self.syncer_ici,
                        password="x",
                    ),
                    Session(
                        self.comptes["travail"],
                        self.stores["travail"],
                        self.syncer_ailleurs if autre_en_ligne else None,
                        password="x",
                    ),
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
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        return app.screen

    async def _choisir(self, pilot, app, compte, dossier):
        from textual.widgets import DataTable

        ecran = await self._ouvrir(pilot, app)
        rang = next(
            i
            for i, (session, nom) in enumerate(ecran.cibles)
            if session.account.name == compte and nom == dossier
        )
        ecran.query_one("#move_list", DataTable).move_cursor(row=rang)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    def _statut(self, app):
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)

    def _restants(self):
        return [m.uid for m in self.stores["perso"].list_messages(self.boite)]


class TestWhatTheListOffers(DeuxComptesCase):
    async def test_the_other_accounts_folders_are_offered(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            ecran = await self._ouvrir(pilot, app)
            self.assertIn(
                ("travail", "Archives"),
                [(s.account.name, n) for s, n in ecran.cibles],
            )

    async def test_the_message_own_account_comes_first(self):
        """C'est le rangement courant, et le curseur y est déjà."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            ecran = await self._ouvrir(pilot, app)
            self.assertEqual(ecran.cibles[0][0].account.name, "perso")

    async def test_an_offline_account_is_not_offered(self):
        """Proposer une cible injoignable ferait échouer le geste après
        coup, une fois le message déjà relu."""
        app = await self._app(autre_en_ligne=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            ecran = await self._ouvrir(pilot, app)
            self.assertEqual(
                {s.account.name for s, _ in ecran.cibles}, {"perso"}
            )

    async def test_the_open_folder_is_still_not_offered(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            ecran = await self._ouvrir(pilot, app)
            self.assertNotIn(
                ("perso", "INBOX"),
                [(s.account.name, n) for s, n in ecran.cibles],
            )


class TestTheOrderOfTheGesture(DeuxComptesCase):
    async def test_it_deposits_in_the_other_account(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertEqual(len(self.ailleurs.depots), 1)
            dossier, raw, _, _ = self.ailleurs.depots[0]
            self.assertEqual(dossier, "Archives")
            self.assertEqual(raw, CORPS)

    async def test_the_flags_and_the_date_travel_with_it(self):
        """Sans la date d'origine, le serveur horodate à maintenant et le
        message remonte en tête de la boîte comme s'il venait d'arriver."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            _, _, drapeaux, date = self.ailleurs.depots[0]
            self.assertEqual(drapeaux, ["\\Seen"])
            self.assertEqual(date, 1_500_000_000)

    async def test_the_source_is_removed_only_after_the_deposit(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertEqual(self.ici.retires, [[7]])
            self.assertEqual(self._restants(), [])

    async def test_the_other_account_is_read_again(self):
        """Sans cette relecture, le message n'apparaîtrait là-bas qu'à la
        prochaine passe complète."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertEqual(self.syncer_ailleurs.relectures, ["Archives"])


class TestWhenItCannotBeConfirmed(DeuxComptesCase):
    async def test_an_unconfirmed_deposit_keeps_the_source(self):
        """Le cœur du sujet : un message en double se corrige, un message
        disparu ne se rattrape pas."""
        app = await self._app(ailleurs=FauxTransport(arrive=False))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertEqual(self.ici.retires, [])
            self.assertEqual(self._restants(), [7])
            self.assertTrue(self._statut(app))

    async def test_a_refused_deposit_removes_nothing(self):
        from script.todo.mail.imap_transport import ImapError

        app = await self._app(
            ailleurs=FauxTransport(erreur=ImapError("refus"))
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertEqual(self.ici.retires, [])
            self.assertIn("refus", self._statut(app))
            self.assertEqual(self._restants(), [7])

    async def test_a_source_the_server_could_not_clear_is_said(self):
        app = await self._app(ici=FauxTransport(vide=False))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertTrue(self._statut(app))

    async def test_the_deposit_is_checked_by_the_message_id(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app, "travail", "Archives")
            self.assertEqual(
                self.ailleurs.demandes, [("Archives", "<devis-42@e.ca>")]
            )


if __name__ == "__main__":
    unittest.main()
