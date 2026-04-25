
# Stream Deck Translator — Speech-to-Text + Local LLM

A Stream Deck mode that records audio, transcribes it via a local
speech-to-text engine, optionally post-processes the result with a
local LLM, and writes the final text into the focused window or onto
the clipboard.

Activate from the idle menu via the **TRANSL** button (icon: speech
bubble with three dots).

## Architecture

| File | Role |
|------|------|
| `script/stream_deck/translator.py` | Audio recording, STT backends, LLM backends, hardware detection, output methods. |
| `script/stream_deck/game_tiler.py` | UI: `MODE_TRANSLATOR` rendering, key handling, settings persistence. |
| `~/.config/streamdeck-tiler/settings.json` | Persisted picks: `translator_stt`, `translator_output`, `translator_llm`, `translator_llm_mode`. |
| `tasks/translator-roadmap.md` | Phase planning and security notes. |

The Stream Deck process orchestrates everything. There is **no** GNOME
extension dependency for the translator — the existing
`streamdeck-tiler@technolibre.ca` extension is unrelated.

## TRANSLATOR mode layout

On an 8×4 deck, row 1 of the mode looks like:

```
BACK   .   REC   STT   OUT   LLM   LLMBE   .
```

| Key | Function |
|-----|----------|
| BACK (key 0) | Back to idle. Stops a recording in progress. |
| REC (key cols+1) | Start / stop recording. Red while recording, gray when idle. Icon: `mic_on` while recording, `mic_off` when idle. |
| STT (key cols+2) | Cycle the active speech-to-text backend. Label is the backend name (`whisper.cpp`, `openai-whisper`, `vosk`). |
| OUT (key cols+3) | Cycle the output method (`TYPE` or `CLIP`). |
| LLM (key cols+4, ≥6 cols) | Cycle the LLM post-processing mode: `OFF`, `TRSL`, `CHAT`. |
| LLMBE (key cols+5, ≥6 cols) | Cycle the LLM backend (`ollama`, `llama.cpp`). |

Decks with fewer than 6 columns hide the LLM controls. Decks with
fewer than 4 columns or fewer than 2 rows show
`DECK\nTOO\nSMALL`.

## Phase 1 — Speech to text

### Audio capture

`translator.detect_recorder()` picks the first available of:

1. `parecord` (PipeWire / PulseAudio) — preferred.
2. `arecord` (ALSA).
3. `ffmpeg` (PulseAudio source).

Recording produces a 16 kHz mono WAV file in `/tmp/sttrec_*`. The file
is unlinked after transcription.

### STT language

Whisper auto-detects the spoken language but is biased toward English.
Force a specific language via its ISO 639-1 code in
`~/.config/streamdeck-tiler/settings.json`:

```json
{
  "translator_stt_language": "fr"
}
```

Value `"auto"` (default) or absent = auto-detect. The setting is
applied through `-l` for whisper.cpp and `--language` for
openai-whisper. Vosk ignores it because language is baked into the
installed model.

### History

After every successful transcription the deck appends an entry to a
ring buffer kept in `~/.config/streamdeck-tiler/translator-history.json`
(20 most recent kept). In `MODE_TRANSLATOR`, press the **HIST** button
(8-col deck only) to enter history mode: each remaining key shows a
truncated snippet of a saved entry; press to re-output it via the
current OUT method. Top-right key = `CLEAR` (deletes the file, no
confirm). Entry payload: `text`, `ts` (unix seconds), `llm_mode`,
`language`, `wm_class`.

### Recording auto-stop

Forgetting to press STOP leaves a recording running until the next
press. Set `translator_recording_timeout` to a positive integer in
`~/.config/streamdeck-tiler/settings.json`:

```json
{
  "translator_recording_timeout": 60
}
```

The deck cancels the recording (and triggers transcription) once the
elapsed time exceeds the value in seconds. `0` or absent = no limit.
A real silence-based VAD is on the roadmap; this is the safety net.

### STT model size

Whisper ships several model sizes trading accuracy for speed and
memory. The default is `tiny` (~75 MB, fastest, lowest accuracy).
Override per session in the same settings file:

```json
{
  "translator_stt_model": "base"
}
```

Accepted: `tiny`, `base`, `small`, `medium`, `large`. Whisper.cpp
looks for the matching `ggml-<size>.bin` under
`~/.local/share/whisper.cpp/models/`; openai-whisper passes the size
through `--model`. Pull the ggml file once with the make target:

```bash
WHISPER_MODEL=base make streamdeck_translator_install_whisper
```

### STT backends

`translator.detect_stt_backends()` returns the available backends in a
fixed order. A backend is "available" only if both the binary/package
and the model files exist.

| Backend | Binary / package | Model paths checked |
|---------|------------------|---------------------|
| `whisper.cpp` | `whisper-cli`, `whisper-cpp`, or `main` (also probes `~/.local/share/whisper.cpp/`) | `~/.cache/streamdeck-tiler/whisper.bin`, `~/.local/share/whisper.cpp/models/ggml-tiny.bin`, `~/.local/share/whisper.cpp/models/ggml-base.bin` |
| `openai-whisper` | `whisper` | downloaded automatically by `openai-whisper` |
| `vosk` | Python `vosk` | `~/.cache/streamdeck-tiler/vosk-model/` |

Audit and install via make targets:

```bash
make streamdeck_translator_doctor             # see what is missing
make streamdeck_translator_install_whisper    # clone + build + tiny model
make streamdeck_translator_install_ollama     # ollama + hardware-recommended model
make streamdeck_translator_install_typing     # wl-clipboard + ydotool + input group
make streamdeck_translator_install_vosk_fr    # vosk + French model
make streamdeck_translator_test               # 5s recording + every STT backend
make streamdeck_translator_unittest            # pure unit tests (no audio / network)
```

`streamdeck_translator_test` records a short clip and runs the active
STT backends against it in turn so you can compare quality and timing
on your own voice before driving the deck. Add `-- --seconds 10` to
record longer or `-- --keep` to preserve the WAV file.

Manual install hints (alternative):

```bash
# whisper.cpp + tiny model (~75 MB, offline)
git clone https://github.com/ggerganov/whisper.cpp ~/.local/share/whisper.cpp
make -C ~/.local/share/whisper.cpp
bash ~/.local/share/whisper.cpp/models/download-ggml-model.sh tiny

# openai-whisper (PyTorch, ~2 GB extra)
pip install openai-whisper

# vosk (smaller model, language-specific)
pip install vosk
mkdir -p ~/.cache/streamdeck-tiler
curl -L https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip \
  -o /tmp/vosk.zip
unzip /tmp/vosk.zip -d ~/.cache/streamdeck-tiler/
mv ~/.cache/streamdeck-tiler/vosk-model-small-* \
   ~/.cache/streamdeck-tiler/vosk-model
```

### Output methods

`translator.detect_output_methods()` returns the supported outputs:

- `TYPE` — keystroke injection into the focused window:
  - `ydotool type` (Wayland, requires uinput access).
  - `xdotool type` (X11 fallback).
- `CLIP` — clipboard:
  - `wl-copy` (Wayland, from `wl-clipboard`).
  - `xclip -selection clipboard` (X11).

On GNOME 48 Wayland, `TYPE` requires:

```bash
sudo apt install ydotool wl-clipboard
sudo systemctl enable --now ydotoold
sudo usermod -aG input "$USER"
# Re-login for the group change to take effect.
```

If neither method is detected at startup, the UI falls back to `CLIP`
and copy operations are no-ops until a tool is installed.

## Phase 2 — Local LLM post-processing

### Hardware detection

`translator.detect_hardware()` reads:

- RAM from `/proc/meminfo`.
- GPU name from `lspci`.
- VRAM from `nvidia-smi` (skipped on AMD/Intel for now).

`translator.recommend_model(hw)` maps the result to an Ollama tag:

| Tier | Condition | Suggested model |
|------|-----------|-----------------|
| XL | `vram_gb >= 16` | `llama3.1:8b-instruct-q5_K_M` |
| L | `ram_gb >= 32` or `vram_gb >= 8` | `llama3.1:8b-instruct-q4_K_M` |
| M | `ram_gb >= 16` | `llama3.2:3b-instruct` |
| S | `ram_gb >= 8` | `qwen2.5:1.5b-instruct` |
| XS | otherwise | `qwen2.5:0.5b-instruct` |

The current machine reads as `15 GB RAM, Intel Iris Xe, 0 VRAM` and
the recommender returns `qwen2.5:1.5b-instruct` — a sensible offline
default.

### LLM backends

| Backend | Endpoint | Detection probe |
|---------|----------|-----------------|
| `ollama` | `http://localhost:11434/api/generate` | `GET /api/tags` returns 200. First model in `models[]` is used by default. |
| `llama.cpp` | `http://localhost:8080/v1/chat/completions` (OpenAI-compatible) | `GET /v1/models` returns a valid `{"data": [...]}` body. |

The `llama.cpp` probe asserts on the response shape, not just HTTP 200,
to avoid false positives when a different web service happens to be
listening on `:8080`.

`OllamaBackend` lists every model returned by `/api/tags` and stores
them as `installed_models`. By default it picks the first one. Pin a
specific model with `translator_llm_model` in settings.json:

```json
{
  "translator_llm_model": "llama3.2:3b-instruct"
}
```

If the pinned tag is not pulled, the backend falls back to the first
available model; the doctor reports the active and pinned values for
visibility.

Install hints:

```bash
# ollama (recommended, simplest)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct      # follow recommend_model()

# llama.cpp (manual control)
git clone https://github.com/ggerganov/llama.cpp
make -C llama.cpp llama-server
~/llama.cpp/llama-server -m /path/to/model.gguf --port 8080
```

### LLM modes

The `LLM` button cycles through three modes:

| Mode | What it does |
|------|--------------|
| `OFF` | STT text is sent straight to the output method. |
| `TRSL` | STT text is wrapped in the `translate` prompt template and the LLM response is output. |
| `CHAT` | STT text is wrapped in the `chat` prompt template and the response is output. |

The default templates are computed at call time so a `LANG=fr_*`
session gets a "Translate to French" prompt without any settings
edit. The supported locale targets are French, Spanish, German,
Italian, Portuguese — anything else falls back to English. Override
them per mode in `~/.config/streamdeck-tiler/settings.json`:

```json
{
  "translator_prompts": {
    "translate": "Translate to French. Output only the French translation:\n\n{text}",
    "chat": "You are a concise assistant. {text}"
  }
}
```

The `{text}` placeholder is substituted with the STT result. If
`{text}` is absent the STT result is appended after a blank line.

#### Per-app prompt presets

Layer per-application prompts on top of the global override. The
extension exposes `GetFocusedWindowClass` and the translator looks
up the bucket matching the active window's wm_class:

```json
{
  "translator_prompts_per_app": {
    "Slack": {
      "translate": "Translate to English, keep it casual:\n\n{text}",
      "chat": "Reply in one short sentence: {text}"
    },
    "Code": {
      "chat": "Format as a code comment, no prose:\n\n{text}"
    }
  }
}
```

Resolution order: per-app preset → global `translator_prompts` → locale
default. Run `gnome-extensions list` to see your wm_class candidates,
or check `gdbus call ...GetFocusedWindowClass` directly. Reload the
extension once after upgrading so `GetFocusedWindowClass` is
registered (DEV RELOAD on the deck or re-login).

If the LLM call fails, the original STT text is used as a fallback so
no audio capture is lost.

## Settings persistence

`~/.config/streamdeck-tiler/settings.json` (created on first save):

```json
{
  "font_scale": 1.0,
  "show_labels": false,
  "translator_stt": "whisper.cpp",
  "translator_output": "type",
  "translator_llm": "ollama",
  "translator_llm_mode": "off"
}
```

All keys are optional. Missing keys fall back to the first detected
backend / method and to `LLM_MODE_OFF`.

## End-to-end flow

1. User presses TRANSL on the idle screen → `MODE_TRANSLATOR`.
2. User picks a backend / output / LLM mode.
3. User presses REC. `translator.start_recording()` spawns the
   recorder; the button turns red and the icon switches to `mic_on`.
4. User speaks.
5. User presses REC again. `translator.stop_recording()` terminates
   the recorder. A daemon thread runs `_finish_transcription()`:
   1. Selected STT backend transcribes the WAV.
   2. If `LLM` mode is not `OFF`, `llm_postprocess()` runs.
   3. `output_text()` injects keystrokes (`TYPE`) or copies to
      clipboard (`CLIP`).
   4. The WAV file is unlinked.
6. The deck flashes `OK!` (green) or `ERR` (red) for 1.5 s.

The STT and LLM calls happen on a worker thread so the deck stays
responsive — the user can press BACK to leave the mode without losing
the in-flight transcription (the thread finishes silently).

## Security notes

- The `TYPE` output writes whatever the LLM returns into the focused
  window. A maliciously crafted audio clip combined with a permissive
  prompt template could inject keystrokes. Prefer `CLIP` when the
  audio source is uncertain (e.g. in a meeting where someone else may
  speak commands at your microphone).
- Audio recordings are written to `/tmp` and removed after transcription;
  no audio is retained on disk.
- The LLM call is HTTP to `localhost`. The script never reaches an
  external API. If you replace `OllamaBackend.URL` with a remote host,
  audio-derived text leaves the machine — make that change deliberate.

## Future work

- A make target that installs `whisper.cpp` + tiny model in one
  command.
- Hardware-aware model auto-pull at first run (`recommend_model`
  + `ollama pull`).
- Streaming transcription (live caption) once whisper.cpp's stream
  binary is wrapped — currently a chunked recording would only show
  results after STOP.
- Configurable LLM prompt templates per mode (currently hard-coded in
  `translator.llm_postprocess`).

See `tasks/translator-roadmap.md` for the full phase plan and the
deferred Phase 3 (browser WebLLM) discussion.
