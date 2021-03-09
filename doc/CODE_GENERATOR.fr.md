# Comment générer du code

Ne jamais exécuter le générateur de code dans un environnement de production, il y a création de dépendance circulaire pouvant causer de la frustration à nettoyer tous les dommages.

```
Modules
############    ##################    ##########
# Template # -> # Code_Generator # -> # Module #
############    ##################    ##########
```

Il y a 3 types de module dans le contexte du générateur de code :
1. [A Template generates a Template or a Code_Generator.](#crer-votre-premier-code_generator)
2. Un Code_Generator génère un module.
3. Un Template lis un module pour générer un Code_Generator.

Attention pour ne pas écraser votre code, toujours commiter après une manipulation, l'utilisation du mode enable_sync_code peut effacer des données. Seul git vous sauvera!

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

Ouvrir le navigateur sur [http://localhost:8069](http://localhost:8069). Utilisateur `test` et mot de passe `test`. Une fois connecté, ouvrir sur [http://localhost:8069/web?debug=](http://localhost:8069/web?debug=) pour activer le déverminage.

Ouvrir l'application `Code Generator` et créer un `Module`. Remplir les champs requis et générer avec `Action/Generate code`.

## Préparer une BD

Ceci va détruire et créer une base de donnée nommé `code_generator`.

```bash
make db_restore_erplibre_base_db_code_generator
```

## Tester le générateur de code

Tester la génération des modules internes du générateur, créant les démos à partir de leur générateur respectif.
```bash
make test_code_generator_generation
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

Nommé votre module qui débute par `MODULE_NAME = "code_generator_"`

Pour continuer avec l'exemple, généré le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons.sh template code_generator_template_demo_website_snippet
```

Aller à la section [Créer votre premier module](#crer-votre-premier-module)

### Générer un Code_Generator_Demo

Nommé votre module qui débute par `MODULE_NAME = "code_generator_demo_"`

Désactiver la variable `enable_template_code_generator_demo`

```python
value["enable_template_code_generator_demo"] = False
```

Pour continuer avec l'exemple, généré le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

```bash
./script/addons/install_addons.sh code_generator code_generator_template_demo_website_snippet
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
./script/addons/install_addons.sh code_generator code_generator_demo_website_snippet
```

Maintenant, vous pouvez le tester! Pour info, on ne peut pas installer un module généré avec son générateur de code associé, puisqu'il y a une duplication des modèles!

Il est maintenant possible de modifier les paramètres via l'interface manuelle pour ce module, puis le regénérer en effaçant la BD. Ajouter un modèle.

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons.sh code_generator code_generator_demo_website_snippet
```

Faire la boucle d'amélioration, commiter le code pour avoir une traçabilité des changements.

Ensuite, modifier la valeur `enable_sync_template` à `True` dans le fichier template, de l'exemple `code_generator_template_demo_website_snippet`.

```python
value["enable_sync_template"] = True
```

Exécuter l'installation du template pour qu'il se synchronise sur le module généré.
```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons.sh template code_generator_template_demo_website_snippet
```

Prêt à tester, générer le module :

```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./script/addons/install_addons.sh test demo_website_snippet
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
./script/addons/install_addons.sh test demo_portal
./script/addons/install_addons.sh test code_generator_template_demo_portal
```

# Synchroniser les champs du `Code_Generator` du module

Ceci va permettre de réduire le temps de programmation d'un `Code_Generator` avec la synchronisation des champs de module avec `Template`.

On a besoin d'un `Template`, un `Code_Generator` accompagné de son module. Installer le module en premier dans une base de donnée nettoyé et installer le `Template`, ceci va générer le `Code_Generator`, utiliser `enable_sync_template` à la valeur `True`.

Exemple :

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons.sh test demo_portal
./script/addons/install_addons.sh test code_generator_template_demo_portal
```

# Tester le générateur de code

Une bonne manière de tester un générateur de code est de valider qu'il génère le même code, il ne devient pas nécessaire de tester les fonctionnalités, puisque le comportement est la génération.

Tester les générations simples :

```bash
make test_code_generator_generation
```

Tester les générations extra :

```bash
make test_code_generator_generation_extra
```
Tester les générations des templates :

```bash
make test_code_generator_template
```
