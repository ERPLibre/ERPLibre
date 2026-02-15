<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Execute ERPLibre

## Start database

<!-- [fr] -->
# Exécuter ERPLibre

## Démarrer la base de données

<!-- [common] -->
```bash
sudo systemctl start postgresql.service
```

<!-- [en] -->
## Run ERPLibre

### Method 1

Simply

<!-- [fr] -->
## Exécuter ERPLibre

### Méthode 1

Simplement

<!-- [common] -->
```bash
./run.sh
```

<!-- [en] -->
With arguments

<!-- [fr] -->
Avec des arguments

<!-- [common] -->
```bash
./run.sh -h
```

<!-- [en] -->
### Method 2

Execute your own python script:

<!-- [fr] -->
### Méthode 2

Exécutez votre propre script Python :

<!-- [common] -->
```bash
./run.sh --log-level debug
```

<!-- [en] -->
### Update all

Great idea to run it when updating Odoo, it updates each module database.

<!-- [fr] -->
### Tout mettre à jour

Bonne idée de l'exécuter lors de la mise à jour d'Odoo, cela met à jour la base de données de chaque module.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u all --log-level debug
```

<!-- [en] -->
### Update module

<!-- [fr] -->
### Mettre à jour un module

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u [module] --log-level debug
```

<!-- [en] -->
### Test

First execution, install you requirements, choose a new database.

<!-- [fr] -->
### Test

Première exécution, installez vos dépendances, choisissez une nouvelle base de données.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -i [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

<!-- [en] -->
Execute your test on a specific module.

<!-- [fr] -->
Exécutez vos tests sur un module spécifique.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

<!-- [en] -->
Execute your test on a specific module with tags.

<!-- [fr] -->
Exécutez vos tests sur un module spécifique avec des tags.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test --test-tags [module_name][tags]
```
