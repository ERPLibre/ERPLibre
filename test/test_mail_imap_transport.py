#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest
from unittest.mock import MagicMock, patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_transport import (
    ImapError,
    ImaplibTransport,
    connect,
    decode_header_value,
    decode_mailbox,
    parse_fetch_headers,
    parse_list_line,
)


class TestDecodeHeaderValue(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(decode_header_value("Bonjour"), "Bonjour")

    def test_encoded_word_base64(self):
        self.assertEqual(
            decode_header_value("=?UTF-8?B?RGV2aXMgcsOpdmlzw6k=?="),
            "Devis révisé",
        )

    def test_encoded_word_quoted_printable(self):
        self.assertEqual(
            decode_header_value("=?UTF-8?Q?Devis_r=C3=A9vis=C3=A9?="),
            "Devis révisé",
        )

    def test_mixed_parts(self):
        self.assertEqual(
            decode_header_value("Re: =?UTF-8?B?ZGV2aXM=?="), "Re: devis"
        )

    def test_none_is_empty(self):
        self.assertEqual(decode_header_value(None), "")

    def test_broken_encoding_does_not_raise(self):
        self.assertIsInstance(decode_header_value("=?UTF-8?B?!!!?="), str)

    def test_unknown_8bit_charset_does_not_raise(self):
        """Étiquette réelle vue en usage : certains MTA la posent sur un
        en-tête 8 bits mal formé. Python ne connaît pas ce nom de codec :
        `bytes.decode("unknown-8bit", "replace")` lève `LookupError` à la
        recherche du codec, avant que `errors="replace"` ne serve. Un seul
        message ainsi étiqueté faisait échouer toute la synchronisation du
        dossier (`_sync_folder` catch par dossier, donc le dossier entier
        n'était jamais marqué synchronisé)."""
        self.assertEqual(
            decode_header_value("=?unknown-8bit?Q?Bonjour?="), "Bonjour"
        )


class TestDecodeMailbox(unittest.TestCase):
    def test_ascii_unchanged(self):
        self.assertEqual(decode_mailbox("INBOX"), "INBOX")

    def test_modified_utf7(self):
        self.assertEqual(decode_mailbox("&AMk-l&AOk-ments"), "Éléments")

    def test_ampersand_escape(self):
        self.assertEqual(decode_mailbox("A&-B"), "A&B")

    def test_broken_input_returns_original(self):
        self.assertEqual(decode_mailbox("&&&"), "&&&")


class TestParseListLine(unittest.TestCase):
    def test_plain_inbox(self):
        info = parse_list_line(b'(\\HasNoChildren) "/" "INBOX"')
        self.assertEqual(info.name, "INBOX")
        self.assertEqual(info.role, "inbox")

    def test_sent_role_from_special_use(self):
        info = parse_list_line(
            b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"'
        )
        self.assertEqual(info.name, "[Gmail]/Sent Mail")
        self.assertEqual(info.role, "sent")

    def test_trash_role(self):
        self.assertEqual(
            parse_list_line(b'(\\Trash) "/" "Corbeille"').role, "trash"
        )

    def test_drafts_role(self):
        self.assertEqual(
            parse_list_line(b'(\\Drafts) "/" "Drafts"').role, "drafts"
        )

    def test_junk_role(self):
        self.assertEqual(parse_list_line(b'(\\Junk) "/" "Spam"').role, "junk")

    def test_archive_role(self):
        self.assertEqual(
            parse_list_line(b'(\\Archive) "/" "Archive"').role, "archive"
        )

    def test_noselect_containers_are_marked_unselectable(self):
        """« [Gmail] » est un NIVEAU de hiérarchie, pas une boîte : le
        serveur l'annonce dans les drapeaux de LIST, il suffit de l'écouter
        plutôt que de traiter son nom comme un cas particulier."""
        for ligne in (
            b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
            b'(\\NonExistent \\HasChildren) "/" "Vieux"',
        ):
            self.assertFalse(parse_list_line(ligne).selectable, ligne)

    def test_ordinary_folders_stay_selectable(self):
        """Le contrôle négatif : marquer TOUT comme non sélectionnable
        passerait le test ci-dessus, et ne synchroniserait plus rien."""
        for ligne in (
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
        ):
            self.assertTrue(parse_list_line(ligne).selectable, ligne)

    def test_no_special_use_has_no_role(self):
        self.assertIsNone(
            parse_list_line(b'(\\HasNoChildren) "/" "Projets"').role
        )

    def test_unquoted_name(self):
        self.assertEqual(
            parse_list_line(b'(\\HasNoChildren) "/" Projets').name, "Projets"
        )

    def test_display_is_decoded(self):
        info = parse_list_line(b'(\\HasNoChildren) "/" "&AMk-l&AOk-ments"')
        self.assertEqual(info.display, "Éléments")


HEADERS_1 = (
    b"1 (UID 101 RFC822.SIZE 420 FLAGS (\\Seen) BODY[HEADER.FIELDS "
    b"(FROM TO SUBJECT DATE MESSAGE-ID)] {160}",
    b"From: Alice <alice@x.ca>\r\n"
    b"To: moi@x.ca\r\n"
    b"Subject: =?UTF-8?B?RGV2aXMgcsOpdmlzw6k=?=\r\n"
    b"Date: Fri, 01 Aug 2026 10:41:00 +0000\r\n"
    b"Message-ID: <abc@x.ca>\r\n\r\n",
)
HEADERS_2 = (
    b"2 (UID 102 RFC822.SIZE 12 FLAGS () BODY[HEADER.FIELDS "
    b"(FROM TO SUBJECT DATE MESSAGE-ID)] {40}",
    b"From: bob@x.ca\r\nSubject: CR\r\n\r\n",
)


# Même message, mais le serveur place les attributs APRÈS le littéral.
# `imaplib` rend alors la fin de ligne dans une entrée séparée.
HEADERS_TRAILING = (
    b"3 (BODY[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)] {42}",
    b"From: carl@x.ca\r\nSubject: Facture\r\n\r\n",
)
TRAILING_ATTRS = b" UID 103 RFC822.SIZE 99 FLAGS (\\Answered))"


class TestParseFetchHeaders(unittest.TestCase):
    def test_single_message(self):
        got = parse_fetch_headers([HEADERS_1, b")"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].uid, 101)

    def test_size_and_flags(self):
        got = parse_fetch_headers([HEADERS_1, b")"])[0]
        self.assertEqual(got.size, 420)
        self.assertEqual(got.flags, "\\Seen")

    def test_subject_is_decoded(self):
        self.assertEqual(
            parse_fetch_headers([HEADERS_1, b")"])[0].subject, "Devis révisé"
        )

    def test_from_and_to(self):
        got = parse_fetch_headers([HEADERS_1, b")"])[0]
        self.assertEqual(got.frm, "Alice <alice@x.ca>")
        self.assertEqual(got.to, "moi@x.ca")

    def test_msgid(self):
        self.assertEqual(
            parse_fetch_headers([HEADERS_1, b")"])[0].msgid, "<abc@x.ca>"
        )

    def test_raw_8bit_bytes_in_the_date_do_not_lose_the_message(self):
        """Signalé depuis une VRAIE boîte : un `Date:` porteur d'octets 8
        bits fait renvoyer un `Header` et non une chaîne, et
        `parsedate_to_datetime` y lève un AttributeError que le `except`
        d'origine ne rattrapait pas — la synchro du dossier ENTIER tombait
        sur un seul message. Une date est une commodité d'affichage : elle
        ne vaut pas la perte du message."""
        entetes = (
            b"From: a@x.ca\r\n"
            b"Subject: essai\r\n"
            b"Date: Wed, 06 Ao\xfbt 2026 10:00:00 +0000\r\n\r\n"
        )
        data = [
            (
                b"1 (UID 42 RFC822.SIZE 100 FLAGS (\\Seen) "
                b"BODY[HEADER.FIELDS (DATE FROM TO SUBJECT MESSAGE-ID)] "
                b"{%d}" % len(entetes),
                entetes,
            ),
            b")",
        ]
        infos = parse_fetch_headers(data)
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].uid, 42)
        self.assertEqual(infos[0].date, 0)
        self.assertEqual(infos[0].subject, "essai")

    def test_date_is_epoch(self):
        self.assertEqual(
            parse_fetch_headers([HEADERS_1, b")"])[0].date, 1785580860
        )

    def test_missing_date_is_zero(self):
        self.assertEqual(parse_fetch_headers([HEADERS_2, b")"])[0].date, 0)

    def test_missing_to_is_empty(self):
        self.assertEqual(parse_fetch_headers([HEADERS_2, b")"])[0].to, "")

    def test_several_messages(self):
        got = parse_fetch_headers([HEADERS_1, b")", HEADERS_2, b")"])
        self.assertEqual([m.uid for m in got], [101, 102])

    def test_non_tuple_entries_are_skipped(self):
        self.assertEqual(parse_fetch_headers([b")", None]), [])

    def test_attributes_after_the_literal_are_read(self):
        """RFC 3501 n'impose pas l'ordre : sinon le message disparaît."""
        got = parse_fetch_headers([HEADERS_TRAILING, TRAILING_ATTRS])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].uid, 103)

    def test_attributes_after_the_literal_keep_flags_and_size(self):
        got = parse_fetch_headers([HEADERS_TRAILING, TRAILING_ATTRS])[0]
        self.assertEqual(got.flags, "\\Answered")
        self.assertEqual(got.size, 99)
        self.assertEqual(got.subject, "Facture")

    def test_both_orders_in_one_response(self):
        got = parse_fetch_headers(
            [HEADERS_1, b")", HEADERS_TRAILING, TRAILING_ATTRS]
        )
        self.assertEqual([m.uid for m in got], [101, 103])


class TestTransport(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.transport = ImaplibTransport(self.client)

    def test_list_folders(self):
        self.client.list.return_value = (
            "OK",
            [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Sent) "/" "Sent"'],
        )
        names = [f.name for f in self.transport.list_folders()]
        self.assertEqual(names, ["INBOX", "Sent"])

    def test_list_failure_raises(self):
        self.client.list.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.list_folders()

    def test_select_reads_uidvalidity_and_uidnext(self):
        self.client.select.return_value = ("OK", [b"42"])
        self.client.response.side_effect = lambda k: {
            "UIDVALIDITY": ("OK", [b"7"]),
            "UIDNEXT": ("OK", [b"103"]),
        }[k]
        info = self.transport.select("INBOX")
        self.assertEqual(
            (info.uidvalidity, info.uidnext, info.exists), (7, 103, 42)
        )

    def test_select_failure_raises(self):
        self.client.select.return_value = ("NO", [b"pas de boite"])
        with self.assertRaises(ImapError):
            self.transport.select("ABSENT")

    def test_search_uids(self):
        self.client.uid.return_value = ("OK", [b"101 102 103"])
        self.assertEqual(self.transport.search_uids(101), [101, 102, 103])

    def test_search_empty(self):
        self.client.uid.return_value = ("OK", [b""])
        self.assertEqual(self.transport.search_uids(1), [])

    def test_fetch_headers_empty_list_skips_network(self):
        self.assertEqual(self.transport.fetch_headers([]), [])
        self.client.uid.assert_not_called()

    def test_fetch_body(self):
        self.client.uid.return_value = (
            "OK",
            [(b"1 (UID 101 BODY[] {5}", b"corps"), b")"],
        )
        self.assertEqual(self.transport.fetch_body(101), b"corps")

    def test_fetch_body_failure_raises(self):
        self.client.uid.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.fetch_body(101)

    def test_store_flags_add_and_remove(self):
        self.client.uid.return_value = ("OK", [b""])
        self.transport.store_flags(101, ["\\Seen"], ["\\Flagged"])
        calls = [c.args for c in self.client.uid.call_args_list]
        self.assertIn(("STORE", "101", "+FLAGS", "(\\Seen)"), calls)
        self.assertIn(("STORE", "101", "-FLAGS", "(\\Flagged)"), calls)

    def test_logout_is_forgiving(self):
        self.client.logout.side_effect = OSError("déjà fermé")
        self.transport.logout()  # ne doit pas lever


class TestFetchFlags(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.transport = ImaplibTransport(self.client)

    def test_empty_list_skips_the_network(self):
        self.assertEqual(self.transport.fetch_flags([]), [])
        self.client.uid.assert_not_called()

    def test_parses_bare_lines(self):
        self.client.uid.return_value = (
            "OK",
            [b"1 (UID 101 FLAGS (\\Seen))", b"2 (UID 102 FLAGS ())"],
        )
        self.assertEqual(
            self.transport.fetch_flags([101, 102]),
            [(101, "\\Seen"), (102, "")],
        )

    def test_skips_entries_without_a_uid(self):
        self.client.uid.return_value = (
            "OK",
            [b")", None, b"1 (UID 101 FLAGS (\\Seen))"],
        )
        self.assertEqual(self.transport.fetch_flags([101]), [(101, "\\Seen")])

    def test_failure_raises(self):
        self.client.uid.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.fetch_flags([101])


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.transport = ImaplibTransport(self.client)

    def test_quotes_the_folder_and_joins_the_flags(self):
        self.client.append.return_value = ("OK", [b"fait"])
        self.transport.append("Sent Items", b"brut", ["\\Seen"])
        self.client.append.assert_called_once_with(
            '"Sent Items"', "(\\Seen)", None, b"brut"
        )

    def test_failure_raises(self):
        self.client.append.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.append("Sent", b"brut", [])


class TestConnect(unittest.TestCase):
    """`connect` est le code le plus sensible au protocole du fichier.

    Aucun de ces tests ne joint le réseau : `imaplib` est remplacé.
    """

    def _account(self, security):
        account = account_from_preset("perso", "moi@x.ca", "generic")
        account.imap.host = "imap.x.ca"
        account.imap.port = 993
        account.imap.security = security
        return account

    def test_ssl_branch(self):
        client = MagicMock()
        with patch("imaplib.IMAP4_SSL", return_value=client) as ctor:
            transport = connect(self._account("ssl"), "hunter2")
        ctor.assert_called_once_with("imap.x.ca", 993, timeout=30)
        client.login.assert_called_once_with("moi@x.ca", "hunter2")
        self.assertIsInstance(transport, ImaplibTransport)

    def test_starttls_branch_upgrades(self):
        client = MagicMock()
        with patch("imaplib.IMAP4", return_value=client) as ctor:
            connect(self._account("starttls"), "hunter2")
        client.starttls.assert_called_once()
        ctor.assert_called_once_with("imap.x.ca", 993, timeout=30)

    def test_plain_branch_does_not_upgrade(self):
        client = MagicMock()
        with patch("imaplib.IMAP4", return_value=client):
            connect(self._account("none"), "hunter2")
        client.starttls.assert_not_called()

    def test_login_failure_becomes_an_imap_error(self):
        client = MagicMock()
        client.login.side_effect = OSError("530 refus")
        with patch("imaplib.IMAP4_SSL", return_value=client):
            with self.assertRaises(ImapError) as ctx:
                connect(self._account("ssl"), "mauvais")
        self.assertIn("530", str(ctx.exception))

    def test_a_non_ascii_password_says_it_never_left(self):
        """`imaplib` encode LOGIN en ASCII : un mot de passe accentué
        n'atteint pas le serveur. Le message général dit « refusée », ce qui
        accuserait le serveur d'un refus qu'il n'a pas prononcé — et
        enverrait chercher la panne du mauvais côté du réseau."""
        client = MagicMock()
        client.login.side_effect = UnicodeEncodeError(
            "ascii", "motdepassé", 10, 11, "ordinal not in range(128)"
        )
        with patch("imaplib.IMAP4_SSL", return_value=client):
            with self.assertRaises(ImapError) as ctx:
                connect(self._account("ssl"), "motdepassé")
        message = str(ctx.exception)
        self.assertIn("ASCII", message)
        self.assertNotIn("refusée", message)
        self.assertNotIn("ordinal", message)

    def test_connection_failure_becomes_an_imap_error(self):
        with patch("imaplib.IMAP4_SSL", side_effect=OSError("injoignable")):
            with self.assertRaises(ImapError):
                connect(self._account("ssl"), "hunter2")
