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

    async def _details(self, pilot, app):
        """Ouvre puis demande les détails, et attend le fil de travail."""
        await self._ouvrir(pilot, app)
        await pilot.press("enter")
        await app.workers.wait_for_complete()
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
    async def test_the_overview_shows_counts_and_the_histogram(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertIn("█", self._corps(app))

    async def test_the_overview_does_not_scan_the_mailbox(self):
        """La propriété qui rend l'écran utilisable sur une grande boîte :
        les correspondants ouvrent chaque colonne scellée, et les calculer
        avant le premier affichage fige l'écran. Ils n'apparaissent
        qu'après demande."""
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertNotIn("ana@e.ca", self._corps(app))

    async def test_enter_computes_the_correspondents(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._details(pilot, app)
            self.assertIn("ana@e.ca", self._corps(app))

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
            await self._details(pilot, app)
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
            await self._details(pilot, app)
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

    async def test_changing_the_scope_drops_stale_details(self):
        """Les détails portaient sur l'autre portée : les garder
        afficherait des correspondants qui ne sont plus ceux du filtre
        annoncé juste au-dessus."""
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._details(pilot, app)
            self.assertIn("ana@e.ca", self._corps(app))
            await pilot.press("f")
            await pilot.pause()
            self.assertNotIn("ana@e.ca", self._corps(app))

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


class TestScrolling(StatsScreenCase):
    """Le contenu doit DÉBORDER pour qu'il y ait quelque chose à faire
    défiler : avec `height: 1fr` sur le texte, la hauteur virtuelle du
    conteneur égalait la hauteur visible et le texte était tronqué, pas
    débordant — les touches ne faisaient rien."""

    def remplir_beaucoup(self):
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=uid,
                    date=DEPART + uid * JOUR,
                    size=10,
                    flags="",
                    msgid=f"<{uid}@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="s",
                    snippet="",
                )
                for uid in range(1, 200)
            ],
        )

    async def test_the_content_overflows_its_window(self):
        from textual.containers import VerticalScroll

        self.remplir_beaucoup()
        app = await self._app()
        async with app.run_test(size=(100, 25)) as pilot:
            await self._ouvrir(pilot, app)
            zone = app.screen.query_one("#stats_scroll", VerticalScroll)
            self.assertGreater(zone.virtual_size.height, zone.size.height)

    async def test_the_scroll_area_holds_the_focus_on_open(self):
        """Sans ça le focus va à la première liste déroulante : les flèches
        la parcourent au lieu de faire défiler, et `enter` la déplie au lieu
        de lancer les détails."""
        self.remplir_beaucoup()
        app = await self._app()
        async with app.run_test(size=(100, 25)) as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(app.screen.focused.id, "stats_scroll")

    async def test_page_down_moves_the_view(self):
        from textual.containers import VerticalScroll

        self.remplir_beaucoup()
        app = await self._app()
        async with app.run_test(size=(100, 25)) as pilot:
            await self._ouvrir(pilot, app)
            zone = app.screen.query_one("#stats_scroll", VerticalScroll)
            depart = zone.scroll_offset.y
            await pilot.press("pagedown")
            await pilot.pause()
            self.assertGreater(zone.scroll_offset.y, depart)


class TestSelectBoxes(StatsScreenCase):
    async def test_the_three_lists_are_there(self):
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            for ident in ("stats_pas", "stats_periode", "stats_portee"):
                self.assertTrue(app.screen.query(f"#{ident}"))

    async def test_choosing_a_step_changes_the_histogram(self):
        from textual.widgets import Select

        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            app.screen.query_one("#stats_pas", Select).value = "year"
            await pilot.pause()
            self.assertIn("année", self._entete(app))

    async def test_a_key_keeps_the_list_in_step_with_the_screen(self):
        """Deux chemins vers un seul réglage : sans mise à jour croisée, la
        liste annoncerait un pas que l'écran n'utilise pas."""
        from textual.widgets import Select

        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("m")
            await pilot.pause()
            self.assertEqual(
                app.screen.query_one("#stats_pas", Select).value, "month"
            )

    async def test_a_period_narrows_what_is_counted(self):
        """Les messages hors de la fenêtre choisie sortent du total."""
        import time as horloge

        from textual.widgets import Select

        maintenant = int(horloge.time())
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=90,
                    date=maintenant - 5 * JOUR,
                    size=10,
                    flags="",
                    msgid="<recent@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="s",
                    snippet="",
                ),
                MessageMeta(
                    uid=91,
                    date=maintenant - 900 * JOUR,
                    size=10,
                    flags="",
                    msgid="<vieux@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="s",
                    snippet="",
                ),
            ],
        )
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            app.screen.query_one("#stats_periode", Select).value = "month"
            await pilot.pause()
            corps = self._corps(app)
            self.assertIn("Messages : 1", corps)


class TestListModes(StatsScreenCase):
    """La touche `g` fait défiler les modes d'affichage de la liste."""

    async def _app_liste(self):
        self.remplir()
        return await self._app()

    async def test_g_announces_the_mode_it_switched_to(self):
        app = await self._app_liste()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            self.assertEqual(app.list_mode, "threads")

    async def test_g_cycles_back_to_flat(self):
        from script.todo.mail.tui_text import LIST_MODES

        app = await self._app_liste()
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(len(LIST_MODES)):
                await pilot.press("g")
                await pilot.pause()
            self.assertEqual(app.list_mode, LIST_MODES[0])

    async def test_the_cursor_still_points_at_the_shown_message(self):
        """En mode fil l'ordre change : lire `visible_metas` au lieu des
        lignes affichées rendrait le message d'une AUTRE ligne que celle où
        le curseur se trouve."""
        app = await self._app_liste()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            lignes = app.lignes_a_afficher()
            table = app.query_one("#list")
            if lignes and table.cursor_row is not None:
                attendu = lignes[table.cursor_row][0]
                self.assertEqual(app.current_meta().uid, attendu.uid)

    async def test_the_list_keeps_a_gutter_for_its_scrollbar(self):
        """Sans gouttière réservée, la largeur du tableau change selon le
        nombre de messages, sous le curseur."""
        app = await self._app_liste()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#list")
            self.assertEqual(
                str(table.styles.scrollbar_gutter).lower(), "stable"
            )


class TestFolderScreen(StatsScreenCase):
    """L'écran de gestion des dossiers, touche `F`."""

    class FauxTransport:
        def __init__(self):
            self.faits = []

        def create_folder(self, name):
            self.faits.append(("create", name))

        def rename_folder(self, ancien, nouveau):
            self.faits.append(("rename", ancien, nouveau))

        def delete_folder(self, name):
            self.faits.append(("delete", name))

    async def _ouvrir_dossiers(self):
        from types import SimpleNamespace

        self.remplir()
        app = await self._app()
        transport = self.FauxTransport()
        session = app.session_for("perso")
        # `online` est calculé depuis `syncer` et n'a pas de setter :
        # poser le syncer suffit, et décrit mieux la réalité.
        session.syncer = SimpleNamespace(transport=transport)
        return app, transport

    async def test_F_opens_the_folder_screen(self):
        app, _ = await self._ouvrir_dossiers()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("F")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "FolderScreen")

    async def test_deleting_needs_the_exact_word(self):
        """Une saisie approximative ne doit RIEN détruire : le serveur n'a
        pas de corbeille pour les dossiers."""
        from script.todo.mail.tui import MOT_SUPPRESSION

        app, transport = await self._ouvrir_dossiers()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("F")
            await pilot.pause()
            ecran = app.screen
            ecran.action_start_delete()
            await pilot.pause()
            champ = ecran.query_one("#folder_input")
            champ.value = "supprim"
            await champ.action_submit()
            await pilot.pause()
            self.assertEqual(transport.faits, [])
            self.assertNotEqual(MOT_SUPPRESSION, "supprim")

    async def test_deleting_with_the_word_reaches_the_server(self):
        from script.todo.mail.tui import MOT_SUPPRESSION

        app, transport = await self._ouvrir_dossiers()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("F")
            await pilot.pause()
            ecran = app.screen
            ecran.action_start_delete()
            await pilot.pause()
            champ = ecran.query_one("#folder_input")
            champ.value = MOT_SUPPRESSION
            await champ.action_submit()
            await pilot.pause()
            self.assertTrue(
                any(f[0] == "delete" for f in transport.faits), transport.faits
            )

    async def test_an_offline_account_is_refused_not_crashed(self):
        """Créer ou détruire passe par le serveur : hors ligne, l'écran ne
        pourrait qu'échouer à chaque geste."""
        self.remplir()
        app = await self._app()
        app.session_for("perso").syncer = None
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("F")
            await pilot.pause()
            self.assertNotEqual(type(app.screen).__name__, "FolderScreen")


class TestOutboxScreen(StatsScreenCase):
    """L'écran de la file, touche `o`, avec son bouton à gauche."""

    def _mettre_en_file(self, sujet="Devis"):
        from script.todo.mail.smtp_send import build_message
        from script.todo.mail.tui import deliver

        deliver(
            Session(self.account, self.store, None, password="x"),
            build_message(self.account, "a@y.ca", sujet, "Bonjour"),
        )

    async def test_o_opens_the_outbox(self):
        self.remplir()
        self._mettre_en_file()
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            self.assertEqual(type(app.screen).__name__, "OutboxScreen")

    async def test_each_message_carries_its_button_on_the_left(self):
        from textual.widgets import Button

        self.remplir()
        self._mettre_en_file()
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            self.assertTrue(app.screen.query(Button))

    async def test_the_button_holds_then_releases(self):
        """La retenue se lève par un geste, jamais par un délai."""
        from textual.widgets import Button

        self.remplir()
        self._mettre_en_file()
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            bouton = app.screen.query(Button).first()
            await pilot.click(bouton)
            await pilot.pause()
            self.assertTrue(self.store.outbox()[0]["held"])
            await pilot.click(app.screen.query(Button).first())
            await pilot.pause()
            self.assertFalse(self.store.outbox()[0]["held"])

    async def test_an_empty_outbox_says_so(self):
        """Un écran vide sans phrase se lit comme un écran cassé."""
        self.remplir()
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            from textual.widgets import Static

            texte = str(app.screen.query_one("#outbox_hint", Static).content)
            self.assertTrue(texte.strip())
