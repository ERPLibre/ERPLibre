# Stream Deck Translator — Roadmap

## Phase 1 — Speech-to-text (delivered)

`MODE_TRANSLATOR` exposes:

- **REC / STOP**: toggle recording. `parecord` / `arecord` / `ffmpeg`
  records 16 kHz mono WAV.
- **STT backend cycle**: select between detected backends. Persisted in
  `~/.config/streamdeck-tiler/settings.json` key `translator_stt`.
- **OUT method cycle**: TYPE (ydotool / xdotool injects keystrokes into
  focused window) or CLIP (wl-copy / xclip puts text on the clipboard
  for manual paste). Persisted as `translator_output`.

### Backend detection

| Backend | Binary / Pkg | Model location |
|---------|--------------|----------------|
| whisper.cpp | `whisper-cli`, `whisper-cpp`, or `main` | `~/.cache/streamdeck-tiler/whisper.bin` or `~/.local/share/whisper.cpp/models/ggml-{tiny,base}.bin` |
| openai-whisper | `whisper` (PyPI) | downloaded by `whisper` itself |
| vosk | Python `vosk` | `~/.cache/streamdeck-tiler/vosk-model/` |

If no backend has both binary + model, REC press flashes ERR.

### Wayland typing limit

GNOME 48 Wayland needs `ydotool` with the daemon running and the user in
the `input` group (or a uinput rule). Without it, only the CLIP method
works — the user pastes manually.

### Install hints (manual for now)

```bash
# whisper.cpp + tiny model (offline, ~75 MB)
git clone https://github.com/ggerganov/whisper.cpp ~/.local/share/whisper.cpp
cd ~/.local/share/whisper.cpp && make
bash models/download-ggml-model.sh tiny

# Audio + clipboard tools
sudo apt install pulseaudio-utils wl-clipboard

# Optional: keystroke injection on Wayland
sudo apt install ydotool
sudo systemctl enable --now ydotoold
```

## Phase 2 — Local LLM (delivered)

Use the captured text or a typed prompt as input to a local model and
write the result back via the same output method.

### Hardware detection

```
ram_gb = $(free -g | awk '/^Mem:/ {print $2}')
gpu = $(lspci | grep -iE 'vga|3d' | head -1)
```

Pick model size:

| RAM     | Model |
|---------|-------|
| < 8 GB  | qwen2.5:1.5b or llama3.2:1b |
| 8–16 GB | llama3.2:3b or phi3.5:3.8b |
| 16–32 GB| llama3.1:8b-q4 |
| > 32 GB | mistral:7b-instruct-q5 |

GPU > 8 GB VRAM allows q4_K_M variants.

### Backend choices

- `ollama` — daemon + REST on `http://localhost:11434`. Detected via
  `GET /api/tags`. First model in the list is used by default.
- `llama-server` (`llama.cpp`) — REST on `http://localhost:8080`.
  Detected via `GET /v1/models` returning a `{"data": [...]}` shape.

In MODE_TRANSLATOR the `LLM` button cycles `OFF / TRSL / CHAT`:

- `OFF` — STT output goes straight to the focused window / clipboard.
- `TRSL` — wraps the STT text with `Translate the following to English`
  and outputs the LLM response.
- `CHAT` — sends the STT text as a raw prompt to the LLM.

The neighboring `LLM\n<name>` button cycles between detected backends.
Both selections persist as `translator_llm` and `translator_llm_mode`
in `settings.json`.

### Parallel download

```
aria2c -x 8 -s 8 https://...gguf
```

`aria2c` does multi-connection by default. Add a `make` target that
resolves model URL by hardware tier and pulls it.

## Phase 3 — Browser WebLLM (deferred — not recommended)

Reasoning: in-browser WebLLM via WebGPU runs slower than native, but
lets the LLM be cached in IndexedDB and reused across machines without
installing native deps.

`gallery_server.py` would expose a new route `/llm` that serves a
static page bundled with `@mlc-ai/web-llm`. The page caches model
weights in IndexedDB on first visit. The Stream Deck button opens the
page in the user's browser and POSTs prompts via fetch.

Trade-offs vs Phase 2:

- (+) Zero native install; weights survive in browser cache.
- (-) WebGPU support patchy; performance 5–20× slower than `llama.cpp`.
- (-) Coordination shell ↔ browser through the gallery_server is
  fragile.

Recommend: ship Phase 2 first; add Phase 3 only if a use case emerges
(e.g. running on a borrowed machine with no install permissions).

Decision 2026-04-25: Phase 3 deferred. Phase 2 (`ollama` /
`llama-server`) covers the same use case with much better performance
and without bridging shell ↔ browser. Re-open if a no-install
deployment scenario appears.

## Security considerations

- TYPE method writes text into the focused window. A malicious mic
  source (e.g. computer speaker bleed) could inject keystrokes.
  Mitigation: prefer CLIP when source is uncertain.
- LLM output is untrusted. Prompt injection in the audio could craft
  text that the typer pastes into a sudo prompt or a chat. Recommend a
  confirmation step before TYPE for LLM responses.
- Audio recordings stay in `/tmp` until transcription completes, then
  unlink. No on-disk retention.
