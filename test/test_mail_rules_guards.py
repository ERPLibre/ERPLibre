#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import time
import unittest

from script.todo.mail.imap_transport import decode_header_value
from script.todo.mail.rules import guards
from script.todo.mail.rules.filter import BodyUnavailable
from script.todo.mail.rules.guards import (
    ENGINE_REASONS,
    REASONS,
    SEND,
    SILENT_REASONS,
    GuardContext,
    authentication_passes,
    authserv_id,
    check_forward_target,
    decide,
    header_values,
    reply_target,
    response_addresses,
    stats_authenticated,
    stats_target,
)
from script.todo.mail.rules.model import (
    FORWARD_MAX_BYTES,
    Armed,
    Condition,
    Group,
    MessageView,
    RuleError,
    new_rule,
)
from script.todo.todo_i18n import t

SECOND = "bruno.filtre@example.net"
THIRD = "denis.tri@example.org"

NOW = 1_793_000_000
UIDV = 1_700_000_001
OWN = "boite.regles@example.org"
HUMAN = "carole.regle@example.org"
OTHER_ACCOUNT = "relais.auto@example.com"
ROUTER_RETURN = "retour.envoi@example.net"
DMARC_PASS = "mx.example.org; dmarc=pass header.from=example.org"


def view(extra=None, **kwargs) -> MessageView:
    base = {
        "uid": 4600,
        "uidvalidity": UIDV,
        "internaldate": NOW - 60,
        "msgid": "<m1@example.org>",
        "frm": f"Carole <{HUMAN}>",
        "to": OWN,
        "cc": "",
        "subject": "Demande de devis",
        "extra": {k.lower(): v for k, v in (extra or {}).items()},
    }
    base.update(kwargs)
    return MessageView(**base)


def armed_rule(**kwargs):
    rule = new_rule("reply", "Absence")
    rule.armed = Armed(uidvalidity=UIDV, uidnext=4500, at=NOW - 3600)
    for key, value in kwargs.items():
        setattr(rule, key, value)
    return rule


def stats_rule(**kwargs):
    """Une règle de rapport armée, aux limites de son type."""
    rule = new_rule("stats", "Rapport")
    rule.armed = Armed(uidvalidity=UIDV, uidnext=4500, at=NOW - 3600)
    for key, value in kwargs.items():
        setattr(rule, key, value)
    return rule


def forward_rule(targets=(HUMAN,), **options):
    """Une règle de redirection armée vers `targets`, options complétées."""
    rule = new_rule("forward", "Renvoi")
    rule.armed = Armed(uidvalidity=UIDV, uidnext=4500, at=NOW - 3600)
    rule.action.options.update(targets=list(targets), **options)
    return rule


def ctx(logged=False, last_send=None, **kwargs) -> GuardContext:
    calls = []

    def last_send_at(sender, target):
        calls.append((sender, target))
        if callable(last_send):
            return last_send(sender, target)
        return last_send

    context = GuardContext(
        now=NOW,
        own_addresses=frozenset({OWN}),
        other_account_addresses=frozenset({OTHER_ACCOUNT}),
        is_logged=lambda: logged,
        last_send_at=last_send_at,
    )
    context.calls = calls
    for key, value in kwargs.items():
        setattr(context, key, value)
    return context


class TestOneCasePerReason(unittest.TestCase):
    """Un message qui déclenche chaque code de `REASONS`."""

    def reason(self, message=None, rule=None, context=None, body=None):
        return decide(
            rule or armed_rule(), message or view(), context or ctx(), body
        ).reason

    def test_plain_message_is_sent(self):
        self.assertEqual(self.reason(), SEND)

    def test_not_armed_without_arming(self):
        self.assertEqual(self.reason(rule=armed_rule(armed=None)), "not_armed")

    def test_not_armed_for_uid_below_uidnext(self):
        self.assertEqual(self.reason(view(uid=4499)), "not_armed")

    def test_not_armed_for_other_uidvalidity(self):
        self.assertEqual(self.reason(view(uidvalidity=UIDV + 1)), "not_armed")

    def test_not_armed_for_reception_before_arming(self):
        self.assertEqual(
            self.reason(view(internaldate=NOW - 7200)), "not_armed"
        )

    def test_duplicate(self):
        self.assertEqual(self.reason(context=ctx(logged=True)), "duplicate")

    def test_too_old_at_48_hours_and_one_second(self):
        rule = armed_rule()
        rule.armed = Armed(UIDV, 4500, 0)
        message = view(internaldate=NOW - 48 * 3600 - 1)
        self.assertEqual(self.reason(message, rule), "too_old")
        message = view(internaldate=NOW - 48 * 3600)
        self.assertEqual(self.reason(message, rule), SEND)

    def test_too_old_for_unknown_reception_date(self):
        self.assertEqual(self.reason(view(internaldate=0)), "too_old")

    def test_bad_date_for_reception_in_the_future(self):
        self.assertEqual(
            self.reason(view(internaldate=NOW + 3600)), "bad_date"
        )

    def test_no_match(self):
        rule = armed_rule()
        rule.filter = Group(children=[Condition("subject", "facture")])
        self.assertEqual(self.reason(rule=rule), "no_match")

    def test_auto_submitted(self):
        message = view({"Auto-Submitted": "auto-replied"})
        self.assertEqual(self.reason(message), "auto_submitted")

    def test_auto_submitted_no_passes(self):
        message = view({"Auto-Submitted": "No ; comment"})
        self.assertEqual(self.reason(message), SEND)

    def test_precedence(self):
        self.assertEqual(
            self.reason(view({"Precedence": "Bulk"})), "precedence"
        )

    def test_list(self):
        message = view({"List-Id": "<liste-annonces.example.net>"})
        self.assertEqual(self.reason(message), "list")
        message = view(
            {"List-Unsubscribe": "<mailto:liste-annonces@example.net>"}
        )
        self.assertEqual(self.reason(message), "list")

    def test_auto_response_suppress(self):
        message = view({"X-Auto-Response-Suppress": "DR, OOF"})
        self.assertEqual(self.reason(message), "auto_response_suppress")

    def test_x_loop(self):
        message = view({"X-Loop": f"erplibre-rules {OTHER_ACCOUNT}"})
        self.assertEqual(self.reason(message), "x_loop")

    def test_spam(self):
        self.assertEqual(self.reason(view({"X-Spam-Flag": "YES"})), "spam")

    def test_null_sender(self):
        self.assertEqual(
            self.reason(view({"Return-Path": "<>"})), "null_sender"
        )

    def test_no_target(self):
        self.assertEqual(self.reason(view(frm="Inconnu")), "no_target")

    def test_robot_sender(self):
        for sender in (
            "mailer-daemon@example.net",
            "no-reply@example.net",
            "liste-annonces-bounces@example.net",
        ):
            with self.subTest(sender=sender):
                self.assertEqual(self.reason(view(frm=sender)), "robot_sender")

    def test_robot_sender_by_return_path(self):
        message = view({"Return-Path": "<bounces+x@example.net>"})
        self.assertEqual(self.reason(message), "robot_sender")

    def test_self(self):
        self.assertEqual(self.reason(view(frm=OWN.upper())), "self")

    def test_other_account_by_from_alone(self):
        message = view(
            {"Return-Path": f"<{HUMAN}>"}, frm=f"Relais <{OTHER_ACCOUNT}>"
        )
        self.assertEqual(self.reason(message), "other_account")

    def test_not_addressed(self):
        message = view(
            to="liste-annonces@example.net", cc="denis.tri@example.org"
        )
        self.assertEqual(self.reason(message), "not_addressed")

    def test_addressed_through_cc(self):
        message = view(to="denis.tri@example.org", cc=OWN)
        self.assertEqual(self.reason(message), SEND)

    def test_auth_fail(self):
        results = "mx.example.org; dmarc=fail header.from=example.org"
        message = view({"Authentication-Results": results})
        self.assertEqual(self.reason(message), "auth_fail")

    def test_spf_fail_without_dkim_pass(self):
        fail = "mx.example.org; spf=fail smtp.mailfrom=example.org; dkim=none"
        self.assertEqual(
            self.reason(view({"Authentication-Results": fail})), "auth_fail"
        )
        rescued = "mx.example.org; spf=fail; dkim=pass header.d=example.org"
        self.assertEqual(
            self.reason(view({"Authentication-Results": rescued})), SEND
        )

    def test_auth_fail_only_reads_the_first_header(self):
        results = "mx.example.org; dmarc=pass\nmx.example.org; dmarc=fail"
        message = view({"Authentication-Results": results})
        self.assertEqual(self.reason(message), SEND)

    def test_auth_fail_ignores_comments(self):
        results = "mx.example.org; spf=pass (dmarc=fail est un commentaire)"
        message = view({"Authentication-Results": results})
        self.assertEqual(self.reason(message), SEND)

    def test_absent_authentication_results_has_no_effect(self):
        self.assertEqual(self.reason(view()), SEND)

    def test_unauthenticated_stats_without_authentication_results(self):
        self.assertEqual(self.reason(rule=stats_rule()), "unauthenticated")

    def test_unauthenticated_stats_with_dmarc_pass_for_another_domain(self):
        results = "mx.example.org; dmarc=pass header.from=example.net"
        message = view({"Authentication-Results": results})
        self.assertEqual(self.reason(message, stats_rule()), "unauthenticated")

    def test_throttled(self):
        self.assertEqual(
            self.reason(context=ctx(last_send=NOW - 60)), "throttled"
        )

    def forward(self, message=None, context=None, **options):
        """Le verdict d'une redirection de Bruno vers Carole."""
        message = message or view(frm=SECOND)
        return self.reason(message, forward_rule(**options), context)

    def test_own_message_by_message_id_and_by_in_reply_to(self):
        self.assertEqual(
            self.forward(context=ctx(is_own_send=lambda: True)),
            "own_message",
        )
        # Une règle de réponse ne consulte pas ce contrôle.
        self.assertEqual(
            self.reason(context=ctx(is_own_send=lambda: True)), SEND
        )

    def test_resent_loop(self):
        message = view({"Resent-From": f"Boîte <{OWN}>"}, frm=SECOND)
        self.assertEqual(self.reason(message), "resent_loop")
        self.assertEqual(self.forward(message), "resent_loop")

    def test_delivery_report_by_content_type_and_sender(self):
        for message in (
            view(
                {"Content-Type": 'Multipart/Report; report-type="x"'},
                frm=SECOND,
            ),
            view({"Content-Type": "message/delivery-status"}, frm=SECOND),
            view(frm="MAILER-DAEMON@example.net"),
            view({"Return-Path": "<postmaster@example.net>"}, frm=SECOND),
        ):
            with self.subTest(message=message.extra or message.frm):
                self.assertEqual(self.forward(message), "delivery_report")

    def test_auto_reply(self):
        for extra in (
            {"Auto-Submitted": "Auto-Replied; owner-email=x"},
            {"Precedence": "auto_reply"},
        ):
            with self.subTest(extra=extra):
                message = view(extra, frm=SECOND)
                self.assertEqual(self.forward(message), "auto_reply")

    def test_too_big(self):
        message = view(frm=SECOND, size=FORWARD_MAX_BYTES + 1)
        self.assertEqual(self.forward(message), "too_big")
        message = view(frm=SECOND, size=FORWARD_MAX_BYTES)
        self.assertEqual(self.forward(message), SEND)

    def test_no_forward_target(self):
        message = view(frm=SECOND)
        self.assertEqual(
            self.forward(message, targets=[SECOND]), "no_forward_target"
        )

    def test_every_reason_is_covered_here(self):
        names = {name for name in dir(self) if name.startswith("test_")}
        for reason in REASONS:
            with self.subTest(reason=reason):
                self.assertTrue(any(reason in name for name in names))


class TestForwardGuard(unittest.TestCase):
    """Une redirection de Bruno vers Carole : ce qui est sauté par défaut,
    ce qui reste, et le choix des destinations."""

    def decision(self, message=None, context=None, **options):
        return decide(
            forward_rule(**options),
            message or view(frm=SECOND),
            context or ctx(),
            None,
        )

    def reason(self, message=None, context=None, **options):
        return self.decision(message, context, **options).reason

    def test_a_list_message_is_forwarded_by_default(self):
        message = view(
            {
                "List-Id": "<annonces.example.net>",
                "Precedence": "bulk",
                "X-Auto-Response-Suppress": "All",
                "Return-Path": "<liste-annonces-bounces@example.net>",
            },
            frm="liste-annonces@example.net",
            to="liste-annonces@example.net",
        )
        self.assertEqual(self.reason(message), SEND)

    def test_skip_lists_restores_the_list_and_robot_checks(self):
        cas = (
            ({"Auto-Submitted": "auto-generated"}, SECOND, "auto_submitted"),
            ({"Precedence": "bulk"}, SECOND, "precedence"),
            ({"List-Id": "<annonces.example.net>"}, SECOND, "list"),
            (
                {"X-Auto-Response-Suppress": "OOF"},
                SECOND,
                "auto_response_suppress",
            ),
            ({}, "noreply@example.net", "robot_sender"),
            (
                {"Return-Path": "<liste-annonces-bounces@example.net>"},
                SECOND,
                "robot_sender",
            ),
        )
        for extra, frm, attendu in cas:
            with self.subTest(attendu=attendu, frm=frm):
                message = view(extra, frm=frm)
                self.assertEqual(self.reason(message), SEND)
                self.assertEqual(
                    self.reason(message, skip_lists=True), attendu
                )

    def test_not_addressed_is_ignored_by_default(self):
        message = view(frm=SECOND, to="liste-annonces@example.net")
        self.assertEqual(self.reason(message), SEND)
        self.assertEqual(
            self.reason(message, skip_lists=True), "not_addressed"
        )

    def test_x_loop_spam_and_null_sender_always_apply(self):
        cas = (
            ({"X-Loop": f"erplibre-rules {OTHER_ACCOUNT}"}, "x_loop"),
            ({"X-Spam-Flag": "YES"}, "spam"),
            ({"Return-Path": "<>"}, "null_sender"),
        )
        for extra, attendu in cas:
            for skip in (False, True):
                with self.subTest(attendu=attendu, skip_lists=skip):
                    message = view(extra, frm=SECOND)
                    self.assertEqual(
                        self.reason(message, skip_lists=skip), attendu
                    )

    def test_resent_from_us_stops_every_kind(self):
        message = view({"Resent-From": OWN}, frm=SECOND)
        for rule in (armed_rule(), stats_rule(), forward_rule()):
            with self.subTest(kind=rule.action.kind):
                self.assertEqual(
                    decide(rule, message, ctx(), None).reason, "resent_loop"
                )

    def test_a_resent_from_another_account_is_not_a_resent_loop(self):
        """Une redirection manuelle depuis un autre compte configuré : la
        règle de réponse répond comme avant."""
        message = view({"Resent-From": f"Relais <{OTHER_ACCOUNT}>"})
        self.assertEqual(
            decide(armed_rule(), message, ctx(), None).reason, SEND
        )

    def test_an_auto_reply_is_never_forwarded(self):
        for extra in (
            {"Auto-Submitted": "auto-replied"},
            {"Precedence": "auto_reply"},
        ):
            for skip in (False, True):
                with self.subTest(extra=extra, skip_lists=skip):
                    message = view(extra, frm=SECOND)
                    self.assertEqual(
                        self.reason(message, skip_lists=skip), "auto_reply"
                    )

    def test_an_auto_generated_message_is_still_forwarded(self):
        message = view({"Auto-Submitted": "auto-generated"}, frm=SECOND)
        self.assertEqual(self.reason(message), SEND)

    def test_mailer_daemon_is_a_delivery_report_without_skip_lists(self):
        message = view(frm="mailer-daemon@example.net")
        self.assertEqual(self.reason(message), "delivery_report")

    def test_sender_and_return_path_are_removed_from_targets(self):
        message = view(
            {"Return-Path": f"<{THIRD.upper()}>"}, frm=f"Bruno <{SECOND}>"
        )
        d = self.decision(message, targets=[SECOND, HUMAN, THIRD])
        self.assertEqual(d.reason, SEND)
        self.assertEqual(d.targets, (HUMAN,))
        self.assertEqual(d.removed, ((SECOND, "sender"), (THIRD, "sender")))
        d = self.decision(message, targets=[SECOND])
        self.assertEqual(
            (d.reason, d.targets, d.removed),
            ("no_forward_target", (), ((SECOND, "sender"),)),
        )

    def test_own_and_other_account_targets_are_removed(self):
        """Seul un `rules.json` édité à la main peut les porter."""
        d = self.decision(targets=[OWN, HUMAN, OTHER_ACCOUNT])
        self.assertEqual(d.targets, (HUMAN,))
        self.assertEqual(
            d.removed, ((OWN, "self"), (OTHER_ACCOUNT, "other_account"))
        )

    def test_idna_targets_are_compared_in_their_normal_form(self):
        message = view(frm="bruno.filtre@filtré.example.net")
        d = self.decision(
            message, targets=["bruno.filtre@xn--filtr-fsa.example.net", HUMAN]
        )
        self.assertEqual(d.targets, (HUMAN,))
        self.assertEqual(
            d.removed,
            (("bruno.filtre@xn--filtr-fsa.example.net", "sender"),),
        )

    def test_unauthenticated_never_applies_to_forward(self):
        self.assertEqual(self.reason(), SEND)
        self.assertEqual(self.reason(skip_lists=True), SEND)

    def test_auth_fail_applies_to_forward(self):
        results = "mx.example.org; dmarc=fail header.from=example.net"
        message = view({"Authentication-Results": results}, frm=SECOND)
        self.assertEqual(self.reason(message), "auth_fail")

    def test_the_throttle_keys_on_the_sender(self):
        context = ctx(last_send=NOW - 60)
        rule = forward_rule()
        rule.throttle_enabled = True
        message = view({"Return-Path": "<prvs=1=x@example.net>"}, frm=SECOND)
        self.assertEqual(
            decide(rule, message, context, None).reason, "throttled"
        )
        self.assertEqual(context.calls, [(SECOND, SECOND)])
        rule.throttle_enabled = False
        self.assertEqual(decide(rule, message, context, None).reason, SEND)

    def test_a_noreply_sender_is_forwarded_by_default(self):
        message = view(
            {"Reply-To": SECOND}, frm="Service <noreply@example.net>"
        )
        self.assertEqual(self.reason(message), SEND)

    def test_response_addresses_of_a_forward_is_the_sender(self):
        message = view({"Return-Path": f"<{THIRD}>"}, frm=f"Bruno <{SECOND}>")
        self.assertEqual(
            response_addresses(forward_rule(), message),
            (SECOND, SECOND, SECOND),
        )

    def test_unreadable_options_raise_after_the_filter(self):
        rule = forward_rule()
        rule.action.options["mode"] = "copie"
        with self.assertRaises(RuleError):
            decide(rule, view(frm=SECOND), ctx(), None)
        # Avant le filtre, rien n'est lu.
        rule.filter = Group(children=[Condition("subject", "facture")])
        self.assertEqual(
            decide(rule, view(frm=SECOND), ctx(), None).reason, "no_match"
        )

    def test_check_forward_target_reports_each_refusal(self):
        own = frozenset({OWN})
        others = frozenset({OTHER_ACCOUNT})
        self.assertEqual(
            check_forward_target(
                "bruno.filtre@Filtré.Example.NET", own=own, others=others
            ),
            "bruno.filtre@xn--filtr-fsa.example.net",
        )
        plein = [f"carole.regle+{i}@example.org" for i in range(10)]
        cas = (
            ("pas une adresse", (), "mail_rules_err_fwd_address"),
            (OWN.upper(), (), "mail_rules_err_fwd_self"),
            (OTHER_ACCOUNT, (), "mail_rules_err_fwd_other_account"),
            (HUMAN.upper(), [HUMAN], "mail_rules_err_fwd_duplicate"),
            (SECOND, plein, "mail_rules_err_fwd_too_many"),
        )
        for texte, courant, cle in cas:
            with self.subTest(cle=cle):
                with self.assertRaises(RuleError) as pris:
                    check_forward_target(
                        texte, own=own, others=others, current=courant
                    )
                self.assertTrue(str(pris.exception).startswith(t(cle)))
        with self.assertRaises(RuleError) as pris:
            check_forward_target(SECOND, own=own, others=others, current=plein)
        self.assertIn("10", str(pris.exception))


class TestStatsGuard(unittest.TestCase):
    """Une règle `stats` répond à From, et seulement s'il est authentifié."""

    def decision(self, extra=None, rule=None, context=None, **fields):
        message = view(extra, **fields)
        return decide(rule or stats_rule(), message, context or ctx(), None)

    def reason(self, extra=None, **kwargs):
        return self.decision(extra, **kwargs).reason

    def test_dmarc_pass_lets_a_stats_rule_send(self):
        self.assertEqual(
            self.reason({"Authentication-Results": DMARC_PASS}), SEND
        )

    def test_aligned_spf_pass_alone_is_enough(self):
        results = f"mx.example.org; spf=pass smtp.mailfrom={HUMAN}"
        self.assertEqual(
            self.reason({"Authentication-Results": results}), SEND
        )

    def test_aligned_dkim_pass_alone_is_enough(self):
        results = "mx.example.org; dkim=pass header.d=example.org"
        self.assertEqual(
            self.reason({"Authentication-Results": results}), SEND
        )

    def test_a_second_authentication_results_is_ignored(self):
        results = f"mx.example.org; spf=none\n{DMARC_PASS}"
        self.assertEqual(
            self.reason({"Authentication-Results": results}),
            "unauthenticated",
        )

    def test_the_configured_authserv_id_must_match(self):
        wanted = ctx(auth_serv_id="mx.example.org")
        foreign = "mx.example.net; dmarc=pass header.from=example.org"
        self.assertEqual(
            self.reason({"Authentication-Results": foreign}, context=wanted),
            "unauthenticated",
        )
        self.assertEqual(
            self.reason(
                {"Authentication-Results": DMARC_PASS}, context=wanted
            ),
            SEND,
        )
        shouted = "MX.Example.ORG; dmarc=pass header.from=example.org"
        self.assertEqual(
            self.reason({"Authentication-Results": shouted}, context=wanted),
            SEND,
        )

    def test_authserv_id_ignores_comments_and_version(self):
        results = (
            "mx.example.org (relais de réception) 1;"
            " dmarc=pass header.from=example.org"
        )
        message = view({"Authentication-Results": results})
        self.assertEqual(authserv_id(message), "mx.example.org")
        self.assertTrue(stats_authenticated(message, "mx.example.org"))
        self.assertFalse(stats_authenticated(message, "mx.example.net"))

    def test_stats_target_is_from_not_return_path(self):
        decision = self.decision(
            {
                "Return-Path": f"<{ROUTER_RETURN}>",
                "Authentication-Results": DMARC_PASS,
            }
        )
        self.assertEqual(decision.reason, SEND)
        self.assertEqual(decision.target, HUMAN)
        self.assertEqual(decision.target_addr, HUMAN)

    def test_stats_ignores_reply_to(self):
        decision = self.decision(
            {"Reply-To": THIRD, "Authentication-Results": DMARC_PASS}
        )
        self.assertEqual(decision.reason, SEND)
        self.assertEqual(decision.target_addr, HUMAN)

    def test_dmarc_fail_is_still_auth_fail(self):
        results = "mx.example.org; dmarc=fail header.from=example.org"
        self.assertEqual(
            self.reason({"Authentication-Results": results}), "auth_fail"
        )

    def test_a_quoted_envelope_sender_cannot_forge_a_result(self):
        """Le « ; » d'une adresse d'enveloppe entre guillemets ne coupe pas
        l'en-tête : le « spf=pass » qu'elle porte reste dans la valeur."""
        results = (
            "mx.example.net; spf=softfail"
            ' smtp.mailfrom="a;spf=pass smtp.mailfrom=b"@example.org;'
            " dkim=none; dmarc=none header.from=example.org"
        )
        message = view({"Authentication-Results": results})
        self.assertFalse(stats_authenticated(message))
        self.assertFalse(stats_authenticated(message, "mx.example.net"))
        self.assertFalse(guards._auth_fails(message))
        self.assertEqual(
            [r[:2] for r in guards._auth_results(message)],
            [("spf", "softfail"), ("dkim", "none"), ("dmarc", "none")],
        )
        self.assertEqual(
            guards._auth_results(message)[0][2]["smtp.mailfrom"],
            "a;spf=pass smtp.mailfrom=b@example.org",
        )
        self.assertEqual(
            self.reason({"Authentication-Results": results}),
            "unauthenticated",
        )

    def test_a_quoted_local_part_keeps_the_domain_after_the_last_at(self):
        """Une partie locale entre guillemets qui porte « @ » n'aligne pas
        son contenu : seul le domaine qui suit le dernier « @ » compte."""
        forged = (
            'mx.example.org; spf=pass smtp.mailfrom="x@example.org"'
            "@example.net"
        )
        self.assertEqual(
            self.reason({"Authentication-Results": forged}),
            "unauthenticated",
        )
        genuine = (
            'mx.example.org; spf=pass smtp.mailfrom="carole;regle"@example.org'
        )
        self.assertEqual(
            self.reason({"Authentication-Results": genuine}), SEND
        )

    def test_a_property_repeated_inside_a_value_keeps_the_first(self):
        """Une clé glissée dans une valeur après celle du serveur ne la
        remplace pas."""
        results = (
            "mx.example.org; spf=pass smtp.mailfrom=a"
            " smtp.mailfrom=b@example.org"
        )
        self.assertEqual(
            self.reason({"Authentication-Results": results}),
            "unauthenticated",
        )

    def test_an_unclosed_quote_reads_as_a_failure(self):
        """Une chaîne entre guillemets jamais refermée rend l'en-tête
        illisible : rien n'y est authentifié, et la réponse est écartée
        comme pour un échec."""
        results = (
            'mx.example.org; spf=pass smtp.mailfrom="a@example.org;'
            " dmarc=fail header.from=example.org"
        )
        message = view({"Authentication-Results": results})
        self.assertIsNone(guards._auth_results(message))
        self.assertTrue(guards._auth_fails(message))
        self.assertFalse(stats_authenticated(message))

    def test_a_parenthesis_inside_quotes_opens_no_comment(self):
        results = (
            'mx.example.org; spf=softfail smtp.mailfrom="(x"@example.net;'
            " dmarc=fail header.from=example.org; dkim=none (absente)"
        )
        message = view({"Authentication-Results": results})
        self.assertTrue(guards._auth_fails(message))

    def test_a_reply_rule_does_not_need_authentication(self):
        self.assertEqual(self.reason(rule=armed_rule()), SEND)

    def test_null_return_path_still_stops_a_stats_rule(self):
        extra = {"Return-Path": "<>", "Authentication-Results": DMARC_PASS}
        self.assertEqual(self.reason(extra), "null_sender")

    def test_stats_stops_on_a_robot_return_path(self):
        extra = {
            "Return-Path": "<liste-annonces-bounces@example.net>",
            "Authentication-Results": DMARC_PASS,
        }
        self.assertEqual(self.reason(extra), "robot_sender")

    def test_stats_stops_on_a_return_path_to_ourselves(self):
        extra = {
            "Return-Path": f"<{OWN}>",
            "Authentication-Results": DMARC_PASS,
        }
        self.assertEqual(self.reason(extra), "self")

    def test_authserv_id_is_empty_when_the_header_starts_with_a_result(self):
        results = (
            "spf=pass smtp.mailfrom=example.org;"
            " dkim=pass header.d=example.org"
        )
        message = view({"Authentication-Results": results})
        self.assertEqual(authserv_id(message), "")
        self.assertTrue(stats_authenticated(message))
        self.assertFalse(stats_authenticated(message, "mx.example.org"))
        self.assertEqual(
            self.reason(
                {"Authentication-Results": results},
                context=ctx(auth_serv_id="mx.example.org"),
            ),
            "unauthenticated",
        )

    def test_response_addresses_for_reply_and_stats(self):
        message = view({"Return-Path": f"<{ROUTER_RETURN}>"})
        self.assertEqual(
            response_addresses(armed_rule(), message),
            (HUMAN, ROUTER_RETURN, ROUTER_RETURN),
        )
        self.assertEqual(
            response_addresses(stats_rule(), message), (HUMAN, HUMAN, HUMAN)
        )
        bare = view()
        self.assertEqual(
            response_addresses(armed_rule(), bare), (HUMAN, HUMAN, HUMAN)
        )


class TestPriority(unittest.TestCase):
    """Le premier garde-fou de la liste l'emporte."""

    def test_auto_submitted_before_list(self):
        message = view(
            {
                "List-Id": "<liste-annonces.example.net>",
                "Auto-Submitted": "auto-generated",
            }
        )
        self.assertEqual(
            decide(armed_rule(), message, ctx(), None).reason, "auto_submitted"
        )

    def test_not_armed_before_duplicate(self):
        decision = decide(
            armed_rule(armed=None), view(), ctx(logged=True), None
        )
        self.assertEqual(decision.reason, "not_armed")

    def test_no_match_before_header_guards(self):
        rule = armed_rule()
        rule.filter = Group(children=[Condition("subject", "facture")])
        decision = decide(rule, view({"Precedence": "bulk"}), ctx(), None)
        self.assertEqual(decision.reason, "no_match")


class TestEveryOccurrence(unittest.TestCase):
    """Chaque occurrence d'un en-tête répété est testée à part."""

    def reason(self, extra):
        return decide(armed_rule(), view(extra), ctx(), None).reason

    def test_precedence_bulk_then_list(self):
        self.assertEqual(
            self.reason({"Precedence": "bulk\nlist"}), "precedence"
        )

    def test_auto_submitted_no_then_auto_replied(self):
        self.assertEqual(
            self.reason({"Auto-Submitted": "no\nauto-replied"}),
            "auto_submitted",
        )

    def test_spam_flag_no_then_yes(self):
        self.assertEqual(self.reason({"X-Spam-Flag": "NO\nYES"}), "spam")

    def test_header_values_splits_and_drops_blanks(self):
        message = view({"Precedence": "bulk\n\n list "})
        self.assertEqual(
            header_values(message, "PRECEDENCE"), ["bulk", "list"]
        )

    def test_only_the_first_return_path_counts(self):
        message = view({"Return-Path": f"<{HUMAN}>\n<>"})
        self.assertEqual(reply_target(message), HUMAN)
        self.assertEqual(self.reason({"Return-Path": f"<{HUMAN}>\n<>"}), SEND)
        self.assertEqual(
            self.reason({"Return-Path": f"<>\n<{HUMAN}>"}), "null_sender"
        )


class TestReplyTarget(unittest.TestCase):
    """L'adresse de réponse : Return-Path, sinon From, jamais Reply-To."""

    def test_prefers_return_path(self):
        message = view({"Return-Path": "<bruno.filtre@example.net>"})
        self.assertEqual(reply_target(message), "bruno.filtre@example.net")

    def test_ignores_reply_to(self):
        message = view({"Reply-To": "denis.tri@example.org"})
        self.assertEqual(reply_target(message), HUMAN)

    def test_raw_keeps_the_received_form(self):
        message = view(frm="Bruno <Bruno.Filtre@XN--FILTR-FSA.example.net>")
        self.assertEqual(
            reply_target(message, raw=True),
            "Bruno.Filtre@XN--FILTR-FSA.example.net",
        )
        self.assertEqual(
            reply_target(message), "bruno.filtre@filtré.example.net"
        )

    def test_decision_target_addr_keeps_the_idna_form(self):
        message = view(frm="bruno.filtre@xn--filtr-fsa.example.net")
        decision = decide(armed_rule(), message, ctx(), None)
        self.assertEqual(decision.reason, SEND)
        self.assertEqual(
            decision.target_addr, "bruno.filtre@xn--filtr-fsa.example.net"
        )
        self.assertEqual(decision.target, "bruno.filtre@filtré.example.net")
        self.assertEqual(decision.sender, "bruno.filtre@filtré.example.net")


class TestThrottle(unittest.TestCase):
    """Limite d'envoi par règle et par expéditeur, horloge injectée."""

    def decide_with(self, last_send, **rule_kwargs):
        rule = armed_rule(throttle_minutes=10, **rule_kwargs)
        return decide(rule, view(), ctx(last_send=last_send), None).reason

    def test_no_previous_send(self):
        self.assertEqual(self.decide_with(None), SEND)

    def test_send_five_minutes_ago_with_ten_minute_limit(self):
        self.assertEqual(self.decide_with(NOW - 5 * 60), "throttled")

    def test_send_eleven_minutes_ago(self):
        self.assertEqual(self.decide_with(NOW - 11 * 60), SEND)

    def test_unchecked_box_ignores_a_send_one_minute_ago(self):
        self.assertEqual(
            self.decide_with(NOW - 60, throttle_enabled=False), SEND
        )

    def test_queries_with_normalized_sender_and_target(self):
        context = ctx(last_send=None)
        message = view({"Return-Path": "<Bruno.Filtre@Example.NET>"})
        decide(armed_rule(), message, context, None)
        self.assertEqual(context.calls, [(HUMAN, "bruno.filtre@example.net")])

    def test_changing_batv_return_path_is_throttled_by_from(self):
        sent = {}

        def last_send(sender, target):
            hits = [sent[k] for k in (sender, target) if k in sent]
            return max(hits) if hits else None

        rule = armed_rule(throttle_minutes=10)
        for index, token in enumerate(("a1b2c3", "d4e5f6")):
            message = view(
                {"Return-Path": f"<prvs={token}={HUMAN}>"}, uid=4600 + index
            )
            decision = decide(rule, message, ctx(last_send=last_send), None)
            if index == 0:
                self.assertEqual(decision.reason, SEND)
                sent[decision.sender] = NOW
                sent[decision.target] = NOW
            else:
                self.assertNotEqual(decision.target, f"prvs=a1b2c3={HUMAN}")
                self.assertEqual(decision.reason, "throttled")


class TestDecisionFields(unittest.TestCase):
    def test_matched_true_for_a_rejection_after_the_filter(self):
        decision = decide(
            armed_rule(), view({"Precedence": "bulk"}), ctx(), None
        )
        self.assertTrue(decision.matched)
        self.assertTrue(decision.logged)

    def test_matched_false_for_no_match(self):
        rule = armed_rule()
        rule.filter = Group(children=[Condition("subject", "facture")])
        decision = decide(rule, view(), ctx(), None)
        self.assertFalse(decision.matched)
        self.assertFalse(decision.logged)

    def test_silent_reasons_are_not_logged(self):
        decision = decide(armed_rule(armed=None), view(), ctx(), None)
        self.assertIn(decision.reason, SILENT_REASONS)
        self.assertFalse(decision.logged)

    def test_too_old_is_logged_but_not_matched(self):
        decision = decide(armed_rule(), view(internaldate=0), ctx(), None)
        self.assertTrue(decision.logged)
        self.assertFalse(decision.matched)

    def test_send_is_matched(self):
        decision = decide(armed_rule(), view(), ctx(), None)
        self.assertEqual(decision.reason, SEND)
        self.assertTrue(decision.matched)

    def test_body_unavailable_passes_through(self):
        rule = armed_rule()
        rule.filter = Group(children=[Condition("body", "urgent")])
        with self.assertRaises(BodyUnavailable):
            decide(rule, view(), ctx(), None)


class TestAuthenticationPasses(unittest.TestCase):
    """Contrôle de l'authentification, réutilisable par les statistiques."""

    def check(self, results, frm=HUMAN, domain="example.org"):
        message = view({"Authentication-Results": results}, frm=frm)
        return authentication_passes(message, domain)

    def test_dmarc_pass_with_aligned_header_from(self):
        self.assertTrue(
            self.check("mx.example.org; dmarc=pass header.from=example.org")
        )

    def test_dmarc_pass_for_another_domain_is_false(self):
        self.assertFalse(
            self.check("mx.example.org; dmarc=pass header.from=example.net")
        )

    def test_dkim_pass_on_a_subdomain_is_aligned(self):
        self.assertTrue(
            self.check("mx.example.org; dkim=pass header.d=mail.example.org")
        )

    def test_spf_pass_with_aligned_mailfrom(self):
        self.assertTrue(
            self.check(
                "mx.example.org; spf=pass smtp.mailfrom=carole.regle@example.org"
            )
        )

    def test_second_forged_header_is_ignored(self):
        results = (
            "mx.example.org; dmarc=fail header.from=example.org\n"
            "mx.example.org; dmarc=pass header.from=example.org"
        )
        self.assertFalse(self.check(results))

    def test_domain_must_be_the_from_domain(self):
        self.assertFalse(
            self.check(
                "mx.example.org; dmarc=pass header.from=example.net",
                domain="example.net",
            )
        )

    def test_absent_header_is_false(self):
        self.assertFalse(authentication_passes(view(), "example.org"))


class TestStatsTarget(unittest.TestCase):
    def test_single_address(self):
        self.assertEqual(stats_target(view()), HUMAN)

    def test_two_addresses_in_from(self):
        message = view(frm=f"{HUMAN}, bruno.filtre@example.net")
        self.assertEqual(stats_target(message), "")


class TestForgedOrUnreadableFrom(unittest.TestCase):
    """Un From dont l'adresse n'est pas sûre n'obtient aucune réponse.

    Les en-têtes arrivent DÉCODÉS RFC 2047 : un libellé encodé y devient
    une adresse que l'expéditeur a choisie.
    """

    # Le tiers suivi d'une virgule, caché dans un libellé encodé.
    ENCODED_LIST = f"=?utf-8?q?denis.tri=40example.org=2C?= <{SECOND}>"
    # Le tiers entre chevrons, caché de même, sans virgule.
    ENCODED_ANGLE = f"=?utf-8?q?=3Cdenis.tri=40example.org=3E?= <{SECOND}>"

    def decide(self, message, rule=None):
        return decide(rule or armed_rule(), message, ctx(), None)

    def test_encoded_display_name_does_not_redirect_the_reply(self):
        for raw in (self.ENCODED_LIST, self.ENCODED_ANGLE):
            with self.subTest(raw=raw):
                decision = self.decide(view(frm=decode_header_value(raw)))
                self.assertEqual(decision.reason, "no_target")
                self.assertEqual(decision.target, "")
                self.assertEqual(decision.target_addr, "")
                self.assertEqual(decision.sender, "")

    def test_encoded_display_name_does_not_satisfy_an_allow_list(self):
        rule = armed_rule(
            filter=Group(
                children=[
                    Condition(field="from", value="*@example.net", op="glob")
                ]
            )
        )
        message = view(
            {"Return-Path": f"<{THIRD}>"},
            frm=decode_header_value(f"=?utf-8?q?{SECOND}=2C?= <{THIRD}>"),
        )
        decision = self.decide(message, rule)
        self.assertTrue(decision.matched)
        self.assertEqual(decision.reason, "no_target")

    def test_unparseable_from_does_not_answer_an_excluded_sender(self):
        rule = armed_rule(
            filter=Group(
                op="not",
                children=[
                    Condition(field="from", value="*@example.net", op="glob")
                ],
            )
        )
        message = view(
            {"Return-Path": f"<{SECOND}>"}, frm=f"Bruno [F] <{SECOND}>"
        )
        decision = self.decide(message, rule)
        self.assertEqual(decision.reason, "no_target")
        self.assertEqual(decision.sender, "")

    def test_two_mailboxes_in_from_give_no_target(self):
        message = view({"Return-Path": f"<{HUMAN}>"}, frm=f"{HUMAN}, {SECOND}")
        self.assertEqual(self.decide(message).reason, "no_target")

    def test_address_repeated_as_display_name_is_sent(self):
        for frm in (f'"{HUMAN}" <{HUMAN}>', f'"{HUMAN.upper()}" <{HUMAN}>'):
            with self.subTest(frm=frm):
                decision = self.decide(view(frm=frm))
                self.assertEqual(decision.reason, SEND)
                self.assertEqual(decision.target, HUMAN)

    def test_reply_target_ignores_an_ambiguous_from(self):
        message = view(frm=decode_header_value(self.ENCODED_LIST))
        self.assertEqual(reply_target(message), "")
        self.assertEqual(reply_target(message, raw=True), "")

    def test_stats_target_ignores_an_ambiguous_from(self):
        message = view(frm=decode_header_value(self.ENCODED_LIST))
        self.assertEqual(stats_target(message), "")


class TestHostileHeaderSize(unittest.TestCase):
    """Un en-tête d'environ 100 Ko tient sous la limite d'un serveur de
    courrier courant : son analyse reste linéaire, avant tout filtre."""

    LONG = 200_000
    BUDGET_S = 3.0

    def chrono(self, fonction, *args):
        debut = time.monotonic()
        resultat = fonction(*args)
        self.assertLess(time.monotonic() - debut, self.BUDGET_S)
        return resultat

    def test_a_huge_display_name_is_decided_quickly(self):
        message = view(frm="a" * self.LONG + f" <{HUMAN}>")
        decision = self.chrono(decide, armed_rule(), message, ctx(), None)
        self.assertEqual((decision.sender, decision.target), (HUMAN, HUMAN))

    def test_a_huge_authentication_results_is_parsed_quickly(self):
        message = view({"Authentication-Results": "mx; " + "a" * self.LONG})
        self.assertEqual(self.chrono(guards._auth_results, message), [])

    def test_deeply_nested_comments_are_stripped_in_one_pass(self):
        texte = "(" * self.LONG + ")" * self.LONG + " dkim=fail"
        self.assertEqual(
            self.chrono(guards._strip_comments, texte).split(), ["dkim=fail"]
        )

    def test_comment_stripping_keeps_an_unclosed_parenthesis(self):
        """Ce qui suit une parenthèse jamais refermée reste analysé : un
        « fail » qui s'y trouve compte."""
        self.assertEqual(guards._strip_comments("a(b(c)d)e"), "a e")
        self.assertEqual(guards._strip_comments("x(a(b)c"), "x(a c")
        self.assertEqual(guards._strip_comments("a)b"), "a)b")
        resultats = "mx.example.org; spf=pass (x; dkim=fail"
        message = view({"Authentication-Results": resultats})
        self.assertIn(
            ("dkim", "fail"), [r[:2] for r in guards._auth_results(message)]
        )

    def test_reply_target_without_return_path_matches_decide(self):
        message = view(frm=f"Carole <{HUMAN.upper()}>")
        decision = decide(armed_rule(), message, ctx(), None)
        self.assertEqual(decision.target, reply_target(message))
        self.assertEqual(decision.target_addr, reply_target(message, raw=True))


class TestReasonLists(unittest.TestCase):
    def test_engine_reasons_and_reasons_are_disjoint(self):
        self.assertEqual(set(ENGINE_REASONS) & set(REASONS), set())

    def test_silent_reasons_belong_to_reasons(self):
        self.assertLessEqual(SILENT_REASONS, set(REASONS))

    def test_send_is_not_a_reason(self):
        self.assertNotIn(guards.SEND, REASONS + ENGINE_REASONS)


if __name__ == "__main__":
    unittest.main()
