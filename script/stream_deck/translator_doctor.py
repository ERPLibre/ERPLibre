#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Translator stack audit — what is installed, what is missing.

Prints a one-line status for each layer (recorder, STT, output, LLM)
and the hardware-recommended LLM model. Use --recommend to print only
the recommended model tag (consumed by Make targets).
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import translator  # noqa: E402


def _ok(label, value):
    print(f"  ✓ {label:14s} {value}")


def _miss(label, hint):
    print(f"  ✗ {label:14s} MISSING — {hint}")


def main():
    if "--recommend" in sys.argv:
        hw = translator.detect_hardware()
        print(translator.recommend_model(hw))
        return

    print("=== Translator stack audit ===")

    rec = translator.detect_recorder()
    if rec:
        _ok("Recorder", rec)
    else:
        _miss("Recorder", "apt install pulseaudio-utils (for parecord)")

    stt = translator.detect_stt_backends()
    if stt:
        for b in stt:
            extra = f" model={b.model}" if getattr(b, "model", None) else ""
            _ok("STT backend", f"{b.name} (binary={b.binary}{extra})")
    else:
        _miss(
            "STT backend",
            "make streamdeck_translator_install_whisper",
        )

    out = translator.detect_output_methods()
    if out:
        _ok("Output", ", ".join(out))
    else:
        _miss(
            "Output",
            "apt install wl-clipboard ydotool (or xclip/xdotool on X11)",
        )

    llm = translator.detect_llm_backends()
    if llm:
        for b in llm:
            _ok("LLM backend", f"{b.name} (model={b.model})")
    else:
        _miss(
            "LLM backend",
            "make streamdeck_translator_install_ollama",
        )

    hw = translator.detect_hardware()
    gpu = hw["gpu_name"] or "no GPU"
    print(
        f"  i Hardware       {hw['ram_gb']} GB RAM, {gpu}, "
        f"{hw['gpu_vram_gb']} GB VRAM"
    )
    print(f"  i Recommended    {translator.recommend_model(hw)}")

    lang = translator.stt_language()
    print(f"  i STT language   {lang}")
    print(f"  i STT model size {translator.stt_model_size()}")

    overrides = translator._load_prompt_overrides()
    for mode in (translator.LLM_MODE_TRANSLATE, translator.LLM_MODE_CHAT):
        active = translator.get_prompt_template(mode)
        is_override = mode in overrides
        kind = "custom" if is_override else "default"
        snippet = active if len(active) <= 60 else active[:57] + "…"
        print(f"  i Prompt {mode:9s} ({kind}): {snippet}")

    summary = []
    if not stt:
        summary.append("install an STT backend")
    if not llm:
        summary.append("install an LLM backend (optional)")
    if not out:
        summary.append("install an output method")
    if summary:
        print("\nNext: " + "; ".join(summary) + ".")
    else:
        print("\nAll layers ready.")


if __name__ == "__main__":
    main()
