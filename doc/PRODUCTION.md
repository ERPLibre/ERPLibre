# ERPLibre production guide

## Installation procedure production

### 1. Clone the project:
```bash
git clone https://git.erplibre.ca/ERPLibre.git
```

### 2. Modify the parameters
Modify the file env_var.sh for production installation.

### 3. Execute the script:
```bash
cd ERPLibre
./script/install_dev.sh
./script/install_production.sh
```

## Production execution
```bash
cd /[EL_USER]/erplibre
./run.sh -d [DATABASE] --no-database-list
```

## Move database prod to dev
When moving database prod to your dev environment, you want to remove email servers, and install user test to test the database.
Run:
```bash
./run.sh --stop-after-init -i user_test,disable_mail_server --dev all -d DATABASE
```

## Update production
Simply update all feature.
```bash
./run.sh --limit-time-real 99999 --stop-after-init -u all -d DATABASE
```
