
# Execute ERPLibre

## Start database

```bash
sudo systemctl start postgresql.service
```

## Run ERPLibre

### Method 1

Simply

```bash
./run.sh
```

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

With arguments

```bash
./run.sh -h
```

### Method 2

Execute your own python script:

```bash
./run.sh --log-level debug
```

### Update all

Great idea to run it when updating Odoo, it updates each module database.

```bash
./run.sh -d [DATABASE] -u all --log-level debug
```

### Update module

```bash
./run.sh -d [DATABASE] -u [module] --log-level debug
```

### Test

First execution, install you requirements, choose a new database.

```bash
./run.sh -d [DATABASE] -i [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Execute your test on a specific module.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Execute your test on a specific module with tags.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test --test-tags [module_name][tags]
```