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

The value "enable_template_code_generator_demo" at True

### Generate a Code_Generator

Name your module begin with `MODULE_NAME = "code_generator_template_"`

The value "enable_template_code_generator_demo" at False

## Create your first Module

TODO
