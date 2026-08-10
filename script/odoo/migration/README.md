
# Migration

Run this script when doing database migration. Example :

```bash
source ./.venv.odoo15.0_python3.8.20/bin/activate && cat ./script/odoo/migration/fix_migration_odoo140_to_odoo150.py | ./odoo15.0/odoo/odoo-bin shell -d DATABASE
```

Check [uninstall_module_list_odoo140_to_odoo150.txt](uninstall_module_list_odoo140_to_odoo150.txt)

## Module lists to uninstall

Before a version bump, the migration uninstalls the modules listed in
`uninstall_module_list_odoo<from>_to_odoo<to>.txt`. Two locations are read, the
private one first, and the results are merged (duplicates dropped):

1. `private/odoo/migration/<database>/uninstall_module_list_odooXX0_to_odooYY0.txt`
   — specific to ONE database, not versioned. Which modules must be dropped
   depends on the data, so this is where nearly every entry belongs.
2. `script/odoo/migration/uninstall_module_list_odooXX0_to_odooYY0.txt`
   — shared defaults, versioned, valid for every database.

Syntax: one module per line, with a justification after `#`. Commas and several
names per line are accepted; blank lines and full-line comments are ignored.
A module without a stated reason is flagged at runtime: removing a module is a
decision someone must be able to review later.

```
queue_job                        # blocks 12->13, trigger queue_job_notify
mgmtsystem_hazard                # not ported to 13.0
web_syncer                       # dropped upstream
```