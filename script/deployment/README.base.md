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

<!-- [en] -->
# erplibre_dist.py — building a self-contained ERPLibre

`erplibre_dist.py --racine <ERPLibre checkout> --sortie <dir>` turns an
installed ERPLibre into ONE directory that installs without an index, for a
hosting server that reads an application from a single repository. Freeze the
checkout first: `make repo_configure_all FREEZE=1` puts every project on its
frozen commit, and the build refuses a project that still follows its branch.

The directory holds the Odoo tree of the version without `.git` and without
proprietary modules (OPL-1, OEEL-1, « Other proprietary »), one wheel per
dependency in `roues/` with `requirements.lock.txt` naming each by its
sha256, ERPLibre's version files, a `config.conf` whose `addons_path` is
relative, the `erplibre_serve.py` launcher, and `PROVENANCE.lock` (the
commit of each project and the excluded modules). The build ends with a
proof: a fresh venv installed with `--no-index --require-hashes` must
initialise `base` in a throwaway database. Wheels built from source link the
build host's libraries (libpq, libldap…): the target runs the same system.

`--figer` runs the freeze first. `--detache <journal>` runs the build in its
own session and follows the journal to the verdict: a dropped connection
stops only the follow-up, and the same command resumes it. TODO runs both on
the selected SSH target with `Deploy › SSH › Build the offline bundle`
(`make ssh_dist`, output in `SSH_DIST`, `~/erplibre-dist` by default) — a
build machine, since its repositories are frozen.

<!-- [fr] -->
# erplibre_dist.py — construire un ERPLibre autonome

`erplibre_dist.py --racine <dépôt ERPLibre> --sortie <dossier>` fait d'un
ERPLibre installé UN dossier qui s'installe sans index, pour un serveur
d'hébergement qui lit une application dans un seul dépôt. Figer d'abord :
`make repo_configure_all FREEZE=1` met chaque projet sur son commit figé, et
la construction refuse un projet qui suit encore sa branche.

Le dossier porte l'arbre Odoo de la version, sans `.git` ni modules
propriétaires (OPL-1, OEEL-1, « Other proprietary »), une roue par dépendance
dans `roues/` avec `requirements.lock.txt` qui nomme chacune par son sha256,
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
une machine de construction, puisque ses dépôts sont figés.
