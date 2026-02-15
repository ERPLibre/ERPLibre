
# Comment générer du code

Ne jamais exécuter le générateur de code dans un environnement de production, il y a création de dépendances circulaires pouvant causer de la frustration à nettoyer tous les dommages. D'ailleurs, il est nécessaire d'exécuter en mode développement, avec l'argument `--dev cg`.

L'objectif du générateur de code est de :
- utiliser le générateur via l'interface web;
- créer un nouveau module;
- modifier un module existant;
- exécuter les tests.

Ce générateur de code, pour ERPLibre, a tout avantage d'être sous licence AGPLv3 et nécessite d'être dans une communauté active de logiciels libres puisqu'il sera plus efficace d'accéder à du code pour l'auto-apprentissage. Le libre permet :
- (Utiliser) L'utilisation de module sans restriction;
- (Copier) Copier des modules pour faciliter leur maintenance et leur pérennité;
- (Étudier) De comprendre le comportement des fonctionnalités;
- (Modifier) Modifier un module existant pour l'améliorer et devoir le redistribuer à la communauté;

```
Modules
############    ##################    ##########
# Template # -> # Code_Generator # -> # Module #
############    ##################    ##########
```

Il y a 3 types de modules dans le contexte du générateur de code :
1. [A Template generates a Template or a Code_Generator.](#crer-votre-premier-code_generator), le chef d'orchestre qui permet de gérer plusieurs générateurs de code.
2. Un Code_Generator génère un module, c'est un moule à module généré.
3. Un Template lit un module pour générer un Code_Generator.

Attention pour ne pas écraser votre code, toujours commiter après une manipulation, l'utilisation du mode enable_sync_code peut effacer des données. Seul Git vous sauvera!

## Générateur de module avec l'interface web

Niveau intermédiaire.

Pour utiliser le générateur de code, il faut ouvrir l'interface web qui permet la configuration du logiciel à générer. Un des choix suivants :

Générateur de code de base :
```bash
make addons_install_code_generator_basic
make run_code_generator
```

Générateur de code avec fonctionnalités avancées :
```bash
make addons_install_code_generator_featured
make run_code_generator
```

Générateur de code avec fonctionnalités complètes :
```bash
make addons_install_code_generator_full
make run_code_generator
```

Ouvrir le navigateur sur [http://localhost:8069](http://localhost:8069). Utilisateur `admin` et mot de passe `admin`. Une fois connecté, ouvrir sur [http://localhost:8069/web?debug=](http://localhost:8069/web?debug=) pour activer le mode déverminage.

Ouvrir l'application `Code Generator` et créer un `Module`. Remplir les champs requis et générer avec `Action/Generate code`.

### Créer un module modèle avec vue

```bash
make addons_install_code_generator_basic
make run_code_generator
```

Pour des références techniques, voir modules :
- code_generator_template_demo_portal
- code_generator_demo_portal
- code_generator_demo_internal
- demo_portal
- demo_internal

Aller dans le module «Code generator» et créer un module «test»;
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Technical Data», activer «Application»;
- Sur l'onglet «Elements»/«Models», ajouter un modèle et sauvegarder;
- Appuyer sur le bouton «Views»
  - Appuyer «Generate».

Générer le module avec «Action/Générer code».

Tester sur :
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

### Créer un module avec la vue portail

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_portal
make run_code_generator
```

Pour des références techniques, voir modules :
- code_generator_template_demo_portal
- code_generator_demo_portal
- code_generator_demo_internal
- demo_portal
- demo_internal

Aller dans le module «Code generator» et créer un module «test»;
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Technical Data», activer «Application»;
- Sur l'onglet «Elements»/«Models», ajouter un modèle et sauvegarder;
- Appuyer sur le bouton «Views»
  - Désactiver «Enable all feature»
  - Dans l'onglet «Portal»
    - Activer «Enable portal feature»
  - Appuyer «Generate».

Générer le module avec «Action/Générer code».

Tester sur :
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

Ajouter des données dans votre nouveau module «test».

Aller sur le portail pour visualiser les données, à l'adresse `/my`.

### Créer un module crochet pour l'installation

Le crochet nommé «hook» permet d'exécuter du code en:
- Pré-initialisation du module;
- Post-initialisation du module;
- Désinstallation du module.

Pour des références techniques, voir module :
- code_generator_demo

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_hook
make run_code_generator
```

Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Hook»:
  - Activer «Show post_init_hook»
  - Ajouter le code suivant dans la fenêtre qui est apparue :

```python
with api.Environment.manage():
    env = api.Environment(cr, SUPERUSER_ID, {})
    print("Hello World")
```

Générer le module avec «Action/Générer code».

Tester et chercher dans la console "Hello World" :
```bash
make db_restore_erplibre_base_db_test_module_test
```

### Créer un module d'exécution de code sur une plage horaire

Permettre d'exécuter du code basé sur des séquences de temps ou des moments spécifiques à répétition.

Pour des références techniques, voir module :
- code_generator_template_demo_sysadmin_cron;
- code_generator_auto_backup;
- auto_backup.

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_cron
make run_code_generator
```

Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Cron»:
  - Ajouter un cron
    - Choisir le «Modèle» : «Contact»;
    - Choisir unité de temps en «Minutes» dans «Exécuter tous les»;
    - Modifier «Nombre d'appel» à -1 pour exécution sans arrêt;
    - Activer «Force nextcall» pour permettre que l'interval soit basé sur le moment d'installation du module.
    - Ajouter le code :

```python
log("Coucou")
```

Générer le module avec «Action/Générer code».

Tester :
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

Avec les outils développeur, aller regarder les logs dans l'application «Configuration»/Technique/«Structure de base de données»/Historisation. Des informations dans le temps apparaîtront avec le mot «Coucou».

### Créer un module de snippet pour le site web

En progression, non terminé

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_website_snippet
make run_code_generator
```

Pour des références techniques, voir module :
- code_generator_template_demo_website_snippet;
- code_generator_demo_website_snippet;
- demo_website_snippet.

Puis dans le repo addons/ERPLibre_erplibre_theme_addons, branche code_generator_erplibre_website_snippets
- code_generator_erplibre_website_snippets

Aller dans le module «Code generator» et créer un module «test».
- Sur l'onglet «Information», activer «Enable Sync Code»

TODO Incomplet

### Créer un module de gestion de coordonnées géospatiales avec Leaflet

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_website_leaflet
make run_code_generator
```

Pour des références techniques, voir module :
- code_generator_demo_website_leaflet;
- demo_website_leaflet.

Aller dans le module «Code generator» et créer un module «test»:
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Technical Data»:
  - Activer «Application»;
  - Ajouter la dépendance du geo_engine «Geospatial support for System»;
- Sur l'onglet «Elements»/«Models»:
  - Ajouter un modèle «test»;
    - Ajouter un champs de type «geo_». Le «geo_point» fonctionne bien. Si vous ajoutez plusieurs géométries, telles que «geo_point», «geo_line» et «geo_polygon», il faut ajouter le champs nommé «type» au type sélection avec les valeurs du nom des champs choisis en option de sélection, exemple `[('geo_point', 'Geo Point'),('geo_polygon', 'Geo Polygon')]`
    - Ajouter le champs optionnel «html_text» de type «html» pour pouvoir afficher du texte dedans.
- Appuyer sur le bouton «Controllers»:
  - Ajouter le modèle du module actuel, «test»;
  - Appuyer «Generate».
- Appuyer sur le bouton «Views»:
  - Désactiver «Enable all feature»;
  - Dans l'onglet «Website»:
    - Activer «Enable website leaflet feature»;
    - Activer «Enable geoengine feature»;
  - Appuyer «Generate».

Générer le module avec «Action/Générer code».

Tester sur :
```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

Ajouter les permissions d'utilisation, dans l'application «Configuration», «Gérer les droits d'accès». Sur votre utilisateur, ajouter «Geoengine Admin».

Aller sur l'application «test», créer un «geo_point».

Aller sur la page du site web, ajouter le snippet «Leaflet». Chercher le point qui a été ajouté sur la carte du monde.

### Créer un module thème pour site web

Pour des références techniques, voir module :
- code_generator_demo_theme_website.

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_theme_website
make run_code_generator
```
Aller dans le module «Code generator» et créer un module «theme_test»:
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Technical Data», activer «Website theme»;
- Appuyer sur le bouton «Views»:
  - Aller à l'onglet «theme_website»:
    - Mettre les couleurs désirés;
  - Appuyer «Generate».

Générer le module avec «Action/Générer code».

Ce module doit être installé manuellement pour l'instant.

```bash
make db_restore_erplibre_base_db_test
./script/addons/install_addons.sh test website
make run_test
```

Aller dans l'interface web, Application «Configuration», «Paramètres Généraux»/«Site Web»/«Choisissez un thème». Installer le thème «TEST», puis aller la page du site web, les couleurs sont dans «Personnaliser»/«Personnaliser le thème».

### Extraire les données vers un module

L'exemple est construit avec le helpdesk. Installer le module helpdesk_mgmt :

Pour des références techniques, voir module :
- code_generator_demo_export_helpdesk;
- code_generator_demo_export_website;
- demo_website_data;
- demo_helpdesk_data.

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator helpdesk_mgmt
make run_code_generator
```
Créer un ticket dans l'application «Helpdesk» dans l'interface web.

Aller dans le module «Code generator» et créer un module «test»:
- Sur l'onglet «Information», activer «Enable Sync Code»;
- Sur l'onglet «Technical Data», activer «Only export data»;
- Appuyer sur le bouton «Models»:
  - Choisissez dans «Models» :
    - «helpdesk.ticket»;
  - Activer «Clear field blacklisted»;
  - Enlever les éléments suivants de «Fields» :
    - name;
    - description;
    - number;
  - Appuyer «Generate».

Générer le module avec «Action/Générer code».
```bash
make db_restore_erplibre_base_db_test_module_test
```

### Exporter un site web vers un module

Cette technique a été testé sans thème d'installé.

Ce qui est exporté : Les pages, les fichiers attachés et les fichiers CSS.
Ce qui n'est pas exporté à notre connaissance : Les menus, les fichiers XML autres.

À propos des fichiers attachés, ils sont importés et associés à un xml_id. Les doublons sont enlevés et les noms
duppliqués sont gérés. Les URL sont réécrites dans chaque page.

À propos des fichiers CSS, pour modifier les couleurs sans avoir de thème, aller en mode debug assets, dans le website
builder, activé `Inclure tous les fichiers SCSS`. Vous pourrez ainsi modifier les fichiers `user_color_palette`
et `user_theme_color_palette`.

Exemple pour `/website/static/src/scss/options/colors/user_color_palette.scss` :

```scss
$o-user-color-palette: map-merge($o-user-color-palette, o-map-omit((
        'menu': #ffffff,
  // -- hook --
)));
```

Exemple pour `/website/static/src/scss/options/colors/user_theme_color_palette.scss` :

```scss
$o-user-theme-color-palette: map-merge($o-user-theme-color-palette, o-map-omit((
        'alpha': #ff956b,
        'beta': null,
        'gamma': null,
        'delta': null,
        'epsilon': #ffffff,
  // -- hook --
)));
```

Plus d'exemple des variables dans le
fichier `addons/TechnoLibre_odoo-code-generator-template/theme_website_demo_code_generator/static/src/scss/primary_variables.scss`

Une fois qu'on passe en module, il n'est plus possible d'utiliser adéquatement le `website_builder`, puisqu'une mise à
jour effacerait toutes les modifications sur le design. Il faut ainsi toujours mettre à jour le module et faire des
mises à jour sur le design. La stratégie est alors de migrer le design dans un module thème.

#### Méthode 1 (fonctionnel pour les fichiers attachés et pages, non fonctionnel pour les CSS)

Cette méthode permet de voir tous les fichiers importés, mais il ne nécessite pas de transformation de la BD.

Modifier le module `code_generator_demo_export_website` pour décider du nouveau module à créer.

Suggestion, faites un clone de votre BD de production avant de l'exporter pour ne pas l'affecter, l'exportation modifie
des informations dans la base de données.

Le résultat généré montre les fichiers modifiés, mais il doit être adapté, surement être transformé en thème.

Supposons que le nom de votre BD est `test_website` :

```bash
./script/addons/install_addons_dev.sh test_website code_generator_demo_export_website
```

#### Méthode 2 (fonctionnel pour les CSS, fichiers attachés et pages)

Cette méthode nécessite la transformation de la BD, elle remplace ensuite les fichiers d'origine dans le website
builder.

Modifier le module `code_generator_demo_export_website_attachments` pour décider du nouveau module à créer.

Suggestion, faites un clone de votre BD de production avant de l'exporter pour ne pas l'affecter, l'exportation modifie
des informations dans la base de données.

Supposons que le nom de votre BD est `test_website` :

```bash
./odoo_bin.sh db --backup --database test_website --restore_image test_website_backup
./script/database/db_restore.py --database test_website_2 --image test_website_backup.zip --clean_cache
```

Un fichier temporaire `./image_db/test_website_backup.zip` a été créé, vous pouvez aller l'effacer.

Maintenant, modifier chaques fichiers manuellements de la liste désiré à importer (comme ajouter un espace à la fin du
fichier, le formatage va l'effacer) et exécuter :

```bash
./script/addons/install_addons_dev.sh test_website_2 code_generator_demo_export_website_attachments
```

### Migrer une base de données externe en module de migration

En progression.

Pour des références techniques, voir module :
- ??

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_db_servers
make run_code_generator
```
Aller dans le module «Code generator», menu «Databases»/«Databases» et créer un connecteur vers une base de données.

À compléter...

### Migrer d'un site web vers un modèle de données avec des données format PDF

En progression, ce n'est pas encore supporté via l'interface web.

Cette technique permet d'aller lire du Javascript sur un site web pour lire ensuite le HTML, c'est-à-dire la vue, et en comprendre l'information, pour créer un modèle.

Pour des références techniques, voir module :
- code_generator_demo_converter_js;
- business_plan_import_pdf.

Attention, il faut mettre à jour les variables, dans les fichiers hook.py, qui permettront d'extraire des données sur le site web à copier. Aucun exemple public n'est accessible pour le moment.

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_converter_js
make db_restore_erplibre_base_db_test
./script/addons/install_addons_dev.sh test business_plan_import_pdf
```

## Préparer une BD

Ceci va détruire et créer une base de données nommée `code_generator`.

```bash
make db_restore_erplibre_base_db_code_generator
```

Pour de meilleures performances d'exécution, réduire la quantité de «repo addons» qui permet d'accélérer l'installation, exécuter :

```bash
make config_gen_code_generator
```

Pour revenir à la configuration normale, en production, exécuter :

```bash
make config_gen_all
```

# Créer un générateur de code

Le script suivant sert à démarrer projet avec le générateur de code en appuie.

```bash
./script/code_generator/new_project.py -d CHEMIN -m NOM_DU_MODULE
```

## Créer votre premier `Code_Generator`

Modifier [Code Generator Demo](./../addons/TechnoLibre_odoo-code-generator/code_generator_demo/hooks.py) et mettre à jour `# TODO HUMAN:`

### Générer un `Template`

Par défaut, installer le module code_generator_demo va générer le module `code_generator_demo`.

Nommer votre module en commençant par `MODULE_NAME = "code_generator_template_"`

Un exemple, générer le module `code_generator_template_demo_website_snippet`, changer la variable `value`:

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

Générer un nouveau module, ceci va écraser `code_generator_template_demo_website_snippet` :

```bash
make db_restore_erplibre_base_db_code_generator
make addons_install_code_generator_demo
```

### Générer un Code_Generator (suite de template)

Au besoin, renommer votre module qui débute par `MODULE_NAME = "code_generator_"`

Pour continuer avec l'exemple, généré le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet
```

Aller à la section [Créer votre premier module](#crer-votre-premier-module)

### Générer un Code_Generator_Demo

Nommer votre module qui débute par `MODULE_NAME = "code_generator_demo_"`

Désactiver la variable `enable_template_code_generator_demo`

```python
value["enable_template_code_generator_demo"] = False
```

Pour continuer avec l'exemple, générez le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

```bash
./script/addons/install_addons_dev.sh code_generator code_generator_template_demo_website_snippet
```

## Créer votre premier module

Continuer avec l'exemple du `code_generator_demo_website_snippet` pour générer votre premier module. Mettre à jour les valeurs suivantes :

```python
"application": True,
"category_id": env.ref("base.module_category_website").id,
[...]
# Add dependencies
lst_depend = [
    "website",
]
```

Générer votre module :

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
```

Maintenant, vous pouvez le tester! Pour info, on ne peut pas installer un module généré avec son générateur de code associé, puisqu'il y a une duplication des modèles!

Il est maintenant possible de modifier les paramètres via l'interface manuelle pour ce module, puis le regénérer en effaçant la BD. Ajouter un modèle et une vue.

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
```

Faire la boucle d'amélioration, commiter le code pour avoir une traçabilité des changements.

Ensuite, modifier la valeur `enable_sync_template` à `True`, `enable_template_wizard_view` à `True`, `template_model_name` avec un modèle existant, dans le fichier template, de l'exemple `code_generator_template_demo_website_snippet`.

```python
value["enable_sync_template"] = True
value["enable_template_wizard_view"] = True
value["template_model_name"] = "test;test2"
```

Exécuter l'installation du template pour qu'il se synchronise avec le module généré.

```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons_dev.sh template demo_website_snippet
./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet
```

Prêt à tester, générer le module :

```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./script/addons/install_addons_dev.sh test demo_website_snippet
```

# Comment générer les traductions i18n

Vous avez besoin d'un template et d'un module. Soyez certain que vous avez cette ligne dans le template :

```python
new_module_path = os.path.join(path_module_generate, new_module_name)
code_generator_writer.set_module_translator(new_module_name, new_module_path)
```

Premièrement, installer le module, par exemple `demo_portal`, et ensuite le template, par exemple `code_generator_template_demo_portal`.

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh test demo_portal
./script/addons/install_addons_dev.sh test code_generator_template_demo_portal
```

# Synchroniser les champs du `Code_Generator` du module

Ceci va permettre de réduire le temps de programmation d'un `Code_Generator` avec la synchronisation des champs de module avec `Template`.

On a besoin d'un `Template`, un `Code_Generator` accompagné de son module. Installer le module en premier dans une base de données nettoyée et installer le `Template`, ceci va générer le `Code_Generator`, utiliser `enable_sync_template` à la valeur `True`.

Exemple :

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh test demo_portal
./script/addons/install_addons_dev.sh test code_generator_template_demo_portal
```

# Tester le générateur de code

Une bonne manière de tester un générateur de code est de valider qu'il génère le même code, il ne devient pas nécessaire de tester les fonctionnalités, puisque le comportement est la génération.

```bash
make test
```

Tester les générations simples :

```bash
make test_code_generator_generation
```

Tester les générations extras :

```bash
make test_code_generator_generation_extra
```
Tester les générations des templates :

```bash
make test_code_generator_template
```