#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import copy
import json
import unittest
from types import SimpleNamespace

from script.todo.mail.rules import model
from script.todo.mail.rules.model import (
    Action,
    Armed,
    Condition,
    Group,
    MediaRef,
    Rule,
    RuleError,
    message_view,
    new_rule,
    validate,
    validate_node,
)
from script.todo.mail.store import MessageMeta
from script.todo.todo_i18n import t

SAMPLE = {
    "version": 1,
    "account": "perso",
    "rules": [
        {
            "id": "3f9c0a1b2c4d",
            "name": "Absence",
            "enabled": True,
            "order": 10,
            "stop_after": False,
            "filter": {
                "type": "group",
                "op": "all",
                "children": [
                    {
                        "type": "condition",
                        "field": "from",
                        "op": "glob",
                        "value": "*@example.net",
                        "mode": "substring_ci",
                    },
                    {
                        "type": "group",
                        "op": "not",
                        "children": [
                            {
                                "type": "condition",
                                "field": "subject",
                                "op": "contains",
                                "value": "désabonnement",
                                "mode": "word",
                            }
                        ],
                    },
                    {
                        "type": "group",
                        "op": "any",
                        "children": [
                            {
                                "type": "condition",
                                "field": "to_cc",
                                "op": "contains",
                                "value": "boite.regles@example.org",
                                "mode": "exact",
                            },
                            {
                                "type": "condition",
                                "field": "body",
                                "op": "contains",
                                "value": "urgent",
                                "mode": "substring_ci",
                            },
                        ],
                    },
                ],
            },
            "action": {
                "kind": "reply",
                "format": "markdown",
                "subject": "",
                "body": "Bonjour,\n\nJe suis absente.\n\n![Logo](logo.png)\n",
                "images": [
                    {"file": "logo.png", "sha256": "9b1c", "mime": "image/png"}
                ],
                "options": {},
            },
            "throttle_enabled": True,
            "throttle_minutes": 10080,
            "max_age_hours": 48,
            "hold_first": 1,
            "armed": {
                "uidvalidity": 1700000001,
                "uidnext": 4512,
                "at": 1793000000,
            },
        }
    ],
}


def sample_rule() -> Rule:
    return model.rules_from_dict(copy.deepcopy(SAMPLE))[0]


def cond(**kwargs) -> Condition:
    base = {"field": "subject", "value": "devis"}
    base.update(kwargs)
    return Condition(**base)


def rule_with(node) -> Rule:
    rule = new_rule()
    rule.filter = Group(children=[node])
    return rule


class TestRoundTrip(unittest.TestCase):
    """Le fichier se relit et se réécrit sans rien perdre."""

    def test_to_dict_of_from_dict_is_identical(self):
        rules = model.rules_from_dict(copy.deepcopy(SAMPLE))
        self.assertEqual(model.rules_to_dict("perso", rules), SAMPLE)

    def test_round_trip_survives_json_serialization(self):
        text = json.dumps(
            model.rules_to_dict("perso", [sample_rule()]), ensure_ascii=False
        )
        again = model.rules_from_dict(json.loads(text))
        self.assertEqual(again[0], sample_rule())

    def test_future_version_is_refused(self):
        data = copy.deepcopy(SAMPLE)
        data["version"] = 2
        with self.assertRaises(RuleError):
            model.rules_from_dict(data)

    def test_missing_version_reads_as_one(self):
        data = copy.deepcopy(SAMPLE)
        del data["version"]
        self.assertEqual(len(model.rules_from_dict(data)), 1)

    def test_unknown_rule_keys_are_kept_in_extra(self):
        data = copy.deepcopy(SAMPLE)
        data["rules"][0]["schedule"] = {"days": [1, 2]}
        rule = model.rules_from_dict(data)[0]
        self.assertEqual(rule.extra, {"schedule": {"days": [1, 2]}})
        self.assertEqual(rule.to_dict()["schedule"], {"days": [1, 2]})

    def test_unknown_action_keys_are_kept_in_options(self):
        data = copy.deepcopy(SAMPLE)
        data["rules"][0]["action"]["recipients"] = ["denis.tri@example.org"]
        rule = model.rules_from_dict(data)[0]
        self.assertEqual(
            rule.action.options, {"recipients": ["denis.tri@example.org"]}
        )
        written = rule.to_dict()["action"]["options"]
        self.assertEqual(written, {"recipients": ["denis.tri@example.org"]})

    def test_missing_id_is_refused_rather_than_regenerated(self):
        data = copy.deepcopy(SAMPLE)
        del data["rules"][0]["id"]
        with self.assertRaises(RuleError):
            model.rules_from_dict(data)

    def test_duplicate_ids_are_refused(self):
        data = copy.deepcopy(SAMPLE)
        data["rules"].append(copy.deepcopy(data["rules"][0]))
        with self.assertRaises(RuleError):
            model.rules_from_dict(data)

    def test_wrong_types_are_refused(self):
        for key, value in (
            ("enabled", "yes"),
            ("throttle_minutes", True),
            ("order", "10"),
            ("armed", [1, 2, 3]),
        ):
            with self.subTest(key=key):
                data = copy.deepcopy(SAMPLE)
                data["rules"][0][key] = value
                with self.assertRaises(RuleError):
                    model.rules_from_dict(data)

    def test_condition_at_the_root_is_refused(self):
        data = copy.deepcopy(SAMPLE)
        data["rules"][0]["filter"] = {
            "type": "condition",
            "field": "subject",
            "value": "x",
        }
        with self.assertRaises(RuleError):
            model.rules_from_dict(data)

    def test_absurdly_deep_file_is_refused_while_reading(self):
        node = {"type": "condition", "field": "subject", "value": "x"}
        for _ in range(model.MAX_DEPTH + 5):
            node = {"type": "group", "op": "all", "children": [node]}
        with self.assertRaises(RuleError):
            model.node_from_dict(node)


class TestNewRule(unittest.TestCase):
    """Chaque type d'action naît avec sa limite par défaut."""

    def test_reply_defaults(self):
        rule = new_rule("reply")
        self.assertTrue(rule.throttle_enabled)
        self.assertEqual(rule.throttle_minutes, 10080)
        self.assertEqual(rule.max_age_hours, 48)
        self.assertEqual(rule.hold_first, 1)
        self.assertIsNone(rule.armed)
        self.assertEqual(rule.action.kind, "reply")

    def test_stats_defaults(self):
        rule = new_rule("stats")
        self.assertTrue(rule.throttle_enabled)
        self.assertEqual(rule.throttle_minutes, 1440)

    def test_forward_defaults(self):
        rule = new_rule("forward")
        self.assertFalse(rule.throttle_enabled)
        self.assertEqual(rule.throttle_minutes, 10080)
        self.assertEqual(rule.action.format, "text")
        self.assertEqual(rule.action.body, "")
        self.assertEqual(
            rule.action.options,
            {"targets": [], "mode": "inline", "skip_lists": False},
        )
        self.assertIn("forward", model.EXECUTABLE_KINDS)

    def test_ids_are_fresh_and_twelve_hex_characters(self):
        first, second = new_rule(), new_rule()
        self.assertNotEqual(first.id, second.id)
        self.assertRegex(first.id, r"^[0-9a-f]{12}$")

    def test_new_rule_is_valid(self):
        for kind in ("reply", "stats"):
            with self.subTest(kind=kind):
                validate(new_rule(kind, "Absence"))

    def test_a_new_forward_rule_needs_a_target(self):
        with self.assertRaises(RuleError) as pris:
            validate(new_rule("forward", "Renvoi"))
        self.assertIn(t("mail_rules_err_fwd_no_target"), str(pris.exception))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(RuleError):
            new_rule("delete")


def forward_rule(**options):
    """Une règle `forward` dont les options sont complétées par `options`."""
    rule = new_rule("forward", "Renvoi")
    rule.action.options.update(options)
    return rule


class TestForwardOptions(unittest.TestCase):
    """Les options d'une action `forward`, relues, contrôlées, nettoyées."""

    def test_forward_options_deduplicate_and_canonicalize(self):
        action = Action(
            kind="forward",
            options={
                "targets": [
                    "Carole.Regle@EXAMPLE.org",
                    "carole.regle@example.org",
                    "bruno.filtre@filtré.example.net",
                    "bruno.filtre@xn--filtr-fsa.example.net",
                    "denis.tri@example.org",
                ],
                "mode": "redirect",
                "skip_lists": True,
            },
        )
        opts = model.forward_options(action)
        self.assertEqual(
            opts.targets,
            (
                "Carole.Regle@example.org",
                "bruno.filtre@xn--filtr-fsa.example.net",
                "denis.tri@example.org",
            ),
        )
        self.assertEqual((opts.mode, opts.skip_lists), ("redirect", True))
        # Clés absentes : valeurs par défaut.
        vide = model.forward_options(Action(kind="forward"))
        self.assertEqual(
            (vide.targets, vide.mode, vide.skip_lists), ((), "inline", False)
        )

    def test_forward_options_reject_wrong_types(self):
        for cle, valeur in (
            ("targets", "carole.regle@example.org"),
            ("targets", ["carole.regle@example.org", 3]),
            ("mode", 1),
            ("skip_lists", "oui"),
            ("skip_lists", 0),
        ):
            with self.subTest(cle=cle, valeur=valeur):
                action = Action(kind="forward", options={cle: valeur})
                with self.assertRaises(RuleError) as pris:
                    model.forward_options(action)
                self.assertIn(f"options.{cle}", str(pris.exception))
        action = Action(kind="forward", options={"mode": "copie"})
        with self.assertRaises(RuleError) as pris:
            model.forward_options(action)
        self.assertIn(t("mail_rules_err_fwd_mode"), str(pris.exception))
        action = Action(
            kind="forward", options={"targets": ["carole regle@example.org"]}
        )
        with self.assertRaises(RuleError) as pris:
            model.forward_options(action)
        self.assertIn(t("mail_rules_err_fwd_address"), str(pris.exception))

    def test_forward_validation_bounds(self):
        validate(forward_rule(targets=["carole.regle@example.org"]))
        onze = [f"carole.regle+{i}@example.org" for i in range(11)]
        image = MediaRef("logo.png", "0" * 64, "image/png")
        cas = (
            (forward_rule(), "mail_rules_err_fwd_no_target"),
            (forward_rule(targets=onze), "mail_rules_err_fwd_too_many"),
            (
                forward_rule(targets=onze[:1], mode="copie"),
                "mail_rules_err_fwd_mode",
            ),
        )
        for rule, cle in cas:
            with self.subTest(cle=cle):
                with self.assertRaises(RuleError) as pris:
                    validate(rule)
                self.assertIn(t(cle), str(pris.exception))
        dix = forward_rule(targets=onze[:10])
        validate(dix)
        long = forward_rule(targets=onze[:1])
        long.action.body = "x" * model.FORWARD_INTRO_MAX
        validate(long)
        long.action.body += "x"
        with self.assertRaises(RuleError) as pris:
            validate(long)
        self.assertIn(
            t("mail_rules_err_fwd_intro_too_long"), str(pris.exception)
        )
        illustree = forward_rule(targets=onze[:1])
        illustree.action.images = [image]
        with self.assertRaises(RuleError) as pris:
            validate(illustree)
        self.assertIn(t("mail_rules_err_fwd_images"), str(pris.exception))

    def test_clean_action_strips_what_the_kind_ignores(self):
        image = MediaRef("logo.png", "0" * 64, "image/png")
        options = {
            "targets": ["carole.regle@example.org"],
            "mode": "attachment",
            "skip_lists": True,
            "future": 1,
        }
        renvoi = Action(
            kind="forward",
            format="html",
            subject="Sujet",
            body="Intro",
            images=[image],
            options=dict(options),
        )
        propre = model.clean_action(renvoi)
        self.assertEqual(
            (propre.format, propre.subject, propre.images, propre.body),
            ("text", "", [], "Intro"),
        )
        self.assertEqual(propre.options, options)
        self.assertEqual(renvoi.images, [image])
        reponse = Action(
            kind="reply", body="Absent.", images=[image], options=options
        )
        propre = model.clean_action(reponse)
        self.assertEqual(propre.options, {"future": 1})
        self.assertEqual((propre.images, propre.body), ([image], "Absent."))
        self.assertIn("targets", reponse.options)

    def test_fingerprint_changes_with_targets_mode_and_skip_lists(self):
        base = forward_rule(targets=["carole.regle@example.org"])
        empreinte = base.fingerprint()
        for cle, valeur in (
            ("targets", ["denis.tri@example.org"]),
            ("mode", "redirect"),
            ("skip_lists", True),
        ):
            with self.subTest(cle=cle):
                autre = copy.deepcopy(base)
                autre.action.options[cle] = valeur
                self.assertNotEqual(autre.fingerprint(), empreinte)

    def test_a_forward_rule_round_trips_through_json(self):
        rule = forward_rule(
            targets=["carole.regle@example.org", "denis.tri@example.org"],
            mode="attachment",
        )
        relue = Rule.from_dict(json.loads(json.dumps(rule.to_dict())))
        self.assertEqual(relue.action.options, rule.action.options)
        self.assertEqual(relue.fingerprint(), rule.fingerprint())


class TestTemplates(unittest.TestCase):
    """Les variables « {{nom}} » d'une règle stats, et leur refus ailleurs."""

    def test_stats_rule_starts_with_the_default_template(self):
        rule = new_rule("stats")
        self.assertEqual(rule.action.body, t("mail_stats_default_body"))
        self.assertIn("{{rapport}}", rule.action.body)
        self.assertEqual(rule.action.format, "markdown")
        self.assertEqual(new_rule("reply").action.body, "")

    def test_unknown_template_variable_is_refused(self):
        rule = new_rule("stats")
        rule.action.body = "{{ jours }} {{rapport}} {{Jours}}"
        with self.assertRaises(model.TemplateError) as caught:
            validate(rule)
        self.assertIn("{{Jours}}", str(caught.exception))
        self.assertIn(t("mail_rules_err_template_var"), str(caught.exception))
        rule.action.subject = "{{inconnue}}"
        rule.action.body = "{{rapport}}"
        with self.assertRaises(model.TemplateError):
            validate(rule)

    def test_block_variable_in_subject_is_refused(self):
        rule = new_rule("stats")
        rule.action.subject = "Rapport {{ rapport_jours }}"
        with self.assertRaises(model.TemplateError) as caught:
            validate(rule)
        self.assertIn(
            t("mail_rules_err_template_block_subject"), str(caught.exception)
        )
        rule.action.subject = "{{jours}} jours : {subject}"
        validate(rule)

    def test_block_variable_inside_an_html_tag_is_refused(self):
        rule = new_rule("stats")
        rule.action.format = "html"
        rule.action.body = '<p title="{{ rapport }}">x</p>'
        with self.assertRaises(model.TemplateError) as caught:
            validate(rule)
        self.assertIn("{{rapport}}", str(caught.exception))
        rule.action.format = "markdown"
        validate(rule)

    def test_reply_rule_body_braces_are_not_checked(self):
        rule = new_rule("reply")
        rule.action.body = "{{prenom}} {{ autre chose }} {{"
        rule.action.subject = "{{x}} {subject}"
        validate(rule)

    def test_reply_rule_refuses_a_report_variable(self):
        for where in ("body", "subject"):
            with self.subTest(where=where):
                rule = new_rule("reply")
                setattr(rule.action, where, "Voir {{ recus_total }}")
                with self.assertRaises(model.TemplateError) as caught:
                    validate(rule)
                self.assertIn(
                    t("mail_rules_err_template_reply_var"),
                    str(caught.exception),
                )

    def test_template_names_are_stripped_unique_and_ordered(self):
        self.assertEqual(
            model.template_names("{{ b }}{{a}}{{b}} {{ c"), ["b", "a"]
        )


class TestValidate(unittest.TestCase):
    """Chaque refus de `validate`, un par contrôle."""

    def assert_refused(self, rule):
        with self.assertRaises(RuleError):
            validate(rule)

    def test_sample_rule_is_valid(self):
        validate(sample_rule())

    def test_glob_on_subject_is_refused(self):
        self.assert_refused(rule_with(cond(op="glob", value="*devis*")))

    def test_not_group_with_two_children_is_refused(self):
        group = Group(op="not", children=[cond(), cond(value="facture")])
        self.assert_refused(rule_with(group))

    def test_invalid_regex_is_refused(self):
        self.assert_refused(rule_with(cond(mode="regex", value="(abc")))

    def test_nested_quantifier_is_refused(self):
        for pattern in (
            "(a+)+",
            "(a*)*",
            "(a+)*",
            "(a{2,})+",
            "((a+))+",
            "(?:(?:a+))*",
            "((a)+)+",
            "(?P<n>a+)+",
            "(a+) +",
        ):
            with self.subTest(pattern=pattern):
                self.assert_refused(
                    rule_with(cond(mode="regex", value=pattern))
                )

    def test_plain_alternation_with_quantifier_is_accepted(self):
        validate(rule_with(cond(mode="regex", value="(x|y)+")))

    def test_escaped_or_class_parentheses_are_not_groups(self):
        for pattern in (r"\(a+\)+", "[(]a+[)]+", "([+])+", r"(a\+)+"):
            with self.subTest(pattern=pattern):
                validate(rule_with(cond(mode="regex", value=pattern)))

    def test_quantified_groups_side_by_side_are_accepted(self):
        for pattern in ("((x|y))+", "(a)+(b)+", "(a+)?"):
            with self.subTest(pattern=pattern):
                validate(rule_with(cond(mode="regex", value=pattern)))

    def test_too_long_regex_is_refused(self):
        pattern = "a" * (model.MAX_REGEX_LEN + 1)
        self.assert_refused(rule_with(cond(mode="regex", value=pattern)))

    def test_regex_mode_is_ignored_for_a_glob(self):
        validate(
            rule_with(
                cond(
                    field="from",
                    op="glob",
                    value="*@example.net",
                    mode="regex",
                )
            )
        )

    def test_zero_minutes_is_refused_even_unchecked(self):
        rule = new_rule()
        rule.throttle_minutes = 0
        self.assert_refused(rule)
        rule.throttle_enabled = False
        self.assert_refused(rule)

    def test_bounds_of_age_and_hold(self):
        for attr, value in (
            ("throttle_minutes", model.THROTTLE_MINUTES_MAX + 1),
            ("max_age_hours", 0),
            ("max_age_hours", model.MAX_AGE_HOURS_MAX + 1),
            ("hold_first", 0),
            ("hold_first", model.HOLD_FIRST_MAX + 1),
        ):
            with self.subTest(attr=attr, value=value):
                rule = new_rule()
                setattr(rule, attr, value)
                self.assert_refused(rule)

    def test_depth_nine_is_refused_and_eight_accepted(self):
        def chain(depth):
            node = cond()
            for _ in range(depth):
                node = Group(children=[node])
            return node

        rule = new_rule()
        rule.filter = chain(model.MAX_DEPTH)
        validate(rule)
        rule.filter = chain(model.MAX_DEPTH + 1)
        self.assert_refused(rule)

    def test_too_many_nodes_is_refused(self):
        rule = new_rule()
        rule.filter = Group(children=[cond() for _ in range(model.MAX_NODES)])
        self.assert_refused(rule)

    def test_image_name_escaping_the_media_folder_is_refused(self):
        for name in ("../x.png", "a/b.png", "a\\b.png", ".cache.png", ""):
            with self.subTest(name=name):
                rule = new_rule()
                rule.action.images = [MediaRef(name, "00", "image/png")]
                self.assert_refused(rule)

    def test_image_type_outside_the_list_is_refused(self):
        rule = new_rule()
        rule.action.images = [MediaRef("logo.svg", "00", "image/svg+xml")]
        self.assert_refused(rule)

    def test_unknown_kind_and_format_are_refused(self):
        rule = new_rule()
        rule.action.kind = "delete"
        self.assert_refused(rule)
        rule = new_rule()
        rule.action.format = "rtf"
        self.assert_refused(rule)

    def test_message_is_translated_and_names_the_fault(self):
        with self.assertRaises(RuleError) as caught:
            validate(rule_with(cond(field="bcc")))
        self.assertIn("bcc", str(caught.exception))
        self.assertNotIn("mail_rules_", str(caught.exception))


class TestValidateNode(unittest.TestCase):
    """L'éditeur de condition valide un nœud seul."""

    def test_glob_on_subject_alone_is_refused(self):
        with self.assertRaises(RuleError):
            validate_node(cond(op="glob", value="*x*"))

    def test_blank_value_alone_is_refused(self):
        with self.assertRaises(RuleError):
            validate_node(cond(value="   "))

    def test_too_long_value_is_refused(self):
        with self.assertRaises(RuleError):
            validate_node(cond(value="x" * (model.MAX_VALUE_LEN + 1)))

    def test_valid_condition_passes(self):
        validate_node(cond(field="to_cc", op="glob", value="*@example.net"))


class TestMessageView(unittest.TestCase):
    """Une vue naît d'un en-tête de synchro comme d'une ligne du cache."""

    def test_message_view_reads_the_size(self):
        for taille, attendu in ((4096, 4096), (None, 0), ("x", 0), (-5, 0)):
            with self.subTest(taille=taille):
                header = SimpleNamespace(uid=1, size=taille)
                self.assertEqual(message_view(header, 1).size, attendu)
        self.assertEqual(message_view(SimpleNamespace(uid=1), 1).size, 0)

    def test_header_with_every_field(self):
        header = SimpleNamespace(
            uid=7,
            date=0,
            msgid="<a@example.org>",
            frm="carole.regle@example.org",
            to="boite.regles@example.org",
            cc="denis.tri@example.org",
            subject="Devis",
            in_reply_to="",
            references="",
            internaldate=1793000000,
            extra={"Precedence": "bulk"},
        )
        view = message_view(header, 42)
        self.assertEqual(view.uid, 7)
        self.assertEqual(view.uidvalidity, 42)
        self.assertEqual(view.cc, "denis.tri@example.org")
        self.assertEqual(view.internaldate, 1793000000)
        self.assertEqual(dict(view.extra), {"precedence": "bulk"})

    def test_message_meta_has_no_cc_nor_extra_and_uses_received_at(self):
        meta = MessageMeta(
            uid=3,
            date=0,
            size=10,
            flags="",
            msgid="<b@example.org>",
            frm="bruno.filtre@example.net",
            to="boite.regles@example.org",
            subject="Bonjour",
            snippet="",
        )
        # Posé après coup : le champ n'existe qu'à partir du cache v6.
        meta.received_at = 1793000123
        view = message_view(meta, 9)
        self.assertEqual(view.cc, "")
        self.assertEqual(dict(view.extra), {})
        self.assertEqual(view.internaldate, 1793000123)

    def test_unknown_reception_date_is_zero(self):
        header = SimpleNamespace(
            uid=1, msgid="", frm="", to="", subject="", internaldate=0
        )
        self.assertEqual(message_view(header, 1).internaldate, 0)

    def test_view_extra_is_read_only(self):
        header = SimpleNamespace(
            uid=1, msgid="", frm="", to="", subject="", extra={"x-loop": "a"}
        )
        view = message_view(header, 1)
        with self.assertRaises(TypeError):
            view.extra["x-loop"] = "b"


class TestFingerprint(unittest.TestCase):
    """L'empreinte change avec le message envoyé, pas avec le reste."""

    def test_stable_regardless_of_dict_order(self):
        rule = sample_rule()
        rule.action.options = {"b": 1, "a": 2}
        other = sample_rule()
        other.action.options = {"a": 2, "b": 1}
        self.assertEqual(rule.fingerprint(), other.fingerprint())

    def test_unchanged_by_name_order_limits_and_arming(self):
        rule = sample_rule()
        before = rule.fingerprint()
        rule.name = "Autre"
        rule.order = 99
        rule.enabled = False
        rule.stop_after = True
        rule.throttle_enabled = False
        rule.throttle_minutes = 5
        rule.max_age_hours = 2
        rule.hold_first = 3
        rule.armed = Armed(1, 2, 3)
        rule.extra = {"x": 1}
        self.assertEqual(rule.fingerprint(), before)

    def test_changed_by_condition_body_format_and_image_hash(self):
        base = sample_rule().fingerprint()
        changes = {
            "condition": lambda r: setattr(
                r.filter.children[0], "value", "*@example.com"
            ),
            "body": lambda r: setattr(r.action, "body", "Autre corps"),
            "format": lambda r: setattr(r.action, "format", "html"),
            "image": lambda r: setattr(r.action.images[0], "sha256", "ffff"),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                rule = sample_rule()
                change(rule)
                self.assertNotEqual(rule.fingerprint(), base)

    def test_is_sixteen_hex_characters(self):
        self.assertRegex(sample_rule().fingerprint(), r"^[0-9a-f]{16}$")


class TestTestsBody(unittest.TestCase):
    def test_sample_rule_tests_the_body(self):
        self.assertTrue(sample_rule().tests_body())

    def test_rule_without_body_condition(self):
        self.assertFalse(rule_with(cond()).tests_body())
        self.assertFalse(new_rule().tests_body())

    def test_default_action_is_a_reply(self):
        self.assertEqual(Action().kind, "reply")


if __name__ == "__main__":
    unittest.main()
