# Documentation multilingue

La documentation est bilingue (anglais/français) via **mmg** (Multilingual Markdown Generator).

## Fonctionnement
- Les fichiers sources sont les `.base.md` (contiennent les deux langues)
- `mmg` génère : `FICHIER.md` (anglais) et `FICHIER.fr.md` (français)
- Marqueurs : `<!-- [en] -->`, `<!-- [fr] -->`, `<!-- [common] -->` (blocs de code partagés)

## Commandes
```bash
make doc_markdown            # Regénérer toute la doc multilingue
```

## Convention
- **Ne jamais modifier directement** les fichiers `.md` ou `.fr.md` générés
- Toujours modifier le fichier `.base.md` correspondant, puis exécuter `make doc_markdown`
- Les blocs de code vont dans `<!-- [common] -->`, le texte dans `<!-- [en] -->` et `<!-- [fr] -->`
- En-tête obligatoire dans chaque `.base.md` :
```
<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->
```

## Fichiers concernés (30 fichiers)
- Racine : `README`, `CHANGELOG`, `TODO`
- `doc/` : DEVELOPMENT, PRODUCTION, DISCOVER, RUN, MIGRATION, WINDOWS_INSTALLATION, FAQ, GIT_REPO, POETRY, RELEASE, UPDATE, CONTRIBUTION, HOWTO, TODO, CODE_GENERATOR
- `docker/` : README
- `script/*/` : database, deployment, fork_github_repo, nginx, restful, selenium (2), todo, odoo/migration
- `.github/ISSUE_TEMPLATE/` : bug_report, feature_request

## Internationalisation du CLI TODO (i18n)

Le CLI interactif `script/todo/todo.py` supporte le français et l'anglais.

### Architecture
- **`script/todo/todo_i18n.py`** — Module de traduction (dictionnaire `TRANSLATIONS`, fonctions `t()`, `get_lang()`, `set_lang()`)
- Les chaînes traduisibles utilisent `t("clé")` au lieu de texte en dur
- Les entrées de `todo.json` peuvent avoir un champ `prompt_description_key` résolu via `t()` (fallback sur `prompt_description`)

### Résolution de la langue (priorité)
1. Variable d'environnement `EL_LANG` (définie dans `env_var.sh`, défaut `"fr"`)
2. Défaut : `"fr"`

### Comportement
- Première exécution : prompt bilingue demande à l'utilisateur de choisir sa langue
- Le choix est persisté dans `env_var.sh`
- Changement de langue possible via le menu Execute > Langue/Language

### Ajouter une traduction
1. Ajouter la clé dans `TRANSLATIONS` de `todo_i18n.py` avec les valeurs `"fr"` et `"en"`
2. Remplacer la chaîne en dur par `t("ma_clé")` dans `todo.py`
3. Pour les entrées JSON : ajouter `"prompt_description_key": "ma_clé"` dans `todo.json`
