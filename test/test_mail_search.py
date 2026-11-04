#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Recherche sur tout le cache : index FTS5 en clair, balayage déchiffré
en mode chiffré. Le mode change le COÛT, jamais le résultat."""

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import AesGcmCrypto
from script.todo.mail.store import (
    CacheModeMismatch,
    MessageMeta,
    Store,
    new_key,
)


class SearchCase(unittest.TestCase):
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
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")
        self.autre = self.store.upsert_folder("Archives", "Archives", None)
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=1,
                    date=100,
                    size=1,
                    flags="",
                    msgid="<1@e.ca>",
                    frm="Ana <ana@e.ca>",
                    to="moi@x.ca",
                    subject="Devis pour la toiture",
                    snippet="bonjour voici le devis",
                ),
                MessageMeta(
                    uid=2,
                    date=200,
                    size=1,
                    flags="",
                    msgid="<2@e.ca>",
                    frm="Bo <bo@e.ca>",
                    to="moi@x.ca",
                    subject="Facture été",
                    snippet="règlement attendu",
                ),
            ],
        )
        self.store.upsert_messages(
            self.autre,
            [
                MessageMeta(
                    uid=3,
                    date=300,
                    size=1,
                    flags="",
                    msgid="<3@e.ca>",
                    frm="Ana <ana@e.ca>",
                    to="moi@x.ca",
                    subject="Devis archivé",
                    snippet="ancien",
                ),
            ],
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def sujets(self, *a, **k):
        return sorted(m.subject for m in self.store.search(*a, **k))


class TestSearchClear(SearchCase):
    def test_it_finds_by_subject(self):
        self.assertIn("Devis pour la toiture", self.sujets("toiture"))

    def test_it_finds_by_sender(self):
        self.assertEqual(len(self.sujets("ana")), 2)

    def test_it_finds_by_snippet(self):
        self.assertIn("Facture été", self.sujets("règlement"))

    def test_it_reaches_beyond_the_open_folder(self):
        """La limite qui motivait ce chantier : chercher ne voyait que les
        500 messages chargés du dossier ouvert."""
        self.assertIn("Devis archivé", self.sujets("devis"))

    def test_a_folder_filter_narrows_it(self):
        self.assertNotIn(
            "Devis archivé", self.sujets("devis", folder_id=self.inbox)
        )

    def test_an_empty_query_finds_nothing(self):
        self.assertEqual(self.sujets(""), [])

    def test_punctuation_does_not_raise(self):
        """L'utilisateur tape des mots, pas la syntaxe de FTS5 : un
        guillemet ou une étoile y lèverait une erreur de syntaxe."""
        for brut in ('"', "*", 'devis "', "a* OR"):
            self.store.search(brut)

    def test_the_mode_says_whether_an_index_answered(self):
        self.assertTrue(self.store.search_is_indexed())


class TestSearchEncrypted(SearchCase):
    mode = "encrypted"

    def test_no_plaintext_index_file_exists(self):
        """La raison d'être du balayage : un index FTS5 stockerait en clair
        ce que la base scelle."""
        tables = [
            r[0]
            for r in self.store._db().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        self.assertNotIn("messages_fts", tables)

    def test_it_still_finds_the_same_things(self):
        """Le mode ne doit pas changer le RÉSULTAT, seulement le coût."""
        self.assertIn("Devis pour la toiture", self.sujets("toiture"))
        self.assertEqual(len(self.sujets("ana")), 2)
        self.assertIn("Devis archivé", self.sujets("devis"))

    def test_the_mode_says_it_scans(self):
        self.assertFalse(self.store.search_is_indexed())


class TestTheIndexDoesNotOutliveWhatItIndexes(SearchCase):
    """L'index FTS5 garde en clair le sujet, l'extrait et les adresses.

    C'est le compromis assumé du mode clair. Il cesse de l'être dès que le
    cache qui l'a rempli n'est plus censé être lisible : un compte passé en
    chiffré, ou un cache que l'utilisateur vient de purger, laissaient
    l'index derrière eux avec tout son contenu.
    """

    def _tables(self, store):
        return [
            r[0]
            for r in store._db().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]

    def _indexes(self, store):
        return [
            r[0]
            for r in store._db().execute("SELECT subject FROM messages_fts")
        ]

    def _rouvrir(self, mode, key=None):
        self.store.close()
        self.store = Store(
            self.account,
            mode=mode,
            key=key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        return self.store

    def test_reopening_as_encrypted_is_refused_and_keeps_the_index(self):
        """Le cache est inscrit `clear` : l'ouvrir en chiffré est refusé
        AVANT `_ensure_fts`, qui supprimerait l'index, et la recherche
        reste indexée à la réouverture en clair."""
        self.assertIn("messages_fts", self._tables(self.store))
        with self.assertRaises(CacheModeMismatch):
            self._rouvrir("encrypted", new_key())
        store = self._rouvrir("clear")
        self.assertIn("messages_fts", self._tables(store))
        self.assertTrue(store.search_is_indexed())
        self.assertIn("Devis pour la toiture", self.sujets("toiture"))

    def test_an_old_mixed_cache_detected_encrypted_loses_its_index(self):
        """Un cache d'avant l'inscription, clair et indexé, qui porte une
        ligne scellée : il est détecté `encrypted`, l'ouverture chiffrée est
        acceptée et l'index, qui rendrait les sujets en clair, part."""
        key = new_key()
        db = self.store._db()
        scelle = AesGcmCrypto(key).seal(b"Sujet scelle")
        db.execute(
            "UPDATE messages SET sealed_subject = ? WHERE uid = 1", (scelle,)
        )
        db.execute("DELETE FROM meta WHERE key = 'cache_mode'")
        db.commit()
        store = self._rouvrir("encrypted", key)
        self.assertNotIn("messages_fts", self._tables(store))
        inscrit = (
            store._db()
            .execute("SELECT value FROM meta WHERE key = 'cache_mode'")
            .fetchone()[0]
        )
        self.assertEqual(inscrit, "encrypted")

    def test_purging_the_cache_empties_the_index_too(self):
        """« Effacer le cache » qui laisse l'index intact n'efface rien de
        ce qui se lit."""
        self.store.purge_all()
        self.assertEqual(self._indexes(self.store), [])

    def test_purging_one_folder_leaves_the_others_indexed(self):
        self.store.purge_folder("INBOX")
        restants = self._indexes(self.store)
        self.assertEqual(restants, ["Devis archivé"])


class TestIndexIsRebuilt(SearchCase):
    def test_an_existing_cache_becomes_searchable_without_a_resync(self):
        """Un index vide répondrait « aucun résultat » sur une boîte pleine
        — indiscernable d'une absence de correspondance."""
        self.store._db().execute("DROP TABLE messages_fts")
        self.store._db().commit()
        self.store.close()
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        self.assertIn("Devis pour la toiture", self.sujets("toiture"))

    def test_a_contentless_index_is_rebuilt_not_kept(self):
        """Une table `content=''` ne stocke rien et refuse les DELETE : une
        resynchronisation ne pourrait plus remplacer l'entrée d'un message
        déjà indexé. Les colonnes seules ne distinguent pas les deux
        formes."""
        db = self.store._db()
        db.execute("DROP TABLE messages_fts")
        db.execute(
            "CREATE VIRTUAL TABLE messages_fts USING fts5(subject, snippet,"
            " frm, adr_to, content='')"
        )
        db.commit()
        self.store.close()
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        self.assertIn("Devis pour la toiture", self.sujets("toiture"))

    def test_a_resync_replaces_the_indexed_entry(self):
        """Sans DELETE possible, un message resynchronisé apparaîtrait deux
        fois — ou garderait son ancien sujet."""
        from script.todo.mail.store import MessageMeta

        remplace = MessageMeta(
            uid=1,
            date=100,
            size=1,
            flags="",
            msgid="<1@e.ca>",
            frm="Ana <ana@e.ca>",
            to="moi@x.ca",
            subject="Sujet corrige",
            snippet="nouveau",
        )
        self.store.upsert_messages(self.inbox, [remplace])
        self.assertEqual(self.sujets("toiture"), [])
        self.assertEqual(self.sujets("corrige"), ["Sujet corrige"])

    def test_a_narrower_index_is_rebuilt_not_kept(self):
        """`IF NOT EXISTS` garderait une table d'une version antérieure, et
        la recherche répondrait alors selon l'âge du cache."""
        db = self.store._db()
        db.execute("DROP TABLE messages_fts")
        db.execute(
            "CREATE VIRTUAL TABLE messages_fts USING fts5(subject, content='')"
        )
        db.commit()
        self.store.close()
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        self.assertEqual(len(self.sujets("ana")), 2)


if __name__ == "__main__":
    unittest.main()
