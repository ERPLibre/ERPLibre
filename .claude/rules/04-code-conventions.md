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

### Le sujet

Le sujet est lu cent fois pour une fois que le corps l'est — `git log
--oneline`, un blame, une note de version, un bisect. Il a une seule tâche :
dire **sur quoi porte le code**.

L'épreuve : le lire seul, sans diff ni corps. Sait-on quelle partie du système
est en jeu, et ce qui y est désormais différent ? Sinon il n'est pas fini.

Nommer la chose, puis ce qui change pour elle. Le symptôme, le message d'erreur
cité et la métaphore sont des PREUVES, et une preuve va dans le corps — un
sujet bâti sur elles se lit bien et n'apprend rien. La portée dit OÙ, les mots
après le deux-points doivent dire QUOI.

Le sujet résume le commit ENTIER, pas sa plus grosse pièce. S'il lui faut un
« et » entre deux choses sans rapport, c'étaient deux commits.

Le mode d'emploi complet, avec des exemples avant/après pris dans l'historique
de ce dépôt, est dans `conf/template_claude_commands_commit.md`.

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
