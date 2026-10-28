#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Transfert et redirection d'un message reçu : construction et remise.

Ce que ces tests figent : une destination se ramène à sa forme d'envoi ou
est refusée ; un transfert garde la structure d'origine, porte nos
en-têtes automatiques et cache ses destinations les unes aux autres ; un
message signé part en pièce jointe ; une redirection est l'original octet
pour octet sous un seul bloc `Resent-*`, sans Cci, en CRLF, remis à son
enveloppe explicite et jamais aux en-têtes.
"""

import email
import email.policy
import smtplib
import unittest
from unittest import mock

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import (
    REDIRECT_DROPPED_FIELDS,
    UNDISCLOSED_RECIPIENTS,
    RawOutgoing,
    SmtpError,
    SmtplibTransport,
    build_forward_attached,
    build_forward_inline,
    build_message,
    build_redirect,
    forward_subject,
    parse_envelope,
    recipients,
    send,
    smtp_address,
    strip_header_fields,
    to_crlf,
    without_bcc,
)
from script.todo.todo_i18n import t

OWN = "boite.regles@example.org"
BRUNO = "bruno.filtre@example.net"
CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
TEMOIN = "temoin.cci@example.com"
RELAIS = "relais.auto@example.com"
IDN_UNICODE = "bruno.filtre@filtré.example.net"
IDN_ACE = "bruno.filtre@xn--filtr-fsa.example.net"
DATE = "Wed, 28 Oct 2026 10:00:00 +0000"
MSGID = "<transfert-1@example.org>"

# Original de référence : mixte = alternative (texte, related HTML + image
# `cid:`) + PDF joint, avec en-têtes d'acheminement et un Cci plié.
ORIGINAL = (
    b"Return-Path: <bruno.filtre@example.net>\r\n"
    b"Received: from mx.example.org by mx.example.org;\r\n"
    b" Wed, 28 Oct 2026 09:00:00 +0000\r\n"
    b"DKIM-Signature: v=1; a=rsa-sha256; d=example.net; s=sel;\r\n"
    b" h=from:to:subject; bh=YWJj; b=ZGVm\r\n"
    b"From: Bruno Filtre <bruno.filtre@example.net>\r\n"
    b"To: carole.regle@example.org\r\n"
    b"Cc: temoin.cci@example.com\r\n"
    b"Bcc:\r\n"
    b" temoin.cci@example.com\r\n"
    b"Subject: =?utf-8?q?Devis_r=C3=A9vis=C3=A9?=\r\n"
    b"Date: Wed, 28 Oct 2026 09:00:00 +0000\r\n"
    b"Message-ID: <orig-1@example.net>\r\n"
    b"X-Loop: liste-annonces@example.net\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="mix"\r\n'
    b"\r\n"
    b"--mix\r\n"
    b'Content-Type: multipart/alternative; boundary="alt"\r\n'
    b"\r\n"
    b"--alt\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Content-Transfer-Encoding: 8bit\r\n"
    b"\r\n"
    b"Bonjour, voici le devis r\xc3\xa9vis\xc3\xa9.\r\n"
    b"--alt\r\n"
    b'Content-Type: multipart/related; boundary="rel"\r\n'
    b"\r\n"
    b"--rel\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"Content-Transfer-Encoding: 8bit\r\n"
    b"\r\n"
    b'<html><head></head><BODY class="m"><p>Bonjour, voici le devis'
    b' <b>r\xc3\xa9vis\xc3\xa9</b>.</p><img src="cid:logo@example.net">'
    b"</BODY></html>\r\n"
    b"--rel\r\n"
    b"Content-Type: image/png\r\n"
    b"Content-ID: <logo@example.net>\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b'Content-Disposition: inline; filename="logo.png"\r\n'
    b"\r\n"
    b"iVBORw0KGgo=\r\n"
    b"--rel--\r\n"
    b"--alt--\r\n"
    b"--mix\r\n"
    b'Content-Type: application/pdf; name="devis.pdf"\r\n'
    b'Content-Disposition: attachment; filename="devis.pdf"\r\n'
    b"Content-Transfer-Encoding: base64\r\n"
    b"\r\n"
    b"JVBERi0xLjQK\r\n"
    b"--mix--\r\n"
)


def simple(headers: bytes, body: bytes = b"Bonjour.\r\n") -> bytes:
    """Un message texte d'une partie, d'en-têtes `headers` (CRLF)."""
    return (
        b"From: Bruno Filtre <bruno.filtre@example.net>\r\n"
        b"To: boite.regles@example.org\r\n"
        b"Subject: Question\r\n"
        b"Message-ID: <simple@example.net>\r\n" + headers + b"\r\n" + body
    )


def relu(msg):
    """`msg` sérialisé puis relu, comme le lira la destination."""
    return email.message_from_bytes(
        msg.as_bytes(), policy=email.policy.default
    )


def entete(raw: bytes) -> bytes:
    """La section d'en-têtes de la racine de `raw`."""
    for sep in (b"\r\n\r\n", b"\n\n"):
        if sep in raw:
            return raw.split(sep, 1)[0]
    return raw


class ForwardCase(unittest.TestCase):
    def setUp(self):
        self.account = account_from_preset("perso", OWN, "generic")

    def inline(self, raw=ORIGINAL, to=(CAROLE, DENIS), **kw):
        kw.setdefault("date", DATE)
        kw.setdefault("msgid", MSGID)
        return build_forward_inline(self.account, raw, list(to), **kw)

    def attached(self, raw=ORIGINAL, to=(CAROLE, DENIS), **kw):
        kw.setdefault("date", DATE)
        kw.setdefault("msgid", MSGID)
        return build_forward_attached(self.account, raw, list(to), **kw)

    def redirect(self, raw=ORIGINAL, to=(CAROLE, DENIS)):
        return build_redirect(
            self.account,
            raw,
            list(to),
            date=DATE,
            msgid="<resent-1@example.org>",
        )

    def assert_attached(self, msg):
        types = [p.get_content_type() for p in relu(msg).iter_parts()]
        self.assertEqual(types, ["text/plain", "message/rfc822"])


class TestSmtpAddress(unittest.TestCase):
    def test_plain_address_is_kept(self):
        self.assertEqual(smtp_address(CAROLE), CAROLE)
        self.assertEqual(
            smtp_address("Carole.Regle@example.org"),
            "Carole.Regle@example.org",
        )

    def test_domain_is_lowercased_and_idna_encoded(self):
        self.assertEqual(smtp_address(IDN_UNICODE), IDN_ACE)
        self.assertEqual(
            smtp_address("bruno.filtre@Filtré.Example.NET"), IDN_ACE
        )
        self.assertEqual(smtp_address(IDN_ACE), IDN_ACE)
        self.assertEqual(
            smtp_address("denis.tri@EXAMPLE.org"), "denis.tri@example.org"
        )

    def test_quoted_or_non_ascii_local_part_is_refused(self):
        for adresse in (
            '"carole regle"@example.org',
            '"carole"@example.org',
            "carolé.regle@example.org",
        ):
            with self.subTest(adresse=adresse):
                with self.assertRaises(SmtpError) as ctx:
                    smtp_address(adresse)
                self.assertIn(
                    t("mail_rules_err_fwd_address"), str(ctx.exception)
                )

    def test_garbage_is_refused(self):
        for adresse in (
            "",
            "carole regle@example.org",
            " carole.regle@example.org",
            "carole.regle@exa mple.org",
            "carole@regle@example.org",
            "carole.regle",
            "carole.regle@example",
            "carole.regle@-filtre.example.org",
            "carole.regle@filtre-.example.org",
            "carole,regle@example.org",
            f"{CAROLE},{DENIS}",
            "<carole.regle@example.org>",
            "carole.regle@xn--zz.example.net",
            "carole.regle@[192.0.2.1]",
            "carole.regle@192.0.2.1",
            "carole..regle@example.org",
            "carole.regle@example..org",
            "carole.regle@example.org.",
            "a" * 65 + "@example.org",
            "carole.regle@" + "a" * 250 + ".org",
            None,
        ):
            with self.subTest(adresse=adresse):
                with self.assertRaises(SmtpError):
                    smtp_address(adresse)

    def test_an_idna_deviation_character_is_refused(self):
        for adresse in (
            "denis.tri@straße.example.org",
            "denis.tri@STRAẞE.example.org",
            "denis.tri@ας.example.org",
            "denis.tri@fil\u200ctre.example.org",
            "denis.tri@fil\u200dtre.example.org",
        ):
            with self.subTest(adresse=adresse):
                with self.assertRaises(SmtpError) as ctx:
                    smtp_address(adresse)
                self.assertIn(
                    t("mail_rules_err_fwd_address"), str(ctx.exception)
                )
        self.assertEqual(
            smtp_address("denis.tri@strasse.example.org"),
            "denis.tri@strasse.example.org",
        )

    def test_parse_envelope_round_trips_the_queue_text(self):
        cibles = (CAROLE, DENIS, IDN_ACE)
        self.assertEqual(parse_envelope(", ".join(cibles)), cibles)
        self.assertEqual(
            parse_envelope(f" {CAROLE} ,{DENIS}, CAROLE.regle@example.org"),
            (CAROLE, DENIS),
        )

    def test_parse_envelope_refuses_an_empty_text(self):
        for texte in ("", " ", " , ", None):
            with self.subTest(texte=texte):
                with self.assertRaises(SmtpError):
                    parse_envelope(texte)
        with self.assertRaises(SmtpError):
            parse_envelope(f"{CAROLE}, pas une adresse")


class TestStripHeaderFields(unittest.TestCase):
    def test_folded_bcc_is_removed_with_its_continuation(self):
        sortie = strip_header_fields(ORIGINAL, {"bcc"})
        self.assertNotIn(b"Bcc:", sortie)
        self.assertEqual(
            sortie,
            ORIGINAL.replace(b"Bcc:\r\n temoin.cci@example.com\r\n", b""),
        )
        # Le Cc qui précède et le Subject qui suit sont intacts.
        self.assertIn(b"Cc: temoin.cci@example.com\r\nSubject:", sortie)

    def test_body_lines_that_look_like_headers_stay(self):
        raw = simple(b"Bcc: temoin.cci@example.com\r\n", b"Bcc: corps\r\n")
        sortie = strip_header_fields(raw, {"bcc"})
        self.assertTrue(sortie.endswith(b"\r\n\r\nBcc: corps\r\n"))
        self.assertNotIn(TEMOIN.encode(), sortie)

    def test_lf_only_message_is_handled(self):
        raw = (
            b"From: bruno.filtre@example.net\n"
            b"Bcc: temoin.cci@example.com,\n"
            b"\tdenis.tri@example.org\n"
            b"Subject: s\n"
            b"\n"
            b"Bcc: corps\n"
        )
        self.assertEqual(
            strip_header_fields(raw, {"bcc"}),
            b"From: bruno.filtre@example.net\nSubject: s\n\nBcc: corps\n",
        )
        sans_corps = (
            b"From: bruno.filtre@example.net\nBcc: temoin.cci@example.com\n"
        )
        self.assertEqual(
            strip_header_fields(sans_corps, {"bcc"}),
            b"From: bruno.filtre@example.net\n",
        )

    def test_names_are_compared_without_case(self):
        raw = simple(
            b"BCC: temoin.cci@example.com\r\n"
            b"return-PATH: <bruno.filtre@example.net>\r\n"
            b"Resent-Bcc : temoin.cci@example.com\r\n"
        )
        sortie = strip_header_fields(raw, REDIRECT_DROPPED_FIELDS)
        self.assertNotIn(TEMOIN.encode(), sortie)
        self.assertNotIn(b"return-PATH", sortie)
        self.assertIn(b"Subject: Question\r\n", sortie)

    def test_to_crlf_normalises_bare_lf_and_bare_cr(self):
        self.assertEqual(to_crlf(b"a\nb\rc\r\nd"), b"a\r\nb\r\nc\r\nd")
        self.assertEqual(to_crlf(b"\r\r\n\n"), b"\r\n\r\n\r\n")
        once = to_crlf(b"a\nb\r\rc\r\n")
        self.assertEqual(to_crlf(once), once)


class TestForwardSubject(ForwardCase):
    def test_control_characters_in_the_subject_are_neutralised(self):
        encode = "=?utf-8?q?a=00b=1Bc?="
        sujet = forward_subject(encode)
        self.assertEqual(sujet, "Fwd: a b c")
        raw = simple(b"").replace(
            b"Subject: Question", b"Subject: " + encode.encode()
        )
        for msg in (self.inline(raw), self.attached(raw)):
            with self.subTest(type=msg.get_content_type()):
                self.assertNotIn("\x00", str(msg["Subject"]))
                self.assertNotIn("\x1b", str(msg["Subject"]))
                self.assertNotIn(b"\x00", msg.as_bytes())
                self.assertNotIn(b"\x1b", msg.as_bytes())
        redirection = self.redirect(raw)
        self.assertEqual(redirection.subject, "a b c")


class TestForwardInline(ForwardCase):
    def test_headers_are_ours_and_reply_to_is_the_given_one(self):
        msg = relu(self.inline(reply_to=BRUNO))
        self.assertEqual(msg["From"], self.account.from_header())
        self.assertEqual(msg["Reply-To"], BRUNO)
        self.assertEqual(msg["Date"], DATE)
        self.assertEqual(msg["Message-ID"], MSGID)
        self.assertIsNone(relu(self.inline())["Reply-To"])

    def test_a_line_break_in_reply_to_is_refused(self):
        with self.assertRaises(SmtpError):
            self.inline(reply_to=f"{BRUNO}\r\nBcc: {TEMOIN}")

    def test_subject_gets_one_fwd_prefix(self):
        self.assertEqual(relu(self.inline())["Subject"], "Fwd: Devis révisé")
        raw = simple(b"").replace(b"Subject: Question", b"Subject: FWD: x")
        self.assertEqual(relu(self.inline(raw))["Subject"], "FWD: x")

    def test_text_part_starts_with_intro_and_original_headers(self):
        msg = relu(self.inline(intro="Pour suite.\n"))
        texte = msg.get_body(("plain",)).get_content()
        attendu = (
            "Pour suite.\n\n"
            f"{t('mail_rules_fwd_separator')}\n"
            f"{t('mail_rules_fwd_from')} Bruno Filtre <{BRUNO}>\n"
            f"{t('mail_rules_fwd_date')} Wed, 28 Oct 2026 09:00:00 +0000\n"
            f"{t('mail_rules_fwd_to')} {CAROLE}\n"
            f"{t('mail_rules_fwd_cc')} {TEMOIN}\n"
            f"{t('mail_rules_fwd_subject')} Devis révisé\n\n"
            "Bonjour, voici le devis révisé."
        )
        self.assertTrue(texte.startswith(attendu), texte)

    def test_without_intro_the_block_comes_first(self):
        texte = relu(self.inline()).get_body(("plain",)).get_content()
        self.assertTrue(texte.startswith(t("mail_rules_fwd_separator")))

    def test_html_part_gets_the_block_right_after_body(self):
        msg = relu(self.inline(intro="A <b> & B\nsuite"))
        page = msg.get_body(("html",)).get_content()
        balise = '<BODY class="m">'
        apres = page[page.index(balise) + len(balise) :]
        self.assertTrue(
            apres.startswith("<div><p>A &lt;b&gt; &amp; B<br>suite</p><p>"),
            apres,
        )
        self.assertIn(f"Bruno Filtre &lt;{BRUNO}&gt;", apres)
        self.assertIn("<b>révisé</b>", apres)
        self.assertTrue(page.startswith("<html><head></head>"))

    def test_html_without_body_tag_gets_the_block_first(self):
        raw = simple(
            b"MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n",
            b"<p>Bonjour</p>\r\n",
        )
        page = relu(self.inline(raw)).get_body(("html",)).get_content()
        self.assertTrue(page.startswith("<div>"), page)
        self.assertIn("<p>Bonjour</p>", page)

    def test_related_images_and_attachments_survive(self):
        msg = relu(self.inline())
        types = [p.get_content_type() for p in msg.walk()]
        self.assertEqual(
            types,
            [
                "multipart/mixed",
                "multipart/alternative",
                "text/plain",
                "multipart/related",
                "text/html",
                "image/png",
                "application/pdf",
            ],
        )
        image = [p for p in msg.walk() if p.get_content_type() == "image/png"]
        self.assertEqual(image[0]["Content-ID"], "<logo@example.net>")
        pdf = [p for p in msg.iter_attachments()]
        self.assertEqual([p.get_filename() for p in pdf], ["devis.pdf"])
        self.assertEqual(pdf[0].get_content(), b"%PDF-1.4\n")

    def test_original_routing_headers_are_gone(self):
        msg = self.inline()
        noms = {n.lower() for n in msg.keys()}
        for nom in ("received", "dkim-signature", "return-path", "bcc", "cc"):
            self.assertNotIn(nom, noms)
        self.assertNotIn(TEMOIN.encode(), entete(msg.as_bytes()))

    def test_no_in_reply_to_or_references(self):
        msg = relu(self.inline())
        self.assertIsNone(msg["In-Reply-To"])
        self.assertIsNone(msg["References"])

    def test_auto_submitted_x_loop_and_suppress_are_set(self):
        msg = relu(self.inline())
        self.assertEqual(msg["Auto-Submitted"], "auto-generated")
        self.assertEqual(msg["X-Auto-Response-Suppress"], "All")
        self.assertEqual(msg.get_all("X-Loop")[-1], f"erplibre-rules {OWN}")
        self.assertEqual(msg["MIME-Version"], "1.0")

    def test_existing_x_loop_fields_are_kept(self):
        raw = simple(
            b"X-Loop: liste-annonces@example.net\r\n"
            b"X-Loop: relais\r\n\tauto@example.com\r\n"
        )
        boucles = relu(self.inline(raw)).get_all("X-Loop")
        self.assertEqual(
            boucles,
            [
                "liste-annonces@example.net",
                "relais auto@example.com",
                f"erplibre-rules {OWN}",
            ],
        )

    def test_targets_do_not_see_each_other(self):
        msg = self.inline()
        self.assertEqual(str(msg["To"]), UNDISCLOSED_RECIPIENTS)
        visible = entete(without_bcc(msg).as_bytes())
        for cible in (CAROLE, DENIS):
            self.assertNotIn(cible.encode(), visible)
        self.assertEqual(recipients(msg), [CAROLE, DENIS])

    def test_reply_all_cannot_reach_other_targets(self):
        envoye = relu(without_bcc(self.inline(reply_to=BRUNO)))
        for nom in ("To", "Cc", "Reply-To"):
            valeur = str(envoye.get(nom) or "")
            self.assertNotIn(CAROLE, valeur)
            self.assertNotIn(DENIS, valeur)

    def test_targets_are_in_sending_form_and_deduplicated(self):
        msg = self.inline(to=(IDN_UNICODE, CAROLE, "CAROLE.regle@example.org"))
        self.assertEqual(recipients(msg), [IDN_ACE, CAROLE])

    def test_an_invalid_or_missing_target_is_refused(self):
        with self.assertRaises(SmtpError):
            self.inline(to=())
        with self.assertRaises(SmtpError):
            self.inline(to=(CAROLE, '"x"@example.org'))

    def test_single_part_non_ascii_text_is_forwarded_inline(self):
        raw = simple(
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n",
            "Café crème, é.\r\n".encode(),
        )
        msg = relu(self.inline(raw))
        self.assertEqual(msg.get_content_type(), "text/plain")
        texte = msg.get_content()
        self.assertIn(t("mail_rules_fwd_separator"), texte)
        self.assertTrue(texte.rstrip().endswith("Café crème, é."), texte)

    def test_single_part_html_root_is_forwarded_inline(self):
        raw = simple(
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/html; charset=iso-8859-1\r\n"
            b"Content-Transfer-Encoding: quoted-printable\r\n",
            b"<html><body><p>Caf=E9 cr=E8me</p></body></html>\r\n",
        )
        msg = relu(self.inline(raw))
        self.assertEqual(msg.get_content_type(), "text/html")
        page = msg.get_content()
        self.assertIn("<body><div>", page)
        self.assertIn("<p>Café crème</p>", page)

    def test_signed_message_falls_back_to_attachment(self):
        raw = simple(
            b"Bcc: temoin.cci@example.com\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: multipart/signed; boundary=sig;"
            b' protocol="application/pgp-signature"\r\n',
            b"--sig\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Texte signe.\r\n"
            b"--sig\r\n"
            b"Content-Type: application/pgp-signature\r\n\r\n"
            b"SIGNATURE\r\n"
            b"--sig--\r\n",
        )
        with self.assertLogs("script.todo.mail.smtp_send", "INFO"):
            msg = self.inline(raw)
        self.assert_attached(msg)
        self.assertNotIn(TEMOIN.encode(), msg.as_bytes())
        self.assertIn(b"Texte signe.\r\n--sig", to_crlf(msg.as_bytes()))

    def test_nested_signed_part_falls_back_to_attachment(self):
        raw = simple(
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: multipart/mixed; boundary=liste\r\n",
            b"--liste\r\n"
            b"Content-Type: multipart/signed; boundary=sig;"
            b' protocol="application/pgp-signature"\r\n\r\n'
            b"--sig\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Texte signe.\r\n"
            b"--sig\r\n"
            b"Content-Type: application/pgp-signature\r\n\r\n"
            b"SIGNATURE\r\n"
            b"--sig--\r\n"
            b"--liste\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Pied de liste.\r\n"
            b"--liste--\r\n",
        )
        self.assert_attached(self.inline(raw))

    def test_inline_pgp_falls_back_to_attachment(self):
        raw = simple(
            b"",
            b"-----BEGIN PGP SIGNED MESSAGE-----\r\nHash: SHA256\r\n\r\n"
            b"Texte.\r\n-----BEGIN PGP SIGNATURE-----\r\nx\r\n"
            b"-----END PGP SIGNATURE-----\r\n",
        )
        self.assert_attached(self.inline(raw))

    def test_message_without_text_falls_back_to_attachment(self):
        raw = simple(
            b"MIME-Version: 1.0\r\nContent-Type: image/png\r\n"
            b"Content-Transfer-Encoding: base64\r\n",
            b"iVBORw0KGgo=\r\n",
        )
        self.assert_attached(self.inline(raw))

    def test_a_failing_serialisation_falls_back_to_attachment(self):
        with mock.patch(
            "script.todo.mail.smtp_send._set_text",
            side_effect=LookupError("x-inconnu"),
        ):
            msg = self.inline()
        self.assert_attached(msg)

    def test_unknown_charset_still_builds(self):
        raw = simple(
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain; charset=x-inconnu\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n",
            b"Bonjour tout le monde.\r\n",
        )
        msg = relu(self.inline(raw))
        self.assertEqual(msg.get_content_type(), "text/plain")
        self.assertIn("Bonjour tout le monde.", msg.get_content())

    def test_cc_line_only_when_present(self):
        avec = relu(self.inline()).get_body(("plain",)).get_content()
        self.assertIn(f"\n{t('mail_rules_fwd_cc')} {TEMOIN}\n", avec)
        sans = relu(self.inline(simple(b""))).get_content()
        self.assertNotIn(f"\n{t('mail_rules_fwd_cc')} ", sans)
        self.assertIn(f"\n{t('mail_rules_fwd_to')} {OWN}\n", sans)

    def test_subject_prefix_for_a_trial(self):
        msg = relu(self.inline(subject_prefix="[Essai]"))
        self.assertEqual(msg["Subject"], "[Essai] Fwd: Devis révisé")

    def test_an_empty_raw_is_refused(self):
        with self.assertRaises(SmtpError) as ctx:
            self.inline(b"")
        self.assertIn(t("mail_rules_err_fwd_unreadable"), str(ctx.exception))


class TestForwardAttached(ForwardCase):
    def test_structure_is_text_then_rfc822(self):
        msg = self.attached(intro="Pour suite.")
        self.assert_attached(msg)
        texte = relu(msg).get_body(("plain",)).get_content()
        self.assertTrue(texte.startswith("Pour suite.\n\n"))
        self.assertIn(f"{t('mail_rules_fwd_subject')} Devis révisé", texte)
        jointe = list(relu(msg).iter_attachments())[0]
        self.assertEqual(jointe.get_filename(), "message.eml")

    def test_inner_message_keeps_its_headers(self):
        jointe = list(relu(self.attached()).iter_attachments())[0]
        inner = jointe.get_content()
        self.assertEqual(inner["Message-ID"], "<orig-1@example.net>")
        self.assertEqual(inner["From"], f"Bruno Filtre <{BRUNO}>")
        self.assertIn("Received", inner)
        self.assertIn("DKIM-Signature", inner)
        self.assertEqual(inner["Subject"], "Devis révisé")
        self.assertEqual(
            [p.get_content_type() for p in inner.walk()][-1],
            "application/pdf",
        )

    def test_auto_headers_are_set(self):
        msg = relu(self.attached(reply_to=BRUNO))
        self.assertEqual(msg["From"], self.account.from_header())
        self.assertEqual(msg["To"], UNDISCLOSED_RECIPIENTS)
        self.assertEqual(msg["Reply-To"], BRUNO)
        self.assertEqual(msg["Subject"], "Fwd: Devis révisé")
        self.assertEqual(msg["Auto-Submitted"], "auto-generated")
        self.assertEqual(msg["X-Auto-Response-Suppress"], "All")
        self.assertEqual(
            msg.get_all("X-Loop"),
            ["liste-annonces@example.net", f"erplibre-rules {OWN}"],
        )
        self.assertIsNone(msg["In-Reply-To"])
        self.assertIsNone(msg["References"])

    def test_inner_message_has_no_bcc(self):
        raw = simple(
            b"Bcc: temoin.cci@example.com\r\n"
            b"Resent-Bcc: temoin.cci@example.com\r\n"
            b"X-ERPLibre-Bcc: temoin.cci@example.com\r\n"
        )
        msg = self.attached(raw)
        self.assertNotIn(TEMOIN.encode(), msg.as_bytes())
        self.assertNotIn(TEMOIN, recipients(msg))

    def test_a_bcc_after_a_bare_cr_is_removed_from_the_inner_message(self):
        raw = (
            b"From: bruno.filtre@example.net\r\n"
            b"Subject: Question\rBcc: temoin.cci@example.com\r\n"
            b"X-Divers: a\rX-ERPLibre-Bcc: temoin.cci@example.com\r\n"
            b"\r\nBonjour.\r\n"
        )
        msg = self.attached(raw)
        self.assertNotIn(TEMOIN.encode(), msg.as_bytes())
        jointe = list(relu(msg).iter_attachments())[0].get_content()
        self.assertIsNone(jointe["Bcc"])
        self.assertIsNone(jointe["X-ERPLibre-Bcc"])
        self.assertEqual(jointe["Subject"], "Question")

    def test_targets_do_not_see_each_other(self):
        msg = self.attached()
        visible = entete(without_bcc(msg).as_bytes())
        for cible in (CAROLE, DENIS):
            self.assertNotIn(cible.encode(), visible)
        self.assertEqual(recipients(msg), [CAROLE, DENIS])


class TestRedirect(ForwardCase):
    def bloc(self, sortie: RawOutgoing) -> list[bytes]:
        lignes = sortie.raw.split(b"\r\n")
        return lignes[:3]

    def test_original_bytes_follow_one_resent_block(self):
        sortie = self.redirect()
        attendu = to_crlf(
            strip_header_fields(ORIGINAL, REDIRECT_DROPPED_FIELDS)
        )
        self.assertTrue(sortie.raw.endswith(attendu))
        prefixe = sortie.raw[: -len(attendu)]
        self.assertEqual(prefixe.count(b"\r\n"), 3)
        self.assertTrue(prefixe.startswith(b"Resent-From: "))

    def test_resent_block_fields_and_order(self):
        noms = [
            ligne.split(b":", 1)[0] for ligne in self.bloc(self.redirect())
        ]
        self.assertEqual(
            noms, [b"Resent-From", b"Resent-Date", b"Resent-Message-ID"]
        )
        lignes = self.bloc(self.redirect())
        self.assertEqual(lignes[0], f"Resent-From: {OWN}".encode())
        self.assertEqual(lignes[1], f"Resent-Date: {DATE}".encode())
        self.assertEqual(
            lignes[2], b"Resent-Message-ID: <resent-1@example.org>"
        )
        self.assertNotIn(b"Resent-To", self.redirect().raw)

    def test_only_bcc_resent_bcc_and_return_path_are_removed(self):
        raw = ORIGINAL.replace(
            b"X-Loop:", b"Resent-Bcc: temoin.cci@example.com\r\nX-Loop:"
        )
        avant = email.message_from_bytes(raw).keys()
        apres = email.message_from_bytes(self.redirect(raw).raw).keys()
        retires = [n for n in avant if n not in apres]
        self.assertEqual(
            sorted(n.lower() for n in retires),
            ["bcc", "resent-bcc", "return-path"],
        )
        self.assertEqual(
            [n for n in apres if not n.startswith("Resent-")],
            [n for n in avant if n not in retires],
        )

    def test_a_planted_erplibre_bcc_header_is_stripped_from_a_redirect(self):
        raw = simple(b"X-ERPLibre-Bcc: temoin.cci@example.com\r\n")
        sortie = self.redirect(raw)
        self.assertNotIn(TEMOIN.encode(), sortie.raw)
        self.assertNotIn(b"X-ERPLibre-Bcc", sortie.raw)
        self.assertEqual(sortie.envelope, (CAROLE, DENIS))

    def test_an_existing_resent_block_stays_below_ours(self):
        raw = (
            b"Resent-From: relais.auto@example.com\r\n"
            b"Resent-Date: Tue, 27 Oct 2026 08:00:00 +0000\r\n"
            b"Resent-Message-ID: <ancien@example.com>\r\n" + simple(b"")
        )
        sortie = email.message_from_bytes(self.redirect(raw).raw)
        self.assertEqual(sortie.get_all("Resent-From"), [OWN, RELAIS])
        self.assertEqual(
            sortie.get_all("Resent-Message-ID"),
            ["<resent-1@example.org>", "<ancien@example.com>"],
        )

    def test_line_endings_are_normalised_to_crlf(self):
        raw = ORIGINAL.replace(b"\r\n", b"\n")
        sortie = self.redirect(raw).raw
        self.assertNotIn(b"\n", sortie.replace(b"\r\n", b""))
        self.assertNotIn(b"\r", sortie.replace(b"\r\n", b""))
        self.assertTrue(sortie.startswith(b"Resent-From: "))
        self.assertIn(b"Resent-Message-ID: <resent-1@example.org>\r\n", sortie)

    def test_a_bcc_after_a_bare_cr_is_removed(self):
        raw = (
            b"From: bruno.filtre@example.net\r\n"
            b"Subject: Question\rBcc: temoin.cci@example.com\r\n"
            b"X-Divers: a\rX-ERPLibre-Bcc: temoin.cci@example.com\r\n"
            b"\r\nBonjour.\r\n"
        )
        sortie = self.redirect(raw).raw
        self.assertNotIn(TEMOIN.encode(), sortie)
        self.assertNotIn(b"Bcc", sortie)
        self.assertIn(b"\r\nSubject: Question\r\n", sortie)
        self.assertIn(b"\r\nX-Divers: a\r\n", sortie)

    def test_a_cr_only_original_keeps_its_headers_and_body(self):
        raw = (
            b"Return-Path: <bruno.filtre@example.net>\r"
            b"From: bruno.filtre@example.net\r"
            b"Bcc: temoin.cci@example.com\r"
            b"Subject: s\r\rcorps\r"
        )
        sortie = self.redirect(raw).raw
        self.assertNotIn(b"Return-Path", sortie)
        self.assertNotIn(TEMOIN.encode(), sortie)
        self.assertTrue(
            sortie.endswith(
                b"From: bruno.filtre@example.net\r\n"
                b"Subject: s\r\n\r\ncorps\r\n"
            )
        )
        relu_ = email.message_from_bytes(sortie)
        self.assertEqual(relu_["Subject"], "s")
        self.assertEqual(relu_.get_payload(), "corps\r\n")

    def test_bare_cr_dot_cannot_end_the_data(self):
        raw = simple(b"", b"ligne\r.\rsuite\rfin\r\n.\r\n")
        sortie = self.redirect(raw).raw
        self.assertNotIn(b"\r.\r", sortie.replace(b"\r\n", b"\n"))
        self.assertNotIn(b"\r", sortie.replace(b"\r\n", b""))
        client = FauxClient()
        SmtplibTransport(client).send_raw(raw, OWN, [CAROLE])
        envoye = client.sendmail_calls[0][2]
        self.assertNotIn(b"\r", envoye.replace(b"\r\n", b""))
        self.assertNotIn(b"\n", envoye.replace(b"\r\n", b""))

    def test_envelope_is_exact_and_deduplicated(self):
        sortie = self.redirect(
            to=(CAROLE, "carole.regle@EXAMPLE.org", DENIS, IDN_UNICODE)
        )
        self.assertEqual(sortie.envelope, (CAROLE, DENIS, IDN_ACE))

    def test_empty_targets_are_refused(self):
        with self.assertRaises(SmtpError):
            self.redirect(to=())
        with self.assertRaises(SmtpError):
            self.redirect(to=("pas une adresse",))

    def test_unreadable_raw_is_refused(self):
        for raw in (b"", b"\r\n\r\nseulement un corps\r\n", b"pas d'en-tete"):
            with self.subTest(raw=raw):
                with self.assertRaises(SmtpError) as ctx:
                    self.redirect(raw)
                self.assertIn(
                    t("mail_rules_err_fwd_unreadable"), str(ctx.exception)
                )

    def test_subject_is_decoded(self):
        sortie = self.redirect()
        self.assertEqual(sortie.subject, "Devis révisé")
        self.assertIn(
            b"Subject: =?utf-8?q?Devis_r=C3=A9vis=C3=A9?=", sortie.raw
        )

    def test_no_x_loop_nor_auto_submitted_is_added(self):
        sortie = email.message_from_bytes(self.redirect().raw)
        self.assertEqual(
            sortie.get_all("X-Loop"), ["liste-annonces@example.net"]
        )
        self.assertIsNone(sortie["Auto-Submitted"])
        self.assertEqual(self.redirect().as_bytes(), self.redirect().raw)


class FauxClient:
    """Un client `smtplib` qui enregistre ce qu'on lui demande."""

    def __init__(self, extensions=("8bitmime",)):
        self.extensions = set(extensions)
        self.sendmail_calls = []
        self.ehlo_calls = 0

    def ehlo_or_helo_if_needed(self):
        self.ehlo_calls += 1

    def has_extn(self, nom):
        return nom.lower() in self.extensions

    def sendmail(self, from_addr, to_addrs, msg, mail_options=()):
        self.sendmail_calls.append(
            (from_addr, list(to_addrs), msg, list(mail_options))
        )
        return {}


class FauxTransport:
    """Un transport SMTP qui enregistre ses deux chemins d'envoi."""

    def __init__(self, erreur=None):
        self.raw_calls = []
        self.message_calls = []
        self.erreur = erreur

    def send_raw(self, raw, from_addr, to_addrs):
        if self.erreur is not None:
            raise self.erreur
        self.raw_calls.append((raw, from_addr, list(to_addrs)))

    def send_message(self, msg, from_addr, to_addrs):
        self.message_calls.append((msg, from_addr, list(to_addrs)))

    def quit(self):
        pass


class TestSendRaw(ForwardCase):
    def test_send_uses_the_explicit_envelope_never_the_headers(self):
        raw = simple(
            b"Cc: temoin.cci@example.com\r\nBcc: temoin.cci@example.com\r\n"
        ).replace(
            b"To: boite.regles@example.org", b"To: temoin.cci@example.com"
        )
        transport = FauxTransport()
        servis = send(
            self.account, self.redirect(raw, to=(CAROLE,)), transport
        )
        self.assertEqual(servis, [CAROLE])
        self.assertEqual(transport.message_calls, [])
        octets, expediteur, rcpt = transport.raw_calls[0]
        self.assertEqual((expediteur, rcpt), (OWN, [CAROLE]))
        self.assertTrue(octets.startswith(b"Resent-From: "))

    def test_send_refuses_an_empty_envelope(self):
        with self.assertRaises(SmtpError):
            send(self.account, RawOutgoing(b"x", ()), FauxTransport())

    def test_send_raw_passes_8bitmime_when_needed_and_offered(self):
        client = FauxClient()
        SmtplibTransport(client).send_raw(ORIGINAL, OWN, [CAROLE, DENIS])
        expediteur, rcpt, octets, options = client.sendmail_calls[0]
        self.assertEqual((expediteur, rcpt), (OWN, [CAROLE, DENIS]))
        self.assertEqual(octets, ORIGINAL)
        self.assertEqual(options, ["BODY=8BITMIME"])

    def test_send_raw_without_8bit_bytes_has_no_option(self):
        client = FauxClient()
        SmtplibTransport(client).send_raw(simple(b""), OWN, [CAROLE])
        self.assertEqual(client.sendmail_calls[0][3], [])

    def test_send_raw_never_asks_8bitmime_from_a_server_without_it(self):
        client = FauxClient(extensions=())
        SmtplibTransport(client).send_raw(ORIGINAL, OWN, [CAROLE])
        self.assertEqual(client.sendmail_calls[0][3], [])
        self.assertEqual(client.ehlo_calls, 1)

    def test_email_messages_still_go_through_send_message(self):
        msg = build_message(
            self.account, CAROLE, "Devis", "Bonjour", bcc=[DENIS]
        )
        transport = FauxTransport()
        self.assertEqual(send(self.account, msg, transport), [CAROLE, DENIS])
        self.assertEqual(transport.raw_calls, [])
        envoye, _de, rcpt = transport.message_calls[0]
        self.assertEqual(rcpt, [CAROLE, DENIS])
        self.assertIsNone(envoye["X-ERPLibre-Bcc"])

    def test_a_refusal_carries_the_smtp_code(self):
        refus = smtplib.SMTPRecipientsRefused({CAROLE: (550, b"inconnu")})
        with self.assertRaises(SmtpError) as ctx:
            send(self.account, self.redirect(), FauxTransport(refus))
        self.assertEqual(ctx.exception.code, 550)
        self.assertTrue(ctx.exception.permanent)

    def test_two_resent_blocks_are_sent_without_error(self):
        raw = (
            b"Resent-From: relais.auto@example.com\r\n"
            b"Resent-Date: Tue, 27 Oct 2026 08:00:00 +0000\r\n" + simple(b"")
        )
        sortie = self.redirect(raw, to=(CAROLE,))
        client = FauxClient()
        send(self.account, sortie, SmtplibTransport(client))
        self.assertEqual(client.sendmail_calls[0][2], sortie.raw)
        # Le chemin `send_message` refuserait ce message.
        relu_msg = email.message_from_bytes(
            sortie.raw, policy=email.policy.default
        )
        with mock.patch.object(smtplib.SMTP, "ehlo_or_helo_if_needed"):
            with self.assertRaises(ValueError):
                smtplib.SMTP().send_message(relu_msg)


if __name__ == "__main__":
    unittest.main()
