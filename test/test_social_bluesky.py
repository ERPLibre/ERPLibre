#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire et publier sur un dépôt de données personnel.

Rien ne touche le réseau : le dépôt est démarré par le test sur un port
éphémère de la boucle locale. Ce qui est éprouvé n'est pas la conformité du
service mais ce que le CLIENT en fait, et surtout les trois points par
lesquels ce réseau diffère du premier :

la session porte DEUX jetons, et le jeton d'accès expire en cours de route —
le rafraîchir est la seule réponse juste, redemander le mot de passe étant
l'erreur que le nom de l'erreur existe pour éviter ;

la suite d'une page vit dans le CORPS de la réponse, non dans un en-tête ;

publier, c'est écrire un enregistrement à une ADRESSE qu'on choisit, et
c'est elle qui tient lieu de clé d'idempotence.
"""

import unittest

from bluesky_sandbox import (
    MOT_DE_PASSE,
    BlueskySandbox,
    EnVrac,
    Illisible,
    JetonExpire,
    Refuse,
    TropVite,
    billet,
    image,
)

from script.todo.social.accounts import account_from_preset
from script.todo.social.bluesky import (
    LIMITE_CARACTERES,
    BlueskyTransport,
    billet_depuis_entree,
    nouvelle_adresse,
)
from script.todo.social.mastodon import (
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRefused,
)


class BlueskyCase(unittest.TestCase):
    def setUp(self):
        self.bac = BlueskySandbox().start()
        self.addCleanup(self.bac.stop)
        self.account = account_from_preset(
            "perso", "moi.exemple", "bluesky", base_url=self.bac.base_url
        )
        self.transport = BlueskyTransport(
            self.account, MOT_DE_PASSE, timeout=5
        )


class TestTheSession(BlueskyCase):
    def test_the_app_password_opens_it(self):
        identite = self.transport.ouvrir()
        self.assertEqual(identite["handle"], "moi.exemple")
        self.assertTrue(identite["did"])

    def test_a_wrong_password_is_an_authentication_failure(self):
        autre = BlueskyTransport(self.account, "pas le bon", timeout=5)
        with self.assertRaises(SocialAuthError):
            autre.ouvrir()

    def test_the_session_opens_itself_on_first_use(self):
        """L'appelant n'a pas à s'en souvenir : une lecture l'ouvre."""
        self.bac.publier(billet("a1"))
        self.transport.home_timeline()
        self.assertEqual(self.bac.sessions, 1)

    def test_it_is_opened_once_for_several_calls(self):
        self.bac.publier(billet("a1"))
        self.transport.home_timeline()
        self.transport.home_timeline()
        self.assertEqual(self.bac.sessions, 1)


class TestAnExpiredAccessToken(BlueskyCase):
    """Le point qui sépare ce réseau du premier."""

    def test_it_is_refreshed_not_asked_again(self):
        """Redemander le mot de passe serait l'erreur : il est bon, c'est le
        jeton d'accès qui a vécu."""
        self.bac.publier(billet("a1"))
        self.transport.home_timeline()
        self.bac.expire = True
        billets, _ = self.transport.home_timeline()
        self.assertEqual(self.bac.rafraichissements, 1)
        self.assertEqual(self.bac.sessions, 1)
        self.assertEqual(len(billets), 1)

    def test_the_call_goes_through_after_the_refresh(self):
        self.bac.publier(billet("a1", "revenu"))
        self.transport.ouvrir()
        self.bac.expire = True
        billets, _ = self.transport.home_timeline()
        self.assertEqual(billets[0].text, "revenu")

    def test_publishing_survives_it_too(self):
        self.transport.ouvrir()
        self.bac.expire = True
        self.transport.publish("Bonjour.")
        self.assertEqual(self.bac.rafraichissements, 1)
        self.assertEqual(len(self.bac.ecrits), 1)

    def test_a_refusal_that_is_not_expiry_is_not_retried(self):
        """Rafraîchir n'y changerait rien, et boucler ferait tourner le
        client indéfiniment."""
        self.transport.ouvrir()
        with self.assertRaises(SocialRefused):
            self.transport.publish("")
        self.assertEqual(self.bac.rafraichissements, 0)

    def test_only_one_refresh_is_attempted(self):
        """Un rafraîchissement qui ne suffit pas signifie autre chose qu'un
        jeton périmé."""
        self.transport.ouvrir()
        chemin = "/xrpc/app.bsky.feed"
        self.bac.fail(JetonExpire(sur=chemin))
        self.bac.fail(JetonExpire(sur=chemin))
        with self.assertRaises(SocialRefused):
            self.transport.home_timeline()
        self.assertEqual(self.bac.rafraichissements, 1)


class TestReadingTheFeed(BlueskyCase):
    def test_an_empty_feed_is_not_an_error(self):
        billets, suite = self.transport.home_timeline()
        self.assertEqual(billets, [])
        self.assertEqual(suite, "")

    def test_the_posts_come_back(self):
        self.bac.publier(billet("a3"), billet("a2"), billet("a1"))
        billets, _ = self.transport.home_timeline()
        self.assertEqual([b.post_id for b in billets], ["a3", "a2", "a1"])

    def test_the_cursor_comes_from_the_body(self):
        """L'autre réseau l'écrit dans un en-tête ; le cache n'a pas à
        connaître la différence."""
        self.bac.publier(*[billet(f"a{n}") for n in range(9)])
        _, suite = self.transport.home_timeline(limit=4)
        self.assertTrue(suite)

    def test_the_next_page_continues_where_the_first_stopped(self):
        self.bac.publier(*[billet(f"a{n}") for n in range(9)])
        page, suite = self.transport.home_timeline(limit=4)
        suivante, _ = self.transport.home_timeline(cursor=suite, limit=4)
        self.assertFalse(
            {b.post_id for b in page} & {b.post_id for b in suivante}
        )

    def test_the_last_page_announces_nothing(self):
        self.bac.publier(billet("a1"))
        _, suite = self.transport.home_timeline()
        self.assertEqual(suite, "")


class TestWhatAPostBecomes(unittest.TestCase):
    def test_the_author_and_the_text_are_read(self):
        meta = billet_depuis_entree(billet("a1", "salut"))
        self.assertEqual(meta.post_id, "a1")
        self.assertEqual(meta.author, "ana.exemple")
        self.assertEqual(meta.author_name, "Ana")
        self.assertEqual(meta.text, "salut")
        self.assertTrue(meta.created_at > 0)

    def test_a_reply_names_what_it_answers(self):
        meta = billet_depuis_entree(
            billet("a2", repond_a="at://did:plc:x/app.bsky.feed.post/a1")
        )
        self.assertEqual(meta.reply_to, "a1")

    def test_a_shared_post_is_marked(self):
        """Ce qui dit le partage vit À CÔTÉ du billet, non dedans : l'auteur
        reste celui qui a écrit."""
        meta = billet_depuis_entree(billet("a1", partage_par="cam.exemple"))
        self.assertTrue(meta.boost_of)
        self.assertEqual(meta.author, "ana.exemple")

    def test_an_ordinary_post_shares_nothing(self):
        self.assertEqual(billet_depuis_entree(billet("a1")).boost_of, "")

    def test_an_image_keeps_its_alternative_text(self):
        meta = billet_depuis_entree(
            billet("a1", images=[image(alt="un graphique")])
        )
        self.assertEqual(meta.media[0].description, "un graphique")
        self.assertEqual(meta.media[0].kind, "image")

    def test_an_unreadable_date_does_not_lose_the_post(self):
        meta = billet_depuis_entree(billet("a1", quand="pas une date"))
        self.assertEqual(meta.created_at, 0)
        self.assertEqual(meta.post_id, "a1")


class TestPublishing(BlueskyCase):
    def test_a_post_reaches_the_repository(self):
        meta = self.transport.publish("Bonjour le fil.")
        self.assertEqual(len(self.bac.ecrits), 1)
        self.assertEqual(meta.text, "Bonjour le fil.")

    def test_the_same_address_twice_writes_once(self):
        """L'adresse tient ici le rôle d'une clé d'idempotence : réécrire
        remplace au lieu d'ajouter."""
        self.transport.publish("Bonjour.", cle="rk-1")
        self.transport.publish("Bonjour.", cle="rk-1")
        self.assertEqual(len(self.bac.ecrits), 1)

    def test_a_fresh_address_each_try_would_double_it(self):
        """Le contrôle qui donne son sens au test précédent."""
        self.transport.publish("Bonjour.")
        self.transport.publish("Bonjour.")
        self.assertEqual(len(self.bac.ecrits), 2)

    def test_a_lost_answer_does_not_double_the_post(self):
        self.transport.ouvrir()
        self.bac.fail(EnVrac(sur="/xrpc/com.atproto.repo.putRecord"))
        with self.assertRaises(SocialError):
            self.transport.publish("Bonjour.", cle="rk-1")
        self.transport.publish("Bonjour.", cle="rk-1")
        self.assertEqual(len(self.bac.ecrits), 1)

    def test_an_address_is_generated_when_none_is_given(self):
        self.transport.publish("Bonjour.")
        self.assertEqual(len(self.bac.ecrits), 1)

    def test_addresses_grow_with_time(self):
        """Le service range un dépôt par adresse : tirées au hasard, elles
        y mêleraient les billets."""
        self.assertLess(nouvelle_adresse(), nouvelle_adresse())

    def test_a_reply_names_the_post_it_answers(self):
        self.transport.publish("Merci.", cle="rk-2", repond_a="rk-1")
        ecrit = self.bac.ecrits[f"at://{self.bac.did}/app.bsky.feed.post/rk-2"]
        self.assertIn("rk-1", ecrit["reply"]["parent"]["uri"])

    def test_an_empty_post_never_leaves(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("   ")
        self.assertEqual(self.bac.ecrits, {})

    def test_a_post_over_the_limit_never_leaves(self):
        """Refusé AVANT le réseau : la limite est celle du protocole, pas
        d'un dépôt, donc rien à demander pour la connaître."""
        with self.assertRaises(SocialRefused):
            self.transport.publish("a" * (LIMITE_CARACTERES + 1))
        self.assertEqual(self.bac.ecrits, {})

    def test_the_visibility_is_accepted_and_ignored(self):
        """Ce protocole ne porte pas cette notion. Prétendre l'honorer
        laisserait croire à une confidentialité qui n'existe pas ; la
        refuser obligerait l'appelant à distinguer les réseaux."""
        self.transport.publish("Bonjour.", cle="rk-1", visibilite="private")
        ecrit = self.bac.ecrits[f"at://{self.bac.did}/app.bsky.feed.post/rk-1"]
        self.assertNotIn("visibility", ecrit)


class TestWhatItDoesWithARefusal(BlueskyCase):
    def test_a_refused_credential_is_its_own_class(self):
        self.transport.ouvrir()
        self.bac.fail(Refuse(sur="/xrpc/app.bsky.feed"))
        with self.assertRaises(SocialAuthError):
            self.transport.home_timeline()

    def test_a_rate_limit_says_when_to_come_back(self):
        self.transport.ouvrir()
        self.bac.fail(TropVite(sur="/xrpc/app.bsky.feed", reprise=1234))
        with self.assertRaises(SocialRateLimited) as pris:
            self.transport.home_timeline()
        self.assertEqual(pris.exception.reprise, 1234)

    def test_a_broken_service_is_an_ordinary_error(self):
        self.transport.ouvrir()
        self.bac.fail(EnVrac(sur="/xrpc/app.bsky.feed"))
        with self.assertRaises(SocialError) as pris:
            self.transport.home_timeline()
        self.assertNotIsInstance(pris.exception, SocialAuthError)

    def test_a_gateway_page_under_a_success_code_is_told(self):
        self.transport.ouvrir()
        self.bac.fail(Illisible(sur="/xrpc/app.bsky.feed"))
        with self.assertRaises(SocialError):
            self.transport.home_timeline()

    def test_an_unreachable_service_is_an_ordinary_error(self):
        mort = account_from_preset(
            "mort", "x.exemple", "bluesky", base_url="http://127.0.0.1:1"
        )
        with self.assertRaises(SocialError):
            BlueskyTransport(mort, MOT_DE_PASSE, timeout=2).home_timeline()


if __name__ == "__main__":
    unittest.main()
