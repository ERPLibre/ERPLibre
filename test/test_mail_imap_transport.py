#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import calendar
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_transport import (
    EXTRA_HEADERS,
    HEADER_FIELDS,
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


class TestThreadHeaders(unittest.TestCase):
    """Fils de discussion (phase 3) : sans `In-Reply-To`, aucun délai de
    réponse n'est calculable."""

    def _data(self, entetes: bytes, uid: int = 7):
        return [
            (
                b"1 (UID %d RFC822.SIZE 100 FLAGS (\\Seen) "
                b"BODY[HEADER.FIELDS (X)] {%d}" % (uid, len(entetes)),
                entetes,
            ),
            b")",
        ]

    BASE = (
        b"From: a@x.ca\r\nSubject: Re: Devis\r\n"
        b"Message-ID: <r1@x.ca>\r\n"
        b"Date: Wed, 06 Aug 2026 10:00:00 +0000\r\n"
    )

    def test_the_server_is_asked_for_them(self):
        """Sans ces champs dans la requête, l'extraction serait du code
        mort : le serveur ne renverrait jamais ces en-têtes."""
        self.assertIn("IN-REPLY-TO", HEADER_FIELDS)
        self.assertIn("REFERENCES", HEADER_FIELDS)

    def test_in_reply_to_is_extracted(self):
        entetes = self.BASE + b"In-Reply-To: <orig@x.ca>\r\n\r\n"
        self.assertEqual(
            parse_fetch_headers(self._data(entetes))[0].in_reply_to,
            "<orig@x.ca>",
        )

    def test_references_are_extracted(self):
        entetes = self.BASE + b"References: <a@x.ca> <orig@x.ca>\r\n\r\n"
        self.assertEqual(
            parse_fetch_headers(self._data(entetes))[0].references,
            "<a@x.ca> <orig@x.ca>",
        )

    def test_absent_headers_are_empty_not_none(self):
        entetes = self.BASE + b"\r\n"
        info = parse_fetch_headers(self._data(entetes))[0]
        self.assertEqual((info.in_reply_to, info.references), ("", ""))

    def test_raw_8bit_bytes_do_not_lose_the_message(self):
        """Même piège que la date : un en-tête 8 bits revient en `Header`,
        et `.strip()` y lèverait — emportant le dossier entier."""
        entetes = self.BASE + b"In-Reply-To: <ori\xffg@x.ca>\r\n\r\n"
        infos = parse_fetch_headers(self._data(entetes))
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].uid, 7)

    def test_a_raw_8bit_message_id_does_not_lose_the_message(self):
        """Le Message-ID suit la même garde : un `Header` y lèverait aussi,
        et le curseur du dossier n'avancerait plus jamais."""
        entetes = (
            b"From: carole.regle@example.org\r\nSubject: Devis\r\n"
            b"Message-ID: <\xff@example.org>\r\n\r\n"
        )
        infos = parse_fetch_headers(self._data(entetes))
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].uid, 7)
        self.assertIsInstance(infos[0].msgid, str)
        self.assertTrue(infos[0].msgid.endswith("@example.org>"))


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


class TestRulesHeaders(unittest.TestCase):
    """v6 : INTERNALDATE, `Cc` et les en-têtes que lisent les garde-fous des
    règles de courriel entrant."""

    BASE = (
        b"From: carole.regle@example.org\r\n"
        b"To: boite.regles@example.org\r\n"
        b"Subject: Absence\r\n"
        b"Message-ID: <v6@example.org>\r\n"
    )
    RECU = b"06-Aug-2026 10:00:00 +0000"
    RECU_EPOCH = calendar.timegm((2026, 8, 6, 10, 0, 0))

    def _avant(self, entetes: bytes, date: bytes = RECU, uid: int = 7):
        """INTERNALDATE dans le préfixe, AVANT le littéral."""
        return [
            (
                b'1 (UID %d FLAGS () INTERNALDATE "%s" RFC822.SIZE 100 '
                b"BODY[HEADER.FIELDS (X)] {%d}" % (uid, date, len(entetes)),
                entetes,
            ),
            b")",
        ]

    def _info(self, entetes: bytes):
        return parse_fetch_headers(self._avant(entetes + b"\r\n"))[0]

    def test_internaldate_before_the_literal(self):
        info = self._info(self.BASE)
        self.assertEqual(info.internaldate, self.RECU_EPOCH)

    def test_internaldate_after_the_literal(self):
        """L'attribut peut SUIVRE le littéral : il se lit alors dans
        l'entrée suivante, comme UID et FLAGS."""
        entetes = self.BASE + b"\r\n"
        data = [
            (
                b"2 (BODY[HEADER.FIELDS (X)] {%d}" % len(entetes),
                entetes,
            ),
            b' UID 8 INTERNALDATE "06-Aug-2026 10:00:00 +0000")',
        ]
        info = parse_fetch_headers(data)[0]
        self.assertEqual((info.uid, info.internaldate), (8, self.RECU_EPOCH))

    def test_internaldate_with_an_offset_is_converted_to_utc(self):
        data = self._avant(self.BASE + b"\r\n", b"06-Aug-2026 06:00:00 -0400")
        self.assertEqual(
            parse_fetch_headers(data)[0].internaldate, self.RECU_EPOCH
        )

    def test_unreadable_internaldate_is_zero_without_losing_the_message(self):
        data = self._avant(self.BASE + b"\r\n", b"31-Foo-2026 99:00:00 +0000")
        infos = parse_fetch_headers(data)
        self.assertEqual(len(infos), 1)
        self.assertEqual((infos[0].uid, infos[0].internaldate), (7, 0))
        self.assertEqual(infos[0].subject, "Absence")

    def test_missing_internaldate_is_zero(self):
        entetes = self.BASE + b"\r\n"
        data = [
            (
                b"1 (UID 9 FLAGS () BODY[HEADER.FIELDS (X)] {%d}"
                % len(entetes),
                entetes,
            ),
            b")",
        ]
        self.assertEqual(parse_fetch_headers(data)[0].internaldate, 0)

    def test_cc_is_decoded(self):
        info = self._info(
            self.BASE + b"Cc: =?utf-8?q?Bruno_Filtr=C3=A9?="
            b" <bruno.filtre@example.net>\r\n"
        )
        self.assertEqual(info.cc, "Bruno Filtré <bruno.filtre@example.net>")

    def test_missing_cc_is_empty(self):
        self.assertEqual(self._info(self.BASE).cc, "")

    def test_two_x_loop_are_joined_in_message_order(self):
        info = self._info(
            self.BASE + b"X-Loop: erplibre-rules boite.regles@example.org\r\n"
            b"X-Loop: liste-annonces@example.net\r\n"
        )
        self.assertEqual(
            info.extra["x-loop"],
            "erplibre-rules boite.regles@example.org\n"
            "liste-annonces@example.net",
        )

    def test_a_folded_header_is_unfolded_without_cr_or_lf(self):
        info = self._info(
            self.BASE + b"Authentication-Results: mx.example.org;\r\n"
            b"\tspf=pass smtp.mailfrom=example.org;\r\n"
            b"  dmarc=pass header.from=example.org\r\n"
        )
        valeur = info.extra["authentication-results"]
        self.assertEqual(
            valeur,
            "mx.example.org; spf=pass smtp.mailfrom=example.org;"
            " dmarc=pass header.from=example.org",
        )
        self.assertNotIn("\r", valeur)
        self.assertNotIn("\n", valeur)

    def test_an_absent_header_has_no_key(self):
        info = self._info(self.BASE + b"Auto-Submitted: auto-replied\r\n")
        self.assertEqual(info.extra, {"auto-submitted": "auto-replied"})
        self.assertNotIn("list-id", info.extra)

    def test_every_extra_header_reaches_the_dict_in_lower_case(self):
        lignes = b"".join(
            nom.encode() + b": valeur\r\n" for nom in EXTRA_HEADERS
        )
        info = self._info(self.BASE + lignes)
        self.assertEqual(
            sorted(info.extra), sorted(n.lower() for n in EXTRA_HEADERS)
        )

    def test_extra_values_are_not_rfc2047_decoded(self):
        """Ce sont des jetons machine, comparés tels quels."""
        info = self._info(self.BASE + b"X-Spam-Flag: =?utf-8?q?YES?=\r\n")
        self.assertEqual(info.extra["x-spam-flag"], "=?utf-8?q?YES?=")

    def test_header_fields_ask_for_cc_and_every_extra_header(self):
        """Sans ces noms dans la requête, le serveur ne renverrait jamais
        les en-têtes que les garde-fous lisent."""
        demandes = HEADER_FIELDS.split()
        self.assertIn("CC", demandes)
        for nom in EXTRA_HEADERS:
            self.assertIn(nom.upper(), demandes)

    def test_content_type_and_resent_from_are_extra_headers(self):
        """Une redirection revenue et un rapport de remise se reconnaissent
        sans télécharger le corps."""
        self.assertIn("Content-Type", EXTRA_HEADERS)
        self.assertIn("Resent-From", EXTRA_HEADERS)
        demandes = HEADER_FIELDS.split()
        self.assertIn("CONTENT-TYPE", demandes)
        self.assertIn("RESENT-FROM", demandes)
        info = self._info(
            self.BASE + b"Content-Type: multipart/report;\r\n"
            b" report-type=delivery-status; boundary=x\r\n"
            b"Resent-From: boite.regles@example.org\r\n"
            b"Resent-From: relais.auto@example.com\r\n"
        )
        self.assertEqual(
            info.extra["content-type"],
            "multipart/report; report-type=delivery-status; boundary=x",
        )
        self.assertEqual(
            info.extra["resent-from"],
            "boite.regles@example.org\nrelais.auto@example.com",
        )

    def test_fetch_headers_asks_for_internaldate(self):
        client = MagicMock()
        client.uid.return_value = ("OK", [])
        ImaplibTransport(client).fetch_headers([1, 2])
        spec = client.uid.call_args[0][2]
        self.assertIn("INTERNALDATE", spec)
        self.assertIn(f"BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})]", spec)


@unittest.skipUnless(
    os.path.exists("/usr/share/zoneinfo/America/Montreal"),
    "base de fuseaux horaires absente",
)
class TestInternaldateAcrossTheRepeatedHour(unittest.TestCase):
    """Au passage à l'heure normale, 01:30 locale existe deux fois. La
    conversion passe par un temps LOCAL ; elle reste exacte parce que
    `Internaldate2tuple` pose `tm_isdst` et que `mktime` le respecte."""

    def setUp(self):
        ancien = os.environ.get("TZ")

        def restaurer():
            if ancien is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = ancien
            time.tzset()

        self.addCleanup(restaurer)
        os.environ["TZ"] = "America/Montreal"
        time.tzset()

    def _epoch(self, date: bytes) -> int:
        entetes = b"Subject: heure\r\n\r\n"
        data = [
            (
                b'1 (UID 1 INTERNALDATE "%s" BODY[HEADER.FIELDS (X)] {%d}'
                % (date, len(entetes)),
                entetes,
            ),
            b")",
        ]
        return parse_fetch_headers(data)[0].internaldate

    def test_the_first_pass_of_the_hour_is_exact(self):
        self.assertEqual(
            self._epoch(b"01-Nov-2026 01:30:00 -0400"),
            calendar.timegm((2026, 11, 1, 5, 30, 0)),
        )

    def test_the_second_pass_of_the_hour_is_exact(self):
        self.assertEqual(
            self._epoch(b"01-Nov-2026 01:30:00 -0500"),
            calendar.timegm((2026, 11, 1, 6, 30, 0)),
        )


if __name__ == "__main__":
    unittest.main()
