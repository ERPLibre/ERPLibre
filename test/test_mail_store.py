#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import CryptoError, new_key
from script.todo.mail.store import (
    EPHEMERAL_PREFIX,
    MessageMeta,
    Store,
    StoreError,
    cache_root,
    folder_dirname,
    resolve_mode,
    sweep_orphan_ephemeral,
)


def meta(uid, subject="Sujet", frm="a@x.ca", date=1000, flags=""):
    return MessageMeta(
        uid=uid,
        date=date,
        size=42,
        flags=flags,
        msgid=f"<{uid}@x.ca>",
        frm=frm,
        to="moi@x.ca",
        subject=subject,
        snippet="debut du corps",
    )


class TestResolveMode(unittest.TestCase):
    def test_account_override_wins(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        acc.cache_mode = "encrypted"
        self.assertEqual(
            resolve_mode(acc, lambda k, d=None: "clear"), "encrypted"
        )

    def test_falls_back_to_general_default(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        self.assertEqual(
            resolve_mode(acc, lambda k, d=None: "ephemeral"), "ephemeral"
        )

    def test_unknown_general_default_falls_back_to_clear(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        self.assertEqual(
            resolve_mode(acc, lambda k, d=None: "magique"), "clear"
        )


class TestFolderDirname(unittest.TestCase):
    def test_slash_is_escaped(self):
        self.assertNotIn("/", folder_dirname("[Gmail]/Sent Mail"))

    def test_is_reversible_enough_to_be_unique(self):
        self.assertNotEqual(folder_dirname("A/B"), folder_dirname("A_B"))

    def test_traversal_collapses_to_one_component(self):
        self.assertNotIn("/", folder_dirname("../../etc"))

    def test_degenerate_names_cannot_designate_the_parent(self):
        """`racine / ".."` remonterait d'un cran : ces noms sont réécrits."""
        for hostile in ("", ".", ".."):
            self.assertNotIn(folder_dirname(hostile), ("", ".", ".."))

    def test_dotted_hierarchy_stays_readable(self):
        """Le point sépare la hiérarchie chez beaucoup de serveurs IMAP."""
        self.assertEqual(folder_dirname("INBOX.Sent"), "INBOX.Sent")


class TestCacheRoot(unittest.TestCase):
    def test_persistent_modes_use_base(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        with tempfile.TemporaryDirectory() as tmp:
            root = cache_root(acc, "clear", Path(tmp))
            self.assertEqual(root, Path(tmp) / "perso")

    def test_ephemeral_root_carries_the_pid(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        with tempfile.TemporaryDirectory() as tmp:
            root = cache_root(acc, "ephemeral", Path(tmp))
            self.assertIn(f"{EPHEMERAL_PREFIX}{os.getpid()}", str(root))


class StoreCase(unittest.TestCase):
    """Socle commun : un compte, une base temporaire, mode paramétrable."""

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

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class TestSchema(StoreCase):
    def test_db_file_created(self):
        self.assertTrue((self.store.root / "cache.db").exists())

    def test_root_is_0700(self):
        import stat

        self.assertEqual(stat.S_IMODE(os.stat(self.store.root).st_mode), 0o700)

    def test_reopen_is_idempotent(self):
        self.store.close()
        again = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        again.open()
        again.close()


class TestFolders(StoreCase):
    def test_upsert_returns_id(self):
        fid = self.store.upsert_folder("INBOX", "INBOX", "inbox", 1, 10)
        self.assertIsInstance(fid, int)

    def test_upsert_twice_keeps_same_id(self):
        first = self.store.upsert_folder("INBOX")
        second = self.store.upsert_folder("INBOX")
        self.assertEqual(first, second)

    def test_folder_state(self):
        self.store.upsert_folder("INBOX", uidvalidity=7)
        state = self.store.folder_state("INBOX")
        self.assertEqual(state["uidvalidity"], 7)
        self.assertEqual(state["last_uid"], 0)

    def test_set_folder_state(self):
        self.store.upsert_folder("INBOX")
        self.store.set_folder_state("INBOX", last_uid=99, unseen=3)
        state = self.store.folder_state("INBOX")
        self.assertEqual(state["last_uid"], 99)
        self.assertEqual(state["unseen"], 3)

    def test_unknown_folder_state_is_none(self):
        self.assertIsNone(self.store.folder_state("ABSENT"))

    def test_folders_lists_them(self):
        self.store.upsert_folder("INBOX")
        self.store.upsert_folder("Sent")
        self.assertEqual(
            {f["name"] for f in self.store.folders()}, {"INBOX", "Sent"}
        )

    def test_display_is_null_until_one_is_known(self):
        """NULL veut dire « inconnu » : le lecteur retombe sur le nom IMAP."""
        self.store.upsert_folder("INBOX")
        self.assertIsNone(self.store.folder_state("INBOX")["display"])

    def test_partial_upsert_keeps_the_display_name(self):
        """Une resync qui ne repasse que le nom IMAP ne doit rien écraser."""
        self.store.upsert_folder("INBOX", "Boîte de réception")
        self.store.upsert_folder("INBOX")
        self.assertEqual(
            self.store.folder_state("INBOX")["display"], "Boîte de réception"
        )


class TestMessages(StoreCase):
    def setUp(self):
        super().setUp()
        self.fid = self.store.upsert_folder("INBOX")

    def test_upsert_then_list(self):
        self.store.upsert_messages(self.fid, [meta(1), meta(2)])
        got = self.store.list_messages(self.fid)
        self.assertEqual({m.uid for m in got}, {1, 2})

    def test_subject_survives_roundtrip(self):
        self.store.upsert_messages(self.fid, [meta(1, subject="Devis révisé")])
        self.assertEqual(
            self.store.list_messages(self.fid)[0].subject, "Devis révisé"
        )

    def test_upsert_same_uid_updates(self):
        self.store.upsert_messages(self.fid, [meta(1, subject="ancien")])
        self.store.upsert_messages(self.fid, [meta(1, subject="nouveau")])
        got = self.store.list_messages(self.fid)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].subject, "nouveau")

    def test_sorted_by_date_desc(self):
        self.store.upsert_messages(
            self.fid, [meta(1, date=100), meta(2, date=300), meta(3, date=200)]
        )
        self.assertEqual(
            [m.uid for m in self.store.list_messages(self.fid)], [2, 3, 1]
        )

    def test_update_flags(self):
        self.store.upsert_messages(self.fid, [meta(1)])
        self.store.update_flags(self.fid, 1, "\\Seen")
        self.assertEqual(self.store.list_messages(self.fid)[0].flags, "\\Seen")

    def test_known_uids(self):
        self.store.upsert_messages(self.fid, [meta(1), meta(2), meta(3)])
        self.assertEqual(sorted(self.store.known_uids(self.fid)), [1, 2, 3])

    def test_limit_and_offset(self):
        self.store.upsert_messages(
            self.fid, [meta(i, date=i) for i in range(1, 6)]
        )
        self.assertEqual(
            [m.uid for m in self.store.list_messages(self.fid, limit=2)],
            [5, 4],
        )
        self.assertEqual(
            [
                m.uid
                for m in self.store.list_messages(self.fid, limit=2, offset=2)
            ],
            [3, 2],
        )


class TestBodies(StoreCase):
    def test_write_then_read(self):
        self.store.upsert_folder("INBOX")
        self.store.write_body("INBOX", 1, b"From: a@x.ca\r\n\r\nBonjour")
        self.assertEqual(
            self.store.read_body("INBOX", 1), b"From: a@x.ca\r\n\r\nBonjour"
        )

    def test_missing_body_is_none(self):
        self.assertIsNone(self.store.read_body("INBOX", 404))

    def test_has_body_flag_is_set(self):
        fid = self.store.upsert_folder("INBOX")
        self.store.upsert_messages(fid, [meta(1)])
        self.store.write_body("INBOX", 1, b"corps")
        self.assertTrue(self.store.list_messages(fid)[0].has_body)

    def test_folder_with_slash(self):
        self.store.upsert_folder("[Gmail]/Sent Mail")
        self.store.write_body("[Gmail]/Sent Mail", 1, b"corps")
        self.assertEqual(
            self.store.read_body("[Gmail]/Sent Mail", 1), b"corps"
        )

    def test_no_window_at_the_process_umask(self):
        """`write_bytes` puis `chmod` laisserait le corps du message lisible
        à l'umask du process le temps entre les deux appels. Au moment où
        `chmod` est appelé, le fichier doit déjà être en 0600."""
        import stat
        from unittest.mock import patch

        self.store.upsert_folder("INBOX")
        path = self.store._body_path("INBOX", 1)
        seen = []
        original_chmod = os.chmod

        def spy(target, mode):
            if Path(target) == path:
                seen.append(stat.S_IMODE(os.stat(target).st_mode))
            return original_chmod(target, mode)

        with patch("os.chmod", side_effect=spy):
            self.store.write_body("INBOX", 1, b"corps")

        self.assertEqual(seen, [0o600])


class TestPurge(StoreCase):
    def test_purge_folder_drops_rows_and_files(self):
        fid = self.store.upsert_folder("INBOX")
        self.store.upsert_messages(fid, [meta(1)])
        self.store.write_body("INBOX", 1, b"corps")
        self.store.purge_folder("INBOX")
        self.assertEqual(self.store.list_messages(fid), [])
        self.assertIsNone(self.store.read_body("INBOX", 1))

    def test_purge_folder_resets_last_uid(self):
        self.store.upsert_folder("INBOX")
        self.store.set_folder_state("INBOX", last_uid=50)
        self.store.purge_folder("INBOX")
        self.assertEqual(self.store.folder_state("INBOX")["last_uid"], 0)

    def test_purge_all(self):
        fid = self.store.upsert_folder("INBOX")
        self.store.upsert_messages(fid, [meta(1)])
        self.store.purge_all()
        self.assertEqual(self.store.folders(), [])

    def test_size_bytes_grows(self):
        before = self.store.size_bytes()
        self.store.upsert_folder("INBOX")
        self.store.write_body("INBOX", 1, b"x" * 5000)
        self.assertGreater(self.store.size_bytes(), before)


class TestEncryptedStore(TestMessages):
    """Le même contrat, en chiffré : rien ne doit changer du point de vue de l'appelant."""

    mode = "encrypted"

    def test_subject_absent_from_db_file(self):
        self.store.upsert_messages(self.fid, [meta(1, subject="CONFIDENTIEL")])
        self.store.close()
        raw = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(b"CONFIDENTIEL", raw)
        self.store.open()

    def test_body_file_is_encrypted(self):
        self.store.write_body("INBOX", 1, b"TEXTE SECRET")
        path = next((self.store.root).rglob("*.eml*"))
        self.assertNotIn(b"TEXTE SECRET", path.read_bytes())

    def test_date_stays_queryable_in_clear(self):
        """Le tri doit rester du SQL : la date n'est pas scellée."""
        self.store.upsert_messages(self.fid, [meta(1, date=12345)])
        rows = self.store._conn.execute(
            "SELECT date FROM messages WHERE uid = 1"
        ).fetchall()
        self.assertEqual(rows[0][0], 12345)


class TestWrongKey(unittest.TestCase):
    def test_reopening_with_another_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            acc = account_from_preset("perso", "a@x.ca", "generic")
            first = Store(acc, mode="encrypted", key=new_key(), base=Path(tmp))
            first.open()
            fid = first.upsert_folder("INBOX")
            first.upsert_messages(fid, [meta(1, subject="secret")])
            first.close()

            second = Store(
                acc, mode="encrypted", key=new_key(), base=Path(tmp)
            )
            second.open()
            with self.assertRaises(CryptoError):
                second.list_messages(fid)
            second.close()


class TestEphemeral(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "a@x.ca", "generic")

    def tearDown(self):
        self.tmp.cleanup()

    def test_cleanup_removes_everything(self):
        store = Store(
            self.account,
            mode="ephemeral",
            key=new_key(),
            base=Path(self.tmp.name),
        )
        store.open()
        root = store.root
        store.write_body("INBOX", 1, b"corps")
        self.assertTrue(root.exists())
        store.close()
        store.cleanup()
        self.assertFalse(root.exists())

    def test_sweep_removes_dead_pid_dirs(self):
        base = Path(self.tmp.name)
        dead = base / f"{EPHEMERAL_PREFIX}999999999"
        dead.mkdir()
        alive = base / f"{EPHEMERAL_PREFIX}{os.getpid()}"
        alive.mkdir()
        removed = sweep_orphan_ephemeral(base)
        self.assertEqual(removed, 1)
        self.assertFalse(dead.exists())
        self.assertTrue(alive.exists())

    def test_sweep_ignores_foreign_dirs(self):
        base = Path(self.tmp.name)
        (base / "autre-chose").mkdir()
        self.assertEqual(sweep_orphan_ephemeral(base), 0)
        self.assertTrue((base / "autre-chose").exists())


class TestCorruptDatabase(unittest.TestCase):
    """Un open() raté ne doit pas laisser l'objet porteur d'un handle cassé."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        root = Path(self.tmp.name) / "perso"
        root.mkdir(parents=True)
        (root / "cache.db").write_bytes(b"ceci n'est pas une base sqlite" * 40)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_raises_store_error(self):
        store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        with self.assertRaises(StoreError):
            store.open()

    def test_failed_open_does_not_publish_the_connection(self):
        """Sinon le open() suivant réussirait en silence sur une base sans schéma."""
        store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        with self.assertRaises(StoreError):
            store.open()
        with self.assertRaises(StoreError):
            store.open()


class TestEphemeralIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.a = account_from_preset("perso", "a@x.ca", "generic")
        self.b = account_from_preset("travail", "b@x.ca", "generic")

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self, account):
        store = Store(account, mode="ephemeral", key=new_key(), base=self.base)
        store.open()
        return store

    def test_cleanup_spares_the_sibling_account(self):
        """Le dossier par PID est partagé : l'effacer tuerait le voisin."""
        first, second = self._store(self.a), self._store(self.b)
        first.write_body("INBOX", 1, b"corps a")
        second.write_body("INBOX", 1, b"corps b")
        first.cleanup()
        self.assertFalse(first.root.exists())
        self.assertTrue(second.root.exists())
        self.assertEqual(second.read_body("INBOX", 1), b"corps b")
        second.cleanup()

    def test_last_cleanup_removes_the_pid_directory(self):
        first, second = self._store(self.a), self._store(self.b)
        pid_dir = first.root.parent
        first.cleanup()
        self.assertTrue(pid_dir.exists())
        second.cleanup()
        self.assertFalse(pid_dir.exists())

    def test_pid_directory_is_0700(self):
        """/dev/shm est en 1777 : le dossier par PID ne doit rien laisser voir."""
        import stat as stat_module

        store = self._store(self.a)
        mode = stat_module.S_IMODE(os.stat(store.root.parent).st_mode)
        self.assertEqual(mode, 0o700)
        store.cleanup()

    def test_symlinked_pid_directory_is_refused(self):
        """Un tiers peut pré-créer le chemin : on refuse de le suivre."""
        target = self.base / "ailleurs"
        target.mkdir()
        (self.base / f"{EPHEMERAL_PREFIX}{os.getpid()}").symlink_to(target)
        store = Store(self.a, mode="ephemeral", key=new_key(), base=self.base)
        with self.assertRaises(StoreError):
            store.open()


class TestKeyPersistence(unittest.TestCase):
    """Le seul chemin du module qui écrit de la matière de clé sur disque."""

    class FakeVault:
        def __init__(self):
            self.data = {}

        def get(self, ref):
            return self.data.get(ref)

        def set(self, ref, value):
            self.data[ref] = value

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.vault = self.FakeVault()

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        store = Store(
            self.account, mode="encrypted", secrets=self.vault, base=self.base
        )
        store.open()
        return store

    def test_first_open_stores_a_key_under_the_cache_key_ref(self):
        self._store().close()
        self.assertIn(self.account.cache_key_ref(), self.vault.data)

    def test_stored_key_is_base64_of_32_bytes(self):
        import base64

        self._store().close()
        raw = base64.b64decode(self.vault.data[self.account.cache_key_ref()])
        self.assertEqual(len(raw), 32)

    def test_second_store_reuses_the_stored_key(self):
        first = self._store()
        fid = first.upsert_folder("INBOX")
        first.upsert_messages(fid, [meta(1, subject="Devis")])
        first.close()

        second = self._store()
        self.assertEqual(second.list_messages(fid)[0].subject, "Devis")
        second.close()

    def test_key_is_not_regenerated_on_reopen(self):
        self._store().close()
        stored = self.vault.data[self.account.cache_key_ref()]
        self._store().close()
        self.assertEqual(self.vault.data[self.account.cache_key_ref()], stored)

    def test_key_never_lands_in_the_cache_file(self):
        import base64

        store = self._store()
        fid = store.upsert_folder("INBOX")
        store.upsert_messages(fid, [meta(1)])
        root = store.root
        store.close()
        raw = base64.b64decode(self.vault.data[self.account.cache_key_ref()])
        blob = (root / "cache.db").read_bytes()
        self.assertNotIn(raw, blob)
        self.assertNotIn(base64.b64encode(raw), blob)


class TestThreadSafety(unittest.TestCase):
    """Le TUI synchronise dans un thread de travail pendant que l'écran lit.

    Sans `check_same_thread=False` ET le verrou, la toute première passe de
    synchronisation lèverait `sqlite3.ProgrammingError`.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.fid = self.store.upsert_folder("INBOX")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_read_from_another_thread(self):
        import threading

        erreurs = []

        def worker():
            try:
                self.store.folders()
            except Exception as exc:
                erreurs.append(f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(erreurs, [])

    def test_write_from_another_thread(self):
        import threading

        erreurs = []

        def worker():
            try:
                self.store.upsert_messages(self.fid, [meta(1)])
            except Exception as exc:
                erreurs.append(f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(erreurs, [])
        self.assertEqual(len(self.store.list_messages(self.fid)), 1)

    def test_concurrent_writers_all_land(self):
        """Le verrou sérialise : aucun upsert ne doit se perdre."""
        import threading

        def worker(start):
            self.store.upsert_messages(
                self.fid, [meta(uid) for uid in range(start, start + 20)]
            )

        threads = [
            threading.Thread(target=worker, args=(base,))
            for base in (1, 101, 201, 301)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(
            len(self.store.list_messages(self.fid, limit=500)), 80
        )


class TestKeyRequired(unittest.TestCase):
    def test_encrypted_without_key_or_secrets_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            acc = account_from_preset("perso", "a@x.ca", "generic")
            store = Store(acc, mode="encrypted", base=Path(tmp))
            with self.assertRaises(StoreError):
                store.open()


if __name__ == "__main__":
    unittest.main()
