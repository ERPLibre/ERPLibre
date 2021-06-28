# How to generate code

Never run this on production environment, this create circular dependencies and will cause frustration to clean damage.

```
Modules
############    ##################    ##########
# Template # -> # Code_Generator # -> # Module #
############    ##################    ##########
```

1. [A Template generates a Template or a Code_Generator.](#create-your-first-code_generator)
2. A Code_Generator generates a Module.
3. A Template reads a Module to generate a Code_Generator.

Warning, be careful to your code, always commit after a manipulation, because the mode enable_sync_code erase data, only the git will save you!

## Manual generator with web interface

TODO

```bash
make addons_install_code_generator_basic
make run_code_generator
```

```bash
make addons_install_code_generator_featured
make run_code_generator
```

```bash
make addons_install_code_generator_full
make run_code_generator
```

Ouvrir le navigateur sur [http://localhost:8069](http://localhost:8069). Utilisateur `test` et mot de passe `test`. Une fois connecté, ouvrir sur [http://localhost:8069/web?debug=](http://localhost:8069/web?debug=) pour activer le déverminage.

Ouvrir l'application `Code Generator` et créer un `Module`. Remplir les champs requis et générer avec `Action/Generate code`.

### Create model-view module

```bash
make addons_install_code_generator_basic
make run_code_generator
```

TODO

TODO

```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

### Create portal module

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_portal
make run_code_generator
```

TODO

TODO

```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

TODO

### Create hook module for installation

TODO

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_hook
make run_code_generator
```

TODO

```python
with api.Environment.manage():
    env = api.Environment(cr, SUPERUSER_ID, {})
    print("Hello World")
```

TODO

```bash
make db_restore_erplibre_base_db_test_module_test
```

### Create cron module

TODO

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_cron
make run_code_generator
```

TODO

```python
log("Coucou")
```

TODO

```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

TODO

### Create website snippet module

In progress

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_website_snippet
make run_code_generator
```

TODO

TODO

### Create geoengine with Leaflet module

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_website_leaflet
make run_code_generator
```

TODO

TODO

```bash
make db_restore_erplibre_base_db_test_module_test
make run_test
```

TODO

### Create theme module for website

TODO

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_theme_website
make run_code_generator
```
TODO

```bash
make db_restore_erplibre_base_db_test
./script/addons/install_addons.sh test website
make run_test
```

TODO

### Extract data to module

TODO

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator helpdesk_mgmt
make run_code_generator
```
TODO

```bash
make db_restore_erplibre_base_db_test_module_test
```

### Migrate external database into module of migration

TODO

```bash
make addons_install_code_generator_basic
./script/addons/install_addons.sh code_generator code_generator_db_servers
make run_code_generator
```
TODO

### Migrate from website to model with PDF data

TODO

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_converter_js
make db_restore_erplibre_base_db_test
./script/addons/install_addons_dev.sh test business_plan_import_pdf
```

## Prepare a DB

This will destroy and create database named `code_generator`.

```bash
make db_restore_erplibre_base_db_code_generator
```

TODO

```bash
make config_gen_code_generator
```

TODO

```bash
make config_gen_all
```

## Create your first `Code_Generator`

Edit [Code Generator Demo](./../addons/TechnoLibre_odoo-code-generator/code_generator_demo/hooks.py) and update `# TODO HUMAN:`

### Generate a `Template`

By default, `code_generator_demo` generate itself, `code_generator_demo`.

Name your module begin with `MODULE_NAME = "code_generator_template_"`

The value "enable_template_code_generator_demo" at `False` to create a new template module, else this will recreate `code_generator_demo`.

Example, to generate the module `code_generator_template_demo_website_snippet`, change value:

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

Generate new module, this will overwrite `code_generator_template_demo_website_snippet`:

```bash
make db_restore_erplibre_base_db_code_generator
make addons_install_code_generator_demo
```

### Generate a Code_Generator (continue template)

Name your module begin with `MODULE_NAME = "code_generator_"`

Continue the example, you generated the template `code_generator_template_demo_website_snippet`, this will overwrite `code_generator_demo_website_snippet`:

```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet
```

Go to section [Create your first module](#create-your-first-module)

### Generate a Code_Generator_Demo

Name your module begin with `MODULE_NAME = "code_generator_demo_"`

Disable `enable_template_code_generator_demo`

```python
value["enable_template_code_generator_demo"] = False
```

Continue the example, you generated the template `code_generator_template_demo_website_snippet`, this will overwrite `code_generator_demo_website_snippet`:

```bash
./script/addons/install_addons_dev.sh code_generator code_generator_template_demo_website_snippet
```

## Create your first Module

Continue example of code_generator_demo_website_snippet to generate your first module. Update next value:

```python
"application": True,
"category_id": env.ref("base.module_category_website").id,
[...]
# Add dependencies
lst_depend = [
    "website",
]
```

Generate your module:

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
```

Now, you can test it! Note, you cannot install a generated module with is code_generator associated, because duplicated
models!


```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
```


```python
value["enable_sync_template"] = True
value["enable_template_wizard_view"] = True
value["template_model_name"] = "test;test2"
```

TODO

```bash
make db_restore_erplibre_base_db_template
./script/addons/install_addons_dev.sh template demo_website_snippet
./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet
```

Ready to test, generate your module:

```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./script/addons/install_addons_dev.sh test demo_website_snippet
```

# How to generate i18n translation

You need a template and a module. Be sure you have this line in template:

```python
new_module_path = os.path.join(path_module_generate, new_module_name)
code_generator_writer.set_module_translator(new_module_name, new_module_path)
```

First, install the module, example `demo_portal`, and after the template, example `code_generator_template_demo_portal`.

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh test demo_portal
./script/addons/install_addons_dev.sh test code_generator_template_demo_portal
```

# Sync Code_Generator fields from Module

This reduce time of programming a `Code_Generator` with sync module field with `Template`.

You need a `Template`, a `Code_Generator` with his `Module`. Install the `Module` first in clean database and install `Template`,
this will generate the `Code_Generator`, use `enable_sync_template` at True.

Example:

```bash
make db_restore_erplibre_base_db_code_generator
./script/addons/install_addons_dev.sh test demo_portal
./script/addons/install_addons_dev.sh test code_generator_template_demo_portal
```

# Test the code generator

TODO

```bash
make test
```

TODO

```bash
make test_code_generator_generation
```

TODO

```bash
make test_code_generator_generation_extra
```
TODO

```bash
make test_code_generator_template
```
