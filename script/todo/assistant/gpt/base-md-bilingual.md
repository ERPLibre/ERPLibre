---
gpt: 1
name: Bilingual doc - write or repair a .base.md
description: Produce or fix a .base.md, its header and its language blocks
requires:
  hosting: lan
  context_window: 16000
  parameters: 30
params:
  temperature: 0.2
  max_tokens: 1200
inputs:
  - name: path
    type: repo_path
    required: true
  - name: direction
    type: choice
    required: true
context:
  files:
    - .claude/rules/07-documentation.md
    - script/todo/README.base.md
---

<!-- [system] -->
Tu écris ou répares un fichier source de documentation bilingue.

La forme est exacte : un en-tête de quatre lignes, puis des blocs par
langue, plus un bloc commun. Un bloc de code va dans le commun et ne se
traduit jamais.

La traduction se corrige à la SOURCE : les deux fichiers dérivés sont
regénérés, donc une correction qui y serait faite est perdue au prochain
passage de l'outil.

Rends le fichier source complet, et rien d'autre.

<!-- [question] -->
Écris ou répare {path}, dans le sens {direction}.
