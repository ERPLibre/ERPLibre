#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import dataclasses
import html
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from script.todo import todo_i18n
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import report
from script.todo.mail.rules.model import (
    STATS_BLOCK_VARIABLES,
    STATS_VARIABLES,
    Action,
    MediaRef,
    RuleError,
    TemplateError,
)
from script.todo.mail.rules.report import (
    NO_VALUE,
    Bucket,
    build_data,
    collect_mailbox,
    day_starts,
    format_delay,
    html_table,
    mailbox_from_dict,
    mailbox_to_dict,
    render_stats_reply,
    render_subject,
    round_delay,
    snapshot_key,
    text_table,
    week_starts,
)
from script.todo.mail.rules.storage import ReportSettings
from script.todo.mail.store import MessageMeta, Store
from script.todo.todo_i18n import TRANSLATIONS

COMPTE = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"
DENIS = "denis.tri@example.org"
HEURE = 3600
JOUR = 86400
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def local(*parts):
    """L'époque d'une date locale (a, m, j[, h, min])."""
    full = list(parts) + [0] * (5 - len(parts))
    return int(time.mktime((*full, 0, 0, 0, -1)))


def fr(key):
    return TRANSLATIONS[key]["fr"]


class ReportCase(unittest.TestCase):
    """Cache clair temporaire, fuseau de Toronto, interface en français."""

    tz = "America/Toronto"

    def setUp(self):
        self._old_tz = os.environ.get("TZ")
        os.environ["TZ"] = self.tz
        time.tzset()
        self._old_lang = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.tmp = tempfile.TemporaryDirectory()
        account = account_from_preset("perso", COMPTE, "generic")
        self.store = Store(account, mode="clear", base=Path(self.tmp.name))
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "INBOX", "inbox")
        self.sent = self.store.upsert_folder("Sent", "Sent")
        self.uid = 0
        # Un mercredi : la semaine courante a commencé lundi 26.
        self.now = local(2026, 10, 28, 10)
        self.settings = ReportSettings()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        todo_i18n._current_lang = self._old_lang
        if self._old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._old_tz
        time.tzset()

    def recevoir(self, at, *, frm=CAROLE, flags="", subject="Sujet"):
        """Un message reçu à `at` ; rend son Message-ID."""
        self.uid += 1
        msgid = f"<m{self.uid}@example.org>"
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=self.uid,
                    date=at,
                    size=10,
                    flags=flags,
                    msgid=msgid,
                    frm=frm,
                    to=COMPTE,
                    subject=subject,
                    snippet="",
                    received_at=at,
                )
            ],
        )
        return msgid

    def repondre(self, msgid, at, subject="Re: Sujet"):
        self.uid += 1
        self.store.upsert_messages(
            self.sent,
            [
                MessageMeta(
                    uid=self.uid,
                    date=at,
                    size=10,
                    flags="\\Seen",
                    msgid=f"<r{self.uid}@example.org>",
                    frm=COMPTE,
                    to=CAROLE,
                    subject=subject,
                    snippet="",
                    in_reply_to=msgid,
                )
            ],
        )

    def mailbox(self, **changes):
        settings = dataclasses.replace(self.settings, **changes)
        return collect_mailbox(self.store, settings, now=self.now)

    def data(self, sender=CAROLE, **changes):
        settings = dataclasses.replace(self.settings, **changes)
        return build_data(self.store, settings, now=self.now, sender=sender)

    def render(
        self, body, fmt="markdown", sender=CAROLE, images=(), media=None
    ):
        action = Action(
            kind="stats", format=fmt, body=body, images=list(images)
        )
        return render_stats_reply(
            action, media or {}, "example.org", self.data(sender)
        )


class TestCalendar(ReportCase):
    def test_day_starts_are_local_midnights(self):
        starts = day_starts(self.now, 3)
        self.assertEqual(len(starts), 3)
        for start in starts:
            moment = time.localtime(start)
            self.assertEqual((moment.tm_hour, moment.tm_min), (0, 0))
        self.assertEqual(
            time.strftime("%Y-%m-%d", time.localtime(starts[-1])),
            "2026-10-27",
        )
        self.assertEqual(starts[1] - starts[0], JOUR)

    def test_today_is_never_in_the_report(self):
        self.recevoir(local(2026, 10, 28, 8))
        mailbox = self.mailbox()
        self.assertEqual(mailbox.received_total, 0)
        self.assertEqual(sum(b.received for b in mailbox.days), 0)
        self.assertEqual(mailbox.period_end, local(2026, 10, 28))

    def test_the_current_week_is_never_in_the_report(self):
        self.recevoir(local(2026, 10, 26, 9))
        mailbox = self.mailbox()
        self.assertEqual(sum(b.received for b in mailbox.weeks), 0)
        self.assertEqual(mailbox.weeks[-1].label, "2026-W43")
        self.assertEqual(mailbox.days[-2].received, 1)

    def test_a_message_late_in_the_evening_stays_on_its_local_day(self):
        self.recevoir(local(2026, 10, 26, 23, 30))
        days = {b.label: b.received for b in self.mailbox().days}
        self.assertEqual(days["2026-10-26"], 1)
        self.assertEqual(days["2026-10-27"], 0)

    def test_a_day_of_twenty_five_hours_at_the_dst_change(self):
        self.now = local(2026, 11, 3, 10)
        starts = day_starts(self.now, 2)
        self.assertEqual(starts[1] - starts[0], 25 * HEURE)
        self.recevoir(local(2026, 11, 1, 23, 30))
        days = {b.label: b.received for b in self.mailbox(days=2).days}
        self.assertEqual(days, {"2026-11-01": 1, "2026-11-02": 0})

    def test_iso_weeks_start_on_local_monday(self):
        starts = week_starts(self.now, 2)
        for start in starts:
            moment = time.localtime(start)
            self.assertEqual(
                (moment.tm_wday, moment.tm_hour, moment.tm_min), (0, 0, 0)
            )
        weeks = self.mailbox(weeks=2).weeks
        self.assertEqual([w.label for w in weeks], ["2026-W42", "2026-W43"])
        self.assertEqual(
            [w.first_day for w in weeks], ["2026-10-12", "2026-10-19"]
        )
        self.assertEqual(week_starts(self.now, 0), [])

    def test_new_year_days_fall_in_iso_week_53_of_2026(self):
        self.now = local(2027, 1, 6, 10)
        self.recevoir(local(2027, 1, 1, 12))
        weeks = self.mailbox(weeks=1).weeks
        self.assertEqual(weeks[0].label, "2026-W53")
        self.assertEqual(weeks[0].first_day, "2026-12-28")
        self.assertEqual(weeks[0].received, 1)

    def test_zero_weeks_gives_no_weekly_table(self):
        data = self.data(weeks=0)
        self.assertEqual(data.mailbox.weeks, [])
        vals = report.values(data)
        self.assertEqual(vals["rapport_semaines"], ("", ""))
        self.assertNotIn(fr("mail_stats_report_col_week"), vals["rapport"][0])
        self.assertEqual(vals["semaines"][0], "0")


class TestMailboxActivity(ReportCase):
    def test_totals_cover_the_daily_window_only(self):
        self.recevoir(local(2026, 10, 27, 9))
        self.recevoir(local(2026, 10, 15, 9))
        mailbox = self.mailbox()
        self.assertEqual(mailbox.received_total, 1)
        self.assertEqual(sum(b.received for b in mailbox.weeks), 1)
        vals = report.values(self.data())
        self.assertEqual(vals["recus_total"][0], "1")
        self.assertEqual(vals["periode_debut"][0], "2026-10-21")
        self.assertEqual(vals["periode_fin"][0], "2026-10-27")

    def test_lus_and_repondus_never_exceed_recus(self):
        for day in range(20, 28):
            seen = self.recevoir(local(2026, 10, day, 9), flags="\\Seen")
            self.repondre(seen, local(2026, 10, day, 11))
            self.repondre(seen, local(2026, 10, day, 12))
            self.recevoir(local(2026, 10, day, 10), flags="\\Answered")
        mailbox = self.mailbox()
        for bucket in mailbox.days + mailbox.weeks:
            with self.subTest(bucket=bucket.label):
                self.assertLessEqual(bucket.seen, bucket.received)
                self.assertLessEqual(bucket.answered, bucket.received)

    def test_mailbox_mean_delay_over_the_window(self):
        for index, hours in enumerate((1, 2, 3, 4, 5)):
            msgid = self.recevoir(local(2026, 10, 20 + index, 9))
            self.repondre(
                msgid, local(2026, 10, 20 + index, 9) + hours * HEURE
            )
        old = self.recevoir(local(2026, 8, 1, 9))
        self.repondre(old, local(2026, 8, 20, 9))
        mailbox = self.mailbox()
        self.assertEqual(mailbox.delay_count, 5)
        self.assertEqual(mailbox.delay_mean, 3 * HEURE)
        vals = report.values(self.data(sender=None))
        self.assertEqual(vals["delai_moyen_boite"][0], "3 h")
        self.assertIn(
            fr("mail_stats_report_mailbox_delay").replace("{n}", "30")
            + " 3 h",
            vals["rapport"][0],
        )

    def test_mailbox_delay_hidden_below_the_minimum_count(self):
        for index in range(4):
            msgid = self.recevoir(local(2026, 10, 20 + index, 9))
            self.repondre(msgid, local(2026, 10, 20 + index, 11))
        vals = report.values(self.data(sender=None))
        self.assertEqual(vals["delai_moyen_boite"][0], NO_VALUE)
        self.assertIn(
            fr("mail_stats_report_mailbox_few").replace("{n}", "30"),
            vals["rapport"][0],
        )

    def test_round_delay_cases(self):
        cases = {
            2 * 60: 5 * 60,
            47 * 60: 45 * 60,
            3 * HEURE + 8 * 60: 3 * HEURE + 15 * 60,
            2 * JOUR + 4 * HEURE + 20 * 60: 2 * JOUR + 4 * HEURE,
        }
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(round_delay(seconds), expected)


class TestRequester(ReportCase):
    def test_requester_mean_delay_counts_only_that_sender(self):
        first = self.recevoir(local(2026, 10, 20, 9))
        second = self.recevoir(local(2026, 10, 21, 9))
        other = self.recevoir(local(2026, 10, 22, 9), frm=BRUNO)
        self.repondre(first, local(2026, 10, 20, 11))
        self.repondre(second, local(2026, 10, 21, 13))
        self.repondre(other, local(2026, 10, 23, 9))
        data = self.data(sender="Carole.Regle@Example.ORG")
        self.assertEqual(data.requester.received, 2)
        self.assertEqual(data.requester.answered, 2)
        vals = report.values(data)
        self.assertEqual(vals["delai_moyen"][0], "3 h")
        self.assertEqual(vals["demandeur_recus"][0], "2")
        self.assertIn(
            fr("mail_stats_report_based_on").replace("{n}", "2"),
            vals["rapport"][0],
        )

    def test_requester_without_answered_message_gives_the_neutral_phrase(self):
        self.recevoir(local(2026, 10, 20, 9))
        vals = report.values(self.data())
        self.assertEqual(vals["delai_moyen"][0], NO_VALUE)
        self.assertIn(
            fr("mail_stats_report_requester_none").replace("{n}", "30"),
            vals["rapport"][0],
        )

    def test_answered_flag_without_sent_reply_counts_for_the_requester(self):
        self.recevoir(local(2026, 10, 20, 9), flags="\\Answered")
        vals = report.values(self.data())
        self.assertEqual(vals["demandeur_repondus"][0], "1")
        self.assertEqual(vals["delai_moyen"][0], NO_VALUE)

    def test_preview_without_requester_omits_its_line(self):
        msgid = self.recevoir(local(2026, 10, 20, 9))
        self.repondre(msgid, local(2026, 10, 20, 11))
        data = self.data(sender=None)
        self.assertIsNone(data.requester)
        vals = report.values(data)
        text = vals["rapport"][0]
        for key in (
            "mail_stats_report_requester_delay",
            "mail_stats_report_requester_none",
        ):
            self.assertNotIn(fr(key).replace("{n}", "30")[:12], text)
        self.assertEqual(vals["delai_moyen"][0], NO_VALUE)
        self.assertEqual(vals["demandeur_recus"][0], NO_VALUE)

    def test_an_unreadable_from_gives_an_empty_requester(self):
        self.recevoir(local(2026, 10, 20, 9))
        data = self.data(sender="")
        self.assertEqual(
            (data.requester.received, data.requester.delays), (0, [])
        )


class TestSnapshot(ReportCase):
    def test_snapshot_round_trip_and_key_mismatch(self):
        msgid = self.recevoir(local(2026, 10, 20, 9), flags="\\Seen")
        self.repondre(msgid, local(2026, 10, 20, 11))
        mailbox = self.mailbox()
        key = snapshot_key(self.settings, self.now)
        self.assertEqual(key["day"], "2026-10-28")
        stored = mailbox_to_dict(mailbox, key)
        self.assertEqual(mailbox_from_dict(stored, key), mailbox)
        tomorrow = snapshot_key(self.settings, self.now + JOUR)
        self.assertIsNone(mailbox_from_dict(stored, tomorrow))
        other = snapshot_key(
            dataclasses.replace(self.settings, days=8), self.now
        )
        self.assertIsNone(mailbox_from_dict(stored, other))
        broken = mailbox_to_dict(mailbox, key)
        broken["mailbox"]["days"][0][3] = "trois"
        self.assertIsNone(mailbox_from_dict(broken, key))
        missing = mailbox_to_dict(mailbox, key)
        del missing["mailbox"]["delay_mean"]
        self.assertIsNone(mailbox_from_dict(missing, key))
        self.assertIsNone(mailbox_from_dict(None, key))
        self.assertIsNone(mailbox_from_dict({"key": key}, key))


class TestFormatting(ReportCase):
    def test_format_delay_cases(self):
        cases = {
            59: "< 1 min",
            45 * 60: "45 min",
            3 * HEURE: "3 h",
            3 * HEURE + 5 * 60: "3 h 05 min",
            2 * JOUR + 4 * HEURE: "2 j 4 h",
            2 * JOUR: "2 j",
        }
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(format_delay(seconds), expected)
        self.assertEqual(format_delay(2 * JOUR + 4 * HEURE, "en"), "2 d 4 h")
        self.assertEqual(format_delay(None), NO_VALUE)

    def buckets(self):
        return [
            Bucket("2026-W42", 0, "2026-10-12", 3, 3, 2),
            Bucket("2026-W43", 0, "2026-10-19", 123, 45, 6),
        ]

    def test_text_table_is_aligned(self):
        for kind in ("day", "week"):
            with self.subTest(kind=kind):
                lines = text_table(self.buckets(), kind, "").splitlines()
                self.assertEqual(len(lines), 4)
                self.assertEqual(len({len(line) for line in lines}), 1)
                self.assertTrue(lines[-1].startswith("Total"))

    def test_weekly_totals_fall_under_their_columns(self):
        lines = text_table(self.buckets(), "week", "").splitlines()
        head, total = lines[0], lines[-1]
        for key, value in (
            ("mail_stats_report_col_received", "126"),
            ("mail_stats_report_col_seen", "48"),
            ("mail_stats_report_col_answered", "8"),
        ):
            label = fr(key)
            end = head.index(label) + len(label)
            self.assertEqual(total[end - len(value) : end], value)
        self.assertIn(
            '<th colspan="2">Total</th>',
            html_table(self.buckets(), "week", ""),
        )
        self.assertIn("<th>Total</th>", html_table(self.buckets(), "day", ""))

    def test_html_table_escapes_labels(self):
        buckets = [Bucket("<b>&", 0, "<i>", 1, 1, 1)]
        with mock.patch.dict(
            TRANSLATIONS,
            {"mail_stats_report_col_day": {"fr": "J<o>", "en": "D<a>"}},
        ):
            table = html_table(buckets, "week", "")
            day_table = html_table(buckets, "day", "")
        self.assertIn("&lt;b&gt;&amp;", table)
        self.assertIn("&lt;i&gt;", table)
        self.assertNotIn("<b>", table)
        self.assertIn("<th>J&lt;o&gt;</th>", day_table)

    def test_the_report_states_its_timezone(self):
        vals = report.values(self.data())
        self.assertEqual(vals["date_rapport"][0], "2026-10-28 10:00 -0400")
        zone = fr("mail_stats_report_local_time").replace("{tz}", "UTC-04:00")
        self.assertIn(zone, vals["rapport"][0])
        self.assertIn(html.escape(zone), vals["rapport"][1])
        self.assertIn(
            f"{fr('mail_stats_report_generated')} 2026-10-28 10:00 -0400",
            vals["rapport"][0],
        )


class TestRender(ReportCase):
    def setUp(self):
        super().setUp()
        msgid = self.recevoir(local(2026, 10, 26, 9), flags="\\Seen")
        self.repondre(msgid, local(2026, 10, 26, 11))

    def test_markdown_body_gets_an_html_table_and_a_text_table(self):
        out = self.render("Bonjour,\n\n{{rapport}}\n")
        self.assertIn("<table", out.html)
        self.assertNotIn("{{", out.html)
        self.assertNotIn("ZSTATS", out.html + out.text)
        self.assertIn("Jour        Reçus  Lus  Répondus", out.text)
        self.assertNotIn("<table", out.text)

    def test_html_body_gets_the_table_and_a_text_version(self):
        out = self.render("<p>Bonjour,</p>\n<p>{{rapport}}</p>", fmt="html")
        self.assertIn("<table", out.html)
        self.assertNotIn("<p><table", out.html.replace("\n", ""))
        self.assertIn("Jour        Reçus  Lus  Répondus", out.text)
        self.assertIn("Bonjour,", out.text)

    def test_text_body_gets_the_text_table_and_no_html(self):
        out = self.render("Bonjour,\n\n{{rapport_jours}}\n", fmt="text")
        self.assertIsNone(out.html)
        self.assertIn("Total ", out.text)
        self.assertIn(
            fr("mail_stats_report_days_title").replace("{n}", "7"), out.text
        )

    def test_scalar_values_are_escaped_in_html(self):
        real = report.values

        def double(data):
            vals = real(data)
            text = "2026-10-28 <script>"
            vals["date_rapport"] = (text, html.escape(text))
            return vals

        with mock.patch.object(report, "values", double):
            out = self.render("Le {{date_rapport}}", fmt="markdown")
        self.assertIn("&lt;script&gt;", out.html)
        self.assertNotIn("<script>", out.html)
        self.assertIn("2026-10-28 <script>", out.text)
        for name, (text, markup_html) in real(self.data()).items():
            if name not in STATS_BLOCK_VARIABLES:
                with self.subTest(name=name):
                    self.assertEqual(markup_html, html.escape(text))

    def test_spaces_inside_braces_are_tolerated(self):
        out = self.render("Reçus : {{ recus_total }}", fmt="text")
        self.assertEqual(out.text, "Reçus : 1")

    def test_an_unknown_variable_raises_template_error_at_render(self):
        with self.assertRaises(TemplateError):
            self.render("{{inconnue}}")

    def test_a_missing_image_raises_a_plain_rule_error(self):
        ref = MediaRef("logo.png", "0" * 64, "image/png")
        with self.assertRaises(RuleError) as caught:
            self.render("{{rapport}}", images=[ref])
        self.assertNotIsInstance(caught.exception, TemplateError)

    def test_a_block_inline_with_text_closes_the_paragraph(self):
        out = self.render("Voici :\n{{rapport}}")
        document = out.html
        self.assertNotIn("<p></p>", document.replace("\n", ""))
        depth = 0
        for index in range(len(document)):
            if document.startswith("<p>", index) or document.startswith(
                "<p ", index
            ):
                depth += 1
            elif document.startswith("</p>", index):
                depth -= 1
            elif document.startswith("<table", index):
                self.assertEqual(depth, 0)
            self.assertIn(depth, (0, 1))
        self.assertIn("Voici :", document)

    def test_a_block_inside_a_tag_is_refused(self):
        with self.assertRaises(TemplateError):
            self.render('<p title="{{rapport}}">x</p>', fmt="html")
        out = self.render('<p title="{{jours}}">x</p>', fmt="html")
        self.assertIn('title="7"', out.html)

    def test_a_literal_double_brace_without_close_stays_text(self):
        out = self.render("a {{ b et {c}", fmt="text")
        self.assertEqual(out.text, "a {{ b et {c}")

    def test_images_still_go_inline_with_variables(self):
        import hashlib

        ref = MediaRef(
            "logo.png", hashlib.sha256(PNG).hexdigest(), "image/png"
        )
        out = self.render(
            '<p><img src="logo.png"></p>\n<p>{{rapport}}</p>',
            fmt="html",
            images=[ref],
            media={"logo.png": PNG},
        )
        self.assertEqual(len(out.inline), 1)
        self.assertEqual(out.attachments, [])
        self.assertIn("cid:", out.html)
        self.assertIn("<table", out.html)

    def test_subject_takes_scalars_then_the_received_subject(self):
        data = self.data()
        subject = render_subject(
            "Demande\r\n de chiffres", "{{ jours }} jours : {subject}", data
        )
        self.assertEqual(subject, "7 jours : Demande de chiffres")
        self.assertEqual(render_subject("Demande", "", data), "Auto: Demande")

    def test_a_block_in_the_subject_is_refused(self):
        with self.assertRaises(TemplateError):
            render_subject("Demande", "Voir {{rapport}}", self.data())
        with self.assertRaises(TemplateError):
            render_subject("Demande", "{{inconnue}}", self.data())

    def test_the_report_names_no_correspondent(self):
        for frm, subject in (
            (DENIS, "Contrat confidentiel"),
            (BRUNO, "Facture privée"),
        ):
            msgid = self.recevoir(
                local(2026, 10, 22, 9), frm=frm, subject=subject
            )
            self.repondre(msgid, local(2026, 10, 22, 15), "Re: " + subject)
        self.recevoir(local(2026, 10, 23, 9), subject="Ma demande")
        body = "".join("{{" + name + "}}\n\n" for name in STATS_VARIABLES)
        out = self.render(body, sender=CAROLE)
        for rendered in (out.text, out.html):
            for secret in (
                DENIS,
                BRUNO,
                CAROLE,
                "@",
                "Contrat",
                "Facture",
                "Ma demande",
                "Sujet",
            ):
                self.assertNotIn(secret, rendered)

    def test_report_lang_en_uses_english_labels_under_a_french_interface(self):
        settings = dataclasses.replace(self.settings, lang="en")
        data = build_data(self.store, settings, now=self.now, sender=CAROLE)
        text = report.values(data)["rapport"][0]
        self.assertIn("Activity over the last 7 days", text)
        self.assertIn("Day         Received  Read  Answered", text)
        self.assertNotIn("Reçus", text)


if __name__ == "__main__":
    unittest.main()
