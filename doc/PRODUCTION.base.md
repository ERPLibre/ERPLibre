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
### 2. Modifier les paramètres

Modifiez le fichier env_var.sh pour l'installation en production. Activez nginx si vous avez besoin d'un proxy avec `EL_INSTALL_NGINX` à
True. Redirigez votre DNS vers l'adresse IP du proxy et ajoutez vos enregistrements A et AAAA dans `EL_WEBSITE_NAME` séparés par des espaces.

### 3. Exécuter les scripts :

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

#### Ubuntu 24.04 server

Apply fix libpng12-0: https://www.linuxuprising.com/2018/05/fix-libpng12-0-missing-in-ubuntu-1804.html

<!-- [fr] -->
Un service est en cours d'exécution via SystemD. Vous pouvez y accéder avec le nom DNS trouvé dans `env_var.sh`

#### Serveur Ubuntu 24.04

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
Un service est en cours d'exécution via SystemD, vous pouvez y accéder avec le nom DNS trouvé dans `env_var.sh`

### 4. SSL :

Générer un certificat SSL

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
## Exécuter par adresse IP

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

Redémarrer le daemon :

<!-- [common] -->
```bash
sudo systemctl restart nginx
sudo systemctl restart [EL_USER]
```

<!-- [en] -->
## Production execution

<!-- [fr] -->
## Exécution en production

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
## Déplacer la base de données de production vers le développement

Lorsque vous déplacez une base de données de production vers votre environnement de développement, vous souhaitez supprimer les serveurs de messagerie et installer un utilisateur de test pour tester la base de données. ATTENTION, ceci n'est pas sécuritaire pour la production, vous exposerez toutes les données.

1. Copiez votre image de base de données dans le répertoire image_db, par exemple le nom de l'image est `my_db.zip`
1. Exécutez

<!-- [common] -->
```bash
./script/database/db_restore.py --clean_cache --database test_my_db --image my_db
./script/addons/update_prod_to_dev.sh test_my_db
```

<!-- [en] -->
## Update production

Update all features.

<!-- [fr] -->
## Mise à jour de la production

Mettre à jour toutes les fonctionnalités.

<!-- [common] -->
```bash
./run.sh --limit-time-real 99999 --no-http --stop-after-init -u all -d DATABASE
```

<!-- [en] -->
### Update modules of an instance run by systemd

`script/odoo/update_module.py` stops the unit, backs the database up,
updates the modules, restarts the unit and checks its log. The unit is only
read, never modified, and a unit that was running is restarted whatever
happens. Always simulate first:

<!-- [fr] -->
### Mettre à jour les modules d'une instance servie par systemd

`script/odoo/update_module.py` arrête l'unité, sauvegarde la base, met à
jour les modules, relance l'unité et vérifie son journal. L'unité est
seulement lue, jamais modifiée, et une unité qui tournait est relancée quoi
qu'il arrive. Toujours simuler d'abord :

<!-- [common] -->
```bash
./script/odoo/update_module.py --module 'my_module_*' --db DATABASE --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db DATABASE
```

<!-- [en] -->
The same is reachable from `make todo`: `Execute > Production`. Options,
detection order and exit codes: [script/odoo/README.md](../script/odoo/README.md).

<!-- [fr] -->
Le même geste est accessible depuis `make todo` : `Exécuter > Production`.
Options, ordre de détection et codes de sortie :
[script/odoo/README.fr.md](../script/odoo/README.fr.md).

<!-- [en] -->
### Verified backups

`script/database/odoo_backup.py` backs a database up in Odoo's own zip
format, verifies the file, keeps a daily, weekly and monthly retention,
reports the age of the last success, test-restores into a temporary
database and restores into a new database only. `update_module.py` uses it
for its backup before an update, under the same database lock.

<!-- [fr] -->
### Sauvegardes vérifiées

`script/database/odoo_backup.py` sauvegarde une base au format zip d'Odoo,
vérifie le fichier, tient une rétention quotidienne, hebdomadaire et
mensuelle, donne l'âge du dernier succès, essaie la restauration dans une
base temporaire et ne restaure que dans une nouvelle base.
`update_module.py` s'en sert pour sa sauvegarde avant une mise à jour, sous
le même verrou de base.

<!-- [common] -->
```bash
./script/database/odoo_backup.py --db DATABASE --dry-run
sudo ./script/database/odoo_backup.py --db DATABASE
./script/database/odoo_backup.py --status
sudo ./script/database/odoo_backup.py --test-restore --db DATABASE
```

<!-- [en] -->
The scheduled backup is a systemd service and timer written by
`script/systemd/install_backup_timer.py`. The service runs the backup as
the account of the Odoo unit, never as root, with every option in its
`ExecStart`; the timer runs daily at 03:00 by default (`--on-calendar`),
with `RandomizedDelaySec` and `Persistent=true`. A tmpfiles.d entry
creates the shared lock file `/run/lock/erplibre-db-DATABASE.lock` at
boot, so the account can take the lock where `/run/lock` belongs to root.
Before writing anything, the script checks as that account that it can
run the interpreter and read the tool and the Odoo configuration. It
refuses to replace a file it did not write, and `--uninstall` keeps the
backups:

<!-- [fr] -->
La sauvegarde planifiée est un service et une minuterie systemd écrits par
`script/systemd/install_backup_timer.py`. Le service lance la sauvegarde
sous le compte de l'unité Odoo, jamais en root, toutes ses options dans son
`ExecStart` ; la minuterie part chaque jour à 03:00 par défaut
(`--on-calendar`), avec `RandomizedDelaySec` et `Persistent=true`. Une
entrée tmpfiles.d crée au démarrage le fichier du verrou partagé
`/run/lock/erplibre-db-DATABASE.lock` : le compte prend le verrou même là
où `/run/lock` appartient à root. Avant d'écrire quoi que ce soit, le
script vérifie sous ce compte qu'il peut lancer l'interpréteur et lire
l'outil et la configuration Odoo. Il refuse de remplacer un fichier qu'il
n'a pas écrit, et `--uninstall` garde les sauvegardes :

<!-- [common] -->
```bash
sudo ./script/systemd/install_backup_timer.py --db DATABASE --dry-run
sudo ./script/systemd/install_backup_timer.py --db DATABASE --copy-to backup@backup.example.org:/srv/backups
systemctl list-timers 'erplibre-backup-*'
sudo ./script/systemd/install_backup_timer.py --db DATABASE --uninstall
```

<!-- [en] -->
`--copy-to` adds an off-site copy (rsync over ssh with the account's key;
the remote side has no retention and grows). Monitor `--status`: it exits
with code 1 when the last success is older than `--max-age` hours (26).
All of it is also in `make todo`: `Execute > Production`. Details,
retention rules and exit codes:
[script/database/README.md](../script/database/README.md).

<!-- [fr] -->
`--copy-to` ajoute une copie hors site (rsync sur ssh avec la clé du
compte ; le côté distant n'a pas de rétention et grossit). Surveiller
`--status` : il sort en code 1 quand le dernier succès date de plus de
`--max-age` heures (26). Tout cela est aussi dans `make todo` :
`Exécuter > Production`. Détails, règles de rétention et codes de sortie :
[script/database/README.fr.md](../script/database/README.fr.md).

<!-- [en] -->
### Odoo journal

`script/odoo/log_check.py` reads the journal of the instance and says what
needs a look: Python tracebacks grouped by their final exception, other
`ERROR`/`CRITICAL` records, refused SQL queries, and mail sending failures
classified as transient or PERMANENT with the Odoo setting to check. It
reads the unit's `logfile` when its configuration sets one, otherwise
`journalctl` for the unit; `--file` reads any Odoo log file. Known harmless
messages are counted apart, and `--ignore REGEX` adds local ones.

<!-- [fr] -->
### Journal d'Odoo

`script/odoo/log_check.py` lit le journal de l'instance et dit ce qui mérite
un regard : traces Python groupées par leur exception finale, autres
enregistrements `ERROR`/`CRITICAL`, requêtes SQL refusées, et échecs
d'envoi de courriel classés passagers ou PERMANENTS avec le réglage d'Odoo
à vérifier. Il lit le `logfile` de l'unité quand sa configuration en pose
un, sinon `journalctl` pour l'unité ; `--file` lit n'importe quel fichier
de journal d'Odoo. Les messages connus et sans gravité sont comptés à part,
et `--ignore REGEX` en ajoute de locaux.

<!-- [common] -->
```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --since-last --json
```

<!-- [en] -->
`--since-last` remembers where it stopped (journal cursor, or file inode
and offset) in `/var/lib/erplibre-logcheck/<unit>.json` (`--state-dir`),
only after a complete read; the first run covers the last 24 h. Without a
window option it reads the last 24 h. If the state folder is not writable
the report is still printed and says that the position was not saved; run
it with sudo, or point `--state-dir` to a folder the account can write. An
account in the `systemd-journal` (or `adm`) group reads the journal without
sudo; otherwise the tool exits with code 2 instead of reporting nothing.
Exit codes: 0 nothing to review, 1 something to review, 2 could not read.
It writes nothing but its state file. Details:
[script/odoo/README.md](../script/odoo/README.md).

<!-- [fr] -->
`--since-last` retient où il s'est arrêté (curseur du journal, ou inode et
octet d'un fichier) dans `/var/lib/erplibre-logcheck/<unité>.json`
(`--state-dir`), seulement après une lecture complète ; la première fois
couvre les dernières 24 h. Sans option de fenêtre, il lit les dernières
24 h. Si le dossier d'état n'est pas inscriptible, le rapport s'affiche
quand même et dit que la position n'a pas été retenue ; le lancer avec
sudo, ou désigner par `--state-dir` un dossier où le compte peut écrire. Un
compte du groupe `systemd-journal` (ou `adm`) lit le journal sans sudo ;
sinon l'outil sort en code 2 au lieu de ne rien signaler. Codes de sortie :
0 rien à revoir, 1 quelque chose à revoir, 2 lecture impossible. Il
n'écrit rien d'autre que son fichier d'état. Détails :
[script/odoo/README.fr.md](../script/odoo/README.fr.md).

<!-- [en] -->
### Failed outgoing mail

`script/odoo/mail_retry.py` lists the mails Odoo could not send in the last
`--days` (30), read-only, as the unit's account: date, subject, recipients
masked unless `--details`, and the cause, transient or PERMANENT. A
PERMANENT cause (authentication, sender, relay, TLS, invalid address) fails
again on resend until the named setting is fixed. Resending puts the chosen
mails back in the queue through the unit's Odoo shell and the ORM
(`action_retry`, or `state = outgoing` where that method does not exist);
the scheduled action "Mail: Email Queue Manager" sends them at its next
run.

<!-- [fr] -->
### Courriels sortants en échec

`script/odoo/mail_retry.py` liste les courriels qu'Odoo n'a pas pu envoyer
dans les `--days` derniers jours (30), en lecture seule, sous le compte de
l'unité : date, sujet, destinataires masqués sauf `--details`, et la
cause, passagère ou PERMANENTE. Une cause PERMANENTE (authentification,
expéditeur, relais, TLS, adresse invalide) échoue de nouveau au renvoi tant
que le réglage nommé n'est pas corrigé. Le renvoi remet les courriels
choisis en file par le shell d'Odoo de l'unité et l'ORM (`action_retry`, ou
`state = outgoing` là où la méthode n'existe pas) ; l'action planifiée
« Mail: Email Queue Manager » les envoie à son prochain passage.

<!-- [common] -->
```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
```

<!-- [en] -->
On a terminal, without `--resend`, a menu asks which ones to resend (all,
the oldest batch, chosen ids, none — the default). Without a terminal,
`--resend all | oldest N | ids LIST` needs `--yes`. Exit codes: 0 nothing
failed or every chosen mail requeued, 1 failures left or part of the
selection skipped, 2 refused or impossible. Both tools are in `make todo`:
`Execute > Production`. Details and the Odoo 12 to 18 matrix:
[script/odoo/README.md](../script/odoo/README.md).

<!-- [fr] -->
Sur un terminal, sans `--resend`, un menu demande lesquels renvoyer (tous,
les plus anciens, des ids choisis, aucun — le défaut). Sans terminal,
`--resend all | oldest N | ids LISTE` exige `--yes`. Codes de sortie : 0
aucun échec ou tous les courriels choisis remis en file, 1 des échecs
restent ou une partie de la sélection est ignorée, 2 refusé ou impossible.
Les deux outils sont dans `make todo` : `Exécuter > Production`. Détails et
matrice Odoo 12 à 18 :
[script/odoo/README.fr.md](../script/odoo/README.fr.md).

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

Éditez ce fichier pour accepter les interfaces de tous les réseaux :
> /var/lib/postgres/data/postgresql.conf

# Supprimer une instance en production

ATTENTION, ceci supprimera le répertoire personnel de l'utilisateur, c'est irrévocable.

<!-- [common] -->
```bash
./script/database/delete_production.sh
```

<!-- [en] -->
# Update ip when public ip change with CloudFlare and crontab

First you need a valid python3 interpreter running with cloudflare module installed: (make sure your pip3 pointing the right python3)

<!-- [fr] -->
# Mettre à jour l'IP lorsque l'IP publique change avec CloudFlare et crontab

Vous avez d'abord besoin d'un interpréteur python3 valide avec le module cloudflare installé : (assurez-vous que votre pip3 pointe vers le bon python3)

<!-- [common] -->
```bash
pip3 install cloudflare==2.20.0
```

<!-- [en] -->
Then you need to create the cfg files with credentials for your cloudflare account.

<!-- [fr] -->
Ensuite, vous devez créer les fichiers cfg avec les identifiants de votre compte cloudflare.

<!-- [common] -->
```bash
mkdir ~/.cloudflare
```

<!-- [en] -->
Edit ~/.cloudflare/cloudflare.cfg

<!-- [fr] -->
Éditez ~/.cloudflare/cloudflare.cfg

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
Ajoutez votre cron et spécifiez le python3 que vous souhaitez utiliser.
- USER est l'utilisateur local avec les permissions pour exécuter le script
- PATH est le chemin vers l'intérieur du dossier ERPLibre/deployment/
- PROFILE_NAME doit correspondre au PROFILE_NAME dans cloudflare.cfg
- CLOUDFLARE_ZONE_NAME est le nom de la zone du site web sur cloudflare
- DNS_NAME est le nom d'un enregistrement DNS A disponible sur cette zone

Notes :
- Un seul crontab est nécessaire car le script recherchera automatiquement toutes les zones disponibles avec une IP obsolète et les mettra à jour sur tous les enregistrements A.
- À chaque exécution du crontab, si l'IP publique n'a pas changé par rapport à ce qui est sur cloudflare, le script ne fera pas de changements inutiles et laissera tout en l'état.

<!-- [common] -->
```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync
```

<!-- [en] -->
Check log with

<!-- [fr] -->
Vérifier les journaux avec

<!-- [common] -->
```bash
sudo journalctl -feu cron
```

<!-- [en] -->
If you want to log what is happening and when the script is run, like logging when ip changes, you can add a logging part to your cron

<!-- [fr] -->
Si vous souhaitez journaliser ce qui se passe et quand le script est exécuté, comme la journalisation des changements d'IP, vous pouvez ajouter une partie de journalisation à votre cron

<!-- [common] -->
```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync > /home/USER/logs/update_dns_ZONE_NAME.log 2>&1

```

<!-- [en] -->
You can then read all logs with this command (Need to have ts installed: sudo apt install moreutils)

<!-- [fr] -->
Vous pouvez ensuite lire tous les journaux avec cette commande (Nécessite l'installation de ts : sudo apt install moreutils)

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

## Mise à jour

Lors de la mise à jour d'un docker, vous devez mettre à jour la liste des modules.

Exécutez le script pour mettre à jour la configuration :

<!-- [common] -->
```bash
./script/docker/docker_gen_config.sh
```

<!-- [en] -->
Edit the docker-compose.yml and update the command line (change DATABASE) to :

<!-- [fr] -->
Éditez le docker-compose.yml et mettez à jour la ligne de commande (changez DATABASE) pour :

<!-- [common] -->
```yaml
    command: odoo --workers 2 -u erplibre_info -d DATABASE
```

<!-- [en] -->
Note, the goal is to call `env['ir.module.module'].update_list()`.

Restart the docker :

<!-- [fr] -->
Note, l'objectif est d'appeler `env['ir.module.module'].update_list()`.

Redémarrez le docker :

<!-- [common] -->
```bash
docker compose down
docker compose up -d
```

<!-- [en] -->
Revert the command in docker-compose.yml.

You can validate in log the update, you need to find `odoo.modules.loading: updating modules list`, check

<!-- [fr] -->
Annulez la commande dans docker-compose.yml.

Vous pouvez valider la mise à jour dans les journaux, vous devez trouver `odoo.modules.loading: updating modules list`, vérifiez

<!-- [common] -->
```bash
docker compose logs -f
```

<!-- [en] -->
## Update all

Do a backup on url https://HOST/web/database/manager

Edit the docker-compose.yml and update the command line (change DATABASE) to :

<!-- [fr] -->
## Tout mettre à jour

Faites une sauvegarde à l'URL https://HOST/web/database/manager

Éditez le docker-compose.yml et mettez à jour la ligne de commande (changez DATABASE) pour :

<!-- [common] -->
```yaml
    command: odoo --workers 2 -u all -d DATABASE
```

<!-- [en] -->
Watch log to see error, if you got error, you need to do some code to migrate your data, depend the case.

<!-- [fr] -->
Surveillez les journaux pour voir les erreurs, si vous obtenez une erreur, vous devez écrire du code pour migrer vos données, selon le cas.

<!-- [common] -->
```bash
make docker_show_logs_live
```
