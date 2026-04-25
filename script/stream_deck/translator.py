#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Translator helpers — speech-to-text and text-to-output abstractions.

Phase 1: STT (mic recording -> text -> active window).
Phase 2 (planned): local LLM (llama.cpp / ollama) for translate / answer.
Phase 3 (planned): browser-based WebLLM in cache via gallery_server.

See tasks/translator-roadmap.md for the long form plan.
"""

import os
import shutil
import subprocess
import tempfile


# ---------- Audio capture ----------

def detect_recorder():
    """Pick a CLI recorder that produces a 16 kHz mono WAV. Returns name or ''.
    Order: parecord (PipeWire/Pulse), arecord (ALSA), ffmpeg fallback.
    """
    for name in ("parecord", "arecord", "ffmpeg"):
        if shutil.which(name):
            return name
    return ""


def start_recording(out_path, recorder=None):
    """Spawn an audio capture subprocess writing 16 kHz mono WAV.
    Returns the Popen handle or None on failure.
    """
    recorder = recorder or detect_recorder()
    if not recorder:
        return None
    if recorder == "parecord":
        cmd = [
            "parecord",
            "--format=s16le", "--rate=16000", "--channels=1",
            "--file-format=wav", out_path,
        ]
    elif recorder == "arecord":
        cmd = [
            "arecord", "-f", "S16_LE", "-r", "16000", "-c", "1",
            "-t", "wav", out_path,
        ]
    elif recorder == "ffmpeg":
        cmd = [
            "ffmpeg", "-y", "-f", "pulse", "-i", "default",
            "-ar", "16000", "-ac", "1", "-loglevel", "error",
            out_path,
        ]
    else:
        return None
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"start_recording failed: {e}")
        return None


def stop_recording(proc, timeout=3):
    """Stop a recording subprocess cleanly."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------- STT backends ----------

class STTBackend:
    name = "?"
    available = False
    binary = None

    def transcribe(self, wav_path):
        """Return transcribed text, or '' on failure."""
        return ""


class WhisperCppBackend(STTBackend):
    name = "whisper.cpp"

    def __init__(self):
        # whisper.cpp ships various binary names depending on build
        for cand in ("whisper-cli", "whisper-cpp", "main"):
            p = shutil.which(cand)
            if p:
                self.binary = p
                break
        self.available = bool(self.binary)
        # User must place a ggml model at one of these paths
        self.model = None
        for cand in (
            os.path.expanduser("~/.cache/streamdeck-tiler/whisper.bin"),
            os.path.expanduser("~/.local/share/whisper.cpp/models/ggml-tiny.bin"),
            os.path.expanduser("~/.local/share/whisper.cpp/models/ggml-base.bin"),
        ):
            if os.path.isfile(cand):
                self.model = cand
                break
        if not self.model:
            self.available = False

    def transcribe(self, wav_path):
        try:
            r = subprocess.run(
                [
                    self.binary,
                    "-m", self.model,
                    "-f", wav_path,
                    "-nt", "-np",
                    "--output-txt",
                ],
                capture_output=True, text=True, timeout=120,
            )
            # whisper.cpp writes to <wav>.txt with --output-txt
            txt_path = wav_path + ".txt"
            if os.path.isfile(txt_path):
                with open(txt_path, encoding="utf-8") as f:
                    return f.read().strip()
            return r.stdout.strip()
        except Exception as e:
            print(f"whisper.cpp transcribe error: {e}")
            return ""


class OpenAIWhisperBackend(STTBackend):
    name = "openai-whisper"

    def __init__(self):
        self.binary = shutil.which("whisper")
        self.available = bool(self.binary)

    def transcribe(self, wav_path):
        try:
            tmpdir = tempfile.mkdtemp(prefix="sttout_")
            r = subprocess.run(
                [
                    self.binary, wav_path,
                    "--model", "tiny",
                    "--output_format", "txt",
                    "--output_dir", tmpdir,
                    "--fp16", "False",
                ],
                capture_output=True, text=True, timeout=180,
            )
            base = os.path.splitext(os.path.basename(wav_path))[0]
            out_path = os.path.join(tmpdir, base + ".txt")
            if os.path.isfile(out_path):
                with open(out_path, encoding="utf-8") as f:
                    return f.read().strip()
            return r.stdout.strip()
        except Exception as e:
            print(f"openai-whisper transcribe error: {e}")
            return ""


class VoskBackend(STTBackend):
    name = "vosk"

    def __init__(self):
        try:
            import vosk  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False
        self.model_path = os.path.expanduser(
            "~/.cache/streamdeck-tiler/vosk-model"
        )
        if not os.path.isdir(self.model_path):
            self.available = False

    def transcribe(self, wav_path):
        try:
            import json
            import wave
            from vosk import Model, KaldiRecognizer
            wf = wave.open(wav_path, "rb")
            rec = KaldiRecognizer(Model(self.model_path), wf.getframerate())
            chunks = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    chunks.append(json.loads(rec.Result()).get("text", ""))
            chunks.append(json.loads(rec.FinalResult()).get("text", ""))
            return " ".join(c for c in chunks if c).strip()
        except Exception as e:
            print(f"vosk transcribe error: {e}")
            return ""


def detect_stt_backends():
    """Return list of available STT backends."""
    out = []
    for cls in (WhisperCppBackend, OpenAIWhisperBackend, VoskBackend):
        b = cls()
        if b.available:
            out.append(b)
    return out


# ---------- Output (typing into focused window or clipboard) ----------

OUTPUT_TYPE = "type"
OUTPUT_CLIP = "clip"


def detect_output_methods():
    """Methods available, in preference order."""
    methods = []
    if shutil.which("ydotool"):
        methods.append(OUTPUT_TYPE)  # Wayland keystroke injection
    elif shutil.which("xdotool"):
        methods.append(OUTPUT_TYPE)
    if shutil.which("wl-copy") or shutil.which("xclip"):
        methods.append(OUTPUT_CLIP)
    return methods


def _typer_command(text):
    if shutil.which("ydotool"):
        return ["ydotool", "type", "--", text]
    if shutil.which("xdotool"):
        return ["xdotool", "type", "--", text]
    return None


def _clipboard_command():
    if shutil.which("wl-copy"):
        return ["wl-copy"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard"]
    return None


def output_text(text, method):
    """Send text to the focused window or clipboard. Returns True on success."""
    if not text:
        return False
    if method == OUTPUT_TYPE:
        cmd = _typer_command(text)
        if not cmd:
            return False
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception as e:
            print(f"type output error: {e}")
            return False
    if method == OUTPUT_CLIP:
        cmd = _clipboard_command()
        if not cmd:
            return False
        try:
            r = subprocess.run(
                cmd, input=text, text=True, capture_output=True, timeout=5,
            )
            return r.returncode == 0
        except Exception as e:
            print(f"clipboard output error: {e}")
            return False
    return False
