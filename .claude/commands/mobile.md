# /mobile — Guide de développement mobile ERPLibre

Tu travailles sur l'application mobile ERPLibre Home.

**Répertoire de travail :** `mobile/erplibre_home_mobile/`

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| UI | OWL 2.x (`@odoo/owl`) |
| Natif | Capacitor 8 |
| Build | Vite 6 |
| Tests | Vitest 3 |
| Lang | TypeScript |
| DB | SQLite (`@capacitor-community/sqlite`) |
| i18n | `src/i18n/fr.ts` + `src/i18n/en.ts` |

---

## Structure `src/`

```
src/
├── components/       # Composants OWL (1 dossier par composant)
│   ├── <nom>/        # <nom>_component.ts + <nom>_component.scss
│   └── ...
├── services/         # Logique métier + accès DB
├── models/           # Interfaces TypeScript (Note, Tag, Server…)
├── plugins/          # Wrappers Capacitor natifs
├── i18n/             # Traductions fr.ts / en.ts / index.ts
├── constants/        # Constantes partagées
├── utils/            # Utilitaires purs
├── __tests__/        # Tests Vitest (un fichier par service)
└── __mocks__/        # Mocks Capacitor pour les tests
```

---

## Conventions

### Composants OWL
- Nom de fichier : `snake_case_component.ts` + `.scss`
- Classe : `PascalCaseComponent extends Component`
- Template inline via `xml\`...\`` (pas de fichiers XML séparés)
- Générer un nouveau composant :
  ```bash
  cd mobile/erplibre_home_mobile
  npm run gencomp -- <NomComposant> [chemin/relatif]
  # Exemple : npm run gencomp -- NoteEditor note/editor
  ```

### Services
- Une classe par service, instanciée en singleton dans `appService.ts`
- Méthodes `async`/`await`, pas de callbacks
- Accès DB uniquement via `DatabaseService`

### Migrations DB
- Format version : `YYYYMMDDNN` (ex: `2026041401`)
- Fichiers dans `src/services/migrations/`
- Chaque migration : classe avec `version`, `up()`, et description
- `MigrationService` gère l'ordre et l'historique

### i18n
- Clés dans `src/i18n/fr.ts` et `src/i18n/en.ts`
- Utiliser `t("clé")` via l'import de `src/i18n/index.ts`
- Langue par défaut : français

### Tests
- Un fichier `<service>.test.ts` par service dans `src/__tests__/`
- Mocks Capacitor dans `src/__mocks__/`
- Lancer : `npm test` (dans `mobile/erplibre_home_mobile/`)

---

## Commandes essentielles

```bash
# Depuis mobile/erplibre_home_mobile/
npm install              # Installer dépendances
npm run build            # Build production
npm run build:dev        # Build développement
npm run start            # Dev server web
npm test                 # Vitest (tests unitaires)

# BSR = Build + Sync + Run (Android)
npm run bsr              # node scripts/bsr.js

# Capacitor
npx cap sync             # Sync web → natif
npx cap run android      # Lancer sur Android
npx cap open android     # Ouvrir Android Studio
```

---

## Points d'attention

- **Pas d'Ionic** — UI 100% OWL + CSS/SCSS custom
- **Plugins natifs** dans `src/plugins/` : wrapper TS autour des plugins Capacitor
- **Biométrie** : `@aparajita/capacitor-biometric-auth` (auth locale sans serveur)
- **Stockage sécurisé** : `capacitor-secure-storage-plugin` (tokens, clés)
- **SQLite** : toujours passer par `DatabaseService`, jamais directement
- **Offline-first** : sync avec ERPLibre via `syncService.ts`

---

## Tâche demandée

$ARGUMENTS
