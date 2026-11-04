#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Refus partiel des destinataires, côté transport.

Ce que ces tests figent : `send()` rend les refusés d'un départ avec leur
code, sous l'orthographe de l'enveloppe, sans changer ce qu'en lit un
appelant qui ne connaît que la liste des servis ; un refus de chaque
destinataire n'est jamais un succès ; `split_refusals` ne réessaie qu'un
4xx qu'une enveloppe peut porter, et ne garde rien du texte qui nomme une
adresse refusée ; `outgoing_bytes` rend des octets qu'une enveloppe
explicite peut remettre sans montrer le Cci interne.
"""

import email
import email.policy
import smtplib
import unittest

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import (
    RawOutgoing,
    Refusals,
    Served,
    SmtpError,
    SmtplibTransport,
    build_forward_inline,
    build_message,
    build_redirect,
    outgoing_bytes,
    send,
    split_refusals,
)

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
TEMP = "refus.temporaire@example.net"
DEF = "refus.definitif@example.net"
DATE = "Wed, 28 Oct 2026 10:00:00 +0000"

ORIGINAL = (
    b"From: Denis Tri <denis.tri@example.org>\r\n"
    b"To: boite.regles@example.org\r\n"
    b"Subject: Devis\r\n"
    b"Date: Wed, 28 Oct 2026 09:00:00 +0000\r\n"
    b"Message-ID: <orig-partiel@example.org>\r\n"
    b"\r\n"
    b"Bonjour.\r\n"
)


class FauxClient:
    """Un client `smtplib` dont les deux chemins rendent `refus`, ou lèvent
    `erreur`."""

    def __init__(self, refus=None, erreur=None):
        self.refus = refus or {}
        self.erreur = erreur
        self.appels = []

    def ehlo_or_helo_if_needed(self):
        pass

    def has_extn(self, nom):
        return False

    def sendmail(self, from_addr, to_addrs, msg, mail_options=()):
        self.appels.append(("raw", list(to_addrs)))
        if self.erreur is not None:
            raise self.erreur
        return dict(self.refus)

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.appels.append(("message", list(to_addrs)))
        if self.erreur is not None:
            raise self.erreur
        return dict(self.refus)


class PartialCase(unittest.TestCase):
    def setUp(self):
        self.account = account_from_preset("perso", OWN, "generic")

    def redirect(self, to=(CAROLE, TEMP, DEF)):
        return build_redirect(
            self.account,
            ORIGINAL,
            list(to),
            date=DATE,
            msgid="<resent-partiel@example.org>",
        )

    def forward(self, to=(CAROLE, TEMP, DEF)):
        return build_forward_inline(
            self.account,
            ORIGINAL,
            list(to),
            date=DATE,
            msgid="<transfert-partiel@example.org>",
        )


class TestServed(PartialCase):
    def test_send_returns_the_refusals_with_their_codes_on_both_paths(self):
        refus = {TEMP: (450, b"plus tard"), DEF: (550, b"inconnu")}
        for sortie in (self.redirect(), self.forward()):
            with self.subTest(type=type(sortie).__name__):
                client = FauxClient(refus)
                servis = send(self.account, sortie, SmtplibTransport(client))
                self.assertIsInstance(servis, Served)
                self.assertEqual(list(servis), [CAROLE])
                self.assertEqual(servis.refused, {TEMP: 450, DEF: 550})
                self.assertEqual(servis.envelope, (CAROLE, TEMP, DEF))

    def test_refused_keys_follow_the_envelope_spelling_whatever_the_case(self):
        client = FauxClient({TEMP.upper(): (451, b"plus tard")})
        servis = send(
            self.account,
            self.redirect((CAROLE, TEMP)),
            SmtplibTransport(client),
        )
        self.assertEqual(servis.refused, {TEMP: 451})
        self.assertEqual(list(servis), [CAROLE])

    def test_a_key_outside_the_envelope_is_ignored(self):
        client = FauxClient({DENIS: (550, b"inconnu")})
        servis = send(
            self.account,
            self.redirect((CAROLE, TEMP)),
            SmtplibTransport(client),
        )
        self.assertEqual(servis.refused, {})
        self.assertEqual(list(servis), [CAROLE, TEMP])

    def test_a_full_success_has_no_refusal(self):
        servis = send(
            self.account, self.redirect(), SmtplibTransport(FauxClient())
        )
        self.assertEqual(servis.refused, {})
        self.assertEqual(list(servis), [CAROLE, TEMP, DEF])

    def test_a_dict_refusing_every_recipient_raises_with_the_lowest_code(self):
        client = FauxClient(
            {CAROLE: (552, b"plein"), TEMP: (450, b"x"), DEF: (550, b"y")}
        )
        with self.assertRaises(SmtpError) as ctx:
            send(self.account, self.redirect(), SmtplibTransport(client))
        self.assertEqual(ctx.exception.code, 450)
        self.assertFalse(ctx.exception.permanent)
        self.assertEqual(
            ctx.exception.refused, {CAROLE: 552, TEMP: 450, DEF: 550}
        )

    def test_an_unknown_code_never_becomes_the_exception_code(self):
        client = FauxClient({TEMP: ("?", b"x"), DEF: (550, b"y")})
        with self.assertRaises(SmtpError) as ctx:
            send(
                self.account,
                self.redirect((TEMP, DEF)),
                SmtplibTransport(client),
            )
        self.assertEqual(ctx.exception.code, 550)
        self.assertTrue(ctx.exception.permanent)
        self.assertEqual(ctx.exception.refused, {TEMP: 0, DEF: 550})
        client = FauxClient({TEMP: (None, b"x")})
        with self.assertRaises(SmtpError) as ctx:
            send(
                self.account, self.redirect((TEMP,)), SmtplibTransport(client)
            )
        self.assertIsNone(ctx.exception.code)

    def test_a_wholly_refused_send_carries_its_refusals(self):
        erreur = smtplib.SMTPRecipientsRefused(
            {TEMP: (450, b"plus tard"), DEF.upper(): (550, b"inconnu")}
        )
        for sortie in (self.redirect((TEMP, DEF)), self.forward((TEMP, DEF))):
            with self.subTest(type=type(sortie).__name__):
                client = FauxClient(erreur=erreur)
                with self.assertRaises(SmtpError) as ctx:
                    send(self.account, sortie, SmtplibTransport(client))
                self.assertEqual(ctx.exception.refused, {TEMP: 450, DEF: 550})
                self.assertEqual(ctx.exception.code, 450)

    def test_another_failure_carries_no_refusal(self):
        client = FauxClient(erreur=smtplib.SMTPDataError(554, b"rejet"))
        with self.assertRaises(SmtpError) as ctx:
            send(self.account, self.redirect(), SmtplibTransport(client))
        self.assertEqual(ctx.exception.refused, {})

    def test_served_still_equals_the_list_of_served(self):
        servis = Served([CAROLE], envelope=(CAROLE, TEMP), refused={TEMP: 450})
        self.assertEqual(servis, [CAROLE])
        self.assertEqual(Served(), [])
        self.assertEqual(Served().refused, {})
        self.assertEqual(Served().envelope, ())


class TestSplitRefusals(unittest.TestCase):
    def test_4xx_go_to_retry_in_envelope_order(self):
        autre = DENIS
        part = split_refusals((CAROLE, autre, TEMP), {TEMP: 450, autre: 421})
        self.assertEqual(part.retry, (autre, TEMP))
        self.assertEqual(part.retry_codes, (421, 450))
        self.assertEqual(part.dropped_codes, ())
        self.assertEqual(part.count, 2)

    def test_5xx_and_unknown_codes_are_dropped(self):
        part = split_refusals(
            (CAROLE, TEMP, DEF), {TEMP: 0, DEF: 550, CAROLE: "x"}
        )
        self.assertEqual(part.retry, ())
        self.assertEqual(part.dropped_codes, (0, 0, 550))
        self.assertEqual(part.count, 3)

    def test_a_4xx_address_no_envelope_can_carry_is_dropped(self):
        illisible = '"refus temporaire"@example.net'
        part = split_refusals((CAROLE, illisible, TEMP), {illisible: 450})
        self.assertEqual(part, Refusals(dropped_codes=(450,)))
        self.assertNotIn("refus temporaire", repr(part))

    def test_keys_match_the_envelope_whatever_the_case(self):
        part = split_refusals((CAROLE, TEMP), {TEMP.upper(): 452})
        self.assertEqual(part.retry, (TEMP,))
        part = split_refusals((CAROLE,), {TEMP: 452})
        self.assertEqual(part, Refusals())

    def test_codes_are_sorted(self):
        autre = DENIS
        part = split_refusals(
            (DEF, autre, TEMP, CAROLE),
            {DEF: 554, autre: 452, TEMP: 421, CAROLE: 550},
        )
        self.assertEqual(part.retry_codes, (421, 452))
        self.assertEqual(part.retry, (autre, TEMP))
        self.assertEqual(part.dropped_codes, (550, 554))


class TestOutgoingBytes(PartialCase):
    def test_a_redirect_keeps_its_bytes_and_its_single_resent_block(self):
        sortie = self.redirect()
        octets = outgoing_bytes(sortie)
        self.assertEqual(octets, sortie.raw)
        self.assertEqual(octets.count(b"Resent-From:"), 1)

    def test_a_forward_loses_the_internal_bcc_and_keeps_its_message_id(self):
        sortie = self.forward()
        self.assertIsNotNone(sortie["X-ERPLibre-Bcc"])
        relu = email.message_from_bytes(
            outgoing_bytes(sortie), policy=email.policy.default
        )
        self.assertIsNone(relu["X-ERPLibre-Bcc"])
        self.assertEqual(relu["Message-ID"], sortie["Message-ID"])
        self.assertEqual(relu["Subject"], sortie["Subject"])
        self.assertEqual(relu["To"], sortie["To"])
        self.assertEqual(relu["From"], sortie["From"])
        self.assertIsNotNone(sortie["X-ERPLibre-Bcc"])

    def test_line_endings_are_crlf(self):
        msg = build_message(self.account, CAROLE, "Devis", "un\ndeux\n")
        octets = outgoing_bytes(msg)
        self.assertNotIn(b"\n", octets.replace(b"\r\n", b""))
        self.assertNotIn(b"\r", octets.replace(b"\r\n", b""))

    def test_raw_outgoing_bytes_are_returned_as_they_are(self):
        sortie = RawOutgoing(b"Subject: x\n\ncorps\n", (CAROLE,))
        self.assertEqual(outgoing_bytes(sortie), b"Subject: x\n\ncorps\n")


if __name__ == "__main__":
    unittest.main()
