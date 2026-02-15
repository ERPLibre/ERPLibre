<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# ERPLibre production guide

## Requirement

- 5Go of disk space

## Production installation procedure

### 1. Clone the project:

<!-- [fr] -->
# Guide de production ERPLibre

## Prérequis

- 5 Go d'espace disque

## Procédure d'installation en production

### 1. Cloner le projet :

<!-- [common] -->
```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

<!-- [en] -->
### 2. Modify the parameters

Modify the file env_var.sh for production installation. Enable nginx if you need a proxy with `EL_INSTALL_NGINX` at
True. Redirect your DNS to the proxy's ip and add your A and AAAA into `EL_WEBSITE_NAME` with space between.

### 3. Execute the scripts:

#### With proxy nginx production, install certbot before for SSL

<!-- [fr] -->
### 2. Modifier les parametres

Modifiez le fichier env_var.sh pour l'installation en production. Activez nginx si vous avez besoin d'un proxy avec `EL_INSTALL_NGINX` a
True. Redirigez votre DNS vers l'adresse IP du proxy et ajoutez vos enregistrements A et AAAA dans `EL_WEBSITE_NAME` separes par des espaces.

### 3. Executer les scripts :

#### Avec le proxy nginx en production, installer certbot avant pour le SSL

<!-- [common] -->
```bash
# Snap installation
# https://snapcraft.io/docs/installing-snap-on-debian
sudo apt install -y snapd
sudo snap install core
sudo snap refresh core

# https://certbot.eff.org/lets-encrypt/debianbuster-nginx
# Certbot
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

<!-- [en] -->
#### Ubuntu 18.04 server

<!-- [fr] -->
#### Serveur Ubuntu 18.04

<!-- [common] -->
```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

<!-- [en] -->
A service is running by SystemD. You can access it with the DNS name found in `env_var.sh`

#### Ubuntu 20.04 server

Apply fix libpng12-0: https://www.linuxuprising.com/2018/05/fix-libpng12-0-missing-in-ubuntu-1804.html

<!-- [fr] -->
Un service est en cours d'execution via SystemD. Vous pouvez y acceder avec le nom DNS trouve dans `env_var.sh`

#### Serveur Ubuntu 20.04

Appliquer le correctif libpng12-0 : https://www.linuxuprising.com/2018/05/fix-libpng12-0-missing-in-ubuntu-1804.html

<!-- [common] -->
```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

<!-- [en] -->
A service is running by SystemD, you can access it with the DNS name found in `env_var.sh`

### 4. SSL:

Generate a ssl certificate

<!-- [fr] -->
Un service est en cours d'execution via SystemD, vous pouvez y acceder avec le nom DNS trouve dans `env_var.sh`

### 4. SSL :

Generer un certificat SSL

<!-- [common] -->
```bash
sudo certbot --nginx
```

<!-- [en] -->
## Watch log

<!-- [fr] -->
## Consulter les journaux

<!-- [common] -->
```bash
sudo systemctl -feu [EL_USER]
```

<!-- [en] -->
## Run by address ip

Comment the following line in `/[EL_USER]/erplibre/config.conf`

<!-- [fr] -->
## Executer par adresse IP

Commentez la ligne suivante dans `/[EL_USER]/erplibre/config.conf`

<!-- [common] -->
```
xmlrpc_interface = 0.0.0.0
proxy_mode = True
```

<!-- [en] -->
Add your address ip server_name in nginx config `/etc/nginx/sites-available/[EL_WEBSITE_NAME]`

Restart daemon:

<!-- [fr] -->
Ajoutez votre adresse IP comme server_name dans la configuration nginx `/etc/nginx/sites-available/[EL_WEBSITE_NAME]`

Redemarrer le daemon :

<!-- [common] -->
```bash
sudo systemctl restart nginx
sudo systemctl restart [EL_USER]
```

<!-- [en] -->
## Production execution

<!-- [fr] -->
## Execution en production

<!-- [common] -->
```bash
cd /[EL_USER]/erplibre
./run.sh -d [DATABASE] --no-database-list
```

<!-- [en] -->
## Move prod database to dev

When moving prod database to your dev environment, you want to remove email servers and install user test to test the
database. WARNING, this is not safe for production, you will expose all data.

1. Copy your database image to directory image_db, exemple the image name is `my_db.zip`
1. Run

<!-- [fr] -->
## Deplacer la base de donnees de production vers le developpement

Lorsque vous deplacez une base de donnees de production vers votre environnement de developpement, vous souhaitez supprimer les serveurs de messagerie et installer un utilisateur de test pour tester la base de donnees. ATTENTION, ceci n'est pas securitaire pour la production, vous exposerez toutes les donnees.

1. Copiez votre image de base de donnees dans le repertoire image_db, par exemple le nom de l'image est `my_db.zip`
1. Executez

<!-- [common] -->
```bash
./script/database/db_restore.py --clean_cache --database test_my_db --image my_db
./script/addons/update_prod_to_dev.sh test_my_db
```

<!-- [en] -->
## Update production

Update all features.

<!-- [fr] -->
## Mise a jour de la production

Mettre a jour toutes les fonctionnalites.

<!-- [common] -->
```bash
./run.sh --limit-time-real 99999 --no-http --stop-after-init -u all -d DATABASE
```

<!-- [en] -->
# Postgresql

To show config files:
> psql -U postgres -c 'SHOW config_file'

Edit this file to accept interface from all networks:
> /var/lib/postgres/data/postgresql.conf

# Delete an instance in production

CAUTION, this will delete user's home, it's irrevocable.

<!-- [fr] -->
# Postgresql

Pour afficher les fichiers de configuration :
> psql -U postgres -c 'SHOW config_file'

Editez ce fichier pour accepter les interfaces de tous les reseaux :
> /var/lib/postgres/data/postgresql.conf

# Supprimer une instance en production

ATTENTION, ceci supprimera le repertoire personnel de l'utilisateur, c'est irrevocable.

<!-- [common] -->
```bash
./script/database/delete_production.sh
```

<!-- [en] -->
# Update ip when public ip change with CloudFlare and crontab

First you need a valid python3 interpreter running with cloudflare module installed: (make sure your pip3 pointing the right python3)

<!-- [fr] -->
# Mettre a jour l'IP lorsque l'IP publique change avec CloudFlare et crontab

Vous avez d'abord besoin d'un interpreteur python3 valide avec le module cloudflare installe : (assurez-vous que votre pip3 pointe vers le bon python3)

<!-- [common] -->
```bash
pip3 install cloudflare==2.20.0
```

<!-- [en] -->
Then you need to create the cfg files with credentials for your cloudflare account.

<!-- [fr] -->
Ensuite, vous devez creer les fichiers cfg avec les identifiants de votre compte cloudflare.

<!-- [common] -->
```bash
mkdir ~/.cloudflare
```

<!-- [en] -->
Edit ~/.cloudflare/cloudflare.cfg

<!-- [fr] -->
Editez ~/.cloudflare/cloudflare.cfg

<!-- [common] -->
```
[PROFILE_NAME]
email=EMAIL
token=TOKEN (Use the global API key so that it works)
```

<!-- [en] -->
Add your cron and specify the python3 you want to use with it.
- USER is the local user with permissions to execute the script
- PATH is path to inside of ERPLibre/deployment/ folder
- PROFILE_NAME must match the PROFILE_NAME in cloudflare.cfg
- CLOUDFLARE_ZONE_NAME is the name of the website zone on cloudflare
- DNS_NAME is the name of one DNS A record name available on that zone

Notes:
- Only one crontab is required because the script will automatically research all available zones with outdated ip and update them on all A records.
- For each crontab run, if public IP did not change compared to what is on cloudflare, the script will not do unnecessary changes and let everything as is.

<!-- [fr] -->
Ajoutez votre cron et specifiez le python3 que vous souhaitez utiliser.
- USER est l'utilisateur local avec les permissions pour executer le script
- PATH est le chemin vers l'interieur du dossier ERPLibre/deployment/
- PROFILE_NAME doit correspondre au PROFILE_NAME dans cloudflare.cfg
- CLOUDFLARE_ZONE_NAME est le nom de la zone du site web sur cloudflare
- DNS_NAME est le nom d'un enregistrement DNS A disponible sur cette zone

Notes :
- Un seul crontab est necessaire car le script recherchera automatiquement toutes les zones disponibles avec une IP obsolete et les mettra a jour sur tous les enregistrements A.
- A chaque execution du crontab, si l'IP publique n'a pas change par rapport a ce qui est sur cloudflare, le script ne fera pas de changements inutiles et laissera tout en l'etat.

<!-- [common] -->
```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync
```

<!-- [en] -->
Check log with

<!-- [fr] -->
Verifier les journaux avec

<!-- [common] -->
```bash
sudo journalctl -feu cron
```

<!-- [en] -->
If you want to log what is happening and when the script is run, like logging when ip changes, you can add a logging part to your cron

<!-- [fr] -->
Si vous souhaitez journaliser ce qui se passe et quand le script est execute, comme la journalisation des changements d'IP, vous pouvez ajouter une partie de journalisation a votre cron

<!-- [common] -->
```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync > /home/USER/logs/update_dns_ZONE_NAME.log 2>&1

```

<!-- [en] -->
You can then read all logs with this command (Need to have ts installed: sudo apt install moreutils)

<!-- [fr] -->
Vous pouvez ensuite lire tous les journaux avec cette commande (Necessite l'installation de ts : sudo apt install moreutils)

<!-- [common] -->
```bash
tail -f /home/USER/logs/update_dns_ZONE_NAME.log | ts
```

<!-- [en] -->
# Docker

## Update

When update a docker, you need to update the list of module.

Run script to update configuration :

<!-- [fr] -->
# Docker

## Mise a jour

Lors de la mise a jour d'un docker, vous devez mettre a jour la liste des modules.

Executez le script pour mettre a jour la configuration :

<!-- [common] -->
```bash
./script/docker/docker_gen_config.sh
```

<!-- [en] -->
Edit the docker-compose.yml and update the command line (change DATABASE) to :

<!-- [fr] -->
Editez le docker-compose.yml et mettez a jour la ligne de commande (changez DATABASE) pour :

<!-- [common] -->
```yaml
    command: odoo --workers 2 -u erplibre_info -d DATABASE
```

<!-- [en] -->
Note, the goal is to call `env['ir.module.module'].update_list()`.

Restart the docker :

<!-- [fr] -->
Note, l'objectif est d'appeler `env['ir.module.module'].update_list()`.

Redemarrez le docker :

<!-- [common] -->
```bash
docker compose down
docker compose up -d
```

<!-- [en] -->
Revert the command in docker-compose.yml.

You can validate in log the update, you need to find `odoo.modules.loading: updating modules list`, check

<!-- [fr] -->
Revertez la commande dans docker-compose.yml.

Vous pouvez valider la mise a jour dans les journaux, vous devez trouver `odoo.modules.loading: updating modules list`, verifiez

<!-- [common] -->
```bash
docker compose logs -f
```

<!-- [en] -->
## Update all

Do a backup on url https://HOST/web/database/manager

Edit the docker-compose.yml and update the command line (change DATABASE) to :

<!-- [fr] -->
## Tout mettre a jour

Faites une sauvegarde a l'URL https://HOST/web/database/manager

Editez le docker-compose.yml et mettez a jour la ligne de commande (changez DATABASE) pour :

<!-- [common] -->
```yaml
    command: odoo --workers 2 -u all -d DATABASE
```

<!-- [en] -->
Watch log to see error, if you got error, you need to do some code to migrate your data, depend the case.

<!-- [fr] -->
Surveillez les journaux pour voir les erreurs, si vous obtenez une erreur, vous devez ecrire du code pour migrer vos donnees, selon le cas.

<!-- [common] -->
```bash
make docker_show_logs_live
```
