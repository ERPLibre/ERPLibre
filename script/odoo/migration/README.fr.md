
# Migration

Exécutez ce script lors de la migration de base de données. Exemple :

```bash
source ./.venv.odoo15.0_python3.8.20/bin/activate && cat ./script/odoo/migration/fix_migration_odoo140_to_odoo150.py | ./odoo15.0/odoo/odoo-bin shell -d DATABASE
```

Consultez [uninstall_module_list_odoo140_to_odoo150.txt](uninstall_module_list_odoo140_to_odoo150.txt)

## Listes de modules à désinstaller

Avant une montée de version, la migration désinstalle les modules listés dans
`uninstall_module_list_odoo<depuis>_to_odoo<vers>.txt`. Deux emplacements sont
lus, le privé d'abord, puis fusionnés (doublons éliminés) :

1. `private/odoo/migration/<base>/uninstall_module_list_odooXX0_to_odooYY0.txt`
   — propre à UNE base de données, non versionné. Les modules à supprimer
   dépendent des données : c'est ici que va la quasi-totalité des entrées.
2. `script/odoo/migration/uninstall_module_list_odooXX0_to_odooYY0.txt`
   — valeurs par défaut partagées, versionnées, valables pour toute base.

Syntaxe : un module par ligne, avec une justification après `#`. Les virgules et
plusieurs noms par ligne sont acceptés ; lignes vides et commentaires pleine
ligne sont ignorés. Un module sans raison est signalé à l'exécution : supprimer
un module est une décision qui doit pouvoir être relue plus tard.

```
queue_job                        # blocks 12->13, trigger queue_job_notify
mgmtsystem_hazard                # not ported to 13.0
web_syncer                       # dropped upstream
```