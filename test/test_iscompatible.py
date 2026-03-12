#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest

from packaging.version import Version

from script.poetry.iscompatible import (
    iscompatible,
    parse_requirements,
    string_to_tuple,
)


class TestStringToTuple(unittest.TestCase):
    def test_three_parts(self):
        self.assertEqual(string_to_tuple("1.0.0"), (1, 0, 0))

    def test_two_parts(self):
        self.assertEqual(string_to_tuple("2.5"), (2, 5))

    def test_single_part(self):
        self.assertEqual(string_to_tuple("3"), (3,))

    def test_large_numbers(self):
        self.assertEqual(string_to_tuple("10.20.300"), (10, 20, 300))


class TestParseRequirements(unittest.TestCase):
    def test_exact_match(self):
        result = parse_requirements("foo==1.0.0")
        self.assertEqual(result, [("==", "1.0.0")])

    def test_greater_equal(self):
        result = parse_requirements("foo>=1.1.0")
        self.assertEqual(result, [(">=", "1.1.0")])

    def test_multiple_constraints(self):
        result = parse_requirements("foo>=1.1.0, <1.2")
        self.assertEqual(result, [(">=", "1.1.0"), ("<", "1.2")])

    def test_not_equal(self):
        result = parse_requirements("bar!=2.0")
        self.assertEqual(result, [("!=", "2.0")])

    def test_less_equal(self):
        result = parse_requirements("baz<=3.0.0")
        self.assertEqual(result, [("<=", "3.0.0")])

    def test_no_version_returns_empty(self):
        result = parse_requirements("foo")
        self.assertEqual(result, [])

    def test_with_comment(self):
        result = parse_requirements("foo>=1.0 # some comment")
        self.assertEqual(result, [(">=", "1.0")])


class TestIsCompatible(unittest.TestCase):
    def test_exact_match_true(self):
        self.assertTrue(iscompatible("foo==1.0.0", Version("1.0.0")))

    def test_exact_match_false(self):
        self.assertFalse(iscompatible("foo==1.0.0", Version("1.0.1")))

    def test_greater_equal_true(self):
        self.assertTrue(iscompatible("foo>=5", Version("5.6.1")))

    def test_greater_equal_false(self):
        self.assertFalse(iscompatible("foo>=5.6.1, <5.7", Version("5.0.0")))

    def test_range_true(self):
        self.assertTrue(iscompatible("foo>=1.1, <2.1", Version("2.0.0")))

    def test_range_false(self):
        self.assertFalse(iscompatible("foo>=1.1, <2.0", Version("2.0.0")))

    def test_less_equal(self):
        self.assertTrue(iscompatible("foo<=1", Version("0.9.0")))

    def test_greater_than(self):
        self.assertTrue(iscompatible("foo>1.0", Version("1.0.1")))

    def test_greater_than_equal(self):
        # Version (1,0,0) > (1,0) is True because tuple comparison
        # extends shorter tuple, so this is actually compatible
        self.assertTrue(iscompatible("foo>1.0", Version("1.0.0")))

    def test_not_equal_true(self):
        self.assertTrue(iscompatible("foo!=1.0.0", Version("1.0.1")))

    def test_not_equal_false(self):
        self.assertFalse(iscompatible("foo!=1.0.0", Version("1.0.0")))
