# ERPLibre

## Installation procedure production

##### 1. Clone the project:
```
git clone https://github.com/ERPLibre/ERPLibre.git
```
##### 2. Modify the parameters
Modify the file env_var.sh for production installation.

##### 3. Execute the script:
```
sudo ./script/odoo_install_production.sh
```

## Installation procedure locally

##### 1. Clone the project:
```
git clone https://github.com/ERPLibre/ERPLibre.git
```

##### 2. Execute the script:
```
sudo ./script/odoo_install_locally.sh
```

# Execution
## First run
```
source ./venv/bin/activate
python odoo/odoo-bin -c config.conf --log-level debug
```

## Update all
Great idea to run it when update Odoo, update database of each modules.
```
python odoo/odoo-bin -c config.conf -d [DATABASE] -u all --log-level debug
```

## Update module
```
python odoo/odoo-bin -c config.conf -d [DATABASE] -u [module] --log-level debug
```

## Test
```
python odoo/odoo-bin -c config.conf -d [DATABASE] -i [module to test] --test-enable --stop-after-init --log-level=test --test-tags [module_name][tags]
```

# Production
```
python odoo/odoo-bin -c config.conf -d [DATABASE] --no-database-list
```

# Thanks
Thanks Yenthe Van Ginneken for your guides.