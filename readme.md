# Analyse de refactorisation - ERPLibre Scripts

## Vue d'ensemble

Ce document analyse les scripts principaux d'ERPLibre en vue d'une refactorisation.
Les problèmes identifiés se regroupent en 3 catégories : **nommage des variables**,
**architecture** et **cohérence du code**.

---

## Fichiers analysés

| Fichier | Lignes | Priorité | Problème principal |
|---------|--------|----------|--------------------|
| `script/todo/todo.py` | 1860 | Critique | God Object, classe unique trop large |
| `script/git/git_tool.py` | 1096 | Critique | Responsabilités multiples, notation hongroise |
| `script/todo/todo_i18n.py` | 586 | Haute | Dictionnaire monolithique de 200+ clés |
| `script/execute/execute.py` | 193 | Haute | Paramètres booléens multiples, mélange FR/EN |
| `script/config/config_file.py` | 98 | Moyenne | Nommage flou des variables de merge |
| `script/process/kill_process_by_port.py` | 255 | Basse | Problèmes mineurs de nommage |

---

## 1. Problèmes de nommage des variables

### 1.1 Notation hongroise (`dct_`, `lst_`, `no_`, `cst_`)

Utilisée de manière incohérente à travers le projet. Non-standard en Python (PEP 8).

**Exemples :**
```python
# git_tool.py - notation hongroise
dct_remote = {a.get("@name"): a.get("@fetch") for a in lst_remote}

# Recommandé :
remotes_by_name = {a.get("@name"): a.get("@fetch") for a in remote_list}
```

```python
# config_file.py - noms flous
dct_data_init = ...
dct_data_second = ...
dct_data_final = ...

# Recommandé :
default_config = ...
override_config = ...
merged_config = ...
```

```python
# execute.py, todo.py - préfixe "cst_" pour constante
cst_venv_erplibre = ".venv.erplibre"

# Recommandé :
VENV_ERPLIBRE = ".venv.erplibre"
```

### 1.2 Mélange français/anglais

```python
# execute.py ligne 62
def execute(self, commande, ...):  # "commande" est en français
# Recommandé :
def execute(self, command, ...):
```

### 1.3 Constantes en minuscules

```python
# todo.py
file_error_path = "error_log.txt"  # Devrait être FILE_ERROR_PATH (constante module)

# git_tool.py
CST_FILE_SOURCE_REPO_ADDONS = ...  # Préfixe "CST_" inutile
# Recommandé : FILE_SOURCE_REPO_ADDONS
```

### 1.4 Noms génériques ou ambigus

```python
# git_tool.py
class Struct(object):  # Trop générique
# Recommandé : class RepoInfo ou _DynamicAttrs

# todo.py
self.file_path = None  # Chemin vers quoi exactement ?
# Recommandé : self.selected_file_path ou self.kdbx_file_path

# kill_process_by_port.py
STOP_PARENT_KILL = [...]  # Confus : c'est une liste de noms de processus parents
# Recommandé : PROTECTED_PARENT_NAMES ou WRAPPER_SCRIPT_NAMES
```

### 1.5 Paramètres booléens en cascade

```python
# execute.py - trop de flags booléens
def execute(self, commande,
            return_status=False,
            return_status_and_command=False,
            return_status_and_output=False,
            source_erplibre=True,
            source_odoo=""):
# Recommandé : utiliser un Enum ou un dataclass pour le type de retour
```

---

## 2. Problèmes d'architecture

### 2.1 God Object : `todo.py` (1860 lignes, 1 classe)

La classe `TODO` gère tout :
- Navigation des menus CLI (20+ méthodes `prompt_*`)
- Gestion des mots de passe KeePass
- Sélection de bases de données
- Gestion des versions Odoo
- Exécution de commandes
- Affichage et formatage

**Découpage recommandé :**

```
todo.py (orchestrateur léger ~200 lignes)
├── menu_builder.py       - Construction et navigation des menus
├── database_manager.py   - Sélection et opérations DB
├── version_manager.py    - Gestion des versions Odoo
├── kdbx_manager.py       - Gestion KeePass
└── command_runner.py     - Exécution des commandes
```

### 2.2 God Object : `git_tool.py` (1096 lignes, 1 classe)

La classe `GitTool` mélange :
- Transformation d'URLs Git
- Extraction d'info de dépôts
- Parsing de manifests XML
- Gestion de submodules
- Interaction API GitHub

**Découpage recommandé :**

```
git_tool.py (facade légère)
├── repo_url.py           - Parsing et transformation d'URLs
├── manifest_parser.py    - Parsing XML des manifests Google Repo
├── repo_info.py          - Extraction d'informations de dépôts
└── github_api.py         - Interactions avec l'API GitHub
```

### 2.3 Dictionnaire monolithique : `todo_i18n.py`

Un seul dictionnaire `TRANSLATIONS` contient 200+ entrées mélangées :
menus, prompts, messages d'erreur, configurations.

**Recommandé :** Séparer par domaine ou utiliser des fichiers `.json`/`.po` :
```python
MENU_TRANSLATIONS = { ... }
PROMPT_TRANSLATIONS = { ... }
ERROR_TRANSLATIONS = { ... }
```

---

## 3. Incohérences à travers le projet

| Problème | Où | Impact |
|----------|----|--------|
| Notation hongroise (`dct_`, `lst_`) | git_tool.py, config_file.py | Lisibilité |
| Préfixe `cst_` pour constantes | todo.py, execute.py | Convention PEP 8 |
| Français dans le code (`commande`) | execute.py | Cohérence |
| Commentaires en français dans code anglais | Plusieurs fichiers | Cohérence |
| `.keys()` redondant dans `if x in dict.keys()` | config_file.py | Style |
| `Exception` générique capturée | execute.py | Robustesse |
| Variables initialisées à `None` sans typage | todo.py | Maintenabilité |

---

## 4. Plan de refactorisation suggéré

### Phase 1 : Nommage (risque faible)
1. Remplacer la notation hongroise (`dct_`, `lst_`, `no_`, `cst_`)
2. Renommer `commande` -> `command` dans execute.py
3. Mettre les constantes module en MAJUSCULES
4. Renommer les classes/variables génériques (`Struct`, `file_path`)

### Phase 2 : Découpage (risque moyen)
1. Extraire `KdbxManager` de todo.py
2. Extraire `DatabaseManager` de todo.py
3. Extraire `VersionManager` de todo.py
4. Découper git_tool.py en 4 modules

### Phase 3 : Modernisation (risque moyen)
1. Ajouter des type hints aux signatures publiques
2. Remplacer les flags booléens par des Enum/dataclass dans execute.py
3. Séparer le dictionnaire de traductions par domaine
4. Ajouter des tests unitaires avant chaque refactorisation

---

## 5. Bonnes pratiques déjà en place

- Système de configuration en couches (base -> override -> privé)
- Module i18n séparé du CLI
- Pool asyncio pour l'exécution parallèle
- Liste de protection des processus parents dans kill_process_by_port.py
- Séparation claire entre scripts ERPLibre et scripts Odoo

---

## Notes

- Chaque phase de refactorisation devrait être précédée de tests pour éviter les régressions
- Le découpage de todo.py est la refactorisation à plus haut impact
- Le renommage des variables peut se faire de manière incrémentale, fichier par fichier

---
---

# Analyse du module `erplibre_sync_external_data`

## Vue d'ensemble

Module Odoo 18 pour importer/synchroniser des données externes (Excel/CSV) vers des modèles Odoo, avec suivi des modifications et transformation de données.

**Version :** 18.0.1.2.4 | **Licence :** AGPL-3 | **Auteur :** TechnoLibre

---

## Architecture (8 modèles)

```
sync.model                          # Template de sync (métadonnées JSON)
  └── sync.data.exec                # Contrôleur d'import (upload → extraction → résumé)
        ├── sync.data.create        # Référence aux enregistrements créés
        └── mail.tracking.value     # Suivi des modifications (hérité)

sync.data.transform                 # Contrôleur de transformation
  ├── sync.data.transform.exec      # Tâche de transformation unitaire (create/write)
  └── sync.data.transform.filter_search  # Patterns de filtre de recherche

sync.data.exec.cron.log             # Journal des crons
```

### Flux de données

```
Fichier Excel/CSV
  → sync.data.exec.extract_automated_excel()  (943 lignes)
    → Lecture métadonnées depuis sync.model.spreadsheet_extraction_metadata
    → Validation des en-têtes
    → Conversion de types (date, bool, int, float, char)
    → Recherche d'existants via champs "sync"
    → Création OU mise à jour des enregistrements
    → Suivi via mail.tracking.value / sync.data.create

  → sync.data.transform.action_transform_default()
    → Lecture des "bind" depuis les métadonnées
    → Construction de sync.data.transform.exec (create/write)
    → Résolution de dépendances (#REPLACE.{hex})
    → Application des modifications
```

---

## Problèmes identifiés

### 1. Variables difficiles à comprendre

| Variable actuelle | Fichier | Problème | Suggestion |
|---|---|---|---|
| `file_no_line` | sync_data_exec.py:373,618,700 | "no_line" = "numéro de ligne" en franglais | `file_line_number` |
| `numero_projet` | sync_data_exec.py:290,316,601 | Variable française dans code anglais | `project_number` |
| `bind_field_reverse` | sync_data_transform.py:208,254 | Le sens "reverse" est ambigu | `back_reference_field` |
| `id_depend_name` | sync_data_transform_exec.py:73 | Format `#REPLACE.{hex}` non documenté | `dependency_placeholder` |
| `associate_key` | sync_data_transform_exec.py:379,482,555 | Rôle flou, format `{model}.{method}.{field}.{value}` | `dedup_key` ou `unique_operation_key` |
| `dct_mapping_value` | sync_data_exec.py:549 | Préfixe `dct_` systématique, verbose | `field_mapping` |
| `lst_row_text` | sync_data_exec.py | Préfixe `lst_` systématique, verbose | `row_values` |
| `lst_sync_field` | sync_data_exec.py | idem | `sync_fields` |
| `dct_mirror_group` | sync_data_transform.py | Concept "mirror" non documenté | `grouped_bindings` |
| `modification_json` | sync_data_transform_exec.py:394,480 | Parfois str JSON, parfois dict | `field_values` (toujours dict) |

### 2. Complexité excessive

#### `extract_automated_excel()` — 943 lignes, 8+ niveaux d'imbrication
- **sync_data_exec.py:354-721** : Méthode monolithique impossible à tester unitairement
- Mélange lecture fichier, validation, conversion de types, recherche ORM, création/écriture

**Découpage suggéré :**
```
extract_automated_excel()
  ├── _parse_file(file, metadata)           → DataFrame/liste de lignes
  ├── _validate_headers(headers, expected)  → bool + warnings
  ├── _convert_row(row, field_types)        → dict de valeurs typées
  ├── _find_existing(model, sync_fields, values) → recordset ou False
  ├── _create_record(model, values)         → recordset
  └── _update_record(record, values)        → tracking values
```

#### `_transform_date()` — 6 blocs try/except imbriqués
- **sync_data_exec.py:794-922** : Anti-pattern classique
- Supporte 20+ formats de date incluant les mois français

**Suggestion :** Utiliser `dateutil.parser.parse()` avec fallback sur les formats spécifiques, ou une liste de formats avec boucle unique :
```python
DATE_FORMATS = ["%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", ...]
for fmt in DATE_FORMATS:
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError:
        continue
```

#### `_bind_transform()` — 175 lignes, 3 listes modifiées en place
- **sync_data_transform.py:338-512** : État mutable complexe
- Many2many/One2many : `print("todo")` aux lignes 435 et 504

### 3. Métadonnées JSON trop complexes

Le champ `spreadsheet_extraction_metadata` accepte 20+ clés imbriquées sans validation de schéma :

```python
{
    "header": [...],                        # Obligatoire
    "index_line_header": 0,                 # Obligatoire
    "nb_line_header": 1,                    # Obligatoire
    "sync": [...],                          # Obligatoire
    "filetype": "xlsx",                     # Obligatoire
    "sheet_name": "...",                    # Optionnel
    "ignore_last_line": 0,                  # Optionnel
    "index_last_line": 0,                   # Optionnel
    "ignore_data": [...],                   # Optionnel
    "ignore_validation_header": False,      # Optionnel
    "callback_init_read_header": "...",     # Optionnel
    "option_level": {                       # Optionnel
        "repeat_column": [],
        "duplicate_column_when_empty": []
    },
    "bind": [...]                           # Optionnel, structure profonde
}
```

**Suggestion :** Remplacer par des champs Odoo explicites sur `sync.model` ou au minimum valider le JSON avec un schéma.

### 4. Code mort et incomplet

| Localisation | Problème |
|---|---|
| sync_data_exec.py:435-436 | Print de debug commenté |
| sync_data_transform.py:376-422 | Bloc de code commenté |
| sync_data_transform.py:435 | `print("todo")` pour many2many |
| sync_data_transform.py:504 | `print("todo")` pour one2many |
| sync_data_exec.py:316 | Commentaire TODO |
| sync_data_exec.py:598 | Commentaire TODO |
| sync_data_exec.py:260 | `CST_CRM_LEAD_TEAM` commenté |

### 5. Gestion d'erreurs fragile

- Les erreurs de parsing sont loguées en warning mais l'exécution continue silencieusement
- `_transform_date()` retourne `False` au lieu de `None` pour les dates non parsables
- Pas de validation sur les clés du dictionnaire de métadonnées
- Les indices magiques (`lst_row_text[1:]`, `len(line) - 1`) cassent si le format change

---

## Recommandations de refactorisation (par priorité)

### Priorité 1 — Lisibilité immédiate
1. **Renommer les variables** selon le tableau ci-dessus
2. **Supprimer le code mort** (commentaires TODO, print debug, blocs commentés)
3. **Uniformiser la langue** : tout en anglais

### Priorité 2 — Découpage structurel
4. **Éclater `extract_automated_excel()`** en 5-6 méthodes privées testables
5. **Refactoriser `_transform_date()`** : liste de formats + boucle unique
6. **Extraire `_bind_transform()`** en sous-méthodes par type de champ

### Priorité 3 — Robustesse
7. **Valider le JSON de métadonnées** avec un schéma (ou migrer vers des champs Odoo)
8. **Implémenter many2many/one2many** ou lever une `NotImplementedError`
9. **Améliorer la gestion d'erreurs** : fail-fast avec messages clairs

### Priorité 4 — Simplification architecturale
10. **Réduire la profondeur des `bind`** : séparer la config de liaison dans un modèle dédié
11. **Remplacer `#REPLACE.{hex}`** par un système de résolution de dépendances plus explicite
12. **Unifier le format `modification`** : toujours dict, jamais str JSON

---

## Statistiques du module

| Métrique | Valeur |
|---|---|
| Fichiers Python (modèles) | 8 |
| Fichiers XML (vues) | 8 |
| Fichiers de test | 3 |
| Migrations | 5 versions |
| Lignes Python totales | ~1950 |
| Fichier le plus long | sync_data_exec.py (943 lignes) |
| Complexité cyclomatique max | extract_automated_excel (~40+) |
| Couverture de test | Bonne pour les utilitaires, faible pour le flux principal |

---

## Bonnes pratiques déjà en place

- Système de suivi des modifications via `mail.tracking.value`
- Support async via `queue_job` (avec fallback synchrone)
- Tests unitaires existants (30+ tests de parsing de dates)
- Système de dépendances entre transformations
- Notifications par email configurables par groupe
