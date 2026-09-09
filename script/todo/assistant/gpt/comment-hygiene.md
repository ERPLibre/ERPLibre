---
gpt: 1
name: Comment hygiene - rewrite narrative as mechanism
description: Rewrite each flagged sentence so the code is the subject, present tense
requires:
  # `lan` et non `loopback` : une trouvaille identifiante ne doit pas
  # atteindre un TIERS, et une machine que l'opérateur fait tourner sur
  # son propre réseau n'en est pas un. Seul `any` est refusé.
  hosting: lan
  context_window: 8000
  parameters: 30
params:
  temperature: 0.2
  max_tokens: 700
inputs:
  - name: path
    type: repo_path
    required: true
context:
  files:
    - .claude/rules/04-code-conventions.md
  commands:
    - label: Findings
      argv:
        - python3
        - script/analyse/check_comment_hygiene.py
        - --json
        - "{path}"
---

<!-- [system] -->
Tu réécris les phrases signalées « récit » pour que le CODE en soit le sujet,
au présent. Le mode de défaillance que le code empêche RESTE ; l'incident où
on l'a observé PART.

Le vérificateur donne le fichier, la ligne et le motif — pas la phrase. Lis
les lignes autour avant de réécrire.

Rends, par trouvaille :
NARRATIF: <le fragment exact qui raconte, recopié tel quel>
DURABLE: <le fait de fonctionnement qui doit survivre>
APRÈS: <la phrase finale, sans le narratif>

<!-- [question] -->
Réécris les phrases signalées dans {path}.
