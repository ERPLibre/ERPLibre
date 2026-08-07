<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Migration

Run this script when doing database migration. Example :

<!-- [fr] -->
# Migration

Exécutez ce script lors de la migration de base de données. Exemple :

<!-- [common] -->
```bash
source ./.venv.odoo15.0_python3.8.20/bin/activate && cat ./script/odoo/migration/fix_migration_odoo140_to_odoo150.py | ./odoo15.0/odoo/odoo-bin shell -d DATABASE
```

<!-- [en] -->
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

<!-- [fr] -->
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

<!-- [common] -->
```
queue_job                        # blocks 12->13, trigger queue_job_notify
mgmtsystem_hazard                # not ported to 13.0
web_syncer                       # dropped upstream
```
