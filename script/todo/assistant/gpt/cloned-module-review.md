---
gpt: 1
name: Cloned module - find what it inherited
description: Name what a cloned module inherited rather than what was written
requires:
  # `lan` : le travail de ce gpt est de regarder des noms suspects, donc
  # il ne doit atteindre aucun tiers — mais le réseau de l'opérateur
  # n'est pas un tiers.
  hosting: lan
  context_window: 32000
  parameters: 7
params:
  temperature: 0.1
  max_tokens: 600
inputs:
  - name: module_path
    type: repo_path
    required: true
context:
  files:
    - .claude/rules/04-code-conventions.md
  commands:
    - label: Staged diff
      argv: ["git", "diff", "--cached", "--", "{module_path}"]
    - label: Comment findings
      argv:
        - python3
        - script/analyse/check_comment_hygiene.py
        - --json
        - "{module_path}"
---

<!-- [system] -->
Un module engendré depuis un module existant hérite de ses commentaires et
de ses docstrings. Ton travail est de repérer ce qui a été HÉRITÉ plutôt
qu'écrit pour ce module-ci : une phrase qui parle d'un autre sujet, un nom
qui n'a rien à faire là, un exemple pris ailleurs.

Tu ne réécris rien. Tu désignes.

Rends une ligne par trouvaille, au plus huit :
<fichier>:<ligne> — <ce qui trahit l'héritage, en une phrase>

<!-- [question] -->
Qu'est-ce que {module_path} a hérité sans qu'on le veuille ?
