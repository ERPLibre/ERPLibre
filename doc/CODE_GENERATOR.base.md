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
1. [A Template generates a Template or a Code_Generator.](Create your first `Code_Generator`)
2. A Code_Generator generates a Module.
3. A Template reads a Module to generate a Code_Generator.

<!-- [fr] -->
1. [A Template generates a Template or a Code_Generator.](Créer votre premier `Code_Generator`)
2. Un Code_Generator génère un module.
3. Un Template lis un module pour générer un Code_Generator.

<!-- [en] -->
Warning, be careful to your code, always commit after a manipulation, because the mode enable_sync_code erase data, only the git will save you!

<!-- [fr] -->
Attention pour ne pas écraser votre code, toujours commiter après une manipulation, l'utilisation du mode enable_sync_code peut effacer des données. Seul git vous sauvera!

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

Mettre la variable "enable_template_code_generator_demo" à `False` pour créer un nouveau module de type template, sinon cela va recréer un `code_generator_demo`.

<!-- [common] -->
```python
value["enable_template_code_generator_demo"] = True
```

<!-- [en] -->
Example, to generate the module `code_generator_template_demo_website_snippet`, change value:

<!-- [fr] -->
Un example, générer le module `code_generator_template_demo_website_snippet`, changer la variable `value`:

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
make addons_install_code_generator_demo
```

<!-- [en] -->
### Generate a Code_Generator

<!-- [fr] -->
### Générer un Code_Generator

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
./install_addon.sh code_generator code_generator_template_demo_website_snippet
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
./install_addon.sh code_generator code_generator_demo_website_snippet
```

<!-- [en] -->
Now, you can test it! Note, you cannot install a generated module with is code_generator associated, because duplicated
models!

Generate your module:

<!-- [fr] -->
Maintenant, vous pouvez le tester! Pour info, on ne peut pas installer un module généré avec son générateur de code associé, puisqu'il y a une duplication des modèles!

Générer le module :

<!-- [common] -->
```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./install_addon.sh test demo_website_snippet
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
./install_addon.sh test demo_portal
./install_addon.sh test code_generator_template_demo_portal
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
./install_addon.sh test demo_portal
./install_addon.sh test code_generator_template_demo_portal
```
