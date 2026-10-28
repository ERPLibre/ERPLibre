#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur et la réponse à statistiques, de la synchronisation à l'envoi.

Même socle que `test_mail_rules_engine` : cache clair temporaire, serveur
IMAP en mémoire (avec un dossier `Sent`, nom du dossier d'envoi du
préréglage `generic`), horloge injectée, `deliver` espion. Le fuseau est
UTC : les jours du rapport sont alors ceux de l'horloge.

L'historique (messages anciens et leurs réponses) est posé SOUS l'UID
d'armement de la règle : il nourrit les statistiques sans être lui-même
une demande.
"""

import dataclasses
import json
import os
import time
import unittest
from unittest import mock

from test_mail_rules_engine import (
    BRUNO,
    CAROLE,
    DENIS,
    HOUR,
    OWN,
    T0,
    EngineCase,
)

from script.todo.mail.imap_sync import HeaderInfo
from script.todo.mail.rules import engine, report, storage
from script.todo.mail.rules.model import Armed, MediaRef, new_rule
from script.todo.mail.store import Store
from script.todo.todo_i18n import t

DAY = 86400
RETOUR = "retour.envoi@example.net"
# Premier UID de demande : tout ce qui est en dessous est de l'historique.
ARME = 100


def auth_pour(adresse):
    """L'Authentication-Results d'un serveur de réception qui a vérifié
    le domaine de `adresse`."""
    domaine = adresse.rpartition("@")[2]
    return {
        "authentication-results": (
            f"mx.example.org; dmarc=pass header.from={domaine}"
        )
    }


def texte(msg):
    return msg.get_body(preferencelist=("plain",)).get_content()


def html_de(msg):
    part = msg.get_body(preferencelist=("html",))
    return part.get_content() if part is not None else None


class StatsEngineCase(EngineCase):
    def setUp(self):
        self._old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        super().setUp()
        self.imap.folders["Sent"] = {
            "uidvalidity": 7,
            "messages": {},
            "bodies": {},
        }
        self.sent_uid = 0

    def tearDown(self):
        super().tearDown()
        if self._old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._old_tz
        time.tzset()

    # -- aides -----------------------------------------------------------

    def regle_stats(self, *, approuvee=True, body=None, **champs):
        """Une règle de rapport enregistrée, armée à l'UID `ARME`."""
        rule = new_rule("stats", champs.pop("name", "Rapport"))
        rule.action.format = champs.pop("format", "text")
        rule.action.images = champs.pop("images", [])
        if body is not None:
            rule.action.body = body
        for cle, valeur in champs.items():
            setattr(rule, cle, valeur)
        armed = Armed(1, ARME, T0 - 40 * DAY)
        storage.upsert_rule("perso", rule, rearm=armed, base=self.base)
        rule.armed = armed
        if approuvee:
            self.deja_approuvee(rule)
        return rule

    def demande(self, uid, frm=CAROLE, *, auth=True, extra=None, **kw):
        """Un message reçu à l'instant de l'horloge, authentifié si
        `auth`."""
        entetes = dict(auth_pour(frm) if auth else {})
        entetes.update(extra or {})
        kw.setdefault("internaldate", self.horloge() - 10)
        self.imap.recevoir(uid, frm=frm, extra=entetes, **kw)

    def ancien(self, uid, frm, recu, *, repondu_apres=None, sujet=None):
        """Un message d'historique reçu à `recu`, avec sa réponse classée
        dans Envoyés `repondu_apres` secondes plus tard."""
        self.imap.recevoir(uid, frm=frm, internaldate=recu, subject=sujet)
        if repondu_apres is not None:
            self.envoye(f"<{uid}@example.net>", recu + repondu_apres, frm)

    def envoye(self, in_reply_to, date, to, *, msgid=None, extra=None):
        self.sent_uid += 1
        uid = self.sent_uid
        self.imap.folders["Sent"]["messages"][uid] = HeaderInfo(
            uid=uid,
            date=date,
            size=10,
            flags="\\Seen",
            msgid=msgid or f"<r{uid}@example.org>",
            frm=OWN,
            to=to,
            subject="Re: question",
            in_reply_to=in_reply_to,
            internaldate=date,
            extra=dict(extra or {}),
        )

    def journal(self, rule):
        return self.store.rule_log_entries(rule.id)


class TestStatsReply(StatsEngineCase):
    def test_an_authenticated_request_gets_the_report(self):
        rule = self.regle_stats()
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (1, "ok"))
        self.assertEqual(self.destinataires(), [CAROLE])
        corps = texte(self.envois[0])
        self.assertIn(t("mail_stats_report_col_received"), corps)
        self.assertIn(t("mail_stats_report_total"), corps)
        self.assertEqual(self.journal(rule)[0]["outcome"], "sent")

    def test_the_report_goes_to_from_not_return_path_nor_reply_to(self):
        self.regle_stats()
        self.demande(
            ARME,
            extra={"return-path": f"<{RETOUR}>", "reply-to": DENIS},
        )
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.destinataires(), [CAROLE])

    def test_an_unauthenticated_request_is_logged_and_gets_nothing(self):
        rule = self.regle_stats()
        self.demande(ARME, auth=False)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(bilan.skipped["unauthenticated"], 1)
        self.assertEqual(self.envois, [])
        entree = self.journal(rule)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]),
            ("skipped", "unauthenticated"),
        )

    def test_the_requester_delay_is_in_the_reply(self):
        self.regle_stats(body="Votre délai : {{delai_moyen}}.")
        maintenant = self.horloge()
        self.ancien(1, CAROLE, maintenant - 3 * DAY, repondu_apres=2 * HOUR)
        self.ancien(2, CAROLE, maintenant - 2 * DAY, repondu_apres=4 * HOUR)
        self.ancien(3, BRUNO, maintenant - 2 * DAY, repondu_apres=20 * HOUR)
        self.demande(ARME)
        self.assertEqual(self.passe().sent, 1)
        self.assertIn("Votre délai : 3 h.", texte(self.envois[0]))

    def test_another_sender_history_does_not_leak(self):
        self.regle_stats(format="markdown")
        maintenant = self.horloge()
        self.ancien(
            1,
            BRUNO,
            maintenant - 2 * DAY,
            repondu_apres=HOUR,
            sujet="Contrat confidentiel",
        )
        self.ancien(
            2,
            DENIS,
            maintenant - DAY,
            repondu_apres=3 * HOUR,
            sujet="Dossier médical",
        )
        self.demande(ARME)
        self.assertEqual(self.passe().sent, 1)
        msg = self.envois[0]
        tout = msg.as_string()
        for secret in (BRUNO, DENIS, "Contrat", "Dossier"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, tout)
        for partie in (texte(msg), html_de(msg)):
            self.assertNotIn("@", partie)

    def test_the_stats_throttle_defaults_to_one_day(self):
        rule = self.regle_stats()
        self.assertTrue(rule.throttle_enabled)
        self.assertEqual(rule.throttle_minutes, 1440)
        resultats = []
        for uid, decalage in (
            (ARME, 0),
            (ARME + 1, HOUR),
            (ARME + 2, 25 * HOUR),
        ):
            self.horloge.instant = T0 + 1000 + decalage
            self.demande(uid)
            bilan = self.passe()
            resultats.append((bilan.sent, bilan.skipped.get("throttled", 0)))
        self.assertEqual(resultats, [(1, 0), (0, 1), (1, 0)])

    def test_hold_first_applies_to_stats_rules(self):
        rule = self.regle_stats(approuvee=False)
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (0, 1))
        self.assertEqual(self.envois, [])
        entree = self.journal(rule)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("held", "hold_first")
        )
        self.assertTrue(self.store.outbox()[0]["held"])

    def test_the_stats_reply_is_marked_auto_sent_and_left_out_of_the_next_report(
        self,
    ):
        self.regle_stats()
        self.demande(ARME)
        self.assertEqual(self.passe().sent, 1)
        reponse = self.envois[0]
        self.envoye(
            f"<{ARME}@example.net>",
            self.horloge() + 60,
            CAROLE,
            msgid=reponse["Message-ID"],
        )
        self.session.sync()
        lignes = self.store.stats_activity(0, self.horloge() + DAY)
        self.assertEqual(len(lignes), 1)
        self.assertFalse(lignes[0].answered)
        self.assertIsNone(lignes[0].first_reply_at)

    def test_a_reply_rule_is_unchanged_by_report_settings(self):
        rule = self.regle()
        chemin = storage.rules_path("perso", self.base)
        donnees = json.loads(chemin.read_text())
        donnees["report"] = {"days": 0, "lang": "xx"}
        chemin.write_text(json.dumps(donnees))
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (1, "ok"))
        self.assertEqual(bilan.warnings, [])
        self.assertIn("Je suis absente.", texte(self.envois[0]))
        self.assertEqual(self.journal(rule)[0]["outcome"], "sent")


class TestStatsFailures(StatsEngineCase):
    def ecrire_regle(self, rule, **action):
        """Réécrit l'action d'une règle dans `rules.json` sans passer par
        `validate`, comme une édition à la main."""
        chemin = storage.rules_path("perso", self.base)
        donnees = json.loads(chemin.read_text())
        for entree in donnees["rules"]:
            if entree["id"] == rule.id:
                entree["action"].update(action)
        chemin.write_text(json.dumps(donnees))

    def test_an_invalid_report_setting_skips_only_stats_rules(self):
        reponse = self.regle(throttle_enabled=False)
        stats = self.regle_stats()
        chemin = storage.rules_path("perso", self.base)
        donnees = json.loads(chemin.read_text())
        donnees["report"] = {"weeks": 9}
        chemin.write_text(json.dumps(donnees))
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertIn("Je suis absente.", texte(self.envois[0]))
        self.assertEqual(self.journal(reponse)[0]["outcome"], "sent")
        recentes = [e for e in self.journal(stats) if e["at"] > T0 - 2 * DAY]
        self.assertEqual(recentes, [])
        invalide = t("mail_stats_report_invalid")
        self.assertTrue(any(w.startswith(invalide) for w in bilan.warnings))
        self.assertTrue(any(e.startswith(invalide) for e in bilan.errors))

    def test_an_invalid_report_setting_alone_leaves_no_rule_to_run(self):
        self.regle_stats()
        chemin = storage.rules_path("perso", self.base)
        donnees = json.loads(chemin.read_text())
        donnees["report"] = {"days": True}
        chemin.write_text(json.dumps(donnees))
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.status, bilan.sent), ("no_rules", 0))
        self.assertTrue(bilan.warnings)
        self.assertIn(bilan.account, engine.summary_line([bilan]))

    def test_a_hand_edited_unknown_variable_fails_with_build_error(self):
        rule = self.regle_stats()
        self.ecrire_regle(rule, body="Voici {{inconnue}}.")
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        entree = self.journal(rule)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("failed", "build_error")
        )
        self.assertTrue(
            any(t("mail_rules_err_template_var") in w for w in bilan.warnings)
        )
        self.assertEqual(self.store.outbox(), [])

    def test_a_bad_variable_in_the_subject_fails_like_the_body(self):
        rule = self.regle_stats()
        self.ecrire_regle(rule, subject="Rapport {{rapport}}")
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        entree = self.journal(rule)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("failed", "build_error")
        )

    def test_a_missing_image_still_fails_with_media(self):
        rule = self.regle_stats(
            images=[MediaRef("absent.png", "0" * 64, "image/png")]
        )
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        entree = self.journal(rule)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("failed", "media")
        )


class TestStatsComputation(StatsEngineCase):
    def test_the_mailbox_part_is_computed_once_per_pass(self):
        self.regle_stats()
        self.demande(ARME)
        self.demande(ARME + 1, frm=BRUNO)
        with mock.patch(
            "script.todo.mail.rules.report.collect_mailbox",
            wraps=report.collect_mailbox,
        ) as espion:
            bilan = self.passe()
        self.assertEqual(bilan.sent, 2)
        self.assertEqual(espion.call_count, 1)

    def test_an_unwritable_snapshot_does_not_block_the_report(self):
        """Un instantané qui ne s'écrit pas laisse un avertissement ; les
        rapports partent avec les chiffres calculés, une fois par passe."""
        rule = self.regle_stats()
        self.demande(ARME)
        self.demande(ARME + 1, frm=BRUNO)
        with (
            mock.patch(
                "script.todo.mail.rules.storage.save_report_snapshot",
                side_effect=OSError("disque plein"),
            ) as ecriture,
            mock.patch(
                "script.todo.mail.rules.report.collect_mailbox",
                wraps=report.collect_mailbox,
            ) as espion,
        ):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (2, 0))
        self.assertEqual((espion.call_count, ecriture.call_count), (1, 1))
        self.assertIn(t("mail_stats_snapshot_unsaved"), bilan.warnings)
        self.assertEqual(self.journal(rule)[0]["outcome"], "sent")

    def test_a_refused_snapshot_write_does_not_block_the_report(self):
        self.regle_stats()
        self.demande(ARME)
        with mock.patch(
            "script.todo.mail.rules.storage.save_report_snapshot",
            side_effect=storage.RuleError("verrou"),
        ):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (1, 0))
        self.assertIn(t("mail_stats_snapshot_unsaved"), bilan.warnings)

    def test_requester_data_is_scanned_once_per_pass(self):
        self.regle_stats()
        self.demande(ARME)
        self.demande(ARME + 1, frm=BRUNO)
        original = Store.stats_activity
        appels = []

        def espion(store, since, until, *, with_sender=False):
            appels.append(with_sender)
            return original(store, since, until, with_sender=with_sender)

        with mock.patch.object(Store, "stats_activity", espion):
            bilan = self.passe()
        self.assertEqual(bilan.sent, 2)
        self.assertEqual(appels.count(True), 1)

    def test_two_requests_the_same_day_get_the_same_report(self):
        self.regle_stats(body="Lus : {{lus_total}}.")
        self.ancien(1, DENIS, T0 - DAY)
        self.demande(ARME)
        self.assertEqual(self.passe().sent, 1)

        boite = self.imap.folders["INBOX"]["messages"]
        boite[1] = dataclasses.replace(boite[1], flags="\\Seen")
        self.horloge.instant += 2 * HOUR
        self.demande(ARME + 1, frm=BRUNO)
        with mock.patch(
            "script.todo.mail.rules.report.collect_mailbox",
            wraps=report.collect_mailbox,
        ) as espion:
            self.assertEqual(self.passe().sent, 1)
        self.assertEqual(espion.call_count, 0)
        self.assertEqual(
            self.store.stats_activity(T0 - 2 * DAY, T0)[0].seen, True
        )

        self.horloge.instant += DAY
        self.demande(ARME + 2)
        self.assertEqual(self.passe().sent, 1)
        corps = [texte(m) for m in self.envois]
        self.assertIn("Lus : 0.", corps[0])
        self.assertIn("Lus : 0.", corps[1])
        self.assertIn("Lus : 1.", corps[2])

    def test_the_daily_stats_cap_skips_beyond_twenty(self):
        rule = self.regle_stats()
        maintenant = self.horloge()
        for numero in range(engine.STATS_DAILY_MAX):
            self.store.rule_log_claim(
                rule.id,
                f"plafond-{numero}",
                outcome="sent",
                at=maintenant - 2 * HOUR,
                fingerprint=rule.fingerprint(),
            )
        avant = self.store.rule_log_recent_sends(maintenant - DAY)
        self.demande(ARME)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held, bilan.queued), (0, 0, 0))
        self.assertEqual(bilan.skipped["stats_cap"], 1)
        self.assertEqual(self.envois, [])
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(
            self.store.rule_log_recent_sends(maintenant - DAY), avant
        )
        entree = self.journal(rule)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("skipped", "stats_cap")
        )


class TestHoldReason(StatsEngineCase):
    """`hold_reason` dit, sans rien écrire, ce que `_send` retiendrait."""

    def raison(self, rule, **kw):
        valeurs = {
            "now": self.horloge(),
            "hold_until": 0,
            "sends_this_pass": 0,
            "max_per_pass": 20,
            "max_per_hour": 60,
        }
        valeurs.update(kw)
        return engine.hold_reason(self.store, rule, **valeurs)

    def test_order_of_the_hold_reasons(self):
        rule = self.regle_stats(approuvee=False)
        self.assertEqual(self.raison(rule), "hold_first")
        self.deja_approuvee(rule)
        self.assertIsNone(self.raison(rule))
        self.assertEqual(
            self.raison(rule, hold_until=self.horloge() + 1), "cache_rebuilt"
        )
        self.assertEqual(self.raison(rule, max_per_hour=0), "hour_cap")
        self.assertEqual(
            self.raison(rule, sends_this_pass=20, max_per_hour=0), "pass_cap"
        )
        for numero in range(engine.STATS_DAILY_MAX):
            self.store.rule_log_claim(
                rule.id,
                f"plafond-{numero}",
                outcome="queued",
                at=self.horloge() - HOUR,
            )
        self.assertEqual(self.raison(rule, sends_this_pass=20), "stats_cap")

    def test_the_daily_cap_is_for_stats_rules_only(self):
        rule = self.regle()
        for numero in range(engine.STATS_DAILY_MAX):
            self.store.rule_log_claim(
                rule.id,
                f"plafond-{numero}",
                outcome="sent",
                at=self.horloge() - HOUR,
            )
        self.assertIsNone(self.raison(rule, max_per_hour=100))


if __name__ == "__main__":
    unittest.main()
