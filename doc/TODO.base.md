<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Health check note

Table to verify in pgsql: ir_ui_view

Restore a database:

- a module is installed but is not physically present

A database is installed but cannot be executed

<!-- [fr] -->
# Note de vérification de santé

Table à vérifier dans pgsql : ir_ui_view

Restaurer une base de données :

- un module est installé mais n'est pas physiquement là

Une base de données est installée mais on n'arrive pas à l'exécuter

<!-- [common] -->
HEALTHCHECK CMD curl --fail http://localhost:8069/web || exit 1

<!-- [en] -->
TODO: having the DB variable configurable

<!-- [fr] -->
À FAIRE : rendre la variable DB configurable
