<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Dolibarr

ERPLibre installs and runs [Dolibarr](https://www.dolibarr.org/), the PHP
ERP, next to Odoo. The Dolibarr version is pinned: a commit of the official
repository, fetched by Google Repo into `dolibarr/dolibarr`.

From TODO:

- `Installation › Dolibarr` installs an instance;
- `Execute › Dolibarr` starts, stops and follows development instances, and
  moves the pinned commit.

Each TODO entry runs a script of this directory with its parameters; every
script also runs on its own.

## Scripts

| Script | Role |
|--------|------|
| `install_native.py` | Installs an instance with nginx, PHP-FPM and MariaDB or PostgreSQL |
| `install_container.py` | Installs a development instance in Docker or Podman containers |
| `native_prod.py` | Production steps, played by `install_native.py --mode prod` |
| `run.py` | `start`, `stop`, `status`, `logs` of a development instance |
| `pin.py` | `show` the pinned commit, `update` it (dry run unless `--apply`) |
| `detect.py` | Find Dolibarr installations on this machine or over SSH |
| `doctor.py` | Health, security and integrity of each registered instance |
| `backup.py` | `create`, `list` and `restore` backups (restore: `restore.py`) |
| `fleet.py` | `list` the instances, `remove` one |
| `upgrade.py` | Upgrade an instance to the pinned version, rollback on failure |
| `debug.py` | Debug profile of an instance `on`/`off`, `status`, `tail` of its log |
| `module.py` | `create`, `link`, `enable`, `disable` the modules of a development instance |
| `package.py` | `check` a module against DoliStore's rules, `build` its zip |
| `lib_dolibarr.py` | Pure decisions: pin, names, what the host allows |
| `packages.py` | Package names and paths per distribution family |
| `web_config.py`, `units.py`, `install_files.py` | Pure rendering of the nginx, PHP-FPM, systemd and install files |
| `container_plan.py` | Pure rendering of the Docker/Podman commands of an instance |
| `integrity.py` | Installed code against the archive of its pinned commit |

Supported families: Debian/Ubuntu (apt), Fedora/EL (dnf), Arch (pacman),
openSUSE (zypper).

## Development

<!-- [fr] -->
# Dolibarr

ERPLibre installe et fait tourner [Dolibarr](https://www.dolibarr.org/),
l'ERP en PHP, à côté d'Odoo. La version de Dolibarr est épinglée : un commit
du dépôt officiel, que Google Repo récupère dans `dolibarr/dolibarr`.

Depuis TODO :

- `Installation › Dolibarr` installe une instance ;
- `Exécution › Dolibarr` lance, arrête et suit les instances de
  développement, et relève le commit épinglé.

Chaque entrée de TODO lance un script de ce dossier avec ses paramètres ;
chaque script se lance aussi seul.

## Scripts

| Script | Rôle |
|--------|------|
| `install_native.py` | Installe une instance avec nginx, PHP-FPM et MariaDB ou PostgreSQL |
| `install_container.py` | Installe une instance de développement en conteneurs Docker ou Podman |
| `native_prod.py` | Étapes de production, jouées par `install_native.py --mode prod` |
| `run.py` | `start`, `stop`, `status`, `logs` d'une instance de développement |
| `pin.py` | `show` le commit épinglé, `update` le relève (à blanc sans `--apply`) |
| `detect.py` | Trouver les installations Dolibarr, sur ce poste ou par SSH |
| `doctor.py` | Santé, sécurité et intégrité de chaque instance inscrite |
| `backup.py` | `create`, `list` et `restore` des sauvegardes (restauration : `restore.py`) |
| `fleet.py` | `list` des instances, `remove` d'une instance |
| `upgrade.py` | Monter une instance à la version épinglée, retour arrière sur échec |
| `debug.py` | Profil de déverminage d'une instance `on`/`off`, `status`, `tail` de son journal |
| `module.py` | `create`, `link`, `enable`, `disable` les modules d'une instance de développement |
| `package.py` | `check` d'un module selon les règles de DoliStore, `build` de son zip |
| `lib_dolibarr.py` | Décisions pures : épinglage, noms, ce que l'hôte permet |
| `packages.py` | Noms de paquets et chemins par famille de distribution |
| `web_config.py`, `units.py`, `install_files.py` | Rendu pur des fichiers nginx, PHP-FPM, systemd et d'installation |
| `container_plan.py` | Rendu pur des commandes Docker/Podman d'une instance |
| `integrity.py` | Code installé contre l'archive de son commit épinglé |

Familles prises en charge : Debian/Ubuntu (apt), Fedora/EL (dnf), Arch
(pacman), openSUSE (zypper).

## Développement

<!-- [common] -->
```bash
./script/dolibarr/install_native.py --mode dev --db mariadb --instance erp --port 8080
./script/dolibarr/run.py start --instance erp
./script/dolibarr/run.py status
./script/dolibarr/run.py logs --instance erp --lines 40
./script/dolibarr/run.py stop --instance erp
```

<!-- [en] -->
nginx and PHP-FPM run under your own account on `127.0.0.1:<port>`; nothing
goes to `/etc`. The code is the checkout itself, so a change in
`dolibarr/dolibarr/htdocs` shows on the next page load. Everything else of
the instance lives in `~/.local/share/ERPLibre/dolibarr/<instance>`:
documents, `run/` (pid, socket, logs) and `secrets.env` (0600: database and
administrator passwords).

The administrator password is asked by TODO, or generated when left empty.
On the command line it comes from the `EL_DOLIBARR_ADMIN_PASSWORD`
environment variable, never from an argument.

## Containers (development)

<!-- [fr] -->
nginx et PHP-FPM tournent sous votre compte sur `127.0.0.1:<port>` ; rien ne
va dans `/etc`. Le code est le checkout lui-même : une modification dans
`dolibarr/dolibarr/htdocs` se voit au chargement suivant. Le reste de
l'instance vit dans `~/.local/share/ERPLibre/dolibarr/<instance>` :
documents, `run/` (pid, socket, journaux) et `secrets.env` (0600 : mots de
passe de la base et de l'administrateur).

Le mot de passe administrateur est demandé par TODO, ou généré s'il reste
vide. En ligne de commande, il vient de la variable d'environnement
`EL_DOLIBARR_ADMIN_PASSWORD`, jamais d'un argument.

## Conteneurs (développement)

<!-- [common] -->
```bash
./script/dolibarr/install_container.py --mode dev --instance erp --port 8081 [--engine podman]
```

<!-- [en] -->
The official `dolibarr/dolibarr` image on MariaDB, with Docker or Podman,
whichever answers without sudo first; no compose tool is needed. The image
runs the version Docker Hub publishes, which can trail the native pin. Its
data lives in named volumes; `custom/` is a host directory, writable from
the container, for module development. Secrets are files (0600) in
`~/.local/share/ERPLibre/dolibarr/<instance>/secrets`, passed to the
containers read-only. The first start takes about 70 to 100 s.

## Production

<!-- [fr] -->
L'image officielle `dolibarr/dolibarr` sur MariaDB, avec Docker ou Podman,
celui qui répond sans sudo d'abord ; aucun outil compose n'est requis.
L'image porte la version que publie Docker Hub, parfois en retard sur
l'épinglage natif. Ses données vivent dans des volumes nommés ; `custom/`
est un dossier de l'hôte, inscriptible depuis le conteneur, pour
développer des modules. Les secrets sont des fichiers (0600) de
`~/.local/share/ERPLibre/dolibarr/<instance>/secrets`, montés en lecture
seule. Le premier démarrage prend de 70 à 100 s environ.

## Production

<!-- [common] -->
```bash
./script/dolibarr/install_native.py --mode prod --db mariadb --instance erp \
    --domain erp.example.org --tls certbot --email ops@example.org
```

<!-- [en] -->
Production needs systemd and a domain name. Layout of an instance `<i>`:

- code: `/opt/erplibre-dolibarr/<i>`, exported from the pinned commit,
  owned by root and read-only;
- data: `/var/lib/erplibre-dolibarr/<i>` (documents, sessions), owned by the
  system account `dolibarr_<i>`;
- secrets, cron key, copy of `conf.php`, local certificate:
  `/etc/erplibre-dolibarr/<i>`, root, 0700;
- PHP-FPM: one pool under `dolibarr_<i>`, whose socket only nginx reads;
- nginx: one site where the distribution keeps them;
- scheduled jobs: `erplibre-dolibarr-cron-<i>.timer` runs Dolibarr's jobs
  every 5 minutes.

`conf.php` ends read-only for the instance account, with `prod` on.
`--tls` chooses the certificate: `certbot` (Let's Encrypt, public name;
certbot is installed, from EPEL on EL), `local` (for tests: signed by the
local authority of the reverse proxy, `~/.erplibre/reverse_proxy_tls/ca.crt`,
imported once in the browser) or `none` (HTTP only). Each nginx site closes
the connection on any host name but its own.

Every secret is written to `secrets.env` before the database is touched: an
install stopped by an error resumes with the same passwords when run again.

Known limit: SELinux in enforcing mode is refused until its contexts are
set.

## Operations

<!-- [fr] -->
La production exige systemd et un nom de domaine. Disposition d'une
instance `<i>` :

- code : `/opt/erplibre-dolibarr/<i>`, exporté du commit épinglé, à root et
  en lecture seule ;
- données : `/var/lib/erplibre-dolibarr/<i>` (documents, sessions), au
  compte système `dolibarr_<i>` ;
- secrets, clé cron, copie de `conf.php`, certificat local :
  `/etc/erplibre-dolibarr/<i>`, root, 0700 ;
- PHP-FPM : un pool sous `dolibarr_<i>`, dont seul nginx lit la socket ;
- nginx : un site là où la distribution les range ;
- tâches planifiées : `erplibre-dolibarr-cron-<i>.timer` lance les tâches
  de Dolibarr toutes les 5 minutes.

`conf.php` finit en lecture seule pour le compte de l'instance, `prod`
allumé. `--tls` choisit le certificat : `certbot` (Let's Encrypt, nom
public ; certbot est installé, depuis EPEL sur EL), `local` (pour les
essais : signé par l'autorité locale du mandataire inverse,
`~/.erplibre/reverse_proxy_tls/ca.crt`, importée une fois dans le
navigateur) ou `none` (HTTP seul). Chaque site nginx ferme la connexion sur
tout autre nom que le sien.

Chaque secret est écrit dans `secrets.env` avant que la base soit touchée :
une installation arrêtée par une erreur reprend, relancée, avec les mêmes
mots de passe.

Limite connue : SELinux en mode enforcing est refusé tant que ses contextes
ne sont pas posés.

## Exploitation

<!-- [common] -->
```bash
./script/dolibarr/detect.py --local            # or --ssh host (repeatable)
./script/dolibarr/doctor.py --all
./script/dolibarr/backup.py create --instance erp
./script/dolibarr/backup.py restore --instance erp --archive <file> --confirm erp
./script/dolibarr/fleet.py list
./script/dolibarr/fleet.py remove --instance erp --dry-run
./script/dolibarr/upgrade.py --instance erp        # after pin.py update --apply
```

<!-- [en] -->
- `detect.py` sends a read-only POSIX sh probe (one round trip, no
  privilege) and reports each installation and Dolibarr container, never a
  password; reports go to `private/dolibarr/inventory/`.
- `doctor.py` checks what each instance serves, its code (production: every
  file against the pinned archive, where an added PHP file fails), its
  `conf.php`, its install lock, its cron timer and PHP; it changes nothing.
- A backup holds the database, `documents/`, `custom/` and `conf.php`, whose
  instance key encrypts values in the database; 0600, under
  `private/dolibarr/backups/`. Restoring asks for the instance name, takes a
  safety backup first, refuses a backup newer than the code, and also
  clones a backup into a freshly installed instance.
- Removing an instance shows its plan first and asks for its name; a
  container's `custom/` stays.
- `upgrade.py` brings an instance to the pinned version after `pin.py
  update --apply`: backup first, one major version at a time, success
  judged by `MAIN_VERSION_LAST_UPGRADE` and not by exit codes alone, and on
  failure the old code (or image) and the backup come back. A new commit
  of the same version is upgraded too: its schema can differ. The full
  output of each upgrade goes to `private/dolibarr/upgrades/`, and
  `doctor.py` warns when an instance is behind the pin.

## Development tools

<!-- [fr] -->
- `detect.py` envoie une sonde POSIX sh en lecture seule (un aller-retour,
  aucun privilège) et rapporte chaque installation et conteneur Dolibarr,
  jamais un mot de passe ; rapports sous `private/dolibarr/inventory/`.
- `doctor.py` vérifie ce que sert chaque instance, son code (en production,
  chaque fichier contre l'archive épinglée : un PHP ajouté échoue), son
  `conf.php`, son verrou, sa minuterie cron et PHP ; il ne change rien.
- Une sauvegarde porte la base, `documents/`, `custom/` et `conf.php`, dont
  la clé d'instance chiffre des valeurs en base ; 0600, sous
  `private/dolibarr/backups/`. Restaurer demande le nom de l'instance,
  prend d'abord une sauvegarde de sûreté, refuse une sauvegarde plus récente
  que le code, et clone aussi une sauvegarde dans une instance neuve.
- Retirer une instance montre d'abord son plan et demande son nom ; le
  `custom/` d'un conteneur reste.
- `upgrade.py` amène une instance à la version épinglée après `pin.py
  update --apply` : sauvegarde d'abord, un saut majeur à la fois, réussite
  jugée par `MAIN_VERSION_LAST_UPGRADE` et non par les seuls codes de
  sortie, et sur échec l'ancien code (ou l'ancienne image) et la sauvegarde
  reviennent. Un nouveau commit de même version se monte aussi : son schéma
  peut différer. La sortie complète de chaque montée va dans
  `private/dolibarr/upgrades/`, et `doctor.py` avertit quand une instance
  est en retard sur l'épinglage.

## Outils de développement

<!-- [common] -->
```bash
./script/dolibarr/debug.py on --instance erp       # off puts everything back
./script/dolibarr/debug.py tail --instance erp --filter ERR
./script/dolibarr/module.py create --instance erp --name Zorglub --enable
./script/dolibarr/module.py link --instance erp --path ~/src/zorglub
./script/dolibarr/module.py enable --instance erp --name Stock
./script/dolibarr/package.py check --instance erp --name Zorglub
./script/dolibarr/package.py build --instance erp --name Zorglub --dolistore
```

<!-- [en] -->
- `debug.py on` shows development features (`MAIN_FEATURES_LEVEL=2`),
  enables DebugBar and Syslog at level 7 (every SQL query), and on a native
  development instance sets `conf.php` to prod=0 and strict mode. The
  previous state is saved once; `off` puts it back row for row. A production
  needs its name retyped: level 7 logs session ids.
- `module.py create` does what the ModuleBuilder's "New module" does, from
  the instance's own template, so the module goes on in the ModuleBuilder.
  It lands in `custom/` (the checkout's `htdocs/custom`, or the host
  directory mounted in the container) with the first free ID from 500000;
  IDs from 100000 to 499999 are reserved on the Dolibarr wiki. The author
  comes from `--author` or git.
- `module.py link` symlinks a module kept in its own repository into
  `htdocs/custom` (native only: a container sees only its `custom/`).
  `enable` and `disable` go through Dolibarr, dependencies and permissions
  included. A production is refused: it receives a package.
- `package.py build` writes `<module>/bin/module_<name>-<version>.zip` as
  the ModuleBuilder's "Generate package" does; Dolibarr's "Deploy an
  external module" page takes it as is. A broken descriptor, a version
  that is not numeric or a PHP syntax error blocks the zip. `check` also
  applies DoliStore's rules: an ID from 95000 to 499999 (500000 and up is
  never distributed), a complete en_US, pages that try `main.inc.php` in
  several places, `#!/usr/bin/env php` on scripts, no copy of a core file;
  `--dolistore` makes them block the zip. "Dolibarr" as a word of the name
  and an empty editor are warnings.

## Pinned version

<!-- [fr] -->
- `debug.py on` montre les fonctionnalités en développement
  (`MAIN_FEATURES_LEVEL=2`), active DebugBar et Syslog au niveau 7 (chaque
  requête SQL), et en développement natif passe `conf.php` à prod=0 et en
  mode strict. L'état d'avant est gardé une fois ; `off` le remet ligne à
  ligne. Une production exige son nom retapé : le niveau 7 journalise les
  identifiants de session.
- `module.py create` fait ce que fait « Nouveau module » du ModuleBuilder,
  depuis le gabarit de l'instance elle-même : le module se poursuit dans le
  ModuleBuilder. Il naît dans `custom/` (`htdocs/custom` du checkout, ou le
  dossier de l'hôte monté dans le conteneur) avec le premier numéro libre
  dès 500000 ; de 100000 à 499999, les numéros se réservent sur le wiki de
  Dolibarr. L'auteur vient de `--author` ou de git.
- `module.py link` pose dans `htdocs/custom` le lien d'un module tenu dans
  son propre dépôt (natif seulement : un conteneur ne voit que son
  `custom/`). `enable` et `disable` passent par Dolibarr, dépendances et
  droits compris. Une production est refusée : elle reçoit un paquet.
- `package.py build` écrit `<module>/bin/module_<nom>-<version>.zip` comme
  « Générer le paquet » du ModuleBuilder ; la page « Déployer un module
  externe » de Dolibarr le prend tel quel. Un descripteur cassé, une
  version non numérique ou une erreur de syntaxe PHP bloquent le zip.
  `check` applique aussi les règles de DoliStore : un numéro de 95000 à
  499999 (500000 et plus ne se distribue jamais), un en_US complet, des
  pages qui essaient `main.inc.php` à plusieurs endroits,
  `#!/usr/bin/env php` en tête des scripts, aucune copie d'un fichier du
  cœur ; `--dolistore` les rend bloquantes. « Dolibarr » comme mot du nom
  et un éditeur vide sont des avis.

## Version épinglée

<!-- [common] -->
```bash
./script/dolibarr/pin.py show
./script/dolibarr/pin.py update                 # dry run: what would change
./script/dolibarr/pin.py update --apply
./script/manifest/update_manifest_local_dolibarr.sh
```

<!-- [en] -->
`conf/supported_version_dolibarr.json` and `manifest/git_manifest_dolibarr.xml`
move together. The Docker image tag follows only when Docker Hub publishes
it.

The checkout belongs to Google Repo: a project dropped from the merged
manifest is deleted at the next sync, `conf.php` included. ERPLibre merges
the Dolibarr manifest automatically as soon as `dolibarr/dolibarr` exists,
and keeps a copy of `conf.php` in the instance's state directory.

<!-- [fr] -->
`conf/supported_version_dolibarr.json` et `manifest/git_manifest_dolibarr.xml`
bougent ensemble. L'étiquette de l'image Docker ne suit que si Docker Hub la
publie.

Le checkout appartient à Google Repo : un projet sorti du manifest fusionné
est effacé au sync suivant, `conf.php` compris. ERPLibre fusionne le
manifest Dolibarr d'office dès que `dolibarr/dolibarr` existe, et garde une
copie de `conf.php` dans le dossier d'état de l'instance.
