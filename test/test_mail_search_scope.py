#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Chercher au-delà du dossier ouvert.

`/` ne regardait qu'un dossier d'un compte. `p` fait défiler la portée —
dossier, compte, tous les comptes — et le résultat traverse alors les
dossiers.

Ce que ces tests couvrent d'abord, c'est la PROVENANCE. Un UID ne désigne
rien tout seul : le même nombre nomme un autre message dans chaque
dossier. Un résultat qui perdrait le sien ferait lire le corps du voisin
et ranger le mauvais message.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store, new_key
from script.todo.mail.tui import MailboxRef, Session


def message(uid, sujet, date=100):
    return MessageMeta(
        uid=uid,
        date=date,
        size=1,
        flags="",
        msgid=f"<{uid}@e.ca>",
        frm="ana@e.ca",
        to="moi@x.ca",
        subject=sujet,
        snippet="",
    )


class StoreScopeCase(unittest.TestCase):
    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.key = new_key() if self.mode != "clear" else None
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")
        self.archives = self.store.upsert_folder("Archives", "Archives", None)
        self.store.upsert_messages(self.inbox, [message(1, "Devis récent")])
        # LE MÊME UID dans l'autre dossier : c'est le cas qui démasque un
        # résultat sans provenance, et il n'a rien d'exceptionnel — chaque
        # dossier numérote pour lui seul.
        self.store.upsert_messages(self.archives, [message(1, "Devis vieux")])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class TestWhereResultsComeFrom(StoreScopeCase):
    def test_a_search_without_a_folder_crosses_them(self):
        trouves = self.store.search("devis")
        self.assertEqual(len(trouves), 2)

    def test_each_result_names_its_folder(self):
        trouves = self.store.search("devis")
        self.assertEqual(
            sorted(m.folder for m in trouves), ["Archives", "INBOX"]
        )

    def test_the_folder_travels_with_the_right_message(self):
        """Deux messages du même UID : seule la provenance les distingue."""
        par_dossier = {m.folder: m.subject for m in self.store.search("devis")}
        self.assertEqual(par_dossier["INBOX"], "Devis récent")
        self.assertEqual(par_dossier["Archives"], "Devis vieux")

    def test_a_folder_search_still_names_it(self):
        trouves = self.store.search("devis", folder_id=self.inbox)
        self.assertEqual([m.folder for m in trouves], ["INBOX"])

    def test_a_folder_search_stays_in_its_folder(self):
        trouves = self.store.search("devis", folder_id=self.archives)
        self.assertEqual([m.subject for m in trouves], ["Devis vieux"])

    def test_nobody_is_signed_with_an_account(self):
        """Le cache ne connaît qu'un compte : le nommer ici laisserait
        croire qu'il sait distinguer, alors que c'est l'appelant qui
        assemble."""
        self.assertEqual({m.account for m in self.store.search("devis")}, {""})


class TestTheSameThroughTheDecryptingScan(TestWhereResultsComeFrom):
    """Le mode chiffré n'a pas d'index et balaie en déchiffrant. Le coût
    change, le résultat non — la provenance comprise."""

    mode = "encrypted"


class TuiScopeCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.stores = {}
        for nom in ("perso", "travail"):
            compte = account_from_preset(nom, f"{nom}@x.ca", "generic")
            store = Store(compte, mode="clear", base=Path(self.tmp.name) / nom)
            store.open()
            inbox = store.upsert_folder("INBOX", "Boîte", "inbox")
            archives = store.upsert_folder("Archives", "Archives", None)
            store.upsert_messages(
                inbox, [message(1, f"Devis boîte {nom}", date=200)]
            )
            store.upsert_messages(
                archives, [message(1, f"Devis archive {nom}", date=100)]
            )
            self.stores[nom] = (compte, store)

    def tearDown(self):
        for _, store in self.stores.values():
            store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

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
                    Session(compte, store, None, password="x")
                    for compte, store in self.stores.values()
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

    def _statut(self, app):
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)

    async def _chercher(self, pilot, app, portees=0):
        app.select_ref(app.current_ref)
        await pilot.pause()
        for _ in range(portees):
            await pilot.press("p")
            await pilot.pause()
        app.query = "devis"
        app.recherche_complete = True
        app.refresh_list()
        await pilot.pause()
        return [m.subject for m in app.visible_metas()]


class TestWhatEachScopeShows(TuiScopeCase):
    async def test_the_open_folder_only_by_default(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(
                await self._chercher(pilot, app), ["Devis boîte perso"]
            )

    async def test_one_press_covers_the_whole_account(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            trouves = await self._chercher(pilot, app, portees=1)
            self.assertEqual(
                sorted(trouves), ["Devis archive perso", "Devis boîte perso"]
            )

    async def test_two_presses_cover_every_account(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            trouves = await self._chercher(pilot, app, portees=2)
            self.assertEqual(len(trouves), 4)

    async def test_three_presses_come_back_to_the_open_folder(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(
                await self._chercher(pilot, app, portees=3),
                ["Devis boîte perso"],
            )

    async def test_the_scope_is_said_each_time(self):
        """Une portée qui change en silence ferait passer une liste plus
        longue pour un défaut."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=1)
            self.assertTrue(self._statut(app))

    async def test_the_widest_search_is_sorted_by_date(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=2)
            dates = [m.date for m in app.visible_metas()]
            self.assertEqual(dates, sorted(dates, reverse=True))


class TestThatNothingLosesItsOrigin(TuiScopeCase):
    async def test_rows_sharing_a_uid_do_not_collide(self):
        """`DataTable` refuse deux fois la même clé : sans une clé qui
        porte le dossier, la liste lèverait au lieu de s'afficher."""
        from textual.widgets import DataTable

        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=2)
            self.assertEqual(app.query_one("#list", DataTable).row_count, 4)

    async def test_a_result_from_elsewhere_says_where_it_is(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=1)
            sujets = [
                app._provenance(m) + m.subject for m in app.visible_metas()
            ]
            self.assertIn("[Archives] Devis archive perso", sujets)

    async def test_the_open_folder_is_not_labelled(self):
        """Le répéter sur chaque ligne mangerait la largeur du sujet sans
        rien apprendre."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=1)
            ici = [
                m for m in app.visible_metas() if m.subject.endswith("perso")
            ]
            boite = next(m for m in ici if m.folder == "INBOX")
            self.assertEqual(app._provenance(boite), "")

    async def test_another_account_is_named_with_its_folder(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=2)
            ailleurs = next(
                m
                for m in app.visible_metas()
                if m.account == "travail" and m.folder == "Archives"
            )
            self.assertEqual(app._provenance(ailleurs), "[travail/Archives] ")

    async def test_a_result_is_read_in_its_own_folder(self):
        """Le cœur du sujet : lire par le dossier ouvert afficherait le
        corps du message qui porte le même UID ici."""
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=2)
            cible = next(
                m
                for m in app.visible_metas()
                if m.account == "travail" and m.folder == "Archives"
            )
            session, dossier = app.meta_origin(cible)
            self.assertEqual(session.account.name, "travail")
            self.assertEqual(dossier, "Archives")

    async def test_a_message_of_the_open_folder_keeps_the_open_folder(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.select_ref(app.current_ref)
            await pilot.pause()
            session, dossier = app.meta_origin(app.metas[0])
            self.assertEqual(session.account.name, "perso")
            self.assertEqual(dossier, "INBOX")


class FauxTransport:
    """Le lien réseau, réduit à ce qu'un rangement emploie."""

    def __init__(self):
        self.selections = []
        self.deplacements = []

    def select(self, folder):
        self.selections.append(folder)

    def move(self, uids, target):
        self.deplacements.append((self.selections[-1], list(uids), target))
        return True

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class TestFilingAResultFromElsewhere(TuiScopeCase):
    """Ranger depuis une liste élargie doit porter sur le message DÉSIGNÉ.

    C'est le défaut que la provenance existe pour empêcher : l'UID d'un
    résultat venu des archives, appliqué au dossier ouvert, y nomme un
    autre message — qui partirait à la corbeille à sa place.
    """

    async def _app_en_ligne(self, transport):
        app = await self._app()
        compte, store = self.stores["perso"]
        store.upsert_folder("Trash", "Corbeille", "trash")
        session = app.session_for("perso")
        session.syncer = FauxSyncer(transport)
        return app

    async def test_the_trash_key_moves_it_out_of_its_own_folder(self):
        from textual.widgets import DataTable

        transport = FauxTransport()
        app = await self._app_en_ligne(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=1)
            ligne = next(
                i
                for i, m in enumerate(app.visible_metas())
                if m.folder == "Archives" and m.account == "perso"
            )
            app.query_one("#list", DataTable).move_cursor(row=ligne)
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(
                transport.deplacements, [("Archives", [1], "Trash")]
            )

    async def test_the_message_of_the_open_folder_stays(self):
        transport = FauxTransport()
        app = await self._app_en_ligne(transport)
        _, store = self.stores["perso"]
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, portees=1)
            from textual.widgets import DataTable

            ligne = next(
                i
                for i, m in enumerate(app.visible_metas())
                if m.folder == "Archives" and m.account == "perso"
            )
            app.query_one("#list", DataTable).move_cursor(row=ligne)
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            boite = store.folder_state("INBOX")["id"]
            self.assertEqual([m.uid for m in store.list_messages(boite)], [1])


if __name__ == "__main__":
    unittest.main()
