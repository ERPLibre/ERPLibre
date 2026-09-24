#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Modes d'affichage de la liste, dont le regroupement par fil.

Le regroupement est une fonction pure sur des métadonnées : il se vérifie
sans monter d'interface, et une erreur d'ordre doit se lire comme telle.
"""
import unittest

from script.todo.mail.store import MessageMeta
from script.todo.mail.tui_text import (
    LIST_MODES,
    group_threads,
    next_list_mode,
    only_unread,
)


def meta(uid, date, msgid_hash="", in_reply_to_hash="", flags=""):
    return MessageMeta(
        uid=uid,
        date=date,
        size=1,
        flags=flags,
        msgid=f"<{uid}@e.ca>",
        frm="a@e.ca",
        to="b@e.ca",
        subject=f"s{uid}",
        snippet="",
        msgid_hash=msgid_hash,
        in_reply_to_hash=in_reply_to_hash,
    )


class TestModes(unittest.TestCase):
    def test_the_key_cycles_and_wraps(self):
        vus = []
        courant = LIST_MODES[0]
        for _ in range(len(LIST_MODES)):
            courant = next_list_mode(courant)
            vus.append(courant)
        self.assertEqual(vus[-1], LIST_MODES[0])
        self.assertEqual(len(set(vus)), len(LIST_MODES))

    def test_an_unknown_mode_falls_back_to_the_first(self):
        """Un mode retenu par une version antérieure ne doit pas bloquer la
        touche sur une valeur que plus rien ne comprend."""
        self.assertEqual(next_list_mode("inexistant"), LIST_MODES[0])


class TestGroupThreads(unittest.TestCase):
    def test_a_reply_sits_under_the_message_it_answers(self):
        racine = meta(1, 100, msgid_hash="A")
        reponse = meta(2, 200, msgid_hash="B", in_reply_to_hash="A")
        self.assertEqual(
            [(m.uid, n) for m, n in group_threads([racine, reponse])],
            [(1, 0), (2, 1)],
        )

    def test_replies_are_ordered_by_date_under_their_root(self):
        racine = meta(1, 100, msgid_hash="A")
        tard = meta(3, 300, msgid_hash="C", in_reply_to_hash="A")
        tot = meta(2, 200, msgid_hash="B", in_reply_to_hash="A")
        self.assertEqual(
            [m.uid for m, _ in group_threads([racine, tard, tot])],
            [1, 2, 3],
        )

    def test_roots_keep_the_order_they_arrived_in(self):
        """Activer les fils ne doit pas rebattre la liste entière : les
        racines gardent l'ordre de la vue à plat."""
        a = meta(1, 300, msgid_hash="A")
        b = meta(2, 200, msgid_hash="B")
        self.assertEqual([m.uid for m, _ in group_threads([a, b])], [1, 2])

    def test_an_orphan_reply_stays_visible_as_a_root(self):
        """Son original est hors de la sélection — dans un autre dossier,
        ou plus ancien que la page. La masquer ferait disparaître un
        message que les autres modes affichent."""
        orpheline = meta(9, 100, msgid_hash="Z", in_reply_to_hash="ABSENT")
        self.assertEqual(
            [(m.uid, n) for m, n in group_threads([orpheline])], [(9, 0)]
        )

    def test_a_message_answering_itself_does_not_vanish(self):
        """Un en-tête peut désigner son propre message. Sans garde, il
        deviendrait son propre enfant et ne serait jamais affiché."""
        boucle = meta(5, 100, msgid_hash="A", in_reply_to_hash="A")
        self.assertEqual([m.uid for m, _ in group_threads([boucle])], [5])

    def test_nothing_is_lost_whatever_the_shape(self):
        """La propriété qui compte : le regroupement RÉORDONNE, il ne
        supprime pas."""
        metas = [
            meta(1, 100, msgid_hash="A"),
            meta(2, 200, msgid_hash="B", in_reply_to_hash="A"),
            meta(3, 300, msgid_hash="C", in_reply_to_hash="INCONNU"),
            meta(4, 400),
        ]
        self.assertEqual(
            sorted(m.uid for m, _ in group_threads(metas)), [1, 2, 3, 4]
        )

    def test_messages_without_hashes_are_all_roots(self):
        """Un cache d'avant la v2 n'a aucune empreinte : le mode fil doit
        s'y comporter comme la vue à plat, pas rendre une liste vide."""
        metas = [meta(1, 100), meta(2, 200)]
        self.assertEqual([n for _, n in group_threads(metas)], [0, 0])


class TestOnlyUnread(unittest.TestCase):
    def test_it_keeps_only_the_unread(self):
        lus = meta(1, 100, flags="\\Seen")
        neufs = meta(2, 200, flags="")
        self.assertEqual([m.uid for m in only_unread([lus, neufs])], [2])


if __name__ == "__main__":
    unittest.main()
