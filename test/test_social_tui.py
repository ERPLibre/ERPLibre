#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran des fils.

Ce qu'il doit tenir et qu'un écran de courriel n'a pas à connaître : un
compte dont la PLATEFORME ne sert pas de fil, qui n'est pas en panne et ne
doit pas en avoir l'air ; et un envoi qui garde sa clé d'idempotence tant que
l'écran vit, pour qu'une reprise après un refus ne publie pas deux fois.

Rien ne touche le réseau : les sessions portent un transport double ou le bac
à sable HTTP local, comme partout ailleurs dans ce paquet.
"""

import os
import tempfile
import unittest
from pathlib import Path

from script.todo.social.accounts import SocialAccount, account_from_preset
from script.todo.social.mastodon import SocialError, SocialRefused
from script.todo.social.store import Media, PostMeta, Store
from script.todo.social.tui import (
    FeedRef,
    Session,
    feed_refs,
    run_tui,
    sync_session,
)


def t_refuse() -> str:
    """Le préfixe d'un refus ordinaire, pour vérifier qu'un DOUTE ne le
    porte pas."""
    from script.todo.todo_i18n import t

    return t("social_compose_refused")


def billet(post_id, texte="Bonjour le fil.", **kw):
    base = dict(
        post_id=post_id,
        created_at=1_780_000_000 + int(post_id),
        author="ana",
        author_name="Ana",
        text=texte,
        url="https://i.exemple/@ana/1",
        uri="https://i.exemple/users/ana/statuses/1",
    )
    base.update(kw)
    return PostMeta(**base)


class FauxTransport:
    """Un transport qui rend des pages, et note ce qu'on lui demande."""

    def __init__(self, pages=None, limite=500, refus=None):
        self.pages = list(pages or [])
        self.limite = limite
        self.refus = refus
        self.publies = []
        self.curseurs = []
        self.cles = 0

    def home_timeline(self, cursor="", limit=40):
        self.curseurs.append(cursor)
        if not self.pages:
            return [], ""
        return self.pages.pop(0)

    def limite_caracteres(self):
        return self.limite

    def nouvelle_cle(self):
        """La clé vient du TRANSPORT : chaque protocole la définit à sa
        façon, et imposer celle d'un réseau la ferait refuser ailleurs."""
        self.cles += 1
        return f"cle-{self.cles}"

    def publish(
        self, texte, *, cle="", visibilite="public", repond_a="", parent=None
    ):
        self.publies.append((texte, cle, visibilite, repond_a, parent))
        if self.refus is not None:
            souci = self.refus
            self.refus = None
            raise souci
        return billet("9", texte)


class TuiCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset(
            "perso",
            "@moi@i.exemple",
            "mastodon",
            base_url="https://i.exemple",
        )
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.fil = self.store.upsert_feed("home", "Accueil")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def _session(self, transport=None):
        return Session(self.account, self.store, transport or FauxTransport())

    async def _app(self, sessions=None):
        import textual.app

        captures = []
        orig = textual.app.App.__init__

        def cap(app_self, *a, **k):
            orig(app_self, *a, **k)
            captures.append(app_self)

        textual.app.App.__init__ = cap
        try:
            run_tui(run_app=False, sessions=sessions or [self._session()])
        finally:
            textual.app.App.__init__ = orig
        return captures[-1]


class TestTheFetchPass(TuiCase):
    """La passe vit hors de l'écran : elle se teste sans terminal."""

    def test_it_writes_what_the_instance_serves(self):
        transport = FauxTransport([([billet("1"), billet("2")], "")])
        self.assertEqual(sync_session(self._session(transport)), 2)
        self.assertEqual(self.store.count_posts(self.fil), 2)

    def test_it_keeps_the_cursor_when_the_ceiling_stops_it(self):
        """Arrêtée par le plafond, la passe garde où elle en était : la
        suivante reprend la descente au lieu de la recommencer."""
        transport = FauxTransport(
            [([billet(str(n))], f"k-{n}") for n in range(1, 10)]
        )
        sync_session(self._session(transport), pages=2)
        self.assertEqual(self.store.feed_state("home")["cursor"], "k-2")

    def test_the_next_pass_resumes_where_the_ceiling_stopped(self):
        transport = FauxTransport(
            [([billet(str(n))], f"k-{n}") for n in range(1, 10)]
        )
        sync_session(self._session(transport), pages=2)
        suite = FauxTransport([([billet("50")], "")])
        sync_session(self._session(suite))
        self.assertEqual(suite.curseurs[0], "k-2")

    def test_it_clears_the_cursor_once_the_feed_is_exhausted(self):
        """L'instance n'annonce plus de suite : l'historique est descendu en
        entier. La passe suivante doit repartir du HAUT, où arrivent les
        billets neufs, et non d'un curseur qui ne désigne plus rien."""
        transport = FauxTransport([([billet("1")], "")])
        sync_session(self._session(transport))
        self.assertIsNone(self.store.feed_state("home")["cursor"])

    def test_it_stops_when_the_instance_announces_no_more(self):
        transport = FauxTransport([([billet("1")], "")])
        sync_session(self._session(transport))
        self.assertEqual(len(transport.curseurs), 1)

    def test_it_stops_at_the_page_ceiling(self):
        """Une première passe sur un compte ancien remonterait des années de
        fil pour un écran qui n'en montre que le haut."""
        transport = FauxTransport(
            [([billet(str(n))], f"k-{n}") for n in range(1, 20)]
        )
        sync_session(self._session(transport), pages=3)
        self.assertEqual(len(transport.curseurs), 3)

    def test_an_offline_account_fetches_nothing(self):
        session = Session(self.account, self.store, None)
        self.assertEqual(sync_session(session), 0)

    def test_a_platform_without_a_feed_fetches_nothing(self):
        """Ce n'est pas une panne : la plateforme n'en sert pas."""
        compte = SocialAccount(
            name="pro",
            handle="moi",
            platform="linkedin",
            secret_ref="kdbx:x",
        )
        magasin = Store(compte, mode="clear", base=Path(self.tmp.name))
        magasin.open()
        self.addCleanup(magasin.close)
        session = Session(compte, magasin, FauxTransport())
        self.assertFalse(session.peut_lire())
        self.assertEqual(sync_session(session), 0)


class TestTheTree(TuiCase):
    async def test_a_feed_appears_under_its_account(self):
        app = await self._app()
        async with app.run_test():
            refs = feed_refs(app.sessions)
            self.assertEqual([r.feed_name for r in refs], ["home"])

    async def test_the_unread_count_is_shown(self):
        self.store.upsert_posts(self.fil, [billet("1"), billet("2")])
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("2", str(self._feuille(app).label))

    async def test_marking_one_read_moves_the_count_at_once(self):
        """Le compteur suit le geste, sans attendre une passe."""
        self.store.upsert_posts(self.fil, [billet("1"), billet("2")])
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            self.assertIn("1", str(self._feuille(app).label))

    async def test_a_platform_without_a_feed_says_so(self):
        """Un nœud vide se lirait comme une synchronisation qui n'a pas eu
        lieu ; ce compte n'aura JAMAIS de fil."""
        from textual.widgets import Tree

        compte = SocialAccount(
            name="pro",
            handle="moi",
            platform="linkedin",
            secret_ref="kdbx:x",
        )
        magasin = Store(compte, mode="clear", base=Path(self.tmp.name))
        magasin.open()
        self.addCleanup(magasin.close)
        app = await self._app([Session(compte, magasin, None)])
        async with app.run_test() as pilot:
            await pilot.pause()
            arbre = app.query_one("#feeds", Tree)
            libelles = [
                str(f.label) for c in arbre.root.children for f in c.children
            ]
            self.assertTrue(libelles)
            self.assertIn("fil", libelles[0].lower())

    def _feuille(self, app):
        from textual.widgets import Tree

        arbre = app.query_one("#feeds", Tree)
        for compte in arbre.root.children:
            for feuille in compte.children:
                if isinstance(feuille.data, FeedRef):
                    return feuille
        self.fail("aucune feuille de fil dans l'arbre")


class TestTheList(TuiCase):
    async def test_the_newest_post_comes_first(self):
        self.store.upsert_posts(
            self.fil, [billet("1"), billet("3"), billet("2")]
        )
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual([m.post_id for m in app.metas], ["3", "2", "1"])

    async def test_a_multiline_post_stays_on_one_row(self):
        """Les retours à la ligne feraient grandir la rangée et casseraient
        l'alignement des colonnes."""
        from textual.widgets import DataTable

        self.store.upsert_posts(
            self.fil, [billet("1", "premiere\nseconde\ntroisieme")]
        )
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#list", DataTable)
            cellule = table.get_row_at(0)[1]
            self.assertNotIn("\n", str(cellule))

    async def test_an_unread_post_is_marked(self):
        from textual.widgets import DataTable

        self.store.upsert_posts(self.fil, [billet("1")])
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#list", DataTable)
            self.assertIn("●", str(table.get_row_at(0)[0]))


class TestThePreview(TuiCase):
    async def _apercu(self, app) -> str:
        from textual.widgets import Static

        return str(app.query_one("#preview", Static).content)

    async def test_it_shows_the_text_of_the_post(self):
        self.store.upsert_posts(self.fil, [billet("1", "un vrai message")])
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("un vrai message", await self._apercu(app))

    async def test_a_bracket_token_is_shown_not_parsed(self):
        """Auteur et texte viennent du réseau, donc de n'importe qui : un
        crochet y serait analysé comme une balise."""
        jeton = "[&g=3f9a&msg_token=QkZBAAEB%2F7RH%3D]"
        self.store.upsert_posts(self.fil, [billet("1", f"suivi {jeton}")])
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("msg_token", await self._apercu(app))

    async def test_a_shared_post_says_it_is_shared(self):
        self.store.upsert_posts(self.fil, [billet("1", boost_of="5")])
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("↻", await self._apercu(app))

    async def test_an_attachment_shows_its_description(self):
        self.store.upsert_posts(
            self.fil,
            [
                billet(
                    "1", media=[Media("https://i/1.png", "image", "un plan")]
                )
            ],
        )
        app = await self._app()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("un plan", await self._apercu(app))


class TestWriting(TuiCase):
    async def _ouvrir(self, pilot, app):
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        return app.screen

    async def test_the_key_survives_a_refusal(self):
        """LE point de l'écran : un envoi refusé garde sa clé, donc la
        reprise rend le billet déjà posé au lieu d'en créer un second."""
        transport = FauxTransport(refus=SocialError("passerelle en vrac"))
        app = await self._app([self._session(transport)])
        async with app.run_test() as pilot:
            ecran = await self._ouvrir(pilot, app)
            from textual.widgets import TextArea

            ecran.query_one("#compose_text", TextArea).text = "Bonjour."
            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(len(transport.publies), 2)
            self.assertEqual(transport.publies[0][1], transport.publies[1][1])

    async def test_a_refusal_leaves_the_screen_open(self):
        """Fermer l'écran perdrait le texte écrit et la clé avec lui."""
        from textual.screen import ModalScreen

        transport = FauxTransport(refus=SocialRefused("trop long"))
        app = await self._app([self._session(transport)])
        async with app.run_test() as pilot:
            ecran = await self._ouvrir(pilot, app)
            from textual.widgets import TextArea

            ecran.query_one("#compose_text", TextArea).text = "Bonjour."
            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)

    async def test_a_doubt_is_not_shown_as_a_refusal(self):
        """Sur un réseau qui n'offre rien pour rejouer, le billet est
        peut-être parti : dire « refusé » ferait presser à nouveau, et
        publierait peut-être deux fois."""
        from textual.widgets import Static, TextArea

        from script.todo.social.linkedin import SocialUnknownOutcome

        transport = FauxTransport(
            refus=SocialUnknownOutcome("envoi parti sans réponse")
        )
        app = await self._app([self._session(transport)])
        async with app.run_test() as pilot:
            ecran = await self._ouvrir(pilot, app)
            ecran.query_one("#compose_text", TextArea).text = "Bonjour."
            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            dit = str(app.screen.query_one("#compose_status", Static).content)
            self.assertIn("sans réponse", dit)
            self.assertNotIn(t_refuse(), dit)

    async def test_an_empty_post_never_leaves(self):
        transport = FauxTransport()
        app = await self._app([self._session(transport)])
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(transport.publies, [])

    async def test_a_post_over_the_limit_never_leaves(self):
        """Refusé ICI : la personne corrige sans payer un aller-retour."""
        transport = FauxTransport(limite=10)
        app = await self._app([self._session(transport)])
        async with app.run_test() as pilot:
            ecran = await self._ouvrir(pilot, app)
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import TextArea

            ecran.query_one("#compose_text", TextArea).text = "a" * 40
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertEqual(transport.publies, [])

    async def test_a_reply_names_the_post_it_answers(self):
        transport = FauxTransport()
        self.store.upsert_posts(self.fil, [billet("7")])
        app = await self._app([self._session(transport)])
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            from textual.widgets import TextArea

            app.screen.query_one("#compose_text", TextArea).text = "Merci."
            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(transport.publies[0][3], "7")
            # Le billet d'origine voyage avec : certains réseaux le
            # désignent par son adresse ET son empreinte.
            self.assertIsNotNone(transport.publies[0][4])
            self.assertEqual(transport.publies[0][4].post_id, "7")

    async def test_an_offline_account_is_refused_and_told(self):
        app = await self._app([Session(self.account, self.store, None)])
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            self.assertTrue(app.status)


class TestTheMenuEntry(unittest.TestCase):
    """L'aiguillage : `[3]` ouvre le social et RIEN d'autre.

    Le symétrique existe pour le courriel ; sans celui-ci, une entrée
    insérée au mauvais rang enverrait vers le mauvais paquet sans que rien
    ne le signale.
    """

    def test_three_dispatches_to_social_only(self):
        from unittest.mock import patch

        from script.todo.todo import TODO

        todo = TODO()
        with (
            patch.object(TODO, "prompt_assistant_llm") as question,
            patch("script.todo.mail.menu.prompt_execute_mail") as courriel,
            patch("script.todo.social.menu.prompt_execute_social") as social,
            patch("click.prompt", side_effect=["3", "0"]),
            patch("script.todo.todo_telemetry.record"),
        ):
            todo.prompt_assistant()

        social.assert_called_once_with(todo)
        courriel.assert_not_called()
        question.assert_not_called()

    def test_two_still_dispatches_to_mail(self):
        """Le contrôle : insérer une entrée ne doit pas décaler les
        autres."""
        from unittest.mock import patch

        from script.todo.todo import TODO

        todo = TODO()
        with (
            patch("script.todo.mail.menu.prompt_execute_mail") as courriel,
            patch("script.todo.social.menu.prompt_execute_social") as social,
            patch("click.prompt", side_effect=["2", "0"]),
            patch("script.todo.todo_telemetry.record"),
        ):
            todo.prompt_assistant()

        courriel.assert_called_once_with(todo)
        social.assert_not_called()


if __name__ == "__main__":
    unittest.main()
