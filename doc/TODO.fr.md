
# Note de vérification de santé

Table à vérifier dans pgsql : ir_ui_view

Restaurer une base de données :

- un module est installé mais n'est pas physiquement là

Une base de données est installée mais on n'arrive pas à l'exécuter

HEALTHCHECK CMD curl --fail http://localhost:8069/web || exit 1

À FAIRE : rendre la variable DB configurable

Voir aussi : [EMAIL.fr.md](EMAIL.fr.md) — le client courriel intégré au CLI
TODO (`Assistant > Courriel`).