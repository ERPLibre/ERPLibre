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
Without any argument, ERPLibre picks the database for you: with a single
one it starts on it, with several it shows a numbered menu. It only asks
when a real terminal is there — a service started by systemd behaves
exactly as before.

Two options steer that, and neither reaches Odoo:

| option | effect |
|---|---|
| `--auto-erplibre` | pick the database even when other arguments are given |
| `--no-cli-erplibre` | never show the menu; a lone database is still taken |

Naming a database yourself — `-d`, `--database` — turns the whole thing
off, and so does a `db_name` set in the configuration file.

<!-- [fr] -->
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
