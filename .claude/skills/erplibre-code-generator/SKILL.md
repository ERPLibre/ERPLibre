---
name: erplibre-code-generator
description: >-
  Génération de modules Odoo dans ERPLibre : créer un module, cloner un
  module existant, où vivent le moteur et les gabarits, et l'hygiène des
  commentaires du code produit. À charger avant de générer ou de cloner
  un module.
---

ERPLibre inclut un système de génération de modules Odoo :
- `script/code_generator/new_project.py` — Créer un nouveau module
- `script/code_generator/create_from_existing_module.py` — Cloner un module existant
- `addons/TechnoLibre_odoo-code-generator/` — Moteur de génération
- `addons/TechnoLibre_odoo-code-generator-template/` — Templates

Documentation : `doc/CODE_GENERATOR.md`

## Les commentaires du code produit

Le code généré porte des commentaires comme le reste, et la même règle : ils
disent COMMENT ça marche, ils ne portent rien d'identifiant et ils ne
racontent pas l'enquête. Voir `.claude/rules/04-code-conventions.md`.

Un module généré à partir d'une base existante hérite de ce qu'elle contient :
relire ses commentaires et ses docstrings avant de committer, un nom de client
ou de base y arrive tout seul.

## Le nettoyage au fur et à mesure

La règle et ses deux garde-fous sont dans `.claude/rules/04-code-conventions.md`. Une invocation lui manque, utile
sur du code généré en masse : elle ne relève que les trouvailles.

```bash
python3 script/analyse/check_comment_hygiene.py script --identifying-only
```
