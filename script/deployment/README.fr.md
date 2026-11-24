
# Informations sur le déploiement avec Cloudflare

Le script update_dns_cloudflare.py est utilisé pour mettre à jour tous les DNS dans le cas d'un DDNS, lorsque l'adresse IP change, avec un cron. Cette version supporte une ancienne version de cloudflare==2.20.0

Le script cloudflare_dns.py est utilisé pour mettre à jour une adresse spécifique lors d'un déploiement.

# erplibre_serve.py — démarrer un ERPLibre hébergé

`erplibre_serve.py --port <port> --etat <dossier d'état>` démarre l'Odoo d'un
dépôt ERPLibre depuis l'environnement de l'hôte, tel qu'un serveur d'hébergement
le fournit. La connexion à la base vient des variables de libpq (`PGHOST`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`, `PGSSLROOTCERT`) ; le mot de
passe maître de `ODOO_ADMIN_PASSWD`. Le mot de passe de la base n'entre jamais
dans le fichier de configuration. Les versions sont celles d'ERPLibre :
`.erplibre-version` et `.odoo-version`, sinon le couple par défaut de
`conf/supported_version_erplibre.json`.

À chaque démarrage, il initialise une base vide, migre quand le code a changé,
sert sinon, et REFUSE une base vide que son dossier d'état avait déjà
initialisée : une restauration qui n'a pas eu lieu ne doit pas être couverte
par une base neuve.

# erplibre_dist.py — construire un ERPLibre autonome

`erplibre_dist.py --racine <dépôt ERPLibre> --sortie <dossier>` fait d'un
ERPLibre installé UN dossier qui s'installe sans index, pour un serveur
d'hébergement qui lit une application dans un seul dépôt. Figer d'abord :
`make repo_configure_all FREEZE=1` met chaque projet sur son commit figé, et
la construction refuse un projet qui suit encore sa branche.

Le dossier porte l'arbre Odoo de la version, tiré de chaque commit figé par
`git archive` (ni `.git`, ni fichier non commité ou ignoré) et sans modules
propriétaires (OPL-1, OEEL-1, « Other proprietary »), une roue par dépendance
dans `roues/` (celles installées depuis git comprises) avec
`requirements.lock.txt` qui nomme chacune par son sha256,
les fichiers de version d'ERPLibre, un `config.conf` dont l'`addons_path` est
relatif, le lanceur `erplibre_serve.py`, et `PROVENANCE.lock` (le commit de
chaque projet et les modules exclus). La construction finit par une épreuve :
un venv neuf, installé en `--no-index --require-hashes`, doit initialiser
`base` dans une base jetable. Les roues construites depuis les sources lient
les bibliothèques de l'hôte de construction (libpq, libldap…) : la cible
exécute le même système.

`--figer` fige d'abord. `--detache <journal>` lance la construction dans sa
propre session et suit le journal jusqu'au verdict : une connexion perdue
n'arrête que le suivi, et la même commande le reprend. TODO joue les deux sur
la cible SSH retenue par `Deploy › SSH › Construire le livrable hors ligne`
(`make ssh_dist`, sortie dans `SSH_DIST`, `~/erplibre-dist` par défaut) —
une machine de construction, puisque ses dépôts sont figés. La sortie est
vidée avant chaque construction, sauf son `.git`, et seulement si c'est un
livrable précédent qui ne chevauche pas le checkout.