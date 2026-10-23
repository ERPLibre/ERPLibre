<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Improve Odoo: ERPLibre's Odoo fork

Each `odooX.0/odoo` checkout is the branch `ERPLibre/X.0` of the repository
ERPLibre/odoo. This page lists what that branch adds to Odoo, version by
version, and where each addition lives: in the Odoo core, or in a module.

## Upstream: OCA/OCB

The fork follows OCA/OCB, the community branch of Odoo, not Odoo itself. The
manifest says so with three attributes on the `odooX.0/odoo` project:

<!-- [fr] -->
# Améliorer Odoo : le fork Odoo d'ERPLibre

Chaque checkout `odooX.0/odoo` est la branche `ERPLibre/X.0` du dépôt
ERPLibre/odoo. Cette page liste ce que cette branche ajoute à Odoo, version
par version, et où vit chaque ajout : dans le cœur d'Odoo, ou dans un module.

## En amont : OCA/OCB

Le fork suit OCA/OCB, la branche communautaire d'Odoo, et non Odoo lui-même.
Le manifeste le dit par trois attributs du projet `odooX.0/odoo` :

<!-- [common] -->
```xml
<project
    name="odoo.git"
    path="odoo18.0/odoo"
    remote="ERPLibre_origin_odoo"
    fork-upstream-remote="OCA"
    fork-upstream-name="OCB.git"
    fork-upstream="18.0"
    revision="ERPLibre/18.0"
/>
```

<!-- [en] -->
What the fork carries on top of OCB, once the `OCA` remote is fetched:

<!-- [fr] -->
Ce que le fork porte par-dessus OCB, une fois le remote `OCA` récupéré :

<!-- [common] -->
```bash
git -C odoo18.0/odoo log --oneline OCA/18.0..ERPLibre/18.0
git -C odoo18.0/odoo diff --stat OCA/18.0 ERPLibre/18.0
```

<!-- [en] -->
Bringing OCB's new commits into the fork is an **upgrade**, described in
[GIT_REPO.md, "Update or upgrade"](./GIT_REPO.md#update-or-upgrade).

## Policy

The core diverges from OCB only where a module cannot do the job. Every other
change lives in a module. The command line commands live in the module
`erplibre_odoo_cli_base`, in the repository `ERPLibre_erplibre_addons`
(`odooX.0/addons/ERPLibre_erplibre_addons`). The module is never installed
(`installable: False`): it only carries a `cli/` package, which `odoo-bin`
imports before it runs a command.

A smaller core diff means fewer conflicts at each OCB upgrade, and a core that
any OCB user recognises.

## Matrix

`core`: the patch is a commit of the fork. `module`: the feature comes from
`erplibre_odoo_cli_base`, the fork does not carry it. `OCB`: OCB already
behaves this way, no patch is needed. `-`: absent.

| Patch | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|
| P1 uninstall from the command line | core | core | core | core | module | module | module |
| P2 `db` command | core | core | core | core | module | module | module |
| P3 `i18n` command | core | core | core | core | module | module | module |
| P4 install and apply a theme | core | core | core | core | module | module | module |
| P5 Message-ID `erplibre` | - | - | - | - | core | core | core |
| P6 push notification error hidden | - | - | - | - | - | - | core |
| P7 `partner_autocomplete` not auto-installed | - | core | - | - | core | OCB | OCB |
| P8 `web_unsplash` not auto-installed | core | core | core | core | - | - | - |
| P9 login without trailing spaces | core | core | core | core | - | - | - |
| P10 fixes of one version | core | - | core | core | - | - | - |

From 16 to 18, P1 to P4 come from `erplibre_odoo_cli_base`: the 16 fork is
OCB plus P5 and P7, the 17 fork is OCB plus P5, the 18 fork is OCB plus P5 and
P6. In 12 to 15, P1 to P4 stay in the core.

## The patches

### P1 Uninstall from the command line

When a module breaks the web client, the interface that would uninstall it no
longer loads. The command line uninstalls the listed modules and every
installed module that depends on them.

- 12 to 15: server option `--uninstall a,b`, in `odoo/modules/loading.py`
  and `odoo/tools/config.py`. In 14 and 15, a follow-up hides an empty
  option value.
- 16 to 18: `odoo_bin.sh module uninstall -d DB a,b`, from the module. Only
  modules in the `installed` state are uninstalled, as before.

### P2 The `db` command

OCB's `db` command loads, dumps, duplicates, renames and drops a database. The
ERPLibre command also restores an image of `./image_db/`, creates an
initialised database (language, admin login and password, country), lists the
databases and prints the Odoo version. The master password comes from the
`MASTER_PWD` environment variable: an argument is readable by every user of
the machine in `/proc`.

- 12 to 15: `odoo/cli/db.py` replaced by a command with flags (`--restore`,
  `--restore_image`, `--clone`, `--create`, `--backup`, `--drop`, `--list`,
  `--list_incompatible_db`, `--version`).
- 16 to 18: `odoo/cli/db.py` is OCB's. The module's `db` inherits it and adds
  `create`, `list`, `list-incompatible`, `version`, `--image` on `load` and
  `dump`, and a `drop` that checks the master password. On 16 and 17, whose
  OCB `load` has no `--move`, the module adds it.

### P3 The `i18n` command

Writes the `.pot` and the `.po` of an installed module into a directory, for
translators, without the interface.

- 12 to 15: `odoo/cli/i18n.py`.
- 16 to 18: the module's `i18n`, same options.

### P4 Install and apply a theme

Installing a theme module with `-i` does not apply it to the website: the
website's "Choose theme" button does that (copy the theme's views onto the
website, set it as the website's theme).

- 12 to 15: server option `--install-theme theme_x`, in
  `odoo/modules/loading.py` and `odoo/tools/config.py`. 12 fixes the
  option's empty default; 14 and 15 hide an empty value.
- 16 to 18: `odoo_bin.sh theme apply -d DB theme_x`, from the module. A theme
  the database does not list yet is found after refreshing the module list.
  The module installs the theme when needed, then calls the button's own
  method; on 16, whose button builds the website editor URL from the HTTP
  request, it runs the button's steps without that last one.

### P5 Message-ID `erplibre`

`odoo/tools/mail.py` builds the Message-ID of the e-mails Odoo sends. The
patch writes `erplibre` where Odoo writes `openerp`. It stays in the core: the
function is a module-level helper that the mail code calls directly.

- 16, 17, 18: one line of `odoo/tools/mail.py`.

### P6 Push notification error hidden

When the browser refuses push notifications, the mail web client shows a
sticky red notification at every load. The patch keeps the console warning
and drops the notification. It stays in the core: the call sits in the middle
of a patched method of the web client.

- 18: `addons/mail/static/src/webclient/web/webclient.js`.

### P7 `partner_autocomplete` not auto-installed

`partner_autocomplete` sends partner data to an Odoo IAP service. The patch
sets `auto_install: False`.

- 13: `iap` and `partner_autocomplete`; 16: `partner_autocomplete`.
- 17 and 18: OCB already sets `auto_install: False`; no patch.

### P8 `web_unsplash` not auto-installed

`web_unsplash` calls the Unsplash service from the image dialogs. The patch
sets `auto_install: False` in `addons/web_unsplash/__manifest__.py`.

- 12 to 15.

### P9 Login without trailing spaces

A mobile keyboard's autocompletion adds a space after the login. Login and
password reset strip it (`addons/web/controllers/main.py`,
`addons/auth_signup/models/res_users.py`).

- 12 to 15.

### P10 Fixes of one version

| Version | Commit | Change |
|---|---|---|
| 12 | e8e18c1b | `exec_pg_command` works with PostgreSQL 17 client tools (`odoo/tools/misc.py`) |
| 12 | 441ecac1 | `website_event` geolocation checks the event before using it |
| 12 | 43562f2c | `website`: header option for the navbar height |
| 12 | cd16be9b | `abstract_field.js` checks that a field is focusable |
| 12 | 7d5cfeef | `requirements.txt` aligned with OCA |
| 12 | c051702e | sale report: no salesperson line when it is empty |
| 12 | 64a5dd16 | sale portal: product error shown instead of an endless loading |
| 14 | 4d166425 | web: an image that cannot be shown is hidden |
| 14 | b9f96122, 136c1b1a | `packaging` instead of the deprecated `distutils` versions |
| 14, 15 | 0bbc0c2f, e9f9d7af | mail: `fr_CA` translation of the sent e-mails |
| 14, 15 | afc23de6, 3549b881 | mail: CC and TO fields for `mail_thread_cc` |
| 14, 15 | eb61b7a4, dab04fe5 | mail: suggested recipient name formatted |

## The command line module

`./odoo_bin.sh` is the entry point. Old flag syntax and new syntax:

<!-- [fr] -->
Faire entrer les nouveaux commits d'OCB dans le fork est une **mise à
niveau**, décrite dans
[GIT_REPO.fr.md, « Mise à jour ou mise à niveau »](./GIT_REPO.fr.md#mise-à-jour-ou-mise-à-niveau).

## Principe

Le cœur ne s'écarte d'OCB que là où un module ne peut pas faire le travail.
Tout autre changement vit dans un module. Les commandes de ligne de commande
vivent dans le module `erplibre_odoo_cli_base`, du dépôt
`ERPLibre_erplibre_addons` (`odooX.0/addons/ERPLibre_erplibre_addons`). Le
module ne s'installe jamais (`installable: False`) : il ne porte qu'un paquet
`cli/`, que `odoo-bin` importe avant de lancer une commande.

Un écart plus petit, c'est moins de conflits à chaque mise à niveau d'OCB, et
un cœur que tout utilisateur d'OCB reconnaît.

## Matrice

`cœur` : le correctif est un commit du fork. `module` : la fonction vient de
`erplibre_odoo_cli_base`, le fork ne la porte pas. `OCB` : OCB se comporte
déjà ainsi, aucun correctif. `-` : absent.

| Correctif | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|
| P1 désinstaller en ligne de commande | cœur | cœur | cœur | cœur | module | module | module |
| P2 commande `db` | cœur | cœur | cœur | cœur | module | module | module |
| P3 commande `i18n` | cœur | cœur | cœur | cœur | module | module | module |
| P4 installer et appliquer un thème | cœur | cœur | cœur | cœur | module | module | module |
| P5 Message-ID `erplibre` | - | - | - | - | cœur | cœur | cœur |
| P6 erreur de notification push masquée | - | - | - | - | - | - | cœur |
| P7 `partner_autocomplete` sans auto-installation | - | cœur | - | - | cœur | OCB | OCB |
| P8 `web_unsplash` sans auto-installation | cœur | cœur | cœur | cœur | - | - | - |
| P9 identifiant sans espace final | cœur | cœur | cœur | cœur | - | - | - |
| P10 correctifs propres à une version | cœur | - | cœur | cœur | - | - | - |

De 16 à 18, P1 à P4 viennent de `erplibre_odoo_cli_base` : le fork 16 est OCB
plus P5 et P7, le fork 17 est OCB plus P5, le fork 18 est OCB plus P5 et P6.
De 12 à 15, P1 à P4 restent dans le cœur.

## Les correctifs

### P1 Désinstaller en ligne de commande

Quand un module casse le client web, l'interface qui le désinstallerait ne se
charge plus. La ligne de commande désinstalle les modules listés et tout
module installé qui en dépend.

- 12 à 15 : option serveur `--uninstall a,b`, dans `odoo/modules/loading.py`
  et `odoo/tools/config.py`. En 14 et 15, un correctif suivant masque une
  valeur vide.
- 16 à 18 : `odoo_bin.sh module uninstall -d BASE a,b`, par le module. Seuls
  les modules à l'état `installed` sont désinstallés, comme avant.

### P2 La commande `db`

La commande `db` d'OCB charge, vide, duplique, renomme et supprime une base.
Celle d'ERPLibre restaure aussi une image de `./image_db/`, crée une base
initialisée (langue, identifiant et mot de passe admin, pays), liste les bases
et affiche la version d'Odoo. Le mot de passe maître vient de la variable
d'environnement `MASTER_PWD` : un argument est lisible par tout utilisateur
de la machine dans `/proc`.

- 12 à 15 : `odoo/cli/db.py` remplacé par une commande à drapeaux
  (`--restore`, `--restore_image`, `--clone`, `--create`, `--backup`,
  `--drop`, `--list`, `--list_incompatible_db`, `--version`).
- 16 à 18 : `odoo/cli/db.py` est celui d'OCB. Le `db` du module en hérite et
  ajoute `create`, `list`, `list-incompatible`, `version`, `--image` sur
  `load` et `dump`, et un `drop` qui vérifie le mot de passe maître. En 16 et
  17, dont le `load` d'OCB n'a pas `--move`, le module l'ajoute.

### P3 La commande `i18n`

Écrit le `.pot` et le `.po` d'un module installé dans un dossier, pour les
traducteurs, sans l'interface.

- 12 à 15 : `odoo/cli/i18n.py`.
- 16 à 18 : le `i18n` du module, mêmes options.

### P4 Installer et appliquer un thème

Installer un module de thème par `-i` ne l'applique pas au site : c'est le
bouton « Choisir le thème » du site qui le fait (copier les vues du thème
dans le site, en faire le thème du site).

- 12 à 15 : option serveur `--install-theme theme_x`, dans
  `odoo/modules/loading.py` et `odoo/tools/config.py`. 12 corrige la valeur
  par défaut vide de l'option ; 14 et 15 masquent une valeur vide.
- 16 à 18 : `odoo_bin.sh theme apply -d BASE theme_x`, par le module. Un
  thème que la base ne liste pas encore est trouvé après la mise à jour de la
  liste des modules. Le module installe le thème au besoin, puis appelle la
  méthode même du bouton ; en 16, dont le bouton construit l'adresse de
  l'éditeur du site à partir de la requête HTTP, il en fait les étapes sans
  cette dernière.

### P5 Message-ID `erplibre`

`odoo/tools/mail.py` construit le Message-ID des courriels qu'Odoo envoie. Le
correctif écrit `erplibre` là où Odoo écrit `openerp`. Il reste dans le cœur :
la fonction est une aide de niveau module que le code de courriel appelle
directement.

- 16, 17, 18 : une ligne de `odoo/tools/mail.py`.

### P6 Erreur de notification push masquée

Quand le navigateur refuse les notifications push, le client web de mail
affiche une notification rouge persistante à chaque chargement. Le correctif
garde l'avertissement de la console et retire la notification. Il reste dans
le cœur : l'appel est au milieu d'une méthode du client web déjà surchargée.

- 18 : `addons/mail/static/src/webclient/web/webclient.js`.

### P7 `partner_autocomplete` sans auto-installation

`partner_autocomplete` envoie des données de partenaires à un service IAP
d'Odoo. Le correctif pose `auto_install: False`.

- 13 : `iap` et `partner_autocomplete` ; 16 : `partner_autocomplete`.
- 17 et 18 : OCB pose déjà `auto_install: False` ; aucun correctif.

### P8 `web_unsplash` sans auto-installation

`web_unsplash` appelle le service Unsplash depuis les dialogues d'image. Le
correctif pose `auto_install: False` dans
`addons/web_unsplash/__manifest__.py`.

- 12 à 15.

### P9 Identifiant sans espace final

L'autocomplétion d'un clavier mobile ajoute une espace après l'identifiant.
La connexion et la réinitialisation du mot de passe la retirent
(`addons/web/controllers/main.py`, `addons/auth_signup/models/res_users.py`).

- 12 à 15.

### P10 Correctifs propres à une version

| Version | Commit | Changement |
|---|---|---|
| 12 | e8e18c1b | `exec_pg_command` fonctionne avec les outils clients de PostgreSQL 17 (`odoo/tools/misc.py`) |
| 12 | 441ecac1 | la géolocalisation de `website_event` vérifie l'événement avant de s'en servir |
| 12 | 43562f2c | `website` : option d'en-tête pour la hauteur de la barre de navigation |
| 12 | cd16be9b | `abstract_field.js` vérifie qu'un champ peut prendre le focus |
| 12 | 7d5cfeef | `requirements.txt` aligné sur l'OCA |
| 12 | c051702e | rapport de vente : pas de ligne de vendeur quand il est vide |
| 12 | 64a5dd16 | portail de vente : erreur de produit affichée au lieu d'un chargement sans fin |
| 14 | 4d166425 | web : une image qui ne peut s'afficher est masquée |
| 14 | b9f96122, 136c1b1a | `packaging` au lieu des versions `distutils` dépréciées |
| 14, 15 | 0bbc0c2f, e9f9d7af | mail : traduction `fr_CA` des courriels envoyés |
| 14, 15 | afc23de6, 3549b881 | mail : champs CC et TO pour `mail_thread_cc` |
| 14, 15 | eb61b7a4, dab04fe5 | mail : nom du destinataire suggéré mis en forme |

## Le module de ligne de commande

`./odoo_bin.sh` est le point d'entrée. Ancienne syntaxe à drapeaux et
nouvelle syntaxe :

<!-- [common] -->
| Old (12-15 fork) | New |
|---|---|
| `db --create --database DB [--demo] [--user_lang L] [--user_login U] [--user_password P] [--user_phone N] [--user_country_code C]` | `db create [-f] [--demo] [--lang L] [--login U] [--password P] [--phone N] [--country C] DB` |
| `db --list` | `db list` |
| `db --list_incompatible_db` | `db list-incompatible` |
| `db --version` | `db version` |
| `db --drop --database DB` | `db drop [--if-exists] DB` |
| `db --restore --database DB --restore_image IMG` | `db load [-f] [-n] [--move] [DB] --image IMG` |
| `db --restore --database DB --restore_db_file FILE` | `db load [-f] [-n] [--move] [DB] FILE` |
| `db --backup --database DB --restore_image IMG` | `db dump DB --image IMG` |
| `db --backup --database DB --restore_db_file FILE` | `db dump DB FILE` |
| `db --clone --from_database SRC --database DST` | `db duplicate [-f] [-n] SRC DST` |
| - | `db rename [-f] SRC DST` |
| `i18n -d DB --module M --addons_path OUT` | `i18n -d DB --module M --addons_path OUT` |
| `./run.sh --no-http --stop-after-init -d DB --uninstall a,b` | `module uninstall [-c FILE] -d DB a,b` |
| `./run.sh --no-http --stop-after-init -d DB --install-theme T` | `theme apply [-c FILE] -d DB T` |

<!-- [en] -->
- `MASTER_PWD`: `db drop` checks the master password first, read from this
  environment variable (`admin` when unset), then looks at the database.
  `-f` on `db create`, `db load`, `db duplicate` and `db rename` checks it
  too before it deletes an existing database; OCB's `-f` does not.
- `--if-exists`: without it, dropping an absent database is an error.
- `--image NAME`: `./image_db/NAME.zip`; a value containing `/` is a path
  (`.zip` appended when missing). `db load --image NAME` without a database
  name creates the database `NAME`.
- `db list`, `db list-incompatible` and `db version` print only their data on
  stdout, no log line.
- Global options come before the subcommand, as with OCB: `db -c FILE list`.
- Discovery: `odoo-bin` finds the module's commands through the addons path
  known when it starts, the configuration file of `ODOO_RC`. `./odoo_bin.sh`
  exports `ODOO_RC` (the repository's `config.conf`). A bare `odoo-bin` needs
  `ODOO_RC`, or `--addons-path=...` written before the command name.

## Older versions

12 to 15 keep the old commands in the core. `./odoo_bin.sh` decides from the
core of the active version (`.odoo-version`): when
`odooX.0/odoo/odoo/cli/db.py` lacks `_check_target`, the method of OCB's `db`
command, the core carries the old commands, and `./odoo_bin.sh` hands `db`,
`module` and `theme` to `script/database/odoo_db_legacy.py`, which turns the
new syntax into the old flags and server options. That is 12 to 15 always,
and a 16 or 17 fork still on its old commits. `i18n` passes unchanged. The
translation has known limits:

- `db load` on 12 to 15 always restores as a moved database (the UUID is
  kept); `--move` changes nothing there. On an old 16 or 17 fork, `-n` and
  `--move` become `--neutralize` and `--move_database`.
- No `--neutralize` (`-n`) on 12 to 15; no `db rename`, no `db dump` to
  stdout, no `db load` from a URL: the translator stops with exit code 2.
- `db create -f`, `db load -f` and `db duplicate -f` drop through the old
  `--drop`, which checks the master password (`MASTER_PWD`).
- Global options other than `-c` (`--db_host`...) are refused before the `db`
  subcommand.

The fork and the module go together. Next to an old core, the module
registers no command (its `cli/__init__.py` makes the same test), so the
translation works whether the module is there or not. On a core with OCB's
`db` but without the module, `db`, `module` and `theme` do not exist:
`./odoo_bin.sh` stops with exit code 2 and names the missing module.

<!-- [fr] -->
- `MASTER_PWD` : `db drop` vérifie d'abord le mot de passe maître, lu dans
  cette variable d'environnement (`admin` si elle est vide), puis regarde la
  base. `-f` sur `db create`, `db load`, `db duplicate` et `db rename` le
  vérifie aussi avant de supprimer une base existante ; le `-f` d'OCB ne le
  fait pas.
- `--if-exists` : sans lui, supprimer une base absente est une erreur.
- `--image NOM` : `./image_db/NOM.zip` ; une valeur qui contient `/` est un
  chemin (`.zip` ajouté s'il manque). `db load --image NOM` sans nom de base
  crée la base `NOM`.
- `db list`, `db list-incompatible` et `db version` n'écrivent que leurs
  données sur stdout, aucune ligne de journal.
- Les options globales précèdent la sous-commande, comme dans OCB :
  `db -c FICHIER list`.
- Découverte : `odoo-bin` trouve les commandes du module par l'addons path
  connu à son démarrage, celui du fichier de configuration de `ODOO_RC`.
  `./odoo_bin.sh` exporte `ODOO_RC` (le `config.conf` du dépôt). Un
  `odoo-bin` nu demande `ODOO_RC`, ou un `--addons-path=...` écrit avant le
  nom de la commande.

## Versions plus anciennes

De 12 à 15, les anciennes commandes restent dans le cœur. `./odoo_bin.sh`
décide d'après le cœur de la version active (`.odoo-version`) : quand
`odooX.0/odoo/odoo/cli/db.py` n'a pas `_check_target`, la méthode de la
commande `db` d'OCB, le cœur porte les anciennes commandes, et
`./odoo_bin.sh` passe `db`, `module` et `theme` à
`script/database/odoo_db_legacy.py`, qui convertit la nouvelle syntaxe en
anciens drapeaux et options serveur. C'est le cas de 12 à 15 toujours, et
d'un fork 16 ou 17 resté sur ses anciens commits. `i18n` passe tel quel. La
traduction a des limites connues :

- `db load` de 12 à 15 restaure toujours en base déplacée (l'UUID est
  gardé) ; `--move` n'y change rien. Sur un ancien fork 16 ou 17, `-n` et
  `--move` deviennent `--neutralize` et `--move_database`.
- Pas de `--neutralize` (`-n`) de 12 à 15 ; pas de `db rename`, pas de `db
  dump` vers stdout, pas de `db load` depuis une URL : le traducteur
  s'arrête avec le code de sortie 2.
- `db create -f`, `db load -f` et `db duplicate -f` suppriment par l'ancien
  `--drop`, qui vérifie le mot de passe maître (`MASTER_PWD`).
- Les options globales autres que `-c` (`--db_host`…) sont refusées avant la
  sous-commande `db`.

Le fork et le module vont ensemble. À côté d'un ancien cœur, le module
n'enregistre aucune commande (son `cli/__init__.py` fait le même test) : la
traduction fonctionne, que le module soit là ou non. Sur un cœur qui a le
`db` d'OCB mais pas le module, `db`, `module` et `theme` n'existent pas :
`./odoo_bin.sh` s'arrête avec le code de sortie 2 et nomme le module
manquant.
