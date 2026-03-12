# Structure du projet

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
