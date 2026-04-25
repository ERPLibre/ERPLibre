#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Unit tests for translator pure helpers (no audio / network).

Run: python3 -m unittest script.stream_deck.test_translator
Or:  ./script/stream_deck/test_translator.py
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import translator  # noqa: E402


class _SettingsFixture:
    """Patch translator._load_settings to read from a per-test JSON dict."""

    def __init__(self, data=None):
        self.data = data or {}

    def __enter__(self):
        self._patch = mock.patch.object(
            translator, "_load_settings", return_value=self.data,
        )
        self._patch.start()
        return self

    def __exit__(self, *_):
        self._patch.stop()


class TestLocale(unittest.TestCase):
    def test_locale_short_fr(self):
        with mock.patch.dict(os.environ, {"LANG": "fr_CA.UTF-8"}, clear=False):
            self.assertEqual(translator._locale_short(), "fr")

    def test_locale_short_en(self):
        with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}, clear=False):
            self.assertEqual(translator._locale_short(), "en")

    def test_locale_short_no_underscore(self):
        with mock.patch.dict(os.environ, {"LANG": "C"}, clear=False):
            self.assertEqual(translator._locale_short(), "c")

    def test_locale_short_empty_falls_back(self):
        env = {k: v for k, v in os.environ.items() if k not in ("LANG", "LC_ALL")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(translator._locale_short(), "en")

    def test_default_translate_target_known_locales(self):
        for code, expected in (
            ("fr_CA.UTF-8", "French"),
            ("es_ES", "Spanish"),
            ("de_DE.UTF-8", "German"),
            ("it_IT", "Italian"),
            ("pt_BR", "Portuguese"),
            ("en_US", "English"),
        ):
            with mock.patch.dict(os.environ, {"LANG": code}, clear=False):
                self.assertEqual(
                    translator.default_translate_target(),
                    expected, msg=code,
                )

    def test_default_translate_target_unknown_falls_back(self):
        with mock.patch.dict(os.environ, {"LANG": "ja_JP.UTF-8"}, clear=False):
            self.assertEqual(
                translator.default_translate_target(), "English",
            )


class TestSettingsReaders(unittest.TestCase):
    def test_stt_language_default_is_auto(self):
        with _SettingsFixture({}):
            self.assertEqual(translator.stt_language(), "auto")

    def test_stt_language_lowercased(self):
        with _SettingsFixture({"translator_stt_language": " FR "}):
            self.assertEqual(translator.stt_language(), "fr")

    def test_stt_model_size_default_is_tiny(self):
        with _SettingsFixture({}):
            self.assertEqual(translator.stt_model_size(), "tiny")

    def test_stt_model_size_validates_against_whitelist(self):
        with _SettingsFixture({"translator_stt_model": "huge"}):
            self.assertEqual(translator.stt_model_size(), "tiny")
        with _SettingsFixture({"translator_stt_model": "BASE"}):
            self.assertEqual(translator.stt_model_size(), "base")

    def test_llm_model_preference_default_empty(self):
        with _SettingsFixture({}):
            self.assertEqual(translator.llm_model_preference(), "")

    def test_llm_model_preference_strips(self):
        with _SettingsFixture({"translator_llm_model": "  llama:7b  "}):
            self.assertEqual(
                translator.llm_model_preference(), "llama:7b",
            )

    def test_recording_timeout_seconds_default_zero(self):
        with _SettingsFixture({}):
            self.assertEqual(translator.recording_timeout_seconds(), 0)

    def test_recording_timeout_seconds_invalid_falls_back(self):
        with _SettingsFixture({"translator_recording_timeout": "abc"}):
            self.assertEqual(translator.recording_timeout_seconds(), 0)
        with _SettingsFixture({"translator_recording_timeout": -5}):
            self.assertEqual(translator.recording_timeout_seconds(), 0)
        with _SettingsFixture({"translator_recording_timeout": 60}):
            self.assertEqual(translator.recording_timeout_seconds(), 60)


class TestPromptOverrides(unittest.TestCase):
    def test_load_prompt_overrides_filters_non_strings(self):
        with _SettingsFixture({
            "translator_prompts": {
                "translate": "Custom",
                "chat": 42,  # filtered out
                "extra": ["list"],  # filtered out
            },
        }):
            out = translator._load_prompt_overrides()
            self.assertEqual(out, {"translate": "Custom"})

    def test_get_prompt_template_uses_override(self):
        with _SettingsFixture({
            "translator_prompts": {"translate": "Override {text}"},
        }):
            self.assertEqual(
                translator.get_prompt_template("translate", wm_class=""),
                "Override {text}",
            )

    def test_get_prompt_template_falls_back_to_default(self):
        with _SettingsFixture({}):
            with mock.patch.dict(
                os.environ, {"LANG": "fr_CA"}, clear=False,
            ):
                template = translator.get_prompt_template(
                    "translate", wm_class="",
                )
                self.assertIn("French", template)
                self.assertIn("{text}", template)

    def test_per_app_override_wins_over_global(self):
        with _SettingsFixture({
            "translator_prompts": {"translate": "Global {text}"},
            "translator_prompts_per_app": {
                "Code": {"translate": "Code-specific {text}"},
            },
        }):
            self.assertEqual(
                translator.get_prompt_template(
                    "translate", wm_class="Code",
                ),
                "Code-specific {text}",
            )

    def test_per_app_override_skipped_when_class_unknown(self):
        with _SettingsFixture({
            "translator_prompts": {"translate": "Global {text}"},
            "translator_prompts_per_app": {
                "Code": {"translate": "Code-specific {text}"},
            },
        }):
            self.assertEqual(
                translator.get_prompt_template(
                    "translate", wm_class="Firefox",
                ),
                "Global {text}",
            )

    def test_per_app_filters_non_string_values(self):
        with _SettingsFixture({
            "translator_prompts_per_app": {
                "Code": {
                    "translate": "Yes {text}",
                    "chat": 42,
                },
            },
        }):
            with mock.patch.dict(
                os.environ, {"LANG": "en_US"}, clear=False,
            ):
                # translate: per-app wins
                self.assertEqual(
                    translator.get_prompt_template(
                        "translate", wm_class="Code",
                    ),
                    "Yes {text}",
                )
                # chat: filtered, falls back to default
                tmpl = translator.get_prompt_template(
                    "chat", wm_class="Code",
                )
                self.assertEqual(tmpl, "{text}")


class TestLLMPostprocess(unittest.TestCase):
    def _fake_backend(self, response="LLM response"):
        backend = mock.Mock()
        backend.chat.return_value = response
        return backend

    def test_off_mode_returns_original(self):
        backend = self._fake_backend()
        out = translator.llm_postprocess(
            "hello", translator.LLM_MODE_OFF, backend,
        )
        self.assertEqual(out, "hello")
        backend.chat.assert_not_called()

    def test_translate_mode_substitutes_text(self):
        backend = self._fake_backend("Bonjour")
        with _SettingsFixture({}):
            out = translator.llm_postprocess(
                "Hello", translator.LLM_MODE_TRANSLATE, backend,
            )
        self.assertEqual(out, "Bonjour")
        backend.chat.assert_called_once()
        prompt = backend.chat.call_args[0][0]
        self.assertIn("Hello", prompt)

    def test_falls_back_to_text_on_empty_response(self):
        backend = self._fake_backend("")
        with _SettingsFixture({}):
            out = translator.llm_postprocess(
                "Hello", translator.LLM_MODE_TRANSLATE, backend,
            )
        self.assertEqual(out, "Hello")

    def test_no_backend_returns_original(self):
        out = translator.llm_postprocess(
            "Hello", translator.LLM_MODE_TRANSLATE, None,
        )
        self.assertEqual(out, "Hello")

    def test_template_without_placeholder_appends_text(self):
        backend = self._fake_backend("Reply")
        with _SettingsFixture({
            "translator_prompts": {"translate": "Static template"},
        }):
            out = translator.llm_postprocess(
                "Hello", translator.LLM_MODE_TRANSLATE, backend,
            )
        prompt = backend.chat.call_args[0][0]
        self.assertEqual(out, "Reply")
        self.assertIn("Static template", prompt)
        self.assertIn("Hello", prompt)


class TestRecommendModel(unittest.TestCase):
    def test_xs_for_tiny_machines(self):
        self.assertEqual(
            translator.recommend_model({"ram_gb": 2, "gpu_vram_gb": 0}),
            "qwen2.5:0.5b-instruct",
        )

    def test_s_for_small(self):
        self.assertEqual(
            translator.recommend_model({"ram_gb": 8, "gpu_vram_gb": 0}),
            "qwen2.5:1.5b-instruct",
        )

    def test_m_for_medium(self):
        self.assertEqual(
            translator.recommend_model({"ram_gb": 16, "gpu_vram_gb": 0}),
            "llama3.2:3b-instruct",
        )

    def test_l_for_high_ram_or_gpu(self):
        self.assertEqual(
            translator.recommend_model({"ram_gb": 32, "gpu_vram_gb": 0}),
            "llama3.1:8b-instruct-q4_K_M",
        )
        self.assertEqual(
            translator.recommend_model({"ram_gb": 16, "gpu_vram_gb": 8}),
            "llama3.1:8b-instruct-q4_K_M",
        )

    def test_xl_for_big_gpu(self):
        self.assertEqual(
            translator.recommend_model({"ram_gb": 64, "gpu_vram_gb": 24}),
            "llama3.1:8b-instruct-q5_K_M",
        )


class TestCloudBackends(unittest.TestCase):
    def test_no_keys_means_no_cloud(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
        with mock.patch.dict(os.environ, env, clear=True):
            with _SettingsFixture({}):
                self.assertFalse(translator.cloud_backends_active())
                # Detected list excludes cloud entries
                self.assertNotIn(
                    "openai-chat",
                    [b.name for b in translator.detect_llm_backends()],
                )

    def test_env_key_activates_cloud(self):
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False,
        ):
            with _SettingsFixture({}):
                self.assertTrue(translator.cloud_backends_active())

    def test_settings_key_activates_cloud(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
        with mock.patch.dict(os.environ, env, clear=True):
            with _SettingsFixture({"translator_anthropic_api_key": "sk-ant"}):
                self.assertTrue(translator.cloud_backends_active())

    def test_anthropic_default_model(self):
        with mock.patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "sk-ant"}, clear=False,
        ):
            with _SettingsFixture({}):
                b = translator.AnthropicBackend()
                self.assertTrue(b.available)
                self.assertIn("claude", b.model)


class TestVAD(unittest.TestCase):
    def test_vad_enabled_default_false(self):
        with _SettingsFixture({}):
            self.assertFalse(translator.vad_enabled())

    def test_vad_enabled_true(self):
        with _SettingsFixture({"translator_vad_enabled": True}):
            self.assertTrue(translator.vad_enabled())

    def test_vad_silence_seconds_default(self):
        with _SettingsFixture({}):
            self.assertEqual(translator.vad_silence_seconds(), 2.0)

    def test_vad_silence_seconds_clamps_min(self):
        with _SettingsFixture({"translator_vad_silence_seconds": 0.1}):
            self.assertEqual(translator.vad_silence_seconds(), 0.5)

    def test_vad_silence_db_default(self):
        with _SettingsFixture({}):
            self.assertEqual(translator.vad_silence_db(), -30)

    def test_vad_silence_db_invalid_falls_back(self):
        with _SettingsFixture({"translator_vad_silence_db": "loud"}):
            self.assertEqual(translator.vad_silence_db(), -30)


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        self._tmp.close()
        os.unlink(self._tmp.name)
        self._patch = mock.patch.object(
            translator, "HISTORY_FILE", self._tmp.name,
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def test_append_then_load(self):
        translator.append_history("hello", language="fr")
        translator.append_history("world", language="en")
        entries = translator.load_history()
        self.assertEqual([e["text"] for e in entries], ["hello", "world"])

    def test_empty_text_is_ignored(self):
        translator.append_history("")
        self.assertEqual(translator.load_history(), [])

    def test_ring_buffer_trims_to_max(self):
        for i in range(translator.HISTORY_MAX + 5):
            translator.append_history(f"msg{i}")
        entries = translator.load_history()
        self.assertEqual(len(entries), translator.HISTORY_MAX)
        self.assertEqual(entries[0]["text"], "msg5")
        self.assertEqual(entries[-1]["text"], f"msg{translator.HISTORY_MAX + 4}")

    def test_clear_removes_file(self):
        translator.append_history("hello")
        translator.clear_history()
        self.assertEqual(translator.load_history(), [])

    def test_load_handles_missing_file(self):
        self.assertEqual(translator.load_history(), [])

    def test_load_filters_invalid_entries(self):
        with open(self._tmp.name, "w") as f:
            json.dump({"entries": [
                {"text": "kept"},
                {"no_text": "dropped"},
                "not-a-dict",
                {"text": ""},
            ]}, f)
        entries = translator.load_history()
        self.assertEqual([e["text"] for e in entries], ["kept"])


if __name__ == "__main__":
    unittest.main()
