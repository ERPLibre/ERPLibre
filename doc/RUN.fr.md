
# Exécuter ERPLibre

## Démarrer la base de données

```bash
sudo systemctl start postgresql.service
```

## Exécuter ERPLibre

### Méthode 1

Simplement

```bash
./run.sh
```

Avec des arguments

```bash
./run.sh -h
```

### Méthode 2

Exécutez votre propre script Python :

```bash
./run.sh --log-level debug
```

### Tout mettre à jour

Bonne idée de l'exécuter lors de la mise à jour d'Odoo, cela met à jour la base de données de chaque module.

```bash
./run.sh -d [DATABASE] -u all --log-level debug
```

### Mettre à jour un module

```bash
./run.sh -d [DATABASE] -u [module] --log-level debug
```

### Test

Première exécution, installez vos dépendances, choisissez une nouvelle base de données.

```bash
./run.sh -d [DATABASE] -i [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Exécutez vos tests sur un module spécifique.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Exécutez vos tests sur un module spécifique avec des tags.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test --test-tags [module_name][tags]
```