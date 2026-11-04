#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Refus partiel des destinataires, côté cache.

Ce que ces tests figent : un cache sans les colonnes du refus partiel les
reçoit à l'ouverture ; l'entrée de nouvel essai porte son enveloppe dans
`sealed_to`, derrière la garde qui la rend muette pour un code plus ancien ;
le journal passe à `partial` puis, selon ce qui arrive aux refusés, à
`sent` ou reste `partial`, en une transaction avec la file ; chaque départ
qui sert quelqu'un compte une fois dans les plafonds, à l'instant où il
part, et une ligne en attente de nouvel essai n'est pas comptée deux fois.
"""

import email
import email.policy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import new_key
from script.todo.mail.smtp_send import recipients
from script.todo.mail.store import (
    OUTBOX_MAX_ATTEMPTS,
    OUTBOX_REDIRECT_GUARD,
    SCHEMA_VERSION,
    RcptResult,
    Store,
)

COMPTE = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
TEMP = "refus.temporaire@example.net"
DEF = "refus.definitif@example.net"
REGLE = "3f9c0a1b2c4d"
CLE = "cle-message-1"
T0 = 1_800_000_000
HEURE = 3600

# Un transfert tel qu'il part : en-têtes qui nomment des destinataires.
TRANSFERT = (
    b"From: boite.regles@example.org\r\n"
    b"To: carole.regle@example.org\r\n"
    b"Cc: refus.temporaire@example.net\r\n"
    b"Subject: Tr: Devis\r\n"
    b"Message-ID: <transfert-partiel@example.org>\r\n"
    b"\r\n"
    b"Bonjour.\r\n"
)
ORIGINE = TRANSFERT.replace(
    b"\r\n\r\n",
    b"\r\nX-ERPLibre-Bcc: refus.temporaire@example.net,"
    b" refus.definitif@example.net\r\n\r\n",
    1,
)


class PartialStoreCase(unittest.TestCase):
    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", COMPTE, "generic")
        self.key = new_key() if self.mode != "clear" else None
        self.store = self.ouvrir()

    def tearDown(self):
        self.store.close()

    def ouvrir(self):
        store = Store(
            self.account, mode=self.mode, key=self.key, base=self.base
        )
        store.open()
        return store

    def colonnes(self, table):
        return {
            r["name"]
            for r in self.store._db().execute(f"PRAGMA table_info({table})")
        }

    def ligne(self, cle=CLE):
        return dict(
            self.store._db()
            .execute(
                "SELECT * FROM rule_log WHERE rule_id = ? AND msg_key = ?",
                (REGLE, cle),
            )
            .fetchone()
        )

    def brut(self, queue_id):
        """Les octets scellés d'une entrée, ouverts SANS retirer la garde :
        ce que lit un code qui ne connaît pas `retry`."""
        ligne = (
            self.store._db()
            .execute("SELECT sealed_raw FROM outbox WHERE id = ?", (queue_id,))
            .fetchone()
        )
        return self.store._crypto.open(bytes(ligne[0]))

    def scelle_to(self, queue_id):
        ligne = (
            self.store._db()
            .execute("SELECT sealed_to FROM outbox WHERE id = ?", (queue_id,))
            .fetchone()
        )
        return self.store._open(ligne[0])

    def en_file(self, cle=CLE, *, kind="auto_forward", at=T0):
        """Une ligne `queued` et son entrée d'origine ; rend l'entrée."""
        self.store.rule_log_claim(REGLE, cle, outcome="pending", at=at)
        return self.store.queue_auto(
            ORIGINE,
            f"{CAROLE}, {TEMP}, {DEF}",
            "Tr: Devis",
            held=False,
            rule_id=REGLE,
            source_key=cle,
            expires_at=at + 24 * HEURE,
            outcome="queued",
            reason=None,
            kind=kind,
        )

    def premier_depart(self, cle=CLE, *, kind="auto_forward", at=T0, **kw):
        """Un premier départ qui sert CAROLE, voit TEMP refusé en 450 et
        DEF en 550 ; rend (entrée d'origine, résultat)."""
        origine = self.en_file(cle, kind=kind, at=at)
        champs = dict(
            total=3,
            dropped=(550,),
            pending=(450,),
            sent_at=at,
            retry_raw=TRANSFERT,
            retry_to=TEMP,
            retry_subject="Tr: Devis",
            kind=kind,
            expires_at=at + 24 * HEURE,
            drop_queue_id=origine,
        )
        champs.update(kw)
        return origine, self.store.rule_log_rcpt_result(REGLE, cle, **champs)

    def ids_file(self):
        return [e["id"] for e in self.store.outbox()]


class TestMigration(PartialStoreCase):
    NOUVELLES = {"rcpt_total", "rcpt_dropped", "rcpt_pending", "retry_sent_at"}

    def test_a_cache_without_the_new_columns_gets_them(self):
        db = self.store._db()
        for nom in self.NOUVELLES:
            db.execute(f"ALTER TABLE rule_log DROP COLUMN {nom}")
        db.execute("ALTER TABLE outbox DROP COLUMN retry")
        db.commit()
        self.store.close()
        self.store = self.ouvrir()
        self.assertTrue(self.NOUVELLES <= self.colonnes("rule_log"))
        self.assertIn("retry", self.colonnes("outbox"))
        self.assertEqual(SCHEMA_VERSION, 6)

    def test_a_fresh_cache_has_the_new_columns(self):
        self.assertTrue(self.NOUVELLES <= self.colonnes("rule_log"))
        self.assertIn("retry", self.colonnes("outbox"))

    def test_an_old_outbox_row_reads_as_not_a_retry(self):
        db = self.store._db()
        db.execute("ALTER TABLE outbox DROP COLUMN retry")
        db.commit()
        db.execute(
            "INSERT INTO outbox(created_at, sealed_raw) VALUES(?, ?)",
            (T0, self.store._crypto.seal(b"Subject: x\r\n\r\ny\r\n")),
        )
        db.commit()
        self.store.close()
        self.store = self.ouvrir()
        [entree] = self.store.outbox()
        self.assertIs(entree["retry"], False)


class TestRetryEntry(PartialStoreCase):
    def test_a_retry_entry_is_sealed_behind_the_guard_whatever_its_kind(self):
        for rang, kind in enumerate(
            ("auto_reply", "auto_forward", "auto_redirect")
        ):
            with self.subTest(kind=kind):
                _, res = self.premier_depart(f"k{rang}", kind=kind)
                self.assertTrue(
                    self.brut(res.queue_id).startswith(OUTBOX_REDIRECT_GUARD)
                )
                self.assertEqual(self.scelle_to(res.queue_id), TEMP)

    def test_queued_raw_strips_the_guard_of_a_retry(self):
        _, res = self.premier_depart()
        self.assertEqual(self.store.queued_raw(res.queue_id), TRANSFERT)

    def test_outbox_lists_the_retry_flag(self):
        origine = self.en_file("autre")
        _, res = self.premier_depart()
        drapeaux = {e["id"]: e["retry"] for e in self.store.outbox()}
        self.assertEqual(drapeaux, {origine: False, res.queue_id: True})

    def test_the_retry_bytes_are_sealed_before_the_write_lock(self):
        origine = self.en_file()
        ordre = []
        vrai_sceller = self.store._sceller_file
        vrai_ecriture = self.store._ecriture

        def sceller(*args, **kwargs):
            ordre.append("sceller")
            return vrai_sceller(*args, **kwargs)

        def ecriture():
            ordre.append("BEGIN IMMEDIATE")
            return vrai_ecriture()

        with (
            patch.object(self.store, "_sceller_file", sceller),
            patch.object(self.store, "_ecriture", ecriture),
        ):
            self.store.rule_log_rcpt_result(
                REGLE,
                CLE,
                total=3,
                pending=(450,),
                sent_at=T0,
                retry_raw=TRANSFERT,
                retry_to=TEMP,
                kind="auto_forward",
                drop_queue_id=origine,
            )
        self.assertEqual(ordre, ["sceller", "BEGIN IMMEDIATE"])


class TestOlderReader(PartialStoreCase):
    """Un code qui ne connaît pas `retry` lit l'entrée comme avant."""

    def test_a_retry_read_without_its_flag_has_no_recipient(self):
        for rang, kind in enumerate(("auto_forward", "auto_reply")):
            with self.subTest(kind=kind):
                _, res = self.premier_depart(f"k{rang}", kind=kind)
                relu = email.message_from_bytes(
                    self.brut(res.queue_id), policy=email.policy.default
                )
                self.assertEqual(relu.keys(), [])
                self.assertEqual(recipients(relu), [])

    def test_an_old_reader_of_a_redirect_retry_gets_only_its_envelope(self):
        _, res = self.premier_depart(kind="auto_redirect")
        brut = self.brut(res.queue_id)
        # La lecture d'avant : garde retirée pour une `auto_redirect`,
        # enveloppe lue dans `sealed_to`.
        self.assertTrue(brut.startswith(OUTBOX_REDIRECT_GUARD))
        self.assertEqual(brut[len(OUTBOX_REDIRECT_GUARD) :], TRANSFERT)
        self.assertEqual(self.scelle_to(res.queue_id), TEMP)


class TestRcptResult(PartialStoreCase):
    def test_a_first_partial_departure_logs_partial_and_queues_the_retry(self):
        _, res = self.premier_depart()
        self.assertTrue(res.applied)
        self.assertIsNotNone(res.queue_id)
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_retry")
        )
        self.assertEqual(ligne["rcpt_dropped"], "550")
        self.assertEqual(ligne["rcpt_pending"], "450")
        self.assertEqual(ligne["queue_id"], res.queue_id)

    def test_the_retry_entry_carries_its_own_envelope_and_expiry_and_is_not_held(
        self,
    ):
        _, res = self.premier_depart()
        [entree] = self.store.outbox()
        self.assertEqual(entree["id"], res.queue_id)
        self.assertEqual(entree["to"], TEMP)
        self.assertEqual(entree["expires_at"], T0 + 24 * HEURE)
        self.assertFalse(entree["held"])
        self.assertTrue(entree["retry"])
        self.assertEqual(entree["kind"], "auto_forward")
        self.assertEqual(
            (entree["rule_id"], entree["source_key"]), (REGLE, CLE)
        )
        self.assertEqual(entree["max_attempts"], OUTBOX_MAX_ATTEMPTS)

    def test_the_original_entry_leaves_in_the_same_transaction(self):
        origine, res = self.premier_depart()
        self.assertEqual(self.ids_file(), [res.queue_id])
        self.assertNotEqual(origine, res.queue_id)

    def test_only_dropped_recipients_log_partial_refused_without_retry(self):
        origine = self.en_file()
        res = self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=3,
            dropped=(550, 0),
            sent_at=T0,
            kind="auto_forward",
            drop_queue_id=origine,
        )
        self.assertEqual(res, RcptResult(True, None))
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_refused")
        )
        self.assertEqual(ligne["rcpt_dropped"], "0,550")
        self.assertIsNone(ligne["rcpt_pending"])
        self.assertEqual(ligne["queue_id"], origine)
        self.assertEqual(self.ids_file(), [])

    def nouvel_essai(self, res, **kw):
        champs = dict(
            total=1,
            sent_at=T0 + 600,
            kind="auto_forward",
            drop_queue_id=res.queue_id,
        )
        champs.update(kw)
        return self.store.rule_log_rcpt_result(REGLE, CLE, **champs)

    def test_a_retry_served_to_all_turns_partial_into_sent_after_retry(self):
        origine = self.en_file()
        res = self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=2,
            pending=(450,),
            sent_at=T0,
            retry_raw=TRANSFERT,
            retry_to=TEMP,
            kind="auto_forward",
            drop_queue_id=origine,
        )
        suite = self.nouvel_essai(res)
        self.assertEqual(suite, RcptResult(True, None))
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("sent", "rcpt_retried")
        )
        self.assertIsNone(ligne["rcpt_dropped"])
        self.assertIsNone(ligne["rcpt_pending"])
        self.assertEqual(self.ids_file(), [])

    def test_a_retry_served_to_all_after_a_5xx_stays_partial_refused(self):
        _, res = self.premier_depart()
        self.nouvel_essai(res)
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_refused")
        )
        self.assertEqual(ligne["rcpt_dropped"], "550")
        self.assertIsNone(ligne["rcpt_pending"])

    def test_a_retry_refused_again_in_part_replaces_its_entry(self):
        origine = self.en_file()
        res = self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=3,
            pending=(450, 451),
            sent_at=T0,
            retry_raw=TRANSFERT,
            retry_to=f"{TEMP}, {DENIS}",
            kind="auto_forward",
            drop_queue_id=origine,
        )
        suite = self.nouvel_essai(
            res,
            total=2,
            pending=(452,),
            retry_raw=TRANSFERT,
            retry_to=DENIS,
        )
        self.assertTrue(suite.applied)
        self.assertNotEqual(suite.queue_id, res.queue_id)
        self.assertEqual(self.ids_file(), [suite.queue_id])
        self.assertEqual(self.scelle_to(suite.queue_id), DENIS)
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_retry")
        )
        self.assertEqual(ligne["rcpt_pending"], "452")
        self.assertEqual(ligne["queue_id"], suite.queue_id)

    def test_the_total_keeps_the_first_envelope_size(self):
        _, res = self.premier_depart()
        self.nouvel_essai(res)
        self.assertEqual(self.ligne()["rcpt_total"], 3)

    def test_a_terminal_line_gets_no_retry_and_loses_its_entry(self):
        for issue in ("sent", "skipped", "failed", "expired"):
            with self.subTest(issue=issue):
                cle = f"terminale-{issue}"
                origine = self.en_file(cle)
                self.store._db().execute(
                    "UPDATE rule_log SET outcome = ? WHERE msg_key = ?",
                    (issue, cle),
                )
                self.store._db().commit()
                avant = self.ligne(cle)
                res = self.store.rule_log_rcpt_result(
                    REGLE,
                    cle,
                    total=3,
                    pending=(450,),
                    sent_at=T0,
                    retry_raw=TRANSFERT,
                    retry_to=TEMP,
                    kind="auto_forward",
                    drop_queue_id=origine,
                )
                self.assertEqual(res, RcptResult(False))
                self.assertEqual(self.ligne(cle), avant)
                self.assertNotIn(origine, self.ids_file())
                self.assertEqual(self.ids_file(), [])

    def test_an_absent_line_gets_no_retry(self):
        res = self.store.rule_log_rcpt_result(
            REGLE,
            "absente",
            total=2,
            pending=(450,),
            sent_at=T0,
            retry_raw=TRANSFERT,
            retry_to=TEMP,
            kind="auto_forward",
        )
        self.assertEqual(res, RcptResult(False))
        self.assertEqual(self.ids_file(), [])

    def test_pending_without_bytes_is_refused_before_any_write(self):
        origine = self.en_file()
        avant = self.ligne()
        cas = (
            dict(pending=(450,)),
            dict(pending=(450,), retry_raw=TRANSFERT),
            dict(pending=(450,), retry_to=TEMP),
            dict(retry_raw=TRANSFERT, retry_to=TEMP),
            dict(
                pending=(450,),
                retry_raw=TRANSFERT,
                retry_to=TEMP,
                kind="manual",
            ),
        )
        for champs in cas:
            with self.subTest(champs=sorted(champs)):
                champs.setdefault("kind", "auto_forward")
                with self.assertRaises(ValueError):
                    self.store.rule_log_rcpt_result(
                        REGLE,
                        CLE,
                        total=3,
                        sent_at=T0,
                        drop_queue_id=origine,
                        **champs,
                    )
                self.assertEqual(self.ligne(), avant)
                self.assertEqual(self.ids_file(), [origine])

    def test_a_failed_insert_rolls_back_the_line_and_the_drop(self):
        for rang, ordre in enumerate(
            ("INSERT INTO outbox", "UPDATE rule_log SET outcome")
        ):
            with self.subTest(echec=ordre):
                self.verifier_annulation(f"k{rang}", ordre)

    def verifier_annulation(self, cle, prefixe):
        """Une écriture qui lève à `prefixe` laisse la ligne et la file
        comme avant l'appel."""
        origine = self.en_file(cle)
        avant = self.ligne(cle)
        file_avant = self.ids_file()
        vrai = sqlite3.connect

        class Panne(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith(prefixe):
                    raise sqlite3.OperationalError("disk I/O error")
                return super().execute(sql, *args)

        self.store.close()
        with patch(
            "script.todo.mail.store.sqlite3.connect",
            lambda *a, **k: vrai(*a, factory=Panne, **k),
        ):
            self.store = self.ouvrir()
        with self.assertRaises(sqlite3.OperationalError):
            self.store.rule_log_rcpt_result(
                REGLE,
                cle,
                total=3,
                pending=(450,),
                sent_at=T0,
                retry_raw=TRANSFERT,
                retry_to=TEMP,
                kind="auto_forward",
                drop_queue_id=origine,
            )
        self.assertFalse(self.store._db().in_transaction)
        self.assertEqual(self.ligne(cle), avant)
        self.assertEqual(self.ids_file(), file_avant)
        self.assertIn(origine, file_avant)
        self.store.close()
        self.store = self.ouvrir()

    def test_a_first_departure_sets_sent_at_and_a_retry_sets_retry_sent_at(
        self,
    ):
        _, res = self.premier_depart()
        ligne = self.ligne()
        self.assertEqual(
            (ligne["sent_at"], ligne["retry_sent_at"]), (T0, None)
        )
        self.nouvel_essai(res, sent_at=T0 + 900)
        ligne = self.ligne()
        self.assertEqual(
            (ligne["sent_at"], ligne["retry_sent_at"]), (T0, T0 + 900)
        )


class TestRetryClosed(PartialStoreCase):
    def test_closing_a_retry_moves_pending_codes_to_dropped_with_its_reason(
        self,
    ):
        _, res = self.premier_depart()
        self.assertTrue(
            self.store.rule_log_retry_closed(
                REGLE, CLE, "expired", drop_queue_id=res.queue_id
            )
        )
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "expired")
        )
        self.assertEqual(ligne["rcpt_dropped"], "450,550")
        self.assertIsNone(ligne["rcpt_pending"])
        self.assertEqual(self.ids_file(), [])

    def test_closing_with_the_last_codes_records_them_instead_of_the_pending(
        self,
    ):
        _, res = self.premier_depart()
        self.store.rule_log_retry_closed(
            REGLE,
            CLE,
            "attempts_exhausted",
            drop_queue_id=res.queue_id,
            codes=[550],
        )
        ligne = self.ligne()
        self.assertEqual(ligne["rcpt_dropped"], "550,550")
        self.assertEqual(ligne["reason"], "attempts_exhausted")

    def test_closing_drops_the_entry_and_updates_the_line_in_one_transaction(
        self,
    ):
        _, res = self.premier_depart()
        avant = self.ligne()
        vrai = sqlite3.connect

        class Panne(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith("UPDATE rule_log SET reason"):
                    raise sqlite3.OperationalError("disk I/O error")
                return super().execute(sql, *args)

        self.store.close()
        with patch(
            "script.todo.mail.store.sqlite3.connect",
            lambda *a, **k: vrai(*a, factory=Panne, **k),
        ):
            self.store = self.ouvrir()
        with self.assertRaises(sqlite3.OperationalError):
            self.store.rule_log_retry_closed(
                REGLE, CLE, "expired", drop_queue_id=res.queue_id
            )
        self.assertEqual(self.ids_file(), [res.queue_id])
        self.assertEqual(self.ligne(), avant)

    def test_closing_leaves_a_non_partial_line_alone(self):
        origine = self.en_file()
        avant = self.ligne()
        self.assertFalse(
            self.store.rule_log_retry_closed(
                REGLE, CLE, "expired", drop_queue_id=origine
            )
        )
        self.assertEqual(self.ligne(), avant)
        self.assertEqual(self.ids_file(), [])

    def test_closing_a_stray_entry_leaves_the_waiting_retry_alone(self):
        _, res = self.premier_depart()
        avant = self.ligne()
        self.assertFalse(
            self.store.rule_log_retry_closed(
                REGLE, CLE, "expired", drop_queue_id=res.queue_id + 100
            )
        )
        self.assertEqual(self.ligne(), avant)
        self.assertEqual(self.ids_file(), [res.queue_id])

    def test_set_outcome_never_rewrites_partial(self):
        self.premier_depart()
        for issue in ("expired", "failed", "sent", "queued"):
            self.assertFalse(
                self.store.rule_log_set_outcome(REGLE, CLE, issue, "x")
            )
        self.assertEqual(self.ligne()["outcome"], "partial")


class TestRetryNarrowed(PartialStoreCase):
    def test_narrowing_keeps_the_4xx_in_the_envelope_and_drops_the_others(
        self,
    ):
        origine = self.en_file()
        res = self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=3,
            pending=(450, 451),
            sent_at=T0,
            retry_raw=TRANSFERT,
            retry_to=f"{TEMP}, {DEF}",
            kind="auto_forward",
            drop_queue_id=origine,
        )
        self.assertTrue(
            self.store.rule_log_retry_narrowed(
                REGLE,
                CLE,
                res.queue_id,
                retry_to=TEMP,
                pending=(450,),
                dropped=(550,),
            )
        )
        self.assertEqual(self.scelle_to(res.queue_id), TEMP)
        ligne = self.ligne()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_retry")
        )
        self.assertEqual(ligne["rcpt_pending"], "450")
        self.assertEqual(ligne["rcpt_dropped"], "550")

    def test_narrowing_a_retry_the_line_no_longer_points_to_writes_nothing(
        self,
    ):
        _, res = self.premier_depart()
        avant = self.ligne()
        db = self.store._db()
        egaree = self.store._inserer_file(
            db,
            TRANSFERT,
            TEMP,
            "Tr: Devis",
            held=False,
            kind="auto_forward",
            rule_id=REGLE,
            source_key=CLE,
            expires_at=T0 + 24 * HEURE,
            max_attempts=OUTBOX_MAX_ATTEMPTS,
            retry=True,
        )
        db.commit()
        for queue_id in (egaree, res.queue_id + 100):
            self.assertFalse(
                self.store.rule_log_retry_narrowed(
                    REGLE,
                    CLE,
                    queue_id,
                    retry_to=DENIS,
                    pending=(450,),
                    dropped=(550,),
                )
            )
        self.assertEqual(self.ligne(), avant)
        self.assertEqual(self.scelle_to(res.queue_id), TEMP)
        self.assertEqual(self.scelle_to(egaree), TEMP)

    def test_narrowing_is_idempotent(self):
        """Un second refus lu sur l'enveloppe déjà réduite, ou sur une
        enveloppe qui n'est plus celle de l'entrée, n'écrit rien : les
        codes abandonnés ne comptent qu'une fois."""
        origine = self.en_file()
        res = self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=3,
            pending=(450, 451),
            sent_at=T0,
            retry_raw=TRANSFERT,
            retry_to=f"{TEMP}, {DEF}",
            kind="auto_forward",
            drop_queue_id=origine,
        )
        reduire = dict(retry_to=TEMP, pending=(450,), dropped=(550,))
        self.assertTrue(
            self.store.rule_log_retry_narrowed(
                REGLE, CLE, res.queue_id, tried=(TEMP, DEF), **reduire
            )
        )
        apres = self.ligne()
        self.assertFalse(
            self.store.rule_log_retry_narrowed(
                REGLE, CLE, res.queue_id, **reduire
            )
        )
        self.assertFalse(
            self.store.rule_log_retry_narrowed(
                REGLE,
                CLE,
                res.queue_id,
                retry_to=DENIS,
                pending=(450,),
                dropped=(550,),
                tried=(TEMP.upper(), DEF),
            )
        )
        self.assertEqual(self.ligne(), apres)
        self.assertEqual(apres["rcpt_dropped"], "550")
        self.assertEqual(self.scelle_to(res.queue_id), TEMP)

    def test_narrowing_to_nothing_is_refused(self):
        _, res = self.premier_depart()
        with self.assertRaises(ValueError):
            self.store.rule_log_retry_narrowed(
                REGLE, CLE, res.queue_id, retry_to="", pending=(), dropped=()
            )


class TestRetryDeparted(PartialStoreCase):
    def test_a_retry_departure_alone_counts_in_its_hour(self):
        self.premier_depart()
        t1 = T0 + 50 * 60
        self.assertTrue(self.store.rule_log_retry_departed(REGLE, CLE, t1))
        self.assertEqual(self.ligne()["retry_sent_at"], t1)
        self.assertEqual(self.store.rule_log_sent_since(T0), 2)

    def test_a_line_that_is_not_partial_is_left_alone(self):
        self.store.rule_log_claim(
            REGLE, CLE, outcome="sent", at=T0, fingerprint="f"
        )
        self.assertFalse(self.store.rule_log_retry_departed(REGLE, CLE, T0))
        self.assertIsNone(self.ligne()["retry_sent_at"])


class TestCounts(PartialStoreCase):
    def test_a_partial_line_counts_once_at_its_first_departure(self):
        self.premier_depart()
        self.assertEqual(self.store.rule_log_sent_since(T0), 1)
        self.assertEqual(self.store.rule_log_recent_sends(T0), 1)
        self.assertEqual(self.store.rule_log_sent_since(T0 + 1), 0)

    def test_a_partial_line_whose_retry_waits_is_not_counted_twice(self):
        self.premier_depart()
        # La ligne `partial` a une entrée en file, mais n'est plus `queued`.
        self.assertEqual(self.store.rule_log_recent_sends(T0 - HEURE), 1)
        self.assertEqual(self.store.rule_log_sent_since(T0 - HEURE), 1)

    def test_a_retry_departure_counts_once_more_in_its_hour(self):
        _, res = self.premier_depart()
        t1 = T0 + 50 * 60
        self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=1,
            sent_at=t1,
            kind="auto_forward",
            drop_queue_id=res.queue_id,
        )
        self.assertEqual(self.store.rule_log_sent_since(T0), 2)
        self.assertEqual(self.store.rule_log_sent_since(T0 + 1), 1)
        self.assertEqual(self.store.rule_log_sent_since(t1 + 1), 0)

    def test_retry_sent_at_counts_for_the_engine_cap_too(self):
        _, res = self.premier_depart()
        t1 = T0 + 50 * 60
        self.store.rule_log_rcpt_result(
            REGLE,
            CLE,
            total=1,
            sent_at=t1,
            kind="auto_forward",
            drop_queue_id=res.queue_id,
        )
        self.assertEqual(self.store.rule_log_recent_sends(T0), 2)
        self.assertEqual(self.store.rule_log_recent_sends(T0 + 1), 1)

    def test_partial_counts_as_an_approved_send(self):
        self.store.rule_log_claim(
            REGLE, CLE, outcome="pending", at=T0, fingerprint="empreinte"
        )
        self.store.rule_log_rcpt_result(
            REGLE, CLE, total=2, dropped=(550,), sent_at=T0, kind="auto_reply"
        )
        self.assertEqual(self.store.rule_log_sent_count(REGLE, "empreinte"), 1)

    def test_partial_counts_for_the_sender_throttle(self):
        self.store.rule_log_claim(
            REGLE, CLE, outcome="pending", at=T0, sender_hash="h-exp"
        )
        self.store.rule_log_rcpt_result(
            REGLE, CLE, total=2, dropped=(550,), sent_at=T0, kind="auto_reply"
        )
        self.assertEqual(self.store.rule_log_last_send(REGLE, "h-exp"), T0)

    def test_partial_counts_toward_the_daily_report_cap(self):
        self.premier_depart()
        self.assertEqual(self.store.rule_log_rule_sends(REGLE, T0), 1)


class TestEntries(PartialStoreCase):
    def test_entries_return_the_recipient_counts(self):
        _, res = self.premier_depart()
        [entree] = self.store.rule_log_entries()
        self.assertEqual(entree["outcome"], "partial")
        self.assertEqual(entree["rcpt_total"], 3)
        self.assertEqual(entree["rcpt_dropped"], [550])
        self.assertEqual(entree["rcpt_pending"], [450])
        self.assertEqual(entree["sent_at"], T0)
        self.assertIsNone(entree["retry_sent_at"])
        self.assertEqual(entree["queue_id"], res.queue_id)

    def test_entries_without_any_refusal_have_empty_counts(self):
        self.store.rule_log_claim(REGLE, CLE, outcome="sent", at=T0)
        [entree] = self.store.rule_log_entries()
        self.assertIsNone(entree["rcpt_total"])
        self.assertEqual(entree["rcpt_dropped"], [])
        self.assertEqual(entree["rcpt_pending"], [])

    def test_state_reads_outcome_reason_and_queue(self):
        _, res = self.premier_depart()
        self.assertEqual(
            self.store.rule_log_state(REGLE, CLE),
            {
                "outcome": "partial",
                "reason": "rcpt_retry",
                "queue_id": res.queue_id,
            },
        )
        self.assertIsNone(self.store.rule_log_state(REGLE, "absente"))


class TestEncrypted(TestRetryEntry):
    """Les mêmes propriétés de la file sous un cache chiffré."""

    mode = "encrypted"


if __name__ == "__main__":
    unittest.main()
