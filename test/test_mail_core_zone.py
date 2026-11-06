#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le fuseau du noyau : `zone.local_zone` et le calendrier du rapport de
statistiques, dans le fuseau du processus ou dans celui que passe
l'appelant.

Les références « d'avant » (`time.mktime`, `time.localtime`,
`time.strftime`) sont copiées ici : le calendrier en `tzinfo` doit rendre
exactement les mêmes minuits, dates et textes.

N'importe que la bibliothèque standard et `erplibre_mail_core`.
"""

import calendar
import datetime
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core import i18n, zone  # noqa: E402
from erplibre_mail_core.catalog import CATALOG  # noqa: E402
from erplibre_mail_core.rules import report  # noqa: E402

ZONES = (
    "America/Toronto",
    "Europe/Paris",
    "Australia/Sydney",
    "Asia/Kolkata",
    "America/Santiago",
    "America/Havana",
)
ZONEINFO_DIR = Path("/usr/share/zoneinfo")
# Un instant d'été et un instant d'hiver de l'hémisphère nord, en UTC.
NOW_ETE = calendar.timegm((2025, 7, 15, 12, 0, 0))
NOW_HIVER = calendar.timegm((2025, 1, 15, 12, 0, 0))
# Le premier instant de l'année que parcourent les comparaisons.
DEBUT_2025 = calendar.timegm((2025, 1, 1, 0, 0, 0))


def a_le_fuseau(nom: str) -> bool:
    return (ZONEINFO_DIR / nom).is_file()


def _mktime_midnight(day: datetime.date) -> int:
    return int(time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1)))


def _localtime_date(epoch: int) -> datetime.date:
    local = time.localtime(epoch)
    return datetime.date(local.tm_year, local.tm_mon, local.tm_mday)


def _strftime_local(epoch: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M %z", time.localtime(epoch))


class TzCase(unittest.TestCase):
    """Pose `TZ` pour un test et le rétablit, `time.tzset` compris."""

    def setUp(self):
        ancien = os.environ.get("TZ")

        def retablir():
            if ancien is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = ancien
            time.tzset()

        self.addCleanup(retablir)

    def poser(self, valeur):
        if valeur is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = valeur
        time.tzset()


class TestLocalZone(TzCase):
    def test_local_zone_follows_tz(self):
        self.poser("America/Toronto")
        self.assertEqual(zone.local_zone().key, "America/Toronto")
        self.poser(":Europe/Paris")
        self.assertEqual(zone.local_zone().key, "Europe/Paris")
        kolkata = ZONEINFO_DIR / "Asia" / "Kolkata"
        if kolkata.is_file():
            self.poser(str(kolkata))
            decalage = datetime.datetime.fromtimestamp(
                NOW_ETE, zone.local_zone()
            ).utcoffset()
            self.assertEqual(decalage, datetime.timedelta(hours=5, minutes=30))

    def test_empty_tz_is_utc(self):
        self.poser("")
        self.assertIs(zone.local_zone(), datetime.timezone.utc)
        self.poser(":")
        self.assertIs(zone.local_zone(), datetime.timezone.utc)

    @unittest.skipUnless(
        os.path.exists("/etc/localtime"), "/etc/localtime absent"
    )
    def test_unset_tz_reads_etc_localtime(self):
        self.poser(None)
        fuseau = zone.local_zone()
        debut = DEBUT_2025
        for i in range(10):
            instant = debut + i * 36 * 86400
            with self.subTest(instant=instant):
                self.assertEqual(
                    datetime.datetime.fromtimestamp(instant, fuseau)
                    .utcoffset()
                    .total_seconds(),
                    time.localtime(instant).tm_gmtoff,
                )

    def test_posix_string_falls_back_to_a_fixed_offset(self):
        """Une chaîne POSIX n'est pas un fichier TZif : décalage fixe de
        `time.localtime`, l'heure d'été d'une chaîne à règles est perdue."""
        self.poser("XYZ-3")
        fuseau = zone.local_zone()
        self.assertIsInstance(fuseau, datetime.timezone)
        self.assertEqual(fuseau.utcoffset(None), datetime.timedelta(hours=3))

    @unittest.skipUnless(a_le_fuseau("America/Toronto"), "fuseau absent")
    def test_a_zone_the_libc_contradicts_falls_back(self):
        """Un fuseau que `zoneinfo` trouve et que la libc ignore (paquet
        `tzdata` de pip sur un système sans le fichier) : la libc
        l'emporte."""
        self.poser("America/Toronto")
        utc = time.struct_time(
            (2025, 7, 15, 12, 0, 0, 1, 196, 0),
            {"tm_zone": "UTC", "tm_gmtoff": 0},
        )
        with mock.patch.object(zone.time, "localtime", return_value=utc):
            fuseau = zone.local_zone()
        self.assertIsInstance(fuseau, datetime.timezone)
        self.assertEqual(fuseau.utcoffset(None), datetime.timedelta(0))

    def test_an_unknown_name_falls_back_to_the_libc_offset(self):
        self.poser("Nulle/Part")
        fuseau = zone.local_zone()
        self.assertIsInstance(fuseau, datetime.timezone)
        self.assertEqual(
            fuseau.utcoffset(None),
            datetime.timedelta(seconds=time.localtime().tm_gmtoff),
        )


def reglages(**kw):
    base = dict(days=7, weeks=2, delay_window_days=7, lang="fr")
    base.update(kw)
    return SimpleNamespace(**base)


class BaseFactice:
    """La base que lit le rapport, par duck typing : des messages reçus à
    intervalles réguliers, un sur trois lu, un sur cinq répondu."""

    def __init__(self, debut: int, fin: int, pas: int = 5400):
        self.rows = []
        for i, instant in enumerate(range(debut, fin, pas)):
            repondu = i % 5 == 0
            self.rows.append(
                SimpleNamespace(
                    received_at=instant,
                    seen=i % 3 == 0,
                    answered=repondu,
                    first_reply_at=instant + 3600 * (1 + i % 4)
                    if repondu
                    else None,
                    sender="carole.regle@example.org",
                )
            )

    def stats_activity(self, since, until, with_sender=False):
        return [r for r in self.rows if since <= r.received_at < until]


def resume(boite):
    return (
        [
            (b.label, b.start, b.received, b.seen, b.answered)
            for b in boite.days
        ],
        [(b.label, b.start, b.received) for b in boite.weeks],
        boite.received_total,
        boite.delay_mean,
        boite.period_start,
        boite.period_end,
    )


class TestReportCalendar(TzCase):
    def test_report_calendar_matches_the_process_calendar(self):
        jours = []
        jour = datetime.date(2024, 1, 1)
        while jour <= datetime.date(2026, 12, 31):
            jours.append(jour)
            jour += datetime.timedelta(days=1)
        debut_2025 = DEBUT_2025 - 86400
        for nom in ZONES:
            if not a_le_fuseau(nom):
                continue
            with self.subTest(fuseau=nom):
                self.poser(nom)
                fuseau = zone.local_zone()
                self.assertEqual(fuseau.key, nom)
                for d in jours:
                    self.assertEqual(
                        report._midnight(d, fuseau), _mktime_midnight(d), d
                    )
                for e in range(debut_2025, debut_2025 + 367 * 86400, 1800):
                    self.assertEqual(
                        report._local_date(e, fuseau), _localtime_date(e), e
                    )
                boite = SimpleNamespace(generated_at=0)
                for e in range(debut_2025, debut_2025 + 367 * 86400, 3600):
                    boite.generated_at = e
                    self.assertEqual(
                        report._report_date(boite, fuseau),
                        _strftime_local(e),
                        e,
                    )

    @unittest.skipUnless(a_le_fuseau("America/Santiago"), "fuseau absent")
    def test_tz_none_is_the_process_zone(self):
        self.poser("America/Santiago")
        for now in (NOW_ETE, NOW_HIVER):
            with self.subTest(now=now):
                fuseau = ZoneInfo("America/Santiago")
                self.assertEqual(
                    report.day_starts(now, 30),
                    report.day_starts(now, 30, fuseau),
                )
                self.assertEqual(
                    report.week_starts(now, 8),
                    report.week_starts(now, 8, fuseau),
                )

    @unittest.skipUnless(a_le_fuseau("America/Toronto"), "fuseau absent")
    def test_an_explicit_zone_ignores_the_process_zone(self):
        """Le cas d'un serveur qui force `TZ=UTC` : le fuseau passé fait
        les tranches, pas celui du processus."""
        base = BaseFactice(NOW_ETE - 30 * 86400, NOW_ETE)
        self.poser("UTC")
        explicite = report.collect_mailbox(
            base, reglages(), now=NOW_ETE, tz=ZoneInfo("America/Toronto")
        )
        sans = report.collect_mailbox(base, reglages(), now=NOW_ETE)
        self.poser("America/Toronto")
        processus = report.collect_mailbox(base, reglages(), now=NOW_ETE)
        self.assertEqual(resume(explicite), resume(processus))
        self.assertNotEqual(resume(explicite), resume(sans))

    @unittest.skipUnless(
        a_le_fuseau("America/Toronto") and a_le_fuseau("Europe/Paris"),
        "fuseau absent",
    )
    def test_report_date_uses_the_zone(self):
        self.poser("UTC")
        base = BaseFactice(NOW_ETE - 30 * 86400, NOW_ETE)
        attendus = {
            ("America/Toronto", NOW_ETE): ("-0400", "UTC-04:00"),
            ("America/Toronto", NOW_HIVER): ("-0500", "UTC-05:00"),
            ("Europe/Paris", NOW_ETE): ("+0200", "UTC+02:00"),
            ("Europe/Paris", NOW_HIVER): ("+0100", "UTC+01:00"),
        }
        for (nom, now), (decalage, texte) in attendus.items():
            with self.subTest(fuseau=nom, now=now):
                donnees = report.build_data(
                    base, reglages(), now=now, sender=None, tz=ZoneInfo(nom)
                )
                valeurs = report.values(donnees)
                self.assertTrue(valeurs["date_rapport"][0].endswith(decalage))
                heure_locale = CATALOG["mail_stats_report_local_time"]["fr"]
                self.assertIn(
                    heure_locale.replace("{tz}", texte), valeurs["rapport"][0]
                )

    @unittest.skipUnless(a_le_fuseau("Europe/Paris"), "fuseau absent")
    def test_build_data_records_the_resolved_zone(self):
        self.poser("Australia/Sydney")
        base = BaseFactice(NOW_ETE - 10 * 86400, NOW_ETE)
        donnees = report.build_data(base, reglages(), now=NOW_ETE, sender=None)
        self.assertIsNotNone(donnees.tz)
        local = zone.local_zone()
        debut = DEBUT_2025
        for i in range(10):
            e = debut + i * 36 * 86400
            self.assertEqual(
                datetime.datetime.fromtimestamp(e, donnees.tz).utcoffset(),
                datetime.datetime.fromtimestamp(e, local).utcoffset(),
            )
        paris = ZoneInfo("Europe/Paris")
        donnees = report.build_data(
            base, reglages(), now=NOW_ETE, sender=None, tz=paris
        )
        self.assertIs(donnees.tz, paris)


class TestSnapshotKey(TzCase):
    @unittest.skipUnless(
        a_le_fuseau("America/Toronto") and a_le_fuseau("Europe/Paris"),
        "fuseau absent",
    )
    def test_snapshot_key_carries_the_bounds(self):
        s = reglages(days=5, weeks=3, delay_window_days=10)
        toronto = ZoneInfo("America/Toronto")
        paris = ZoneInfo("Europe/Paris")
        cle = report.snapshot_key(s, NOW_ETE, toronto)
        base = BaseFactice(NOW_ETE - 40 * 86400, NOW_ETE)
        boite = report.collect_mailbox(base, s, now=NOW_ETE, tz=toronto)
        bornes = cle["bounds"]
        self.assertEqual(bornes["days"], [b.start for b in boite.days])
        self.assertEqual(bornes["weeks"], [b.start for b in boite.weeks])
        self.assertEqual(bornes["day_end"], boite.period_end)
        self.assertEqual(bornes["days"][0], boite.period_start)
        self.assertEqual(
            bornes["window_start"], report.day_starts(NOW_ETE, 10, toronto)[0]
        )
        self.assertEqual(
            bornes["week_end"],
            report.week_starts(NOW_ETE + 7 * 86400, 1, toronto)[0],
        )
        ecrit = report.mailbox_to_dict(boite, cle)
        self.assertIsNone(
            report.mailbox_from_dict(
                ecrit, report.snapshot_key(s, NOW_ETE, paris)
            )
        )
        self.assertEqual(report.mailbox_from_dict(ecrit, cle), boite)

    def test_two_names_of_one_zone_give_one_key(self):
        s = reglages()
        paires = (
            ("America/Montreal", "America/Toronto"),
            ("UTC", "Etc/UTC"),
            (":/etc/localtime", None),
        )
        for un, autre in paires:
            presents = all(
                n is None
                or (n.startswith(":/") and os.path.exists(n[1:]))
                or a_le_fuseau(n)
                for n in (un, autre)
            )
            with self.subTest(un=un, autre=autre):
                if not presents:
                    self.skipTest(f"{un} ou {autre} absent")
                cles = []
                for nom in (un, autre):
                    self.poser(nom)
                    cles.append(
                        report.snapshot_key(s, NOW_ETE, zone.local_zone())
                    )
                self.assertEqual(cles[0], cles[1])

    def test_a_key_of_the_old_format_is_read_only_when_allowed(self):
        s = reglages()
        fuseau = datetime.timezone(datetime.timedelta(hours=-5))
        base = BaseFactice(NOW_ETE - 20 * 86400, NOW_ETE)
        boite = report.collect_mailbox(base, s, now=NOW_ETE, tz=fuseau)
        cle = report.snapshot_key(s, NOW_ETE, fuseau)
        ancienne = {k: v for k, v in cle.items() if k != "bounds"}
        ecrit = report.mailbox_to_dict(boite, ancienne)
        self.assertIsNone(report.mailbox_from_dict(ecrit, cle))
        self.assertEqual(
            report.mailbox_from_dict(ecrit, cle, legacy=True), boite
        )
        lendemain = report.snapshot_key(s, NOW_ETE + 86400, fuseau)
        self.assertIsNone(
            report.mailbox_from_dict(ecrit, lendemain, legacy=True)
        )
        autre = dict(ancienne, days=s.days + 1)
        self.assertIsNone(
            report.mailbox_from_dict(
                report.mailbox_to_dict(boite, autre), cle, legacy=True
            )
        )


class TestReportLabels(unittest.TestCase):
    def test_report_labels_take_an_explicit_language(self):
        precedent = i18n.configure(default_lang="en")
        self.addCleanup(lambda: i18n.configure(**precedent))
        unite = "mail_stats_report_unit_day"
        for langue in ("fr", "en"):
            with self.subTest(langue=langue):
                self.assertEqual(
                    report.format_delay(3 * 86400, langue),
                    f"3 {CATALOG[unite][langue]}",
                )
        i18n.configure(default_lang="fr")
        self.assertEqual(
            report.format_delay(3 * 86400, "en"),
            f"3 {CATALOG[unite]['en']}",
        )


if __name__ == "__main__":
    unittest.main()
