# Conventions de code

Le formatage et le lint sont entièrement décrits par les fichiers de
configuration du dépôt — les lire plutôt que de supposer : `.flake8`,
`.editorconfig`, et les sections `[tool.black]` / `[tool.isort]` de
`pyproject.toml`. `make format` applique l'ensemble.

Prettier (via npm) formate XML/JSON/YAML ; `.editorconfig` donne les
indentations par type de fichier.

## Git
- Branches : `develop` (développement), `master` (production)
- Pas de submodules Git — utilise **Google Repo** pour les addons
- Manifests XML dans `manifest/` pour chaque version Odoo
- Format de commit : `[TYPE] description` (ex: `[FIX]`, `[UPD]`, `[ADD]`, `[REM]`)
