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
Ne jamais exécuter le générateur de code dans un environnement de production, il y a création de dépendance circulaire pouvant causer de la frustration à nettoyer tous les dommages.
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
1. [A Template generates a Template or a Code_Generator.](#crer-votre-premier-code_generator)
2. Un Code_Generator génère un module.
3. Un Template lis un module pour générer un Code_Generator.

<!-- [en] -->
Warning, be careful to your code, always commit after a manipulation, because the mode enable_sync_code erase data, only the git will save you!

<!-- [fr] -->
Attention pour ne pas écraser votre code, toujours commiter après une manipulation, l'utilisation du mode enable_sync_code peut effacer des données. Seul git vous sauvera!

<!-- [ignore] -->
TODO
Il y a 4 objectifs sur le générateur :
+ utilisation du générateur via l'interface web
+ créer un nouveau module,
+ modifier un module existant
+ exécuter les tests.

test :
- code generator
- code generator extra (externe au repo template)
- template
- création d'un nouveau module direct ou chaine complète
  - tester chaque étape de la création
- i18n (définir les différents cas)

Suggestion de réduire les config avec make config_ pour les tests.

TODO expliquer les modules/fonctionnalités actuellements supportés. portail WIP, snippet website WIP, cron, web vue tree+form, geoengine WIP, theme website, hook, db_servers WIP, exportation de donnée en module
TODO expliquer objectif des 4 libertés
TODO rechanger les termes pour : orcherstre + moule + module

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
## Test code generator

<!-- [fr] -->
## Tester le générateur de code

<!-- [en] -->
TODO

<!-- [fr] -->
Tester la génération des modules internes du générateur, créant les démos à partir de leur générateur respectif.
```bash
make test_code_generator_generation
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
Nommé votre module qui débute par `MODULE_NAME = "code_generator_"`

<!-- [en] -->
Continue the example, you generated the template `code_generator_template_demo_website_snippet`, this will overwrite `code_generator_demo_website_snippet`:

<!-- [fr] -->
Pour continuer avec l'exemple, généré le template `code_generator_template_demo_website_snippet`, ceci va écraser `code_generator_demo_website_snippet`:

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons.sh template code_generator_template_demo_website_snippet
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
./script/addons/install_addons.sh code_generator code_generator_template_demo_website_snippet
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
./script/addons/install_addons.sh code_generator code_generator_demo_website_snippet
```

<!-- [en] -->
Now, you can test it! Note, you cannot install a generated module with is code_generator associated, because duplicated
models!

<!-- [fr] -->
Maintenant, vous pouvez le tester! Pour info, on ne peut pas installer un module généré avec son générateur de code associé, puisqu'il y a une duplication des modèles!

<!-- [en] -->

<!-- [fr] -->
Il est maintenant possible de modifier les paramètres via l'interface manuelle pour ce module, puis le regénérer en effaçant la BD. Ajouter un modèle.

<!-- [common] -->
```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons.sh code_generator code_generator_demo_website_snippet
```

<!-- [en] -->

<!-- [fr] -->
Faire la boucle d'amélioration, commiter le code pour avoir une traçabilité des changements.

Ensuite, modifier la valeur `enable_sync_template` à `True` dans le fichier template, de l'exemple `code_generator_template_demo_website_snippet`.

<!-- [common] -->
```python
value["enable_sync_template"] = True
```

<!-- [en] -->

<!-- [fr] -->
Exécuter l'installation du template pour qu'il se synchronise sur le module généré.
```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons.sh template code_generator_template_demo_website_snippet
```

<!-- [en] -->
Ready to test, generate your module:

<!-- [fr] -->
Prêt à tester, générer le module :

<!-- [common] -->
```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./script/addons/install_addons.sh test demo_website_snippet
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
./script/addons/install_addons.sh test demo_portal
./script/addons/install_addons.sh test code_generator_template_demo_portal
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
./script/addons/install_addons.sh test demo_portal
./script/addons/install_addons.sh test code_generator_template_demo_portal
```

<!-- [en] -->
# Test the code generator

<!-- [fr] -->
# Tester le générateur de code

<!-- [en] -->
TODO

<!-- [fr] -->
Une bonne manière de tester un générateur de code est de valider qu'il génère le même code, il ne devient pas nécessaire de tester les fonctionnalités, puisque le comportement est la génération.

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
