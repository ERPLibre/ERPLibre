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
Great idea to run it when updating Odoo, it updates database of each modules.
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
./run.sh -d [DATABASE] -i [module to test] --test-enable --stop-after-init --log-level=test
```
Execute your test on specific module.
```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --stop-after-init --log-level=test
```
Execute your test on specific module with tags.
```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --stop-after-init --log-level=test --test-tags [module_name][tags]
```