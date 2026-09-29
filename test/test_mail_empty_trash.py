#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Vider une corbeille.

`d` remplit une corbeille que rien ne vidait. C'est le seul geste du
client qui DÉTRUIT : IMAP n'a pas de corbeille pour ce qui sort d'une
corbeille, et aucune passe de synchronisation ne ramènera ce qui part ici.

Ce que ces tests couvrent d'abord, c'est la portée : le dossier nommé se
vide en entier, et RIEN d'autre ne bouge. Un vidage qui déborderait sur un
autre dossier détruirait des messages que personne n'a désignés.
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
    from mail_sandbox import MailSandboxCase

requires_servers = unittest.skipIf(
    bool(SANDBOX_MISSING),
    f"serveurs de test absents ({SANDBOX_MISSING})"
    " : pip install -r requirement/erplibre_require-ments.txt",
)

UN = (
    b"From: Ana <ana@e.ca>\r\nTo: moi@x.ca\r\nSubject: Vieux devis\r\n"
    b"Message-ID: <1@e.ca>\r\n\r\ncorps un\r\n"
)
DEUX = (
    b"From: Bo <bo@e.ca>\r\nTo: moi@x.ca\r\nSubject: Pourriel\r\n"
    b"Message-ID: <2@e.ca>\r\n\r\ncorps deux\r\n"
)
TROIS = (
    b"From: Cy <cy@e.ca>\r\nTo: moi@x.ca\r\nSubject: Facture\r\n"
    b"Message-ID: <3@e.ca>\r\n\r\ncorps trois\r\n"
)


class EmptyCase(MailSandboxCase):
    UIDPLUS = True

    def setUp(self):
        self.sandbox = self.imap_server(uidplus=self.UIDPLUS)
        self.corbeille = self.sandbox.folder("Trash")
        self.corbeille.deliver(UN)
        self.corbeille.deliver(DEUX)
        self.boite = self.sandbox.folder("INBOX")
        self.boite.deliver(TROIS)
        self.transport = self.imap_transport(self.sandbox)

    def _sujets(self, boite):
        return [
            m.parsed.get("Subject")
            for m in self.sandbox.folder(boite).messages
        ]


@requires_servers
class TestWhatItEmpties(EmptyCase):
    def test_the_folder_is_left_empty(self):
        self.transport.empty_folder("Trash")
        self.assertEqual(self._sujets("Trash"), [])

    def test_it_says_how_many_it_destroyed(self):
        """Le nombre vient du SERVEUR : c'est le seul qui dise ce qui est
        réellement parti."""
        self.assertEqual(self.transport.empty_folder("Trash"), 2)

    def test_nothing_else_is_touched(self):
        """Une destruction qui déborde de son dossier est le pire défaut
        possible pour ce geste."""
        self.transport.empty_folder("Trash")
        self.assertEqual(self._sujets("INBOX"), ["Facture"])

    def test_an_already_empty_folder_is_not_an_error(self):
        self.transport.empty_folder("Trash")
        self.assertEqual(self.transport.empty_folder("Trash"), 0)

    def test_a_message_arriving_later_is_not_swept(self):
        """Le relevé des UID borne le geste : ce qui arrive après n'est pas
        marqué, donc l'EXPUNGE ne l'emporte pas."""
        self.transport.empty_folder("Trash")
        self.corbeille.deliver(TROIS)
        self.transport.select("Trash")
        self.assertEqual(self._sujets("Trash"), ["Facture"])

    def test_the_selected_folder_is_the_one_named(self):
        """L'appelant n'a pas à sélectionner d'abord : la méthode le fait,
        et une sélection oubliée viderait le dossier ouvert."""
        self.transport.select("INBOX")
        self.transport.empty_folder("Trash")
        self.assertEqual(self._sujets("INBOX"), ["Facture"])

    def test_an_unknown_folder_is_refused(self):
        from script.todo.mail.imap_transport import ImapError

        with self.assertRaises(ImapError):
            self.transport.empty_folder("Dossier-qui-n-existe-pas")
        self.assertEqual(len(self.sandbox.folder("Trash").messages), 2)


@requires_servers
class TestAServerWithoutUidplus(EmptyCase):
    """Sans UIDPLUS, il ne reste que l'EXPUNGE nu.

    `move` s'en abstient — il emporterait des messages qu'elle n'a pas
    nommés. Ici le dossier est vidé ENTIER : tout ce qui y est marqué est
    soit ce que le client vient de marquer, soit ce qu'un autre client a
    marqué dans ce même dossier, que le geste détruit de toute façon.
    """

    UIDPLUS = False

    def test_the_folder_is_emptied_anyway(self):
        self.assertEqual(self.transport.empty_folder("Trash"), 2)
        self.assertEqual(self._sujets("Trash"), [])

    def test_another_folder_keeps_what_was_marked_there(self):
        """L'EXPUNGE nu ne porte que sur le dossier sélectionné : un
        message barré ailleurs reste."""
        self.transport.select("INBOX")
        self.transport.store_flags(1, ["\\Deleted"], [])
        self.transport.empty_folder("Trash")
        self.assertEqual(len(self.sandbox.folder("INBOX").messages), 1)


if __name__ == "__main__":
    unittest.main()
