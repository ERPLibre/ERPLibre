#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'essai d'une règle : `simulate` ne touche à rien, `send_trial` envoie
la réponse rendue à l'adresse du compte, hors du moteur.

Même socle que `test_mail_rules_stats_engine` : cache clair, IMAP en
mémoire avec `Sent`, horloge injectée, fuseau UTC.
"""

import json
import unittest
from unittest import mock

from test_mail_rules_engine import BRUNO, CAROLE, OWN, T0
from test_mail_rules_stats_engine import (
    ARME,
    DAY,
    StatsEngineCase,
    texte,
)

from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.filter import BodyUnavailable
from script.todo.mail.rules.guards import SEND
from script.todo.mail.rules.model import (
    Armed,
    Condition,
    Group,
    MediaRef,
    RuleError,
    new_rule,
)
from script.todo.mail.rules.storage import ReportSettings
from script.todo.mail.tui import DeliverOffline, Session
from script.todo.todo_i18n import t


class TrialCase(StatsEngineCase):
    def setUp(self):
        super().setUp()
        self.envois_essai = []

    def espion_essai(self, session, msg, verrou=None, **kw):
        self.envois_essai.append((msg, kw))
        return "envoyé"

    def entete(self, uid, frm=CAROLE, *, auth=True, **kw):
        """Un message reçu, synchronisé, puis relu en entier du serveur."""
        self.demande(uid, frm, auth=auth, **kw)
        self.session.sync()
        header = engine.fetch_inbox_header(self.session, uid, uidvalidity=1)
        self.assertIsNotNone(header)
        return header

    def simuler(self, rule, header, **kw):
        kw.setdefault("all_accounts", [])
        kw.setdefault("now", self.horloge)
        return engine.simulate(self.session, rule, header, uidvalidity=1, **kw)

    def auto_sent(self):
        return (
            self.store._db()
            .execute("SELECT COUNT(*) FROM auto_sent")
            .fetchone()[0]
        )


class TestSimulate(TrialCase):
    def test_simulate_writes_nothing(self):
        rule = self.regle_stats()
        header = self.entete(ARME)
        regles = storage.rules_path("perso", self.base).read_bytes()
        etat = storage.state_path("perso", self.base)
        avant = (
            self.journal(rule),
            etat.read_bytes() if etat.exists() else None,
            self.auto_sent(),
        )
        sim = self.simuler(rule, header)
        self.assertEqual(sim.reason, SEND)
        self.assertIsNotNone(sim.rendered)
        self.assertEqual(
            storage.rules_path("perso", self.base).read_bytes(), regles
        )
        apres = (
            self.journal(rule),
            etat.read_bytes() if etat.exists() else None,
            self.auto_sent(),
        )
        self.assertEqual(apres, avant)
        instantane = storage.account_dir("perso", self.base)
        self.assertFalse((instantane / "report_snapshot.json").exists())

    def test_simulate_explains_the_matching_condition(self):
        rule = self.regle()
        oui = Condition("subject", "Question")
        non = Condition("subject", "facture")
        rule.filter = Group("any", [non, oui])
        header = self.entete(ARME)
        sim = self.simuler(rule, header)
        self.assertEqual(
            [(line.depth, line.result) for line in sim.filter_lines],
            [(0, True), (1, False), (1, True)],
        )
        self.assertIs(sim.filter_lines[2].node, oui)
        self.assertTrue(sim.matched)

    def test_simulate_gives_the_real_and_the_as_new_verdicts(self):
        rule = self.regle(armed=Armed(1, 1, T0 - 40 * DAY))
        header = self.entete(ARME, internaldate=self.horloge() - 3 * DAY)
        sim = self.simuler(rule, header)
        self.assertEqual((sim.reason, sim.reason_if_new), ("too_old", SEND))

    def test_simulate_on_a_message_from_oneself_says_self_but_renders(self):
        rule = self.regle()
        header = self.entete(ARME, frm=OWN, auth=False)
        sim = self.simuler(rule, header)
        self.assertEqual(sim.reason, "self")
        self.assertEqual(sim.target, OWN)
        self.assertIn("Je suis absente.", sim.rendered.text)
        self.assertEqual(sim.error, "")

    def test_simulate_on_a_disabled_rule_says_so(self):
        rule = self.regle(enabled=False)
        sim = self.simuler(rule, self.entete(ARME))
        self.assertFalse(sim.rule_enabled)
        self.assertIsNotNone(sim.rendered)

    def test_simulate_forward_is_not_executable(self):
        rule = new_rule("forward", "Renvoi")
        sim = self.simuler(rule, self.entete(ARME))
        self.assertFalse(sim.executable)
        self.assertEqual(sim.error, t("mail_rules_trial_kind"))
        self.assertIsNone(sim.rendered)

    def test_simulate_with_a_missing_image_reports_the_error(self):
        rule = self.regle()
        rule.action.images = [MediaRef("absent.png", "0" * 64, "image/png")]
        sim = self.simuler(rule, self.entete(ARME))
        self.assertIsNone(sim.rendered)
        self.assertIn(t("mail_rules_err_image_missing"), sim.error)

    def test_simulate_stats_shows_the_authserv_id_and_the_verdict(self):
        rule = self.regle_stats()
        sim = self.simuler(rule, self.entete(ARME))
        self.assertEqual(sim.auth_serv_id, "mx.example.org")
        self.assertIs(sim.authenticated, True)
        self.assertTrue(sim.auth_serv_unset)
        self.assertEqual(sim.reason, SEND)
        self.assertEqual(sim.target, CAROLE)

        exige = ReportSettings(auth_serv_id="mx.example.net")
        sim = self.simuler(
            rule, self.entete(ARME + 1, frm=BRUNO), report_settings=exige
        )
        self.assertIs(sim.authenticated, False)
        self.assertFalse(sim.auth_serv_unset)
        self.assertEqual(sim.reason, "unauthenticated")

        sim = self.simuler(rule, self.entete(ARME + 2, auth=False))
        self.assertEqual(sim.auth_serv_id, "")
        self.assertEqual(sim.reason, "unauthenticated")
        self.assertIsNotNone(sim.rendered)

        sim = self.simuler(self.regle(), self.entete(ARME + 3))
        self.assertIsNone(sim.authenticated)

    def test_simulate_says_the_first_report_is_held(self):
        rule = self.regle_stats(approuvee=False)
        sim = self.simuler(rule, self.entete(ARME))
        self.assertEqual((sim.reason, sim.hold), (SEND, "hold_first"))
        self.deja_approuvee(rule)
        self.assertEqual(self.simuler(rule, self.entete(ARME + 1)).hold, "")

    def test_simulate_without_body_still_gives_the_target(self):
        rule = self.regle()
        rule.filter = Group("all", [Condition("body", "question")])

        def sans_corps():
            raise BodyUnavailable(online=False)

        header = self.entete(ARME, extra={"return-path": f"<{BRUNO}>"})
        sim = self.simuler(rule, header, body_loader=sans_corps)
        self.assertEqual(sim.reason, "body_unavailable")
        self.assertEqual(sim.reason_if_new, "body_unavailable")
        self.assertIsNone(sim.matched)
        self.assertEqual(sim.target, BRUNO)

    def test_simulate_a_reply_rule_ignores_an_invalid_report_key(self):
        rule = self.regle()
        chemin = storage.rules_path("perso", self.base)
        donnees = json.loads(chemin.read_text())
        donnees["report"] = {"days": 0}
        chemin.write_text(json.dumps(donnees))
        sim = self.simuler(rule, self.entete(ARME))
        self.assertEqual(sim.error, "")
        self.assertIsNotNone(sim.rendered)
        stats = self.simuler(self.regle_stats(), self.entete(ARME + 1))
        self.assertIsNone(stats.rendered)
        self.assertIn("report.days", stats.error)

    def test_partial_headers_are_flagged(self):
        rule = self.regle_stats()
        self.demande(ARME)
        self.session.sync()
        etat = self.store.folder_state("INBOX")
        ligne = self.store.list_messages(etat["id"], limit=5)[0]
        sim = self.simuler(rule, ligne, headers_complete=False)
        self.assertFalse(sim.headers_complete)
        # Une ligne du cache ne porte pas Authentication-Results.
        self.assertEqual(sim.auth_serv_id, "")
        self.assertEqual(sim.reason, "unauthenticated")
        self.assertIsNotNone(sim.rendered)

    def test_fetch_inbox_header_returns_none_offline(self):
        self.demande(ARME)
        self.session.sync()
        complet = engine.fetch_inbox_header(self.session, ARME, uidvalidity=1)
        self.assertIn("authentication-results", complet.extra)
        self.assertIsNone(
            engine.fetch_inbox_header(self.session, 999, uidvalidity=1)
        )
        hors_ligne = Session(self.account, self.store, None, password="x")
        self.assertIsNone(
            engine.fetch_inbox_header(hors_ligne, ARME, uidvalidity=1)
        )

    def test_fetch_inbox_header_refuses_a_renumbered_inbox(self):
        """Un numéro du cache n'est pas relu sous une autre UIDVALIDITY :
        il pourrait désigner un autre message."""
        self.demande(ARME)
        self.session.sync()
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        self.assertIsNone(
            engine.fetch_inbox_header(self.session, ARME, uidvalidity=1)
        )
        self.assertIsNotNone(
            engine.fetch_inbox_header(self.session, ARME, uidvalidity=2)
        )


class TestSendTrial(TrialCase):
    def essai(self, rule, header, **kw):
        sim = self.simuler(rule, header)
        kw.setdefault("deliver_fn", self.espion_essai)
        statut = engine.send_trial(
            self.session, rule, sim, now=self.horloge, **kw
        )
        return sim, statut

    def test_send_trial_goes_to_the_account_with_the_trial_prefix(self):
        rule = self.regle_stats()
        header = self.entete(ARME)
        sim = self.simuler(rule, header)
        with mock.patch(
            "script.todo.mail.tui.deliver", side_effect=self.espion_essai
        ):
            statut = engine.send_trial(
                self.session, rule, sim, now=self.horloge
            )
        self.assertEqual(statut, "envoyé")
        msg, kw = self.envois_essai[0]
        self.assertEqual(msg["To"], OWN)
        self.assertEqual(
            msg["Subject"],
            f"{t('mail_rules_trial_subject_prefix')} {sim.subject}",
        )
        self.assertEqual(kw["queue_offline"], False)
        self.assertEqual(texte(msg).strip(), sim.rendered.text.strip())

    def test_send_trial_has_no_in_reply_to_and_follows_rfc_3834(self):
        rule = self.regle()
        self.essai(rule, self.entete(ARME))
        msg = self.envois_essai[0][0]
        self.assertIsNone(msg["In-Reply-To"])
        self.assertIsNone(msg["References"])
        self.assertEqual(msg["Auto-Submitted"], "auto-replied")
        self.assertEqual(msg["X-Auto-Response-Suppress"], "All")
        self.assertIn("erplibre-rules", msg["X-Loop"])

    def test_send_trial_marks_auto_sent_and_writes_no_log(self):
        rule = self.regle_stats()
        header = self.entete(ARME)
        journal = self.journal(rule)
        self.essai(rule, header)
        msg = self.envois_essai[0][0]
        self.assertTrue(
            self.store.is_auto_sent(self.store._msgid_hash(msg["Message-ID"]))
        )
        self.assertEqual(self.journal(rule), journal)
        self.assertEqual(self.store.outbox(), [])

    def test_send_trial_counts_toward_no_cap_or_throttle(self):
        rule = self.regle_stats()
        storage.save_caps(
            "perso", storage.Caps(per_pass=1, per_hour=1), base=self.base
        )
        self.essai(rule, self.entete(ARME))
        self.horloge.instant += 60
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (1, 0))
        self.assertEqual(self.destinataires(), [CAROLE])

    def test_send_trial_offline_raises_and_queues_nothing(self):
        rule = self.regle()
        header = self.entete(ARME)
        sim = self.simuler(rule, header)
        hors_ligne = Session(self.account, self.store, None, password="x")
        with self.assertRaises(RuleError) as pris:
            engine.send_trial(hors_ligne, rule, sim, now=self.horloge)
        self.assertEqual(str(pris.exception), t("mail_rules_trial_offline"))
        self.assertEqual(self.store.outbox(), [])

        def tombe(session, msg, **_kw):
            raise DeliverOffline()

        with self.assertRaises(RuleError):
            engine.send_trial(
                self.session, rule, sim, deliver_fn=tombe, now=self.horloge
            )
        self.assertEqual(self.store.outbox(), [])

    def test_send_trial_without_a_rendering_is_refused(self):
        rule = new_rule("forward", "Renvoi")
        sim = self.simuler(rule, self.entete(ARME))
        with self.assertRaises(RuleError) as pris:
            engine.send_trial(
                self.session, rule, sim, deliver_fn=self.espion_essai
            )
        self.assertEqual(
            str(pris.exception), t("mail_rules_trial_unavailable")
        )
        self.assertEqual(self.envois_essai, [])

    def test_the_trial_is_independent_of_the_real_verdict(self):
        """Un message de soi-même, déjà ancien, s'essaie quand même."""
        rule = self.regle(armed=Armed(1, 1, T0 - 40 * DAY))
        header = self.entete(ARME, frm=OWN, internaldate=self.horloge() - DAY)
        sim, _statut = self.essai(rule, header)
        self.assertEqual(sim.reason, "self")
        self.assertEqual(len(self.envois_essai), 1)


if __name__ == "__main__":
    unittest.main()
