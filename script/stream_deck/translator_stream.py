#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Live streaming transcription via whisper.cpp's `stream` binary.

Spawns the stream binary, reads its stdout in real time, and pipes
each finalized line to the configured output method (TYPE / CLIP).
Press Ctrl+C or send SIGTERM to stop.

This is a CLI companion to the deck's MODE_TRANSLATOR; the deck still
records short clips end-to-end. Useful when you want a live caption
flow without holding the REC button.

Build the stream binary first:
    cd ~/.local/share/whisper.cpp && make stream
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import translator  # noqa: E402


_DEFAULT_STREAM_PATHS = [
    os.path.expanduser("~/.local/share/whisper.cpp/build/bin/whisper-stream"),
    os.path.expanduser("~/.local/share/whisper.cpp/stream"),
]


def _find_stream_binary():
    p = shutil.which("whisper-stream")
    if p:
        return p
    for cand in _DEFAULT_STREAM_PATHS:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _find_model(size):
    cand = os.path.expanduser(
        f"~/.local/share/whisper.cpp/models/ggml-{size}.bin"
    )
    return cand if os.path.isfile(cand) else None


# Lines from whisper.cpp/stream contain transcription text plus timestamps
# and noise like "### Transcription" or empty buffer markers. Filter to
# lines that look like transcribed speech (timestamp prefix + content).
_LINE_RE = re.compile(
    r"^\s*\[\s*\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\s*\]"
    r"\s*(.+?)\s*$"
)


def _is_transcription_line(line):
    return bool(_LINE_RE.match(line))


def _extract_text(line):
    m = _LINE_RE.match(line)
    return m.group(1) if m else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-size", default=None,
        help="Whisper model size (default: from settings.json).",
    )
    parser.add_argument(
        "--step", type=int, default=500,
        help="Audio step in ms (default 500).",
    )
    parser.add_argument(
        "--length", type=int, default=5000,
        help="Audio length per chunk in ms (default 5000).",
    )
    parser.add_argument(
        "--threads", type=int, default=4,
        help="CPU threads for whisper-stream (default 4).",
    )
    parser.add_argument(
        "--echo", action="store_true",
        help="Print transcribed text to stdout in addition to OUT method.",
    )
    args = parser.parse_args()

    binary = _find_stream_binary()
    if not binary:
        print(
            "whisper-stream not found. Build it with:\n"
            "  cd ~/.local/share/whisper.cpp && make stream",
            file=sys.stderr,
        )
        sys.exit(1)

    size = args.model_size or translator.stt_model_size()
    model = _find_model(size)
    if not model:
        print(
            f"ggml-{size}.bin not found under "
            "~/.local/share/whisper.cpp/models/. Run "
            f"WHISPER_MODEL={size} make streamdeck_translator_install_whisper",
            file=sys.stderr,
        )
        sys.exit(1)

    methods = (
        translator.detect_output_methods()
        or [translator.OUTPUT_CLIP]
    )
    method = methods[0]

    cmd = [
        binary,
        "-m", model,
        "-t", str(args.threads),
        "--step", str(args.step),
        "--length", str(args.length),
    ]
    lang = translator.stt_language()
    if lang and lang != "auto":
        cmd.extend(["-l", lang])

    print(
        f"Streaming via {binary} (model: {os.path.basename(model)}, "
        f"language: {lang}, output: {method}). Ctrl+C to stop."
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1,
        text=True,
    )

    def _stop(*_):
        try:
            proc.terminate()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not _is_transcription_line(line):
                continue
            text = _extract_text(line)
            if not text:
                continue
            if args.echo:
                print(text, flush=True)
            translator.output_text(text + " ", method)
    except KeyboardInterrupt:
        _stop()
    finally:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
