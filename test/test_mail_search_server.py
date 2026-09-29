#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Chercher au-delà du cache : demander au serveur.

`/` ne trouve que ce qui est déjà téléchargé. Un message plus ancien que la
fenêtre de synchronisation est donc introuvable dans le client alors que le
serveur, lui, le trouve — et rien à l'écran ne distingue « ça n'existe pas »
de « ce n'est pas ici ».

Ces tests parlent à un vrai serveur IMAP sur 127.0.0.1 (voir
`mail_sandbox.py`). Ce qu'ils couvrent en priorité : le terme accentué, que
`imaplib` refuse d'encoder tout seul, et le fait que ce qui revient du
serveur ENTRE dans le cache — sans quoi la recherche suivante repartirait
sur le réseau pour la même question.

Le bac à sable ne savait pas répondre à SEARCH : le chemin de repli de
Twisted compare des `bytes` à des `str`, ne trouve donc jamais rien, et lève
sur `SUBJECT`. La boîte du bac à sable implémente désormais la recherche
elle-même — sans quoi ces tests passeraient au vert devant un client qui
n'envoie rien.
"""
import unittest

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import MailSandboxCase, sandbox_account

requires_servers = unittest.skipIf(
    bool(SANDBOX_MISSING),
    f"serveurs de test absents ({SANDBOX_MISSING})"
    " : pip install -r requirement/erplibre_require-ments.txt",
)

DEVIS = (
    b"From: Ana <ana@e.ca>\r\n"
    b"To: moi@x.ca\r\n"
    b"Subject: Devis pour la toiture\r\n"
    b"Message-ID: <1@e.ca>\r\n"
    b"Date: Mon, 3 Aug 2026 09:00:00 +0000\r\n"
    b"\r\n"
    b"bonjour voici le devis\r\n"
)
FACTURE = (
    b"From: Bo <bo@e.ca>\r\n"
    b"To: moi@x.ca\r\n"
    b"Subject: Facture\r\n"
    b"Message-ID: <2@e.ca>\r\n"
    b"Date: Tue, 4 Aug 2026 09:00:00 +0000\r\n"
    b"\r\n"
    b"rien a voir\r\n"
)
# Le sujet porte un accent : `imaplib` encode ses arguments `str` en ASCII,
# donc le critère doit partir en octets pour atteindre le serveur.
ETE = (
    "From: Ana <ana@e.ca>\r\n"
    "To: moi@x.ca\r\n"
    "Subject: Vacances d'été\r\n"
    "Message-ID: <3@e.ca>\r\n"
    "Date: Wed, 5 Aug 2026 09:00:00 +0000\r\n"
    "\r\n"
    "on ferme en août\r\n"
).encode("utf-8")


@requires_servers
class TestTheServerAnswersASearch(MailSandboxCase):
    def _transport(self):
        sandbox = self.imap_server()
        boite = sandbox.folder("INBOX")
        boite.deliver(DEVIS)
        boite.deliver(FACTURE)
        boite.deliver(ETE)
        transport = self.imap_transport(sandbox)
        transport.select("INBOX")
        return transport

    def test_it_finds_by_subject(self):
        self.assertEqual(len(self._transport().search("toiture")), 1)

    def test_it_finds_by_sender(self):
        """`TEXT` couvre les en-têtes ET le corps : un sur-ensemble de ce
        que la recherche locale compare, ce qui est le sens même d'aller
        chercher plus loin."""
        self.assertEqual(len(self._transport().search("ana")), 2)

    def test_it_finds_in_the_body(self):
        self.assertEqual(len(self._transport().search("bonjour")), 1)

    def test_an_accented_term_reaches_the_server(self):
        """`imaplib` encode ses arguments `str` en ASCII : un critère qui
        ne partirait pas en octets lèverait `UnicodeEncodeError` avant même
        d'atteindre le serveur."""
        self.assertEqual(len(self._transport().search("été")), 1)

    def test_a_term_nobody_wrote_finds_nothing(self):
        self.assertEqual(self._transport().search("zzzz"), [])

    def test_an_empty_term_asks_the_server_nothing(self):
        """Chercher la chaîne vide rendrait toute la boîte, ce qui n'est pas
        une recherche."""
        self.assertEqual(self._transport().search("  "), [])

    def test_a_quote_in_the_term_does_not_break_the_command(self):
        """Un guillemet non échappé couperait la chaîne IMAP en deux et
        ferait lire le reste comme une autre clé de recherche."""
        self.assertEqual(self._transport().search('dev"is'), [])


@requires_servers
class TestWhatComesBackEntersTheCache(MailSandboxCase):
    """Ce que le serveur trouve doit devenir consultable comme le reste.

    Sans cela, la recherche suivante repartirait sur le réseau pour la même
    question, et le résultat disparaîtrait dès la connexion perdue.
    """

    def _syncer(self):
        from script.todo.mail.imap_sync import Syncer

        sandbox = self.imap_server()
        boite = sandbox.folder("INBOX")
        boite.deliver(DEVIS)
        boite.deliver(FACTURE)
        self.compte = sandbox_account(imap_port=sandbox.port)
        self.magasin = self.temp_store(self.compte)
        return Syncer(self.magasin, self.imap_transport(sandbox, self.compte))

    def test_missing_uids_are_downloaded_and_stored(self):
        syncer = self._syncer()
        fid = self.magasin.upsert_folder("INBOX")
        self.assertEqual(syncer.fetch_uids("INBOX", [1, 2]), 2)
        sujets = [m.subject for m in self.magasin.list_messages(fid)]
        self.assertIn("Devis pour la toiture", sujets)

    def test_what_is_already_cached_is_not_downloaded_again(self):
        """Le serveur compte ces requêtes, et l'utilisateur attend
        pendant."""
        syncer = self._syncer()
        self.magasin.upsert_folder("INBOX")
        syncer.fetch_uids("INBOX", [1, 2])
        self.assertEqual(syncer.fetch_uids("INBOX", [1, 2]), 0)

    def test_an_empty_list_never_touches_the_server(self):
        syncer = self._syncer()
        self.magasin.upsert_folder("INBOX")
        appels = []
        syncer.transport.fetch_headers = lambda uids: appels.append(uids)
        self.assertEqual(syncer.fetch_uids("INBOX", []), 0)
        self.assertEqual(appels, [])

    def test_the_folder_is_selected_before_fetching(self):
        """Un FETCH sans SELECT porte sur le dossier précédent — ou sur
        rien, et le serveur répond NO."""
        syncer = self._syncer()
        self.magasin.upsert_folder("Archives")
        syncer.transport.select("INBOX")
        self.assertEqual(syncer.fetch_uids("INBOX", [1]), 1)


if __name__ == "__main__":
    unittest.main()
