#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Faire passer un message d'un compte à un autre.

Deux comptes, deux serveurs : aucun COPY ne les relie. Le message est
DÉPOSÉ chez le destinataire par APPEND, puis seulement retiré de sa
source.

L'ordre est tout, et c'est ce que ces tests couvrent d'abord. Un retrait
qui précéderait le dépôt, ou qui suivrait un dépôt non confirmé, perdrait
le message pour de bon — aucun serveur ne le rendrait, et la corbeille
elle-même ne le verrait jamais passer.
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
    b"From: Ana <ana@e.ca>\r\nTo: moi@x.ca\r\nSubject: Devis\r\n"
    b"Message-ID: <devis-42@e.ca>\r\n\r\ncorps du devis\r\n"
)
REPONSE = (
    b"From: Bo <bo@e.ca>\r\nTo: moi@x.ca\r\nSubject: Re: Devis\r\n"
    b"Message-ID: <reponse-7@e.ca>\r\nIn-Reply-To: <devis-42@e.ca>\r\n"
    b"\r\nje cite <devis-42@e.ca>\r\n"
)


class DeuxComptesCase(MailSandboxCase):
    def setUp(self):
        self.source = self.imap_server()
        self.source.folder("INBOX").deliver(DEVIS)
        self.lien_source = self.imap_transport(self.source)
        self.lien_source.select("INBOX")

        self.cible = self.imap_server()
        self.cible.folder("INBOX")
        self.archives = self.cible.folder("Archives")
        self.lien_cible = self.imap_transport(
            self.cible, sandbox_account(imap_port=self.cible.port)
        )

    def _sujets(self, sandbox, boite):
        return [
            m.parsed.get("Subject") for m in sandbox.folder(boite).messages
        ]


@requires_servers
class TestDepositingInTheOtherAccount(DeuxComptesCase):
    def test_the_message_arrives(self):
        raw = self.lien_source.fetch_body(1)
        self.lien_cible.append("Archives", raw, [])
        self.assertEqual(self._sujets(self.cible, "Archives"), ["Devis"])

    def test_it_keeps_the_date_it_had(self):
        """Sans date interne, le serveur horodate à maintenant : un message
        d'il y a deux ans remonterait en tête de la boîte comme s'il venait
        d'arriver."""
        self.lien_cible.append("Archives", DEVIS, [], date=1_500_000_000)
        _, _, date = self.cible.folder("Archives").appended[0]
        self.assertIn("2017", str(date))

    def test_without_a_date_the_server_stamps_it_itself(self):
        self.lien_cible.append("Archives", DEVIS, [])
        _, _, date = self.cible.folder("Archives").appended[0]
        self.assertIsNone(date)

    def test_an_unknown_folder_is_refused(self):
        from script.todo.mail.imap_transport import ImapError

        with self.assertRaises(ImapError):
            self.lien_cible.append("Dossier-absent", DEVIS, [])

    def test_the_flags_travel_with_it(self):
        self.lien_cible.append("Archives", DEVIS, ["\\Seen"])
        self.assertIn(
            "\\Seen", self.cible.folder("Archives").messages[0].flags
        )


@requires_servers
class TestConfirmingItArrived(DeuxComptesCase):
    def test_a_deposited_message_is_found_by_its_id(self):
        self.lien_cible.append("Archives", DEVIS, [])
        self.assertTrue(
            self.lien_cible.contient_message_id("Archives", "<devis-42@e.ca>")
        )

    def test_an_empty_folder_confirms_nothing(self):
        self.assertFalse(
            self.lien_cible.contient_message_id("Archives", "<devis-42@e.ca>")
        )

    def test_a_reply_quoting_the_id_does_not_confirm_it(self):
        """Le piège que `HEADER Message-ID` évite et que `TEXT` ne verrait
        pas : une réponse porte l'identifiant du message d'origine dans son
        `In-Reply-To` et souvent dans son corps. La prendre pour le dépôt
        ferait détruire une source qui n'est arrivée nulle part.
        """
        self.cible.folder("Archives").deliver(REPONSE)
        self.assertFalse(
            self.lien_cible.contient_message_id("Archives", "<devis-42@e.ca>")
        )

    def test_a_message_without_an_id_confirms_nothing(self):
        self.lien_cible.append("Archives", DEVIS, [])
        self.assertFalse(self.lien_cible.contient_message_id("Archives", ""))


@requires_servers
class TestRemovingTheSource(DeuxComptesCase):
    def test_the_named_message_leaves(self):
        self.assertTrue(self.lien_source.discard([1]))
        self.assertEqual(self._sujets(self.source, "INBOX"), [])

    def test_nothing_else_is_swept_away(self):
        """`discard` retire ce qu'on NOMME : un message qu'un autre client a
        marqué supprimé dans le même dossier reste."""
        self.source.folder("INBOX").deliver(REPONSE)
        self.lien_source.select("INBOX")
        self.lien_source.store_flags(2, ["\\Deleted"], [])
        self.lien_source.discard([1])
        self.assertEqual(len(self.source.folder("INBOX").messages), 1)

    def test_removing_nothing_touches_nothing(self):
        self.assertTrue(self.lien_source.discard([]))
        self.assertEqual(len(self.source.folder("INBOX").messages), 1)

    def test_without_uidplus_it_says_it_could_not(self):
        muet = self.imap_server(uidplus=False)
        muet.folder("INBOX").deliver(DEVIS)
        lien = self.imap_transport(muet, sandbox_account(imap_port=muet.port))
        lien.select("INBOX")
        self.assertFalse(lien.discard([1]))
        self.assertEqual(len(muet.folder("INBOX").messages), 1)


if __name__ == "__main__":
    unittest.main()
