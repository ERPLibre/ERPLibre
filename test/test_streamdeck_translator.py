#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""translator.py, the speech-to-text helpers of the deck, without vosk.

vosk is no requirement of .venv.streamdeck: the module imports it only in
VoskBackend, and a venv without it loads the module and reports that
backend unavailable. The module is loaded from its path under its own
name, beside the stub `translator` the deck tests install, with HOME on a
temporary directory that holds the vosk model directory.
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TRANSLATOR = ROOT / "script/stream_deck/translator.py"


class VoskIsOptional(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        # The model is there: only the import decides.
        Path(folder.name, ".cache/erplibre-home/vosk-model").mkdir(
            parents=True
        )
        home = mock.patch.dict(os.environ, {"HOME": folder.name})
        home.start()
        self.addCleanup(home.stop)

    def load(self, vosk):
        """translator.py loaded with `vosk` as the vosk module; None makes
        ``import vosk`` raise ImportError."""
        with mock.patch.dict(sys.modules, {"vosk": vosk}):
            spec = importlib.util.spec_from_file_location(
                "streamdeck_translator", TRANSLATOR
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module, module.VoskBackend()

    def test_without_vosk_the_module_loads_and_vosk_is_unavailable(self):
        _module, backend = self.load(None)
        self.assertFalse(backend.available)

    def test_with_vosk_and_its_model_vosk_is_available(self):
        _module, backend = self.load(types.ModuleType("vosk"))
        self.assertTrue(backend.available)


if __name__ == "__main__":
    unittest.main()
