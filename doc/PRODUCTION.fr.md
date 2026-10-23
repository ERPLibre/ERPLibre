
# Guide de production ERPLibre

## Prérequis

- 5 Go d'espace disque

## Procédure d'installation en production

### 1. Cloner le projet :

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

### 2. Modifier les paramètres

Modifiez le fichier env_var.sh pour l'installation en production. Activez nginx si vous avez besoin d'un proxy avec `EL_INSTALL_NGINX` à
True. Redirigez votre DNS vers l'adresse IP du proxy et ajoutez vos enregistrements A et AAAA dans `EL_WEBSITE_NAME` séparés par des espaces.

### 3. Exécuter les scripts :

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

Un service est en cours d'exécution via SystemD. Vous pouvez y accéder avec le nom DNS trouvé dans `env_var.sh`

#### Serveur Ubuntu 24.04

Appliquer le correctif libpng12-0 : https://www.linuxuprising.com/2018/05/fix-libpng12-0-missing-in-ubuntu-1804.html

```bash
./script/install/install_dev.sh
./script/install/install_production.sh
```

Un service est en cours d'exécution via SystemD, vous pouvez y accéder avec le nom DNS trouvé dans `env_var.sh`

### 4. SSL :

Générer un certificat SSL

```bash
sudo certbot --nginx
```

## Consulter les journaux

```bash
sudo systemctl -feu [EL_USER]
```

## Exécuter par adresse IP

Commentez la ligne suivante dans `/[EL_USER]/erplibre/config.conf`

```
xmlrpc_interface = 0.0.0.0
proxy_mode = True
```

Ajoutez votre adresse IP comme server_name dans la configuration nginx `/etc/nginx/sites-available/[EL_WEBSITE_NAME]`

Redémarrer le daemon :

```bash
sudo systemctl restart nginx
sudo systemctl restart [EL_USER]
```

## Exécution en production

```bash
cd /[EL_USER]/erplibre
./run.sh -d [DATABASE] --no-database-list
```

## Déplacer la base de données de production vers le développement

Lorsque vous déplacez une base de données de production vers votre environnement de développement, vous souhaitez supprimer les serveurs de messagerie et installer un utilisateur de test pour tester la base de données. ATTENTION, ceci n'est pas sécuritaire pour la production, vous exposerez toutes les données.

1. Copiez votre image de base de données dans le répertoire image_db, par exemple le nom de l'image est `my_db.zip`
1. Exécutez

```bash
./script/database/db_restore.py --clean_cache --database test_my_db --image my_db
./script/addons/update_prod_to_dev.sh test_my_db
```

## Mise à jour de la production

Mettre à jour toutes les fonctionnalités.

```bash
./run.sh --limit-time-real 99999 --no-http --stop-after-init -u all -d DATABASE
```

### Mettre à jour les modules d'une instance servie par systemd

`script/odoo/update_module.py` arrête l'unité, sauvegarde la base, met à
jour les modules, relance l'unité et vérifie son journal. L'unité est
seulement lue, jamais modifiée, et une unité qui tournait est relancée quoi
qu'il arrive. Toujours simuler d'abord :

```bash
./script/odoo/update_module.py --module 'my_module_*' --db DATABASE --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db DATABASE
```

Après une relance vérifiée, l'outil vérifie la santé de l'instance locale
(voir plus bas ; ses constats sont des avertissements, jamais un échec de
la mise à jour), et `--warmup-deep` préchauffe d'abord les pages publiques
et leurs paquets d'assets.

Le même geste est accessible depuis `make todo` : `Exécuter > Production`.
Options, ordre de détection et codes de sortie :
[script/odoo/README.fr.md](../script/odoo/README.fr.md).

### Sauvegardes vérifiées

`script/database/odoo_backup.py` sauvegarde une base au format zip d'Odoo,
vérifie le fichier, tient une rétention quotidienne, hebdomadaire et
mensuelle, donne l'âge du dernier succès, essaie la restauration dans une
base temporaire et ne restaure que dans une nouvelle base.
`update_module.py` s'en sert pour sa sauvegarde avant une mise à jour, sous
le même verrou de base.

```bash
./script/database/odoo_backup.py --db DATABASE --dry-run
sudo ./script/database/odoo_backup.py --db DATABASE
./script/database/odoo_backup.py --status
sudo ./script/database/odoo_backup.py --test-restore --db DATABASE
```

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

```bash
sudo ./script/systemd/install_backup_timer.py --db DATABASE --dry-run
sudo ./script/systemd/install_backup_timer.py --db DATABASE --copy-to backup@backup.example.org:/srv/backups
systemctl list-timers 'erplibre-backup-*'
sudo ./script/systemd/install_backup_timer.py --db DATABASE --uninstall
```

`--copy-to` ajoute une copie hors site (rsync sur ssh avec la clé du
compte ; le côté distant n'a pas de rétention et grossit). Surveiller
`--status` : il sort en code 1 quand le dernier succès date de plus de
`--max-age` heures (26). Tout cela est aussi dans `make todo` :
`Exécuter > Production`. Détails, règles de rétention et codes de sortie :
[script/database/README.fr.md](../script/database/README.fr.md).

### Journal d'Odoo

`script/odoo/log_check.py` lit le journal de l'instance et dit ce qui mérite
un regard : traces Python groupées par leur exception finale, autres
enregistrements `ERROR`/`CRITICAL`, requêtes SQL refusées, et échecs
d'envoi de courriel classés passagers ou PERMANENTS avec le réglage d'Odoo
à vérifier. Il lit le `logfile` de l'unité quand sa configuration en pose
un, sinon `journalctl` pour l'unité ; `--file` lit n'importe quel fichier
de journal d'Odoo. Les messages connus et sans gravité sont comptés à part,
et `--ignore REGEX` en ajoute de locaux.

```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --since-last --json
```

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

```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
```

Sur un terminal, sans `--resend`, un menu demande lesquels renvoyer (tous,
les plus anciens, des ids choisis, aucun — le défaut). Sans terminal,
`--resend all | oldest N | ids LISTE` exige `--yes`. Codes de sortie : 0
aucun échec ou tous les courriels choisis remis en file, 1 des échecs
restent ou une partie de la sélection est ignorée, 2 refusé ou impossible.
Les deux outils sont dans `make todo` : `Exécuter > Production`. Détails et
matrice Odoo 12 à 18 :
[script/odoo/README.fr.md](../script/odoo/README.fr.md).

### Santé et préchauffage du cache

`script/odoo/health_check.py` vérifie, en lecture seule, qu'une instance
répond et n'expose rien de trop. `--url https://hote` sonde à travers le
proxy inverse, comme un navigateur ; `--local` sonde l'instance de l'unité
systemd détectée, là où Odoo écoute. Chaque vérification dit OK, ATTN, FAIL
ou SKIP avec un conseil d'une ligne : page de connexion, `/web/health`
(SKIP là où la route n'existe pas), certificat TLS (ATTN sous 21 jours,
FAIL sous 7), redirection HTTP vers HTTPS, HSTS, gestionnaire et sélecteur
de bases, chemin du bus derrière le proxy (`/websocket` dès Odoo 16,
`/longpolling/poll` avant), robots.txt, et avec `--mail-domain` les
enregistrements SPF, DMARC (et DKIM avec `--dkim-selector`), lus par `dig`
ou `host`. Aucun identifiant, aucun cookie, aucun service tiers.

```bash
./script/odoo/health_check.py --url https://odoo.example.org --mail-domain example.org
./script/odoo/health_check.py --local --json
./script/odoo/warmup_http.py --deep --local
```

Un déploiement par défaut expose le gestionnaire de bases : Odoo garde
`list_db = True` quand la configuration ne le pose pas, et les gabarits
nginx ne bloquent pas `/web/database`. La vérification rend à juste titre
un FAIL sur `--url` ; poser `list_db = False` dans la configuration d'Odoo,
ou refuser `/web/database` dans nginx. Codes de sortie : 0 aucun FAIL (les
ATTN sont listés), 1 au moins un FAIL, 2 vérification impossible (usage,
détection, configuration illisible : lancer avec sudo).

`script/odoo/warmup_http.py --deep` demande `/web/login`, `/` et au plus
`--max-pages` (20) pages de `/sitemap.xml`, puis les paquets d'assets
qu'elles citent, chacun `--repeat` (4) fois à la fois pour atteindre
plusieurs workers. Avec `--login` et `--api-key-file` (une clé d'API Odoo
lue dans un fichier, jamais sur la ligne de commande), il charge aussi
menus et vues par des appels RPC en lecture seule. Il affiche un bilan et
sort en 0, ou en 1 avec `--strict` quand une requête a échoué. Les trois
gestes sont dans `make todo` : `Exécuter > Production`. Détails et matrice
Odoo 12 à 18 : [script/odoo/README.fr.md](../script/odoo/README.fr.md).

### Audit de performance de l'hôte

`script/proxmox/host_perf_audit.py` mesure, en lecture seule, ce qui
limite les performances de l'hôte — processeur, mémoire, disques, réseau,
ZFS et, sous Proxmox VE, chaque invité — sur une durée choisie, et affiche
un verdict par ressource, la réponse à « des disques SSD sont-ils
justifiés ? » et les réglages à envisager sous forme de commandes, jamais
exécutées. Il est dans `make todo` : `Exécuter > Production` pour ce poste,
et le menu Proxmox VE pour l'hyperviseur retenu. Détails :
[script/proxmox/README.fr.md](../script/proxmox/README.fr.md).

# Postgresql

Pour afficher les fichiers de configuration :
> psql -U postgres -c 'SHOW config_file'

Éditez ce fichier pour accepter les interfaces de tous les réseaux :
> /var/lib/postgres/data/postgresql.conf

# Supprimer une instance en production

ATTENTION, ceci supprimera le répertoire personnel de l'utilisateur, c'est irrévocable.

```bash
./script/database/delete_production.sh
```

# Mettre à jour l'IP lorsque l'IP publique change avec CloudFlare et crontab

Vous avez d'abord besoin d'un interpréteur python3 valide avec le module cloudflare installé : (assurez-vous que votre pip3 pointe vers le bon python3)

```bash
pip3 install cloudflare==2.20.0
```

Ensuite, vous devez créer les fichiers cfg avec les identifiants de votre compte cloudflare.

```bash
mkdir ~/.cloudflare
```

Éditez ~/.cloudflare/cloudflare.cfg

```
[PROFILE_NAME]
email=EMAIL
token=TOKEN (Use the global API key so that it works)
```

Ajoutez votre cron et spécifiez le python3 que vous souhaitez utiliser.
- USER est l'utilisateur local avec les permissions pour exécuter le script
- PATH est le chemin vers l'intérieur du dossier ERPLibre/deployment/
- PROFILE_NAME doit correspondre au PROFILE_NAME dans cloudflare.cfg
- CLOUDFLARE_ZONE_NAME est le nom de la zone du site web sur cloudflare
- DNS_NAME est le nom d'un enregistrement DNS A disponible sur cette zone

Notes :
- Un seul crontab est nécessaire car le script recherchera automatiquement toutes les zones disponibles avec une IP obsolète et les mettra à jour sur tous les enregistrements A.
- À chaque exécution du crontab, si l'IP publique n'a pas changé par rapport à ce qui est sur cloudflare, le script ne fera pas de changements inutiles et laissera tout en l'état.

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync
```

Vérifier les journaux avec

```bash
sudo journalctl -feu cron
```

Si vous souhaitez journaliser ce qui se passe et quand le script est exécuté, comme la journalisation des changements d'IP, vous pouvez ajouter une partie de journalisation à votre cron

```bash
vim /etc/crontab
# Add
*/5 * * * * USER cd PATH && python3 script/deployment/update_dns_cloudflare.py --profile PROFILE_NAME --zone_name CLOUDFLARE_ZONE_NAME --dns_name DNS_NAME --auto_sync > /home/USER/logs/update_dns_ZONE_NAME.log 2>&1

```

Vous pouvez ensuite lire tous les journaux avec cette commande (Nécessite l'installation de ts : sudo apt install moreutils)

```bash
tail -f /home/USER/logs/update_dns_ZONE_NAME.log | ts
```

# Docker

## Mise à jour

Lors de la mise à jour d'un docker, vous devez mettre à jour la liste des modules.

Exécutez le script pour mettre à jour la configuration :

```bash
./script/docker/docker_gen_config.sh
```

Éditez le docker-compose.yml et mettez à jour la ligne de commande (changez DATABASE) pour :

```yaml
    command: odoo --workers 2 -u erplibre_info -d DATABASE
```

Note, l'objectif est d'appeler `env['ir.module.module'].update_list()`.

Redémarrez le docker :

```bash
docker compose down
docker compose up -d
```

Annulez la commande dans docker-compose.yml.

Vous pouvez valider la mise à jour dans les journaux, vous devez trouver `odoo.modules.loading: updating modules list`, vérifiez

```bash
docker compose logs -f
```

## Tout mettre à jour

Faites une sauvegarde à l'URL https://HOST/web/database/manager

Éditez le docker-compose.yml et mettez à jour la ligne de commande (changez DATABASE) pour :

```yaml
    command: odoo --workers 2 -u all -d DATABASE
```

Surveillez les journaux pour voir les erreurs, si vous obtenez une erreur, vous devez écrire du code pour migrer vos données, selon le cas.

```bash
make docker_show_logs_live
```