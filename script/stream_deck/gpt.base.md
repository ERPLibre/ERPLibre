<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [fr] -->
# Stream Deck Translator — Speech-to-Text + LLM local

Un mode Stream Deck qui enregistre l'audio, le transcrit via un moteur
de reconnaissance vocale local, post-traite optionnellement le
résultat avec un LLM local, et écrit le texte final dans la fenêtre
active ou dans le presse-papiers.

Activer depuis le menu d'accueil via le bouton **TRANSL** (icône:
bulle de dialogue avec trois points).

## Architecture

| Fichier | Rôle |
|---------|------|
| `script/stream_deck/translator.py` | Enregistrement audio, backends STT, backends LLM, détection matériel, méthodes de sortie. |
| `script/stream_deck/game_tiler.py` | UI: rendu `MODE_TRANSLATOR`, gestion des touches, persistance des réglages. |
| `~/.config/streamdeck-tiler/settings.json` | Choix persistés: `translator_stt`, `translator_output`, `translator_llm`, `translator_llm_mode`. |
| `tasks/translator-roadmap.md` | Plan des phases et notes de sécurité. |

Le processus Stream Deck orchestre tout. Il n'y a **aucune** dépendance
à l'extension GNOME pour le translator — l'extension existante
`streamdeck-tiler@technolibre.ca` n'est pas concernée.

## Disposition du mode TRANSLATOR

Sur un deck 8×4, la rangée 1 du mode ressemble à:

<!-- [common] -->
```
BACK   .   REC   STT   OUT   LLM   LLMBE   .
```

<!-- [en] -->
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
```

`streamdeck_translator_test` records a short clip and runs the active
STT backends against it in turn so you can compare quality and timing
on your own voice before driving the deck. Add `-- --seconds 10` to
record longer or `-- --keep` to preserve the WAV file.

Manual install hints (alternative):

<!-- [fr] -->
| Touche | Fonction |
|--------|----------|
| BACK (touche 0) | Retour à l'accueil. Arrête un enregistrement en cours. |
| REC (touche cols+1) | Démarrer / arrêter l'enregistrement. Rouge pendant l'enregistrement, gris au repos. Icône: `mic_on` pendant l'enregistrement, `mic_off` au repos. |
| STT (touche cols+2) | Faire défiler le backend de reconnaissance vocale actif. Le label est le nom du backend (`whisper.cpp`, `openai-whisper`, `vosk`). |
| OUT (touche cols+3) | Faire défiler la méthode de sortie (`TYPE` ou `CLIP`). |
| LLM (touche cols+4, ≥6 cols) | Faire défiler le mode de post-traitement LLM: `OFF`, `TRSL`, `CHAT`. |
| LLMBE (touche cols+5, ≥6 cols) | Faire défiler le backend LLM (`ollama`, `llama.cpp`). |

Les decks avec moins de 6 colonnes cachent les contrôles LLM. Les
decks avec moins de 4 colonnes ou moins de 2 rangées affichent
`DECK\nTOO\nSMALL`.

## Phase 1 — Reconnaissance vocale

### Capture audio

`translator.detect_recorder()` choisit le premier disponible parmi:

1. `parecord` (PipeWire / PulseAudio) — préféré.
2. `arecord` (ALSA).
3. `ffmpeg` (source PulseAudio).

L'enregistrement produit un fichier WAV mono 16 kHz dans
`/tmp/sttrec_*`. Le fichier est supprimé après la transcription.

### Langue STT

Whisper auto-détecte la langue mais a un biais anglais. Forcer une
langue par ISO 639-1 dans `~/.config/streamdeck-tiler/settings.json`:

```json
{
  "translator_stt_language": "fr"
}
```

Valeur `"auto"` (défaut) ou absente = auto-détection. Le réglage est
appliqué via `-l` (whisper.cpp) ou `--language` (openai-whisper). Vosk
ignore ce réglage car la langue dépend du modèle installé.

### Taille de modèle STT

Whisper offre plusieurs tailles de modèle (compromis précision /
vitesse / mémoire). Défaut: `tiny` (~75 Mo, le plus rapide, moins
précis). Surcharger dans le même fichier de réglages:

```json
{
  "translator_stt_model": "base"
}
```

Valeurs acceptées: `tiny`, `base`, `small`, `medium`, `large`.
whisper.cpp cherche `ggml-<taille>.bin` sous
`~/.local/share/whisper.cpp/models/`; openai-whisper passe la taille
via `--model`. Télécharger le fichier ggml une fois avec la cible
make:

```bash
WHISPER_MODEL=base make streamdeck_translator_install_whisper
```

### Backends STT

`translator.detect_stt_backends()` retourne les backends disponibles
dans un ordre fixe. Un backend est « disponible » seulement si le
binaire/paquet **et** les fichiers de modèle existent.

| Backend | Binaire / paquet | Chemins de modèle vérifiés |
|---------|------------------|----------------------------|
| `whisper.cpp` | `whisper-cli`, `whisper-cpp`, ou `main` (vérifie aussi `~/.local/share/whisper.cpp/`) | `~/.cache/streamdeck-tiler/whisper.bin`, `~/.local/share/whisper.cpp/models/ggml-tiny.bin`, `~/.local/share/whisper.cpp/models/ggml-base.bin` |
| `openai-whisper` | `whisper` | téléchargé automatiquement par `openai-whisper` |
| `vosk` | Python `vosk` | `~/.cache/streamdeck-tiler/vosk-model/` |

Audit et install via cibles make:

```bash
make streamdeck_translator_doctor             # voir ce qui manque
make streamdeck_translator_install_whisper    # clone + build + modèle tiny
make streamdeck_translator_install_ollama     # ollama + modèle recommandé selon matériel
make streamdeck_translator_install_typing     # wl-clipboard + ydotool + groupe input
make streamdeck_translator_install_vosk_fr    # vosk + modèle français
make streamdeck_translator_test               # enregistrement 5s + chaque backend STT
```

`streamdeck_translator_test` enregistre un court clip et exécute les
backends STT actifs successivement pour que tu puisses comparer la
qualité et le timing sur ta propre voix avant de piloter le deck.
Ajoute `-- --seconds 10` pour enregistrer plus longtemps ou
`-- --keep` pour conserver le WAV.

Pistes d'installation manuelle (alternative):

<!-- [common] -->
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

<!-- [en] -->
### Output methods

`translator.detect_output_methods()` returns the supported outputs:

- `TYPE` — keystroke injection into the focused window:
  - `ydotool type` (Wayland, requires uinput access).
  - `xdotool type` (X11 fallback).
- `CLIP` — clipboard:
  - `wl-copy` (Wayland, from `wl-clipboard`).
  - `xclip -selection clipboard` (X11).

On GNOME 48 Wayland, `TYPE` requires:

<!-- [fr] -->
### Méthodes de sortie

`translator.detect_output_methods()` retourne les sorties supportées:

- `TYPE` — injection de touches dans la fenêtre active:
  - `ydotool type` (Wayland, demande accès uinput).
  - `xdotool type` (fallback X11).
- `CLIP` — presse-papiers:
  - `wl-copy` (Wayland, depuis `wl-clipboard`).
  - `xclip -selection clipboard` (X11).

Sur GNOME 48 Wayland, `TYPE` requiert:

<!-- [common] -->
```bash
sudo apt install ydotool wl-clipboard
sudo systemctl enable --now ydotoold
sudo usermod -aG input "$USER"
# Re-login for the group change to take effect.
```

<!-- [en] -->
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

<!-- [fr] -->
Si aucune méthode n'est détectée au démarrage, l'UI retombe sur
`CLIP` et les opérations de copie ne font rien tant qu'un outil n'est
pas installé.

## Phase 2 — Post-traitement LLM local

### Détection matérielle

`translator.detect_hardware()` lit:

- RAM depuis `/proc/meminfo`.
- Nom du GPU depuis `lspci`.
- VRAM depuis `nvidia-smi` (sauté sur AMD/Intel pour l'instant).

`translator.recommend_model(hw)` mappe le résultat vers un tag Ollama:

| Niveau | Condition | Modèle suggéré |
|--------|-----------|----------------|
| XL | `vram_gb >= 16` | `llama3.1:8b-instruct-q5_K_M` |
| L | `ram_gb >= 32` ou `vram_gb >= 8` | `llama3.1:8b-instruct-q4_K_M` |
| M | `ram_gb >= 16` | `llama3.2:3b-instruct` |
| S | `ram_gb >= 8` | `qwen2.5:1.5b-instruct` |
| XS | sinon | `qwen2.5:0.5b-instruct` |

La machine actuelle se lit comme `15 GB RAM, Intel Iris Xe, 0 VRAM`
et le recommandeur retourne `qwen2.5:1.5b-instruct` — un défaut
offline raisonnable.

### Backends LLM

| Backend | Endpoint | Sonde de détection |
|---------|----------|--------------------|
| `ollama` | `http://localhost:11434/api/generate` | `GET /api/tags` retourne 200. Le premier modèle dans `models[]` est utilisé par défaut. |
| `llama.cpp` | `http://localhost:8080/v1/chat/completions` (compatible OpenAI) | `GET /v1/models` retourne un corps `{"data": [...]}` valide. |

La sonde `llama.cpp` valide la forme de la réponse, pas seulement
HTTP 200, pour éviter les faux positifs quand un autre service web
écoute sur `:8080`.

`OllamaBackend` liste tous les modèles retournés par `/api/tags` et
les stocke dans `installed_models`. Par défaut il prend le premier.
Épingler un modèle spécifique via `translator_llm_model` dans
settings.json:

```json
{
  "translator_llm_model": "llama3.2:3b-instruct"
}
```

Si le tag épinglé n'est pas téléchargé, le backend retombe sur le
premier modèle disponible; le doctor affiche les valeurs active et
préférée pour la visibilité.

Pistes d'installation:

<!-- [common] -->
```bash
# ollama (recommended, simplest)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct      # follow recommend_model()

# llama.cpp (manual control)
git clone https://github.com/ggerganov/llama.cpp
make -C llama.cpp llama-server
~/llama.cpp/llama-server -m /path/to/model.gguf --port 8080
```

<!-- [en] -->
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

If the LLM call fails, the original STT text is used as a fallback so
no audio capture is lost.

## Settings persistence

`~/.config/streamdeck-tiler/settings.json` (created on first save):

<!-- [fr] -->
### Modes LLM

Le bouton `LLM` fait défiler trois modes:

| Mode | Ce qu'il fait |
|------|---------------|
| `OFF` | Le texte STT est envoyé directement à la méthode de sortie. |
| `TRSL` | Le texte STT est emballé dans le template de prompt `translate` et la réponse du LLM est sortie. |
| `CHAT` | Le texte STT est emballé dans le template de prompt `chat` et la réponse est sortie. |

Les templates par défaut sont calculés au moment de l'appel: une
session avec `LANG=fr_*` reçoit automatiquement un prompt
« Translate to French » sans modifier les réglages. Cibles de locale
supportées: français, espagnol, allemand, italien, portugais — tout
autre cas retombe sur l'anglais. Surcharger par mode dans
`~/.config/streamdeck-tiler/settings.json`:

```json
{
  "translator_prompts": {
    "translate": "Translate to French. Output only the French translation:\n\n{text}",
    "chat": "You are a concise assistant. {text}"
  }
}
```

Le placeholder `{text}` est remplacé par le résultat STT. Si `{text}`
est absent, le résultat STT est ajouté après une ligne vide.

Si l'appel LLM échoue, le texte STT original est utilisé comme
fallback pour qu'aucune capture audio ne soit perdue.

## Persistance des réglages

`~/.config/streamdeck-tiler/settings.json` (créé à la première
sauvegarde):

<!-- [common] -->
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

<!-- [en] -->
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

<!-- [fr] -->
Toutes les clés sont optionnelles. Les clés manquantes retombent sur
le premier backend / méthode détecté et sur `LLM_MODE_OFF`.

## Flux de bout en bout

1. L'utilisateur presse TRANSL sur l'écran d'accueil →
   `MODE_TRANSLATOR`.
2. L'utilisateur choisit un backend / sortie / mode LLM.
3. L'utilisateur presse REC. `translator.start_recording()` lance
   l'enregistreur; le bouton devient rouge et l'icône passe à
   `mic_on`.
4. L'utilisateur parle.
5. L'utilisateur presse REC à nouveau. `translator.stop_recording()`
   termine l'enregistreur. Un thread démon exécute
   `_finish_transcription()`:
   1. Le backend STT sélectionné transcrit le WAV.
   2. Si le mode `LLM` n'est pas `OFF`, `llm_postprocess()` tourne.
   3. `output_text()` injecte les touches (`TYPE`) ou copie dans le
      presse-papiers (`CLIP`).
   4. Le fichier WAV est supprimé.
6. Le deck flash `OK!` (vert) ou `ERR` (rouge) pendant 1.5 s.

Les appels STT et LLM tournent sur un worker thread pour que le deck
reste réactif — l'utilisateur peut presser BACK pour quitter le mode
sans perdre la transcription en cours (le thread termine
silencieusement).

## Notes de sécurité

- La sortie `TYPE` écrit ce que le LLM retourne dans la fenêtre
  active. Un clip audio malicieux combiné à un template de prompt
  permissif pourrait injecter des touches. Préférer `CLIP` quand la
  source audio est incertaine (par ex. en réunion où quelqu'un
  d'autre pourrait parler des commandes à ton micro).
- Les enregistrements audio sont écrits dans `/tmp` et supprimés
  après transcription; aucun audio n'est conservé sur disque.
- L'appel LLM est en HTTP vers `localhost`. Le script ne joint
  jamais une API externe. Si tu remplaces `OllamaBackend.URL` par un
  hôte distant, le texte issu de l'audio quitte la machine — fais
  ce changement délibérément.

## Travail futur

- Une cible make qui installe `whisper.cpp` + modèle tiny en une
  commande.
- Auto-pull du modèle selon le matériel au premier run
  (`recommend_model` + `ollama pull`).
- Transcription en streaming (sous-titres live) une fois le binaire
  stream de whisper.cpp encapsulé — actuellement, un enregistrement
  fragmenté n'afficherait les résultats qu'après STOP.
- Templates de prompt LLM configurables par mode (actuellement codés
  en dur dans `translator.llm_postprocess`).

Voir `tasks/translator-roadmap.md` pour le plan de phase complet et
la discussion sur la Phase 3 (WebLLM browser) reportée.
