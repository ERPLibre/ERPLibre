
# Guide de production ERPLibre

## Prérequis

- 5 Go d'espace disque

## Procédure d'installation en production

### 1. Cloner le projet :

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

### 2. Modifier les parametres

Modifiez le fichier env_var.sh pour l'installation en production. Activez nginx si vous avez besoin d'un proxy avec `EL_INSTALL_NGINX` a
True. Redirigez votre DNS vers l'adresse IP du proxy et ajoutez vos enregistrements A et AAAA dans `EL_WEBSITE_NAME` separes par des espaces.

### 3. Executer les scripts :

#### Avec le proxy nginx en production, installer certbot avant pour le SSL

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

#### Serveur Ubuntu 18.04

```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

Un service est en cours d'execution via SystemD. Vous pouvez y acceder avec le nom DNS trouve dans `env_var.sh`

#### Serveur Ubuntu 20.04

Appliquer le correctif libpng12-0 : https://www.linuxuprising.com/2018/05/fix-libpng12-0-missing-in-ubuntu-1804.html

```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

Un service est en cours d'execution via SystemD, vous pouvez y acceder avec le nom DNS trouve dans `env_var.sh`

### 4. SSL :

Generer un certificat SSL

```bash
sudo certbot --nginx
```

## Consulter les journaux

```bash
sudo systemctl -feu [EL_USER]
```

## Executer par adresse IP

Commentez la ligne suivante dans `/[EL_USER]/erplibre/config.conf`

```
xmlrpc_interface = 0.0.0.0
proxy_mode = True
```

Ajoutez votre adresse IP comme server_name dans la configuration nginx `/etc/nginx/sites-available/[EL_WEBSITE_NAME]`

Redemarrer le daemon :

```bash
sudo systemctl restart nginx
sudo systemctl restart [EL_USER]
```

## Execution en production

```bash
cd /[EL_USER]/erplibre
./run.sh -d [DATABASE] --no-database-list
```

## Deplacer la base de donnees de production vers le developpement

Lorsque vous deplacez une base de donnees de production vers votre environnement de developpement, vous souhaitez supprimer les serveurs de messagerie et installer un utilisateur de test pour tester la base de donnees. ATTENTION, ceci n'est pas securitaire pour la production, vous exposerez toutes les donnees.

1. Copiez votre image de base de donnees dans le repertoire image_db, par exemple le nom de l'image est `my_db.zip`
1. Executez

```bash
./script/database/db_restore.py --clean_cache --database test_my_db --image my_db
./script/addons/update_prod_to_dev.sh test_my_db
```

## Mise a jour de la production

Mettre a jour toutes les fonctionnalites.

```bash
./run.sh --limit-time-real 99999 --no-http --stop-after-init -u all -d DATABASE
```

# Postgresql

Pour afficher les fichiers de configuration :
> psql -U postgres -c 'SHOW config_file'

Editez ce fichier pour accepter les interfaces de tous les reseaux :
> /var/lib/postgres/data/postgresql.conf

# Supprimer une instance en production

ATTENTION, ceci supprimera le repertoire personnel de l'utilisateur, c'est irrevocable.

```bash
./script/database/delete_production.sh
```

# Mettre a jour l'IP lorsque l'IP publique change avec CloudFlare et crontab

Vous avez d'abord besoin d'un interpreteur python3 valide avec le module cloudflare installe : (assurez-vous que votre pip3 pointe vers le bon python3)

```bash
pip3 install cloudflare==2.20.0
```

Ensuite, vous devez creer les fichiers cfg avec les identifiants de votre compte cloudflare.

```bash
mkdir ~/.cloudflare
```

Editez ~/.cloudflare/cloudflare.cfg

```
[PROFILE_NAME]
email=EMAIL
token=TOKEN (Use the global API key so that it works)
```

Ajoutez votre cron et specifiez le python3 que vous souhaitez utiliser.
- USER est l'utilisateur local avec les permissions pour executer le script
- PATH est le chemin vers l'interieur du dossier ERPLibre/deployment/
- PROFILE_NAME doit correspondre au PROFILE_NAME dans cloudflare.cfg
- CLOUDFLARE_ZONE_NAME est le nom de la zone du site web sur cloudflare
- DNS_NAME est le nom d'un enregistrement DNS A disponible sur cette zone

Notes :
- Un seul crontab est necessaire car le script recherchera automatiquement toutes les zones disponibles avec une IP obsolete et les mettra a jour sur tous les enregistrements A.
- A chaque execution du crontab, si l'IP publique n'a pas change par rapport a ce qui est sur cloudflare, le script ne fera pas de changements inutiles et laissera tout en l'etat.

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync
```

Verifier les journaux avec

```bash
sudo journalctl -feu cron
```

Si vous souhaitez journaliser ce qui se passe et quand le script est execute, comme la journalisation des changements d'IP, vous pouvez ajouter une partie de journalisation a votre cron

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync > /home/USER/logs/update_dns_ZONE_NAME.log 2>&1

```

Vous pouvez ensuite lire tous les journaux avec cette commande (Necessite l'installation de ts : sudo apt install moreutils)

```bash
tail -f /home/USER/logs/update_dns_ZONE_NAME.log | ts
```

# Docker

## Mise a jour

Lors de la mise a jour d'un docker, vous devez mettre a jour la liste des modules.

Executez le script pour mettre a jour la configuration :

```bash
./script/docker/docker_gen_config.sh
```

Editez le docker-compose.yml et mettez a jour la ligne de commande (changez DATABASE) pour :

```yaml
    command: odoo --workers 2 -u erplibre_info -d DATABASE
```

Note, l'objectif est d'appeler `env['ir.module.module'].update_list()`.

Redemarrez le docker :

```bash
docker compose down
docker compose up -d
```

Revertez la commande dans docker-compose.yml.

Vous pouvez valider la mise a jour dans les journaux, vous devez trouver `odoo.modules.loading: updating modules list`, verifiez

```bash
docker compose logs -f
```

## Tout mettre a jour

Faites une sauvegarde a l'URL https://HOST/web/database/manager

Editez le docker-compose.yml et mettez a jour la ligne de commande (changez DATABASE) pour :

```yaml
    command: odoo --workers 2 -u all -d DATABASE
```

Surveillez les journaux pour voir les erreurs, si vous obtenez une erreur, vous devez ecrire du code pour migrer vos donnees, selon le cas.

```bash
make docker_show_logs_live
```