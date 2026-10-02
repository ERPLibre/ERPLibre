#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire un fil chez une instance de microblogue.

Rien ne sort de la machine : l'instance est démarrée par le test sur un port
éphémère de la boucle locale (`social_sandbox.py`), comme le bac à sable
IMAP. Ce qui est éprouvé n'est pas la conformité de l'instance mais ce que
le CLIENT en fait — et surtout ce qu'il fait de ses refus, car trois
conduites distinctes en dépendent.
"""

import time
import unittest
from datetime import datetime, timezone

from social_sandbox import (
    EnVrac,
    Illisible,
    Refuse,
    SocialSandbox,
    TropVite,
    piece,
    statut,
)

from script.todo.social.accounts import account_from_preset
from script.todo.social.mastodon import (
    DELAI,
    INSTANT,
    MastodonTransport,
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    _suivant,
    billet_depuis_statut,
    instant_de_reprise,
    texte_depuis_html,
)
from script.todo.social.store import Store

JETON = "jeton-du-bac-a-sable"


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.bac = SocialSandbox().start()
        self.addCleanup(self.bac.stop)
        self.account = account_from_preset(
            "perso",
            "@moi@instance.exemple",
            "mastodon",
            base_url=self.bac.base_url,
        )
        self.transport = MastodonTransport(self.account, JETON, timeout=5)


class TestTheTextComesOutOfTheMarkup(unittest.TestCase):
    """L'instance sert du HTML. Le rendre tel quel afficherait des balises."""

    def test_paragraphs_become_line_breaks(self):
        """Les perdre collerait en un bloc un billet qui en comptait trois."""
        self.assertEqual(texte_depuis_html("<p>un</p><p>deux</p>"), "un\ndeux")

    def test_a_line_break_tag_becomes_one(self):
        self.assertEqual(texte_depuis_html("<p>un<br>deux</p>"), "un\ndeux")

    def test_a_link_keeps_its_words(self):
        rendu = texte_depuis_html('<p>voir <a href="https://x">ici</a></p>')
        self.assertEqual(rendu, "voir ici")

    def test_the_entities_come_back(self):
        self.assertEqual(texte_depuis_html("<p>a &amp; b</p>"), "a & b")

    def test_markup_written_by_the_author_survives(self):
        """Rétablir les entités AVANT de retirer les balises ferait passer
        ceci pour du balisage, et le texte disparaîtrait."""
        rendu = texte_depuis_html("<p>tapez &lt;b&gt;gras&lt;/b&gt;</p>")
        self.assertEqual(rendu, "tapez <b>gras</b>")

    def test_an_empty_content_is_an_empty_text(self):
        self.assertEqual(texte_depuis_html(""), "")


class TestWhatAPostBecomes(unittest.TestCase):
    def test_the_author_and_the_date_are_read(self):
        billet = billet_depuis_statut(statut("1", "salut"))
        self.assertEqual(billet.post_id, "1")
        self.assertEqual(billet.author, "ana")
        self.assertEqual(billet.author_name, "Ana")
        self.assertEqual(billet.text, "salut")
        self.assertTrue(billet.created_at > 0)

    def test_a_reply_remembers_what_it_answers(self):
        billet = billet_depuis_statut(statut("2", repond_a="1"))
        self.assertEqual(billet.reply_to, "1")

    def test_a_post_that_answers_nothing_says_so(self):
        self.assertEqual(billet_depuis_statut(statut("1")).reply_to, "")

    def test_a_share_shows_the_text_it_wraps(self):
        """Le contenu d'un partage est VIDE : lire le sien rendrait une ligne
        blanche là où il y a un message."""
        partage = statut(
            "9", partage=statut("5", "le message d'origine", auteur="bo")
        )
        billet = billet_depuis_statut(partage)
        self.assertEqual(billet.text, "le message d'origine")
        self.assertEqual(billet.boost_of, "5")

    def test_a_share_keeps_the_sharer_as_its_author(self):
        """C'est l'auteur de la LIGNE : celui qui partage, pas celui qui a
        écrit. Les confondre ferait croire qu'on suit quelqu'un d'autre."""
        partage = statut(
            "9", auteur="cam", nom="Cam", partage=statut("5", auteur="bo")
        )
        self.assertEqual(billet_depuis_statut(partage).author, "cam")

    def test_an_ordinary_post_shares_nothing(self):
        self.assertEqual(billet_depuis_statut(statut("1")).boost_of, "")

    def test_the_attachments_keep_their_description(self):
        brut = statut(
            "1", pieces=[piece(genre="image", description="un graphique")]
        )
        pieces = billet_depuis_statut(brut).media
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0].description, "un graphique")
        self.assertEqual(pieces[0].kind, "image")

    def test_an_unreadable_date_does_not_lose_the_post(self):
        """Un billet mal daté se range mal ; une page qui ne se charge pas
        ne se lit pas du tout."""
        billet = billet_depuis_statut(statut("1", quand="pas une date"))
        self.assertEqual(billet.created_at, 0)
        self.assertEqual(billet.post_id, "1")


class TestReadingTheFeed(SandboxCase):
    def test_an_empty_feed_is_not_an_error(self):
        billets, suite = self.transport.home_timeline()
        self.assertEqual(billets, [])
        self.assertEqual(suite, "")

    def test_the_posts_come_back(self):
        self.bac.publier(statut("3"), statut("2"), statut("1"))
        billets, _ = self.transport.home_timeline()
        self.assertEqual([b.post_id for b in billets], ["3", "2", "1"])

    def test_the_token_travels(self):
        self.bac.publier(statut("1"))
        self.transport.home_timeline()
        self.assertTrue(self.bac.demandes)

    def test_the_identity_answers(self):
        identite = self.transport.verify()
        self.assertEqual(identite["acct"], "moi")


class TestThePagingFollowsTheHeader(SandboxCase):
    """La suite est annoncée dans `Link`, pas dans le corps. Reprendre à
    l'identifiant du dernier billet reçu saute des billets dès qu'un trou
    apparaît entre deux demandes."""

    def setUp(self):
        super().setUp()
        self.bac.publier(*[statut(str(n)) for n in range(9, 0, -1)])

    def test_a_first_page_announces_a_next_one(self):
        billets, suite = self.transport.home_timeline(limit=4)
        self.assertEqual(len(billets), 4)
        self.assertTrue(suite)

    def test_the_next_page_continues_where_the_first_stopped(self):
        page, suite = self.transport.home_timeline(limit=4)
        suivante, _ = self.transport.home_timeline(cursor=suite)
        self.assertFalse(
            {b.post_id for b in page} & {b.post_id for b in suivante}
        )

    def test_the_header_is_found_whatever_its_case(self):
        """L'instance écrit `link` en minuscules — son cadre replie tout nom
        d'en-tête, et la version 3 du protocole qu'il emploie interdit les
        majuscules. Un client qui cherche `Link` à la lettre ne trouve rien,
        rend un curseur vide, et prend un succès pour une fin de fil.

        Le contrôle porte sur les DEUX casses : la réparation doit tenir
        quelle que soit celle qui arrive.
        """
        import http.client
        import io

        for casse in ("link", "Link", "LINK"):
            entetes = http.client.parse_headers(
                io.BytesIO(
                    f'{casse}: <https://i.exemple/suite>; rel="next"\r\n'
                    "\r\n".encode()
                )
            )
            self.assertEqual(
                _suivant(entetes.get("Link", "")),
                "https://i.exemple/suite",
                f"casse {casse!r} non reconnue",
            )

    def test_a_full_feed_still_announces_a_next_page(self):
        """L'instance annonce une suite dès que la page n'est pas vide.

        Elle construit ce lien à partir des billets qu'elle vient de
        rendre, sans savoir s'il en reste : la dernière page du fil en
        porte donc un, exactement comme les précédentes.
        """
        page, suite = self.transport.home_timeline(limit=40)
        self.assertEqual(len(page), 9)
        self.assertTrue(suite)

    def test_an_empty_page_announces_nothing(self):
        """Le vrai signal de fin, et le seul : plus rien à rendre."""
        _, suite = self.transport.home_timeline(limit=40)
        page, encore = self.transport.home_timeline(cursor=suite, limit=40)
        self.assertEqual(page, [])
        self.assertEqual(encore, "")

    def test_walking_the_whole_feed_sees_every_post(self):
        vus, curseur = [], ""
        for _ in range(10):
            page, curseur = self.transport.home_timeline(
                cursor=curseur, limit=2
            )
            vus.extend(b.post_id for b in page)
            if not curseur:
                break
        self.assertEqual(sorted(vus), sorted(str(n) for n in range(1, 10)))

    def test_the_cursor_may_be_a_token_that_cannot_be_rebuilt(self):
        """Une instance annonce la suite comme elle l'entend : un
        CONTINUATEUR opaque, et pas forcément l'identifiant d'un billet.

        Reconstruire l'URL soi-même à partir du dernier billet reçu
        redemanderait alors la première page, indéfiniment. C'est la raison
        pour laquelle le curseur traverse le client sans être interprété,
        du transport jusqu'au cache.
        """
        bac = SocialSandbox(pagination="jeton").start()
        self.addCleanup(bac.stop)
        bac.publier(*[statut(str(n)) for n in range(9, 0, -1)])
        compte = account_from_preset(
            "jeton", "@moi@i.exemple", "mastodon", base_url=bac.base_url
        )
        transport = MastodonTransport(compte, JETON, timeout=5)
        page, suite = transport.home_timeline(limit=4)
        self.assertIn("suite=k-", suite)
        suivante, _ = transport.home_timeline(cursor=suite)
        self.assertFalse(
            {b.post_id for b in page} & {b.post_id for b in suivante}
        )

    def test_a_limit_above_the_ceiling_is_brought_back_down(self):
        """Au-delà du plafond documenté, l'instance rend ce qu'elle veut."""
        self.transport.home_timeline(limit=500)
        self.assertIn("limit=40", self.bac.demandes[-1])


class TestWhatItDoesWithARefusal(SandboxCase):
    """Trois classes, parce que trois conduites s'ensuivent."""

    def test_a_refused_token_is_its_own_class(self):
        """Aucun nouvel essai ne le répare : il faut refaire autoriser."""
        self.bac.fail(Refuse())
        with self.assertRaises(SocialAuthError):
            self.transport.home_timeline()

    def test_a_wrong_token_is_refused_too(self):
        autre = MastodonTransport(self.account, "pas le bon", timeout=5)
        with self.assertRaises(SocialAuthError):
            autre.home_timeline()

    def test_a_rate_limit_says_when_to_come_back(self):
        """Réessayer avant allonge la coupure au lieu de l'abréger.

        L'instance écrit ce moment en ISO-8601, sous un nom d'en-tête qui
        ferait attendre un nombre. Ne lire qu'un nombre ne rendait donc
        jamais rien de cette instance : la coupure se répétait sans que le
        client sache l'attendre.
        """
        quand = int(time.time()) + 1234
        self.bac.fail(TropVite(reprise=quand))
        with self.assertRaises(SocialRateLimited) as pris:
            self.transport.home_timeline()
        self.assertEqual(pris.exception.reprise, float(quand))

    def test_a_rate_limit_is_not_an_authentication_failure(self):
        self.bac.fail(TropVite())
        with self.assertRaises(SocialRateLimited):
            self.transport.home_timeline()

    def test_a_broken_instance_is_an_ordinary_error(self):
        self.bac.fail(EnVrac())
        with self.assertRaises(SocialError) as pris:
            self.transport.home_timeline()
        self.assertNotIsInstance(pris.exception, SocialAuthError)

    def test_a_gateway_page_under_a_success_code_is_told(self):
        """Une passerelle qui intercale son HTML sous un 200 : le dire,
        plutôt que de planter sur le décodage."""
        self.bac.fail(Illisible())
        with self.assertRaises(SocialError):
            self.transport.home_timeline()

    def test_an_unreachable_instance_is_an_ordinary_error(self):
        mort = account_from_preset(
            "mort",
            "@x@y.exemple",
            "mastodon",
            base_url="http://127.0.0.1:1",
        )
        with self.assertRaises(SocialError):
            MastodonTransport(mort, JETON, timeout=2).home_timeline()

    def test_a_failure_in_the_middle_of_a_walk_is_raised(self):
        """La panne qui compte : la première page passe, la suivante non."""
        self.bac.publier(*[statut(str(n)) for n in range(9, 0, -1)])
        self.bac.fail(EnVrac(apres=1))
        _, suite = self.transport.home_timeline(limit=4)
        with self.assertRaises(SocialError):
            self.transport.home_timeline(cursor=suite)


class TestFromTheInstanceToTheCache(SandboxCase):
    """Le bout en bout de la tranche : ce que l'instance sert finit dans le
    cache, relisible, sans que rien ne touche le réseau."""

    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.addCleanup(self.store.close)
        self.fil = self.store.upsert_feed("home", "Accueil")

    def _rapporter(self) -> int:
        billets, suite = self.transport.home_timeline()
        combien = self.store.upsert_posts(self.fil, billets)
        self.store.set_feed_state("home", cursor=suite or None)
        return combien

    def test_the_posts_land_in_the_cache(self):
        self.bac.publier(statut("2", "second"), statut("1", "premier"))
        self.assertEqual(self._rapporter(), 2)
        self.assertEqual(self.store.count_posts(self.fil), 2)

    def test_the_text_is_readable_not_markup(self):
        self.bac.publier(statut("1", "un <b>vrai</b> message"))
        self._rapporter()
        garde = self.store.get_post(self.fil, "1")
        self.assertEqual(garde.text, "un vrai message")

    def test_a_second_pass_does_not_double_them(self):
        self.bac.publier(statut("1"))
        self._rapporter()
        self._rapporter()
        self.assertEqual(self.store.count_posts(self.fil), 1)

    def test_the_cursor_is_kept_for_the_next_pass(self):
        self.bac.publier(*[statut(str(n)) for n in range(50, 0, -1)])
        self._rapporter()
        self.assertTrue(self.store.feed_state("home")["cursor"])

    def test_the_attachments_survive_the_round_trip(self):
        self.bac.publier(
            statut("1", pieces=[piece(description="une affiche")])
        )
        self._rapporter()
        pieces = self.store.get_post(self.fil, "1").media
        self.assertEqual(pieces[0].description, "une affiche")


class TestWhenToComeBack(unittest.TestCase):
    """Trois services, trois écritures, UN sens.

    `reprise` porte toujours un instant. Un service le nomme, un autre
    donne un délai, et le même champ portait les deux : un délai pris pour
    un instant fait attendre jusqu'en 1970, et l'inverse pendant un
    demi-siècle. Le genre est donc déclaré par le transport, qui sait ce
    que son service écrit.
    """

    def test_a_delay_counts_from_now(self):
        avant = time.time()
        lu = instant_de_reprise(
            {"Retry-After": "120"}, (("Retry-After", DELAI),)
        )
        self.assertGreaterEqual(lu, avant + 120)
        self.assertLess(lu, avant + 125)

    def test_a_moment_is_taken_as_it_is(self):
        lu = instant_de_reprise(
            {"X-RateLimit-Reset": "1800000000"},
            (("X-RateLimit-Reset", INSTANT),),
        )
        self.assertEqual(lu, 1800000000.0)

    def test_an_iso_date_is_read(self):
        """Ce qu'une instance écrit vraiment, là où le nom de l'en-tête
        ferait attendre un nombre."""
        lu = instant_de_reprise(
            {"X-RateLimit-Reset": "2026-10-02T12:00:00.000Z"},
            (("X-RateLimit-Reset", INSTANT),),
        )
        self.assertEqual(
            lu,
            datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc).timestamp(),
        )

    def test_a_date_without_a_zone_is_read_as_utc(self):
        """La lire comme locale décalerait la reprise de l'écart du poste,
        donc d'une valeur qui change avec la machine."""
        lu = instant_de_reprise(
            {"X-RateLimit-Reset": "2026-10-02T12:00:00"},
            (("X-RateLimit-Reset", INSTANT),),
        )
        self.assertEqual(
            lu,
            datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc).timestamp(),
        )

    def test_an_http_date_is_a_moment_even_in_a_delay_header(self):
        """La seule écriture non numérique que `Retry-After` permette :
        elle nomme un moment, et ne s'ajoute donc pas à l'heure courante.
        """
        lu = instant_de_reprise(
            {"Retry-After": "Fri, 02 Oct 2026 12:00:00 GMT"},
            (("Retry-After", DELAI),),
        )
        self.assertEqual(
            lu,
            datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc).timestamp(),
        )

    def test_an_unreadable_value_is_not_invented(self):
        """None se dit « je ne sais pas ». Un nombre inventé serait pris
        pour une mesure, et l'appelant attendrait dessus."""
        self.assertIsNone(
            instant_de_reprise(
                {"Retry-After": "bientôt"}, (("Retry-After", DELAI),)
            )
        )

    def test_a_missing_header_falls_to_the_next_source(self):
        avant = time.time()
        lu = instant_de_reprise(
            {"Retry-After": "60"},
            (("X-RateLimit-Reset", INSTANT), ("Retry-After", DELAI)),
        )
        self.assertGreaterEqual(lu, avant + 60)

    def test_no_source_at_all_says_nothing(self):
        self.assertIsNone(instant_de_reprise({}, (("Retry-After", DELAI),)))
        self.assertIsNone(instant_de_reprise(None, (("Retry-After", DELAI),)))


if __name__ == "__main__":
    unittest.main()
