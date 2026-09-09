---
gpt: 1
name: Commit message - subject, bilingual body, Assisted-by
description: Turn the staged diff into a tagged subject and a bilingual body
requires:
  hosting: lan
  context_window: 16000
  parameters: 30
params:
  temperature: 0.2
  max_tokens: 900
context:
  files:
    - .claude/rules/04-code-conventions.md
  commands:
    - label: Staged files
      argv: ["git", "diff", "--cached", "--stat"]
    - label: Recent subjects, for style
      argv: ["git", "log", "--oneline", "-10"]
    - label: Staged diff
      argv: ["git", "diff", "--cached"]
---

<!-- [system] -->
Tu écris un message de commit pour le diff indexé, selon la règle du dépôt.

Trois contraintes se vérifient mécaniquement, donc tu les respectes sans
exception : le sujet porte un tag et tient en 72 caractères ; le corps fait
au plus dix lignes PAR LANGUE ; le corps est bilingue, séparé par un
marqueur qui nomme la langue de ce qui SUIT.

Le corps dit pourquoi c'était nécessaire, puis s'arrête. Rien de ce que le
diff montre déjà. Aucune donnée identifiante.

<!-- [question] -->
Écris le message pour ce qui est indexé.
