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
- Format de commit : `[TYPE] portée : sujet`, sujet à l'impératif, 72
  caractères au plus. Tags réellement utilisés : `[UPD]`, `[FIX]`, `[ADD]`,
  `[IMP]`, `[REF]`.

### Tout commit assisté par IA

Trois exigences, sans exception — `AI_POLICY.md` en donne la raison :

- Trailer `Assisted-by: <modèle>`, une ligne par modèle. C'est **binaire** :
  il y a eu IA ou non, aucun seuil à apprécier.
- **Jamais** d'IA dans `Co-authored-by:` — ce champ est réservé aux humains.
- Corps **bilingue** : le corps, puis `--- FR ---` (ou `--- EN ---`, le
  marqueur nomme la langue de ce qui SUIT), puis la traduction.

Court et direct : **10 lignes par langue**, 15 est déjà long. Le corps dit
pourquoi c'était nécessaire, puis s'arrête. Rien de ce que le diff montre
déjà ; on garde le symptôme, le chiffre mesuré et la vérification.

Le mode d'emploi complet — résolution dynamique du modèle, gabarit, identité
git, taille des correctifs — est dans
`conf/template_claude_commands_commit.md`, déployable en `/commit` par
`TODO › Execute › GPT code › Claude configs`.
