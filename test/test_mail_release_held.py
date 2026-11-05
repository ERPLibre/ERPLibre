#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les deux gestes de `rules/release.py` sur le moteur en mémoire :
relâcher une réponse retenue, qui revendique alors son message, et
libérer à la main un message dont la revendication n'a pas pu être
établie.

Une retenue s'obtient par une passe réelle d'une règle non approuvée : sa
ligne porte l'origine du message. Les deux machines réelles sont dans
`test_mail_release_sandbox.py`."""

import dataclasses
import threading
import time
import unittest
from unittest import mock

from test_mail_rules_claim import Crash
from test_mail_rules_engine import BRUNO, CAROLE, DENIS, T0, FauxSmtp
from test_mail_rules_release import ReleaseCase

from script.todo.mail.claim import CLAIM_KEYWORD, has_claim
from script.todo.mail.rules import release, storage
from script.todo.mail.rules.lock import file_lock
from script.todo.todo_i18n import t

REMI = "remi.relache@example.com"


class HeldCase(ReleaseCase):
    def retenir(self, uid=1, **kw):
        """Une réponse retenue par une passe réelle ; rend son entrée."""
        if not getattr(self, "regle_retenue", None):
            # Cinq envois à approuver : un relâchement ne suffit pas à
            # approuver la règle, la réponse suivante est retenue aussi.
            self.regle_retenue = self.regle(
                approuvee=False, throttle_enabled=False, hold_first=5
            )
        self.imap.recevoir(uid, **kw)
        self.assertEqual(self.passe().held, 1)
        self.imap.calls.clear()
        self.imap.probes = self.imap.stores = 0
        return next(e for e in self.store.outbox() if e["held"])

    def entree(self, uid=1):
        cle = self.cle(uid)
        return next(
            (e for e in self.store.outbox() if e["source_key"] == cle), None
        )

    def relacher(self, ident, **kw):
        kw.setdefault("rules_base", self.base)
        kw.setdefault("now", self.horloge)
        return release.release_held(
            self.session,
            ident,
            send_fn=lambda a, m, tr: self.envois.append(m) or [CAROLE],
            connect_fn=lambda a, p: FauxSmtp(),
            **kw,
        )

    def liberer_main(self, rule, uid=1, **kw):
        kw.setdefault("rules_base", self.base)
        return release.release_claim(
            self.store, "perso", rule.id, self.cle(uid), **kw
        )

    def mode_inscrit(self, mode):
        etat = storage.load_state("perso", self.base)
        etat.claim_mode = mode
        storage.save_state("perso", etat, base=self.base)

    def sans_mot_cle(self, uid=1):
        entete = self.imap.messages()[uid]
        self.imap.messages()[uid] = dataclasses.replace(entete, flags="")


class TestReleaseClaims(HeldCase):
    def test_releasing_a_held_reply_claims_then_sends(self):
        e = self.retenir()
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.calls, ["probe", "store"])
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.ligne(self.regle_retenue), ("sent", None))
        self.assertEqual(self.store.outbox(), [])
        self.assertTrue(has_claim(self.imap.messages()[1].flags))

    def test_a_release_that_finds_the_keyword_drops_the_entry(self):
        e = self.retenir()
        self.imap.poser(1, CLAIM_KEYWORD)
        res = self.relacher(e["id"])
        self.assertEqual(
            (res.status, res.text),
            ("dropped", t("mail_outbox_release_claimed_elsewhere")),
        )
        self.assertEqual(self.envois, [])
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(
            self.ligne(self.regle_retenue), ("skipped", "claimed_elsewhere")
        )
        self.assertEqual(self.revendication(), "lost")

    def test_a_release_offline_is_refused_and_the_entry_stays_held(self):
        e = self.retenir()
        self.session.syncer = None
        res = self.relacher(e["id"])
        self.assertEqual(
            (res.status, res.text),
            ("refused", t("mail_outbox_release_needs_server")),
        )
        self.assertTrue(self.entree()["held"])
        self.assertEqual(self.imap.probes, 0)

    def test_a_release_offline_of_a_message_settled_here_needs_no_server(
        self,
    ):
        for uid, etat in ((1, "owned"), (2, "released"), (3, "unclaimed")):
            with self.subTest(etat=etat):
                self.en_ligne()
                e = self.retenir(uid, frm=f"x{uid}.relache@example.com")
                if etat == "released":
                    self.store.rule_claim_affirm(1, uid, "released")
                else:
                    self.store.rule_claim_set(1, uid, etat)
                self.session.syncer = None
                res = self.relacher(e["id"])
                self.assertEqual(
                    (res.status, res.text),
                    ("released", t("mail_outbox_release_offline")),
                )
                self.assertFalse(self.entree(uid)["held"])
                self.assertEqual(self.imap.probes, 0)
        with self.subTest(etat="lost"):
            self.en_ligne()
            e = self.retenir(4, frm=REMI)
            self.store.rule_claim_set(1, 4, "lost")
            self.session.syncer = None
            res = self.relacher(e["id"])
            self.assertEqual(res.status, "dropped")
            self.assertIsNone(self.entree(4))

    def test_a_release_offline_on_a_server_without_keywords_releases_as_before(
        self,
    ):
        e = self.retenir()
        self.mode_inscrit("none")
        self.session.syncer = None
        res = self.relacher(e["id"])
        self.assertEqual(
            (res.status, res.text),
            ("released", t("mail_outbox_release_offline")),
        )
        self.assertFalse(self.entree()["held"])

    def test_a_release_on_a_server_without_keywords_sends_unclaimed(self):
        e = self.retenir()
        self.imap.mode = "none"
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(len(self.envois), 1)
        self.assertIsNone(self.revendication())

    def test_a_refused_store_at_release_sends_and_sets_unclaimed(self):
        e = self.retenir()
        self.imap.drops_keyword = True
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(self.revendication(), "unclaimed")

    def test_a_release_of_a_message_owned_here_needs_no_exchange(self):
        self.regle(name="A")
        b = self.regle(name="B", approuvee=False)
        self.imap.recevoir(1)
        self.assertEqual(self.passe().held, 1)
        self.assertEqual(self.imap.probes, 1)
        e = next(x for x in self.store.outbox() if x["held"])
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, 1)
        self.assertEqual(self.ligne(b), ("sent", None))

    def test_a_release_whose_claim_fails_is_refused_and_keeps_the_entry_held(
        self,
    ):
        e = self.retenir()
        compte = mock.Mock(wraps=self.store.rule_claim_failed)

        def avance(uid):
            self.imap.poser(uid, "\\Seen")

        cas = (
            ("sonde", lambda: setattr(self.imap, "probe_error", OSError())),
            ("refus", lambda: setattr(self.imap, "store_reject", True)),
            (
                "MODIFIED",
                lambda: (
                    setattr(self.imap, "mode", "atomic"),
                    setattr(self.imap, "race", avance),
                ),
            ),
            ("inconnu", lambda: setattr(self.imap, "store_unknown", True)),
        )
        with mock.patch.object(self.store, "rule_claim_failed", compte):
            for nom, regler in cas:
                with self.subTest(nom):
                    self.imap.probe_error = None
                    self.imap.store_reject = False
                    self.imap.race = None
                    self.imap.mode = "plain"
                    regler()
                    res = self.relacher(e["id"])
                    self.assertEqual(
                        (res.status, res.text),
                        ("refused", t("mail_outbox_release_claim_failed")),
                    )
                    self.assertTrue(self.entree()["held"])
                    self.assertEqual(self.envois, [])
        compte.assert_not_called()

    def test_a_change_between_probe_and_store_at_release_is_read_again(self):
        e = self.retenir()
        self.imap.mode = "atomic"
        coups = []

        def une_fois(uid):
            if not coups:
                coups.append(uid)
                self.imap.poser(uid, "\\Seen")

        self.imap.race = une_fois
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.calls, ["probe", "store", "probe", "store"])
        self.assertEqual(len(self.envois), 1)


class TestReleaseConfirmations(HeldCase):
    def interrompre(self):
        """Une revendication interrompue : intention locale, mot-clé posé."""
        self.store.rule_claim_intent(1, 1)
        self.imap.poser(1, CLAIM_KEYWORD)

    def test_an_interrupted_claim_asks_for_confirmation(self):
        e = self.retenir()
        self.interrompre()
        res = self.relacher(e["id"])
        self.assertEqual((res.status, res.verdict), ("confirm", "uncertain"))
        self.assertEqual(
            res.question, t("mail_outbox_release_confirm_uncertain")
        )
        self.assertTrue(self.entree()["held"])
        self.assertEqual(self.envois, [])
        self.assertEqual(self.revendication(), "intent")

    def test_a_confirmed_uncertain_release_owns_the_claim_and_sends(self):
        e = self.retenir()
        self.interrompre()
        res = self.relacher(e["id"], force="uncertain")
        self.assertEqual(res.status, "released")
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(self.revendication(), "owned")

    def test_a_release_of_a_message_gone_from_the_inbox_asks_for_confirmation(
        self,
    ):
        e = self.retenir()
        del self.imap.messages()[1]
        res = self.relacher(e["id"])
        self.assertEqual((res.status, res.verdict), ("confirm", "gone"))
        self.assertEqual(res.question, t("mail_outbox_release_confirm_gone"))
        self.assertTrue(self.entree()["held"])

    def test_a_release_in_a_renumbered_inbox_asks_its_own_question(self):
        e = self.retenir()
        self.store.set_folder_state("INBOX", uidvalidity=2)
        res = self.relacher(e["id"])
        self.assertEqual((res.status, res.verdict), ("confirm", "renumbered"))
        self.assertEqual(
            res.question, t("mail_outbox_release_confirm_renumbered")
        )
        self.assertEqual(self.imap.probes, 0)

    def test_a_confirmed_gone_release_sends_without_writing_a_claim(self):
        e = self.retenir()
        del self.imap.messages()[1]
        res = self.relacher(e["id"], force="gone")
        self.assertEqual(res.status, "released")
        self.assertEqual(len(self.envois), 1)
        self.assertIsNone(self.revendication())

    def test_a_forced_release_whose_keyword_was_removed_is_claimed_normally(
        self,
    ):
        e = self.retenir()
        self.interrompre()
        self.assertEqual(self.relacher(e["id"]).verdict, "uncertain")
        self.sans_mot_cle()
        self.store.rule_claim_drop_intent(1, 1)
        res = self.relacher(e["id"], force="uncertain")
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.calls[-2:], ["probe", "store"])
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(len(self.envois), 1)

    def test_a_release_confirmed_for_one_verdict_asks_again_for_another(self):
        e = self.retenir()
        entete = self.imap.messages().pop(1)
        self.assertEqual(self.relacher(e["id"]).verdict, "gone")
        self.imap.messages()[1] = entete
        self.interrompre()
        res = self.relacher(e["id"], force="gone")
        self.assertEqual((res.status, res.verdict), ("confirm", "uncertain"))
        self.assertEqual(self.envois, [])
        self.assertTrue(self.entree()["held"])
        self.assertEqual(self.revendication(), "intent")


class TestReleaseDepartureChecks(HeldCase):
    def test_a_release_of_an_entry_that_can_no_longer_leave_claims_nothing(
        self,
    ):
        regle = self.regle(approuvee=False, throttle_enabled=False)
        for uid, frm in ((1, CAROLE), (2, BRUNO), (3, DENIS), (4, REMI)):
            self.imap.recevoir(uid, frm=frm)
        self.assertEqual(self.passe().held, 4)
        self.imap.calls.clear()
        ids = {u: self.entree(u)["id"] for u in (1, 2, 3, 4)}
        with self.subTest("déjà partie"):
            self.store.rule_log_set_outcome(regle.id, self.cle(1), "sent")
            res = self.relacher(ids[1])
            self.assertEqual(res.status, "dropped")
            self.assertIsNone(self.entree(1))
            self.assertEqual(self.ligne(regle, 1), ("sent", None))
        with self.subTest("échéance"):
            res = self.relacher(ids[2], now=lambda: T0 + 30 * 86400)
            self.assertEqual(
                (res.status, res.text),
                ("dropped", t("mail_outbox_release_dropped")),
            )
            self.assertEqual(self.ligne(regle, 2), ("expired", "expired"))
        regle.action.body = "Nouveau texte."
        storage.upsert_rule("perso", regle, base=self.base)
        with self.subTest("règle modifiée"):
            res = self.relacher(ids[3])
            self.assertEqual(res.status, "dropped")
            self.assertEqual(self.ligne(regle, 3), ("expired", "rule_changed"))
        storage.set_enabled(
            "perso", regle.id, False, armed=None, base=self.base
        )
        with self.subTest("règle désactivée"):
            res = self.relacher(ids[4])
            self.assertEqual(res.status, "dropped")
            self.assertEqual(
                self.ligne(regle, 4), ("expired", "rule_disabled")
            )
        self.assertEqual(self.imap.calls, [])
        self.assertEqual(self.store.outbox(), [])
        for uid in (1, 2, 3, 4):
            self.assertFalse(has_claim(self.imap.messages()[uid].flags))

    def test_a_release_with_unreadable_rules_is_refused_without_a_claim(self):
        e = self.retenir()
        storage.rules_path("perso", self.base).write_text("{pas du json")
        res = self.relacher(e["id"])
        self.assertEqual(
            (res.status, res.text),
            ("refused", t("mail_outbox_release_no_rules")),
        )
        self.assertNotEqual(res.text, t("mail_rules_error"))
        self.assertEqual(self.imap.probes, 0)
        self.assertTrue(self.entree()["held"])

    def test_a_release_without_a_rules_file_is_refused_without_a_claim(self):
        e = self.retenir()
        storage.rules_path("perso", self.base).unlink()
        res = self.relacher(e["id"])
        self.assertEqual(
            (res.status, res.text),
            ("refused", t("mail_outbox_release_no_rules")),
        )
        self.assertEqual(self.imap.probes, 0)
        self.assertTrue(self.entree()["held"])

    def test_a_claimed_entry_close_to_its_deadline_still_leaves(self):
        e = self.retenir()
        instant = int(self.horloge())
        self.store._db().execute(
            "UPDATE outbox SET expires_at = ? WHERE id = ?",
            (instant + 1, e["id"]),
        )
        self.store._db().commit()
        vues = []
        vrai = self.store.outbox_unhold_claimed

        def note(ident, **kw):
            change = vrai(ident, **kw)
            vues.append(self.store.queued_entry(ident)["expires_at"])
            return change

        with mock.patch.object(self.store, "outbox_unhold_claimed", note):
            res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertGreaterEqual(vues[0], instant + 60)
        self.assertEqual(len(self.envois), 1)


class TestReleaseUnderTheLock(HeldCase):
    def pendant_le_verrou(self, geste, **kw):
        """Lance le relâchement pendant que le test tient le verrou du
        compte, fait `geste`, puis rend le verrou ; rend l'issue."""
        e = self.retenir()
        issue = {}
        with file_lock(storage.lock_path("perso", self.base), wait=0) as tenu:
            self.assertTrue(tenu)
            fil = threading.Thread(
                target=lambda: issue.setdefault(
                    "res", self.relacher(e["id"], lock_wait=10, **kw)
                )
            )
            fil.start()
            time.sleep(0.3)
            geste(e)
        fil.join(10)
        return e, issue["res"]

    def test_an_entry_removed_while_waiting_for_the_lock_is_reported_gone(
        self,
    ):
        _e, res = self.pendant_le_verrou(
            lambda e: self.store.outbox_drop_claimed(
                e["id"], e["rule_id"], e["source_key"]
            )
        )
        self.assertEqual(
            (res.status, res.text),
            ("gone", t("mail_outbox_release_claimed_elsewhere")),
        )
        self.assertEqual(self.imap.probes, 0)

    def test_an_entry_released_elsewhere_while_waiting_is_only_sent(self):
        _e, res = self.pendant_le_verrou(
            lambda e: self.store.set_held(e["id"], False)
        )
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, 0)
        self.assertEqual(len(self.envois), 1)

    def test_an_entry_gone_before_the_release_is_status_gone_not_refused(
        self,
    ):
        e = self.retenir()
        self.store.drop_queued(e["id"])
        res = self.relacher(e["id"], entree=e)
        self.assertEqual(res.status, "gone")
        self.assertEqual(self.imap.probes, 0)

    def test_a_release_while_the_account_lock_is_held_is_refused(self):
        e = self.retenir()
        with file_lock(storage.lock_path("perso", self.base), wait=0) as tenu:
            self.assertTrue(tenu)
            res = self.relacher(e["id"], lock_wait=0)
        self.assertEqual(
            (res.status, res.text), ("refused", t("mail_rules_busy"))
        )
        self.assertEqual(self.imap.probes, 0)
        self.assertTrue(self.entree()["held"])


class TestReleaseAfterACrash(HeldCase):
    def test_a_crash_after_the_release_claim_is_taken_up_by_the_next_release(
        self,
    ):
        e = self.retenir()
        with mock.patch.object(
            self.store, "outbox_unhold_claimed", side_effect=Crash()
        ):
            with self.assertRaises(Crash):
                self.relacher(e["id"])
        self.assertEqual(self.revendication(), "owned")
        self.assertTrue(self.entree()["held"])
        self.assertEqual(self.envois, [])
        sondes = self.imap.probes
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, sondes)
        self.assertEqual(len(self.envois), 1)

    def test_a_crash_after_releasing_leaves_the_entry_to_the_next_flush(self):
        e = self.retenir()
        with mock.patch(
            "script.todo.mail.tui.send_released", side_effect=Crash()
        ):
            with self.assertRaises(Crash):
                self.relacher(e["id"])
        self.assertFalse(self.entree()["held"])
        sondes = self.imap.probes
        self.assertEqual(self.vider()[0], 1)
        self.assertEqual(self.imap.probes, sondes)
        self.assertEqual(len(self.envois), 1)

    def test_a_dropped_entry_reserved_by_a_flush_is_refused_busy(self):
        e = self.retenir()
        self.assertTrue(self.store.outbox_claim(e["id"], int(self.horloge())))
        self.imap.poser(1, CLAIM_KEYWORD)
        res = self.relacher(e["id"])
        self.assertEqual(
            (res.status, res.text), ("refused", t("mail_outbox_release_busy"))
        )
        self.assertIsNotNone(self.entree())


class TestReleaseWithoutClaim(HeldCase):
    def test_a_manual_entry_releases_as_before_without_a_claim(self):
        ident = self.store.queue_message(
            b"From: boite.regles@example.org\r\nTo: carole.regle@example.org"
            b"\r\nSubject: s\r\n\r\nx\r\n",
            CAROLE,
            "s",
            held=True,
        )
        res = self.relacher(ident)
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, 0)
        self.assertEqual(len(self.envois), 1)

    def test_a_retry_entry_releases_without_a_claim(self):
        e = self.retenir()
        self.store._db().execute("UPDATE outbox SET retry = 1")
        self.store._db().commit()
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, 0)
        self.assertNotEqual((self.entree() or {}).get("held"), True)

    def test_an_entry_without_origin_releases_as_before(self):
        e = self.retenir()
        self.store._db().execute("UPDATE rule_log SET sealed_origin = NULL")
        self.store._db().commit()
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, 0)
        self.assertEqual(len(self.envois), 1)

    def test_an_entry_already_released_is_only_sent(self):
        e = self.retenir()
        self.store.set_held(e["id"], False)
        res = self.relacher(e["id"])
        self.assertEqual(res.status, "released")
        self.assertEqual(self.imap.probes, 0)
        self.assertEqual(len(self.envois), 1)


class TestClaimMode(HeldCase):
    def test_a_release_writes_the_claim_mode_like_a_pass(self):
        """Comme une passe : un STORE confirmé ou refusé impose son mode,
        une sonde ordinaire (mot-clé trouvé posé) ne fait pas quitter
        `none` ; le reste de l'état ne bouge pas."""
        cas = (
            ("", "atomic", "stored", "released", "atomic"),
            ("", "plain", "refused", "released", "none"),
            ("none", "plain", "present", "dropped", "none"),
            ("none", "plain", "stored", "released", "plain"),
        )
        for uid, (avant, mode, issue, statut, attendu) in enumerate(
            cas, start=1
        ):
            with self.subTest(avant=avant, mode=mode, issue=issue):
                e = self.retenir(uid, frm=f"x{uid}.relache@example.com")
                self.mode_inscrit(avant)
                curseur = storage.load_state("perso", self.base).cursor
                self.imap.mode = mode
                self.imap.drops_keyword = issue == "refused"
                if issue == "present":
                    self.imap.poser(uid, CLAIM_KEYWORD)
                res = self.relacher(e["id"])
                self.assertEqual(res.status, statut)
                etat = storage.load_state("perso", self.base)
                self.assertEqual(etat.claim_mode, attendu)
                self.assertEqual(etat.cursor, curseur)

    def test_after_a_release_learned_none_an_offline_hold_is_held(self):
        e = self.retenir()
        self.imap.mode = "none"
        self.assertEqual(self.relacher(e["id"]).status, "released")
        self.assertEqual(
            storage.load_state("perso", self.base).claim_mode, "none"
        )
        self.imap.recevoir(2, frm=BRUNO)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(bilan.held, 1)
        self.assertNotEqual(bilan.status, "offline")


class TestReleaseClaimByHand(HeldCase):
    def test_release_claim_marks_the_message_released_and_says_so(self):
        regle = self.regle()
        self.incertain(regle)
        self.assertEqual(
            self.liberer_main(regle), (True, t("mail_rules_release_done"))
        )
        self.assertEqual(self.ligne(regle), ("skipped", "released"))
        self.assertEqual(self.revendication(), "released")

    def test_release_claim_of_a_failed_claim_is_allowed(self):
        regle = self.regle()
        self.en_echec(regle)
        self.assertEqual(
            self.liberer_main(regle), (True, t("mail_rules_release_done"))
        )
        self.assertEqual(self.ligne(regle), ("skipped", "released"))
        self.assertEqual(self.revendication(), "retry")

    def test_release_claim_refuses_when_the_rules_are_busy(self):
        regle = self.regle()
        self.incertain(regle)
        with file_lock(storage.lock_path("perso", self.base), wait=0):
            res = self.liberer_main(regle, lock_wait=0)
        self.assertEqual(res, (False, t("mail_rules_busy")))
        self.assertEqual(self.ligne(regle), ("skipped", "claim_uncertain"))

    def test_release_claim_refusals_say_why(self):
        regle = self.regle()
        self.incertain(regle)
        db = self.store._db()
        with self.subTest("not_releasable"):
            self.store.rule_log_set_outcome(regle.id, "absente", "sent")
            res = release.release_claim(
                self.store, "perso", regle.id, "absente", rules_base=self.base
            )
            self.assertEqual(
                res, (False, t("mail_rules_release_not_releasable"))
            )
        with self.subTest("renumbered"):
            self.store.set_folder_state("INBOX", uidvalidity=2)
            self.assertEqual(
                self.liberer_main(regle),
                (False, t("mail_rules_release_renumbered")),
            )
            self.store.set_folder_state("INBOX", uidvalidity=1)
        with self.subTest("absent"):
            db.execute("DELETE FROM messages")
            db.commit()
            self.assertEqual(
                self.liberer_main(regle),
                (False, t("mail_rules_release_absent")),
            )
        with self.subTest("no_origin"):
            db.execute("UPDATE rule_log SET sealed_origin = NULL")
            db.commit()
            self.assertEqual(
                self.liberer_main(regle),
                (False, t("mail_rules_release_no_origin")),
            )
        with self.subTest("no_inbox"):
            self.store.forget_folder("INBOX")
            self.assertEqual(
                self.liberer_main(regle),
                (False, t("mail_rules_release_no_inbox")),
            )
        with self.subTest("ephemeral"):
            with mock.patch.object(storage, "base_of", return_value=None):
                res = release.release_claim(
                    self.store, "perso", regle.id, self.cle(1)
                )
            self.assertEqual(res, (False, t("mail_rules_ephemeral")))
        self.assertEqual(self.ligne(regle), ("skipped", "claim_uncertain"))


if __name__ == "__main__":
    unittest.main()
