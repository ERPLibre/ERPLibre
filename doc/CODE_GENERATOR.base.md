<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# How to generate code

<!-- [fr] -->
# Comment générer du code

<!-- [en] -->
Never run this on production environment, this create circular dependencies and will cause frustration to clean damage.
<!-- [fr] -->
Ne jamais exécuter le générateur de code dans un environnement de production, il y a création de dépendance circulaire pouvant causer de la frustration à nettoyer tous les dommages. D'ailleurs, il est nécessaire d'exécuter en mode développement, avec l'argument `--dev all`. 

L'objectif du générateur de code est de :
- utilisation du générateur via l'interface web;
- créer un nouveau module;
- modifier un module existant;
- exécuter les tests.

Ce générateur de code, pour ERPLibre, a tout avantage d'être sous licence AGPLv3 et nécessite d'être dans une communauté active de logiciels libres puisqu'il sera plus efficace d'accéder à du code pour l'auto-apprentissage. Le libre permet :
- (Utiliser) L'utilisation de module sans restriction;
- (Copier) Copier des modules pour faciliter leur maintenance et leur pérennité;
- (Étudier) De comprendre le comportement des fonctionnalités;
- (Modifier) Modifier un module existant pour l'améliorer et pouvoir le redistribuer à la communauté;
<!-- [common] -->

```
Modules
############    ##################    ##########
# Template # -> # Code_Generator # -> # Module #
############    ##################    ##########
```

<!-- [en] -->
1. [A Template generates a Template or a Code_Generator.](#create-your-first-code_generator)
2. A Code_Generator generates a Module.
3. A Template reads a Module to generate a Code_Generator.

<!-- [fr] -->
Il y a 3 types de module dans le contexte du générateur de code :
1. [A Template generates a Template or a Code_Generator.](#crer-votre-premier-code_generator), le chef d'orchestre qui permet de gérer plusieurs générateur de code.
2. Un Code_Generator génère un module, c'est un moule à module généré.
3. Un Template lit un module pour générer un Code_Generator.

<!-- [en] -->
Warning, be careful to your code, always commit after a manipulation, because the mode enable_sync_code erase data, only the git will save you!

<!-- [fr] -->
Attention pour ne pas écraser votre code, toujours commiter après une manipulation, l'utilisation du mode enable_sync_code peut effacer des données. Seul git vous sauvera!

<!-- [en] -->
## Manual generator with web interface

<!-- [fr] -->
## Générateur de module avec l'interface web

<!-- [en] -->
TODO

<!-- [ignore] -->
At root path of ERPLibre git project, run:

<!-- [fr] -->
Niveau intermédiaire.

Pour utiliser le générateur de code, il faut ouvrir l'interface web qui permet la configuration du logiciel à générer. Un des choix suivants :

Générateur de code de base :
<!-- [common] -->
```bash
make addons_install_code_generator_basic
make run_code_generator
```

<!-- [fr] -->
Générateur de code avec fonctionnalités avancées :
<!-- [common] -->
```bash
make addons_install_code_generator_featured
make run_code_generator
```

<!-- [fr] -->
Générateur de code avec fonctionnalités complètes :
<!-- [common] -->
```bash
make addons_install_code_generator_full
make run_code_generator
```

Ouvrir le navigateur sur [http://localhost:8069](http://localhost:8069). Utilisateur `test` et mot de passe `test`. Une fois connecté, ouvrir sur [http://localhost:8069/web?debug=](http://localhost:8069/web?debug=) pour activer le déverminage.

Ouvrir l'application `Code Generator` et créer un `Module`. Remplir les champs requis et générer avec `Action/Generate code`.

<!-- [en] -->
### Create model-view module

<!-- [fr] -->
### Créer un module modèle avec vue

<!-- [common] -->
```bash
make addons_install_code_generator_basic
make run_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Pour des références techniques, voir module :
- code_generator_template_demo_portal
- code_generator_demo_portal
- code_generator_demo_internal
- demo_portal
- demo_internal

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Technical Data», activer «Application».
- Sur l'onglet «Elements»/«Models», ajouter un modèle et sauvegarder.
- Appuyer sur le bouton «Views»
  - Appuyer «Generate»

Générer le module avec «Action/Générer code».

Tester sur :
<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

<!-- [en] -->
### Create portal module

<!-- [fr] -->
### Créer un module avec la vue portail

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_portal
make run_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Pour des références techniques, voir module :
- code_generator_template_demo_portal
- code_generator_demo_portal
- code_generator_demo_internal
- demo_portal
- demo_internal

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Technical Data», activer «Application».
- Sur l'onglet «Elements»/«Models», ajouter un modèle et sauvegarder.
- Appuyer sur le bouton «Views»
  - Désactiver «Enable all feature»
  - Dans l'onglet «Portal»
    - Activer «Enable portal feature»
  - Appuyer «Generate»

Générer le module avec «Action/Générer code».

Tester sur :
<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

<!-- [en] -->
TODO

<!-- [fr] -->
Ajouter des données dans votre nouveau module «test».

Aller sur le portail pour visualiser les données, à l'adresse `/my`.

<!-- [en] -->
### Create hook module for installation

<!-- [fr] -->
### Créer un module crochet pour l'installation

<!-- [en] -->
TODO

<!-- [fr] -->
Le crochet nommé «hook» permet d'exécuter du code en
- Pré-initialisation du module
- Post-initialisation du module
- Désinstallation du module

Pour des références techniques, voir module :
- code_generator_demo

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_hook
make run_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Hook»
  - Activer «Show post_init_hook»
  - Ajouter le code suivant dans la fenêtre qui est apparu :

<!-- [common] -->
```python
with api.Environment.manage():
    env = api.Environment(cr, SUPERUSER_ID, {})
    print("Hello World")
```

<!-- [en] -->
TODO

<!-- [fr] -->
Générer le module avec «Action/Générer code».

Tester et chercher dans la console "Hello World" :
<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test_module_test
```

<!-- [en] -->
### Create cron module

<!-- [fr] -->
### Créer un module d'exécution de code sur une plage horaire

<!-- [en] -->
TODO

<!-- [fr] -->
Permettre d'exécuter du code basé sur des séquences de temps ou des moments spécifiques à répétition.

Pour des références techniques, voir module :
- code_generator_template_demo_sysadmin_cron
- code_generator_auto_backup
- auto_backup

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_cron
make run_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Cron»
  - Ajouter un cron
    - Choisir le «Modèle» : «Contact»
    - Choisir unité de temps en «Minutes» dans «Exécuter tous les»
    - Modifier «Nombre d'appel» à -1 pour exécution sans arrêt.
    - Activer «Force nextcall» pour permettre que l'interval soit basé sur le moment d'installation du module
    - Ajouter le code :

<!-- [common] -->
```python
log("Coucou")
```

<!-- [en] -->
TODO

<!-- [fr] -->
Générer le module avec «Action/Générer code».

Tester :
<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

<!-- [en] -->
TODO

<!-- [fr] -->
Avec les outils développeur, aller regarder les logs dans l'application «Configuration»/Technique/«Structure de base de donnée»/Historisation. Des informations dans le temps apparaîtront avec le mot «Coucou».

<!-- [en] -->
### Create website snippet module

<!-- [fr] -->
### Créer un module de snippet pour le site web

<!-- [en] -->
In progress

<!-- [fr] -->
En progression, non terminé

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_website_snippet
make run_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Pour des références techniques, voir module :
- code_generator_template_demo_website_snippet
- code_generator_demo_website_snippet
- demo_website_snippet

Puis dans le repo addons/ERPLibre_erplibre_theme_addons, branche code_generator_erplibre_website_snippets
- code_generator_erplibre_website_snippets

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»

TODO Incomplet

<!-- [en] -->
### Create geoengine with Leaflet module

<!-- [fr] -->
### Créer un module de gestion de coordonnée géospatial avec Leaflet

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_website_leaflet
make run_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Pour des références techniques, voir module :
- code_generator_demo_website_leaflet
- demo_website_leaflet

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Technical Data»
  - Activer «Application»
  - Ajouter la dépendance du geo_engine «Geospatial support for System»
- Sur l'onglet «Elements»/«Models»
  - Ajouter un modèle «test»
    - Ajouter un champs de type «geo_». Le «geo_point» fonctionne bien. Si vous ajoutez plusieurs géométrie, tel que «geo_point», «geo_line» et «geo_polygon», il faut ajouter le champs «type» avec les valeurs du nom des champs choisis en option de sélection, exemple `[('geo_point', 'Geo Point'),('geo_polygon', 'Geo Polygon')]`
    - Ajouter le champs optionnel «html_text» de type «html» pour pouvoir afficher du texte dessus.
- Appuyer sur le bouton «Controllers»
  - Ajouter le modèle du module actuel, «test»
  - Appuyer «Generate»
- Appuyer sur le bouton «Views»
  - Désactiver «Enable all feature»
  - Dans l'onglet «Website»
    - Activer «Enable website leaflet feature»
    - Activer «Enable geoengine feature»
  - Appuyer «Generate»

Générer le module avec «Action/Générer code».

Tester sur :
<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

<!-- [en] -->
TODO

<!-- [fr] -->
Ajouter les permissions d'utilisation, dans l'application «Configuration», «Gérer les droits d'accès». Sur votre utilisateur, ajouter «Geoengine Admin».

Aller sur l'application «test», créer un «geo_point».

Aller sur la page du site web, ajouter le snippet «Leaflet». Chercher le point qui a été ajouté sur la carte du monde.

<!-- [en] -->
### Create theme module for website

<!-- [fr] -->
### Créer un module thème pour site web

<!-- [en] -->
TODO

<!-- [fr] -->
Pour des références techniques, voir module :
- code_generator_demo_theme_website

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_theme_website
make run_code_generator
```
<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Technical Data», activer «Website theme».
- Appuyer sur le bouton «Views»
  - Aller à l'onglet «theme_website»
    - Mettre les couleurs désirés
  - Appuyer «Generate»

Générer le module avec «Action/Générer code».

Ce module doit être installé manuellement pour l'instant.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test
./script/addons/install_addons.sh test website
make run_test
```

<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans l'interface web, Application «Configuration», «Paramètres Généraux»/«Site Web»/«Choisissez un thème». Installer le thème «TEST». Puis aller la page du site web, les couleurs sont dans «Personnaliser»/«Personnaliser le thème».

<!-- [en] -->
### Extract data to module

<!-- [fr] -->
### Extraire les données vers un module

<!-- [en] -->
TODO

<!-- [fr] -->
L'exemple est avec le helpdesk. Installer le module helpdesk_mgmt :

Pour des références techniques, voir module :
- code_generator_demo_export_helpdesk
- code_generator_demo_export_website
- demo_website_data
- demo_helpdesk_data

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator helpdesk_mgmt
make run_code_generator
```
<!-- [en] -->
TODO

<!-- [fr] -->
Créer un ticket dans l'application «Helpdesk» dans l'interface web.

Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»
- Sur l'onglet «Technical Data», activer «Only export data».
- Appuyer sur le bouton «Models»
  - Choisissez dans «Models» :
    - «helpdesk.ticket»
  - Activer «Clear field blacklisted»
  - Enlever les éléments suivant de «Fields» :
    - name
    - description
    - number
  - Appuyer «Generate»

Générer le module avec «Action/Générer code».
<!-- [common] -->
```bash
make db_restore_erplibre_base_db_test_module_test
```

<!-- [en] -->
### Migrate external database into module of migration

<!-- [fr] -->
### Migrer une base de donnée externe en module de migration

<!-- [en] -->
TODO

<!-- [fr] -->
En progression.

Pour des références techniques, voir module :
- ??

<!-- [common] -->
```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_db_servers
make run_code_generator
```
<!-- [en] -->
TODO

<!-- [fr] -->
Aller dans le module «Code generator», menu «Databases»/«Databases» et créer un connecteur vers une base de donnée.

À compléter...

<!-- [en] -->
### Migrate from website to model with PDF data

<!-- [fr] -->
### Migrer d'un site web vers un modèle de donnée avec des données format PDF

<!-- [en] -->
TODO

<!-- [fr] -->
En progression, ce n'est pas encore supporté via l'interface web.

Cette technique permet d'aller lire du Javascript sur un site web pour lire ensuite le HTML, c'est à dire la vue, et en comprendre l'information pour créer un modèle.

Pour des références techniques, voir module :
- code_generator_demo_converter_js
- business_plan_import_pdf

Attention, il faut mettre à jour les variables, dans les fichiers hook.py qui permettront d'extraire des données sur le site web à copier. Aucun exemple public n'est accessible pour le moment.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_converter_js
make db_restore_erplibre_base_db_test
./script/addons/install_addons_dev.sh test business_plan_import_pdf
```

<!-- [en] -->
## Prepare a DB

<!-- [fr] -->
## Préparer une BD

<!-- [en] -->
This will destroy and create database named `code_generator`.

<!-- [fr] -->
Ceci va détruire et créer une base de donnée nommé `code_generator`.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Pour de meilleur performance d'exécution, réduire la quantité de «repo addons» permet d'accélérer l'installation, exécuter :

<!-- [common] -->
```bash
make config_gen_code_generator
```

<!-- [en] -->
TODO

<!-- [fr] -->
Pour revenir à la configuration normal, en production, exécuter :

<!-- [common] -->
```bash
make config_gen_all
```

<!-- [en] -->
## Create your first `Code_Generator`

<!-- [fr] -->
## Créer votre premier `Code_Generator`

<!-- [en] -->
Edit [Code Generator Demo](./../addons/TechnoLibre_odoo-code-generator/code_generator_demo/hooks.py) and update `# TODO HUMAN:`

<!-- [fr] -->
Modifier [Code Generator Demo](./../addons/TechnoLibre_odoo-code-generator/code_generator_demo/hooks.py) et mettre à jour `# TODO HUMAN:`

<!-- [en] -->
### Generate a `Template`

<!-- [fr] -->
### Générer un `Template`

<!-- [en] -->
By default, `code_generator_demo` generate itself, `code_generator_demo`.

Name your module begin with `MODULE_NAME = "code_generator_template_"`

The value "enable_template_code_generator_demo" at `False` to create a new template module, else this will recreate `code_generator_demo`.

<!-- [fr] -->
Par défaut, installer le module code_generator_demo va générer le module `code_generator_demo`.

Nommer votre module en commençant par `MODULE_NAME = "code_generator_template_"`

<!-- [en] -->
Example, to generate the module `code_generator_template_demo_website_snippet`, change value:

<!-- [fr] -->
Un exemple, générer le module `code_generator_template_demo_website_snippet`, changer la variable `value`:

<!-- [common] -->
```python
MODULE_NAME = "code_generator_template_demo_website_snippet"
[...]
value["enable_template_website_snippet_view"] = True
[...]
lst_depend = [
    "code_generator",
    "code_generator_website_snippet",
]
```

<!-- [en] -->
Generate new module, this will overwrite `code_generator_template_demo_website_snippet`:

<!-- [fr] -->
Générer un nouveau module, ceci va écraser `code_generator_template_demo_website_snippet` :

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
make addons_install_code_generator_demo
```

<!-- [en] -->
### Generate a Code_Generator (continue template)

<!-- [fr] -->
### Générer un Code_Generator (suite de template)

<!-- [en] -->
Name your module begin with `MODULE_NAME = "code_generator_"`

<!-- [fr] -->
Au besoin, renommé votre module qui débute par `MODULE_NAME = "code_generator_"`

<!-- [en] -->
Continue the example, you generated the template `code_generator_template_demo_website_snippet`, this will overwrite `code_generator_demo_website_snippet`:

<!-- [fr] -->
Pour continuer avec l'exemple, généré le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet
```

<!-- [en] -->
Go to section [Create your first module](#create-your-first-module)

<!-- [fr] -->
Aller à la section [Créer votre premier module](#crer-votre-premier-module)

<!-- [en] -->
### Generate a Code_Generator_Demo

<!-- [fr] -->
### Générer un Code_Generator_Demo

<!-- [ignore] -->
TODO validate this

<!-- [en] -->
Name your module begin with `MODULE_NAME = "code_generator_demo_"`

Disable `enable_template_code_generator_demo`

<!-- [fr] -->
Nommé votre module qui débute par `MODULE_NAME = "code_generator_demo_"`

Désactiver la variable `enable_template_code_generator_demo`

<!-- [common] -->
```python
value["enable_template_code_generator_demo"] = False
```

<!-- [en] -->
Continue the example, you generated the template `code_generator_template_demo_website_snippet`, this will overwrite `code_generator_demo_website_snippet`:

<!-- [fr] -->
Pour continuer avec l'exemple, généré le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

<!-- [common] -->
```bash
./script/addons/install_addons_dev.sh code_generator code_generator_template_demo_website_snippet
```

<!-- [en] -->
## Create your first Module

<!-- [fr] -->
## Créer votre premier module

<!-- [en] -->
Continue example of code_generator_demo_website_snippet to generate your first module. Update next value:

<!-- [fr] -->
Continuer avec l'exemple du `code_generator_demo_website_snippet` pour générer votre premier module. Mettre à jour les valeurs suivantes :

<!-- [common] -->
```python
"application": True,
"category_id": env.ref("base.module_category_website").id,
[...]
# Add dependencies
lst_depend = [
    "website",
]
```

<!-- [en] -->
Generate your module:

<!-- [fr] -->
Générer votre module :

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
```

<!-- [en] -->
Now, you can test it! Note, you cannot install a generated module with is code_generator associated, because duplicated
models!

<!-- [fr] -->
Maintenant, vous pouvez le tester! Pour info, on ne peut pas installer un module généré avec son générateur de code associé, puisqu'il y a une duplication des modèles!

<!-- [en] -->

<!-- [fr] -->
Il est maintenant possible de modifier les paramètres via l'interface manuelle pour ce module, puis le regénérer en effaçant la BD. Ajouter un modèle et une vue.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
```

<!-- [en] -->

<!-- [fr] -->
Faire la boucle d'amélioration, commiter le code pour avoir une traçabilité des changements.

Ensuite, modifier la valeur `enable_sync_template` à `True`, `enable_template_wizard_view` à `True`, `template_model_name` avec un modèle existant, dans le fichier template, de l'exemple `code_generator_template_demo_website_snippet`.

<!-- [common] -->
```python
value["enable_sync_template"] = True
value["enable_template_wizard_view"] = True
value["template_model_name"] = "test;test2"
```

<!-- [en] -->
TODO

<!-- [fr] -->
Exécuter l'installation du template pour qu'il se synchronise sur le module généré.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons_dev.sh template demo_website_snippet
./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet
```

<!-- [en] -->
Ready to test, generate your module:

<!-- [fr] -->
Prêt à tester, générer le module :

<!-- [common] -->
```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./script/addons/install_addons_dev.sh test demo_website_snippet
```

<!-- [en] -->
# How to generate i18n translation

<!-- [fr] -->
# Comment générer les traductions i18n

<!-- [en] -->
You need a template and a module. Be sure you have this line in template:

<!-- [fr] -->
Vous avez besoin d'un template et d'un module. Soyez certain que vous avez cette ligne dans le template :

<!-- [common] -->
```python
new_module_path = os.path.join(path_module_generate, new_module_name)
code_generator_writer.set_module_translator(new_module_name, new_module_path)
```

<!-- [en] -->
First, install the module, example `demo_portal`, and after the template, example `code_generator_template_demo_portal`.

<!-- [fr] -->
Premièrement, installer le module, par exemple `demo_portal`, et ensuite le template, par exemple `code_generator_template_demo_portal`.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh test demo_portal
./script/addons/install_addons_dev.sh test code_generator_template_demo_portal
```

<!-- [en] -->
# Sync Code_Generator fields from Module

<!-- [fr] -->
# Synchroniser les champs du `Code_Generator` du module

<!-- [en] -->
This reduce time of programming a `Code_Generator` with sync module field with `Template`.

You need a `Template`, a `Code_Generator` with his `Module`. Install the `Module` first in clean database and install `Template`,
this will generate the `Code_Generator`, use `enable_sync_template` at True.

Example:

<!-- [fr] -->
Ceci va permettre de réduire le temps de programmation d'un `Code_Generator` avec la synchronisation des champs de module avec `Template`.

On a besoin d'un `Template`, un `Code_Generator` accompagné de son module. Installer le module en premier dans une base de donnée nettoyé et installer le `Template`, ceci va générer le `Code_Generator`, utiliser `enable_sync_template` à la valeur `True`.

Exemple :

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh test demo_portal
./script/addons/install_addons_dev.sh test code_generator_template_demo_portal
```

<!-- [en] -->
# Test the code generator

<!-- [fr] -->
# Tester le générateur de code

<!-- [en] -->
TODO

<!-- [fr] -->
Une bonne manière de tester un générateur de code est de valider qu'il génère le même code, il ne devient pas nécessaire de tester les fonctionnalités, puisque le comportement est la génération.

<!-- [common] -->
```bash
make test
```

<!-- [en] -->
TODO

<!-- [fr] -->
Tester les générations simples :

<!-- [common] -->
```bash
make test_code_generator_generation
```

<!-- [en] -->
TODO

<!-- [fr] -->
Tester les générations extra :

<!-- [common] -->
```bash
make test_code_generator_generation_extra
```
<!-- [en] -->
TODO

<!-- [fr] -->
Tester les générations des templates :

<!-- [common] -->
```bash
make test_code_generator_template
```
