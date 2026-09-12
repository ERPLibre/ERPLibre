#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le parcours d'autorisation : obtenir un premier jeton.

Le rafraîchissement suppose qu'un jeton existe déjà. Ce parcours est ce qui
le crée : le client ouvre la page de consentement du fournisseur, écoute sur
la boucle locale la redirection qui rapporte un code, et échange ce code
contre un jeu de jetons.

Rien de tout cela ne sort de la machine ici. Le faux point de jeton joue le
fournisseur, et le « navigateur » est un rappel injectable qui frappe
l'adresse de redirection — ce qu'un vrai navigateur fait de toute façon.

Ce qui est vérifié en priorité n'est pas le chemin heureux mais ce qui
protège : l'état qui interdit qu'une autre page injecte son code, le
vérificateur PKCE qui lie l'échange à la demande, le délai qui empêche
d'attendre pour toujours, et la socket qui se referme quoi qu'il arrive.
"""
import threading
import unittest
import urllib.parse
import urllib.request

from oauth_fake_server import FakeTokenEndpoint

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.oauth import OAuthError, authorization_url, authorize


class UrlCase(unittest.TestCase):
    def _reglages(self, **extra):
        reglages = {
            "auth_url": "https://exemple.invalide/authorize",
            "token_url": "https://exemple.invalide/token",
            "scope": "portee-a portee-b",
            "client_id": "client-de-test",
            "client_secret": "",
        }
        reglages.update(extra)
        return reglages

    def _params(self, **kwargs):
        url = authorization_url(
            self._reglages(),
            redirect_uri="http://127.0.0.1:1234/",
            state="etat-du-tour",
            code_challenge="empreinte",
            **kwargs,
        )
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))

    def test_it_asks_for_a_code_with_the_pkce_challenge(self):
        params = self._params()
        self.assertEqual(params["response_type"], "code")
        self.assertEqual(params["client_id"], "client-de-test")
        self.assertEqual(params["redirect_uri"], "http://127.0.0.1:1234/")
        self.assertEqual(params["code_challenge"], "empreinte")
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertEqual(params["state"], "etat-du-tour")
        self.assertEqual(params["scope"], "portee-a portee-b")

    def test_google_is_asked_for_a_refresh_token_explicitly(self):
        """Sans `access_type=offline`, Google rend un jeton d'accès et RIEN
        d'autre : le compte cesserait de fonctionner au bout d'une heure.
        `prompt=consent` le redonne à qui a déjà consenti une fois."""
        params = self._params(
            reclamer_hors_ligne=True,
        )
        self.assertEqual(params["access_type"], "offline")
        self.assertEqual(params["prompt"], "consent")

    def test_a_provider_that_does_not_want_them_gets_neither(self):
        params = self._params()
        self.assertNotIn("access_type", params)
        self.assertNotIn("prompt", params)

    def test_the_login_hint_travels_when_there_is_one(self):
        """Sur un poste où plusieurs comptes sont ouverts, la page demande
        lequel autoriser. L'indice évite d'autoriser le mauvais."""
        params = self._params(login_hint="moi@x.ca")
        self.assertEqual(params["login_hint"], "moi@x.ca")


class AuthorizeCase(unittest.TestCase):
    """Le parcours complet, sans navigateur et sans réseau extérieur."""

    def setUp(self):
        self.serveur = FakeTokenEndpoint()
        self.serveur.__enter__()
        self.addCleanup(self.serveur.__exit__)
        self.compte = account_from_preset(
            "perso", "moi@x.ca", "gmail", auth="oauth"
        )
        self.config = {
            ("mail", "oauth", "gmail", "client_id"): "client-de-test",
            ("mail", "oauth", "gmail", "token_url"): self.serveur.url,
            (
                "mail",
                "oauth",
                "gmail",
                "auth_url",
            ): "http://127.0.0.1:1/authorize",
        }

    def _config_get(self, cles):
        return self.config.get(tuple(cles))

    def _navigateur(self, *, code="le-code", etat=None, erreur=None):
        """Joue le navigateur : frappe l'adresse de redirection.

        La frappe part dans un FIL : `webbrowser.open` rend la main dès que
        le navigateur est lancé, et le client n'écoute la redirection
        qu'après. Frapper depuis le fil appelant attendrait une réponse que
        personne ne peut encore donner.
        """
        vues = []

        def frapper(url):
            params = dict(
                urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)
            )
            retour = params["redirect_uri"]
            champs = {"state": etat or params["state"]}
            if erreur:
                champs["error"] = erreur
            else:
                champs["code"] = code
            try:
                urllib.request.urlopen(
                    f"{retour}?{urllib.parse.urlencode(champs)}", timeout=5
                ).read()
            except Exception:
                # Le client a pu refermer sa socket avant de répondre ; ce
                # que le test vérifie est ce qu'il en fait, pas ce que le
                # navigateur reçoit.
                pass

        def ouvrir(url):
            vues.append(url)
            fil = threading.Thread(target=frapper, args=(url,), daemon=True)
            fil.start()
            self.addCleanup(fil.join, 5)

        ouvrir.vues = vues
        return ouvrir

    def test_it_brings_back_a_full_token_set(self):
        from oauth_fake_server import ACCESS_TOKEN, REFRESH_TOKEN

        jeu = authorize(
            self.compte,
            config_get=self._config_get,
            open_browser=self._navigateur(),
        )
        self.assertEqual(jeu.refresh_token, REFRESH_TOKEN)
        self.assertEqual(jeu.access_token, ACCESS_TOKEN)
        self.assertFalse(jeu.is_stale())

    def test_the_exchange_carries_the_code_and_its_verifier(self):
        """PKCE : sans le vérificateur, un code intercepté suffirait à
        obtenir le jeton. Le fournisseur vérifie qu'il correspond à
        l'empreinte envoyée à la demande."""
        authorize(
            self.compte,
            config_get=self._config_get,
            open_browser=self._navigateur(code="le-code"),
        )
        _, champs = self.serveur.seen[0]
        self.assertEqual(champs["grant_type"], "authorization_code")
        self.assertEqual(champs["code"], "le-code")
        self.assertTrue(champs["code_verifier"])
        self.assertGreaterEqual(len(champs["code_verifier"]), 43)

    def test_a_redirection_with_the_wrong_state_is_refused(self):
        """L'état lie la redirection à la demande. Sans lui, n'importe
        quelle page ouverte sur ce poste peut faire échanger SON code par
        notre client, et le compte lié serait celui de l'attaquant."""
        with self.assertRaises(OAuthError):
            authorize(
                self.compte,
                config_get=self._config_get,
                open_browser=self._navigateur(etat="etat-d-un-autre"),
                timeout=5,
            )
        self.assertEqual(self.serveur.seen, [])

    def test_a_refusal_by_the_user_is_said_plainly(self):
        with self.assertRaises(OAuthError) as capture:
            authorize(
                self.compte,
                config_get=self._config_get,
                open_browser=self._navigateur(erreur="access_denied"),
                timeout=5,
            )
        self.assertIn("access_denied", str(capture.exception))
        self.assertEqual(self.serveur.seen, [])

    def test_nobody_answering_ends_in_a_timeout_not_a_hang(self):
        with self.assertRaises(OAuthError):
            authorize(
                self.compte,
                config_get=self._config_get,
                open_browser=lambda url: None,
                timeout=1,
            )

    def test_the_local_port_is_released_even_when_it_fails(self):
        """Une socket d'écoute oubliée par un parcours abandonné resterait
        ouverte jusqu'à la fin du programme."""
        import socket

        vus = []

        def noter(url):
            params = dict(
                urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)
            )
            vus.append(urllib.parse.urlparse(params["redirect_uri"]).port)

        with self.assertRaises(OAuthError):
            authorize(
                self.compte,
                config_get=self._config_get,
                open_browser=noter,
                timeout=1,
            )
        with socket.socket() as sonde:
            sonde.settimeout(1)
            self.assertNotEqual(sonde.connect_ex(("127.0.0.1", vus[0])), 0)

    def test_it_listens_on_the_loopback_only(self):
        """Écouter sur toutes les interfaces exposerait le code
        d'autorisation au réseau local le temps du parcours."""
        vues = []

        def noter(url):
            params = dict(
                urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)
            )
            vues.append(params["redirect_uri"])

        with self.assertRaises(OAuthError):
            authorize(
                self.compte,
                config_get=self._config_get,
                open_browser=noter,
                timeout=1,
            )
        self.assertTrue(vues[0].startswith("http://127.0.0.1:"))

    def test_without_a_client_id_no_browser_is_ever_opened(self):
        """Le dépôt n'en livre aucun : ouvrir une page qui affichera
        « invalid_client » ferait chercher la panne chez le fournisseur."""
        self.config.pop(("mail", "oauth", "gmail", "client_id"))
        ouvert = []
        with self.assertRaises(OAuthError) as capture:
            authorize(
                self.compte,
                config_get=self._config_get,
                open_browser=lambda url: ouvert.append(url),
            )
        self.assertEqual(ouvert, [])
        self.assertIn("client_id", str(capture.exception))


if __name__ == "__main__":
    unittest.main()
