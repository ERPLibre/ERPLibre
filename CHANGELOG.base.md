<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Changelog
<!-- [fr] -->
# Journal des modifications
<!-- [en] -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- [fr] -->

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com). Ce projet adhère
au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- [common] -->

## [Unreleased]

<!-- [en] -->
**Migration notes**

Recreating the virtual environment, use installation guide from tool `make`.

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel, utiliser le guide d'installation depuis l'outil `make`.

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Support Odoo migration database and module with TODO
- Support multi version odoo switch on same workspace
- Script for hardening the installation
- Support Odoo versions 12.0 to 18.0
- Separate ERPLibre python installation from Odoo python with .venv.erplibre and .venv.odoo18
- Implement auto-installation with TODO.py
- TODO show documentation, download database, help with code formatting
- Performance script to mesure request per second
- Support Mainframe architecture 390x
- Deployment with Cloudflare and Nginx
- Support Apache configuration like Nginx
- Support RobotLibre code generator
- Support ERPLibre DevOps, automation procedure about DevOps
- ERPLibre Home Mobile Application, use TODO to compile, deploy it and personalize it
- Support Selenium grid from selenium_lib.py
- Add addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor

<!-- [fr] -->

- Support de la migration de base de données et de modules Odoo avec TODO
- Support du changement multi-version Odoo sur le même espace de travail
- Script pour le renforcement de la sécurité de l'installation
- Support des versions Odoo 12.0 à 18.0
- Séparation de l'installation Python ERPLibre de celle d'Odoo avec .venv.erplibre et .venv.odoo18
- Implémentation de l'auto-installation avec TODO.py
- TODO affiche la documentation, télécharge la base de données, aide au formatage du code
- Script de performance pour mesurer les requêtes par seconde
- Support de l'architecture Mainframe 390x
- Déploiement avec Cloudflare et Nginx
- Support de la configuration Apache comme Nginx
- Support du générateur de code RobotLibre
- Support d'ERPLibre DevOps, procédure d'automatisation DevOps
- Application mobile ERPLibre Home, utiliser TODO pour compiler, déployer et personnaliser
- Support de la grille Selenium depuis selenium_lib.py
- Ajout des addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- Docker support postgresql 18
- Format script search diff file into each repository
- Support neutralize database from Odoo

<!-- [fr] -->

- Support Docker postgresql 18
- Script de formatage recherche les fichiers diff dans chaque dépôt
- Support de la neutralisation de base de données depuis Odoo

<!-- [common] -->

## [1.6.0] - 2025-04-25

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Support multiple Odoo versions (12.0, 14.0, 16.0) in same workspace
    - This will help for the migration of modules
- Selenium script for increasing open software client interface and automating some actions.
    - Video recording
    - Support scrolling and word generating
- FAQ about kill git-daemon
- Supports Arch Linux, Ubuntu 23.10 to 25.04
- ADD repo JayVora-SerpentCS_SerpentCS_Contributions
- ADD repo CybroOdoo_CybroAddons

<!-- [fr] -->

- Support de plusieurs versions Odoo (12.0, 14.0, 16.0) dans le même espace de travail
    - Cela aidera pour la migration des modules
- Script Selenium pour augmenter l'interface client logiciel libre et automatiser certaines actions.
    - Enregistrement vidéo
    - Support du défilement et de la génération de mots
- FAQ sur comment tuer git-daemon
- Support d'Arch Linux, Ubuntu 23.10 à 25.04
- AJOUT du dépôt JayVora-SerpentCS_SerpentCS_Contributions
- AJOUT du dépôt CybroOdoo_CybroAddons

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- Refactor image_db regeneration, use configuration JSON to build image
- Guide for moving dev to prod
- Update Docker buster to bullseye
- Improve format script to help code-generator
- Improve PyCharm script
- Support OSX for open-terminal
- Remove docker-compose and replace by docker compose
- Update Poetry 1.3.1 to 1.5.1
- Test can be launched with a json configuration and support log/result individually
- Script to search docker compose into the system
- Script search class model can output into json format and support field information
- Improve Docker minimal installation docs in README for Ubuntu, test with
  Debian (https://github.com/ERPLibre/ERPLibre/issues/73)
- Statistic script showing evolution module into ERPLibre supporting Odoo 17 and Odoo 18
- Latest version wkhtmltopdf 0.12.6.1-3

<!-- [fr] -->

- Refactorisation de la régénération image_db, utilisation de la configuration JSON pour construire l'image
- Guide pour le passage de dev à prod
- Mise à jour Docker buster vers bullseye
- Amélioration du script de formatage pour aider le code-generator
- Amélioration du script PyCharm
- Support d'OSX pour open-terminal
- Suppression de docker-compose et remplacement par docker compose
- Mise à jour de Poetry 1.3.1 vers 1.5.1
- Les tests peuvent être lancés avec une configuration JSON et supportent les logs/résultats individuellement
- Script pour rechercher docker compose dans le système
- Le script de recherche de modèle de classe peut produire en format JSON et supporte les informations de champ
- Amélioration de la documentation d'installation Docker minimale dans le README pour Ubuntu, test avec
  Debian (https://github.com/ERPLibre/ERPLibre/issues/73)
- Script de statistiques montrant l'évolution des modules dans ERPLibre supportant Odoo 17 et Odoo 18
- Dernière version wkhtmltopdf 0.12.6.1-3

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- NPM installed locally and not globally
- Improve python code writer efficiency
- Config generator supporting space into ERPLibre directory
- Script to update Poetry to support @ URL
- OSX and recent Ubuntu installation
- Cloudflare script integration

<!-- [fr] -->

- NPM installé localement et non globalement
- Amélioration de l'efficacité du générateur de code Python
- Le générateur de configuration supporte les espaces dans le répertoire ERPLibre
- Script de mise à jour de Poetry pour supporter les URL avec @
- Installation OSX et Ubuntu récent
- Intégration du script Cloudflare

<!-- [common] -->

## [1.5.0] - 2023-07-07

<!-- [en] -->
**Migration notes**

Recreating the virtual environment

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel

<!-- [common] -->

```bash
rm -rf ~/.poetry
rm -rf ~/.pyenv

rm ./get-poetry.py
rm -rf ./.venv

make install
```

<!-- [en] -->

Do a backup of your database and update all modules :

<!-- [fr] -->

Faire une sauvegarde de votre base de données et mettre à jour tous les modules :

<!-- [common] -->

```bash
./run.sh --no-http --stop-after-init -d DATABASE -u all
```

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Support Ubuntu 22.04 with installation script
- Module mail_history and fetchmail_thread_default in base image DB
- Makefile can generate image DB in parallel with `image_db_create_all_parallel`
- Makefile can run all code_generator with `run_parallel_cg` and `run_parallel_cg_template`
- Script to generate Pycharm configuration and exclude directory
- Support docker alpha+beta
- Limit memory execution when install in develop
- Template nginx configuration
- Script code count statistic
- Script show OCA evolution module statistic
- Windows development support, check documentation installation
- New project (code generator to create module) support params configuration
- Module sync_external_model to synchronise Odoo models with module

<!-- [fr] -->

- Support d'Ubuntu 22.04 avec script d'installation
- Module mail_history et fetchmail_thread_default dans l'image DB de base
- Le Makefile peut générer l'image DB en parallèle avec `image_db_create_all_parallel`
- Le Makefile peut exécuter tous les code_generator avec `run_parallel_cg` et `run_parallel_cg_template`
- Script pour générer la configuration PyCharm et exclure les répertoires
- Support docker alpha+beta
- Limitation de la mémoire d'exécution lors de l'installation en développement
- Template de configuration nginx
- Script de statistiques de comptage de code
- Script montrant l'évolution des modules OCA
- Support du développement Windows, consulter la documentation d'installation
- Nouveau projet (code generator pour créer un module) supporte la configuration par paramètres
- Module sync_external_model pour synchroniser les modèles Odoo avec un module

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- Odoo 12.0 update from 22-07-2020 to 01-01-2023
- Update pip dependency with security update
    - Pillow==9.3.0
    - psycopg2==2.9.5
    - Werkzeug==0.16.1
    - check diff of file pyproject.toml for all information
- Update to Python==3.7.16
- Update poetry==1.3.1
- Update multilingual-markdown==1.0.3
- Update imagedb with all Odoo update
- Repo documentation-user from Odoo change to documentation
- Repo odooaktiv/QuotationRevision is deleted
- Update all repo (91) to end of 2022
- Rename module project_task_subtask_time_range => project_time_budget
- Rename module project_task_time_range => project_time_range
- Refactor script emplacement, create directory in ./script/ per subject
- Use command parallel in Makefile
- Update sphinx version
- Improve script location

<!-- [fr] -->

- Mise à jour Odoo 12.0 du 22-07-2020 au 01-01-2023
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.3.0
    - psycopg2==2.9.5
    - Werkzeug==0.16.1
    - vérifier le diff du fichier pyproject.toml pour toutes les informations
- Mise à jour vers Python==3.7.16
- Mise à jour poetry==1.3.1
- Mise à jour multilingual-markdown==1.0.3
- Mise à jour imagedb avec toutes les mises à jour Odoo
- Le dépôt documentation-user d'Odoo change pour documentation
- Le dépôt odooaktiv/QuotationRevision est supprimé
- Mise à jour de tous les dépôts (91) à fin 2022
- Renommage du module project_task_subtask_time_range => project_time_budget
- Renommage du module project_task_time_range => project_time_range
- Refactorisation de l'emplacement des scripts, création de répertoires dans ./script/ par sujet
- Utilisation de la commande parallel dans le Makefile
- Mise à jour de la version sphinx
- Amélioration de l'emplacement des scripts

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Debian 11 installation script
- Test result
- OSX installation (not finish to support)
- Poetry update support '~='

<!-- [fr] -->

- Script d'installation Debian 11
- Résultats de tests
- Installation OSX (support non terminé)
- La mise à jour de Poetry supporte '~='

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Ubuntu 18.04 is broken, need to install manually nodejs and npm
- Module contract_portal and remove signature in portal contract, need an update
- Downgrade module helpdesk_mgmt to remove email team and tracking field
    - Module helpdesk_partner
    - Module helpdesk_service_call
    - Module helpdesk_supplier
    - Module helpdesk_mrp
    - Module helpdesk_mailing_list
    - Module helpdesk_join_team
- Module project_time_management
- Support of vatnumber, too old
- Deprecated python dependency like pycrypto

<!-- [fr] -->

- Ubuntu 18.04 est cassé, besoin d'installer manuellement nodejs et npm
- Module contract_portal et suppression de la signature dans le portail de contrat, nécessite une mise à jour
- Rétrogradation du module helpdesk_mgmt pour supprimer l'équipe email et le champ de suivi
    - Module helpdesk_partner
    - Module helpdesk_service_call
    - Module helpdesk_supplier
    - Module helpdesk_mrp
    - Module helpdesk_mailing_list
    - Module helpdesk_join_team
- Module project_time_management
- Support de vatnumber, trop ancien
- Dépendances Python dépréciées comme pycrypto

<!-- [common] -->

## [1.4.0] - 2022-10-05

<!-- [en] -->
**Migration note**

- Update module `website`,`website_form_builder`.
- For dev, run `poetry cache clear --all pypi`

<!-- [fr] -->
**Note de migration**

- Mettre à jour les modules `website`,`website_form_builder`.
- Pour le développement, exécuter `poetry cache clear --all pypi`

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Script run_parallel_test.sh to execute all tests in parallel for better execution speed
- Documentation to use docker in production
- Add repo:
    - Ajepe odoo-addons to support restful
    - OmniaGIT Odoo PLM
    - MathBenTech family-management
    - erplibre-3D-printing-addons
- Add module:
    - iohub_connector to support mqtt
    - website_snippet_all to install all snippets, extracted from all themes
    - website_blog_snippet_all to install website_snippet_all with website_blog and associated snippet
    - sinerkia_jitsi_meet to integrate Jitsi
    - erplibre_website_snippets_jitsi to integrate Jitsi in snippet, work in progress
- Add module by default:
    - auto_backup
    - muk_website_branding
    - website_snippet_anchor
    - website_anchor_smooth_scroll
    - crm_team_quebec
    - partner_no_vat
- Documentation Odoo dev
- Format command supported addons
- Install theme with Odoo command
- Script to install theme addons
- Image website with default theme
- Image erplibre demo
- Test with coverage

<!-- [fr] -->

- Script run_parallel_test.sh pour exécuter tous les tests en parallèle pour une meilleure vitesse d'exécution
- Documentation pour utiliser Docker en production
- Ajout de dépôts :
    - Ajepe odoo-addons pour supporter restful
    - OmniaGIT Odoo PLM
    - MathBenTech family-management
    - erplibre-3D-printing-addons
- Ajout de modules :
    - iohub_connector pour supporter mqtt
    - website_snippet_all pour installer tous les snippets, extraits de tous les thèmes
    - website_blog_snippet_all pour installer website_snippet_all avec website_blog et les snippets associés
    - sinerkia_jitsi_meet pour intégrer Jitsi
    - erplibre_website_snippets_jitsi pour intégrer Jitsi dans les snippets, travail en cours
- Ajout de modules par défaut :
    - auto_backup
    - muk_website_branding
    - website_snippet_anchor
    - website_anchor_smooth_scroll
    - crm_team_quebec
    - partner_no_vat
- Documentation Odoo dev
- Commande de formatage pour les addons supportés
- Installation de thème avec la commande Odoo
- Script pour installer les addons de thème
- Image du site web avec thème par défaut
- Image démo erplibre
- Tests avec couverture

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Downgrade sphinx to 1.6.7 to support Odoo dev documentation
- Update to poetry==1.1.14
- Update pip dependency with security update
    - Pillow==9.0.1
    - PyPDF2==1.27.8
    - lxml==4.9.1
- Code generator export website with attachments and scss design file with documentation
- Code generator support multiple snippets
- Into repo Numigi_odoo-project-addons rename module project_template to project_template_numigi
- Into repo Numigi_odoo-product-addons rename module product_dimension to product_dimension_numigi
- Into repo Numigi_odoo-partner-addons, re-enable auto-install module
- Into repo muk-it_muk_website, re-enable auto-install module

<!-- [fr] -->

- Rétrogradation de sphinx à 1.6.7 pour supporter la documentation Odoo dev
- Mise à jour vers poetry==1.1.14
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.0.1
    - PyPDF2==1.27.8
    - lxml==4.9.1
- Le code generator exporte le site web avec les pièces jointes et le fichier de design scss avec documentation
- Le code generator supporte les snippets multiples
- Dans le dépôt Numigi_odoo-project-addons, renommage du module project_template en project_template_numigi
- Dans le dépôt Numigi_odoo-product-addons, renommage du module product_dimension en product_dimension_numigi
- Dans le dépôt Numigi_odoo-partner-addons, réactivation du module auto-install
- Dans le dépôt muk-it_muk_website, réactivation du module auto-install

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Poetry supports insensitive python dependency
- Code generator new project supports relative path and check duplicated paths
- Muk web theme table header background-color and on hover for Many2many
- Script docker-compose use lowercase name
- website_form_builder HTML support and allow option to align send button
- Odoo cherry-pick 2 commits bus fix
- Minor fix css color into module hr_theme from repo CybroOdoo_OpenHRMS
- Typo in project task when logging time

<!-- [fr] -->

- Poetry supporte les dépendances Python insensibles à la casse
- Le nouveau projet du code generator supporte les chemins relatifs et vérifie les chemins dupliqués
- Couleur d'arrière-plan de l'en-tête de tableau du thème web Muk et survol pour Many2many
- Le script docker-compose utilise des noms en minuscules
- website_form_builder support HTML et option pour aligner le bouton d'envoi
- Cherry-pick Odoo de 2 commits correctif bus
- Correction mineure de couleur CSS dans le module hr_theme du dépôt CybroOdoo_OpenHRMS
- Faute de frappe dans la tâche de projet lors de la saisie du temps

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Module package erplibre from ERPLibre_erplibre_addons and use instead image creation, check Makefile

<!-- [fr] -->

- Paquet de module erplibre de ERPLibre_erplibre_addons, utiliser à la place la création d'image, voir le Makefile

<!-- [common] -->

## [1.3.0] - 2022-01-25

<!-- [en] -->
**Migration note**

With new version of poetry, a bug occurs in the update. The solution is to delete the directory to let it
recreate. `rm -rf ~/.poetry`

<!-- [fr] -->
**Note de migration**

Avec la nouvelle version de poetry, un bogue survient lors de la mise à jour. La solution est de supprimer le répertoire pour le laisser
se recréer. `rm -rf ~/.poetry`

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Code generator supports view : activity, calendar, diagram, form, graph, kanban, pivot, search, timeline and tree
- Code generator supports portal view field and form creation
- Code generator generates generic snippets for demo_portal
- Code generator generates code_generator with code_generator_code_generator
- Code generator tests mariadb migrator
- Code generator supports javascript interpretation for snippet
- Code generator supports inheritance
- Code generator new project to create the suite of generation code
- Script to test the generation of module `code_generator`
- Make test_full_fast to run all test in parallel
- Module `web_timeline` and `web_diagram_position` in base image.
- Module `odoo-formio` from novacode-nl
- Module `design_themes` from Odoo
- Format python header with isort

<!-- [fr] -->

- Le code generator supporte les vues : activity, calendar, diagram, form, graph, kanban, pivot, search, timeline et tree
- Le code generator supporte la création de champs de vue portail et de formulaires
- Le code generator génère des snippets génériques pour demo_portal
- Le code generator génère code_generator avec code_generator_code_generator
- Le code generator teste le migrateur mariadb
- Le code generator supporte l'interprétation javascript pour les snippets
- Le code generator supporte l'héritage
- Nouveau projet du code generator pour créer la suite de génération de code
- Script pour tester la génération du module `code_generator`
- Make test_full_fast pour exécuter tous les tests en parallèle
- Module `web_timeline` et `web_diagram_position` dans l'image de base.
- Module `odoo-formio` de novacode-nl
- Module `design_themes` d'Odoo
- Formatage de l'en-tête Python avec isort

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update to Python==3.7.12
- Update to poetry==1.1.12
- Update pip dependency with security update
    - Pillow==9.0.0
    - lxml==4.7.1
    - babel==2.9.1
    - pyyaml==6.0
    - reportlab==3.6.5
- Web diagram module has all color of the rainbow in option
- Refactor and simplify code of code_generator, better support of code reader

<!-- [fr] -->

- Mise à jour vers Python==3.7.12
- Mise à jour vers poetry==1.1.12
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.0.0
    - lxml==4.7.1
    - babel==2.9.1
    - pyyaml==6.0
    - reportlab==3.6.5
- Le module web diagram a toutes les couleurs de l'arc-en-ciel en option
- Refactorisation et simplification du code du code_generator, meilleur support du lecteur de code

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Downgrade Werkzeug==0.11.15, only this version is supported by Odoo 12.0. This fixes some http request behind a proxy.

<!-- [fr] -->

- Rétrogradation Werkzeug==0.11.15, seule cette version est supportée par Odoo 12.0. Cela corrige certaines requêtes HTTP derrière un proxy.

<!-- [common] -->

## [1.2.1] - 2021-09-28

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- doc/migration.md

<!-- [fr] -->

- doc/migration.md

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update pip dependency with security update
    - Jinja2==2.11.3
    - lxml==4.6.3
    - cryptography==3.4.8
    - psutil==5.6.6
    - Pillow==8.3.2
    - Werkzeug==0.15.3
- Script separate generate_config.sh from install_locally.sh
- Improve developer documentation
- More Docker script

<!-- [fr] -->

- Mise à jour des dépendances pip avec correctif de sécurité
    - Jinja2==2.11.3
    - lxml==4.6.3
    - cryptography==3.4.8
    - psutil==5.6.6
    - Pillow==8.3.2
    - Werkzeug==0.15.3
- Séparation du script generate_config.sh de install_locally.sh
- Amélioration de la documentation développeur
- Plus de scripts Docker

<!-- [en] -->
#### Code generator
<!-- [fr] -->
#### Code generator
<!-- [en] -->

- Improve db_servers generation code
- Improve wizard generate UI menu

<!-- [fr] -->

- Amélioration du code de génération db_servers
- Amélioration du menu UI de l'assistant de génération

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Mobile view menu item in Web interface from muk_web_theme

<!-- [fr] -->

- Élément de menu vue mobile dans l'interface Web de muk_web_theme

<!-- [common] -->

## [1.2.0] - 2021-07-21

<!-- [en] -->
**Migration note**

Because addons repository has change, config file need to be updated.

- When upgrading to version 1.2.0:
    - From docker
        - Clone project if only download docker-compose
<!-- [fr] -->
**Note de migration**

Parce que le dépôt d'addons a changé, le fichier de configuration doit être mis à jour.

- Lors de la mise à niveau vers la version 1.2.0 :
    - Depuis docker
        - Cloner le projet si vous avez seulement téléchargé docker-compose
<!-- [common] -->
            - `git init`
            - `git remote add origin https://github.com/erplibre/erplibre`
            - `git fetch`
            - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
            - `git checkout master`
            - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
<!-- [en] -->
        - Update `./docker-compose.yml` depending of difference with git.
        - Run script `make docker_exec_erplibre_gen_config`
        - Restart the docker `make docker_restart_daemon`
    - From vanilla
        - Run script `make install_dev`
        - Restart your daemon
        - Regenerate master password manually

<!-- [fr] -->
        - Mettre à jour `./docker-compose.yml` selon les différences avec git.
        - Exécuter le script `make docker_exec_erplibre_gen_config`
        - Redémarrer le docker `make docker_restart_daemon`
    - Depuis une installation vanilla
        - Exécuter le script `make install_dev`
        - Redémarrer votre daemon
        - Régénérer le mot de passe maître manuellement

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Adapt script to give an execution status
- Multilingual markdown
- Guide to use Cloudflare with DDNS
- Script to check git diff and ignore date
- Repo with ERPLibre image
- Improve git repo usage, filter repo by use case
- ERPLibre theme website of TechnoLibre
- ERPLibre website snippet
    - Basic HTML snippets
    - Snippet card
    - Snippet timelines
- Module contract_digitized_signature with contract_portal
- Module disable auto_backup
- Odoo cli db command to manipulate restoration db
- Odoo cli i18n command to generate i18n pot files

<!-- [fr] -->

- Adaptation du script pour donner un statut d'exécution
- Markdown multilingue
- Guide pour utiliser Cloudflare avec DDNS
- Script pour vérifier le diff git et ignorer la date
- Dépôt avec l'image ERPLibre
- Amélioration de l'utilisation du dépôt git, filtrer les dépôts par cas d'utilisation
- Thème de site web ERPLibre de TechnoLibre
- Snippet de site web ERPLibre
    - Snippets HTML de base
    - Snippet carte
    - Snippets chronologie
- Module contract_digitized_signature avec contract_portal
- Module disable auto_backup
- Commande CLI Odoo db pour manipuler la restauration de base de données
- Commande CLI Odoo i18n pour générer les fichiers pot i18n

<!-- [en] -->
#### Makefile
<!-- [fr] -->
#### Makefile
<!-- [en] -->

- Format code
- Code generator test
- Addons installation
- OS installation
- Restore database
- Docker execution

<!-- [fr] -->

- Formatage du code
- Test du code generator
- Installation des addons
- Installation du système d'exploitation
- Restauration de base de données
- Exécution Docker

<!-- [en] -->
#### Code generator
<!-- [fr] -->
#### Code generator
<!-- [en] -->

- Code generator for Odoo module, depending of ERPLibre
- Support map geospatial
- Support i18n
- Script to transform Python and XML to Python code writer script to regenerate themselves

<!-- [fr] -->

- Code generator pour les modules Odoo, dépendant d'ERPLibre
- Support des cartes géospatiales
- Support i18n
- Script pour transformer Python et XML en script d'écriture de code Python pour se régénérer eux-mêmes

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update Python dependency with Poetry
- Format all Python code with black
- Module auto_backup with sftp host key
- Module muk_website_branding use ERPLibre branding
- Update docs with vscode support, custom document layout, custom email template and trick to use params to share
  variable

<!-- [fr] -->

- Mise à jour des dépendances Python avec Poetry
- Formatage de tout le code Python avec black
- Module auto_backup avec clé d'hôte sftp
- Le module muk_website_branding utilise le branding ERPLibre
- Mise à jour de la documentation avec le support vscode, mise en page de document personnalisée, modèle d'email personnalisé et astuce pour utiliser les paramètres de partage
  de variables

<!-- [en] -->
#### Docker
<!-- [fr] -->
#### Docker
<!-- [en] -->

- Use buster python 3.7.7 image to remove pyenv
- Update Postgresql to support Postgis
- Support volume addons /ERPLibre/addons/addons

<!-- [fr] -->

- Utilisation de l'image buster python 3.7.7 pour supprimer pyenv
- Mise à jour de PostgreSQL pour supporter PostGIS
- Support du volume addons /ERPLibre/addons/addons

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Ubuntu installation
- Poetry installation
- Geospatial with postgis can be installed

<!-- [fr] -->

- Installation Ubuntu
- Installation de Poetry
- Le géospatial avec PostGIS peut être installé

<!-- [common] -->

## [1.1.1] - 2020-12-11

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Developer, test, migration and user documentation
- Branding ERPLibre with muk_branding
- Uninstall module from parameter Odoo
- Makefile to generate ERPLibre documentation WIP
- Docker support volume on /etc/odoo
- Docker support update database

<!-- [fr] -->

- Documentation développeur, test, migration et utilisateur
- Branding ERPLibre avec muk_branding
- Désinstallation de module depuis les paramètres Odoo
- Makefile pour générer la documentation ERPLibre (travail en cours)
- Support Docker du volume sur /etc/odoo
- Support Docker de la mise à jour de base de données

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Better documentation on how to use ERPLibre and release
- Support wkhtmltox_0.12.6-1

<!-- [fr] -->

- Meilleure documentation sur l'utilisation d'ERPLibre et les versions
- Support de wkhtmltox_0.12.6-1

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- db_backup to accept public host key on sftp
- Docker dependency
- Freeze poetry version 1.0.10

<!-- [fr] -->

- db_backup pour accepter la clé d'hôte publique sur sftp
- Dépendances Docker
- Gel de la version poetry 1.0.10

<!-- [common] -->

## [1.1.0] - 2020-09-30

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Docker
- Pyenv to manage python version
- Poetry to manage python dependencies
    - Script poetry_update to search all dependencies in addons
- Travis CI WIP
- TODO.md
- Guide to update all repositories with community
- Update manifest
    - Add missing OCA repos
    - Add medical, property management and more
    - Add cloud/saas repo

<!-- [fr] -->

- Docker
- Pyenv pour gérer les versions Python
- Poetry pour gérer les dépendances Python
    - Script poetry_update pour rechercher toutes les dépendances dans les addons
- Travis CI (travail en cours)
- TODO.md
- Guide pour mettre à jour tous les dépôts avec la communauté
- Mise à jour du manifeste
    - Ajout des dépôts OCA manquants
    - Ajout de médical, gestion immobilière et plus
    - Ajout du dépôt cloud/saas

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update to Odoo Community 12.0 and all addons
- Rename venv to .venv
- More documentation on how to use ERPLibre

<!-- [fr] -->

- Mise à jour vers Odoo Community 12.0 et tous les addons
- Renommage de venv en .venv
- Plus de documentation sur l'utilisation d'ERPLibre

<!-- [common] -->

## [1.0.1] - 2020-07-14

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Improved documentation with development and production environment
- Improved documentation with git repo
- Move default.xml manifest to root, the default location
- Support default.staged.xml to update prod with dev
- Feature to show diff between manifests or between repo of different manifests
- Update manifest
    - Muk theme in erplibre_base
    - Add draft account invoice approbation in portal
    - New module sale_fix_update_price_unit_when_update_qty
    - New module account_invoice_approbation
    - New module sale_margin_editor

<!-- [fr] -->

- Amélioration de la documentation avec l'environnement de développement et de production
- Amélioration de la documentation avec le dépôt git
- Déplacement du manifeste default.xml à la racine, l'emplacement par défaut
- Support de default.staged.xml pour mettre à jour la prod avec le dev
- Fonctionnalité pour afficher le diff entre les manifestes ou entre les dépôts de différents manifestes
- Mise à jour du manifeste
    - Thème Muk dans erplibre_base
    - Ajout du brouillon d'approbation de facture dans le portail
    - Nouveau module sale_fix_update_price_unit_when_update_qty
    - Nouveau module account_invoice_approbation
    - Nouveau module sale_margin_editor

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Production installation with git_repo

<!-- [fr] -->

- Installation de production avec git_repo

<!-- [common] -->

## [1.0.0] - 2020-07-04

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Environment of development, discovery and production with documentation and script.
- Google git-repo to support addons repository instead of using Git submodule.

<!-- [fr] -->

- Environnement de développement, découverte et production avec documentation et scripts.
- Google git-repo pour supporter le dépôt d'addons au lieu d'utiliser les sous-modules Git.

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Git submodule

<!-- [fr] -->

- Sous-modules Git

<!-- [common] -->

## [0.1.1] - 2020-04-28

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Support helpdesk supplier, helper, employee and services
- Support [SanteLibre.ca](https://santelibre.ca) with MRP, website, hr, ecommerce
- Donation module with thermometer for website
- Script to fork project and all repos in submodule to create ERPLibre

<!-- [fr] -->

- Support du helpdesk fournisseur, assistant, employé et services
- Support de [SanteLibre.ca](https://santelibre.ca) avec MRP, site web, RH, commerce en ligne
- Module de don avec thermomètre pour le site web
- Script pour forker le projet et tous les dépôts en sous-module pour créer ERPLibre

<!-- [common] -->

## [0.1.0] - 2020-04-20

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Move project from https://github.com/mathbentech/InstallScript to ERPLibre.
- Support of Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

<!-- [fr] -->

- Déplacement du projet de https://github.com/mathbentech/InstallScript vers ERPLibre.
- Support d'Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Support scrummer, project, sale, website, helpdesk and hr
- Support Nginx and improve installation

<!-- [fr] -->

- Support de scrummer, projet, vente, site web, helpdesk et RH
- Support de Nginx et amélioration de l'installation

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Support only python3.6 and python3.7, python3.8 causes error in runtime.

<!-- [fr] -->

- Support uniquement de python3.6 et python3.7, python3.8 cause des erreurs à l'exécution.

<!-- [common] -->

[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.6.0...HEAD

[1.6.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.5.0...v1.6.0

[1.5.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.4.0...v1.5.0

[1.4.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.3.0...v1.4.0

[1.3.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.2.1...v1.3.0

[1.2.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.2.0...v1.2.1

[1.2.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.1.1...v1.2.0

[1.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.1

[1.1.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.0

[1.0.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.0...v1.0.1

[1.0.0]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.1...v1.0.0

[0.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.0...v0.1.1

[0.1.0]: https://github.com/ERPLibre/ERPLibre/releases/tag/v0.1.0
