#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La vidange de la file, schéma v6 : Envoyés, expiration, plafond 5xx.

Un envoi différé est classé dans Envoyés une fois, sans Cci ; une entrée
périmée part sans être envoyée ; un refus permanent répété retient un
message écrit à la main et retire une réponse automatique ; une réponse
automatique dont la règle a disparu ou changé n'est plus envoyée ; deux
vidanges concurrentes n'envoient jamais deux fois la même entrée.
"""

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import storage
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.smtp_send import SmtpError, build_message
from script.todo.mail.store import Store
from script.todo.mail.tui import Session, deliver, flush_outbox

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
T0 = 1_790_000_000


class FauxSmtp:
    def quit(self):
        pass


class FauxImap:
    def __init__(self):
        self.appended = []

    def append(self, folder, raw, flags):
        self.appended.append((folder, raw, tuple(flags)))


class FauxSyncer:
    def __init__(self):
        self.transport = FauxImap()

    def sync_one(self, folder):
        pass


class OutboxV6Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.store = Store(self.account, mode="clear", base=self.base)
        self.store.open()
        self.syncer = FauxSyncer()
        self.envois = []

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def en_ligne(self, store=None):
        return Session(
            self.account, store or self.store, self.syncer, password="x"
        )

    def hors_ligne(self):
        return Session(self.account, self.store, None, password="x")

    def envoyer(self, account, msg, transport):
        self.envois.append(msg)
        return [CAROLE]

    def vider(self, send_fn=None, now=T0, store=None):
        return flush_outbox(
            self.en_ligne(store),
            send_fn=send_fn or self.envoyer,
            connect_fn=lambda a, p: FauxSmtp(),
            now=lambda: now,
        )

    def manuel(self, **kw):
        msg = build_message(self.account, CAROLE, "Devis", "Bonjour", **kw)
        deliver(self.hors_ligne(), msg)
        return self.store.outbox()[-1]["id"]

    def regle(self):
        rule = new_rule("reply", "Absence")
        rule.action.body = "Absente."
        storage.upsert_rule(
            "perso", rule, rearm=Armed(1, 1, T0), base=self.base
        )
        return rule

    def automatique(self, rule, *, held=False, expires_at=T0 + 86400):
        cle = f"cle-{len(self.store.outbox())}"
        self.store.rule_log_claim(
            rule.id,
            cle,
            outcome="pending",
            at=T0,
            fingerprint=rule.fingerprint(),
        )
        msg = build_message(self.account, CAROLE, "Auto: Devis", "Absente.")
        ident = self.store.queue_auto(
            msg.as_bytes(),
            CAROLE,
            "Auto: Devis",
            held=held,
            rule_id=rule.id,
            source_key=cle,
            expires_at=expires_at,
            outcome="held" if held else "queued",
            reason="hold_first" if held else "offline",
        )
        return ident, cle


class TestDeferredSendIsFiled(OutboxV6Case):
    def test_one_copy_in_sent_without_bcc(self):
        self.manuel(bcc=[DENIS])
        self.assertEqual(self.vider(), (1, 0, 0))
        self.assertEqual(len(self.syncer.transport.appended), 1)
        dossier, brut, drapeaux = self.syncer.transport.appended[0]
        self.assertEqual(dossier, self.account.sent_folder)
        self.assertNotIn(DENIS.encode(), brut)
        self.assertNotIn(b"X-ERPLibre-Bcc", brut)
        self.assertIn("\\Seen", drapeaux)

    def test_a_failed_append_is_not_a_failed_send(self):
        self.manuel()
        self.syncer.transport = None
        self.assertEqual(self.vider(), (1, 0, 0))
        self.assertEqual(self.store.outbox(), [])


class TestDeliverWithoutQueue(OutboxV6Case):
    def test_offline_without_queue_raises_and_writes_nothing(self):
        """Un appelant qui met lui-même en file (réponse automatique) ne
        laisse pas `deliver` en faire une entrée manuelle."""
        from script.todo.mail.tui import DeliverOffline

        msg = build_message(self.account, CAROLE, "Devis", "Bonjour")
        with self.assertRaises(DeliverOffline):
            deliver(self.hors_ligne(), msg, queue_offline=False)
        self.assertEqual(self.store.outbox(), [])

    def test_offline_by_default_still_queues_a_manual_entry(self):
        ident = self.manuel()
        entree = [e for e in self.store.outbox() if e["id"] == ident][0]
        self.assertEqual(entree["kind"], "manual")


class TestExpiry(OutboxV6Case):
    def test_an_expired_auto_entry_is_dropped_and_logged(self):
        rule = self.regle()
        _ident, cle = self.automatique(rule, held=True, expires_at=T0 + 10)
        self.assertEqual(self.vider(now=T0 + 11), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_outcome(rule.id, cle), "expired")
        self.assertEqual(self.envois, [])

    def test_before_expiry_it_stays(self):
        rule = self.regle()
        self.automatique(rule, held=True, expires_at=T0 + 10)
        self.assertEqual(self.vider(now=T0 + 5), (0, 1, 0))


class TestPermanentFailures(OutboxV6Case):
    @staticmethod
    def refuser(code):
        def refuse(account, msg, transport):
            raise SmtpError(f"{code} refus du serveur", code=code)

        return refuse

    def test_a_manual_message_is_held_after_three_5xx(self):
        ident = self.manuel()
        for _ in range(3):
            self.assertEqual(self.vider(self.refuser(550))[2], 1)
        entree = self.store.outbox()[0]
        self.assertEqual(entree["id"], ident)
        self.assertTrue(entree["held"])
        self.assertIn("refus du serveur", entree["last_error"])

    def test_an_auto_reply_is_dropped_after_three_5xx(self):
        rule = self.regle()
        _ident, cle = self.automatique(rule)
        for _ in range(3):
            self.vider(self.refuser(550))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_outcome(rule.id, cle), "failed")
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["reason"],
            "attempts_exhausted",
        )

    def test_transient_failures_are_not_capped(self):
        self.manuel()
        for _ in range(5):
            self.vider(self.refuser(421))
        entree = self.store.outbox()[0]
        self.assertFalse(entree["held"])
        self.assertEqual(entree["attempts"], 5)


class TestAutoEntriesFollowTheirRule(OutboxV6Case):
    def test_a_disabled_rule_drops_its_entry(self):
        rule = self.regle()
        _ident, cle = self.automatique(rule)
        storage.set_enabled(
            "perso", rule.id, False, armed=None, base=self.base
        )
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["reason"], "rule_disabled"
        )

    def test_a_removed_rule_drops_its_entry(self):
        rule = self.regle()
        self.automatique(rule)
        storage.delete_rule("perso", rule.id, base=self.base)
        self.vider()
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.envois, [])

    def test_a_changed_fingerprint_drops_even_a_held_entry(self):
        rule = self.regle()
        _ident, cle = self.automatique(rule, held=True)
        rule.action.body = "Autre texte."
        storage.upsert_rule("perso", rule, base=self.base)
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["reason"], "rule_changed"
        )

    def test_an_unreadable_rules_file_keeps_auto_entries_and_sends_manual(
        self,
    ):
        rule = self.regle()
        self.automatique(rule)
        self.manuel()
        chemin = storage.rules_path("perso", self.base)
        chemin.write_text("{pas du json")
        self.assertEqual(self.vider(), (1, 0, 0))
        restantes = self.store.outbox()
        self.assertEqual([e["kind"] for e in restantes], ["auto_reply"])

    def test_a_missing_rules_file_keeps_auto_entries(self):
        rule = self.regle()
        self.automatique(rule)
        storage.rules_path("perso", self.base).unlink()
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(len(self.store.outbox()), 1)

    def test_an_entry_already_sent_in_the_log_is_dropped_unsent(self):
        rule = self.regle()
        _ident, cle = self.automatique(rule)
        self.store.rule_log_set_outcome(rule.id, cle, "sent")
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.envois, [])

    def test_a_sent_auto_entry_is_logged_sent(self):
        rule = self.regle()
        _ident, cle = self.automatique(rule)
        self.assertEqual(self.vider(), (1, 0, 0))
        self.assertEqual(self.store.rule_log_outcome(rule.id, cle), "sent")


class TestTwoProcesses(OutboxV6Case):
    def test_two_stores_flushing_the_same_queue_send_once(self):
        """Deux `Store` sur le même `cache.db` : la réservation de la
        première vidange écarte l'entrée de la seconde, lancée en plein
        envoi."""
        self.manuel()
        second = Store(self.account, mode="clear", base=self.base)
        second.open()
        self.addCleanup(second.close)
        imbrique = []

        def envoyer(account, msg, transport):
            if not imbrique:
                imbrique.append(self.vider(store=second))
            self.envois.append(msg)
            return [CAROLE]

        self.assertEqual(self.vider(envoyer), (1, 0, 0))
        self.assertEqual(imbrique, [(0, 0, 0)])
        self.assertEqual(len(self.envois), 1)

    def test_an_entry_sent_elsewhere_is_not_expired_meanwhile(self):
        """Une entrée réservée par une autre vidange, en plein envoi, n'est
        ni retirée ni journalisée `expired` après son échéance : l'issue
        `sent` de l'autre vidange reste visible à la limite d'envoi par
        règle et par expéditeur."""
        rule = self.regle()
        ident, cle = self.automatique(rule, expires_at=T0 + 10)
        self.assertTrue(self.store.outbox_claim(ident, T0 + 5))
        self.assertEqual(self.vider(now=T0 + 11), (0, 0, 0))
        self.assertEqual([e["id"] for e in self.store.outbox()], [ident])
        self.assertTrue(self.store.rule_log_set_outcome(rule.id, cle, "sent"))

    def test_a_rule_change_does_not_drop_an_entry_sent_elsewhere(self):
        rule = self.regle()
        ident, _cle = self.automatique(rule)
        self.store.outbox_claim(ident, T0)
        storage.set_enabled(
            "perso", rule.id, False, armed=None, base=self.base
        )
        self.vider(now=T0 + 1)
        self.assertEqual([e["id"] for e in self.store.outbox()], [ident])


class TestHeldDuringTheFlush(OutboxV6Case):
    def test_an_entry_held_while_another_is_sent_stays(self):
        """La retenue se relit dans la base au moment de l'envoi : posée
        depuis l'écran `o` pendant la vidange, elle est respectée."""
        self.manuel()
        second = self.manuel()

        def envoyer(account, msg, transport):
            if not self.envois:
                self.store.set_held(second, True)
            self.envois.append(msg)
            return [CAROLE]

        self.assertEqual(self.vider(envoyer), (1, 1, 0))
        entree = self.store.outbox()[0]
        self.assertEqual((entree["id"], entree["held"]), (second, True))
        self.assertIsNone(entree["claimed_at"])

    def test_a_held_entry_keeps_no_claim(self):
        ident = self.manuel()
        self.store.set_held(ident, True)
        self.assertEqual(self.vider(), (0, 1, 0))
        self.assertTrue(self.store.outbox_claim(ident, T0 + 1))


class TestUnreachableServer(OutboxV6Case):
    def test_a_failed_connection_stops_the_flush(self):
        """Après un échec de connexion, les entrées suivantes restent en
        file sans nouvel essai : chacune attendrait le même délai."""
        for _ in range(3):
            self.manuel()
        connexions = []

        def connecter(account, secret):
            connexions.append(1)
            raise SmtpError("délai de connexion dépassé")

        resultat = flush_outbox(
            self.en_ligne(),
            send_fn=self.envoyer,
            connect_fn=connecter,
            now=lambda: T0,
        )
        self.assertEqual(resultat, (0, 0, 1))
        self.assertEqual(len(connexions), 1)
        entrees = self.store.outbox()
        self.assertEqual(len(entrees), 3)
        self.assertEqual([e["attempts"] for e in entrees], [1, 0, 0])
        self.assertTrue(all(e["claimed_at"] is None for e in entrees))

    def test_a_refused_message_does_not_stop_the_next_one(self):
        self.manuel()
        self.manuel()

        def envoyer(account, msg, transport):
            if not self.envois:
                self.envois.append(None)
                raise SmtpError("452 boîte pleine", code=452)
            self.envois.append(msg)
            return [CAROLE]

        self.assertEqual(self.vider(envoyer), (1, 0, 1))


if __name__ == "__main__":
    unittest.main()
