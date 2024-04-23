# ERPLibre production guide

## Requirement

- 5Go of disk space

## Production installation procedure

### 1. Clone the project:

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

### 2. Modify the parameters

Modify the file env_var.sh for production installation. Enable nginx if you need a proxy with `EL_INSTALL_NGINX` at
True. Redirect your DNS to the proxy's ip and add your A and AAAA into `EL_WEBSITE_NAME` with space between.

### 3. Execute the scripts:

#### With proxy nginx production, install certbot before for SSL

```bash
# Snap installation
# https://snapcraft.io/docs/installing-snap-on-debian
sudo apt install -y snapd
sudo snap install core
sudo snap refresh core

# https://certbot.eff.org/lets-encrypt/debianbuster-nginx
# Cerbot
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

#### Ubuntu 18.04 server

```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

A service is running by SystemD. You can access it with the DNS name found in `env_var.sh`

#### Ubuntu 20.04 server

Apply fix libpng12-0: https://www.linuxuprising.com/2018/05/fix-libpng12-0-missing-in-ubuntu-1804.html

```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

A service is running by SystemD, you can access it with the DNS name found in `env_var.sh`

### 4. SSL:

Generate a ssl certificate

```bash
sudo certbot --nginx
```

## Watch log

```bash
sudo systemctl -feu [EL_USER]
```

## Run by address ip

Comment the following line in `/[EL_USER]/erplibre/config.conf`

```
#xmlrpc_interface = 127.0.0.1
#netrpc_interface = 127.0.0.1
#proxy_mode = True
```

Add your address ip server_name in nginx config `/etc/nginx/sites-available/[EL_WEBSITE_NAME]`

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

## Move prod database to dev

When moving prod database to your dev environment, you want to remove email servers and install user test to test the
database. WARNING, this is not safe for production, you will expose all data.

1. Copy your database image to directory image_db, exemple the image name is `my_db.zip`
1. Run

```bash
./script/database/db_restore.py --clean_cache --database test_my_db --image my_db
./script/addons/update_prod_to_dev.sh test_my_db
```

## Update production

Update all features.

```bash
./run.sh --limit-time-real 99999 --stop-after-init -u all -d DATABASE
```

# Postgresql

To show config files:
> psql -U postgres -c 'SHOW config_file'

Edit this file to accept interface from all networks:
> /var/lib/postgres/data/postgresql.conf

# Delete an instance in production

CAUTION, this will delete user's home, it's irrevocable.

```bash
./script/database/delete_production.sh
```

# Update ip when public ip change with CloudFlare and crontab

```bash
mkdir ~/.cloudflare
```

Edit ~/.cloudflare/cloudflare.cfg

```
[PROFILE_NAME]
email=EMAIL
token=TOKEN
```

Add your cron

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && ./script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync
```

Check log with

```bash
sudo journalctl -feu cron
```

# Docker

## Update

When update a docker, you need to update the list of module.

Run script to update configuration :

```bash
./script/docker/docker_gen_config.sh
```

Edit the docker-compose.yml and update the command line (change DATABASE) to :

```yaml
    command: odoo --workers 2 -u erplibre_info -d DATABASE
```

Note, the goal is to call `env['ir.module.module'].update_list()`.

Restart the docker :

```bash
docker compose down
docker compose up -d
```

Revert the command in docker-compose.yml.

You can validate in log the update, you need to find `odoo.modules.loading: updating modules list`, check

```bash
docker compose logs -f
```

## Update all

Do a backup on url https://HOST/web/database/manager

Edit the docker-compose.yml and update the command line (change DATABASE) to :

```yaml
    command: odoo --workers 2 -u all -d DATABASE
```

Watch log to see error, if you got error, you need to do some code to migrate your data, depend the case.

```bash
make docker_show_logs_live
```
