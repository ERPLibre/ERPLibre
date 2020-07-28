# ERPLibre production guide

## Installation procedure production

### 1. Clone the project:
```bash
git clone http://git.erplibre.ca/ERPLibre.git
cd ERPLibre
```

### 2. Modify the parameters
Modify the file env_var.sh for production installation.

### 3. Execute the script:
Support Ubuntu 18.04 server
```bash
./script/install_dev.sh
./script/install_production.sh
```
A service is running by systemd, you can access with the DNS name, found it in env_var.sh

### 4. SSL:
Generate a ssl certificat
```bash
sudo certbot --nginx
```

## Watch log
```bash
sudo systemctl -feu [EL_USER]
```

## Run by address ip
Comment following line in /[EL_USER]/erplibre/config.conf
```
#xmlrpc_interface = 127.0.0.1
#netrpc_interface = 127.0.0.1
#proxy_mode = True
```
Add your address ip in nginx config at server_name in /etc/nginx/sites-available/[EL_WEBSITE_NAME]

Restart daemon:
```bash
sudo systemctl restart nginx
sudo systemctl restart [EL_USER]
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

# Postgresql
To show config file:
> psql -U postgres -c 'SHOW config_file'

Edit this file to accept interface from all network:
> /var/lib/postgres/data/postgresql.conf
