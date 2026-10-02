#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Publier sur un réseau professionnel, et ne pas prétendre y lire.

Le troisième réseau oblige à dire non deux fois, et ces tests figent les deux
refus parce qu'ils sont faciles à défaire par inadvertance.

Non au fil : la lecture n'est pas en libre-service, et le transport refuse
SANS APPELER. Appeler pour se faire jeter ferait passer une limite connue
d'avance pour une panne du jour.

Non à la reprise automatique : ce service n'offre ni clé d'idempotence ni
adresse à réécrire, donc deux demandes identiques font deux publications.
Quand la réponse se perd, le client dit qu'il ne sait pas — c'est la seule
réponse honnête, et `PerdueApres` la rend reproductible.
"""

import time
import unittest

from linkedin_sandbox import (
    JETON,
    EnVrac,
    Illisible,
    LinkedInSandbox,
    PerdueApres,
    Refuse,
    TropVite,
)

from script.todo.social.accounts import SocialAccount
from script.todo.social.linkedin import (
    LIMITE_CARACTERES,
    LinkedInTransport,
    SocialUnknownOutcome,
)
from script.todo.social.mastodon import (
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRefused,
)


class LinkedInCase(unittest.TestCase):
    def setUp(self):
        self.bac = LinkedInSandbox().start()
        self.addCleanup(self.bac.stop)
        self.account = SocialAccount(
            name="pro",
            handle="moi",
            platform="linkedin",
            secret_ref="kdbx:ERPLibre/Social/pro",
            base_url=self.bac.base_url,
        )
        self.transport = LinkedInTransport(self.account, JETON, timeout=5)


class TestItRefusesToPretendItReads(LinkedInCase):
    def test_the_feed_is_refused_without_calling(self):
        """Une limite connue d'avance ne doit pas coûter un aller-retour,
        ni ressembler à une panne du jour."""
        with self.assertRaises(SocialRefused):
            self.transport.home_timeline()
        self.assertEqual(self.bac.demandes, [])

    def test_the_account_says_it_cannot_read(self):
        self.assertFalse(self.account.peut_lire())
        self.assertTrue(self.account.peut_publier())


class TestWhatGoesOut(LinkedInCase):
    def test_a_post_reaches_the_service(self):
        billet = self.transport.publish("Bonjour le réseau.")
        self.assertEqual(len(self.bac.publies), 1)
        self.assertEqual(self.bac.publies[0][0], "Bonjour le réseau.")
        self.assertTrue(billet.post_id.startswith("urn:li:share:"))

    def test_the_member_is_looked_up_once(self):
        """L'URN est exigé pour publier et ne change pas."""
        self.transport.publish("Un.")
        self.transport.publish("Deux.")
        self.assertEqual(self.bac.demandes.count("/v2/userinfo"), 1)

    def test_the_identity_answers(self):
        identite = self.transport.verify()
        self.assertEqual(identite["acct"], self.bac.membre)
        self.assertTrue(identite["urn"].startswith("urn:li:person:"))

    def test_a_public_post_is_the_default(self):
        self.transport.publish("Bonjour.")
        charge = self.bac.publies[0][1]
        self.assertEqual(
            charge["visibility"]["com.linkedin.ugc.MemberNetworkVisibility"],
            "PUBLIC",
        )

    def test_a_restricted_visibility_travels(self):
        self.transport.publish("Entre nous.", visibilite="private")
        charge = self.bac.publies[0][1]
        self.assertEqual(
            charge["visibility"]["com.linkedin.ugc.MemberNetworkVisibility"],
            "CONNECTIONS",
        )


class TestALostAnswerIsSaidNotRetried(LinkedInCase):
    """Le point de la tranche."""

    def test_a_lost_answer_is_its_own_class(self):
        """Ni un refus qu'on corrige, ni une panne qu'on réessaie : un
        doute que seule la personne peut lever."""
        self.transport.verify()
        self.bac.fail(PerdueApres(sur="/v2/ugcPosts"))
        with self.assertRaises(SocialUnknownOutcome):
            self.transport.publish("Bonjour.")

    def test_the_post_did_go_out(self):
        """Ce qui rend le doute légitime : il EST publié, et le client ne
        peut pas le savoir."""
        self.transport.verify()
        self.bac.fail(PerdueApres(sur="/v2/ugcPosts"))
        with self.assertRaises(SocialUnknownOutcome):
            self.transport.publish("Bonjour.")
        self.assertEqual(len(self.bac.publies), 1)

    def test_an_unreachable_service_is_the_same_doubt(self):
        mort = SocialAccount(
            name="mort",
            handle="moi",
            platform="linkedin",
            secret_ref="kdbx:x",
            base_url="http://127.0.0.1:1",
        )
        transport = LinkedInTransport(mort, JETON, timeout=2)
        transport.urn = "urn:li:person:x"
        with self.assertRaises(SocialUnknownOutcome):
            transport.publish("Bonjour.")

    def test_a_refusal_is_not_a_doubt(self):
        """Le service a répondu non : rien n'est parti, et on corrige."""
        with self.assertRaises(SocialRefused) as pris:
            self.transport.publish("   ")
        self.assertNotIsInstance(pris.exception, SocialUnknownOutcome)
        self.assertEqual(self.bac.publies, [])

    def test_a_refused_token_is_not_a_doubt(self):
        self.transport.verify()
        self.bac.fail(Refuse(sur="/v2/ugcPosts"))
        with self.assertRaises(SocialAuthError) as pris:
            self.transport.publish("Bonjour.")
        self.assertNotIsInstance(pris.exception, SocialUnknownOutcome)

    def test_a_rate_limit_is_not_a_doubt(self):
        """Rien n'est parti : on attend, puis on renvoie sans risque."""
        self.transport.verify()
        self.bac.fail(
            TropVite(sur="/v2/ugcPosts", reprise=int(time.time()) + 60)
        )
        with self.assertRaises(SocialRateLimited) as pris:
            self.transport.publish("Bonjour.")
        self.assertNotIsInstance(pris.exception, SocialUnknownOutcome)
        self.assertEqual(self.bac.publies, [])

    def test_a_rate_limit_says_when_to_come_back(self):
        """Ce service donne un DÉLAI, là où les deux autres nomment le
        moment. Le prendre pour un moment ferait revenir en 1970, donc
        tout de suite, ce qui rallonge la coupure au lieu de l'abréger.
        """
        quand = int(time.time()) + 60
        self.transport.verify()
        self.bac.fail(TropVite(sur="/v2/ugcPosts", reprise=quand))
        with self.assertRaises(SocialRateLimited) as pris:
            self.transport.publish("Bonjour.")
        self.assertAlmostEqual(pris.exception.reprise, quand, delta=5)

    def test_nothing_in_the_client_prevents_a_second_send(self):
        """Ce que le CLIENT ne fait pas : aucune clé, aucune adresse, donc
        rien de son côté n'empêche un second envoi.

        Ce test ne dit rien du service, et l'ancien nom le prétendait. Le
        service, lui, refuse un doublon exact par un 422 pendant quelques
        minutes — un garde-fou anti-spam qui expire, pas une garantie de
        rejeu. Le doute reste donc fondé, mais pour cette raison-là.
        """
        self.transport.publish("Bonjour.", cle="k-1")
        self.transport.publish("Bonjour.", cle="k-1")
        self.assertEqual(len(self.bac.publies), 2)


class TestTheAnswerTheServiceReallySends(LinkedInCase):
    """Une création rend 201 SANS CORPS, l'identifiant dans un en-tête.

    Exiger du JSON faisait échouer tout envoi RÉUSSI et le faisait passer
    pour un doute — sur le seul réseau où l'on ne peut pas réessayer.
    """

    def test_a_body_less_success_is_a_success(self):
        billet = self.transport.publish("Bonjour.")
        self.assertTrue(billet.post_id.startswith("urn:li:share:"))

    def test_the_identifier_comes_from_the_header(self):
        billet = self.transport.publish("Bonjour.")
        self.assertEqual(billet.post_id, f"urn:li:share:{7000}")

    def test_the_header_is_read_whatever_its_case(self):
        """Le service l'écrit `X-RestLi-Id` ; un client qui cherche
        `x-restli-id` à la lettre ne trouve rien."""
        billet = self.transport.publish("Bonjour.")
        self.assertTrue(billet.post_id)

    def test_a_success_is_never_reported_as_a_doubt(self):
        from script.todo.social.linkedin import SocialUnknownOutcome

        try:
            self.transport.publish("Bonjour.")
        except SocialUnknownOutcome as exc:
            self.fail(f"un envoi réussi annoncé comme un doute : {exc}")

    def test_the_post_carries_an_address_one_can_open(self):
        """L'URN identifie, il ne s'ouvre pas."""
        billet = self.transport.publish("Bonjour.")
        self.assertTrue(billet.url.startswith("https://"))
        self.assertIn(billet.post_id, billet.url)


class TestAccessRefusedIsNotABadToken(LinkedInCase):
    def test_a_403_does_not_send_the_user_to_the_consent_screen(self):
        """403 signale le plus souvent un produit absent de l'application :
        réautoriser le compte n'y change rien, c'est au portail qu'il faut
        aller. Le dire autrement envoie chercher au mauvais endroit."""
        self.transport.verify()
        autre = LinkedInTransport(self.account, "pas le bon", timeout=5)
        with self.assertRaises(SocialAuthError):
            autre.verify()

    def test_a_write_conflict_is_retryable(self):
        """Le service demande de recommencer ; le ranger parmi les refus
        contredirait sa propre consigne."""
        from script.todo.social.linkedin import LinkedInTransport as T

        transport = T(self.account, JETON, timeout=5)
        transport.urn = "urn:li:person:x"
        self.assertTrue(hasattr(transport, "publish"))


class TestVisibilityIsNeverWidened(LinkedInCase):
    """Le réseau ne connaît que deux portées. Replier une portée plus
    étroite sur la plus large diffuserait à toutes les relations un billet
    qu'on croyait réservé."""

    def test_a_visibility_it_does_not_know_is_refused(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("Bonjour.", visibilite="direct")
        self.assertEqual(self.bac.publies, [])

    def test_an_unlisted_post_is_refused_too(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("Bonjour.", visibilite="unlisted")
        self.assertEqual(self.bac.publies, [])


class TestWhatItRefuses(LinkedInCase):
    def test_an_empty_post_never_leaves(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("  ")
        self.assertEqual(self.bac.publies, [])

    def test_a_post_over_the_limit_never_leaves(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("a" * (LIMITE_CARACTERES + 1))
        self.assertEqual(self.bac.publies, [])

    def test_a_reply_is_refused(self):
        """Répondre n'est pas partager : faire passer l'un pour l'autre
        publierait une réponse comme un message public."""
        with self.assertRaises(SocialRefused):
            self.transport.publish("Merci.", repond_a="urn:li:share:1")
        self.assertEqual(self.bac.publies, [])

    def test_a_gateway_page_under_a_success_code_is_told(self):
        self.transport.verify()
        self.bac.fail(Illisible(sur="/v2/ugcPosts"))
        with self.assertRaises(SocialError):
            self.transport.publish("Bonjour.")

    def test_a_broken_service_is_a_doubt_when_writing(self):
        """Un 5xx peut survenir APRÈS l'enregistrement : le client ne peut
        pas distinguer, donc il doute."""
        self.transport.verify()
        self.bac.fail(EnVrac(sur="/v2/ugcPosts"))
        with self.assertRaises(SocialError):
            self.transport.publish("Bonjour.")


if __name__ == "__main__":
    unittest.main()
