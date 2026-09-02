#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Statistiques (phase 3), sans monter d'interface.

Les agrégats vivent dans `Store` — SQL, verrou et clés y sont déjà — et la
composition dans `stats.py`. Aucun test ici n'a besoin d'un terminal : une
erreur de calcul doit se voir comme une erreur de calcul, pas se perdre
derrière un écran qui ne s'affiche pas.
"""
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.stats import bars, build_report, humain, median, top
from script.todo.mail.store import MessageMeta, Store

JOUR = 86400
DEPART = 1_780_000_000


class TestPureHelpers(unittest.TestCase):
    def test_median_of_an_odd_count(self):
        self.assertEqual(median([1, 5, 100]), 5.0)

    def test_median_of_an_even_count_averages_the_middle(self):
        self.assertEqual(median([1, 3, 5, 7]), 4.0)

    def test_median_of_nothing_is_zero(self):
        self.assertEqual(median([]), 0.0)

    def test_the_median_resists_one_extreme_value(self):
        """La raison du choix : une moyenne suivrait le message répondu six
        mois plus tard, la médiane décrit ce qui arrive d'habitude."""
        self.assertEqual(median([60, 60, 60, 60, 10_000_000]), 60)

    def test_top_is_ordered_by_count(self):
        self.assertEqual(top({"b": 2, "c": 9}, 2), [("c", 9), ("b", 2)])

    def test_ties_break_on_the_address_so_the_order_is_stable(self):
        """Sans second critère, deux exécutions sur les mêmes données
        pourraient rendre un ordre différent — un écran qui bouge sans
        raison se lit comme un bogue."""
        self.assertEqual(top({"b": 2, "a": 2}, 2), [("a", 2), ("b", 2)])

    def test_bars_are_normalised_on_the_series_maximum(self):
        sorties = bars([("lun", 1, 0), ("mar", 10, 0)], largeur=10)
        self.assertEqual(len(sorties[1][2]), 10)

    def test_a_non_zero_count_always_keeps_one_block(self):
        """Une barre vide se lit « aucun message ». Sur une série où le
        maximum écrase tout, ce serait faux."""
        sorties = bars([("lun", 1, 0), ("mar", 10_000, 0)], largeur=10)
        self.assertEqual(sorties[0][2], "█")

    def test_bars_of_nothing_is_nothing(self):
        self.assertEqual(bars([]), [])

    def test_durations_are_said_the_way_people_say_them(self):
        self.assertEqual(
            (humain(300), humain(7200), humain(200_000), humain(0)),
            ("5 min", "2 h", "2 j", "—"),
        )


class StatsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")
        self.sent = self.store.upsert_folder("Sent", "Envoyés", "sent")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def msg(self, uid, jour, frm, to, flags="", msgid=None, irt="", size=1000):
        return MessageMeta(
            uid=uid,
            date=DEPART + jour * JOUR,
            size=size,
            flags=flags,
            msgid=msgid or f"<{uid}@x.ca>",
            frm=frm,
            to=to,
            subject="s",
            snippet="",
            in_reply_to=irt,
        )

    def remplir(self):
        self.store.upsert_messages(
            self.inbox,
            [
                self.msg(1, 0, "Alice <a@x.ca>", "moi@x.ca", msgid="<o@x.ca>"),
                self.msg(2, 0, "Bob <b@x.ca>", "moi@x.ca", "\\Seen"),
                self.msg(3, 1, "ALICE <A@X.CA>", "moi@x.ca", "\\Seen"),
            ],
        )
        self.store.upsert_messages(
            self.sent,
            [
                self.msg(
                    10,
                    2,
                    "moi@x.ca",
                    "Alice <a@x.ca>",
                    "\\Seen",
                    irt="<o@x.ca>",
                )
            ],
        )


class TestVolume(StatsCase):
    def test_one_line_per_day_with_counts_and_bytes(self):
        self.remplir()
        self.assertEqual(self.store.stats_volume("day")[0][1:], (2, 2000))

    def test_months_group_what_days_separate(self):
        self.remplir()
        self.assertEqual(len(self.store.stats_volume("month")), 1)

    def test_an_unreadable_date_is_counted_apart_not_placed_in_1970(self):
        """`parse_fetch_headers` met la date à 0 plutôt que de perdre le
        message. Les ranger au 1er janvier 1970 fabriquerait un pic qui n'a
        jamais eu lieu — donc exclus du volume, et comptés à part pour
        qu'on puisse le DIRE à l'écran."""
        self.remplir()
        sans_date = self.msg(99, 0, "c@x.ca", "moi@x.ca")
        sans_date.date = 0
        self.store.upsert_messages(self.inbox, [sans_date])
        self.assertEqual(self.store.stats_undated(), 1)
        self.assertNotIn(
            "1970", " ".join(t for t, _, _ in self.store.stats_volume("day"))
        )

    def test_the_period_filter_excludes_what_is_outside(self):
        self.remplir()
        depuis = DEPART + JOUR
        total = sum(
            n for _, n, _ in self.store.stats_volume("day", since=depuis)
        )
        self.assertEqual(total, 2)


class TestFolders(StatsCase):
    def test_each_folder_reports_count_unseen_and_size(self):
        self.remplir()
        boite = next(
            d for d in self.store.stats_folders() if d["name"] == "INBOX"
        )
        self.assertEqual(
            (boite["count"], boite["unseen"], boite["size"]), (3, 1, 3000)
        )

    def test_an_empty_folder_still_appears(self):
        """Un dossier vide EST une information. Une jointure interne
        l'aurait fait disparaître du classement."""
        self.store.upsert_folder("Archives", "Archives", None)
        noms = [d["name"] for d in self.store.stats_folders()]
        self.assertIn("Archives", noms)


class TestCorrespondents(StatsCase):
    def test_the_same_person_is_counted_once_whatever_the_case(self):
        """Une même adresse écrite en majuscules et en minuscules désigne
        une seule personne : sans repli de casse, elle occuperait deux
        lignes du classement."""
        self.remplir()
        self.assertEqual(self.store.stats_correspondents("from")["a@x.ca"], 2)

    def test_recipients_are_counted_separately_from_senders(self):
        self.remplir()
        self.assertEqual(self.store.stats_correspondents("to")["moi@x.ca"], 3)

    def test_a_display_name_without_an_address_is_ignored(self):
        self.store.upsert_messages(
            self.inbox, [self.msg(50, 0, "Sans adresse", "moi@x.ca")]
        )
        self.assertNotIn(
            "sans adresse", self.store.stats_correspondents("from")
        )


class TestReplyDelays(StatsCase):
    def test_a_reply_yields_the_delay_that_separates_them(self):
        self.remplir()
        self.assertEqual(self.store.stats_reply_delays(), [2 * JOUR])

    def test_a_message_answering_nobody_yields_nothing(self):
        self.store.upsert_messages(
            self.inbox, [self.msg(1, 0, "a@x.ca", "moi@x.ca")]
        )
        self.assertEqual(self.store.stats_reply_delays(), [])

    def test_a_negative_delay_is_dropped(self):
        """Une date d'en-tête peut mentir. Une réponse antérieure à son
        original n'est pas une réponse rapide, c'est une donnée fausse — et
        une seule suffirait à tirer la médiane vers le bas."""
        self.store.upsert_messages(
            self.inbox,
            [
                self.msg(1, 10, "a@x.ca", "moi@x.ca", msgid="<o@x.ca>"),
                self.msg(2, 1, "moi@x.ca", "a@x.ca", irt="<o@x.ca>"),
            ],
        )
        self.assertEqual(self.store.stats_reply_delays(), [])


class TestBuildReport(StatsCase):
    def test_it_assembles_every_piece(self):
        self.remplir()
        rapport = build_report(self.store)
        self.assertEqual(rapport.total, 4)
        self.assertEqual(rapport.total_size, 4000)
        self.assertEqual(rapport.reply_count, 1)
        self.assertTrue(rapport.senders)
        self.assertTrue(rapport.volume)

    def test_the_unseen_share_is_a_ratio_not_a_count(self):
        self.remplir()
        self.assertAlmostEqual(build_report(self.store).unseen_share, 0.25)

    def test_a_share_of_nothing_is_zero_not_a_division_error(self):
        self.assertEqual(build_report(self.store).unseen_share, 0.0)

    def test_filtering_on_a_folder_keeps_only_that_folder(self):
        """Le filtre lisait une clé que `stats_folders` ne renvoyait pas :
        il ne matchait jamais et retombait en silence sur TOUS les
        dossiers, en affichant le contraire de ce qu'on demandait."""
        self.remplir()
        rapport = build_report(self.store, folder_id=self.inbox)
        self.assertEqual([d["name"] for d in rapport.folders], ["INBOX"])


if __name__ == "__main__":
    unittest.main()
