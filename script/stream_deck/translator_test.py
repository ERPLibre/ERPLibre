#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""End-to-end smoke test for the translator stack.

Records a short clip, then transcribes it through every detected STT
backend so the user can compare quality and timing on their own voice
without launching the deck. Useful right after `make
streamdeck_translator_install_*` to confirm the stack actually works.
"""

import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import translator  # noqa: E402


def record(seconds, recorder):
    fd, path = tempfile.mkstemp(prefix="ttest_", suffix=".wav")
    os.close(fd)
    proc = translator.start_recording(path, recorder=recorder)
    if proc is None:
        os.unlink(path)
        return None
    print(f"Recording for {seconds}s — speak now...")
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        print("Interrupted.")
    translator.stop_recording(proc)
    print("Recording stopped.\n")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seconds", type=int, default=5,
        help="Recording duration in seconds (default 5).",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep the WAV file after the test (printed path).",
    )
    args = parser.parse_args()

    recorder = translator.detect_recorder()
    if not recorder:
        print("No audio recorder available (parecord/arecord/ffmpeg).")
        sys.exit(1)

    backends = translator.detect_stt_backends()
    if not backends:
        print(
            "No STT backend available. "
            "Run: make streamdeck_translator_install_whisper"
        )
        sys.exit(1)

    print(f"Recorder:        {recorder}")
    print(f"STT backends:    {[b.name for b in backends]}")
    print(f"STT language:    {translator.stt_language()}")
    print(f"STT model size:  {translator.stt_model_size()}")
    print()

    wav_path = record(args.seconds, recorder)
    if not wav_path:
        print("Recording failed.")
        sys.exit(1)

    try:
        for backend in backends:
            print(f"--- {backend.name} ---")
            t0 = time.monotonic()
            text = backend.transcribe(wav_path)
            dt = time.monotonic() - t0
            print(f"  time : {dt:.2f}s")
            print(f"  text : {text or '(empty)'}")
            print()
    finally:
        if args.keep:
            print(f"WAV kept at: {wav_path}")
        else:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
