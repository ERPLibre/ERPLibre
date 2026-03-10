#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from unittest.mock import patch

from script.todo import todo_i18n


class TestTranslations(unittest.TestCase):
    """Test TRANSLATIONS dictionary integrity."""

    def test_all_entries_have_fr_and_en(self):
        for key, entry in todo_i18n.TRANSLATIONS.items():
            self.assertIn("fr", entry, f"Key '{key}' missing 'fr' translation")
            self.assertIn("en", entry, f"Key '{key}' missing 'en' translation")

    def test_no_empty_translations(self):
        for key, entry in todo_i18n.TRANSLATIONS.items():
            for lang in ("fr", "en"):
                self.assertTrue(
                    len(entry[lang]) > 0,
                    f"Key '{key}' has empty '{lang}' translation",
                )

    def test_translations_not_empty(self):
        self.assertGreater(len(todo_i18n.TRANSLATIONS), 0)


class TestT(unittest.TestCase):
    """Test t() translation function."""

    def setUp(self):
        todo_i18n._current_lang = None

    def tearDown(self):
        todo_i18n._current_lang = None

    def test_returns_french_when_lang_fr(self):
        todo_i18n.set_lang("fr")
        result = todo_i18n.t("menu_quit")
        self.assertEqual(result, "Quitter")

    def test_returns_english_when_lang_en(self):
        todo_i18n.set_lang("en")
        result = todo_i18n.t("menu_quit")
        self.assertEqual(result, "Quit")

    def test_unknown_key_returns_key(self):
        todo_i18n.set_lang("fr")
        result = todo_i18n.t("nonexistent_key_xyz")
        self.assertEqual(result, "nonexistent_key_xyz")

    def test_fallback_to_fr_if_lang_missing(self):
        todo_i18n.set_lang("de")
        result = todo_i18n.t("menu_quit")
        self.assertEqual(result, "Quitter")


class TestGetLang(unittest.TestCase):
    """Test get_lang() function."""

    def setUp(self):
        todo_i18n._current_lang = None

    def tearDown(self):
        todo_i18n._current_lang = None

    def test_returns_cached_lang(self):
        todo_i18n._current_lang = "en"
        result = todo_i18n.get_lang()
        self.assertEqual(result, "en")

    def test_reads_from_env_var_sh(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="en"\n')
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "en")
            finally:
                os.unlink(f.name)

    def test_reads_unquoted_lang(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write("EL_LANG=fr\n")
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "fr")
            finally:
                os.unlink(f.name)

    def test_env_variable_fallback(self):
        with patch.object(
            todo_i18n,
            "CONFIG_OVERRIDE_PRIVATE_FILE",
            "/nonexistent/path",
        ), patch.dict(os.environ, {"EL_LANG": "en"}):
            result = todo_i18n.get_lang()
        self.assertEqual(result, "en")

    def test_default_is_fr(self):
        with patch.object(
            todo_i18n,
            "CONFIG_OVERRIDE_PRIVATE_FILE",
            "/nonexistent/path",
        ), patch.dict(os.environ, {}, clear=True):
            result = todo_i18n.get_lang()
        self.assertEqual(result, "fr")

    def test_invalid_lang_in_file_falls_through(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="de"\n')
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ), patch.dict(os.environ, {}, clear=True):
                    result = todo_i18n.get_lang()
                self.assertEqual(result, "fr")
            finally:
                os.unlink(f.name)


class TestSetLang(unittest.TestCase):
    """Test set_lang() function."""

    def setUp(self):
        todo_i18n._current_lang = None

    def tearDown(self):
        todo_i18n._current_lang = None

    def test_sets_current_lang(self):
        todo_i18n.set_lang("en")
        self.assertEqual(todo_i18n._current_lang, "en")

    def test_persists_to_file_update(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="fr"\nOTHER=value\n')
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ):
                    todo_i18n.set_lang("en")
                with open(f.name) as rf:
                    content = rf.read()
                self.assertIn('EL_LANG="en"', content)
                self.assertIn("OTHER=value", content)
            finally:
                os.unlink(f.name)

    def test_persists_to_file_append(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write("SOME_VAR=123\n")
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ):
                    todo_i18n.set_lang("en")
                with open(f.name) as rf:
                    content = rf.read()
                self.assertIn('EL_LANG="en"', content)
                self.assertIn("SOME_VAR=123", content)
            finally:
                os.unlink(f.name)

    def test_nonexistent_file_no_crash(self):
        with patch.object(
            todo_i18n,
            "CONFIG_OVERRIDE_PRIVATE_FILE",
            "/nonexistent/path",
        ):
            todo_i18n.set_lang("en")
        self.assertEqual(todo_i18n._current_lang, "en")


class TestLangIsConfigured(unittest.TestCase):
    """Test lang_is_configured() function."""

    def test_returns_true_when_configured(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write('EL_LANG="fr"\n')
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ):
                    result = todo_i18n.lang_is_configured()
                self.assertTrue(result)
            finally:
                os.unlink(f.name)

    def test_returns_false_when_not_configured(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write("SOME_VAR=123\n")
            f.flush()
            try:
                with patch.object(
                    todo_i18n, "CONFIG_OVERRIDE_PRIVATE_FILE", f.name
                ):
                    result = todo_i18n.lang_is_configured()
                self.assertFalse(result)
            finally:
                os.unlink(f.name)

    def test_returns_false_when_file_missing(self):
        with patch.object(
            todo_i18n,
            "CONFIG_OVERRIDE_PRIVATE_FILE",
            "/nonexistent/path",
        ):
            result = todo_i18n.lang_is_configured()
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
