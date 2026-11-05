#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Deux machines, une boîte : relâcher une réponse retenue, libérer à la
main une revendication incertaine ou en échec.

Chaque machine a sa base et sa connexion au MÊME bac à sable IMAP ; le
SMTP est commun. Les tests de retenue prennent deux machines dont la règle
n'est pas approuvée ; ceux de la libération à la main, deux machines
approuvées (une règle non approuvée retiendrait de nouveau le message
réévalué). Les mêmes tests tournent avec et sans CONDSTORE ; seul
l'entrelacement de deux relâchements simultanés diffère.
"""

import unittest
from unittest import mock

from test_mail_rules_claim_sandbox import (
    KEYWORD,
    RECU,
    SANDBOX_MISSING,
    Machine,
    TwoMachinesCase,
)

DEMAIN = RECU + 600 + 25 * 3600


def relacher(machine, *, force=None, now=None):
    from script.todo.mail.rules import release

    entree = next(e for e in machine.store.outbox() if e["held"])
    return release.release_held(
        machine.session,
        entree["id"],
        rules_base=machine.base,
        force=force,
        now=now or (lambda: RECU + 700),
    )


def liberer(machine, rule, uid=1):
    from script.todo.mail.rules import release

    cle = machine.store.message_key(f"<{uid}@example.net>", 42, uid)
    return release.release_claim(
        machine.store, "perso", rule.id, cle, rules_base=machine.base
    )


class ReleaseOnTwoMachines:
    """Les tests communs aux deux serveurs, avec et sans CONDSTORE."""

    def retenues(self):
        a = Machine(self, self.rule, approuvee=False)
        b = Machine(self, self.rule, approuvee=False)
        self.assertEqual(a.passe().held, 1)
        self.assertEqual(b.passe().held, 1)
        self.assertNotIn(KEYWORD, self.drapeaux())
        return a, b

    def test_both_machines_hold_and_only_the_first_release_sends(self):
        a, b = self.retenues()
        self.assertEqual(relacher(a).status, "released")
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertIn(KEYWORD, self.drapeaux())
        res = relacher(b)
        self.assertEqual(res.status, "dropped")
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(b.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(b.store.outbox(), [])

    def test_releasing_on_the_second_machine_first_also_sends_once(self):
        a, b = self.retenues()
        self.assertEqual(relacher(b).status, "released")
        self.assertEqual(relacher(a).status, "dropped")
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(a.ligne(self.rule), ("skipped", "claimed_elsewhere"))

    def test_a_release_after_the_other_machine_answered_is_dropped(self):
        a = Machine(self, self.rule, approuvee=False)
        b = Machine(self, self.rule)
        self.assertEqual(a.passe().held, 1)
        self.assertEqual(b.passe().sent, 1)
        self.assertEqual(relacher(a).status, "dropped")
        self.assertEqual(len(self.smtp.messages), 1)

    def test_a_manually_released_uncertain_message_leaves_once(self):
        a, b = self.machines()
        a.store.rule_claim_intent(42, 1)
        self.inbox.marquer_ailleurs(1, KEYWORD)
        self.assertEqual(a.passe().sent, 0)
        self.assertEqual(a.ligne(self.rule), ("skipped", "claim_uncertain"))
        self.assertEqual(b.passe().sent, 0)
        self.assertEqual(b.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        ok, _texte = liberer(a, self.rule)
        self.assertTrue(ok)
        self.assertEqual(a.passe().sent, 1)
        self.assertEqual(a.ligne(self.rule), ("sent", None))
        self.assertEqual(a.store.rule_claim_state(42, 1), "owned")
        a.passe()
        b.passe()
        self.assertEqual(len(self.smtp.messages), 1)

    def echec_sur(self, machine):
        """`failed/claim_failed` sur `machine` : sa sonde est refusée à
        chaque passe, sans reprise du lien."""
        from script.todo.mail.imap_transport import ImapError
        from script.todo.mail.rules import engine

        transport = machine.session.syncer.transport
        with mock.patch.object(
            transport, "claim_probe", side_effect=ImapError("PROBE NO")
        ):
            for _ in range(engine.CLAIM_PASSES_MAX):
                self.assertEqual(machine.passe().sent, 0)
        self.assertEqual(machine.ligne(self.rule), ("failed", "claim_failed"))
        self.assertEqual(self.smtp.messages, [])

    def test_a_manually_released_failed_claim_leaves_once(self):
        a, b = self.machines()
        self.echec_sur(a)
        ok, _texte = liberer(a, self.rule)
        self.assertTrue(ok)
        self.assertEqual(a.passe().sent, 1)
        self.assertEqual(a.ligne(self.rule), ("sent", None))
        self.assertIn(KEYWORD, self.drapeaux())
        self.assertEqual(b.passe().sent, 0)
        self.assertEqual(b.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(len(self.smtp.messages), 1)

    def test_a_failed_claim_released_after_the_other_machine_answered(self):
        a, b = self.machines()
        self.echec_sur(a)
        self.assertEqual(b.passe().sent, 1)
        self.assertTrue(liberer(a, self.rule)[0])
        self.assertEqual(a.passe().sent, 0)
        self.assertEqual(a.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(len(self.smtp.messages), 1)

    def test_an_expired_held_entry_on_one_machine_does_not_stop_the_other(
        self,
    ):
        a, b = self.retenues()
        self.assertEqual(relacher(a, now=lambda: DEMAIN).status, "dropped")
        self.assertNotIn(KEYWORD, self.drapeaux())
        self.assertEqual(relacher(b).status, "released")
        self.assertEqual(len(self.smtp.messages), 1)

    def test_a_message_filed_away_is_sent_by_each_machine_that_confirms(self):
        """La limite que dit la question : rangé hors de la boîte de
        réception, le message ne se revendique plus, et chaque machine qui
        confirme l'envoie."""
        a, b = self.retenues()
        self.inbox.expurger(1)
        for machine in (a, b):
            machine.session.sync()
            res = relacher(machine)
            self.assertEqual((res.status, res.verdict), ("confirm", "gone"))
            self.assertEqual(
                relacher(machine, force="gone").status, "released"
            )
        self.assertEqual(len(self.smtp.messages), 2)

    def entrelacer(self):
        """A sonde ; avant son STORE, B relâche en entier ; puis A
        poursuit. Rend l'issue de A."""
        a, b = self.retenues()
        transport = a.session.syncer.transport
        vrai = transport.claim_store
        fait = []

        def croise(uid, probe):
            if not fait:
                fait.append(relacher(b))
            return vrai(uid, probe)

        with mock.patch.object(transport, "claim_store", croise):
            res = relacher(a)
        self.assertEqual(fait[0].status, "released")
        return res


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestReleaseWithCondstore(ReleaseOnTwoMachines, TwoMachinesCase):
    SANDBOX = {"condstore": True}

    def test_two_releases_racing_send_once(self):
        res = self.entrelacer()
        self.assertEqual(res.status, "dropped")
        self.assertEqual(len(self.smtp.messages), 1)


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestReleaseWithoutCondstore(ReleaseOnTwoMachines, TwoMachinesCase):
    def test_two_releases_racing_may_both_send(self):
        """La limite documentée : sans CONDSTORE, la sonde et le STORE ne
        sont pas atomiques, et deux relâchements simultanés partent."""
        res = self.entrelacer()
        self.assertEqual(res.status, "released")
        self.assertEqual(len(self.smtp.messages), 2)


if __name__ == "__main__":
    unittest.main()
