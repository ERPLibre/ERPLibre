#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache local des billets.

Ce qui le distingue du cache courriel, et ce que ces tests tiennent :
l'identifiant d'un billet est une CHAÎNE choisie par la plateforme — un
compteur à flocon ici, une URI `at://…` là — et le curseur de reprise est
OPAQUE. Supposer un entier croissant ou une forme de curseur marcherait
sur une plateforme et casserait sur la suivante.

Le reste vaut comme pour le courriel : ce qui est scellé l'est vraiment, un
fichier de cache n'est lisible que par son propriétaire, et les compteurs
d'un fil suivent chaque geste plutôt que d'attendre la passe suivante.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.crypto import new_key
from script.todo.social.accounts import account_from_preset
from script.todo.social.store import (
    EPHEMERAL_PREFIX,
    Media,
    PostMeta,
    SocialStoreError,
    Store,
    cache_root,
    resolve_mode,
    sweep_orphan_ephemeral,
)


def billet(post_id, quand=1_780_000_000, **kw):
    base = dict(
        post_id=post_id,
        created_at=quand,
        author="@ana@instance.exemple",
        author_name="Ana",
        text="Bonjour le fil.",
        url="https://instance.exemple/@ana/1",
        uri="https://instance.exemple/users/ana/statuses/1",
    )
    base.update(kw)
    return PostMeta(**base)


class StoreCase(unittest.TestCase):
    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.account = account_from_preset(
            "perso",
            "@moi@instance.exemple",
            "mastodon",
            base_url="https://instance.exemple",
        )
        self.key = new_key() if self.mode != "clear" else None
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()
        self.addCleanup(self.store.close)
        self.home = self.store.upsert_feed("home", "Accueil")


class TestTheSchema(StoreCase):
    def test_the_database_file_is_created(self):
        self.assertTrue((self.store.root / "cache.db").exists())

    def test_the_database_file_is_0600(self):
        chemin = self.store.root / "cache.db"
        self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)

    def test_the_root_is_0700(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.store.root).st_mode), 0o700)

    def test_opening_twice_is_harmless(self):
        self.store.open()
        self.assertEqual(self.store.count_posts(self.home), 0)

    def test_using_it_closed_says_so(self):
        """Un cache jamais ouvert le DIT, plutôt que de lever une erreur de
        SQLite que rien ne rattache au cache."""
        magasin = Store(self.account, mode="clear", base=Path(self.tmp.name))
        with self.assertRaises(SocialStoreError):
            magasin.feeds()


class TestAPlatformIdentifierIsAString(StoreCase):
    """Le point qui sépare ce cache de celui du courriel."""

    def test_a_snowflake_identifier_round_trips(self):
        self.store.upsert_posts(self.home, [billet("109384720138476299")])
        rendu = self.store.list_posts(self.home)[0]
        self.assertEqual(rendu.post_id, "109384720138476299")

    def test_an_at_uri_identifier_round_trips(self):
        """Une autre plateforme nomme ses billets par une URI : rien ici ne
        doit supposer un nombre."""
        uri = "at://did:plc:exemple1234/app.bsky.feed.post/3kabcdefghij2"
        self.store.upsert_posts(self.home, [billet(uri)])
        self.assertEqual(self.store.list_posts(self.home)[0].post_id, uri)

    def test_two_feeds_may_hold_the_same_identifier(self):
        """Le même billet apparaît dans plusieurs fils ; la clé est la PAIRE
        fil + identifiant, comme un UID appartient à son dossier."""
        mentions = self.store.upsert_feed("mentions")
        self.store.upsert_posts(self.home, [billet("42")])
        self.store.upsert_posts(mentions, [billet("42")])
        self.assertEqual(self.store.count_posts(self.home), 1)
        self.assertEqual(self.store.count_posts(mentions), 1)

    def test_the_same_identifier_twice_updates_rather_than_doubles(self):
        self.store.upsert_posts(self.home, [billet("42", text="premier")])
        self.store.upsert_posts(self.home, [billet("42", text="corrigé")])
        billets = self.store.list_posts(self.home)
        self.assertEqual(len(billets), 1)
        self.assertEqual(billets[0].text, "corrigé")


class TestTheCursorIsOpaque(StoreCase):
    """Une plateforme pagine par « depuis tel identifiant », une autre par un
    jeton de continuation. Le cache garde ce qu'on lui donne et le rend tel
    quel."""

    def test_a_numeric_cursor_comes_back_unchanged(self):
        self.store.set_feed_state("home", cursor="109384720138476299")
        self.assertEqual(
            self.store.feed_state("home")["cursor"], "109384720138476299"
        )

    def test_a_token_cursor_comes_back_unchanged(self):
        jeton = "3kabcdefghij2::bafyreih6yuexemple"
        self.store.set_feed_state("home", cursor=jeton)
        self.assertEqual(self.store.feed_state("home")["cursor"], jeton)

    def test_a_feed_starts_without_a_cursor(self):
        """Rien à renvoyer à la plateforme la première fois : c'est ce qui
        distingue une première passe d'une reprise."""
        self.assertIsNone(self.store.feed_state("home")["cursor"])

    def test_an_unknown_field_is_refused(self):
        """Une faute de frappe écrirait en silence dans le vide."""
        with self.assertRaises(SocialStoreError):
            self.store.set_feed_state("home", curseur="x")


class TestWhatComesBack(StoreCase):
    def test_the_newest_post_comes_first(self):
        self.store.upsert_posts(
            self.home,
            [
                billet("1", quand=1000),
                billet("3", quand=3000),
                billet("2", quand=2000),
            ],
        )
        ordre = [p.post_id for p in self.store.list_posts(self.home)]
        self.assertEqual(ordre, ["3", "2", "1"])

    def test_the_list_is_paged(self):
        self.store.upsert_posts(
            self.home, [billet(str(n), quand=1000 + n) for n in range(10)]
        )
        page = self.store.list_posts(self.home, limit=4)
        self.assertEqual(len(page), 4)
        suite = self.store.list_posts(self.home, limit=4, offset=4)
        self.assertEqual(len(suite), 4)
        self.assertFalse(
            {p.post_id for p in page} & {p.post_id for p in suite}
        )

    def test_a_reply_remembers_what_it_answers(self):
        self.store.upsert_posts(self.home, [billet("2", reply_to="1")])
        self.assertEqual(self.store.get_post(self.home, "2").reply_to, "1")

    def test_a_boost_remembers_what_it_shares(self):
        self.store.upsert_posts(self.home, [billet("2", boost_of="9")])
        self.assertEqual(self.store.get_post(self.home, "2").boost_of, "9")

    def test_a_post_that_answers_nothing_says_so(self):
        self.store.upsert_posts(self.home, [billet("1")])
        self.assertEqual(self.store.get_post(self.home, "1").reply_to, "")

    def test_an_unknown_post_is_none(self):
        self.assertIsNone(self.store.get_post(self.home, "jamais-vu"))

    def test_the_feed_name_travels_with_the_post(self):
        """L'écran montre plusieurs fils ensemble : sans lui, une ligne ne
        dirait pas d'où elle vient."""
        self.store.upsert_posts(self.home, [billet("1")])
        self.assertEqual(self.store.list_posts(self.home)[0].feed, "home")


class TestTheAttachments(StoreCase):
    def test_they_come_back_as_they_went_in(self):
        pieces = [
            Media("https://i.exemple/1.png", "image", "Un graphique"),
            Media("https://i.exemple/2.mp4", "video", ""),
        ]
        self.store.upsert_posts(self.home, [billet("1", media=pieces)])
        rendu = self.store.get_post(self.home, "1").media
        self.assertEqual([m.url for m in rendu], [p.url for p in pieces])
        self.assertEqual(rendu[0].description, "Un graphique")

    def test_a_post_without_attachments_has_an_empty_list(self):
        self.store.upsert_posts(self.home, [billet("1")])
        self.assertEqual(self.store.get_post(self.home, "1").media, [])

    def test_a_damaged_column_loses_the_attachments_not_the_post(self):
        """Lever ici ferait disparaître tout le fil pour une colonne
        tronquée ; le billet reste lisible sans ses pièces."""
        from script.todo.social.store import _media_from_json

        self.assertEqual(_media_from_json("{pas du json"), [])
        self.assertEqual(_media_from_json('"une chaîne"'), [])


class TestTheCounters(StoreCase):
    """La même règle que pour le courriel : l'écran lit ces colonnes à chaque
    redessin, donc chaque geste les tient, et l'écriture en lot recompte."""

    def setUp(self):
        super().setUp()
        self.store.upsert_posts(
            self.home, [billet(str(n), quand=1000 + n) for n in range(3)]
        )

    def _etat(self):
        etat = self.store.feed_state("home")
        return etat["total"], etat["unseen"]

    def test_writing_posts_counts_them(self):
        self.assertEqual(self._etat(), (3, 3))

    def test_marking_one_seen_takes_one_off(self):
        self.store.mark_seen(self.home, "1")
        self.assertEqual(self._etat(), (3, 2))

    def test_marking_the_same_one_twice_moves_nothing(self):
        self.store.mark_seen(self.home, "1")
        self.store.mark_seen(self.home, "1")
        self.assertEqual(self._etat(), (3, 2))

    def test_marking_it_unseen_again_puts_it_back(self):
        self.store.mark_seen(self.home, "1")
        self.store.mark_seen(self.home, "1", seen=False)
        self.assertEqual(self._etat(), (3, 3))

    def test_marking_the_whole_feed_says_how_many_changed(self):
        self.store.mark_seen(self.home, "1")
        self.assertEqual(self.store.mark_all_seen(self.home), 2)
        self.assertEqual(self._etat(), (3, 0))

    def test_a_feed_already_read_changes_nothing(self):
        self.store.mark_all_seen(self.home)
        self.assertEqual(self.store.mark_all_seen(self.home), 0)

    def test_forgetting_an_unread_post_takes_it_off_both(self):
        self.store.forget_post(self.home, "1")
        self.assertEqual(self._etat(), (2, 2))

    def test_forgetting_a_read_post_leaves_the_unread_count(self):
        self.store.mark_seen(self.home, "1")
        self.store.forget_post(self.home, "1")
        self.assertEqual(self._etat(), (2, 2))

    def test_forgetting_an_unknown_post_is_harmless(self):
        self.store.forget_post(self.home, "jamais-vu")
        self.assertEqual(self._etat(), (3, 3))

    def test_a_pass_does_not_mark_a_post_unread_again(self):
        """`seen` appartient au lecteur, pas à la plateforme : une passe qui
        réécrit un billet ne doit pas défaire ce qu'il a lu."""
        self.store.mark_seen(self.home, "1")
        self.store.upsert_posts(self.home, [billet("1", text="corrigé")])
        self.assertTrue(self.store.get_post(self.home, "1").seen)
        self.assertEqual(self._etat(), (3, 2))

    def test_purging_the_feed_empties_the_counters(self):
        self.store.purge_feed("home")
        self.assertEqual(self._etat(), (0, 0))

    def test_purging_forgets_the_cursor(self):
        """Garder le curseur ferait reprendre la passe suivante après ce
        qu'on vient d'effacer : le fil resterait vide."""
        self.store.set_feed_state("home", cursor="abc")
        self.store.purge_feed("home")
        self.assertIsNone(self.store.feed_state("home")["cursor"])


class TestNothingReadableOnDisk(StoreCase):
    mode = "encrypted"

    def test_the_author_is_not_in_the_file(self):
        self.store.upsert_posts(self.home, [billet("1")])
        self.store.close()
        brut = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(b"ana@instance.exemple", brut)

    def test_the_text_is_not_in_the_file(self):
        self.store.upsert_posts(
            self.home, [billet("1", text="un secret bien à moi")]
        )
        self.store.close()
        brut = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn("un secret bien à moi".encode(), brut)

    def test_the_uri_is_not_in_the_file(self):
        self.store.upsert_posts(self.home, [billet("1")])
        self.store.close()
        brut = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(b"users/ana/statuses", brut)

    def test_an_attachment_description_is_not_in_the_file(self):
        """Une description d'image dit ce que l'image montre : la sceller
        avec le reste, ou le chiffrement ne couvre que la moitié du fil."""
        self.store.upsert_posts(
            self.home,
            [
                billet(
                    "1", media=[Media("https://i/1.png", "image", "chez moi")]
                )
            ],
        )
        self.store.close()
        brut = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(b"chez moi", brut)

    def test_it_all_reads_back(self):
        self.store.upsert_posts(self.home, [billet("1")])
        rendu = self.store.get_post(self.home, "1")
        self.assertEqual(rendu.author, "@ana@instance.exemple")
        self.assertEqual(rendu.text, "Bonjour le fil.")

    def test_the_date_stays_readable(self):
        """Elle sert à trier : la sceller obligerait à déchiffrer chaque
        ligne pour ordonner un fil de dix mille billets."""
        self.store.upsert_posts(self.home, [billet("1", quand=1_780_000_123)])
        self.store.close()
        self.store.open()
        self.assertEqual(
            self.store.list_posts(self.home)[0].created_at, 1_780_000_123
        )

    def test_a_wrong_key_does_not_read_the_text(self):
        self.store.upsert_posts(self.home, [billet("1")])
        self.store.close()
        autre = Store(
            self.account,
            mode="encrypted",
            key=new_key(),
            base=Path(self.tmp.name),
        )
        autre.open()
        self.addCleanup(autre.close)
        with self.assertRaises(Exception):
            autre.get_post(autre.upsert_feed("home"), "1")


class TestTheUriFingerprint(StoreCase):
    mode = "encrypted"

    def test_the_uri_is_not_in_the_file_but_the_post_is_findable(self):
        self.store.upsert_posts(self.home, [billet("1")])
        ligne = (
            self.store._db()
            .execute("SELECT uri_hash FROM posts WHERE post_id = '1'")
            .fetchone()
        )
        self.assertTrue(ligne["uri_hash"])
        self.assertNotIn("instance.exemple", ligne["uri_hash"])

    def test_a_post_without_uri_gets_no_fingerprint(self):
        """Hacher la chaîne vide donnerait la MÊME empreinte à tous : ils se
        reconnaîtraient les uns les autres."""
        self.store.upsert_posts(self.home, [billet("1", uri="")])
        ligne = (
            self.store._db()
            .execute("SELECT uri_hash FROM posts WHERE post_id = '1'")
            .fetchone()
        )
        self.assertIsNone(ligne["uri_hash"])

    def test_the_fingerprint_is_salted_by_the_cache_key(self):
        """Non salée, une empreinte d'URI publique se retrouve par
        dictionnaire, et la liste des comptes lus se reconstitue sans la
        clé."""
        autre = Store(
            self.account,
            mode="encrypted",
            key=new_key(),
            base=Path(tempfile.mkdtemp()),
        )
        autre.open()
        self.addCleanup(autre.close)
        self.assertNotEqual(
            self.store._uri_hash("https://a/b"), autre._uri_hash("https://a/b")
        )


class TestWhereItLives(unittest.TestCase):
    def setUp(self):
        self.account = account_from_preset(
            "perso",
            "@moi@i.exemple",
            "mastodon",
            base_url="https://i.exemple",
        )

    def test_a_clear_cache_lives_under_the_account_name(self):
        racine = cache_root(self.account, "clear", Path("/tmp/base"))
        self.assertEqual(racine, Path("/tmp/base/perso"))

    def test_an_ephemeral_cache_lives_under_the_process(self):
        racine = cache_root(self.account, "ephemeral", Path("/tmp/base"))
        self.assertIn(f"{EPHEMERAL_PREFIX}{os.getpid()}", str(racine))

    def test_the_sweep_leaves_the_mail_caches_alone(self):
        """Les deux caches partagent le dossier public des éphémères."""
        base = Path(tempfile.mkdtemp())
        courriel = base / "erplibre-mail-999999999"
        courriel.mkdir()
        (base / f"{EPHEMERAL_PREFIX}999999999").mkdir()
        self.assertEqual(sweep_orphan_ephemeral(base), 1)
        self.assertTrue(courriel.exists())

    def test_the_account_mode_wins_over_the_general_one(self):
        self.account.cache_mode = "encrypted"
        self.assertEqual(
            resolve_mode(self.account, lambda k, d=None: "clear"), "encrypted"
        )

    def test_an_unreadable_general_mode_falls_back_to_clear(self):
        """Un défaut illisible ne doit pas empêcher d'ouvrir le cache."""
        self.assertEqual(
            resolve_mode(self.account, lambda k, d=None: "n'importe quoi"),
            "clear",
        )


if __name__ == "__main__":
    unittest.main()
