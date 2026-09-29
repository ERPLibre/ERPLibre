#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un lien IMAP mort se remplace, il ne se traîne pas.

Une lecture qui dépasse le délai marque l'objet socket de Python pour de
bon : toute lecture suivante lève aussitôt « cannot read from timed out
object », sans rien demander au serveur. Un seul LIST lent condamnait donc
le compte pour toute la durée du client — chaque passe échouant en
quelques millisecondes sur un lien déjà mort — et relancer le client était
le seul remède, que rien n'annonçait.

Ce que ces tests séparent : une SOCKET morte, qui se répare en ouvrant un
autre lien, et un SERVEUR qui répond non, où rouvrir ne changerait rien et
où insister ferait tourner le client sans fin.
"""
import imaplib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_transport import ImapAuthError, ImapError
from script.todo.mail.store import Store
from script.todo.mail.tui import Session


class FauxTransport:
    def __init__(self, nom="vivant"):
        self.nom = nom
        self.ferme = False

    def logout(self):
        self.ferme = True


class FauxSyncer:
    """Un moteur dont la passe échoue tant qu'on ne lui change pas son lien."""

    def __init__(self, transport, erreurs):
        self.transport = transport
        # Une erreur par appel, épuisée dans l'ordre ; ensuite, ça marche.
        self.erreurs = list(erreurs)
        self.passes = 0
        self.liens_vus = []

    def sync(self, progress=None):
        self.passes += 1
        self.liens_vus.append(self.transport)
        if self.erreurs:
            raise self.erreurs.pop(0)
        return "rapport"


class LienCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.ouvertures = []

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _session(self, erreurs, connect=True, auth="login"):
        self.account.auth = auth
        syncer = FauxSyncer(FauxTransport(), erreurs)

        def connect_fn(account, secret):
            lien = FauxTransport(f"neuf-{len(self.ouvertures)}")
            self.ouvertures.append((account, secret))
            return lien

        return Session(
            self.account,
            self.store,
            syncer,
            password="x",
            connect_fn=connect_fn if connect else None,
        )


TIMEOUT_POISON = OSError("cannot read from timed out object")


class TestASocketThatDied(LienCase):
    def test_the_pass_succeeds_on_the_second_link(self):
        """Le lien est mort : la passe doit aboutir quand même, sur un
        autre."""
        session = self._session([TIMEOUT_POISON])
        self.assertEqual(session.sync(), "rapport")

    def test_a_new_link_is_opened(self):
        session = self._session([TIMEOUT_POISON])
        session.sync()
        self.assertEqual(len(self.ouvertures), 1)

    def test_the_syncer_gets_the_new_link(self):
        """Remplacer le lien sans le donner au moteur laisserait la passe
        suivante repartir sur le mort."""
        session = self._session([TIMEOUT_POISON])
        session.sync()
        self.assertEqual(session.syncer.transport.nom, "neuf-0")

    def test_the_dead_link_is_closed(self):
        ancien = None
        session = self._session([TIMEOUT_POISON])
        ancien = session.syncer.transport
        session.sync()
        self.assertTrue(ancien.ferme)

    def test_a_plain_timeout_counts_too(self):
        """`TimeoutError` est ce que lève la PREMIÈRE lecture trop longue,
        avant que la socket ne soit marquée."""
        session = self._session([TimeoutError("read operation timed out")])
        self.assertEqual(session.sync(), "rapport")

    def test_a_broken_dialogue_counts_too(self):
        """`IMAP4.abort` : le dialogue est rompu en cours de commande."""
        session = self._session([imaplib.IMAP4.abort("socket error")])
        self.assertEqual(session.sync(), "rapport")

    def test_only_one_retry(self):
        """Deux liens morts d'affilée : le second échec sort. Réessayer sans
        fin ferait tourner le client indéfiniment."""
        session = self._session([TIMEOUT_POISON, TIMEOUT_POISON])
        with self.assertRaises(OSError):
            session.sync()
        self.assertEqual(session.syncer.passes, 2)

    def test_without_a_way_to_reconnect_the_error_surfaces(self):
        """Une session montée à la main n'a pas de fabrique de lien : elle
        doit dire l'erreur, pas prétendre l'avoir réparée."""
        session = self._session([TIMEOUT_POISON], connect=False)
        with self.assertRaises(OSError):
            session.sync()


class TestAServerThatSaysNo(LienCase):
    def test_a_protocol_refusal_is_not_retried(self):
        """Le serveur a répondu, et c'était non : rouvrir n'y changerait
        rien."""
        session = self._session([ImapError("NO [CANNOT] dossier inconnu")])
        with self.assertRaises(ImapError):
            session.sync()
        self.assertEqual(len(self.ouvertures), 0)

    def test_a_refused_password_is_not_retried(self):
        """Représenter le même mot de passe au même serveur donnerait le
        même refus."""
        session = self._session([ImapAuthError("refus")], auth="login")
        with self.assertRaises(ImapAuthError):
            session.sync()
        self.assertEqual(len(self.ouvertures), 0)

    def test_a_refused_token_still_reopens(self):
        """Un jeton, lui, CHANGE : c'est la reprise qui existait déjà."""
        session = self._session([ImapAuthError("jeton périmé")], auth="oauth")
        # Un coffre qui ne rend rien : `current_secret` retombe alors sur
        # le secret déjà en main, ce qui suffit ici — le sujet du test est
        # la RÉOUVERTURE, pas le rafraîchissement.
        session.secrets = SimpleNamespace(get=lambda ref: None)
        self.assertEqual(session.sync(), "rapport")
        self.assertEqual(len(self.ouvertures), 1)


class TestTheReadTimeout(unittest.TestCase):
    """Le délai borne CHAQUE lecture, et se règle."""

    def _delai(self, valeur):
        from unittest.mock import patch

        from script.todo.mail import imap_transport

        with patch("script.todo.todo_prefs.get", return_value=valeur):
            return imap_transport._delai_lecture()

    def test_the_default_is_thirty_seconds(self):
        self.assertEqual(self._delai(30), 30)

    def test_a_larger_value_is_honoured(self):
        """Monter le délai évite la coupure plutôt que de la réparer."""
        self.assertEqual(self._delai(120), 120)

    def test_a_nonsense_value_falls_back(self):
        """Une préférence illisible ne doit pas empêcher de se connecter."""
        self.assertEqual(self._delai("beaucoup"), 30)

    def test_zero_falls_back_rather_than_waiting_forever(self):
        """`timeout=0` met la socket en mode non bloquant : imaplib y
        échouerait sans jamais rien lire."""
        self.assertEqual(self._delai(0), 30)

    def test_a_negative_value_falls_back(self):
        self.assertEqual(self._delai(-5), 30)


if __name__ == "__main__":
    unittest.main()
