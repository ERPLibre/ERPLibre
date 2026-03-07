
# Health check note

Table to verify in pgsql: ir_ui_view

Restore a database:

- a module is installed but is not physically present

A database is installed but cannot be executed

HEALTHCHECK CMD curl --fail http://localhost:8069/web || exit 1

TODO: having the DB variable configurable
