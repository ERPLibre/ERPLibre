#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un certificat refusé pendant un envoi automatique du moteur des règles.

Le refus est transitoire par sa classe : la réponse part en file
(`smtp_transient`), jamais en échec définitif, et le premier refus de la
passe reste dans `EngineReport.tls_error` pour que l'appelant le signale.
"""

import unittest

from test_mail_rules_engine import EngineCase

from script.todo.mail.rules import engine
from script.todo.mail.smtp_send import tls

FP_A = "ab" * 32


def refus(fingerprint=FP_A):
    return tls.TlsCertificateError(
        protocol="smtp",
        host="serveur.example.org",
        port=587,
        reason="untrusted",
        fingerprint=fingerprint,
    )


class TestEngineTls(EngineCase):
    def test_a_refused_reply_is_queued_as_transient(self):
        rule = self.regle()
        self.imap.recevoir(1)

        def refuse(session, msg, verrou=None, **_kw):
            raise refus()

        bilan = self.passe(deliver_fn=refuse)
        self.assertEqual((bilan.queued, bilan.failed), (1, 0))
        entree = self.store.rule_log_entries(rule.id)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("queued", "smtp_transient")
        )

    def test_the_report_keeps_the_first_tls_refusal(self):
        self.regle()
        self.imap.recevoir(1)
        self.imap.recevoir(2, frm="bruno.filtre@example.net")
        refus_vus = [refus(), refus("cd" * 32)]
        lances = []

        def refuse(session, msg, verrou=None, **_kw):
            exc = refus_vus[len(lances) % 2]
            lances.append(exc)
            raise exc

        bilan = self.passe(deliver_fn=refuse)
        self.assertTrue(lances)
        self.assertIs(bilan.tls_error, lances[0])

    def test_a_pass_without_refusal_has_no_tls_error(self):
        self.regle()
        self.imap.recevoir(1)
        self.assertIsNone(self.passe().tls_error)

    def test_smtp_failure_is_permanent_is_false_for_a_tls_refusal(self):
        exc = refus()
        exc.args = ("550 " + str(exc),)
        self.assertTrue(str(exc).startswith("550"))
        self.assertFalse(engine.smtp_failure_is_permanent(exc))

    def test_a_trial_lets_the_tls_refusal_through(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.session.sync()
        header = self.imap.folders["INBOX"]["messages"][1]
        sim = engine.simulate(
            self.session,
            rule,
            header,
            uidvalidity=1,
            body_loader=lambda: "Bonjour, une question.",
            all_accounts=[],
            now=self.horloge,
        )
        exc = refus()

        def refuse(session, msg, verrou=None, **_kw):
            raise exc

        with self.assertRaises(tls.TlsCertificateError) as ctx:
            engine.send_trial(self.session, rule, sim, deliver_fn=refuse)
        self.assertIs(ctx.exception, exc)


if __name__ == "__main__":
    unittest.main()
