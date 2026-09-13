#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Déplacer un message d'un dossier à un autre.

Un client courriel qui ne sait pas ranger ni jeter n'en est pas un. IMAP
n'a pas de verbe « déplacer » universel : le chemin portable est COPY, puis
`\\Deleted` sur la source, puis EXPUNGE.

C'est EXPUNGE qui demande de la prudence, et c'est ce que ces tests
couvrent d'abord : il emporte TOUS les messages marqués supprimés du
dossier, y compris ceux que quelqu'un d'autre a marqués ailleurs. Le
client ne l'appelle donc que lorsqu'il peut nommer ce qu'il retire, et le
dit quand il ne peut pas.
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
    b"From: Ana <ana@e.ca>\r\nTo: moi@x.ca\r\nSubject: Devis\r\n"
    b"Message-ID: <1@e.ca>\r\n\r\ncorps un\r\n"
)
DEUX = (
    b"From: Bo <bo@e.ca>\r\nTo: moi@x.ca\r\nSubject: Facture\r\n"
    b"Message-ID: <2@e.ca>\r\n\r\ncorps deux\r\n"
)


@requires_servers
class TestMovingAMessage(MailSandboxCase):
    def setUp(self):
        self.sandbox = self.imap_server()
        self.boite = self.sandbox.folder("INBOX")
        self.boite.deliver(UN)
        self.boite.deliver(DEUX)
        self.archives = self.sandbox.folder("Archives")
        self.transport = self.imap_transport(self.sandbox)
        self.transport.select("INBOX")

    def _sujets(self, boite):
        return [
            m.parsed.get("Subject")
            for m in self.sandbox.folder(boite).messages
        ]

    def test_the_message_arrives_in_the_target(self):
        self.transport.move([1], "Archives")
        self.assertEqual(self._sujets("Archives"), ["Devis"])

    def test_it_leaves_the_source(self):
        self.transport.move([1], "Archives")
        self.assertEqual(self._sujets("INBOX"), ["Facture"])

    def test_the_others_stay_where_they_are(self):
        """EXPUNGE emporte TOUT ce qui est marqué supprimé : un message que
        le client n'a pas déplacé ne doit pas partir avec."""
        self.transport.store_flags(2, ["\\Deleted"], [])
        self.transport.move([1], "Archives")
        self.assertEqual(self._sujets("Archives"), ["Devis"])
        self.assertEqual(len(self.sandbox.folder("INBOX").messages), 1)

    def test_moving_several_at_once_moves_them_all(self):
        self.transport.move([1, 2], "Archives")
        self.assertEqual(self._sujets("Archives"), ["Devis", "Facture"])
        self.assertEqual(self._sujets("INBOX"), [])

    def test_moving_nothing_touches_nothing(self):
        self.transport.move([], "Archives")
        self.assertEqual(self._sujets("Archives"), [])
        self.assertEqual(len(self.sandbox.folder("INBOX").messages), 2)

    def test_an_unknown_target_is_refused_before_anything_is_deleted(self):
        """Le pire résultat possible : le message retiré de sa source sans
        être arrivé nulle part. La copie passe donc AVANT la suppression, et
        son échec arrête tout."""
        from script.todo.mail.imap_transport import ImapError

        with self.assertRaises(ImapError):
            self.transport.move([1], "Dossier-qui-n-existe-pas")
        self.assertEqual(len(self.sandbox.folder("INBOX").messages), 2)


@requires_servers
class TestAServerWithoutUidplus(MailSandboxCase):
    """Sans UIDPLUS, aucun geste ne retire un message PRÉCIS.

    Il ne reste que l'EXPUNGE nu, qui emporte tout ce qui est marqué
    supprimé dans le dossier — y compris ce qu'un autre client a marqué.
    Le client s'en abstient : il copie, marque, et le dit.
    """

    def setUp(self):
        self.sandbox = self.imap_server(uidplus=False)
        self.boite = self.sandbox.folder("INBOX")
        self.boite.deliver(UN)
        self.boite.deliver(DEUX)
        self.sandbox.folder("Archives")
        self.transport = self.imap_transport(self.sandbox)
        self.transport.select("INBOX")

    def test_the_copy_still_arrives(self):
        self.transport.move([1], "Archives")
        self.assertEqual(
            [
                m.parsed.get("Subject")
                for m in self.sandbox.folder("Archives").messages
            ],
            ["Devis"],
        )

    def test_it_says_the_source_was_not_cleared(self):
        """L'appelant doit pouvoir le dire à l'utilisateur : le message est
        encore là, barré, et un autre client le montrera peut-être."""
        self.assertFalse(self.transport.move([1], "Archives"))

    def test_the_source_keeps_the_message_marked_deleted(self):
        self.transport.move([1], "Archives")
        messages = self.sandbox.folder("INBOX").messages
        self.assertEqual(len(messages), 2)
        self.assertIn("\\Deleted", messages[0].flags)

    def test_nothing_else_is_swept_away(self):
        """Le point entier : un message marqué par quelqu'un d'autre reste."""
        self.transport.store_flags(2, ["\\Deleted"], [])
        self.transport.move([1], "Archives")
        self.assertEqual(len(self.sandbox.folder("INBOX").messages), 2)


if __name__ == "__main__":
    unittest.main()
