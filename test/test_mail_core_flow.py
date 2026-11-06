#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un parcours complet du noyau, sans le client : en-têtes IMAP lus,
règle évaluée, garde-fous, réponse rendue puis construite, rapport de
statistiques dans un fuseau explicite.

C'est le chemin qu'emprunte un appelant qui n'est pas le client courriel.
N'importe que la bibliothèque standard et `erplibre_mail_core`.
"""

import imaplib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core import i18n, imap, smtp  # noqa: E402
from erplibre_mail_core.rules import (  # noqa: E402
    filter as rules_filter,
)
from erplibre_mail_core.rules import guards, markup, model, report  # noqa: E402

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
BRUNO = "bruno.filtre@example.net"
UIDV = 42
NOW = 1_794_000_000


class Compte:
    """Le compte que lisent les constructeurs SMTP, par duck typing."""

    email = OWN

    def from_header(self) -> str:
        return f"Boîte <{OWN}>"


def reponse_fetch(uid: int, entetes: str) -> list:
    """Une réponse FETCH d'en-têtes telle qu'`imaplib` la rend."""
    date = imaplib.Time2Internaldate(NOW - 60).encode()
    return [
        (
            f"1 (UID {uid} FLAGS () RFC822.SIZE 900 INTERNALDATE ".encode()
            + date
            + b" BODY[HEADER.FIELDS (FROM)] {300}",
            entetes.encode(),
        ),
        b")",
    ]


def entetes(**plus) -> str:
    lignes = [
        f"From: Carole <{CAROLE}>",
        f"To: {OWN}",
        "Subject: Demande de devis",
        "Message-ID: <demande1@example.org>",
        "Date: Fri, 06 Nov 2026 10:00:00 -0500",
    ]
    lignes += [f"{nom.replace('_', '-')}: {v}" for nom, v in plus.items()]
    return "\r\n".join(lignes) + "\r\n\r\n"


def vue(uid: int = 10, **plus) -> model.MessageView:
    (entete,) = imap.parse_fetch_headers(reponse_fetch(uid, entetes(**plus)))
    return model.message_view(entete, UIDV)


def regle(kind: str = "reply") -> model.Rule:
    r = model.new_rule(kind, "Accueil")
    r.filter = model.Group(
        "all", [model.Condition("from", "carole", "contains")]
    )
    r.armed = model.Armed(uidvalidity=UIDV, uidnext=1, at=NOW - 3600)
    r.action.subject = "Re: {subject}"
    if kind == "reply":
        r.action.body = "Bonjour, **merci** pour votre message."
    return r


def contexte() -> guards.GuardContext:
    return guards.GuardContext(
        now=NOW,
        own_addresses=frozenset({OWN}),
        other_account_addresses=frozenset({BRUNO}),
        is_logged=lambda: False,
        last_send_at=lambda expediteur, cible: None,
    )


class BaseFactice:
    """La base que lit le rapport : messages reçus pendant trente jours,
    de Carole et de Denis tour à tour."""

    def __init__(self):
        self.rows = []
        for i in range(0, 30 * 24, 5):
            recu = NOW - 30 * 86400 + i * 3600
            self.rows.append(
                SimpleNamespace(
                    received_at=recu,
                    seen=i % 2 == 0,
                    answered=i % 3 == 0,
                    first_reply_at=recu + 7200 if i % 3 == 0 else None,
                    sender=CAROLE if i % 2 else DENIS,
                )
            )

    def stats_activity(self, since, until, with_sender=False):
        return [r for r in self.rows if since <= r.received_at < until]


class TestFlow(unittest.TestCase):
    def setUp(self):
        precedent = i18n.configure(default_lang="fr", translator=None)
        self.addCleanup(lambda: i18n.configure(**precedent))

    def test_a_reply_goes_from_headers_to_a_built_message(self):
        message = vue()
        r = regle()
        self.assertTrue(rules_filter.evaluate(r.filter, message, None))
        decision = guards.decide(r, message, contexte(), None)
        self.assertEqual(decision.reason, guards.SEND)
        self.assertEqual(decision.target, CAROLE)
        rendu = markup.render_reply(r.action, {}, "example.org")
        self.assertIn("merci", rendu.text)
        self.assertIn("<strong>merci</strong>", rendu.html)
        sortant = smtp.build_auto_reply(
            Compte(),
            decision.target_addr,
            smtp.auto_reply_subject(message.subject, r.action.subject),
            rendu.text,
            in_reply_to=message.msgid,
            html=rendu.html,
        )
        self.assertEqual(sortant["In-Reply-To"], "<demande1@example.org>")
        self.assertEqual(sortant["Auto-Submitted"], "auto-replied")
        self.assertEqual(smtp.recipients(sortant), [CAROLE])
        self.assertIn(OWN, sortant["X-Loop"])

    def test_an_automatic_message_is_set_aside(self):
        message = vue(Auto_Submitted="auto-replied")
        decision = guards.decide(regle(), message, contexte(), None)
        self.assertEqual(decision.reason, "auto_submitted")

    def test_a_stats_reply_is_rendered_in_an_explicit_zone(self):
        reglages = SimpleNamespace(
            days=7, weeks=2, delay_window_days=7, lang="fr"
        )
        r = model.new_rule("stats", "Rapport")
        r.action.subject = "Statistiques : {{recus_total}} reçus"
        donnees = report.build_data(
            BaseFactice(),
            reglages,
            now=NOW,
            sender=CAROLE,
            tz=ZoneInfo("America/Toronto"),
        )
        rendu = report.render_stats_reply(r.action, {}, "example.org", donnees)
        sujet = report.render_subject("Demande", r.action.subject, donnees)
        self.assertTrue(rendu.text.strip())
        self.assertTrue(rendu.html.strip())
        self.assertIn("-0500", report.values(donnees)["date_rapport"][0])
        self.assertTrue(sujet.startswith("Statistiques : "))
        for adresse in (CAROLE, DENIS, "@"):
            self.assertNotIn(adresse, rendu.text)
            self.assertNotIn(adresse, rendu.html)


if __name__ == "__main__":
    unittest.main()
