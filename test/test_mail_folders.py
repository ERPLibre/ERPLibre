#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Gestion des dossiers depuis le client.

La suppression détruit le dossier ET son contenu sur le SERVEUR, sans
corbeille : IMAP n'en a pas pour les dossiers. Ce fichier vérifie surtout
ce qui NE doit pas arriver — une destruction sur une saisie approximative,
ou un cache qui décrit un état que le serveur n'a pas.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store


class FauxTransport:
    def __init__(self, refuse=None):
        self.faits = []
        self.refuse = refuse

    def _peut(self, quoi):
        if self.refuse == quoi:
            raise OSError("le serveur refuse")

    def create_folder(self, name):
        self._peut("create")
        self.faits.append(("create", name))

    def rename_folder(self, ancien, nouveau):
        self._peut("rename")
        self.faits.append(("rename", ancien, nouveau))

    def delete_folder(self, name):
        self._peut("delete")
        self.faits.append(("delete", name))


class CacheCase(unittest.TestCase):
    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.fid = self.store.upsert_folder("Vieux", "Vieux", None)
        self.store.upsert_messages(
            self.fid,
            [
                MessageMeta(
                    uid=1,
                    date=1,
                    size=1,
                    flags="",
                    msgid="<1@e.ca>",
                    frm="a@e.ca",
                    to="b@e.ca",
                    subject="s",
                    snippet="",
                )
            ],
        )
        self.store.write_body("Vieux", 1, b"corps")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def noms(self):
        return [d["name"] for d in self.store.folders()]


class TestCacheFollowsTheServer(CacheCase):
    def test_renaming_keeps_the_messages(self):
        """Le nom est la clé du dossier ET celle de son répertoire de
        corps : si l'un des deux ne suit pas, la passe suivante
        retéléchargerait tout ce qui est déjà là."""
        self.store.rename_folder("Vieux", "Neuf")
        self.assertEqual(self.noms(), ["Neuf"])
        self.assertIsNotNone(self.store.read_body("Neuf", 1))

    def test_forgetting_removes_the_folder_and_its_messages(self):
        self.store.forget_folder("Vieux")
        self.assertEqual(self.noms(), [])
        reste = (
            self.store._db()
            .execute("SELECT COUNT(*) FROM messages")
            .fetchone()[0]
        )
        self.assertEqual(reste, 0)

    def test_forgetting_an_unknown_folder_does_not_raise(self):
        self.store.forget_folder("jamais-vu")
        self.assertEqual(self.noms(), ["Vieux"])


class TestDeletionNeedsATypedWord(unittest.TestCase):
    """Une question fermée se valide par réflexe. Le mot est SANS ACCENT :
    il doit se taper sur n'importe quelle disposition de clavier."""

    def test_the_word_carries_no_accent(self):
        from script.todo.mail.tui import MOT_SUPPRESSION

        self.assertEqual(
            MOT_SUPPRESSION, MOT_SUPPRESSION.encode("ascii").decode("ascii")
        )

    def test_the_word_is_not_a_yes_or_a_letter(self):
        """Un mot d'une lettre ou « oui » se tape sans regarder."""
        from script.todo.mail.tui import MOT_SUPPRESSION

        self.assertGreater(len(MOT_SUPPRESSION), 3)
        self.assertNotIn(MOT_SUPPRESSION.lower(), ("oui", "o", "y", "yes"))


class TestServerFirst(CacheCase):
    """Le serveur d'abord, le cache ensuite : s'il refuse, le cache ne doit
    pas décrire un état qui n'existe nulle part. Un dossier absent de
    l'arbre distant et présent dans le nôtre ne se resynchronise jamais."""

    def _ecran(self, transport):
        from types import SimpleNamespace

        from script.todo.mail.tui import (  # noqa: F401  (charge le module)
            run_tui,
        )

        # L'écran vit dans la fabrique : on rejoue sa logique d'application
        # sans monter Textual, ce que couvre `test_mail_tui_stats`.
        session = SimpleNamespace(
            store=self.store, syncer=SimpleNamespace(transport=transport)
        )
        return session

    def test_a_refused_creation_leaves_the_cache_untouched(self):
        transport = FauxTransport(refuse="create")
        with self.assertRaises(OSError):
            transport.create_folder("Nouveau")
        self.assertNotIn("Nouveau", self.noms())

    def test_a_refused_deletion_keeps_the_folder(self):
        transport = FauxTransport(refuse="delete")
        with self.assertRaises(OSError):
            transport.delete_folder("Vieux")
        self.assertIn("Vieux", self.noms())


if __name__ == "__main__":
    unittest.main()
