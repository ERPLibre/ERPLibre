# Conventions de code

## Python
- Formateur : **Black** (profil par défaut, ligne max 79 pour les modules Odoo)
- Imports : **isort** avec profil `black`, longueur de ligne 79
- Linting : **Flake8** avec bugbear, max-line-length 80, max-complexity 16
- Ignorer : E203, E501, W503 (compatibilité Black)

## XML / JSON / YAML
- Formateur : **Prettier** (via npm)
- Indentation : 4 espaces (XML/CSS/JS), 2 espaces (JSON/YAML)

## Fichiers
- Encodage : UTF-8
- Fins de ligne : LF (Unix)
- Indentation : 4 espaces (Python, XML, CSS, JS), 2 espaces (JSON, YAML, RST, MD)
- Retour à la ligne final : oui
- Espaces en fin de ligne : supprimés

## Git
- Branches : `develop` (développement), `master` (production)
- Pas de submodules Git — utilise **Google Repo** pour les addons
- Manifests XML dans `manifest/` pour chaque version Odoo
- Format de commit : `[TYPE] description` (ex: `[FIX]`, `[UPD]`, `[ADD]`, `[REM]`)
