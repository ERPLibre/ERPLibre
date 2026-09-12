#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le rafraîchissement d'un jeton OAuth.

C'est la seule partie d'OAuth qui s'exécute sans personne devant l'écran :
elle doit donc dire clairement ce qui lui arrive. Trois issues, et le
client doit les distinguer, parce que le remède diffère à chaque fois :

- le jeton neuf est arrivé ;
- le fournisseur a révoqué l'autorisation — aucun nouvel essai ne la
  rendra, il faut refaire autoriser le compte ;
- le fournisseur n'a pas répondu, ou a répondu n'importe quoi — on
  réessaiera plus tard, et le jeton en place reste valable.

Les tests parlent à un faux point de jeton sur 127.0.0.1 : rien ne sort de
la machine, et les pannes sont commandées plutôt qu'attendues.
"""
import json
import unittest

from oauth_fake_server import (
    ACCESS_TOKEN,
    Cut,
    FakeTokenEndpoint,
    Malformed,
    Revoked,
    ServerError,
)

from script.todo.mail.oauth import (
    OAuthError,
    RefreshRefused,
    TokenSet,
    refresh,
)


class TokenSetCase(unittest.TestCase):
    """Le jeu de jetons voyage dans UNE chaîne.

    Le coffre ne transporte qu'une chaîne par référence : y ranger trois
    valeurs demanderait trois entrées, donc trois écritures à garder
    cohérentes. Une seule chaîne JSON tient dans l'entrée existante.
    """

    def test_it_survives_the_round_trip_through_one_string(self):
        jeu = TokenSet(
            refresh_token="r", access_token="a", expires_at=1_800_000_000
        )
        self.assertEqual(TokenSet.from_json(jeu.to_json()), jeu)

    def test_an_empty_string_gives_an_empty_set_not_a_crash(self):
        """Le coffre rend `None` ou la chaîne vide quand rien n'y est
        rangé. Lever ici ferait passer « pas encore de jeton » pour un
        cache corrompu."""
        self.assertEqual(TokenSet.from_json(""), TokenSet())
        self.assertEqual(TokenSet.from_json(None), TokenSet())

    def test_a_string_that_is_not_json_is_read_as_a_bare_refresh_token(self):
        """Ce qu'on colle à la main est un jeton de rafraîchissement, pas du
        JSON. Le refuser obligerait l'utilisateur à fabriquer un objet."""
        self.assertEqual(
            TokenSet.from_json("1//collé-à-la-main").refresh_token,
            "1//collé-à-la-main",
        )

    def test_a_set_without_an_access_token_is_stale(self):
        self.assertTrue(TokenSet(refresh_token="r").is_stale())

    def test_a_set_that_expires_soon_is_stale_before_it_expires(self):
        """Rafraîchir À l'expiration laisse la connexion partir avec un
        jeton qui meurt pendant l'échange. La marge est ce qui évite un
        refus sur deux."""
        import time

        presque = TokenSet(
            refresh_token="r", access_token="a", expires_at=time.time() + 5
        )
        self.assertTrue(presque.is_stale())

    def test_a_fresh_set_is_not_stale(self):
        import time

        bon = TokenSet(
            refresh_token="r", access_token="a", expires_at=time.time() + 3600
        )
        self.assertFalse(bon.is_stale())


class RefreshCase(unittest.TestCase):
    def setUp(self):
        self.serveur = FakeTokenEndpoint()
        self.serveur.__enter__()
        self.addCleanup(self.serveur.__exit__)
        self.jeu = TokenSet(refresh_token="r-ancien")

    def _refresh(self):
        return refresh(
            self.jeu,
            token_url=self.serveur.url,
            client_id="client-de-test",
        )

    def test_it_brings_back_a_new_access_token(self):
        neuf = self._refresh()
        self.assertEqual(neuf.access_token, ACCESS_TOKEN)
        self.assertFalse(neuf.is_stale())

    def test_it_keeps_the_refresh_token_the_provider_did_not_resend(self):
        """Google ne renvoie PAS le jeton de rafraîchissement à chaque
        échange. L'écraser par le vide déconnecterait le compte au premier
        rafraîchissement réussi — la panne la plus cruelle possible."""
        self.assertEqual(self._refresh().refresh_token, "r-ancien")

    def test_it_sends_the_refresh_token_and_never_a_password(self):
        self._refresh()
        _, champs = self.serveur.seen[0]
        self.assertEqual(champs["grant_type"], "refresh_token")
        self.assertEqual(champs["refresh_token"], "r-ancien")
        self.assertNotIn("password", champs)

    def test_a_revoked_grant_is_its_own_refusal(self):
        """Réessayer ne le réparera pas : c'est ce que ce type dit, et
        c'est pourquoi il ne se confond pas avec une panne."""
        self.serveur.fail(Revoked())
        with self.assertRaises(RefreshRefused):
            self._refresh()

    def test_a_server_error_is_not_a_refusal(self):
        """Le contrôle symétrique : une panne passagère ne doit pas envoyer
        l'utilisateur refaire autoriser son compte."""
        self.serveur.fail(ServerError())
        with self.assertRaises(OAuthError) as capture:
            self._refresh()
        self.assertNotIsInstance(capture.exception, RefreshRefused)

    def test_a_body_that_is_not_json_does_not_crash_the_client(self):
        self.serveur.fail(Malformed())
        with self.assertRaises(OAuthError) as capture:
            self._refresh()
        self.assertNotIsInstance(capture.exception, RefreshRefused)

    def test_a_cut_connection_is_a_failure_not_a_half_token(self):
        """Un corps tronqué ne doit jamais rendre un jeu de jetons
        partiel : il serait rangé au coffre et refusé à chaque connexion."""
        self.serveur.fail(Cut())
        with self.assertRaises(OAuthError):
            self._refresh()

    def test_a_dead_endpoint_fails_without_hanging(self):
        """Personne n'est devant l'écran : un rafraîchissement sans délai
        gèlerait la synchronisation pour toujours."""
        from script.todo.mail.oauth import refresh as vrai_refresh

        with self.assertRaises(OAuthError):
            vrai_refresh(
                self.jeu,
                token_url="http://127.0.0.1:9/token",
                client_id="client-de-test",
                timeout=2,
            )

    def test_a_set_with_no_refresh_token_refuses_before_the_network(self):
        """Rien à échanger : partir quand même ferait porter au serveur le
        soin de dire ce qu'on savait déjà."""
        self.jeu = TokenSet()
        with self.assertRaises(RefreshRefused):
            self._refresh()
        self.assertEqual(self.serveur.seen, [])

    def test_a_missing_client_id_says_so_before_the_network(self):
        """Le dépôt ne livre aucun identifiant client : le champ vide est
        l'état NORMAL, et le message doit dire quoi faire plutôt que de
        laisser le fournisseur répondre « invalid_client »."""
        with self.assertRaises(OAuthError) as capture:
            refresh(self.jeu, token_url=self.serveur.url, client_id="")
        self.assertEqual(self.serveur.seen, [])
        self.assertIn("client_id", str(capture.exception))

    def test_the_client_secret_is_sent_only_when_there_is_one(self):
        """Un client installé n'en a pas toujours ; en envoyer un vide fait
        refuser l'échange par certains fournisseurs."""
        refresh(
            self.jeu,
            token_url=self.serveur.url,
            client_id="client-de-test",
        )
        _, champs = self.serveur.seen[0]
        self.assertNotIn("client_secret", champs)

    def test_a_provider_that_resends_a_refresh_token_replaces_the_old_one(
        self,
    ):
        """Microsoft en renvoie un à chaque échange, et l'ancien cesse de
        valoir. Le garder déconnecterait le compte au rafraîchissement
        suivant."""
        import script.todo.mail.oauth as oauth

        charge = json.dumps(
            {
                "access_token": "a",
                "refresh_token": "r-neuf",
                "expires_in": 60,
            }
        ).encode()
        neuf = oauth._depuis_charge(charge, TokenSet(refresh_token="r-ancien"))
        self.assertEqual(neuf.refresh_token, "r-neuf")


if __name__ == "__main__":
    unittest.main()
