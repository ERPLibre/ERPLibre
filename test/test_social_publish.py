#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Publier un billet, et ne pas le publier deux fois.

La panne qui compte pour un envoi n'est pas le refus — c'est le SILENCE. Le
billet est posé, la réponse se perd en route, et l'appelant ne sait pas
lequel des deux mondes il habite. Réessayer au hasard publie en double ; ne
pas réessayer perd ce qu'on croyait envoyé.

La clé d'idempotence tranche : rejouée à l'identique, la demande rend le
billet déjà créé. Encore faut-il que l'appelant GARDE la clé d'un essai à
l'autre — en tirer une neuve à chaque reprise revient à ne pas en avoir, et
c'est l'erreur que ces tests interdisent.

L'autre partage est celui des refus : une instance qui répond non à un
billet vide ou trop long ne changera pas d'avis, alors qu'une passerelle en
vrac, oui. Les confondre fait boucler sur un non définitif.
"""

import unittest

from social_sandbox import (
    EnVrac,
    PerdueApres,
    Refuse,
    SocialSandbox,
    TropVite,
)

from script.todo.social.accounts import account_from_preset
from script.todo.social.mastodon import (
    LIMITE_PAR_DEFAUT,
    MastodonTransport,
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRefused,
)

JETON = "jeton-du-bac-a-sable"


class PublishCase(unittest.TestCase):
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


class TestWhatGoesOut(PublishCase):
    def test_a_post_reaches_the_instance(self):
        billet = self.transport.publish("Bonjour le fil.")
        self.assertEqual(len(self.bac.publies), 1)
        self.assertEqual(billet.text, "Bonjour le fil.")

    def test_it_comes_back_with_the_identifier_the_instance_chose(self):
        """C'est cet identifiant qu'il faudra renvoyer pour agir dessus ;
        celui que le client aurait inventé ne désignerait rien."""
        billet = self.transport.publish("Bonjour.")
        self.assertTrue(billet.post_id)
        self.assertEqual(billet.post_id, self.bac.publies[0][0]["id"])

    def test_the_author_is_the_account_that_published(self):
        billet = self.transport.publish("Bonjour.")
        self.assertEqual(billet.author, "moi")

    def test_a_reply_names_what_it_answers(self):
        billet = self.transport.publish("Merci.", repond_a="42")
        self.assertEqual(billet.reply_to, "42")

    def test_the_visibility_travels(self):
        self.transport.publish("Entre nous.", visibilite="private")
        self.assertEqual(self.bac.publies[0][0]["visibility"], "private")

    def test_a_public_post_is_the_default(self):
        """Le défaut le plus exposé est un choix : il doit être celui que
        la personne attend, non celui que le client trouve pratique."""
        self.transport.publish("Bonjour.")
        self.assertEqual(self.bac.publies[0][0]["visibility"], "public")


class TestPublishingTwiceIsRefused(PublishCase):
    """Le cœur de la tranche."""

    def test_the_same_key_twice_posts_once(self):
        self.transport.publish("Bonjour.", cle="k-1")
        self.transport.publish("Bonjour.", cle="k-1")
        self.assertEqual(len(self.bac.publies), 1)

    def test_the_second_call_returns_the_first_post(self):
        premier = self.transport.publish("Bonjour.", cle="k-1")
        second = self.transport.publish("Bonjour.", cle="k-1")
        self.assertEqual(premier.post_id, second.post_id)

    def test_a_lost_answer_does_not_double_the_post(self):
        """LA panne qui compte : l'instance a posé le billet, et la réponse
        se perd. L'appelant ne peut pas savoir ; il rejoue avec sa clé."""
        self.bac.fail(PerdueApres(sur="/api/v1/statuses"))
        with self.assertRaises(SocialError):
            self.transport.publish("Bonjour.", cle="k-1")
        self.assertEqual(len(self.bac.publies), 1)
        repris = self.transport.publish("Bonjour.", cle="k-1")
        self.assertEqual(len(self.bac.publies), 1)
        self.assertEqual(repris.text, "Bonjour.")

    def test_a_fresh_key_on_each_try_would_double_it(self):
        """Le contrôle qui donne son sens au test précédent : sans clé
        retenue, la même reprise publie deux fois."""
        self.bac.fail(PerdueApres(sur="/api/v1/statuses"))
        with self.assertRaises(SocialError):
            self.transport.publish("Bonjour.")
        self.transport.publish("Bonjour.")
        self.assertEqual(len(self.bac.publies), 2)

    def test_a_key_is_sent_even_when_the_caller_gives_none(self):
        """Sans clé du tout, l'instance ne pourrait rien reconnaître."""
        self.transport.publish("Bonjour.")
        self.assertTrue(self.bac.publies[0][1])

    def test_two_different_posts_are_both_published(self):
        self.transport.publish("Premier.", cle="k-1")
        self.transport.publish("Second.", cle="k-2")
        self.assertEqual(len(self.bac.publies), 2)


class TestWhatItRefuses(PublishCase):
    def test_an_empty_post_is_refused_for_good(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("   ")

    def test_a_post_over_the_limit_is_refused_for_good(self):
        with self.assertRaises(SocialRefused):
            self.transport.publish("a" * (self.bac.limite_caracteres + 1))

    def test_a_refusal_is_not_a_breakdown(self):
        """Elles se traitent autrement : l'une se corrige, l'autre
        s'attend. Les confondre fait boucler sur un non définitif."""
        self.bac.fail(EnVrac(sur="/api/v1/statuses"))
        with self.assertRaises(SocialError) as pris:
            self.transport.publish("Bonjour.")
        self.assertNotIsInstance(pris.exception, SocialRefused)

    def test_an_unknown_visibility_never_leaves(self):
        """Refusé AVANT le réseau : l'instance le refuserait, et lui
        demander de le dire coûte un aller-retour pour rien."""
        with self.assertRaises(SocialRefused):
            self.transport.publish("Bonjour.", visibilite="secret")
        self.assertEqual(self.bac.publies, [])

    def test_a_refused_token_stays_its_own_class(self):
        self.bac.fail(Refuse(sur="/api/v1/statuses"))
        with self.assertRaises(SocialAuthError):
            self.transport.publish("Bonjour.")

    def test_a_rate_limit_stays_its_own_class(self):
        self.bac.fail(TropVite(sur="/api/v1/statuses"))
        with self.assertRaises(SocialRateLimited):
            self.transport.publish("Bonjour.")


class TestTheLengthTheInstanceAllows(PublishCase):
    def test_it_is_asked_not_assumed(self):
        """Une instance relève ou abaisse la limite ; la supposer ferait
        refuser un billet sans pouvoir le dire à qui l'écrit."""
        self.bac.limite_caracteres = 1312
        self.assertEqual(self.transport.limite_caracteres(), 1312)

    def test_an_instance_that_does_not_say_falls_back(self):
        """Ne pas savoir ne doit pas empêcher de publier."""
        self.bac.fail(EnVrac(sur="/api/v1/instance"))
        self.assertEqual(self.transport.limite_caracteres(), LIMITE_PAR_DEFAUT)

    def test_a_post_at_the_limit_goes_through(self):
        self.bac.limite_caracteres = 20
        self.transport.publish("a" * 20)
        self.assertEqual(len(self.bac.publies), 1)


if __name__ == "__main__":
    unittest.main()
