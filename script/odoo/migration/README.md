# Migration

Run this script when doing database migration. Example :

```bash
source ./.venv.odoo15.0_python3.8.20/bin/activate && cat ./script/odoo/migration/fix_migration_odoo140_to_odoo150.py | ./odoo15.0/odoo/odoo-bin shell -d DATABASE
```

Check [uninstall_module_list_odoo140_to_odoo150.txt](uninstall_module_list_odoo140_to_odoo150.txt)
