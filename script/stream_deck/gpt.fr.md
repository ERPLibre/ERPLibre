
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

```
BACK   .   REC   STT   OUT   LLM   LLMBE   .
```

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
```

Pistes d'installation manuelle (alternative):

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

### Méthodes de sortie

`translator.detect_output_methods()` retourne les sorties supportées:

- `TYPE` — injection de touches dans la fenêtre active:
  - `ydotool type` (Wayland, demande accès uinput).
  - `xdotool type` (fallback X11).
- `CLIP` — presse-papiers:
  - `wl-copy` (Wayland, depuis `wl-clipboard`).
  - `xclip -selection clipboard` (X11).

Sur GNOME 48 Wayland, `TYPE` requiert:

```bash
sudo apt install ydotool wl-clipboard
sudo systemctl enable --now ydotoold
sudo usermod -aG input "$USER"
# Re-login for the group change to take effect.
```

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

Pistes d'installation:

```bash
# ollama (recommended, simplest)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct      # follow recommend_model()

# llama.cpp (manual control)
git clone https://github.com/ggerganov/llama.cpp
make -C llama.cpp llama-server
~/llama.cpp/llama-server -m /path/to/model.gguf --port 8080
```

### Modes LLM

Le bouton `LLM` fait défiler trois modes:

| Mode | Ce qu'il fait |
|------|---------------|
| `OFF` | Le texte STT est envoyé directement à la méthode de sortie. |
| `TRSL` | Le texte STT est emballé dans le template de prompt `translate` et la réponse du LLM est sortie. |
| `CHAT` | Le texte STT est emballé dans le template de prompt `chat` et la réponse est sortie. |

Les templates par défaut sont dans `translator.DEFAULT_PROMPTS`.
Surcharger par mode dans `~/.config/streamdeck-tiler/settings.json`:

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