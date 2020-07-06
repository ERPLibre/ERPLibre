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
source ./venv/bin/activate
python odoo/odoo-bin -c config.conf --log-level debug
```

### Update all
Great idea to run it when updating Odoo, it updates database of each modules.
```bash
python odoo/odoo-bin -c config.conf -d [DATABASE] -u all --log-level debug
```

### Update module
```bash
python odoo/odoo-bin -c config.conf -d [DATABASE] -u [module] --log-level debug
```

### Test
```bash
python odoo/odoo-bin -c config.conf -d [DATABASE] -i [module to test] --test-enable --stop-after-init --log-level=test --test-tags [module_name][tags]
```