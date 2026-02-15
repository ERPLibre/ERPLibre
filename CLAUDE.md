# CLAUDE.md - ERPLibre Multi-Version Odoo Platform

## Projet

ERPLibre est un fork communautaire d'Odoo Community Edition (OCE) supportant les versions 12 à 18.
Version actuelle : **1.6.0** | Licence : **AGPL-3.0+**
Version Odoo par défaut : **18.0** (support officiel ERPLibre 1.6.0)

## Versions supportées

| Odoo  | Python   | Poetry | Statut     |
|-------|----------|--------|------------|
| 18.0  | 3.12.10  | 2.1.3  | **Défaut** |
| 17.0  | 3.10.18  | 1.8.3  | Actif      |
| 16.0  | 3.10.18  | 1.8.3  | Actif      |
| 15.0  | 3.8.20   | 1.8.3  | Déprécié   |
| 14.0  | 3.8.20   | 1.5.0  | Déprécié   |
| 13.0  | 3.7.17   | 1.5.0  | Déprécié   |
| 12.0  | 3.7.17   | 1.5.0  | Déprécié   |

Configuration dans `conf/supported_version_erplibre.json`.
Fichiers de version : `.odoo-version`, `.erplibre-version`, `.poetry-version`, `.python-odoo-version`.

## Structure du projet

```
erplibre/
├── Makefile                    # Orchestrateur principal (inclut conf/make.*.Makefile)
├── run.sh / odoo_bin.sh        # Lanceurs Odoo (venv + PYTHONPATH)
├── env_var.sh                  # Variables d'environnement globales
├── conf/                       # Configuration : Makefiles modulaires, versions, manifests CSV
│   ├── make.installation.Makefile
│   ├── make.test.Makefile
│   ├── make.database.Makefile
│   ├── make.docker.Makefile
│   ├── make.code_generator.Makefile
│   ├── make.installation.poetry.Makefile
│   └── supported_version_erplibre.json
├── manifest/                   # Manifests Google Repo (XML) par version Odoo
│   └── git_manifest_odoo{12..18}.0.xml
├── requirement/                # Dépendances par version
│   ├── pyproject.odooXX.0_pythonY.Z.toml
│   ├── poetry.odooXX.0_pythonY.Z.lock
│   └── requirements.odooXX.0_pythonY.Z.txt
├── script/                     # Scripts utilitaires (32+ catégories)
│   ├── todo/                   # CLI interactif principal (todo.py)
│   ├── database/               # Opérations DB (restore, migrate, image_db)
│   ├── addons/                 # Gestion des modules (install, update, uninstall)
│   ├── code_generator/         # Génération de modules Odoo
│   ├── version/                # Changement de version
│   ├── git/                    # Opérations Git et Google Repo
│   ├── maintenance/            # Formatage (black, isort, prettier)
│   ├── test/                   # Tests parallèles + coverage
│   ├── docker/                 # Build/run Docker
│   ├── poetry/                 # Gestion Poetry
│   ├── deployment/             # Déploiement production
│   └── selenium/               # Tests web automatisés
├── docker/                     # Dockerfiles + docker-compose par version
├── addons/                     # Répertoire des addons (géré par Google Repo)
│   ├── OCA_*/                  # Modules OCA
│   ├── ERPLibre_*/             # Modules ERPLibre
│   ├── TechnoLibre_*/          # Code generator + templates
│   └── MathBenTech_*/          # Modules spécialisés
├── odoo{12..18}.0/             # Sources Odoo par version
├── doc/                        # Documentation (DEVELOPMENT, PRODUCTION, MIGRATION, etc.)
├── test/                       # Framework de test
└── private/                    # Fichiers privés (non versionné)
```

## Commandes essentielles

### Changement de version Odoo
```bash
make switch_odoo_18          # Passer à Odoo 18
make switch_odoo_17          # Passer à Odoo 17
make switch_odoo_16          # Passer à Odoo 16 (défaut)
make switch_odoo_15          # Passer à Odoo 15
make switch_odoo_14          # Passer à Odoo 14
make switch_odoo_13          # Passer à Odoo 13
make switch_odoo_12          # Passer à Odoo 12
make switch_odoo_16_update   # Passer + mettre à jour les dépendances
```

### Exécution
```bash
make run                     # Lancer Odoo (port 8069)
make run_test                # Lancer avec la DB "test"
./run.sh -d ma_base          # Lancer avec une DB spécifique
./odoo_bin.sh [args]         # Exécuter odoo-bin directement
```

### Base de données
```bash
make db_create_db_test                        # Créer la DB "test"
make db_clone_test_to_test2                   # Cloner test -> test2
./script/database/db_restore.py --database NOM --image IMAGE
./script/addons/install_addons_dev.sh DB module1,module2
./script/addons/update_addons_all.sh DB
```

### Tests
```bash
make test                    # Tests de base + format
make test_full_fast          # Tests complets en parallèle
make test_full_fast_coverage # Avec couverture de code
```

### Formatage du code
```bash
make format                  # Fichiers à commiter uniquement
make format_all              # Tout formater (parallèle)
```

Outils : **Black** (Python, ligne max 79), **isort** (profil black, ligne max 79), **Prettier** (XML/JSON), **Flake8** (ligne max 80, complexité max 16).

### Docker
```bash
make docker_run_daemon       # Lancer en production
make docker_build_odoo_18    # Builder l'image Odoo 18
```

### Google Repo (gestion multi-dépôts)
```bash
make repo_show_status        # Statut de tous les dépôts addons
make repo_configure_all      # Configurer tous les dépôts
make repo_do_stash           # Stash tous les dépôts
.venv.erplibre/bin/repo sync # Synchroniser les dépôts
```

### Installation
```bash
make install_os              # Dépendances système
make install_odoo_18         # Installer Odoo 18 complet
```

## Conventions de code

### Python
- Formateur : **Black** (profil par défaut, ligne max 79 pour les modules Odoo)
- Imports : **isort** avec profil `black`, longueur de ligne 79
- Linting : **Flake8** avec bugbear, max-line-length 80, max-complexity 16
- Ignorer : E203, E501, W503 (compatibilité Black)

### XML / JSON / YAML
- Formateur : **Prettier** (via npm)
- Indentation : 4 espaces (XML/CSS/JS), 2 espaces (JSON/YAML)

### Fichiers
- Encodage : UTF-8
- Fins de ligne : LF (Unix)
- Indentation : 4 espaces (Python, XML, CSS, JS), 2 espaces (JSON, YAML, RST, MD)
- Retour à la ligne final : oui
- Espaces en fin de ligne : supprimés

### Git
- Branches : `develop` (développement), `master` (production)
- Pas de submodules Git — utilise **Google Repo** pour les addons
- Manifests XML dans `manifest/` pour chaque version Odoo

## Architecture des environnements virtuels

```
.venv.erplibre/              # Venv ERPLibre (outils : repo, poetry, coverage)
.venv.odoo18/                # Venv Odoo 18 (Python 3.12)
.venv.odoo17/                # Venv Odoo 17 (Python 3.10)
.venv.odoo16/                # Venv Odoo 16 (Python 3.10)
.venv.odoo14/                # Venv Odoo 14 (Python 3.8)
.venv.odoo12/                # Venv Odoo 12 (Python 3.7)
```

Géré via **pyenv** pour les multiples versions de Python.

## Système de dépendances

Chaque version Odoo a son propre ensemble dans `requirement/` :
- `pyproject.odooXX.0_pythonY.Z.toml` — Configuration Poetry
- `poetry.odooXX.0_pythonY.Z.lock` — Lock file Poetry
- `requirements.odooXX.0_pythonY.Z.txt` — Requirements pip (fallback)
- `ignore_requirements.odooXX.0.txt` — Paquets à ignorer

Mise à jour : `./script/poetry/poetry_update.py`

## Code Generator

ERPLibre inclut un système de génération de modules Odoo :
- `script/code_generator/new_project.py` — Créer un nouveau module
- `script/code_generator/create_from_existing_module.py` — Cloner un module existant
- `addons/TechnoLibre_odoo-code-generator/` — Moteur de génération
- `addons/TechnoLibre_odoo-code-generator-template/` — Templates

Documentation : `doc/CODE_GENERATOR.md`

## Documentation multilingue

La documentation est bilingue (anglais/français) via **mmg** (Multilingual Markdown Generator).

### Fonctionnement
- Les fichiers sources sont les `.base.md` (contiennent les deux langues)
- `mmg` génère : `FICHIER.md` (anglais) et `FICHIER.fr.md` (français)
- Marqueurs : `<!-- [en] -->`, `<!-- [fr] -->`, `<!-- [common] -->` (blocs de code partagés)

### Commandes
```bash
make doc_markdown            # Regénérer toute la doc multilingue
```

### Convention
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

### Fichiers concernés (30 fichiers)
- Racine : `README`, `CHANGELOG`, `TODO`
- `doc/` : DEVELOPMENT, PRODUCTION, DISCOVER, RUN, MIGRATION, WINDOWS_INSTALLATION, FAQ, GIT_REPO, POETRY, RELEASE, UPDATE, CONTRIBUTION, HOWTO, TODO, CODE_GENERATOR
- `docker/` : README
- `script/*/` : database, deployment, fork_github_repo, nginx, restful, selenium (2), todo, odoo/migration
- `.github/ISSUE_TEMPLATE/` : bug_report, feature_request

## Déploiement

- **Docker** : `docker-compose.yml` (PostgreSQL 18 + PostGIS 3.6)
- **Systemd** : `script/systemd/` pour les services
- **Nginx** : `script/nginx/` pour le reverse proxy
- **SSL** : Certbot pour les certificats
- **DNS** : `script/deployment/update_dns_cloudflare.py`

Plateformes supportées : Ubuntu 20.04-25.04, Debian 12, Arch Linux, macOS (pyenv), Windows (WSL/Docker).

## Points d'attention pour Claude

- Toujours vérifier la version Odoo active avant de modifier du code (`cat .odoo-version`)
- Les addons sont dans `addons/` et gérés par Google Repo — ne pas modifier la structure des dépôts
- Utiliser le venv approprié : `.venv.odoo{XX}/bin/python` pour le code Odoo
- Les scripts ERPLibre utilisent `.venv.erplibre/bin/python`
- Le Makefile principal inclut 12 fragments depuis `conf/make.*.Makefile`
- Les fichiers privés vont dans `private/` (non versionné)
- La DB PostgreSQL par défaut est sur le port 5432, mot de passe admin : `admin`
- Port Odoo par défaut : 8069, longpolling : 8072
- Pour les commits : suivre le format `[TYPE] description` (ex: `[FIX]`, `[UPD]`, `[ADD]`, `[REM]`)
- Pour la documentation : modifier les `.base.md`, jamais les `.md` ou `.fr.md` directement
- Outil mmg disponible via `source .venv.erplibre/bin/activate && mmg`
