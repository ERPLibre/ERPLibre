# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ERPLibre Multi-Version Odoo Platform

## Projet

ERPLibre est un fork communautaire d'Odoo Community Edition (OCE) supportant les versions 12 à 18.
Version actuelle : **1.7.0** | Licence : **AGPL-3.0+**
Version Odoo par défaut : **18.0** (support officiel ERPLibre 1.7.0)

## Points d'attention pour Claude

- Toujours vérifier la version Odoo active avant de modifier du code (`cat .odoo-version`)
- Les addons sont dans `addons/` et gérés par Google Repo — ne pas modifier la structure des dépôts
- Utiliser le venv approprié pour le code Odoo. Son nom porte les DEUX versions
  (`.venv.odoo18.0_python3.12.10/bin/python`) : le retrouver par
  `ls -d .venv.odoo*` plutôt que de le composer de tête
- Les scripts ERPLibre utilisent `.venv.erplibre/bin/python`
- Le Makefile principal inclut des fragments depuis `conf/make.*.Makefile`
- Un module cloné depuis un module existant hérite de ses commentaires
  et de ses docstrings : les relire avant de committer, un nom de client
  ou de base y arrive tout seul
- Les fichiers privés vont dans `private/`. C'est le SEUL endroit qui a le
  droit de porter une donnée de client — nom, base, machine, adresse,
  chiffres. Il peut être commité, mais seulement sur un dépôt privé : sur
  un fork public, ce qui s'y trouve devient public comme le reste
- Partout ailleurs — code, commentaires, messages de commit, documentation
  — aucune donnée identifiante, jamais. Ce sont les fichiers qui suivent le
  dépôt en amont. La règle complète, avec l'épreuve qui tranche, est dans
  `.claude/rules/04-code-conventions.md`
- La DB PostgreSQL par défaut est sur le port 5432, mot de passe admin : `admin`
- Port Odoo par défaut : 8069, longpolling : 8072
- Pour la documentation : modifier les `.base.md`, jamais les `.md` ou `.fr.md` directement
- Outil mmg disponible via `source .venv.erplibre/bin/activate && mmg`
- Les tests qui créent de VRAIES machines vivent dans `long_test/` et non dans
  `test/` : le lanceur unitaire balaie `test/test_*.py` et doit rester lançable
  en quelques secondes, même sans virtualisation. Ils durent des heures et se
  défont par `--detruire` — voir `long_test/README.md`

L'arborescence et la liste des venvs ne sont plus documentées : `ls` et
`ls -d .venv.*` en donnent l'état réel, la doc dérivait de la réalité.
