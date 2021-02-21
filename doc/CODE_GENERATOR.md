# How to generate code

Never run this on production environment, this create circular dependencies and will cause frustration to clean damage.

```
Modules
############    ##################    ##########
# Template # -> # Code_Generator # -> # Module #
############    ##################    ##########
```
1. [A Template generates a Template or a Code_Generator.](Create your first code generator)
2. A Code_Generator generates a Module.
3. A Template reads a Module to generate a Code_Generator.

## Prepare a DB

This will destroy and create database named code_generator.
```bash
make db_restore_erplibre_base_db_code_generator
```

## Create your first Code_Generator

Edit [Code Generator Demo](./../addons/TechnoLibre_odoo-code-generator/code_generator_demo/hooks.py) and update `# TODO HUMAN:`

### Generate a Template

By default, code_generator_demo generate itself, code_generator_demo.

Name your module begin with `MODULE_NAME = "code_generator_template_"`

The value "enable_template_code_generator_demo" at False to create a new template module, else this will recreate code_generator_demo.

Example, to generate the module `code_generator_template_demo_website_snippet`, change value
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
Generate new module, this will overwrite code_generator_template_demo_website_snippet:
```bash
make addons_install_code_generator_demo
```

### Generate a Code_Generator

Name your module begin with `MODULE_NAME = "code_generator_demo_"`

The value "enable_template_code_generator_demo" at False

Continue the example, you generated the template `code_generator_template_demo_website_snippet`, this will overwrite code_generator_demo_website_snippet:
```bash
./install_addon.sh code_generator code_generator_template_demo_website_snippet
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
./install_addon.sh code_generator code_generator_demo_website_snippet
```

Now, you can test it! Note, you cannot install a generated module with is code_generator associated, because duplicated models!
Generate your module:
```bash
# Optional, reset test database
make db_restore_erplibre_base_db_test
./install_addon.sh test demo_website_snippet
```

# How to generate i18n translation

You need a template and a module.
Be sure you have this line in template:

```python
new_module_path = os.path.join(path_module_generate, new_module_name)
code_generator_writer.set_module_translator(new_module_name, new_module_path)
```

First, install the module, example demo_portal, and after the template, example code_generator_template_demo_portal
```bash
make db_restore_erplibre_base_db_code_generator
./install_addon.sh test demo_portal
./install_addon.sh test code_generator_template_demo_portal
```
