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
        # whisper.cpp ships various binary names depending on build.
        # Try PATH first, then well-known local install dirs so a build
        # at ~/.local/share/whisper.cpp works without symlinking onto PATH.
        candidates = []
        for cand in ("whisper-cli", "whisper-cpp", "main"):
            p = shutil.which(cand)
            if p:
                candidates.append(p)
        local_root = os.path.expanduser("~/.local/share/whisper.cpp")
        for rel in (
            "build/bin/whisper-cli",
            "main",
            "whisper-cli",
        ):
            cand = os.path.join(local_root, rel)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                candidates.append(cand)
        self.binary = candidates[0] if candidates else None
        self.available = bool(self.binary)
        # User must place a ggml model at one of these paths.
        # The configured size (translator_stt_model) is tried first, then
        # any other size gets picked up as a fallback.
        self.model = None
        size = stt_model_size()
        local_models = os.path.expanduser(
            "~/.local/share/whisper.cpp/models"
        )
        cache_models = os.path.expanduser("~/.cache/streamdeck-tiler")
        candidates = [
            os.path.join(local_models, f"ggml-{size}.bin"),
            os.path.join(cache_models, "whisper.bin"),
        ]
        for other in WHISPER_MODEL_SIZES:
            if other == size:
                continue
            candidates.append(os.path.join(local_models, f"ggml-{other}.bin"))
        for cand in candidates:
            if os.path.isfile(cand):
                self.model = cand
                break
        if not self.model:
            self.available = False

    def transcribe(self, wav_path):
        try:
            cmd = [
                self.binary,
                "-m", self.model,
                "-f", wav_path,
                "-nt", "-np",
                "--output-txt",
            ]
            lang = stt_language()
            if lang and lang != "auto":
                cmd.extend(["-l", lang])
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
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
            cmd = [
                self.binary, wav_path,
                "--model", stt_model_size(),
                "--output_format", "txt",
                "--output_dir", tmpdir,
                "--fp16", "False",
            ]
            lang = stt_language()
            if lang and lang != "auto":
                cmd.extend(["--language", lang])
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180,
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


# ---------- Hardware detection ----------

def detect_hardware():
    """Return {ram_gb, gpu_name, gpu_vram_gb} best-effort."""
    info = {"ram_gb": 0, "gpu_name": "", "gpu_vram_gb": 0}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    info["ram_gb"] = round(kb / (1024 * 1024))
                    break
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=2,
        )
        for line in r.stdout.splitlines():
            if any(t in line.lower() for t in ("vga", "3d controller")):
                info["gpu_name"] = line.split(":", 2)[-1].strip()
                break
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                mb = int(r.stdout.strip().splitlines()[0])
                info["gpu_vram_gb"] = round(mb / 1024)
        except Exception:
            pass
    return info


def recommend_model(hw):
    """Map hardware to an Ollama model tag."""
    ram = hw.get("ram_gb", 0)
    vram = hw.get("gpu_vram_gb", 0)
    if vram >= 16:
        return "llama3.1:8b-instruct-q5_K_M"
    if ram >= 32 or vram >= 8:
        return "llama3.1:8b-instruct-q4_K_M"
    if ram >= 16:
        return "llama3.2:3b-instruct"
    if ram >= 8:
        return "qwen2.5:1.5b-instruct"
    return "qwen2.5:0.5b-instruct"


# ---------- LLM backends ----------

class LLMBackend:
    name = "?"
    available = False
    model = ""

    def chat(self, prompt):
        return ""


class OllamaBackend(LLMBackend):
    name = "ollama"
    URL = "http://localhost:11434"

    def __init__(self):
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"{self.URL}/api/tags", timeout=1,
            ) as r:
                import json
                data = json.loads(r.read())
                self.available = True
                models = [m.get("name") for m in data.get("models", [])]
                self.model = models[0] if models else "llama3.2:3b"
        except Exception:
            self.available = False

    def chat(self, prompt):
        import urllib.request, json
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self.URL}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read()).get("response", "").strip()
        except Exception as e:
            print(f"ollama chat error: {e}")
            return ""


class LlamaCppBackend(LLMBackend):
    """Reaches a llama.cpp llama-server via the OpenAI-compatible API."""
    name = "llama.cpp"
    URL = "http://localhost:8080"

    def __init__(self):
        import urllib.request, json
        try:
            with urllib.request.urlopen(
                f"{self.URL}/v1/models", timeout=1,
            ) as r:
                data = json.loads(r.read())
                # llama-server / OpenAI compat returns {"data": [...]}
                self.available = isinstance(data.get("data"), list)
        except Exception:
            self.available = False
        self.model = "local"

    def chat(self, prompt):
        import urllib.request, json
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self.URL}/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                return (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
        except Exception as e:
            print(f"llama.cpp chat error: {e}")
            return ""


def detect_llm_backends():
    out = []
    for cls in (OllamaBackend, LlamaCppBackend):
        b = cls()
        if b.available:
            out.append(b)
    return out


# LLM modes for chaining after STT
LLM_MODE_OFF = "off"
LLM_MODE_TRANSLATE = "translate"
LLM_MODE_CHAT = "chat"
LLM_MODES = [LLM_MODE_OFF, LLM_MODE_TRANSLATE, LLM_MODE_CHAT]

# Default prompt templates. Each must contain {text}; the spoken text
# is substituted in. Override by setting `translator_prompts` in
# ~/.config/streamdeck-tiler/settings.json:
#   {"translator_prompts": {"translate": "Translate to French: {text}"}}
DEFAULT_PROMPTS = {
    LLM_MODE_TRANSLATE: (
        "Translate the following to English. Output only the "
        "translation, no commentary.\n\n{text}"
    ),
    LLM_MODE_CHAT: "{text}",
}


def _load_settings():
    import json
    settings_path = os.path.expanduser(
        "~/.config/streamdeck-tiler/settings.json"
    )
    try:
        with open(settings_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _load_prompt_overrides():
    custom = _load_settings().get("translator_prompts") or {}
    return {k: v for k, v in custom.items() if isinstance(v, str)}


def stt_language():
    """ISO 639-1 STT language hint, or 'auto' for whisper auto-detect."""
    raw = _load_settings().get("translator_stt_language") or "auto"
    return str(raw).strip().lower() or "auto"


WHISPER_MODEL_SIZES = ("tiny", "base", "small", "medium", "large")


def stt_model_size():
    """Whisper model size: tiny (default), base, small, medium, large."""
    raw = _load_settings().get("translator_stt_model") or "tiny"
    name = str(raw).strip().lower()
    return name if name in WHISPER_MODEL_SIZES else "tiny"


def get_prompt_template(llm_mode):
    """Return the active prompt template for a mode (override or default)."""
    overrides = _load_prompt_overrides()
    if llm_mode in overrides:
        return overrides[llm_mode]
    return DEFAULT_PROMPTS.get(llm_mode, "{text}")


def llm_postprocess(text, llm_mode, backend):
    """Run the LLM with a mode-specific prompt and return its text."""
    if not text or llm_mode == LLM_MODE_OFF or backend is None:
        return text
    if llm_mode not in DEFAULT_PROMPTS:
        return text
    template = get_prompt_template(llm_mode)
    if "{text}" in template:
        prompt = template.replace("{text}", text)
    else:
        prompt = f"{template}\n\n{text}"
    out = backend.chat(prompt)
    return out or text


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
