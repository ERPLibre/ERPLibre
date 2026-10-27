#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import time
import unittest
from unittest import mock

from script.todo.mail.rules import model, regex_worker
from script.todo.mail.rules.filter import (
    BodyUnavailable,
    addr_specs,
    evaluate,
    match_condition,
    normalize_address,
    normalize_pattern,
    sole_address,
)
from script.todo.mail.rules.model import (
    Condition,
    Group,
    MessageView,
    RuleError,
)

IDNA_ADDRESS = "bruno.filtre@xn--filtr-fsa.example.net"


def view(**kwargs) -> MessageView:
    base = {
        "uid": 10,
        "uidvalidity": 1,
        "internaldate": 1793000000,
        "msgid": "<m@example.org>",
        "frm": "Carole Règle <carole.regle@example.org>",
        "to": "boite.regles@example.org",
        "cc": "",
        "subject": "Demande de devis",
    }
    base.update(kwargs)
    return MessageView(**base)


def cond(field="subject", value="devis", op="contains", mode="substring_ci"):
    return Condition(field=field, value=value, op=op, mode=mode)


class Loader:
    """Chargeur de corps qui compte ses appels."""

    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.text


class TestAddresses(unittest.TestCase):
    """Seule l'addr-spec compte, normalisée pour comparer."""

    def test_glob_matches_the_address(self):
        message = view(frm="bruno.filtre@example.net")
        node = cond("from", "*@example.net", op="glob")
        self.assertTrue(evaluate(node, message, None))

    def test_glob_ignores_the_display_label(self):
        message = view(
            frm='"bruno.filtre@example.net" <denis.tri@example.org>'
        )
        node = cond("from", "*@example.net", op="glob")
        self.assertFalse(evaluate(node, message, None))

    def test_glob_is_case_insensitive(self):
        message = view(frm="Bruno.Filtre@EXAMPLE.NET")
        self.assertTrue(
            evaluate(cond("from", "*@example.net", op="glob"), message, None)
        )

    def test_several_addresses_in_from(self):
        message = view(frm="denis.tri@example.org, bruno.filtre@example.net")
        node = cond("from", "*@example.net", op="glob")
        self.assertTrue(evaluate(node, message, None))

    def test_to_cc_reads_cc(self):
        message = view(
            to="denis.tri@example.org", cc="bruno.filtre@example.net"
        )
        node = cond("to_cc", "*@example.net", op="glob")
        self.assertTrue(evaluate(node, message, None))

    def test_idna_domain_is_normalized(self):
        self.assertEqual(
            normalize_address(IDNA_ADDRESS), "bruno.filtre@filtré.example.net"
        )

    def test_glob_pattern_with_idna_domain_is_normalized_the_same_way(self):
        self.assertEqual(
            normalize_pattern("*@XN--FILTR-FSA.example.net"),
            "*@filtré.example.net",
        )
        message = view(frm=IDNA_ADDRESS)
        for pattern in ("*@xn--filtr-fsa.example.net", "*@filtré.example.net"):
            with self.subTest(pattern=pattern):
                node = cond("from", pattern, op="glob")
                self.assertTrue(evaluate(node, message, None))

    def test_invalid_punycode_label_is_kept(self):
        self.assertEqual(
            normalize_address("denis.tri@xn--zz.example.org"),
            "denis.tri@xn--zz.example.org",
        )

    def test_addr_specs_raw_keeps_the_received_form(self):
        self.assertEqual(
            addr_specs(f"Bruno <{IDNA_ADDRESS}>", raw=True), [IDNA_ADDRESS]
        )

    def test_addr_specs_drops_entries_without_at_sign(self):
        self.assertEqual(addr_specs("undisclosed-recipients:;"), [])

    def test_addr_specs_drops_a_fragment_with_an_angle_bracket(self):
        # Un libellé décodé réduit à « " » : l'analyseur rend le chevron
        # avec l'adresse.
        self.assertEqual(addr_specs('" <bruno.filtre@example.net>'), [])


class TestSoleAddress(unittest.TestCase):
    """L'adresse unique et sans ambiguïté d'un From."""

    def test_single_mailbox(self):
        self.assertEqual(
            sole_address("Carole Règle <Carole.Regle@example.org>"),
            "carole.regle@example.org",
        )
        self.assertEqual(
            sole_address("Carole <Carole.Regle@example.org>", raw=True),
            "Carole.Regle@example.org",
        )

    def test_display_name_repeating_the_address_is_accepted(self):
        self.assertEqual(
            sole_address(
                '"carole.regle@example.org" <carole.regle@example.org>'
            ),
            "carole.regle@example.org",
        )

    def test_display_name_with_another_address_is_ambiguous(self):
        for header in (
            "denis.tri@example.org, <bruno.filtre@example.net>",
            "<denis.tri@example.org> <bruno.filtre@example.net>",
            '"denis.tri@example.org" <bruno.filtre@example.net>',
        ):
            with self.subTest(header=header):
                self.assertEqual(sole_address(header), "")

    def test_unparseable_or_empty_header_gives_nothing(self):
        for header in ("", "Inconnu", "Bruno [F] <bruno.filtre@example.net>"):
            with self.subTest(header=header):
                self.assertEqual(sole_address(header), "")


class TestContainsModes(unittest.TestCase):
    """Les cinq modes de « contient »."""

    def test_default_ignores_case_and_accents(self):
        self.assertTrue(
            match_condition(cond(value="desabonnement"), ["Désabonnement"])
        )

    def test_case_sensitive(self):
        node = cond(value="Devis", mode="case_sensitive")
        self.assertTrue(match_condition(node, ["Un Devis"]))
        self.assertFalse(match_condition(node, ["un devis"]))

    def test_exact_compares_whole_value_up_to_blanks(self):
        node = cond(value="demande  de devis", mode="exact")
        self.assertTrue(match_condition(node, ["Demande de DEVIS"]))
        self.assertFalse(match_condition(node, ["Re: Demande de devis"]))

    def test_word_does_not_match_inside_a_longer_word(self):
        node = cond(value="urgent", mode="word")
        self.assertTrue(match_condition(node, ["C'est URGENT !"]))
        self.assertFalse(match_condition(node, ["urgentissime"]))

    def test_regex(self):
        node = cond(value=r"(?i)facture\s+n°\d+", mode="regex")
        self.assertTrue(match_condition(node, ["Votre FACTURE n°42"]))
        self.assertFalse(match_condition(node, ["Votre facture"]))

    def test_regex_reads_only_the_first_characters(self):
        node = cond(value="aiguille", mode="regex")
        text = "x" * model.REGEX_TEXT_MAX + "aiguille"
        self.assertFalse(match_condition(node, [text]))
        self.assertTrue(match_condition(node, ["aiguille" + text]))

    def test_nested_quantifier_from_a_hand_edited_file_is_refused(self):
        with self.assertRaises(RuleError):
            match_condition(cond(value="(a+)+$", mode="regex"), ["aaaa!"])


class TestGroups(unittest.TestCase):
    """ET, OU, NON, et leurs cas vides."""

    def test_empty_all_matches_every_message(self):
        self.assertTrue(evaluate(Group("all", []), view(), None))

    def test_empty_any_matches_nothing(self):
        self.assertFalse(evaluate(Group("any", []), view(), None))

    def test_not(self):
        self.assertFalse(evaluate(Group("not", [cond()]), view(), None))
        self.assertTrue(
            evaluate(Group("not", [cond(value="facture")]), view(), None)
        )

    def test_three_levels_of_nesting(self):
        tree = Group(
            "all",
            [
                cond("from", "*@example.org", op="glob"),
                Group(
                    "any",
                    [
                        cond(value="facture"),
                        Group("not", [cond(value="désabonnement")]),
                    ],
                ),
            ],
        )
        self.assertTrue(evaluate(tree, view(), None))
        self.assertFalse(evaluate(tree, view(subject="Désabonnement"), None))
        self.assertFalse(
            evaluate(tree, view(frm="bruno.filtre@example.net"), None)
        )


class TestBody(unittest.TestCase):
    """Le corps est chargé tard, une fois, et jamais supposé vide."""

    def test_loader_not_called_when_and_fails_before_body(self):
        loader = Loader("urgent")
        tree = Group("all", [cond(value="facture"), cond("body", "urgent")])
        self.assertFalse(evaluate(tree, view(), loader))
        self.assertEqual(loader.calls, 0)

    def test_loader_called_once_for_two_body_conditions(self):
        loader = Loader("Merci, c'est urgent pour le devis.")
        tree = Group("all", [cond("body", "urgent"), cond("body", "devis")])
        self.assertTrue(evaluate(tree, view(), loader))
        self.assertEqual(loader.calls, 1)

    def test_missing_loader_under_not_raises_rather_than_matching(self):
        tree = Group("not", [cond("body", "urgent")])
        with self.assertRaises(BodyUnavailable):
            evaluate(tree, view(), None)

    def test_failing_loader_raises_and_is_not_called_again(self):
        loader = Loader(error=BodyUnavailable(online=True))
        tree = Group("any", [cond("body", "urgent"), cond("body", "devis")])
        with self.assertRaises(BodyUnavailable) as caught:
            evaluate(tree, view(), loader)
        self.assertTrue(caught.exception.online)
        self.assertEqual(loader.calls, 1)

    def test_unexpected_loader_error_becomes_body_unavailable(self):
        loader = Loader(error=OSError("lien coupé"))
        with self.assertRaises(BodyUnavailable):
            evaluate(Group("all", [cond("body", "x")]), view(), loader)
        self.assertEqual(loader.calls, 1)

    def test_body_is_truncated(self):
        from script.todo.mail.rules.filter import BODY_TEXT_MAX

        loader = Loader("x" * BODY_TEXT_MAX + "aiguille")
        self.assertFalse(evaluate(cond("body", "aiguille"), view(), loader))

    def test_body_unavailable_defaults_to_offline(self):
        self.assertFalse(BodyUnavailable().online)


class TestRegexTimeBudget(unittest.TestCase):
    """Des motifs que l'analyse statique laisse passer reculent en temps
    exponentiel ou polynomial : la recherche est bornée, et un dépassement
    n'est jamais un faux."""

    CATASTROPHIQUE = ("(a|a)+$", "a" * 40 + "b")

    def test_a_catastrophic_pattern_passes_validation_but_times_out(self):
        motif, texte = self.CATASTROPHIQUE
        self.assertIsNone(model.regex_fault(motif))
        debut = time.monotonic()
        with self.assertRaises(regex_worker.RegexTimeout):
            regex_worker.search_any(motif, [texte], timeout=0.3)
        self.assertLess(time.monotonic() - debut, 5)
        self.assertTrue(regex_worker.search_any("fo+", ["afoo"]))

    def test_polynomial_patterns_time_out_too(self):
        for motif, texte in (
            (".*foo.*bar", ("foo" * 4000)[: model.REGEX_TEXT_MAX]),
            ("a*a*b", "a" * model.REGEX_TEXT_MAX),
        ):
            with self.subTest(motif=motif):
                with self.assertRaises(regex_worker.RegexTimeout):
                    regex_worker.search_any(motif, [texte], timeout=0.3)

    def test_one_budget_covers_every_value_of_a_field(self):
        motif, texte = self.CATASTROPHIQUE
        debut = time.monotonic()
        with self.assertRaises(regex_worker.RegexTimeout):
            regex_worker.search_any(motif, [texte] * 50, timeout=0.3)
        self.assertLess(time.monotonic() - debut, 5)

    def test_a_timeout_under_not_raises_instead_of_matching(self):
        motif, texte = self.CATASTROPHIQUE
        racine = Group(op="not", children=[cond(value=motif, mode="regex")])
        with mock.patch.object(regex_worker, "REGEX_TIMEOUT_S", 0.3):
            with mock.patch(
                "script.todo.mail.rules.filter.search_any",
                lambda p, t: regex_worker.search_any(p, t, timeout=0.3),
            ):
                with self.assertRaises(regex_worker.RegexTimeout):
                    evaluate(racine, view(subject=texte), None)

    def test_a_spent_time_budget_raises_without_searching(self):
        with mock.patch.object(regex_worker._WORKER, "search") as cherche:
            with regex_worker.time_budget(0):
                with self.assertRaises(regex_worker.RegexTimeout):
                    regex_worker.search_any("x", ["x"])
        cherche.assert_not_called()

    def test_values_are_searched_like_re_search(self):
        self.assertTrue(
            match_condition(
                cond(value="^Re: ", mode="regex"), ["Fwd: x", "Re: devis"]
            )
        )
        self.assertFalse(match_condition(cond(value="^x$", mode="regex"), []))
        self.assertTrue(regex_worker.search_any("x", ["\udcffx"]))

    def test_a_refused_pattern_is_refused_before_the_search(self):
        with mock.patch.object(regex_worker._WORKER, "search") as cherche:
            with self.assertRaises(RuleError):
                match_condition(cond(value="(a+)+", mode="regex"), ["a"])
        cherche.assert_not_called()


if __name__ == "__main__":
    unittest.main()
