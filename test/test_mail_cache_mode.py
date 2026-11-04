#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mode inscrit dans le cache : demande, inscription, détection d'un
cache ancien, refus d'une ouverture dans un autre mode, verrou d'usage et
préimages scellées.

Tout vit sous un dossier temporaire, `HOME` compris : le lanceur de tests
ne l'isole pas, et une sonde sans base lirait sinon le vrai dossier du
compte. Les coffres sont des doubles en mémoire."""

import base64
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mail_cache_fixtures import CAROLE, COMPTE, FauxCoffre, fichiers
from test_mail_rules_engine import EngineCase
from test_mail_store_v6 import V5_ROWS, V5_SQL

from script.todo.mail import errors
from script.todo.mail import store as store_mod
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import AesGcmCrypto, build_crypto, new_key
from script.todo.mail.store import (
    CACHE_CTL_DIRNAME,
    HASHED_COLUMNS,
    LEGACY_SOURCE_COLUMNS,
    PROBE_UNKNOWN,
    SEALED_COLUMNS,
    CacheBusy,
    CacheKeyMissing,
    CacheModeInvalid,
    CacheModeMismatch,
    MessageMeta,
    Store,
    StoreError,
    _probe_root,
    cache_exclusive,
    inscribed_mode,
    mode_request,
    recovery_plan,
    resolve_mode,
)
from script.todo.todo_i18n import t


def compte(nom="perso", mode=None):
    acc = account_from_preset(nom, COMPTE, "generic")
    acc.cache_mode = mode
    return acc


def message(uid, msgid=None, subject="Question"):
    return MessageMeta(
        uid=uid,
        date=1000 + uid,
        size=10,
        flags="",
        msgid=f"<{uid}@example.org>" if msgid is None else msgid,
        frm=CAROLE,
        to=COMPTE,
        subject=subject,
        snippet="Bonjour",
    )


def sans_preference(_cle, defaut=None):
    """Des préférences sans `mail_cache_mode` : rend le défaut reçu."""
    return defaut


def ecrire_etat(
    base: Path, nom: str, phase: str, source="clear", target="encrypted"
):
    ctl = base / CACHE_CTL_DIRNAME / nom
    ctl.mkdir(parents=True, exist_ok=True)
    (ctl / "convert.json").write_text(
        json.dumps(
            {
                "version": 1,
                "phase": phase,
                "source": source,
                "target": target,
                "started_at": 1,
            }
        )
    )


class CacheCase(unittest.TestCase):
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

    def tearDown(self):
        self._tmp.cleanup()

    def ouvrir(self, acc, mode=None, coffre=None, key=None, base=None):
        store = Store(
            acc,
            mode=mode,
            key=key,
            secrets=self.coffre if coffre is None else coffre,
            base=self.base if base is None else base,
        )
        store.open()
        self.addCleanup(store.close)
        return store

    def cache(self, mode, nom="perso", lignes=True):
        """Un cache du mode donné, rempli de deux messages et d'un corps,
        puis fermé."""
        store = self.ouvrir(compte(nom), mode=mode)
        if lignes:
            dossier = store.upsert_folder("INBOX", "Boîte", "inbox", 3)
            store.upsert_messages(dossier, [message(1), message(2)])
            store.write_body("INBOX", 1, b"Corps du premier message")
        store.close()
        return self.base / nom

    def desinscrire(self, racine: Path, sql: str = "") -> None:
        """Retire l'inscription : le cache redevient « ancien »."""
        conn = sqlite3.connect(racine / "cache.db")
        conn.execute("DELETE FROM meta WHERE key = 'cache_mode'")
        if sql:
            conn.executescript(sql)
        conn.commit()
        conn.close()

    def inscription(self, racine: Path):
        conn = sqlite3.connect(racine / "cache.db")
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'cache_mode'"
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def inscrire(self, racine: Path, valeur: str) -> None:
        conn = sqlite3.connect(racine / "cache.db")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('cache_mode', ?)",
            (valeur,),
        )
        conn.commit()
        conn.close()

    def ecrire_prefs(self, texte: str) -> None:
        dossier = self.home / ".erplibre"
        dossier.mkdir(exist_ok=True)
        (dossier / "todo_prefs.json").write_text(texte)


class TestModeRequest(unittest.TestCase):
    def test_the_account_mode_is_a_request(self):
        acc = compte(mode="encrypted")
        self.assertEqual(
            mode_request(acc, lambda k, d=None: "clear"), "encrypted"
        )

    def test_a_valid_general_mode_is_a_request(self):
        self.assertEqual(
            mode_request(compte(), lambda k, d=None: "ephemeral"), "ephemeral"
        )

    def test_an_absent_or_unknown_general_mode_is_no_request(self):
        for valeur in ("", "magique"):
            with self.subTest(valeur=valeur):
                self.assertIsNone(
                    mode_request(compte(), lambda k, d=None, v=valeur: v)
                )

    def test_prefs_are_read_with_an_empty_default(self):
        """`todo_prefs.get` rendrait son propre défaut (`clear`) pour une
        clé absente : lue ainsi, une préférence absente serait une
        demande."""
        recus = []

        def double(cle, defaut=None):
            recus.append(defaut)
            return defaut

        self.assertIsNone(mode_request(compte(), double))
        self.assertEqual(recus, [""])
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home}):
                self.assertIsNone(mode_request(compte()))


class TestResolveMode(CacheCase):
    def test_without_request_the_inscribed_mode_wins(self):
        self.cache("encrypted")
        self.assertEqual(
            resolve_mode(compte(), sans_preference, base=self.base),
            "encrypted",
        )

    def test_without_request_nor_cache_the_default_is_clear(self):
        self.assertEqual(
            resolve_mode(compte(), sans_preference, base=self.base), "clear"
        )

    def test_an_unreadable_prefs_file_falls_back_on_the_cache_not_on_clear(
        self,
    ):
        acc = compte(mode="encrypted")
        store = Store(acc, secrets=self.coffre)
        store.open()
        store.close()
        self.assertTrue(
            (self.home / ".erplibre" / "mail" / "perso" / "cache.db").exists()
        )
        self.ecrire_prefs("{pas du json")
        self.assertEqual(resolve_mode(compte()), "encrypted")
        rouvert = Store(compte(), secrets=self.coffre)
        rouvert.open()
        self.addCleanup(rouvert.close)
        self.assertEqual(rouvert.mode, "encrypted")

    def test_resolving_creates_nothing(self):
        absente = self.tmp / "absente"
        resolve_mode(compte(), sans_preference, base=absente)
        inscribed_mode(compte(), absente)
        self.assertFalse(absente.exists())
        vide = self.tmp / "vide"
        vide.mkdir()
        resolve_mode(compte(), sans_preference, base=vide)
        self.assertEqual(list(vide.iterdir()), [])

    def test_an_invalid_inscription_is_never_resolved(self):
        shm = self.tmp / "shm"
        for i, valeur in enumerate(("magique", "ephemeral")):
            with self.subTest(valeur=valeur):
                nom = f"compte{i}"
                racine = self.cache("clear", nom=nom)
                self.inscrire(racine, valeur)
                acc = compte(nom)
                self.assertEqual(
                    resolve_mode(acc, sans_preference, base=self.base), "clear"
                )
                with mock.patch.object(
                    store_mod, "ephemeral_base", return_value=shm
                ):
                    store = Store(acc, secrets=self.coffre, base=self.base)
                    with self.assertRaises(CacheModeInvalid) as ctx:
                        store.open()
                self.assertEqual(ctx.exception.inscribed, valeur)
                self.assertFalse(shm.exists())

    def test_resolve_mode_never_raises_on_a_hostile_control_dir(self):
        self.cache("encrypted")
        ailleurs = self.tmp / "ailleurs"
        ailleurs.mkdir()
        ctl = self.base / CACHE_CTL_DIRNAME
        if ctl.exists():
            import shutil

            shutil.rmtree(ctl)
        ctl.symlink_to(ailleurs)
        self.assertEqual(
            resolve_mode(compte(), sans_preference, base=self.base),
            "encrypted",
        )
        ctl.unlink()
        ctl.mkdir()
        (ctl / "perso").mkdir()
        os.chmod(ctl, 0)
        try:
            self.assertEqual(
                resolve_mode(compte(), sans_preference, base=self.base),
                "encrypted",
            )
        finally:
            os.chmod(ctl, 0o700)


class TestProbe(CacheCase):
    def test_account_names_with_uri_characters_are_probed_in_place(self):
        noms = ("a?b", "c#d", "e%41f")
        for nom in noms:
            self.cache("encrypted", nom=nom)
        avant = sorted(p.name for p in self.base.iterdir())
        for nom in noms:
            with self.subTest(nom=nom):
                self.assertEqual(_probe_root(self.base / nom), "encrypted")
                self.assertEqual(
                    inscribed_mode(compte(nom), self.base), "encrypted"
                )
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), avant)
        for parasite in ("a", "c", "e", "eAf"):
            self.assertFalse((self.base / parasite).exists())

    def test_a_hot_journal_does_not_hide_the_inscription(self):
        racine = self.cache("encrypted")
        code = (
            "import os, sqlite3, sys\n"
            "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
            "c.execute('PRAGMA cache_size=1')\n"
            "c.execute('BEGIN IMMEDIATE')\n"
            "c.execute('CREATE TABLE lest(x BLOB)')\n"
            "for i in range(300):\n"
            "    c.execute('INSERT INTO lest VALUES(?)', (os.urandom(4000),))\n"
            "c.execute(\"UPDATE meta SET value = 'clear'"
            " WHERE key = 'cache_mode'\")\n"
            "os._exit(9)\n"
        )
        fini = subprocess.run(
            [sys.executable, "-c", code, str(racine / "cache.db")]
        )
        self.assertEqual(fini.returncode, 9)
        self.assertTrue((racine / "cache.db-journal").exists())
        self.assertEqual(_probe_root(racine), "encrypted")
        self.assertEqual(
            resolve_mode(compte(), sans_preference, base=self.base),
            "encrypted",
        )

    def test_an_unreadable_cache_is_unknown_not_absent(self):
        racine = self.base / "perso"
        self.assertIsNone(_probe_root(racine))
        self.assertIsNone(inscribed_mode(compte(), self.base))
        racine.mkdir(parents=True)
        (racine / "cache.db").write_bytes(os.urandom(16))
        self.assertEqual(_probe_root(racine), PROBE_UNKNOWN)
        self.assertEqual(inscribed_mode(compte(), self.base), PROBE_UNKNOWN)

    def test_the_recovery_plan_matches_the_table(self):
        lignes = [
            # (R, O, N, phase, action, issue)
            (1, 0, 0, "building", "none", "none"),
            (1, 0, 0, "swapping", "none", "none"),
            (1, 0, 1, "building", "erase_new", "rolled_back"),
            (1, 0, 1, None, "erase_new", "rolled_back"),
            (1, 0, 1, "swapping", "forward", "rolled_forward"),
            (1, 0, 1, "cleaning", "inconsistent", "inconsistent"),
            (0, 1, 1, "swapping", "forward", "rolled_forward"),
            (0, 1, 1, "cleaning", "forward", "rolled_forward"),
            (0, 1, 1, "building", "restore_old", "rolled_back"),
            (0, 1, 1, "unreadable", "restore_old", "rolled_back"),
            (0, 1, 0, "swapping", "restore_old", "rolled_back"),
            (0, 1, 0, None, "restore_old", "rolled_back"),
            (1, 1, 0, "swapping", "erase_old", "cleaned"),
            (1, 1, 0, "cleaning", "erase_old", "cleaned"),
            (1, 1, 0, "building", "inconsistent", "inconsistent"),
            (1, 1, 0, None, "inconsistent", "inconsistent"),
            (0, 0, 1, "swapping", "forward", "rolled_forward"),
            (0, 0, 1, "building", "inconsistent", "inconsistent"),
            (0, 0, 1, "cleaning", "inconsistent", "inconsistent"),
            (0, 0, 1, None, "inconsistent", "inconsistent"),
            (1, 1, 1, "swapping", "inconsistent", "inconsistent"),
            (1, 1, 1, "building", "inconsistent", "inconsistent"),
            (0, 0, 0, "swapping", "none", "none"),
            (0, 0, 0, None, "none", "none"),
        ]
        for r, o, n, phase, action, issue in lignes:
            with self.subTest(r=r, o=o, n=n, phase=phase):
                self.assertEqual(
                    recovery_plan(bool(r), bool(o), bool(n), phase),
                    (action, issue),
                )

    def test_inscribed_mode_follows_the_recovery_table(self):
        self.cache("clear")
        ctl = self.base / CACHE_CTL_DIRNAME / "perso"
        (ctl / "new").mkdir(parents=True)
        neuve = Store(
            compte(),
            mode="encrypted",
            secrets=self.coffre,
            base=ctl / "new",
            lock_held=True,
        )
        neuve.open()
        neuve.close()
        ecrire_etat(self.base, "perso", "swapping")
        # R ✓ O ✗ N ✓ swapping : la neuve sera la racine.
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")
        # R ✗ O ✓ N ✗ : l'ancienne revient.
        (ctl / "old").mkdir()
        os.rename(self.base / "perso", ctl / "old" / "perso")
        import shutil

        shutil.rmtree(ctl / "new")
        self.assertEqual(inscribed_mode(compte(), self.base), "clear")
        # R ✓ O ✓ N ✗ cleaning : la racine reste. Elle est créée sans
        # verrou ni reprise, qui achèverait l'échange.
        racine = Store(
            compte(),
            mode="encrypted",
            secrets=self.coffre,
            base=self.base,
            lock_held=True,
        )
        racine.open()
        racine.close()
        ecrire_etat(self.base, "perso", "cleaning")
        self.assertEqual(inscribed_mode(compte(), self.base), "encrypted")


class TestInscription(CacheCase):
    def test_a_new_cache_is_inscribed_at_creation(self):
        for mode in ("clear", "encrypted"):
            with self.subTest(mode=mode):
                racine = self.cache(mode, nom=f"neuf-{mode}", lignes=False)
                self.assertEqual(self.inscription(racine), mode)
        store = self.ouvrir(
            compte(mode="ephemeral"), base=self.tmp / "shm", key=None
        )
        valeur = (
            store._db()
            .execute("SELECT value FROM meta WHERE key = 'cache_mode'")
            .fetchone()[0]
        )
        self.assertEqual(valeur, "ephemeral")
        store.cleanup()

    def test_an_old_clear_cache_is_inscribed_from_its_content(self):
        racine = self.cache("clear")
        self.desinscrire(racine)
        self.assertEqual(_probe_root(racine), "clear")
        store = self.ouvrir(compte())
        self.assertEqual(store.mode, "clear")
        store.close()
        self.assertEqual(self.inscription(racine), "clear")

    def test_an_old_encrypted_cache_is_inscribed_from_its_content(self):
        racine = self.cache("encrypted")
        self.desinscrire(racine)
        self.assertEqual(_probe_root(racine), "encrypted")
        store = self.ouvrir(compte())
        self.assertEqual(store.mode, "encrypted")
        self.assertEqual(
            [m.subject for m in store.list_messages(1)],
            ["Question", "Question"],
        )
        store.close()
        self.assertEqual(self.inscription(racine), "encrypted")

    def test_encrypted_evidence_wins_over_clear_rows(self):
        racine = self.cache("clear")
        scelle = AesGcmCrypto(new_key()).seal(b"secret")
        self.desinscrire(racine)
        conn = sqlite3.connect(racine / "cache.db")
        conn.execute(
            "UPDATE messages SET sealed_subject = ? WHERE uid = 2", (scelle,)
        )
        conn.commit()
        conn.close()
        self.assertEqual(_probe_root(racine), "encrypted")
        with self.assertRaises(CacheModeMismatch):
            Store(
                compte(mode="clear"), secrets=self.coffre, base=self.base
            ).open()

    def test_a_sealed_body_file_alone_marks_the_cache_encrypted(self):
        racine = self.cache("encrypted", lignes=False)
        self.desinscrire(racine)
        self.assertIsNone(_probe_root(racine))
        (racine / "INBOX").mkdir()
        (racine / "INBOX" / "1.eml.enc").write_bytes(b"E1...")
        self.assertEqual(_probe_root(racine), "encrypted")

    def test_a_key_salted_epoch_check_marks_the_cache_encrypted(self):
        store = self.ouvrir(compte(), mode="encrypted")
        store.cache_epoch()
        store.close()
        racine = self.base / "perso"
        self.desinscrire(racine)
        self.assertEqual(_probe_root(racine), "encrypted")

    def test_a_clear_index_or_clear_epoch_check_marks_the_cache_clear(self):
        racine = self.cache("clear", lignes=False)
        self.desinscrire(racine)
        # L'index seul.
        self.assertEqual(_probe_root(racine), "clear")
        store = self.ouvrir(compte(), mode="clear")
        store.cache_epoch()
        store.close()
        self.desinscrire(racine)
        conn = sqlite3.connect(racine / "cache.db")
        conn.execute("DROP TABLE messages_fts")
        conn.commit()
        conn.close()
        self.assertEqual(_probe_root(racine), "clear")
        conn = sqlite3.connect(racine / "cache.db")
        conn.execute("DELETE FROM meta WHERE key = 'cache_epoch_check'")
        conn.commit()
        conn.close()
        self.assertIsNone(_probe_root(racine))

    def test_an_empty_old_cache_takes_the_requested_mode(self):
        racine = self.cache("encrypted", lignes=False)
        self.desinscrire(racine)
        store = self.ouvrir(compte(mode="clear"))
        self.assertEqual(store.mode, "clear")
        store.close()
        self.assertEqual(self.inscription(racine), "clear")

    def test_the_prefs_alone_never_decide_an_old_cache(self):
        racine = self.cache("clear")
        self.desinscrire(racine, "DROP TABLE messages_fts;")
        self.ecrire_prefs('{"mail_cache_mode": "encrypted"}')
        avant = (racine / "cache.db").read_bytes()
        self.assertEqual(_probe_root(racine), "clear")
        with self.assertRaises(CacheModeMismatch) as ctx:
            Store(compte(), secrets=self.coffre, base=self.base).open()
        self.assertEqual(ctx.exception.inscribed, "clear")
        self.assertEqual(ctx.exception.requested, "encrypted")
        self.assertEqual((racine / "cache.db").read_bytes(), avant)
        self.assertEqual(self.coffre.writes, 0)

    def test_detection_skips_missing_tables_and_columns(self):
        racine = self.base / "perso"
        racine.mkdir(parents=True)
        conn = sqlite3.connect(racine / "cache.db")
        conn.executescript(V5_SQL)
        conn.commit()
        conn.close()
        self.assertIsNone(_probe_root(racine))
        conn = sqlite3.connect(racine / "cache.db")
        clair = build_crypto("clear", None)
        conn.execute(V5_ROWS[0], (clair.seal(b"Sujet v5"),))
        conn.commit()
        conn.close()
        self.assertEqual(_probe_root(racine), "clear")


class TestMismatchRefused(CacheCase):
    def test_opening_in_another_mode_is_refused_before_any_write(self):
        racine = self.cache("clear")
        avant = (racine / "cache.db").read_bytes()
        coffre = FauxCoffre()
        with self.assertRaises(CacheModeMismatch):
            Store(
                compte(mode="encrypted"), secrets=coffre, base=self.base
            ).open()
        self.assertEqual((racine / "cache.db").read_bytes(), avant)
        conn = sqlite3.connect(racine / "cache.db")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        conn.close()
        self.assertIn("messages_fts", tables)
        self.assertEqual(
            (coffre.values, coffre.writes, coffre.gets), ({}, 0, 0)
        )

    def test_the_refusal_names_the_account_and_both_modes(self):
        self.cache("clear")
        with self.assertRaises(CacheModeMismatch) as ctx:
            Store(
                compte(mode="encrypted"), secrets=self.coffre, base=self.base
            ).open()
        self.assertEqual(
            str(ctx.exception),
            t("mail_err_cache_mode_mismatch").format(
                account="perso", inscribed="clear", requested="encrypted"
            ),
        )
        self.assertEqual(errors.classify(ctx.exception), "mode")

    def test_a_refused_open_publishes_no_connection_and_releases_its_lock(
        self,
    ):
        self.cache("clear")
        store = Store(
            compte(mode="encrypted"), secrets=self.coffre, base=self.base
        )
        with self.assertRaises(CacheModeMismatch):
            store.open()
        self.assertIsNone(store._conn)
        self.assertIsNone(store._usage_fd)
        with cache_exclusive("perso", self.base) as tenu:
            self.assertTrue(tenu)

    def test_an_unknown_inscribed_value_is_refused(self):
        racine = self.cache("clear")
        self.inscrire(racine, "magique")
        with self.assertRaises(CacheModeInvalid) as ctx:
            Store(
                compte(mode="clear"), secrets=self.coffre, base=self.base
            ).open()
        self.assertEqual(
            str(ctx.exception),
            t("mail_err_cache_mode_invalid").format(
                account="perso", inscribed="'magique'"
            ),
        )
        self.assertEqual(errors.classify(ctx.exception), "mode")

    def test_a_request_raced_between_probe_and_lock_is_refused(self):
        racine = self.cache("encrypted")
        avant = fichiers(racine)
        for sonde in (None, PROBE_UNKNOWN):
            with self.subTest(sonde=sonde):
                with mock.patch.object(
                    store_mod, "_probe_root", return_value=sonde
                ):
                    store = Store(
                        compte(mode="clear"),
                        secrets=self.coffre,
                        base=self.base,
                    )
                    with self.assertRaises(CacheModeMismatch):
                        store.open()
                self.assertIsNone(store._conn)
                self.assertEqual(fichiers(racine), avant)

    def test_no_request_adopts_the_inscription_read_under_the_lock(self):
        self.cache("encrypted")
        self.ecrire_prefs("{pas du json")
        for sonde in (None, PROBE_UNKNOWN):
            with self.subTest(sonde=sonde):
                avant = dict(self.coffre.values)
                with mock.patch.object(
                    store_mod, "_probe_root", return_value=sonde
                ):
                    store = Store(
                        compte(), secrets=self.coffre, base=self.base
                    )
                    self.assertEqual(store.mode, "clear")
                    store.open()
                self.assertEqual(store.mode, "encrypted")
                self.assertEqual(
                    [m.subject for m in store.list_messages(1)],
                    ["Question", "Question"],
                )
                store.close()
                self.assertEqual(self.coffre.values, avant)

    def test_no_request_adopts_the_inscription_seen_by_the_probe(self):
        """Résolu `clear` à la construction (aucun cache lu alors), le
        `Store` sans demande prend le mode que la sonde de l'ouverture
        lit, au lieu de se refuser à lui-même."""
        with mock.patch.object(store_mod, "_probe_root", return_value=None):
            store = Store(compte(), secrets=self.coffre, base=self.base)
        self.assertEqual(store.mode, "clear")
        self.cache("encrypted")
        store.open()
        self.addCleanup(store.close)
        self.assertEqual(store.mode, "encrypted")

    def test_an_adopted_cache_never_draws_a_key(self):
        """Adopté sous le verrou alors que la sonde n'a rien lu : la clé
        manquante est refusée, jamais créée."""
        self.cache("encrypted")
        vide = FauxCoffre()
        with mock.patch.object(store_mod, "_probe_root", return_value=None):
            store = Store(compte(), secrets=vide, base=self.base)
            with self.assertRaises(CacheKeyMissing):
                store.open()
        self.assertEqual((vide.values, vide.writes), ({}, 0))

    def test_an_encrypted_cache_without_its_key_is_refused_and_draws_none(
        self,
    ):
        store = self.ouvrir(compte(), mode="encrypted")
        store.cache_epoch()
        store.rule_log_claim("r1", "cle", outcome="sent", at=1)
        store.close()
        vide = FauxCoffre()
        with self.assertRaises(CacheKeyMissing) as ctx:
            Store(
                compte(mode="encrypted"), secrets=vide, base=self.base
            ).open()
        self.assertEqual(errors.classify(ctx.exception), "vault")
        self.assertEqual(
            str(ctx.exception),
            t("mail_err_cache_key_missing").format(account="perso"),
        )
        self.assertEqual((vide.values, vide.writes), ({}, 0))
        rouvert = self.ouvrir(compte(mode="encrypted"))
        rouvert.cache_epoch()
        self.assertTrue(rouvert.rule_log_seen("r1", "cle"))

    def test_an_unreadable_probe_never_draws_a_key(self):
        """Une sonde qui ne lit rien (`PROBE_UNKNOWN`) ne vaut pas
        « aucun cache » : la clé manquante est refusée, jamais créée, et le
        journal reste lisible avec la bonne clé."""
        store = self.ouvrir(compte(), mode="encrypted")
        store.cache_epoch()
        store.rule_log_claim("r1", "cle", outcome="sent", at=1)
        store.close()
        vide = FauxCoffre()
        with mock.patch.object(
            store_mod, "_probe_root", return_value=PROBE_UNKNOWN
        ):
            with self.assertRaises(CacheKeyMissing):
                Store(
                    compte(mode="encrypted"), secrets=vide, base=self.base
                ).open()
        self.assertEqual((vide.values, vide.writes), ({}, 0))
        rouvert = self.ouvrir(compte(mode="encrypted"))
        rouvert.cache_epoch()
        self.assertTrue(rouvert.rule_log_seen("r1", "cle"))

    def test_an_encrypted_cache_with_a_clear_salted_journal_is_refused(self):
        """Le contrôle d'époque salé en clair d'un cache chiffré (journal
        écrit pendant une période claire) : toute ouverture hors
        conversion est refusée sans rien écrire, le journal reste."""
        racine = self.cache("encrypted")
        store = self.ouvrir(compte(), mode="encrypted")
        store.cache_epoch()
        store.rule_log_claim("r1", "cle", outcome="sent", at=1)
        store.close()
        conn = sqlite3.connect(racine / "cache.db")
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'cache_epoch_check'",
            (store_mod.salted_hash(b"clear", "cache_epoch"),),
        )
        conn.commit()
        conn.close()
        avant = fichiers(racine)
        for demande in ("encrypted", None):
            with self.subTest(demande=demande):
                with self.assertRaises(store_mod.CacheNeedsReseal) as ctx:
                    Store(
                        compte(mode=demande),
                        secrets=self.coffre,
                        base=self.base,
                    ).open()
                self.assertEqual(errors.classify(ctx.exception), "mode")
                self.assertEqual(
                    str(ctx.exception),
                    t("mail_err_cache_needs_reseal").format(account="perso"),
                )
                self.assertEqual(fichiers(racine), avant)
        with store_mod.probe_connection(racine / "cache.db") as conn:
            self.assertTrue(store_mod.has_clear_residue(conn, racine))
        conversion = Store(
            compte(mode="encrypted"),
            secrets=self.coffre,
            base=self.base,
            lock_held=True,
        )
        conversion.open()
        conversion.close()

    def test_a_new_encrypted_cache_still_creates_its_key(self):
        coffre = FauxCoffre()
        self.ouvrir(compte(mode="encrypted"), coffre=coffre)
        self.assertEqual(coffre.writes, 1)
        cle = coffre.values[compte().cache_key_ref()]
        self.assertEqual(len(base64.b64decode(cle)), 32)

    def test_an_unusable_usage_lock_is_a_cache_error(self):
        ctl = self.base / CACHE_CTL_DIRNAME / "perso"
        ctl.mkdir(parents=True)
        cible = self.tmp / "cible"
        cible.write_text("")
        (ctl / "lock").symlink_to(cible)
        with self.assertRaises(StoreError) as ctx:
            Store(compte(mode="clear"), base=self.base).open()
        self.assertNotIsInstance(ctx.exception, CacheBusy)
        self.assertEqual(errors.classify(ctx.exception), "cache")
        self.assertTrue(
            str(ctx.exception).startswith(t("mail_err_cache_lock_unusable"))
        )

    def test_ephemeral_ignores_the_disk_cache(self):
        racine = self.cache("encrypted")
        avant = fichiers(self.base)
        store = self.ouvrir(
            compte(mode="ephemeral"),
            base=self.tmp / "shm",
            coffre=FauxCoffre(),
        )
        self.assertEqual(store.mode, "ephemeral")
        store.cleanup()
        self.assertEqual(fichiers(self.base), avant)
        self.assertTrue(racine.exists())

    def test_open_session_reports_the_mismatch_as_kind_mode(self):
        from script.todo.mail.tui import open_session

        self.cache("clear")
        session = open_session(
            compte(mode="encrypted"),
            self.coffre,
            base=self.base,
            connect_fn=lambda *a, **k: None,
        )
        self.assertIsNone(session.store)
        self.assertEqual(
            session.error,
            t("mail_err_cache_mode_mismatch").format(
                account="perso", inscribed="clear", requested="encrypted"
            ),
        )
        self.assertEqual(session.error_kind, "mode")


class TestUsageLock(CacheCase):
    def _lock(self):
        return self.base / CACHE_CTL_DIRNAME / "perso" / "lock"

    def test_open_holds_a_shared_lock_released_on_close(self):
        store = self.ouvrir(compte(mode="clear"))
        fd = os.open(self._lock(), os.O_RDWR)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            store.close()
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def test_two_stores_of_one_process_open_together(self):
        un = self.ouvrir(compte(mode="clear"))
        deux = self.ouvrir(compte(mode="clear"))
        self.assertIsNotNone(un._conn)
        self.assertIsNotNone(deux._conn)

    def test_an_exclusive_holder_makes_open_raise_cache_busy(self):
        self.cache("clear")
        with cache_exclusive("perso", self.base) as tenu:
            self.assertTrue(tenu)
            with self.assertRaises(CacheBusy) as ctx:
                Store(compte(mode="clear"), base=self.base).open()
        self.assertEqual(
            str(ctx.exception), t("mail_err_cache_busy_converting")
        )
        self.assertEqual(errors.classify(ctx.exception), "busy")

    def test_lock_held_takes_no_lock_and_runs_no_recovery(self):
        self.cache("clear")
        ecrire_etat(self.base, "perso", "building")
        neuve = self.base / CACHE_CTL_DIRNAME / "perso" / "new" / "perso"
        neuve.mkdir(parents=True)
        with cache_exclusive("perso", self.base) as tenu:
            self.assertTrue(tenu)
            store = Store(compte(mode="clear"), base=self.base, lock_held=True)
            store.open()
            self.assertIsNone(store._usage_fd)
            store.close()
        self.assertTrue(neuve.exists())
        self.assertTrue(
            (self.base / CACHE_CTL_DIRNAME / "perso" / "convert.json").exists()
        )

    def test_the_lock_lives_outside_the_cache_root(self):
        store = self.ouvrir(compte(mode="clear"))
        self.assertTrue(self._lock().exists())
        self.assertNotIn(store.root, self._lock().parents)
        self.assertEqual(oct(os.stat(self._lock()).st_mode & 0o777), "0o600")
        self.assertEqual(
            oct(os.stat(self._lock().parent).st_mode & 0o777), "0o700"
        )


class TestPreimages(CacheCase):
    def test_message_ref_hashes_to_message_key(self):
        store = self.ouvrir(compte(mode="encrypted"))
        for msgid, attendu in (
            ("  <a@example.org> ", "<a@example.org>"),
            ("", " uid:7:3"),
        ):
            with self.subTest(msgid=msgid):
                self.assertEqual(Store.message_ref(msgid, 7, 3), attendu)
                self.assertEqual(
                    store.message_key(msgid, 7, 3),
                    store._msgid_hash(attendu),
                )

    def test_a_rule_log_line_seals_its_message_ref_and_target(self):
        store = self.ouvrir(compte(mode="encrypted"))
        store.rule_log_claim(
            "r1",
            store.message_key("<1@example.org>", 1, 1),
            outcome="sent",
            at=1,
            msg_ref="<1@example.org>",
            target=CAROLE,
        )
        ref, cible = (
            store._db()
            .execute("SELECT sealed_msg_ref, sealed_target FROM rule_log")
            .fetchone()
        )
        self.assertTrue(bytes(ref).startswith(b"E1"))
        self.assertTrue(bytes(cible).startswith(b"E1"))
        self.assertEqual(store._open(ref), "<1@example.org>")
        self.assertEqual(store._open(cible), CAROLE)

    def test_auto_sent_seals_its_message_id(self):
        store = self.ouvrir(compte(mode="encrypted"))
        store.mark_auto_sent(" <a@example.org> ", "r1", 1)
        store.mark_auto_sent_many([(" <b@example.org>", "", 2)])
        lignes = {
            store._open(r[0])
            for r in store._db().execute("SELECT sealed_msgid FROM auto_sent")
        }
        self.assertEqual(lignes, {"<a@example.org>", "<b@example.org>"})

    def test_an_old_cache_gets_the_preimage_columns(self):
        racine = self.base / "perso"
        racine.mkdir(parents=True)
        conn = sqlite3.connect(racine / "cache.db")
        conn.executescript(V5_SQL)
        conn.commit()
        conn.close()
        store = self.ouvrir(compte(mode="clear"))
        colonnes = lambda table: {  # noqa: E731
            r[1] for r in store._db().execute(f"PRAGMA table_info({table})")
        }
        self.assertTrue(
            {"sealed_msg_ref", "sealed_target"} <= colonnes("rule_log")
        )
        self.assertIn("sealed_msgid", colonnes("auto_sent"))
        store.close()
        conn = sqlite3.connect(racine / "cache.db")
        conn.executescript(
            "ALTER TABLE rule_log DROP COLUMN sealed_msg_ref;"
            "ALTER TABLE rule_log DROP COLUMN sealed_target;"
            "ALTER TABLE auto_sent DROP COLUMN sealed_msgid;"
        )
        conn.commit()
        conn.close()
        store = self.ouvrir(compte(mode="clear"))
        self.assertTrue(
            {"sealed_msg_ref", "sealed_target"} <= colonnes("rule_log")
        )
        self.assertIn("sealed_msgid", colonnes("auto_sent"))


class TestEngineClaimPreimages(EngineCase):
    def test_the_engine_claim_passes_the_ref_and_the_target(self):
        self.regle()
        self.imap.recevoir(1)
        self.assertEqual(self.passe().sent, 1)
        ref, cible = (
            self.store._db()
            .execute(
                "SELECT sealed_msg_ref, sealed_target FROM rule_log"
                " WHERE msg_key NOT LIKE 'pre-%'"
            )
            .fetchone()
        )
        self.assertEqual(self.store._open(ref), "<1@example.net>")
        self.assertEqual(self.store._open(cible), CAROLE)


class TestRegistries(CacheCase):
    TABLES = ("meta", "folders", "messages", "outbox", "rule_log", "auto_sent")

    def _colonnes(self, store, table):
        return [
            r[1] for r in store._db().execute(f"PRAGMA table_info({table})")
        ]

    def test_every_sealed_or_hashed_column_is_registered(self):
        store = self.ouvrir(compte(mode="clear"))
        for table in self.TABLES:
            with self.subTest(table=table):
                colonnes = self._colonnes(store, table)
                scellees = {c for c in colonnes if c.startswith("sealed_")}
                empreintes = {
                    c
                    for c in colonnes
                    if c.endswith("_hash")
                    or c.endswith("_hashes")
                    or c in ("msg_key", "source_key")
                }
                self.assertEqual(scellees, set(SEALED_COLUMNS.get(table, ())))
                self.assertEqual(
                    empreintes, set(HASHED_COLUMNS.get(table, ()))
                )

    def test_an_old_cache_has_only_registered_extra_columns(self):
        from mail_cache_fixtures import rendre_v4

        neuf = self.ouvrir(compte("neuf", mode="clear"))
        store = self.ouvrir(compte(mode="clear"))
        rendre_v4(store)
        store.close()
        store = self.ouvrir(compte(mode="clear"))
        for table in self.TABLES:
            with self.subTest(table=table):
                en_plus = set(self._colonnes(store, table)) - set(
                    self._colonnes(neuf, table)
                )
                self.assertLessEqual(
                    {(table, c) for c in en_plus}, LEGACY_SOURCE_COLUMNS
                )
        self.assertIn("last_error", self._colonnes(store, "outbox"))


class TestBodyFile(CacheCase):
    def test_write_body_file_does_not_touch_has_body(self):
        store = self.ouvrir(compte(mode="encrypted"))
        dossier = store.upsert_folder("INBOX", "Boîte", "inbox", 3)
        store.upsert_messages(dossier, [message(1)])
        store._write_body_file("INBOX", 1, b"Corps")
        self.assertEqual(store.read_body("INBOX", 1), b"Corps")
        self.assertFalse(store.list_messages(dossier)[0].has_body)
        store.write_body("INBOX", 1, b"Corps")
        self.assertTrue(store.list_messages(dossier)[0].has_body)


if __name__ == "__main__":
    unittest.main()
