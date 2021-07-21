# Note healtcheck

Table à vérifier dans pgsql: ir_ui_view

Restore une BD:

- un module est installé mais n'est pas physiquement là

Une DB est installé mais on n'arrive pas à l'exécuté

HEALTHCHECK CMD curl --fail http://localhost:8069/web || exit 1

TODO: having the DB variable configurable
