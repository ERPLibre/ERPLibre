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


class FauxCoffre:
    """Le minimum dont le client se sert : un get et un set."""

    def __init__(self, contenu=None):
        self.contenu = dict(contenu or {})
        self.ecritures = []

    def get(self, ref):
        return self.contenu.get(ref)

    def set(self, ref, valeur):
        self.contenu[ref] = valeur
        self.ecritures.append(ref)


class SettingsCase(unittest.TestCase):
    """Les réglages OAuth d'un compte : d'où ils viennent, dans quel ordre.

    Le dépôt ne livre AUCUN identifiant client : les points de service sont
    connus, l'identité ne l'est pas. Elle vient de celui qui déploie.
    """

    def _compte(self, preset="gmail"):
        from script.todo.mail.accounts import account_from_preset

        return account_from_preset("perso", "a@x.ca", preset, auth="oauth")

    def test_the_endpoints_come_from_the_preset(self):
        from script.todo.mail.oauth import settings_for

        reglages = settings_for(self._compte())
        self.assertIn("google", reglages["token_url"])
        self.assertTrue(reglages["scope"])

    def test_the_client_id_is_empty_until_someone_provides_one(self):
        """L'état normal d'une installation neuve, et non une erreur."""
        from script.todo.mail.oauth import settings_for

        self.assertEqual(settings_for(self._compte())["client_id"], "")

    def test_the_configuration_provides_the_identity(self):
        from script.todo.mail.oauth import settings_for

        table = {
            ("mail", "oauth", "gmail", "client_id"): "de-la-configuration"
        }
        reglages = settings_for(
            self._compte(), config_get=lambda cles: table.get(tuple(cles))
        )
        self.assertEqual(reglages["client_id"], "de-la-configuration")

    def test_an_environment_variable_serves_when_there_is_no_config(self):
        """Le cas du conteneur, où le fichier de configuration n'est pas
        celui de l'utilisateur."""
        from unittest.mock import patch

        from script.todo.mail.oauth import settings_for

        with patch.dict(
            "os.environ",
            {"ERPLIBRE_MAIL_OAUTH_CLIENT_ID": "de-l-environnement"},
        ):
            self.assertEqual(
                settings_for(self._compte())["client_id"],
                "de-l-environnement",
            )

    def test_the_configuration_wins_over_the_environment(self):
        from unittest.mock import patch

        from script.todo.mail.oauth import settings_for

        table = {("mail", "oauth", "gmail", "client_id"): "de-la-config"}
        with patch.dict(
            "os.environ", {"ERPLIBRE_MAIL_OAUTH_CLIENT_ID": "de-l-env"}
        ):
            reglages = settings_for(
                self._compte(), config_get=lambda cles: table.get(tuple(cles))
            )
        self.assertEqual(reglages["client_id"], "de-la-config")

    def test_a_provider_without_oauth_says_so_rather_than_guessing(self):
        """iCloud n'offre pas OAuth. Inventer un point de service ferait
        échouer la connexion sur un message qui n'apprend rien."""
        from script.todo.mail.oauth import OAuthError, settings_for

        with self.assertRaises(OAuthError):
            settings_for(self._compte("icloud"))


class SecretForCase(unittest.TestCase):
    """Ce qu'on présente au serveur, selon le genre du compte.

    Un seul point de décision : les appelants passent le secret rendu ici à
    `connect()`, sans avoir à savoir ce qu'il est.
    """

    def _compte(self, auth="oauth"):
        from script.todo.mail.accounts import account_from_preset

        return account_from_preset("perso", "a@x.ca", "gmail", auth=auth)

    def test_a_password_account_gets_its_password(self):
        from script.todo.mail.oauth import secret_for

        compte = self._compte(auth="login")
        coffre = FauxCoffre({compte.secret_ref: "mon-mot-de-passe"})
        self.assertEqual(secret_for(compte, coffre), "mon-mot-de-passe")

    def test_a_fresh_token_is_used_without_touching_the_network(self):
        import time

        from script.todo.mail.oauth import TokenSet, secret_for

        compte = self._compte()
        jeu = TokenSet(
            refresh_token="r",
            access_token="a-frais",
            expires_at=time.time() + 3600,
        )
        coffre = FauxCoffre({compte.refresh_token_ref(): jeu.to_json()})
        appels = []
        self.assertEqual(
            secret_for(
                compte,
                coffre,
                refresh_fn=lambda *a, **k: appels.append(1),
            ),
            "a-frais",
        )
        self.assertEqual(appels, [])

    def test_a_stale_token_is_refreshed_and_written_back(self):
        """Sans réécriture, chaque ouverture de session rafraîchirait de
        nouveau : le fournisseur compte ces échanges."""
        from script.todo.mail.oauth import TokenSet, secret_for

        compte = self._compte()
        coffre = FauxCoffre({compte.refresh_token_ref(): "r-collé"})
        neuf = TokenSet(
            refresh_token="r-collé", access_token="a-neuf", expires_at=9e9
        )
        secret = secret_for(compte, coffre, refresh_fn=lambda *a, **k: neuf)
        self.assertEqual(secret, "a-neuf")
        self.assertEqual(
            coffre.contenu[compte.refresh_token_ref()], neuf.to_json()
        )

    def test_the_password_entry_is_never_touched_by_a_token_account(self):
        """Les deux références vivent côte à côte : un compte qui repasse
        au mot de passe doit retrouver le sien."""
        from script.todo.mail.oauth import TokenSet, secret_for

        compte = self._compte()
        coffre = FauxCoffre(
            {
                compte.secret_ref: "mot-de-passe-d-avant",
                compte.refresh_token_ref(): "r",
            }
        )
        neuf = TokenSet(refresh_token="r", access_token="a", expires_at=9e9)
        secret_for(compte, coffre, refresh_fn=lambda *a, **k: neuf)
        self.assertEqual(
            coffre.contenu[compte.secret_ref], "mot-de-passe-d-avant"
        )
        self.assertNotIn(compte.secret_ref, coffre.ecritures)

    def test_a_revoked_grant_surfaces_instead_of_an_empty_secret(self):
        """Rendre une chaîne vide ferait échouer la connexion sur « mot de
        passe refusé », et le compte paraîtrait mal configuré."""
        from script.todo.mail.oauth import RefreshRefused, secret_for

        compte = self._compte()
        coffre = FauxCoffre({compte.refresh_token_ref(): "r"})

        def revoque(*a, **k):
            raise RefreshRefused("révoqué")

        with self.assertRaises(RefreshRefused):
            secret_for(compte, coffre, refresh_fn=revoque)

    def test_an_account_with_no_token_at_all_says_which_one_is_missing(self):
        from script.todo.mail.oauth import RefreshRefused, secret_for

        compte = self._compte()
        with self.assertRaises(RefreshRefused):
            secret_for(compte, FauxCoffre())


class SessionCase(unittest.TestCase):
    """L'ouverture d'une session, bout en bout, sans réseau.

    Le jeton se rafraîchit AVANT la connexion et dans le fil principal :
    `SecretStore.set` réécrit le coffre entier, et deux fils de
    synchronisation qui écriraient ensemble le corrompraient.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path

        from script.todo.mail.accounts import account_from_preset

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.compte = account_from_preset(
            "perso", "a@x.ca", "gmail", auth="oauth"
        )
        self.compte.cache_mode = "clear"

    def _ouvrir(self, coffre, refresh_fn):
        from unittest.mock import patch

        from script.todo.mail.tui import open_session

        vus = []
        with patch("script.todo.mail.oauth.refresh", refresh_fn):
            session = open_session(
                self.compte,
                coffre,
                base=self.base,
                connect_fn=lambda a, secret: vus.append(secret) or object(),
            )
        self.addCleanup(session.close)
        return session, vus

    def test_the_connection_gets_the_access_token_not_the_password(self):
        from script.todo.mail.oauth import TokenSet

        coffre = FauxCoffre(
            {
                self.compte.secret_ref: "mot-de-passe-oublié",
                self.compte.refresh_token_ref(): "r",
            }
        )
        neuf = TokenSet(
            refresh_token="r", access_token="a-neuf", expires_at=9e9
        )
        session, vus = self._ouvrir(coffre, lambda *a, **k: neuf)
        self.assertEqual(vus, ["a-neuf"])
        self.assertEqual(session.error, "")

    def test_a_revoked_grant_leaves_the_cache_readable(self):
        """Le compte reste consultable hors ligne : c'est tout l'ordre
        d'ouverture — le cache d'abord, le réseau ensuite."""
        from script.todo.mail.oauth import RefreshRefused

        def revoque(*a, **k):
            raise RefreshRefused("révoqué")

        coffre = FauxCoffre({self.compte.refresh_token_ref(): "r"})
        session, vus = self._ouvrir(coffre, revoque)
        self.assertEqual(vus, [])
        self.assertIsNotNone(session.store)
        self.assertIn("révoqué", session.error)

    def test_a_password_account_is_untouched_by_all_this(self):
        from script.todo.mail.accounts import account_from_preset

        self.compte = account_from_preset("perso", "a@x.ca", "generic")
        self.compte.cache_mode = "clear"
        coffre = FauxCoffre({self.compte.secret_ref: "mon-mot-de-passe"})

        def jamais(*a, **k):
            raise AssertionError("aucun rafraîchissement ici")

        _, vus = self._ouvrir(coffre, jamais)
        self.assertEqual(vus, ["mon-mot-de-passe"])


class LiveSessionCase(unittest.TestCase):
    """Un jeton d'accès vit une heure ; une session peut durer plus.

    Le jeu lu à l'ouverture cesse donc de valoir en cours de route, et tout
    ce qui rejoue le secret gardé — un envoi SMTP, une reconnexion IMAP —
    se ferait refuser jusqu'au redémarrage du client.
    """

    def setUp(self):
        from script.todo.mail.accounts import account_from_preset

        self.compte = account_from_preset(
            "perso", "a@x.ca", "gmail", auth="oauth"
        )

    def _session(self, coffre, refresh_fn):
        from unittest.mock import patch

        from script.todo.mail.tui import Session

        session = Session(
            self.compte,
            None,
            None,
            password="jeton-d-hier",
            secrets=coffre,
        )
        self.patch = patch("script.todo.mail.oauth.refresh", refresh_fn)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        return session

    def _jeu(self, acces, expire_dans=3600):
        import time

        from script.todo.mail.oauth import TokenSet

        return TokenSet(
            refresh_token="r",
            access_token=acces,
            expires_at=time.time() + expire_dans,
        )

    def test_a_stale_token_is_refreshed_when_the_secret_is_asked_for(self):
        coffre = FauxCoffre(
            {
                self.compte.refresh_token_ref(): self._jeu(
                    "vieux", -10
                ).to_json()
            }
        )
        session = self._session(coffre, lambda *a, **k: self._jeu("tout-neuf"))
        self.assertEqual(session.current_secret(), "tout-neuf")

    def test_a_token_still_valid_costs_no_exchange(self):
        """Rafraîchir à chaque envoi ferait compter des échanges au
        fournisseur pour rien."""
        coffre = FauxCoffre(
            {
                self.compte.refresh_token_ref(): self._jeu(
                    "encore-bon"
                ).to_json()
            }
        )
        appels = []
        session = self._session(
            coffre, lambda *a, **k: appels.append(1) or self._jeu("x")
        )
        self.assertEqual(session.current_secret(), "encore-bon")
        self.assertEqual(appels, [])

    def test_a_password_account_keeps_handing_over_its_password(self):
        from script.todo.mail.accounts import account_from_preset
        from script.todo.mail.tui import Session

        compte = account_from_preset("perso", "a@x.ca", "generic")
        session = Session(compte, None, None, password="mon-mot-de-passe")
        self.assertEqual(session.current_secret(), "mon-mot-de-passe")

    def test_a_session_without_a_vault_hands_over_what_it_has(self):
        """Les sessions fabriquées à la main — les tests en montent — n'ont
        pas de coffre. Lever ici les casserait toutes."""
        from script.todo.mail.tui import Session

        session = Session(self.compte, None, None, password="tel-quel")
        self.assertEqual(session.current_secret(), "tel-quel")

    def test_the_outbox_leaves_with_a_fresh_token_not_the_stored_one(self):
        """Le cas qui se voit : un message écrit hors ligne part des heures
        plus tard, et le jeton gardé à l'ouverture ne vaut plus rien."""
        import tempfile
        from pathlib import Path

        from script.todo.mail.smtp_send import build_message
        from script.todo.mail.store import Store
        from script.todo.mail.tui import Session, deliver, flush_outbox

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.compte.cache_mode = "clear"
        magasin = Store(self.compte, mode="clear", base=Path(tmp.name))
        magasin.open()
        self.addCleanup(magasin.close)

        coffre = FauxCoffre(
            {
                self.compte.refresh_token_ref(): self._jeu(
                    "vieux", -10
                ).to_json()
            }
        )
        hors_ligne = Session(
            self.compte, magasin, None, password="jeton-d-hier"
        )
        deliver(
            hors_ligne,
            build_message(self.compte, "a@y.ca", "Devis", "Bonjour"),
        )

        class FauxSyncer:
            transport = None

        en_ligne = self._session(
            coffre, lambda *a, **k: self._jeu("tout-neuf")
        )
        en_ligne.store = magasin
        en_ligne.syncer = FauxSyncer()
        vus = []
        flush_outbox(
            en_ligne,
            send_fn=lambda a, m, t: ["a@y.ca"],
            connect_fn=lambda a, secret: vus.append(secret)
            or type("T", (), {"quit": lambda self: None})(),
        )
        self.assertEqual(vus, ["tout-neuf"])


class ReconnectCase(unittest.TestCase):
    """Le lien IMAP est ouvert une fois, au démarrage, et gardé.

    Quand son jeton meurt, le serveur refuse la passe suivante. Sans
    reprise, le compte cesse de se synchroniser jusqu'à ce que quelqu'un
    relance le client — et rien à l'écran ne dit qu'il suffirait de
    rouvrir la connexion.
    """

    def setUp(self):
        from script.todo.mail.accounts import account_from_preset

        self.compte = account_from_preset(
            "perso", "a@x.ca", "gmail", auth="oauth"
        )

    def _session(self, syncer, secrets=None, connect_fn=None):
        from script.todo.mail.tui import Session

        return Session(
            self.compte,
            None,
            syncer,
            password="jeton-d-hier",
            secrets=secrets,
            connect_fn=connect_fn,
        )

    class FauxSyncer:
        """Refuse `refus` fois, puis rend un rapport."""

        def __init__(self, refus=1):
            self.restants = refus
            self.transport = object()
            self.passes = 0

        def sync(self, progress=None):
            from script.todo.mail.imap_transport import ImapAuthError

            self.passes += 1
            if self.restants > 0:
                self.restants -= 1
                raise ImapAuthError("jeton expiré")
            return "rapport"

    def test_a_refused_pass_reopens_the_connection_and_succeeds(self):
        from unittest.mock import patch

        from script.todo.mail.oauth import TokenSet

        coffre = FauxCoffre({self.compte.refresh_token_ref(): "r"})
        neuf = TokenSet(refresh_token="r", access_token="neuf", expires_at=9e9)
        vus = []
        syncer = self.FauxSyncer(refus=1)
        session = self._session(
            syncer,
            secrets=coffre,
            connect_fn=lambda a, secret: vus.append(secret) or object(),
        )
        with patch("script.todo.mail.oauth.refresh", lambda *a, **k: neuf):
            self.assertEqual(session.sync(), "rapport")
        self.assertEqual(vus, ["neuf"])
        self.assertEqual(syncer.passes, 2)

    def test_it_reopens_once_and_not_in_a_loop(self):
        """Un serveur qui refuse pour une autre raison ferait sinon tourner
        le client indéfiniment, en rafraîchissant à chaque tour."""
        from unittest.mock import patch

        from script.todo.mail.imap_transport import ImapAuthError
        from script.todo.mail.oauth import TokenSet

        coffre = FauxCoffre({self.compte.refresh_token_ref(): "r"})
        neuf = TokenSet(refresh_token="r", access_token="neuf", expires_at=9e9)
        syncer = self.FauxSyncer(refus=5)
        session = self._session(
            syncer, secrets=coffre, connect_fn=lambda a, s: object()
        )
        with patch("script.todo.mail.oauth.refresh", lambda *a, **k: neuf):
            with self.assertRaises(ImapAuthError):
                session.sync()
        self.assertEqual(syncer.passes, 2)

    def test_a_password_account_does_not_reopen_on_a_refusal(self):
        """Rien à rafraîchir : rouvrir présenterait le même mot de passe au
        même serveur, et le refus serait le même."""
        from script.todo.mail.accounts import account_from_preset
        from script.todo.mail.imap_transport import ImapAuthError

        self.compte = account_from_preset("perso", "a@x.ca", "generic")
        syncer = self.FauxSyncer(refus=1)
        session = self._session(syncer, connect_fn=lambda a, s: object())
        with self.assertRaises(ImapAuthError):
            session.sync()
        self.assertEqual(syncer.passes, 1)

    def test_a_pass_that_works_never_reconnects(self):
        syncer = self.FauxSyncer(refus=0)
        vus = []
        session = self._session(
            syncer, connect_fn=lambda a, s: vus.append(s) or object()
        )
        self.assertEqual(session.sync(), "rapport")
        self.assertEqual(vus, [])


if __name__ == "__main__":
    unittest.main()
