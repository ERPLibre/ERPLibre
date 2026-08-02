# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ERPLibre Multi-Version Odoo Platform

## Projet

ERPLibre est un fork communautaire d'Odoo Community Edition (OCE) supportant les versions 12 à 18.
Version actuelle : **1.6.0** | Licence : **AGPL-3.0+**
Version Odoo par défaut : **18.0** (support officiel ERPLibre 1.6.0)

## Points d'attention pour Claude

- Toujours vérifier la version Odoo active avant de modifier du code (`cat .odoo-version`)
- Les addons sont dans `addons/` et gérés par Google Repo — ne pas modifier la structure des dépôts
- Utiliser le venv approprié pour le code Odoo. Son nom porte les DEUX versions
  (`.venv.odoo18.0_python3.12.10/bin/python`) : le retrouver par
  `ls -d .venv.odoo*` plutôt que de le composer de tête
- Les scripts ERPLibre utilisent `.venv.erplibre/bin/python`
- Le Makefile principal inclut des fragments depuis `conf/make.*.Makefile`
- Les fichiers privés vont dans `private/` (non versionné)
- La DB PostgreSQL par défaut est sur le port 5432, mot de passe admin : `admin`
- Port Odoo par défaut : 8069, longpolling : 8072
- Pour les commits : suivre le format `[TYPE] description` (ex: `[FIX]`, `[UPD]`, `[ADD]`, `[REM]`)
- Pour la documentation : modifier les `.base.md`, jamais les `.md` ou `.fr.md` directement
- Outil mmg disponible via `source .venv.erplibre/bin/activate && mmg`

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Règles détaillées

Les instructions détaillées sont dans `.claude/rules/` :

| Fichier | Contenu |
|---------|---------|
| `01-versions.md` | Versions Odoo supportées, où lit-on la correspondance |
| `04-code-conventions.md` | Où sont les configs de format, conventions Git |
| `06-code-generator.md` | Génération de modules Odoo |
| `07-documentation.md` | Interdit : ne pas éditer les `.md` générés |
| `08-deployment.md` | Docker, systemd, nginx, SSL, DNS |
| `09-workflow.md` | Workflow orchestration + task management |

Chargées à la demande (`.claude/skills/`) :

| Skill | Contenu |
|-------|---------|
| `erplibre-commands` | Commandes make et scripts : versions, run, tests, DB, Docker, repo |
| `erplibre-doc-i18n` | Mode d'emploi mmg (`.base.md`) et i18n du CLI TODO |

L'arborescence et la liste des venvs ne sont plus documentées : `ls` et
`ls -d .venv.*` en donnent l'état réel, la doc dérivait de la réalité.
