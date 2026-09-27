
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

```bash
./script/dolibarr/install_native.py --mode dev --db mariadb --instance erp --port 8080
./script/dolibarr/run.py start --instance erp
./script/dolibarr/run.py status
./script/dolibarr/run.py logs --instance erp --lines 40
./script/dolibarr/run.py stop --instance erp
```

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

```bash
./script/dolibarr/install_container.py --mode dev --instance erp --port 8081 [--engine podman]
```

L'image officielle `dolibarr/dolibarr` sur MariaDB, avec Docker ou Podman,
celui qui répond sans sudo d'abord ; aucun outil compose n'est requis.
L'image porte la version que publie Docker Hub, parfois en retard sur
l'épinglage natif. Ses données vivent dans des volumes nommés ; `custom/`
est un dossier de l'hôte, inscriptible depuis le conteneur, pour
développer des modules. Les secrets sont des fichiers (0600) de
`~/.local/share/ERPLibre/dolibarr/<instance>/secrets`, montés en lecture
seule. Le premier démarrage prend de 70 à 100 s environ.

## Production

```bash
./script/dolibarr/install_native.py --mode prod --db mariadb --instance erp \
    --domain erp.example.org --tls certbot --email ops@example.org
```

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

```bash
./script/dolibarr/detect.py --local            # or --ssh host (repeatable)
./script/dolibarr/doctor.py --all
./script/dolibarr/backup.py create --instance erp
./script/dolibarr/backup.py restore --instance erp --archive <file> --confirm erp
./script/dolibarr/fleet.py list
./script/dolibarr/fleet.py remove --instance erp --dry-run
./script/dolibarr/upgrade.py --instance erp        # after pin.py update --apply
```

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

```bash
./script/dolibarr/debug.py on --instance erp       # off puts everything back
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

```bash
./script/dolibarr/api.py enable --instance erp     # --rotate for a new key
./script/dolibarr/api.py status --instance erp
```

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

## Version épinglée

```bash
./script/dolibarr/pin.py show
./script/dolibarr/pin.py update                 # dry run: what would change
./script/dolibarr/pin.py update --apply
./script/manifest/update_manifest_local_dolibarr.sh
```

`conf/supported_version_dolibarr.json` et `manifest/git_manifest_dolibarr.xml`
bougent ensemble. L'étiquette de l'image Docker ne suit que si Docker Hub la
publie.

Le checkout appartient à Google Repo : un projet sorti du manifest fusionné
est effacé au sync suivant, `conf.php` compris. ERPLibre fusionne le
manifest Dolibarr d'office dès que `dolibarr/dolibarr` existe, et garde une
copie de `conf.php` dans le dossier d'état de l'instance.