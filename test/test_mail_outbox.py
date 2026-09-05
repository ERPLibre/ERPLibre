#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""File d'attente d'envoi.

Un message écrit hors ligne attend plutôt que d'être perdu, et part au
retour du réseau — sauf s'il est retenu. Ce fichier vérifie surtout ce qui
ne doit PAS arriver : un message retenu qui part seul, un échec qui bloque
la file, ou un envoi qui disparaît sans trace.
"""
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import build_message
from script.todo.mail.store import Store, new_key
from script.todo.mail.tui import Session, deliver, flush_outbox


class FauxTransport:
    def quit(self):
        pass


class FauxSyncer:
    transport = None


class OutboxCase(unittest.TestCase):
    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.key = new_key() if self.mode != "clear" else None
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        self.msg = build_message(self.account, "a@y.ca", "Devis", "Bonjour")
        self.envoyes = []

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def hors_ligne(self):
        return Session(self.account, self.store, None, password="x")

    def en_ligne(self):
        return Session(self.account, self.store, FauxSyncer(), password="x")

    def vider(self, send_fn=None):
        return flush_outbox(
            self.en_ligne(),
            send_fn=send_fn
            or (lambda a, m, t: self.envoyes.append(m) or ["a@y.ca"]),
            connect_fn=lambda a, p: FauxTransport(),
        )


class TestQueueing(OutboxCase):
    def test_writing_offline_queues_instead_of_losing(self):
        deliver(self.hors_ligne(), self.msg)
        self.assertEqual(len(self.store.outbox()), 1)

    def test_the_queue_keeps_the_order_it_received(self):
        """L'ordre d'écriture est l'ordre d'envoi : deux messages d'un même
        échange arriveraient sinon inversés chez le destinataire."""
        for sujet in ("un", "deux", "trois"):
            deliver(
                self.hors_ligne(),
                build_message(self.account, "a@y.ca", sujet, "x"),
            )
        self.assertEqual(
            [e["subject"] for e in self.store.outbox()],
            ["un", "deux", "trois"],
        )


class TestFlushing(OutboxCase):
    def test_the_queue_empties_when_the_network_is_back(self):
        deliver(self.hors_ligne(), self.msg)
        partis, retenus, echoues = self.vider()
        self.assertEqual((partis, retenus, echoues), (1, 0, 0))
        self.assertEqual(self.store.outbox(), [])

    def test_a_held_message_never_leaves_on_its_own(self):
        """C'est le sens de la retenue : seul un geste la lève, jamais un
        délai qui expire."""
        deliver(self.hors_ligne(), self.msg)
        self.store.set_held(self.store.outbox()[0]["id"], True)
        partis, retenus, _ = self.vider()
        self.assertEqual((partis, retenus), (0, 1))
        self.assertEqual(len(self.store.outbox()), 1)

    def test_releasing_lets_it_go(self):
        deliver(self.hors_ligne(), self.msg)
        ident = self.store.outbox()[0]["id"]
        self.store.set_held(ident, True)
        self.vider()
        self.store.set_held(ident, False)
        self.assertEqual(self.vider()[0], 1)
        self.assertEqual(self.store.outbox(), [])

    def test_a_failure_keeps_the_message_and_its_reason(self):
        """Un compteur seul dirait qu'on a essayé cinq fois sans jamais
        dire pourquoi."""
        deliver(self.hors_ligne(), self.msg)

        def refuse(a, m, t):
            raise OSError("550 boîte pleine")

        partis, _, echoues = self.vider(send_fn=refuse)
        self.assertEqual((partis, echoues), (0, 1))
        entree = self.store.outbox()[0]
        self.assertEqual(entree["attempts"], 1)
        self.assertIn("boîte pleine", entree["last_error"])

    def test_one_failure_does_not_block_those_behind_it(self):
        """Sans ça, un destinataire invalide gèlerait la file pour de bon."""
        deliver(
            self.hors_ligne(),
            build_message(self.account, "casse@y.ca", "casse", "x"),
        )
        deliver(
            self.hors_ligne(),
            build_message(self.account, "bon@y.ca", "bon", "x"),
        )

        def selectif(a, m, t):
            if m.get("Subject") == "casse":
                raise OSError("refus")
            self.envoyes.append(m)
            return ["bon@y.ca"]

        partis, _, echoues = self.vider(send_fn=selectif)
        self.assertEqual((partis, echoues), (1, 1))
        self.assertEqual(
            [e["subject"] for e in self.store.outbox()], ["casse"]
        )

    def test_an_offline_flush_does_nothing(self):
        deliver(self.hors_ligne(), self.msg)
        self.assertEqual(flush_outbox(self.hors_ligne()), (0, 0, 0))
        self.assertEqual(len(self.store.outbox()), 1)


class TestQueuedMessagesAreSealed(OutboxCase):
    mode = "encrypted"

    def test_the_body_is_not_readable_in_the_cache_file(self):
        """Un cache chiffré qui laisserait ses envois en clair protégerait
        tout SAUF ce qu'on vient d'écrire."""
        deliver(self.hors_ligne(), self.msg)
        brut = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(b"Bonjour", brut)

    def test_it_still_goes_out_intact(self):
        deliver(self.hors_ligne(), self.msg)
        self.vider()
        self.assertEqual(len(self.envoyes), 1)
        self.assertEqual(self.envoyes[0].get("Subject"), "Devis")


if __name__ == "__main__":
    unittest.main()
