#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import ast
import unittest

from script.code_generator.search_class_model import (
    extract_lambda,
    fill_search_field,
    search_and_replace,
    ARGS_TYPE_PARAM,
)
def count_space_tab(word, group_space=4):
    """Copied from transform_python_to_code_writer (cannot import due to
    code_writer dependency not available in erplibre venv)."""
    nb_tab = 0
    nb_space = 0
    for s_char in word:
        if s_char in ["\n", "\r"]:
            return -1, 0
        elif s_char in ["\t"]:
            nb_tab += 1
        elif s_char == " ":
            nb_space += 1
            if nb_space == group_space:
                nb_space = 0
                nb_tab += 1
        else:
            break
    return nb_tab, nb_space


class TestCountSpaceTab(unittest.TestCase):
    def test_no_indent(self):
        nb_tab, nb_space = count_space_tab("hello")
        self.assertEqual(nb_tab, 0)
        self.assertEqual(nb_space, 0)

    def test_four_spaces(self):
        nb_tab, nb_space = count_space_tab("    hello")
        self.assertEqual(nb_tab, 1)
        self.assertEqual(nb_space, 0)

    def test_eight_spaces(self):
        nb_tab, nb_space = count_space_tab("        hello")
        self.assertEqual(nb_tab, 2)
        self.assertEqual(nb_space, 0)

    def test_partial_spaces(self):
        nb_tab, nb_space = count_space_tab("      hello")
        self.assertEqual(nb_tab, 1)
        self.assertEqual(nb_space, 2)

    def test_tab_character(self):
        nb_tab, nb_space = count_space_tab("\thello")
        self.assertEqual(nb_tab, 1)
        self.assertEqual(nb_space, 0)

    def test_newline_returns_minus_one(self):
        nb_tab, nb_space = count_space_tab("\n")
        self.assertEqual(nb_tab, -1)
        self.assertEqual(nb_space, 0)

    def test_carriage_return(self):
        nb_tab, nb_space = count_space_tab("\r")
        self.assertEqual(nb_tab, -1)
        self.assertEqual(nb_space, 0)

    def test_custom_group_space(self):
        nb_tab, nb_space = count_space_tab("  hello", group_space=2)
        self.assertEqual(nb_tab, 1)
        self.assertEqual(nb_space, 0)

    def test_mixed_tab_and_spaces(self):
        nb_tab, nb_space = count_space_tab("\t    hello")
        self.assertEqual(nb_tab, 2)
        self.assertEqual(nb_space, 0)


class TestExtractLambda(unittest.TestCase):
    def test_simple_lambda(self):
        node = ast.parse("lambda x: x + 1", mode="eval").body
        result = extract_lambda(node)
        self.assertIn("lambda", result)
        self.assertIn("x + 1", result)

    def test_strips_outer_parens(self):
        code = "(lambda x: x)"
        node = ast.parse(code, mode="eval").body
        result = extract_lambda(node)
        self.assertFalse(result.startswith("("))


class TestFillSearchField(unittest.TestCase):
    def test_constant_string(self):
        node = ast.parse("'hello'", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, "hello")

    def test_constant_int(self):
        node = ast.parse("42", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, 42)

    def test_constant_bool(self):
        node = ast.parse("True", mode="eval").body
        result = fill_search_field(node)
        self.assertTrue(result)

    def test_negative_number(self):
        node = ast.parse("-5", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, -5)

    def test_name(self):
        node = ast.parse("my_var", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, "my_var")

    def test_attribute(self):
        node = ast.parse("fields.Date.today", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, "fields.Date.today")

    def test_list(self):
        node = ast.parse("[1, 2, 3]", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, [1, 2, 3])

    def test_dict(self):
        node = ast.parse("{'a': 1, 'b': 2}", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_tuple(self):
        node = ast.parse("(1, 2)", mode="eval").body
        result = fill_search_field(node)
        self.assertEqual(result, (1, 2))

    def test_lambda(self):
        node = ast.parse("lambda self: self.env", mode="eval").body
        result = fill_search_field(node)
        self.assertIn("lambda", result)

    def test_unsupported_returns_none(self):
        node = ast.parse("{x for x in y}", mode="eval").body
        result = fill_search_field(node)
        self.assertIsNone(result)


class TestSearchAndReplace(unittest.TestCase):
    def test_replace_quoted_value(self):
        content = 'template_model_name = "old_model"'
        result = search_and_replace(
            content, "hooks.py", "new_model"
        )
        self.assertIn('"new_model"', result)
        self.assertNotIn("old_model", result)

    def test_empty_models_name_returns_unchanged(self):
        content = 'template_model_name = "old"'
        result = search_and_replace(content, "hooks.py", "")
        self.assertEqual(result, content)

    def test_missing_search_word_returns_error(self):
        content = "other_variable = 'value'"
        result = search_and_replace(content, "hooks.py", "model")
        self.assertEqual(result, -1)

    def test_custom_search_word(self):
        content = 'my_custom_var = "old_value"'
        result = search_and_replace(
            content,
            "hooks.py",
            "new_value",
            search_word="my_custom_var",
        )
        self.assertIn('"new_value"', result)


class TestArgsTypeParam(unittest.TestCase):
    def test_char_has_string(self):
        self.assertIn("string", ARGS_TYPE_PARAM["Char"])

    def test_many2one_has_comodel(self):
        self.assertIn("comodel_name", ARGS_TYPE_PARAM["Many2one"])

    def test_one2many_has_inverse(self):
        self.assertIn("inverse_name", ARGS_TYPE_PARAM["One2many"])

    def test_many2many_has_relation(self):
        self.assertIn("relation", ARGS_TYPE_PARAM["Many2many"])

    def test_id_is_empty(self):
        self.assertEqual(ARGS_TYPE_PARAM["Id"], [])

    def test_selection_has_selection(self):
        self.assertIn("selection", ARGS_TYPE_PARAM["Selection"])
