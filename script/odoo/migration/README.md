# Migration

Run this script when doing database migration. Example :

```bash
cat ./script/migration/fix_migration_odoo140_to_odoo150.py | ./odoo15.0/odoo/odoo-bin shell -d DATABASE
```

Check [uninstall_module_list_odoo140_to_odoo150.txt](uninstall_module_list_odoo140_to_odoo150.txt)
