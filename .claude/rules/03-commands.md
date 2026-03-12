# Commandes essentielles

## Changement de version Odoo
```bash
make switch_odoo_18          # Passer à Odoo 18
make switch_odoo_17          # Passer à Odoo 17
make switch_odoo_16          # Passer à Odoo 16 (défaut)
make switch_odoo_15          # Passer à Odoo 15
make switch_odoo_14          # Passer à Odoo 14
make switch_odoo_13          # Passer à Odoo 13
make switch_odoo_12          # Passer à Odoo 12
make switch_odoo_16_update   # Passer + mettre à jour les dépendances
```

## Exécution
```bash
make run                     # Lancer Odoo (port 8069)
make run_test                # Lancer avec la DB "test"
./run.sh -d ma_base          # Lancer avec une DB spécifique
./odoo_bin.sh [args]         # Exécuter odoo-bin directement
```

## Base de données
```bash
make db_create_db_test                        # Créer la DB "test"
make db_clone_test_to_test2                   # Cloner test -> test2
./script/database/db_restore.py --database NOM --image IMAGE
./script/addons/install_addons_dev.sh DB module1,module2
./script/addons/update_addons_all.sh DB
```

## Tests
```bash
make test                    # Tests de base + format
make test_full_fast          # Tests complets en parallèle
make test_full_fast_coverage # Avec couverture de code
```

## Formatage du code
```bash
make format                  # Fichiers à commiter uniquement
make format_all              # Tout formater (parallèle)
```

## Docker
```bash
make docker_run_daemon       # Lancer en production
make docker_build_odoo_18    # Builder l'image Odoo 18
```

## Google Repo (gestion multi-dépôts)
```bash
make repo_show_status        # Statut de tous les dépôts addons
make repo_configure_all      # Configurer tous les dépôts
make repo_do_stash           # Stash tous les dépôts
.venv.erplibre/bin/repo sync # Synchroniser les dépôts
```

## Installation
```bash
make install_os              # Dépendances système
make install_odoo_18         # Installer Odoo 18 complet
```
