<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Information about deployment with cloudflare

The script update_dns_cloudflare.py is used to update all DNS for case of DDNS, when ip address change, with a cron. This version support an old version of cloudflare==2.20.0

The script cloudflare_dns.py is used to update specific address at a deployment.

<!-- [fr] -->
# Informations sur le déploiement avec Cloudflare

Le script update_dns_cloudflare.py est utilisé pour mettre à jour tous les DNS dans le cas d'un DDNS, lorsque l'adresse IP change, avec un cron. Cette version supporte une ancienne version de cloudflare==2.20.0

Le script cloudflare_dns.py est utilisé pour mettre à jour une adresse spécifique lors d'un déploiement.

<!-- [en] -->
# erplibre_serve.py — starting a hosted ERPLibre

`erplibre_serve.py --port <port> --etat <state dir>` starts the Odoo of an
ERPLibre checkout from the host's environment, the way a hosting server
provides it. The database connection comes from libpq's variables (`PGHOST`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`, `PGSSLROOTCERT`); the master
password from `ODOO_ADMIN_PASSWD`. The database password never enters the
configuration file. The versions are ERPLibre's own: `.erplibre-version` and
`.odoo-version`, else the default pair of `conf/supported_version_erplibre.json`.

On each start it initialises an empty database, migrates when the code
changed, serves otherwise, and REFUSES an empty database that its state
directory had already initialised: a restore that did not happen must not be
covered by a fresh database.

<!-- [fr] -->
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
