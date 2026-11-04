#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La conversion d'un cache d'un mode à l'autre : ce qu'elle garde, ce
qu'elle traduit, ce qu'elle refuse, la reprise après un arrêt brutal et
l'effacement sûr de l'ancienne copie.

Tout vit sous un dossier temporaire, `HOME` compris ; les coffres sont des
doubles en mémoire (ou sur un fichier du dossier temporaire pour les
sous-processus)."""

import errno
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mail_cache_fixtures import (
    CAROLE,
    COMPTE,
    DENIS,
    FauxCoffre,
    fichiers,
    instantane,
    remplir,
    rendre_v4,
)
from test_mail_rules_engine import BRUNO, HOUR, EngineCase

from script.todo.mail import accounts as mail_accounts
from script.todo.mail import cache_convert
from script.todo.mail import store as store_mod
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.cache_convert import (
    ConvertError,
    convert_cache,
    recover,
    secure_erase,
)
from script.todo.mail.crypto import CLEAR_MAGIC, AesGcmCrypto, new_key
from script.todo.mail.imap_sync import Syncer
from script.todo.mail.rules import storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.store import (
    CACHE_CTL_DIRNAME,
    LEGACY_KEY_PREFIX,
    PROBE_UNKNOWN,
    CacheBusy,
    CacheNeedsReseal,
    Store,
    StoreError,
    _probe_root,
    _sealed_starts_with,
    inscribed_mode,
    salted_hash,
)
from script.todo.mail.tui import Session
from script.todo.todo_i18n import t


def compte(mode=None):
    acc = account_from_preset("perso", COMPTE, "generic")
    acc.cache_mode = mode
    return acc


class ConvertCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.base = self.tmp / "mail"
        self.home = self.tmp / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.coffre = FauxCoffre()
        self.racine = self.base / "perso"
        self.ctl = self.base / CACHE_CTL_DIRNAME / "perso"

    def tearDown(self):
        self._tmp.cleanup()

    def creer(self, mode="clear"):
        store = Store(compte(), mode=mode, secrets=self.coffre, base=self.base)
        store.open()
        self.reperes = remplir(store)
        self.avant = instantane(store)
        store.close()
        return self.reperes

    def ouvrir(self, coffre=None):
        store = Store(
            compte(),
            secrets=self.coffre if coffre is None else coffre,
            base=self.base,
        )
        store.open()
        self.addCleanup(store.close)
        return store

    def convertir(self, target, **kw):
        kw.setdefault("secrets", self.coffre)
        return convert_cache(compte(), target, base=self.base, **kw)

    def sql(self, *requetes, racine=None):
        conn = sqlite3.connect((racine or self.racine) / "cache.db")
        try:
            for requete in requetes:
                if isinstance(requete, tuple):
                    conn.execute(*requete)
                else:
                    conn.execute(requete)
            conn.commit()
        finally:
            conn.close()

    def lire(self, requete, params=(), racine=None):
        conn = sqlite3.connect((racine or self.racine) / "cache.db")
        try:
            return conn.execute(requete, params).fetchall()
        finally:
            conn.close()

    def assert_ctl_vide(self):
        restes = sorted(os.listdir(self.ctl)) if self.ctl.exists() else []
        self.assertEqual([r for r in restes if r != "lock"], [])


class TestConvertKeepsEverything(ConvertCase):
    def test_a_round_trip_keeps_every_row_and_body(self):
        self.creer("clear")
        resultat = self.convertir("encrypted")
        self.assertEqual(
            (resultat.source, resultat.target), ("clear", "encrypted")
        )
        store = self.ouvrir()
        self.assertEqual(store.mode, "encrypted")
        self.assertEqual(instantane(store), self.avant)
        store.close()
        self.convertir("clear")
        store = self.ouvrir()
        self.assertEqual(store.mode, "clear")
        self.assertEqual(instantane(store), self.avant)
        self.assert_ctl_vide()

    def test_nothing_readable_is_left_in_the_encrypted_copy(self):
        self.creer("clear")
        self.convertir("encrypted")
        contenu = fichiers(self.racine)
        for chemin, octets in contenu.items():
            with self.subTest(chemin=chemin):
                self.assertFalse(chemin.endswith(".eml"))
                for texte in (
                    b"Question sur la facture",
                    b"Corps de la question",
                    b"Voici la r",
                    CAROLE.encode(),
                    DENIS.encode(),
                    COMPTE.encode(),
                    b"question-1@example.org",
                ):
                    self.assertNotIn(texte, octets)
        tables = [r[0] for r in self.lire("SELECT name FROM sqlite_master")]
        self.assertNotIn("messages_fts", tables)

    def test_the_rules_journal_still_recognises_its_messages(self):
        self.creer("clear")
        self.convertir("encrypted")
        store = self.ouvrir()
        self.assertTrue(
            store.rule_log_seen(
                "regle-a", store.message_key("<question-1@example.org>", 7, 1)
            )
        )
        self.assertTrue(
            store.rule_log_seen("regle-b", store.message_key("", 7, 2))
        )
        # L'expéditeur seul, puis la cible seule : chacune des deux
        # empreintes est traduite.
        self.assertIsNotNone(
            store.rule_log_last_send("regle-b", store.address_hash(DENIS))
        )
        self.assertIsNotNone(
            store.rule_log_last_send("regle-b", "", store.address_hash(CAROLE))
        )
        self.assertTrue(store.is_rule_send("<envoi-regle@example.org>"))
        self.assertTrue(
            store.is_auto_sent(store._msgid_hash("<auto-tiers@example.org>"))
        )

    def test_outbox_entries_keep_their_ids_links_and_bytes(self):
        reperes = self.creer("clear")
        avant = Store(compte(), mode="clear", base=self.base)
        avant.open()
        brut = {e["id"]: avant.queued_raw(e["id"]) for e in avant.outbox()}
        avant.close()
        self.convertir("encrypted")
        store = self.ouvrir()
        entree = store.queued_entry(reperes["auto"])
        cle = store.message_key("<question-1@example.org>", 7, 1)
        ligne = store.rule_log_state("regle-a", cle)
        self.assertEqual(ligne["queue_id"], reperes["auto"])
        self.assertEqual(entree["source_key"], cle)
        self.assertEqual(entree["retry"], 1)
        self.assertEqual(store.queued_entry(reperes["manuel"])["held"], True)
        self.assertIsNotNone(entree["claimed_at"])
        self.assertEqual(
            {e["id"]: store.queued_raw(e["id"]) for e in store.outbox()}, brut
        )

    def test_flags_seen_answered_and_times_are_kept(self):
        reperes = self.creer("clear")
        avant = Store(compte(), mode="clear", base=self.base)
        avant.open()
        lus = [
            (m.uid, m.flags, m.seen_at, m.received_at, m.has_body)
            for m in avant.list_messages(reperes["inbox"])
        ]
        avant.close()
        self.convertir("encrypted")
        store = self.ouvrir()
        self.assertEqual(
            [
                (m.uid, m.flags, m.seen_at, m.received_at, m.has_body)
                for m in store.list_messages(reperes["inbox"])
            ],
            lus,
        )
        self.assertIn("\\Answered", lus[-1][1])

    def test_thread_links_are_translated(self):
        self.creer("clear")
        avant = Store(compte(), mode="clear", base=self.base)
        avant.open()
        delais = avant.stats_reply_delays()
        avant.close()
        self.assertTrue(delais)
        resultat = self.convertir("encrypted")
        store = self.ouvrir()
        self.assertEqual(store.stats_reply_delays(), delais)
        # La référence vers un message absent du cache est omise.
        self.assertEqual(resultat.dropped_hashes, 1)

    def test_the_cache_epoch_survives_with_a_new_check(self):
        reperes = self.creer("clear")
        self.convertir("encrypted")
        store = self.ouvrir()
        self.assertEqual(store.cache_epoch(), reperes["epoque"])
        self.assertEqual(len(store.rule_log_entries()), 4)

    def test_the_inscription_follows_the_conversion(self):
        self.creer("clear")
        self.convertir("encrypted")
        self.assertEqual(_probe_root(self.racine), "encrypted")
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        with self.assertRaises(Exception):
            Store(compte("clear"), secrets=self.coffre, base=self.base).open()

    def test_a_clear_target_gets_its_index_rebuilt(self):
        self.creer("encrypted")
        self.convertir("clear")
        store = self.ouvrir()
        self.assertTrue(store.search_is_indexed())
        self.assertEqual(
            sorted(m.subject for m in store.search("facture")),
            ["Question sur la facture", "Re: Question sur la facture"],
        )

    def test_progress_reports_rows_and_bodies(self):
        self.creer("clear")
        appels = []
        self.convertir("encrypted", progress=lambda *a: appels.append(a))
        self.assertEqual(appels[-2], ("rows", 13, 13))
        self.assertEqual(appels[-1], ("bodies", 2, 2))

    def test_a_v4_cache_with_last_error_converts(self):
        store = Store(
            compte(), mode="clear", secrets=self.coffre, base=self.base
        )
        store.open()
        remplir(store)
        rendre_v4(store)
        store.close()
        rouvert = Store(compte(), mode="clear", base=self.base)
        rouvert.open()
        avant = instantane(rouvert)
        rouvert.close()
        self.convertir("encrypted")
        store = self.ouvrir()
        colonnes = [
            r[1] for r in store._db().execute("PRAGMA table_info(outbox)")
        ]
        self.assertNotIn("last_error", colonnes)
        apres = instantane(store)
        for ligne in avant["outbox"]:
            ligne.pop("last_error")
        self.assertEqual(apres, avant)

    def test_meta_is_copied_without_overwriting_the_target_inscription(self):
        self.creer("clear")
        self.sql("INSERT INTO meta(key, value) VALUES('reglage_futur', '42')")
        self.convertir("encrypted")
        meta = dict(self.lire("SELECT key, value FROM meta"))
        self.assertEqual(meta["reglage_futur"], "42")
        self.assertEqual(meta["cache_mode"], "encrypted")

    def _cache_mele(self):
        """Un cache passé en chiffré par l'ancien menu : lignes `P0`,
        corps `.eml`, index, une ligne `E1` sous la clé du coffre, inscrit
        `encrypted`."""
        reperes = self.creer("clear")
        cle = new_key()
        self.coffre.set(
            compte().cache_key_ref(),
            __import__("base64").b64encode(cle).decode(),
        )
        self.sql(
            (
                "UPDATE messages SET sealed_snippet = ? WHERE uid = 2",
                (AesGcmCrypto(cle).seal(b"Un message sans Message-ID"),),
            ),
            "UPDATE meta SET value = 'encrypted' WHERE key = 'cache_mode'",
        )
        self.coffre.writes = 0
        return reperes, cle

    def test_a_mixed_encrypted_cache_can_be_resealed(self):
        """Les `.eml` de la période claire, que le cache chiffré ne lit
        plus, partent avec l'ancienne copie ; tout ce qu'il lit suit."""
        self._cache_mele()
        # Ouvert comme la conversion l'ouvre : hors d'elle, ce cache au
        # journal salé en clair est refusé (`CacheNeedsReseal`).
        mele = Store(
            compte(), secrets=self.coffre, base=self.base, lock_held=True
        )
        mele.open()
        avant = instantane(mele)
        mele.close()
        self.assertEqual(
            avant["corps"],
            {("INBOX", 1): None, ("INBOX", 2): None, ("Sent", 5): None},
        )
        resultat = self.convertir("encrypted")
        self.assertTrue(resultat.resealed)
        store = self.ouvrir()
        self.assertEqual(store.mode, "encrypted")
        self.assertFalse(_sealed_starts_with(store._db(), CLEAR_MAGIC))
        self.assertFalse(
            [p for p in fichiers(self.racine) if p.endswith(".eml")]
        )
        self.assertEqual(instantane(store), avant)
        store.close()
        with self.assertRaises(ConvertError) as ctx:
            self.convertir("encrypted")
        self.assertEqual(ctx.exception.reason, "same_mode")

    def test_a_mixed_cache_keeps_its_journal_and_epoch_once_resealed(self):
        """Un cache chiffré au journal salé en clair refuse de s'ouvrir
        (son premier `cache_epoch()` viderait le journal) ; rescellé, il
        s'ouvre, garde son époque et chaque ligne du journal."""
        reperes, _cle = self._cache_mele()
        lignes = self.lire("SELECT count(*) FROM rule_log")[0][0]
        self.assertGreater(lignes, 0)
        with self.assertRaises(CacheNeedsReseal):
            self.ouvrir()
        self.assertEqual(
            self.lire("SELECT count(*) FROM rule_log")[0][0], lignes
        )
        self.convertir("encrypted")
        store = self.ouvrir()
        self.assertEqual(store.cache_epoch(), reperes["epoque"])
        self.assertEqual(
            store._db().execute("SELECT count(*) FROM rule_log").fetchone()[0],
            lignes,
        )
        self.assertTrue(
            store.rule_log_seen(
                "regle-a", store.message_key("<question-1@example.org>", 7, 1)
            )
        )

    def test_on_committed_runs_once_swapping_is_durable_before_any_rename(
        self,
    ):
        self.creer("clear")
        vus = []

        def rappel(cible):
            etat = json.loads((self.ctl / "convert.json").read_text())
            vus.append((cible, etat["phase"], _probe_root(self.racine)))

        resultat = self.convertir("encrypted", on_committed=rappel)
        self.assertEqual(vus, [("encrypted", "swapping", "clear")])
        self.assertTrue(resultat.mode_saved)

    def test_a_failing_on_committed_does_not_stop_the_swap(self):
        self.creer("clear")

        def rappel(_cible):
            raise OSError(errno.EACCES, "accounts.json")

        with self.assertLogs("script.todo.mail.cache_convert", "ERROR"):
            resultat = self.convertir("encrypted", on_committed=rappel)
        self.assertFalse(resultat.mode_saved)
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        self.assert_ctl_vide()


class TestTranslation(ConvertCase):
    def test_a_journal_line_without_its_message_becomes_legacy(self):
        reperes = self.creer("clear")
        avant = Store(compte(), mode="clear", base=self.base)
        avant.open()
        depuis = reperes["now"] - 86400
        envois = avant.rule_log_recent_sends(depuis)
        avant.close()
        resultat = self.convertir("encrypted")
        self.assertEqual(resultat.legacy_keys, 1)
        store = self.ouvrir()
        self.assertEqual(store.rule_log_recent_sends(depuis), envois)
        cles = [
            r[0]
            for r in store._db().execute(
                "SELECT msg_key FROM rule_log WHERE id = 4"
            )
        ]
        self.assertTrue(cles[0].startswith(LEGACY_KEY_PREFIX))

    def test_already_legacy_keys_are_kept_and_not_recounted(self):
        self.creer("clear")
        self.convertir("encrypted")
        jeton = self.lire("SELECT msg_key FROM rule_log WHERE id = 4")[0][0]
        resultat = self.convertir("clear")
        self.assertEqual(resultat.legacy_keys, 0)
        self.assertEqual(
            self.lire("SELECT msg_key FROM rule_log WHERE id = 4")[0][0], jeton
        )

    def test_an_old_line_without_ref_is_recovered_from_its_cached_message(
        self,
    ):
        self.creer("clear")
        self.assertEqual(
            self.lire("SELECT sealed_msg_ref FROM rule_log WHERE id = 3"),
            [(None,)],
        )
        self.convertir("encrypted")
        store = self.ouvrir()
        ref = (
            store._db()
            .execute("SELECT sealed_msg_ref FROM rule_log WHERE id = 3")
            .fetchone()[0]
        )
        self.assertEqual(store._open(ref), "<question-1@example.org>")

    def test_an_outbox_entry_and_its_line_share_the_same_legacy_key(self):
        reperes = self.creer("clear")
        store = Store(compte(), mode="clear", base=self.base)
        store.open()
        entree = store.queue_message(
            b"From: x\r\n\r\nparti",
            DENIS,
            "Parti",
            kind="auto_reply",
            rule_id="regle-a",
            source_key=reperes["perdu"],
        )
        store.close()
        self.convertir("encrypted")
        cle_file = self.lire(
            "SELECT source_key FROM outbox WHERE id = ?", (entree,)
        )[0][0]
        cle_ligne = self.lire("SELECT msg_key FROM rule_log WHERE id = 4")[0][
            0
        ]
        self.assertTrue(cle_file.startswith(LEGACY_KEY_PREFIX))
        self.assertEqual(cle_file, cle_ligne)

    def test_hashes_of_a_mixed_cache_are_repaired(self):
        """Deux doublons d'`auto_sent`, un dans chaque sens : la ligne
        fusionnée garde le plus petit `at` et le `rule_id` non vide, d'où
        qu'ils viennent."""
        reperes, cle = self._cache_mele_avec_doublon()
        resultat = self.convertir("encrypted")
        self.assertEqual(resultat.merged_auto_sent, 2)
        store = self.ouvrir()

        def ligne(msgid):
            return [
                tuple(r)
                for r in store._db().execute(
                    "SELECT rule_id, at FROM auto_sent WHERE msgid_hash = ?",
                    (store._msgid_hash(msgid),),
                )
            ]

        now = reperes["now"]
        self.assertEqual(
            ligne("<envoi-regle@example.org>"), [("regle-a", now - 1700)]
        )
        self.assertEqual(
            ligne("<auto-tiers@example.org>"), [("regle-b", now - 9000)]
        )
        self.assertTrue(store.is_rule_send("<envoi-regle@example.org>"))
        self.assertTrue(
            store.rule_log_seen(
                "regle-a", store.message_key("<question-1@example.org>", 7, 1)
            )
        )
        self.assertEqual(len(store.stats_reply_delays()), 1)

    def _cache_mele_avec_doublon(self):
        reperes = self.creer("clear")
        cle = new_key()
        self.coffre.set(
            compte().cache_key_ref(),
            __import__("base64").b64encode(cle).decode(),
        )
        self.sql(
            (
                "INSERT INTO auto_sent(msgid_hash, rule_id, at)"
                " VALUES(?, '', ?)",
                (
                    salted_hash(cle, "<envoi-regle@example.org>"),
                    reperes["now"] - 100,
                ),
            ),
            (
                "INSERT INTO auto_sent(msgid_hash, rule_id, at)"
                " VALUES(?, 'regle-b', ?)",
                (
                    salted_hash(cle, "<auto-tiers@example.org>"),
                    reperes["now"] - 9000,
                ),
            ),
            (
                "UPDATE messages SET sealed_snippet = ? WHERE uid = 2",
                (AesGcmCrypto(cle).seal(b"scelle"),),
            ),
            "UPDATE meta SET value = 'encrypted' WHERE key = 'cache_mode'",
        )
        return reperes, cle

    def test_losses_are_announced_before_writing_and_can_be_declined(self):
        self.creer("clear")
        self.sql(
            (
                "INSERT INTO auto_sent(msgid_hash, rule_id, at)"
                " VALUES(?, 'regle-a', 1)",
                (salted_hash(b"clear", "<sans-preimage@example.org>"),),
            )
        )
        store = Store(compte(), mode="clear", base=self.base)
        store.open()
        store.purge_all()
        avant = instantane(store)
        store.close()
        self.coffre.writes = 0
        questions = []

        def refuse(journal, envois):
            questions.append((journal, envois))
            self.assertFalse((self.ctl / "convert.json").exists())
            self.assertFalse((self.ctl / "new").exists())
            return False

        with self.assertRaises(ConvertError) as ctx:
            self.convertir("encrypted", confirm_losses=refuse)
        self.assertEqual(ctx.exception.reason, "declined")
        self.assertEqual(str(ctx.exception), t("mail_cache_convert_declined"))
        # Après la purge, seules les lignes à préimage retrouvent leur clé :
        # la ligne sans préimage, et l'envoi inscrit sans la sienne.
        self.assertEqual(questions, [(1, 1)])
        self.assertFalse((self.ctl / "convert.json").exists())
        self.assertFalse((self.ctl / "new").exists())
        store = Store(compte(), mode="clear", base=self.base)
        store.open()
        self.assertEqual(instantane(store), avant)
        store.close()
        self.assertEqual(self.coffre.writes, 0)

    def test_an_unknown_target_hash_is_dropped_and_counted(self):
        self.creer("clear")
        store = Store(compte(), mode="clear", base=self.base)
        store.open()
        store.rule_log_claim(
            "regle-d",
            store.message_key("<question-1@example.org>", 7, 1),
            outcome="sent",
            at=1,
            target_hash="f" * 64,
        )
        store.close()
        resultat = self.convertir("encrypted")
        self.assertEqual(resultat.dropped_hashes, 2)
        self.assertEqual(
            self.lire(
                "SELECT target_hash FROM rule_log WHERE rule_id = 'regle-d'"
            ),
            [(None,)],
        )

    def test_an_orphan_body_of_the_other_suffix_is_not_carried(self):
        self.creer("clear")
        (self.racine / "INBOX" / "2.eml.enc").write_bytes(b"E1orphelin")
        resultat = self.convertir("encrypted")
        self.assertEqual(resultat.bodies, 2)
        self.assertFalse((self.racine / "INBOX" / "2.eml.enc").exists())
        self.assertTrue((self.racine / "INBOX" / "1.eml.enc").exists())

    def test_a_body_listed_but_missing_stays_missing(self):
        reperes = self.creer("clear")
        self.sql("UPDATE messages SET has_body = 1 WHERE uid = 2")
        self.convertir("encrypted")
        store = self.ouvrir()
        self.assertIsNone(store.read_body("INBOX", 2))
        deux = [m for m in store.list_messages(reperes["inbox"]) if m.uid == 2]
        self.assertTrue(deux[0].has_body)


class TestConvertRefusals(ConvertCase):
    def setUp(self):
        super().setUp()
        self.creer("clear")
        self.octets = (self.racine / "cache.db").read_bytes()
        self.coffre.writes = 0

    def assert_refus(self, raison, octets_intacts=True, **kw):
        with self.assertRaises(ConvertError) as ctx:
            self.convertir(kw.pop("target", "encrypted"), **kw)
        self.assertEqual(ctx.exception.reason, raison)
        self.assertFalse((self.ctl / "new").exists())
        self.assertFalse((self.ctl / "convert.json").exists())
        self.assertEqual(self.coffre.writes, 0)
        if octets_intacts:
            self.assertEqual(
                (self.racine / "cache.db").read_bytes(), self.octets
            )
        else:
            store = Store(compte(), base=self.base, secrets=self.coffre)
            store.open()
            self.assertEqual(instantane(store), self.avant)
            store.close()
        return ctx.exception

    def test_an_open_cache_refuses_the_conversion(self):
        store = Store(compte(), base=self.base)
        store.open()
        self.octets = (self.racine / "cache.db").read_bytes()
        try:
            exc = self.assert_refus("busy_open")
        finally:
            store.close()
        self.assertEqual(
            str(exc), t("mail_cache_convert_busy_open").format(account="perso")
        )

    def test_a_running_rules_pass_refuses_the_conversion(self):
        with file_lock(storage.lock_path("perso", self.base)) as tenu:
            self.assertTrue(tenu)
            self.assert_refus("busy_rules", rules_lock_wait=0)

    def test_no_cache_or_same_mode_is_refused(self):
        self.assert_refus("same_mode", target="clear")
        shutil.rmtree(self.racine)
        with self.assertRaises(ConvertError) as ctx:
            self.convertir("encrypted")
        self.assertEqual(ctx.exception.reason, "no_cache")
        self.assertFalse(self.racine.exists())

    def test_an_invalid_inscription_refuses_the_conversion(self):
        self.sql("UPDATE meta SET value = 'magique' WHERE key = 'cache_mode'")
        self.octets = (self.racine / "cache.db").read_bytes()
        exc = self.assert_refus("invalid_mode")
        self.assertEqual(
            str(exc),
            t("mail_err_cache_mode_invalid").format(
                account="perso", inscribed="'magique'"
            ),
        )

    def test_a_symlinked_or_foreign_root_is_refused(self):
        ailleurs = self.tmp / "ailleurs"
        os.rename(self.racine, ailleurs)
        self.racine.symlink_to(ailleurs)
        self.assert_refus("unsupported_root")
        self.racine.unlink()
        os.rename(ailleurs, self.racine)
        vrai = os.lstat
        ctl = self.ctl

        def faux(chemin, *a, **k):
            info = vrai(chemin, *a, **k)
            if Path(chemin) == ctl:
                valeurs = list(info)
                valeurs[2] += 1
                return os.stat_result(valeurs)
            return info

        with mock.patch.object(cache_convert.os, "lstat", faux):
            self.assert_refus("unsupported_root")

    def test_a_missing_source_key_refuses_and_writes_nothing_to_the_vault(
        self,
    ):
        self.convertir("encrypted")
        self.octets = (self.racine / "cache.db").read_bytes()
        vide = FauxCoffre()
        with self.assertRaises(ConvertError) as ctx:
            self.convertir("clear", secrets=vide)
        self.assertEqual(ctx.exception.reason, "no_key")
        self.assertEqual((vide.values, vide.writes), ({}, 0))
        self.assertEqual((self.racine / "cache.db").read_bytes(), self.octets)
        self.assertFalse((self.ctl / "convert.json").exists())

    def test_too_little_disk_space_refuses_before_writing(self):
        libre = shutil._ntuple_diskusage(10**9, 10**9, 5 * 1024 * 1024)
        with mock.patch.object(
            cache_convert.shutil, "disk_usage", return_value=libre
        ):
            exc = self.assert_refus("no_space")
        self.assertIn("5", str(exc))

    def test_a_full_disk_during_the_copy_cancels(self):
        def plein(*_a, **_k):
            raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(Store, "_write_body_file", plein):
            self.assert_refus("no_space", octets_intacts=False)

    def test_an_unreadable_row_cancels_and_leaves_the_cache(self):
        self.sql(
            (
                "UPDATE messages SET sealed_subject = ? WHERE uid = 2",
                (AesGcmCrypto(new_key()).seal(b"autre cle"),),
            )
        )
        self.octets = None
        with self.assertRaises(ConvertError) as ctx:
            self.convertir("encrypted")
        self.assertEqual(ctx.exception.reason, "unreadable")
        self.assertEqual(
            str(ctx.exception), t("mail_cache_convert_unreadable")
        )
        self.assertFalse((self.ctl / "new").exists())
        self.assertFalse((self.ctl / "convert.json").exists())
        self.assertEqual(inscribed_mode(compte(), self.base), "clear")
        self.assertEqual(self.coffre.writes, 0)

    def test_a_failed_verification_cancels_and_leaves_the_cache(self):
        vrai = Store._write_body_file
        ctl = self.ctl

        def altere(magasin, dossier, uid, brut):
            if ctl in magasin.root.parents:
                brut = brut + b" altere"
            return vrai(magasin, dossier, uid, brut)

        with mock.patch.object(Store, "_write_body_file", altere):
            exc = self.assert_refus("verify_failed", octets_intacts=False)
        self.assertEqual(str(exc), t("mail_cache_convert_verify_failed"))

    def test_a_later_auto_sent_time_fails_the_verification(self):
        """Un envoi inscrit dont la copie porterait un `at` plus récent
        que la source : la vérification refuse."""
        vrai = cache_convert._Copier.verify

        def verifie(copieur, target):
            copieur.dst._db().execute("UPDATE auto_sent SET at = at + 1")
            copieur.dst._db().commit()
            return vrai(copieur, target)

        with mock.patch.object(cache_convert._Copier, "verify", verifie):
            self.assert_refus("verify_failed", octets_intacts=False)

    def test_another_key_appearing_in_the_vault_cancels(self):
        """Une autre clé écrite au coffre pendant la copie : la copie,
        scellée par la nôtre, serait illisible ; rien n'est échangé."""
        autre = __import__("base64").b64encode(new_key()).decode()
        coffre = self.coffre
        vrai = FauxCoffre.update

        def concurrent(magasin, ref, change):
            magasin.values[ref] = autre
            return vrai(magasin, ref, change)

        with mock.patch.object(FauxCoffre, "update", concurrent):
            self.assert_refus("failed", octets_intacts=False)
        self.assertEqual(coffre.values[compte().cache_key_ref()], autre)

    def test_an_unreadable_cache_is_not_called_an_unknown_mode(self):
        with mock.patch.object(
            cache_convert, "inscribed_mode", return_value=PROBE_UNKNOWN
        ):
            exc = self.assert_refus("unreadable_cache")
        self.assertEqual(
            str(exc), t("mail_cache_unreadable").format(account="perso")
        )
        self.assertNotIn(PROBE_UNKNOWN, str(exc))

    def test_an_unknown_table_cancels_before_writing(self):
        self.sql("CREATE TABLE futur(x BLOB)")
        self.octets = (self.racine / "cache.db").read_bytes()
        exc = self.assert_refus("failed")
        self.assertEqual(
            str(exc), f"{t('mail_cache_convert_failed')} UnknownSchema"
        )

    def test_an_unknown_source_column_cancels_before_writing(self):
        self.sql("ALTER TABLE rule_log ADD COLUMN sealed_futur BLOB")
        self.octets = (self.racine / "cache.db").read_bytes()
        self.assert_refus("failed")

    def test_ctrl_c_while_building_cancels_and_reraises(self):
        def coupe(point):
            if point == "built":
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.convertir("encrypted", fault=coupe)
        self.assertFalse((self.ctl / "new").exists())
        self.assertFalse((self.ctl / "convert.json").exists())
        self.assertEqual(inscribed_mode(compte(), self.base), "clear")
        store = self.ouvrir()
        self.assertEqual(instantane(store), self.avant)

    def test_an_open_during_the_conversion_gets_cache_busy(self):
        vus = []

        def ouvre(point):
            if point == "built":
                try:
                    Store(compte(), base=self.base).open()
                except CacheBusy as exc:
                    vus.append(exc)

        self.convertir("encrypted", fault=ouvre)
        self.assertEqual(len(vus), 1)

    def test_a_failure_after_swapping_reports_incomplete(self):
        vrai = cache_convert.recover
        appels = []

        def reprise(*a, **k):
            appels.append(1)
            if len(appels) > 1:
                raise StoreError("reprise impossible")
            return vrai(*a, **k)

        def casse(point):
            if point == "moved_new":
                raise OSError(errno.EIO, "panne")

        with mock.patch.object(cache_convert, "recover", reprise):
            with self.assertRaises(ConvertError) as ctx:
                self.convertir("encrypted", fault=casse)
        self.assertEqual(ctx.exception.reason, "incomplete")
        self.assertEqual(
            str(ctx.exception),
            t("mail_cache_convert_incomplete").format(
                account="perso", target="encrypted"
            ),
        )

    def test_a_failure_after_swapping_is_finished_by_the_recovery(self):
        def casse(point):
            if point == "moved_old":
                raise OSError(errno.EIO, "panne")

        resultat = self.convertir("encrypted", fault=casse)
        self.assertEqual(resultat.target, "encrypted")
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        self.assert_ctl_vide()

    def test_ctrl_c_after_swapping_leaves_the_end_to_the_next_open(self):
        for point in ("erased", "moved_old"):
            with self.subTest(point=point):
                if inscribed_mode(compte(), self.base) != "clear":
                    self.convertir("clear")

                def coupe(p, point=point):
                    if p == point:
                        raise KeyboardInterrupt

                with self.assertRaises(ConvertError) as ctx:
                    self.convertir("encrypted", fault=coupe)
                self.assertEqual(ctx.exception.reason, "incomplete")
                store = self.ouvrir()
                self.assertEqual(store.mode, "encrypted")
                self.assertEqual(instantane(store), self.avant)
                store.close()
                self.assert_ctl_vide()


class TestCommitPoint(ConvertCase):
    """Le point de non-retour se lit sur le disque, pas dans le mode
    inscrit : `committed`, le rappel tardif de `on_committed`, et un
    rescellement (source = cible) dont l'échange est défait."""

    def setUp(self):
        super().setUp()
        self.rappels = []

    def rappel(self, cible):
        self.rappels.append(cible)

    def ecriture_etat(self, phase, avant_remplacement):
        """`_write_state` qui lève `OSError(EIO)` pour `phase` : avant
        tout remplacement, ou une fois `convert.json` remplacé (comme une
        synchronisation du dossier en échec)."""
        vrai = cache_convert._write_state

        def ecrit(ctl, p, *a, **k):
            if p == phase and avant_remplacement:
                raise OSError(errno.EIO, "panne")
            vrai(ctl, p, *a, **k)
            if p == phase:
                raise OSError(errno.EIO, "panne")

        return mock.patch.object(cache_convert, "_write_state", ecrit)

    def test_a_failure_once_swapping_is_written_still_settles_the_account(
        self,
    ):
        self.creer("clear")
        with self.ecriture_etat("swapping", avant_remplacement=False):
            resultat = self.convertir("encrypted", on_committed=self.rappel)
        self.assertEqual(self.rappels, ["encrypted"])
        self.assertTrue(resultat.mode_saved)
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        self.assert_ctl_vide()

    def test_a_late_on_committed_failure_is_reported(self):
        self.creer("clear")

        def refuse(_cible):
            raise OSError(errno.EACCES, "accounts.json")

        with (
            self.ecriture_etat("swapping", avant_remplacement=False),
            self.assertLogs("script.todo.mail.cache_convert", "ERROR"),
        ):
            resultat = self.convertir("encrypted", on_committed=refuse)
        self.assertFalse(resultat.mode_saved)
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")

    def test_a_failure_before_swapping_is_written_rolls_back(self):
        self.creer("clear")
        with self.ecriture_etat("swapping", avant_remplacement=True):
            with self.assertRaises(ConvertError) as ctx:
                self.convertir("encrypted", on_committed=self.rappel)
        self.assertFalse(ctx.exception.committed)
        self.assertEqual(ctx.exception.reason, "failed")
        self.assertEqual(self.rappels, [])
        self.assertEqual(inscribed_mode(compte(), self.base), "clear")
        self.assert_ctl_vide()
        self.assertEqual(instantane(self.ouvrir()), self.avant)

    def test_a_reseal_undone_before_swapping_is_not_a_success(self):
        """La source vaut la cible : relire le mode inscrit dirait le
        rescellement fait alors que la reprise l'a défait."""
        self.creer("clear")
        self.sql(
            "UPDATE meta SET value = 'encrypted' WHERE key = 'cache_mode'"
        )
        self.coffre.set(
            compte().cache_key_ref(),
            __import__("base64").b64encode(new_key()).decode(),
        )
        with self.ecriture_etat("swapping", avant_remplacement=True):
            with self.assertRaises(ConvertError) as ctx:
                self.convertir("encrypted", on_committed=self.rappel)
        self.assertFalse(ctx.exception.committed)
        self.assertEqual(self.rappels, [])
        self.assert_ctl_vide()
        with store_mod.probe_connection(self.racine / "cache.db") as conn:
            self.assertTrue(_sealed_starts_with(conn, CLEAR_MAGIC))

    def test_committed_follows_the_state_on_disk(self):
        for point, attendu in (("marked", True), ("moved_new", True)):
            with self.subTest(point=point):
                if inscribed_mode(compte(), self.base) is None:
                    self.creer("clear")
                elif inscribed_mode(compte(), self.base) != "clear":
                    self.convertir("clear")

                def coupe(p, point=point):
                    if p == point:
                        raise KeyboardInterrupt

                with self.assertRaises(ConvertError) as ctx:
                    self.convertir("encrypted", fault=coupe)
                self.assertIs(ctx.exception.committed, attendu)
                self.ouvrir().close()
        self.convertir("clear")
        vrai = cache_convert._write_state

        def coupe_apres(ctl, p, *a, **k):
            vrai(ctl, p, *a, **k)
            if p == "swapping":
                raise KeyboardInterrupt

        with mock.patch.object(cache_convert, "_write_state", coupe_apres):
            with self.assertRaises(ConvertError) as ctx:
                self.convertir("encrypted", on_committed=self.rappel)
        self.assertTrue(ctx.exception.committed)
        self.assertEqual(self.rappels, [])


class TestForeignWriters(ConvertCase):
    """Un processus qui écrit dans `cache.db` sans prendre le verrou
    d'usage (un client lancé avant la mise à jour) : il ne peut rien
    valider pendant la conversion, et une écriture en cours la refuse."""

    def setUp(self):
        super().setUp()
        self.creer("clear")
        self.etranger = sqlite3.connect(self.racine / "cache.db", timeout=0.05)
        self.addCleanup(self.etranger.close)

    def ecrire(self):
        try:
            self.etranger.execute(
                "UPDATE messages SET flags = 'x' WHERE uid = 1"
            )
            self.etranger.commit()
            return "validée"
        except sqlite3.OperationalError as exc:
            self.etranger.rollback()
            return str(exc)

    def test_a_foreign_write_is_refused_until_the_old_copy_is_gone(self):
        vus = {}

        def tente(point):
            if point in ("built", "moved_new"):
                vus[point] = self.ecrire()

        self.convertir("encrypted", fault=tente)
        self.assertEqual(
            vus,
            {"built": "database is locked", "moved_new": "database is locked"},
        )
        store = self.ouvrir()
        self.assertEqual(store.mode, "encrypted")
        self.assertEqual(instantane(store), self.avant)

    def test_a_write_in_progress_refuses_the_conversion(self):
        vrai = Store.open

        def ouvre_puis_ecrit(magasin):
            vrai(magasin)
            if magasin.root == self.racine:
                self.etranger.execute("BEGIN IMMEDIATE")

        with (
            mock.patch.object(store_mod, "STORE_BUSY_TIMEOUT_S", 0.05),
            mock.patch.object(Store, "open", ouvre_puis_ecrit),
        ):
            with self.assertRaises(ConvertError) as ctx:
                self.convertir("encrypted")
        self.etranger.rollback()
        self.assertEqual(ctx.exception.reason, "busy_open")
        self.assert_ctl_vide()
        self.assertEqual(instantane(self.ouvrir()), self.avant)

    def test_a_write_held_from_the_start_is_busy_not_failed(self):
        self.etranger.execute("BEGIN IMMEDIATE")
        with mock.patch.object(store_mod, "STORE_BUSY_TIMEOUT_S", 0.05):
            with self.assertRaises(ConvertError) as ctx:
                self.convertir("encrypted")
        self.etranger.rollback()
        self.assertEqual(ctx.exception.reason, "busy_open")
        self.assert_ctl_vide()


def faire_copie(parent: Path, mode: str, coffre) -> Path:
    """Un cache rempli du mode donné sous `parent/perso`, ouvert sans
    verrou ni reprise."""
    parent.mkdir(parents=True, exist_ok=True)
    store = Store(
        compte(), mode=mode, secrets=coffre, base=parent, lock_held=True
    )
    store.open()
    remplir(store)
    store.close()
    return parent / "perso"


class TestRecovery(ConvertCase):
    def fabriquer(self, r=None, o=None, n=None, phase=None):
        """R, O et N : None (absent) ou le mode de la copie."""
        if r:
            faire_copie(self.base, r, self.coffre)
        self.ctl.mkdir(parents=True, exist_ok=True)
        if o:
            faire_copie(self.ctl / "old", o, self.coffre)
        if n:
            faire_copie(self.ctl / "new", n, self.coffre)
        if phase:
            (self.ctl / "convert.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "phase": phase,
                        "source": "clear",
                        "target": "encrypted",
                        "started_at": 1,
                    }
                )
            )

    def assert_issue(self, attendu, mode):
        self.assertEqual(recover("perso", self.base), attendu)
        self.assertEqual(_probe_root(self.racine), mode)
        self.assert_ctl_vide()

    def assert_incoherent(self):
        avant = fichiers(self.base)
        with self.assertRaises(StoreError) as ctx:
            recover("perso", self.base)
        self.assertEqual(
            str(ctx.exception),
            t("mail_err_cache_convert_inconsistent").format(path=self.ctl),
        )
        self.assertEqual(fichiers(self.base), avant)

    def test_root_only_is_left_alone(self):
        self.fabriquer(r="clear", phase="building")
        self.assert_issue("none", "clear")

    def test_root_and_new_while_building_rolls_back(self):
        self.fabriquer(r="clear", n="encrypted", phase="building")
        self.assert_issue("rolled_back", "clear")

    def test_root_and_new_while_swapping_rolls_forward(self):
        self.fabriquer(r="clear", n="encrypted", phase="swapping")
        self.assert_issue("rolled_forward", "encrypted")

    def test_root_and_new_while_cleaning_is_refused_untouched(self):
        self.fabriquer(r="clear", n="encrypted", phase="cleaning")
        self.assert_incoherent()

    def test_only_old_and_new_while_swapping_rolls_forward(self):
        for phase in ("swapping", "cleaning"):
            with self.subTest(phase=phase):
                self.fabriquer(o="clear", n="encrypted", phase=phase)
                self.assert_issue("rolled_forward", "encrypted")
                shutil.rmtree(self.racine)

    def test_only_old_and_new_while_building_restores_the_old(self):
        self.fabriquer(o="clear", n="encrypted", phase="building")
        self.assert_issue("rolled_back", "clear")

    def test_only_old_is_restored(self):
        self.fabriquer(o="clear", phase="swapping")
        self.assert_issue("rolled_back", "clear")

    def test_root_and_old_after_the_swap_is_cleaned(self):
        self.fabriquer(r="encrypted", o="clear", phase="cleaning")
        self.assert_issue("cleaned", "encrypted")

    def test_root_and_old_while_building_is_refused_untouched(self):
        self.fabriquer(r="encrypted", o="clear", phase="building")
        self.assert_incoherent()

    def test_only_new_while_swapping_rolls_forward(self):
        self.fabriquer(n="encrypted", phase="swapping")
        self.assert_issue("rolled_forward", "encrypted")

    def test_only_new_while_building_is_refused_untouched(self):
        for phase in ("building", "cleaning", None):
            with self.subTest(phase=phase):
                self.fabriquer(n="encrypted", phase=phase)
                self.assert_incoherent()
                shutil.rmtree(self.ctl)

    def test_all_three_are_refused_untouched(self):
        self.fabriquer(r="clear", o="clear", n="encrypted", phase="swapping")
        self.assert_incoherent()

    def test_leftovers_without_state_roll_back(self):
        self.fabriquer(r="clear", n="encrypted")
        self.assert_issue("rolled_back", "clear")

    def test_a_state_without_copies_is_cleared(self):
        self.fabriquer(r="clear", phase="swapping")
        self.assertEqual(recover("perso", self.base), "none")
        self.assertFalse((self.ctl / "convert.json").exists())

    def test_the_state_is_removed_last(self):
        self.fabriquer(r="clear", n="encrypted", phase="swapping")
        vrai = os.unlink
        vus = []

        def surveille(chemin, *a, **k):
            if str(chemin).endswith("convert.json"):
                vus.append(
                    (
                        os.path.lexists(self.ctl / "old"),
                        os.path.lexists(self.ctl / "new"),
                    )
                )
            return vrai(chemin, *a, **k)

        with mock.patch.object(cache_convert.os, "unlink", surveille):
            recover("perso", self.base)
        self.assertEqual(vus, [(False, False)])

    def test_open_runs_the_recovery_first(self):
        self.fabriquer(o="clear", n="encrypted", phase="swapping")
        store = self.ouvrir()
        self.assertEqual(store.mode, "encrypted")
        self.assert_ctl_vide()

    def test_open_runs_the_recovery_on_leftovers_without_state(self):
        self.fabriquer(r="clear", n="encrypted")
        store = self.ouvrir()
        self.assertEqual(store.mode, "clear")
        self.assert_ctl_vide()

    def test_open_continues_on_the_root_when_recovery_fails(self):
        self.fabriquer(r="clear", o="clear", n="encrypted", phase="swapping")
        restes = {k: v for k, v in fichiers(self.ctl).items() if k != "lock"}
        with self.assertLogs("script.todo.mail.store", logging.WARNING):
            store = self.ouvrir()
        self.assertEqual(store.mode, "clear")
        self.assertEqual(
            {k: v for k, v in fichiers(self.ctl).items() if k != "lock"},
            restes,
        )

    def test_open_never_recreates_an_absent_root_next_to_copies(self):
        self.fabriquer(n="encrypted", phase="building")
        neuve = fichiers(self.ctl / "new")
        with self.assertRaises(StoreError) as ctx:
            Store(compte(), secrets=self.coffre, base=self.base).open()
        self.assertNotIsInstance(ctx.exception, CacheBusy)
        self.assertFalse(self.racine.exists())
        self.assertEqual(fichiers(self.ctl / "new"), neuve)

    def test_open_never_creates_a_root_while_a_swap_is_held(self):
        """Racine absente entre les deux renommages et l'exclusif refusé :
        `CacheBusy`, sans créer de racine vide à côté des copies."""
        import contextlib

        from script.todo.mail import store as store_mod

        self.fabriquer(o="clear", n="encrypted", phase="swapping")

        @contextlib.contextmanager
        def refuse(*_a, **_k):
            yield False

        with mock.patch.object(store_mod, "cache_exclusive", refuse):
            with self.assertRaises(CacheBusy):
                Store(compte(), secrets=self.coffre, base=self.base).open()
        self.assertFalse(self.racine.exists())

    def test_open_refuses_when_the_recovery_leaves_no_root(self):
        self.fabriquer(o="clear", n="encrypted", phase="swapping")
        with mock.patch.object(cache_convert, "recover", return_value="none"):
            with self.assertRaises(StoreError) as ctx:
                Store(compte(), secrets=self.coffre, base=self.base).open()
        self.assertNotIsInstance(ctx.exception, CacheBusy)
        self.assertEqual(
            str(ctx.exception),
            t("mail_err_cache_convert_inconsistent").format(path=self.ctl),
        )
        self.assertFalse(self.racine.exists())

    def test_inscribed_mode_announces_the_target_of_a_pending_swap(self):
        self.fabriquer(o="clear", n="encrypted", phase="swapping")
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        shutil.rmtree(self.ctl)
        self.fabriquer(r="clear", n="encrypted", phase="swapping")
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")

    def test_open_skips_recovery_while_someone_holds_the_cache(self):
        self.fabriquer(r="clear")
        tenu = self.ouvrir()
        self.fabriquer(n="encrypted", phase="building")
        neuve = fichiers(self.ctl / "new")
        second = self.ouvrir()
        self.assertEqual(second.mode, "clear")
        self.assertEqual(fichiers(self.ctl / "new"), neuve)
        self.assertIsNotNone(tenu._conn)


# Le fils : convertit le compte relu d'`accounts.json`, règle le compte
# comme le menu au point de non-retour, et meurt au point demandé.
_FILS = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[5])
from mail_cache_fixtures import FauxCoffre
from script.todo.mail import accounts as mail_accounts
from script.todo.mail.cache_convert import convert_cache
base, comptes = Path(sys.argv[1]), Path(sys.argv[2])
coffre, point = sys.argv[3], sys.argv[4]
liste = mail_accounts.load(comptes)
compte = liste[0]

def regle(cible):
    compte.cache_mode = cible
    mail_accounts.save(liste, comptes)

def meurt(p):
    if p == point:
        os._exit(9)

convert_cache(compte, "encrypted", secrets=FauxCoffre(Path(coffre)), base=base,
              on_committed=regle, fault=meurt)
os._exit(0)
"""


class TestKilledConversion(ConvertCase):
    def tuer_a(self, point):
        comptes = self.tmp / "accounts.json"
        coffre = FauxCoffre(self.tmp / "coffre.json")
        acc = compte("clear")
        mail_accounts.save([acc], comptes)
        store = Store(acc, secrets=coffre, base=self.base)
        store.open()
        remplir(store)
        avant = instantane(store)
        store.close()
        racine_depot = Path(__file__).resolve().parents[1]
        fini = subprocess.run(
            [
                sys.executable,
                "-c",
                _FILS,
                str(self.base),
                str(comptes),
                str(self.tmp / "coffre.json"),
                point,
                str(Path(__file__).resolve().parent),
            ],
            cwd=racine_depot,
            env=dict(
                os.environ, HOME=str(self.home), PYTHONPATH=str(racine_depot)
            ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(fini.returncode, 9, fini.stderr)
        relu = mail_accounts.load(comptes)[0]
        store = Store(
            relu, secrets=FauxCoffre(self.tmp / "coffre.json"), base=self.base
        )
        store.open()
        self.addCleanup(store.close)
        self.assertEqual(instantane(store), avant)
        self.assertEqual(
            sorted(os.listdir(self.base)),
            sorted([".cache_ctl", ".rules", "perso"]),
        )
        self.assert_ctl_vide()
        return relu, store

    def test_killed_once_built_keeps_the_old_cache(self):
        relu, store = self.tuer_a("built")
        self.assertEqual((relu.cache_mode, store.mode), ("clear", "clear"))

    def test_killed_once_marked_ends_converted(self):
        relu, store = self.tuer_a("marked")
        self.assertEqual(
            (relu.cache_mode, store.mode), ("encrypted", "encrypted")
        )

    def test_killed_between_renames_ends_converted(self):
        relu, store = self.tuer_a("moved_old")
        self.assertEqual(
            (relu.cache_mode, store.mode), ("encrypted", "encrypted")
        )

    def test_killed_before_erasing_ends_converted_without_the_old_copy(self):
        relu, store = self.tuer_a("moved_new")
        self.assertEqual(
            (relu.cache_mode, store.mode), ("encrypted", "encrypted")
        )
        self.assertFalse((self.ctl / "old").exists())


class TestSecureErase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_files_are_zeroed_before_removal(self):
        dossier = self.tmp / "copie" / "INBOX"
        dossier.mkdir(parents=True)
        (dossier / "1.eml").write_bytes(b"Corps en clair" * 100)
        (dossier.parent / "cache.db").write_bytes(b"base" * 10)
        vrai = os.unlink
        lus = {}

        def surveille(chemin, *a, **k):
            lus[os.path.basename(chemin)] = Path(chemin).read_bytes()
            return vrai(chemin, *a, **k)

        with mock.patch.object(cache_convert.os, "unlink", surveille):
            secure_erase(self.tmp / "copie")
        self.assertEqual(lus["1.eml"], bytes(1400))
        self.assertEqual(lus["cache.db"], bytes(40))
        self.assertFalse((self.tmp / "copie").exists())

    def test_symlinks_are_removed_not_followed(self):
        cible = self.tmp / "cible.txt"
        cible.write_bytes(b"intact")
        dossier = self.tmp / "copie"
        dossier.mkdir()
        (dossier / "lien").symlink_to(cible)
        (dossier / "lien_dossier").symlink_to(self.tmp)
        secure_erase(dossier)
        self.assertEqual(cible.read_bytes(), b"intact")
        self.assertFalse(dossier.exists())

    def test_a_hard_linked_file_is_unlinked_not_zeroed(self):
        dehors = self.tmp / "dehors.eml"
        dehors.write_bytes(b"autre nom")
        dossier = self.tmp / "copie"
        dossier.mkdir()
        os.link(dehors, dossier / "1.eml")
        secure_erase(dossier)
        self.assertEqual(dehors.read_bytes(), b"autre nom")
        self.assertFalse(dossier.exists())

    def test_a_write_failure_falls_back_to_unlink(self):
        fichier = self.tmp / "1.eml"
        fichier.write_bytes(b"clair")

        def plein(*_a, **_k):
            raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(cache_convert.os, "write", plein):
            with self.assertLogs(
                "script.todo.mail.cache_convert", "WARNING"
            ) as logs:
                secure_erase(fichier)
        self.assertFalse(fichier.exists())
        self.assertEqual(len(logs.records), 1)
        self.assertNotIn("clair", logs.output[0])

    def test_a_missing_path_is_fine(self):
        secure_erase(self.tmp / "absent")


class TestEngineAfterConversion(EngineCase):
    def setUp(self):
        super().setUp()
        self.coffre = FauxCoffre()

    def convertir(self):
        """Ferme le cache, le convertit en chiffré, puis rebranche le cache
        neuf partout où la fixture le référence."""
        self.store.close()
        convert_cache(
            self.account, "encrypted", secrets=self.coffre, base=self.base
        )
        self.store = Store(
            self.account, mode="encrypted", secrets=self.coffre, base=self.base
        )
        self.store.open()
        self.syncer = Syncer(self.store, self.imap)
        self.session = Session(
            self.account, self.store, self.syncer, password="x"
        )

    def test_a_handled_message_coming_back_gets_no_second_reply(self):
        self.regle()
        self.imap.recevoir(1)
        self.assertEqual(self.passe().sent, 1)
        self.convertir()
        self.imap.recevoir(2, frm=BRUNO, msgid="<1@example.net>")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(len(self.envois), 1)

    def test_no_cache_rebuilt_hold_after_a_conversion(self):
        self.regle(throttle_minutes=60)
        self.passe()
        self.convertir()
        self.horloge.instant += HOUR // 60
        self.imap.recevoir(1, frm=BRUNO, internaldate=self.horloge() - 5)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertNotIn(t("mail_rules_cache_rebuilt"), bilan.warnings)


if __name__ == "__main__":
    unittest.main()
