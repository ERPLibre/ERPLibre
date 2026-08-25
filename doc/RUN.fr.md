
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

Sans aucun argument, ERPLibre choisit la base pour vous : s'il n'y en a
qu'une il démarre dessus, s'il y en a plusieurs il affiche un menu
numéroté. Il ne pose la question que devant un vrai terminal — un service
lancé par systemd se comporte exactement comme avant.

Deux options le pilotent, et aucune n'arrive jusqu'à Odoo :

| option | effet |
|---|---|
| `--auto-erplibre` | choisir la base même quand d'autres arguments sont donnés |
| `--no-cli-erplibre` | ne jamais afficher le menu ; une base seule est quand même retenue |

Nommer soi-même une base — `-d`, `--database` — désactive tout, de même
qu'un `db_name` posé dans le fichier de configuration.

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