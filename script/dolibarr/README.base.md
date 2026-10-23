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
| `quality.py` | phpcs and PHPStan on a module, with Dolibarr's own rules |
| `hooks_index.py` | Hooks, contexts and triggers at a version, and the diff between two |
| `core.py` | Core changes: `status`, `start` a work branch, `check` against CONTRIBUTING, `patches` |
| `api.py` | REST API: `enable` (module, read-only user, key), `status`, `disable` |
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
| `quality.py` | phpcs et PHPStan sur un module, avec les règles de Dolibarr |
| `hooks_index.py` | Hooks, contextes et déclencheurs à une version, et le diff entre deux |
| `core.py` | Modifier le cœur : `status`, `start` d'une branche, `check` selon CONTRIBUTING, `patches` |
| `api.py` | API REST : `enable` (module, utilisateur en lecture, clé), `status`, `disable` |
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
./script/dolibarr/debug.py on --instance erp --xdebug    # native development
./script/dolibarr/debug.py tail --instance erp --filter ERR
./script/dolibarr/module.py create --instance erp --name Zorglub --enable
./script/dolibarr/module.py link --instance erp --path ~/src/zorglub
./script/dolibarr/module.py enable --instance erp --name Stock
./script/dolibarr/package.py check --instance erp --name Zorglub
./script/dolibarr/package.py build --instance erp --name Zorglub --dolistore
./script/dolibarr/quality.py --instance erp --name Zorglub [--only phpstan]
./script/dolibarr/hooks_index.py list --kind context --filter '^thirdparty'
./script/dolibarr/hooks_index.py diff --from 23.0.4       # to the pinned commit
./script/dolibarr/core.py start --topic fix-invoice-total
./script/dolibarr/core.py check && ./script/dolibarr/core.py patches
```

<!-- [en] -->
- `debug.py on` shows development features (`MAIN_FEATURES_LEVEL=2`),
  enables DebugBar and Syslog at level 7 (every SQL query), and on a native
  development instance sets `conf.php` to prod=0 and strict mode. The
  previous state is saved once; `off` puts it back row for row. A production
  needs its name retyped: level 7 logs session ids.
- `--xdebug`, on a native development instance, loads Xdebug 3 into that
  instance's PHP-FPM only (an ini under its `run/php.d`, nothing in
  `/etc`), in trigger mode on port 9003: add `?XDEBUG_TRIGGER=1` to the
  address or use the browser's Xdebug helper. The package is installed if
  PHP-FPM cannot load it; a host that already loads it everywhere (Debian
  and Fedora do on install) is not made to load it twice. VS Code gets a
  configuration in the checkout's `.vscode/launch.json`, which Dolibarr's
  `.gitignore` ignores; PhpStorm's settings are printed. The paths are the
  same on both sides, so no mapping is needed.
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
- `quality.py` runs phpcs with Dolibarr's ruleset and PHPStan with its
  `phpstan.neon.dist` (the core scanned for symbols, the CI's bootstrap)
  from the pinned composer image: Docker or Podman, nothing installed on
  the host, the tools cached in a volume named after their versions.
  PHPStan follows the version of Dolibarr's CI; phpcs is the last 3.x,
  which Dolibarr's own sniffs target. The ModuleBuilder template's PHPStan
  baseline follows the renamed module, so a fresh module comes out clean.
  Exit 0 clean, 1 findings, 2 a tool that could not finish. A container
  instance needs the pinned checkout, fetched by
  `script/manifest/update_manifest_local_dolibarr.sh`.
- `hooks_index.py` reads, with `git grep` and without checking anything
  out, the hook names passed to `executeHooks`, the literal contexts of
  `initHooks`, the trigger codes passed to `call_trigger` and the agenda
  codes of `llx_c_action_trigger.sql`; `diff` says what appeared or
  vanished between two versions, what a module must look at before an
  upgrade. The pinned commit is read from the checkout; any other tag,
  branch or commit is fetched once, at depth 1, into
  `~/.erplibre/dolibarr_index.git`, which borrows the checkout's objects:
  the checkout that Google Repo manages is never written.
- `core.py` works on the pinned checkout and nothing leaves this machine:
  no push, no pull request. `start` opens a work branch at the pinned
  commit (`repo start`) and deepens the shallow history; it needs a git
  identity, since `repo sync` silently resets a branch none of whose
  commits carries it (`status` warns about it). `check` applies Dolibarr's
  `CONTRIBUTING.md`: the author's `Signed-off-by` (DCO), a title keyword
  (FIX, CLOSE, NEW, PERF, DOC, QUAL, SEC, in capitals for the ChangeLog),
  neither `ChangeLog` nor a language other than en_US, one fix per pull
  request on a stable branch. `patches` exports the series under
  `private/dolibarr/patches/`. The `ERPLibre/dolibarr` fork does not exist
  yet; `status` says when it answers.

## Integration

<!-- [fr] -->
- `debug.py on` montre les fonctionnalités en développement
  (`MAIN_FEATURES_LEVEL=2`), active DebugBar et Syslog au niveau 7 (chaque
  requête SQL), et en développement natif passe `conf.php` à prod=0 et en
  mode strict. L'état d'avant est gardé une fois ; `off` le remet ligne à
  ligne. Une production exige son nom retapé : le niveau 7 journalise les
  identifiants de session.
- `--xdebug`, sur une instance de développement native, charge Xdebug 3
  dans le PHP-FPM de cette instance seulement (un ini sous son
  `run/php.d`, rien dans `/etc`), en mode déclenché sur le port 9003 :
  ajouter `?XDEBUG_TRIGGER=1` à l'adresse ou passer par l'extension Xdebug
  du navigateur. Le paquet s'installe si PHP-FPM ne peut pas le charger ;
  un hôte qui le charge déjà partout (Debian et Fedora le font à
  l'installation) ne le charge pas deux fois. VS Code reçoit une
  configuration dans `.vscode/launch.json` du checkout, que le
  `.gitignore` de Dolibarr ignore ; les réglages de PhpStorm sont
  affichés. Les chemins sont les mêmes des deux côtés : aucun mappage.
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
- `quality.py` lance phpcs avec les règles de Dolibarr et PHPStan avec son
  `phpstan.neon.dist` (le cœur lu pour ses symboles, l'amorce du CI)
  depuis l'image composer épinglée : Docker ou Podman, rien d'installé sur
  l'hôte, les outils gardés dans un volume nommé d'après leurs versions.
  PHPStan suit la version du CI de Dolibarr ; phpcs est la dernière 3.x,
  celle que visent les règles maison de Dolibarr. La ligne de base PHPStan
  du gabarit du ModuleBuilder suit le module renommé : un module neuf sort
  propre. Sortie 0 propre, 1 constats, 2 un outil qui n'a pu finir. Une
  instance en conteneur demande le checkout épinglé, que récupère
  `script/manifest/update_manifest_local_dolibarr.sh`.
- `hooks_index.py` lit par `git grep`, sans rien extraire, les noms de
  hooks passés à `executeHooks`, les contextes littéraux d'`initHooks`,
  les codes de déclencheurs passés à `call_trigger` et les codes d'agenda
  de `llx_c_action_trigger.sql` ; `diff` dit ce qui apparaît ou disparaît
  entre deux versions, ce qu'un module doit regarder avant une montée.
  Le commit épinglé se lit dans le checkout ; tout autre tag, branche ou
  commit se récupère une fois, à profondeur 1, dans
  `~/.erplibre/dolibarr_index.git`, qui emprunte les objets du checkout :
  celui que gère Google Repo n'est jamais écrit.
- `core.py` travaille le checkout épinglé et rien ne quitte ce poste :
  aucun push, aucune demande de fusion. `start` ouvre une branche de
  travail au commit épinglé (`repo start`) et approfondit l'historique peu
  profond ; il exige une identité git, car `repo sync` remet à zéro sans
  rien dire une branche dont aucun commit ne la porte (`status` le
  signale). `check` applique le `CONTRIBUTING.md` de Dolibarr : le
  `Signed-off-by` de l'auteur (DCO), un mot-clé de titre (FIX, CLOSE, NEW,
  PERF, DOC, QUAL, SEC, en capitales pour le ChangeLog), ni `ChangeLog` ni
  langue autre qu'en_US, un seul correctif par demande sur une branche
  stable. `patches` exporte la série sous `private/dolibarr/patches/`. Le
  fork `ERPLibre/dolibarr` n'existe pas encore ; `status` dit quand il
  répond.

## Intégration

<!-- [common] -->
```bash
./script/dolibarr/api.py enable --instance erp     # --rotate for a new key
./script/dolibarr/api.py status --instance erp
```

<!-- [en] -->
- `api.py enable` turns the REST API module on and creates a technical
  user, `erplibre_api`, holding every read right and nothing else. Its
  `DOLAPIKEY` is drawn by ERPLibre, reaches PHP on stdin only, is stored
  encrypted by Dolibarr and kept in `private/dolibarr/api/<instance>.key`
  (0600). Run again, `enable` keeps the key; `--rotate` draws another one
  and the old one stops working.
- `status` calls `/api/index.php/status` with the key: only the status
  answer counts, since a disabled module answers 200 in plain text. The
  explorer (swagger) is at `/api/index.php/explorer/`. A production needs
  its name retyped to turn the API on or off. Dolibarr 24's MCP server,
  still experimental, comes later.

A Dolibarr website moves to Odoo with the `erplibre_website_import_from_dolibarr` addon: export the site from Dolibarr's Website module, then import the zip from Website › Configuration › Import from Dolibarr, or with `./odoo_bin.sh dolibarr_website_import -d DB --website-id 1 --zip FILE`. The module's README describes the review step and the re-import rules.

## Pinned version

<!-- [fr] -->
- `api.py enable` allume le module API REST et crée un utilisateur
  technique, `erplibre_api`, qui a chaque droit de lecture et aucun autre.
  Sa `DOLAPIKEY` est tirée par ERPLibre, n'atteint PHP que par stdin, est
  gardée chiffrée par Dolibarr et dans `private/dolibarr/api/<instance>.key`
  (0600). Relancé, `enable` garde la clé ; `--rotate` en tire une autre et
  l'ancienne cesse d'ouvrir l'API.
- `status` appelle `/api/index.php/status` avec la clé : seule la réponse
  de statut compte, car un module éteint répond 200 en texte.
  L'explorateur (swagger) est à `/api/index.php/explorer/`. Une production
  exige son nom retapé pour allumer ou éteindre l'API. Le serveur MCP de
  Dolibarr 24, encore expérimental, viendra ensuite.

Un site web Dolibarr passe à Odoo par l'addon `erplibre_website_import_from_dolibarr` : exporter le site depuis le module Site web de Dolibarr, puis importer le zip depuis Site web › Configuration › Import depuis Dolibarr, ou par `./odoo_bin.sh dolibarr_website_import -d DB --website-id 1 --zip FICHIER`. Le README du module décrit l'étape de revue et les règles du réimport.

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
