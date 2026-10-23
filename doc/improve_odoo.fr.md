
# Améliorer Odoo : le fork Odoo d'ERPLibre

Chaque checkout `odooX.0/odoo` est la branche `ERPLibre/X.0` du dépôt
ERPLibre/odoo. Cette page liste ce que cette branche ajoute à Odoo, version
par version, et où vit chaque ajout : dans le cœur d'Odoo, ou dans un module.

## En amont : OCA/OCB

Le fork suit OCA/OCB, la branche communautaire d'Odoo, et non Odoo lui-même.
Le manifeste le dit par trois attributs du projet `odooX.0/odoo` :

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

Ce que le fork porte par-dessus OCB, une fois le remote `OCA` récupéré :

```bash
git -C odoo18.0/odoo log --oneline OCA/18.0..ERPLibre/18.0
git -C odoo18.0/odoo diff --stat OCA/18.0 ERPLibre/18.0
```

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
| P7 `partner_autocomplete` sans auto-installation | - | cœur | - | - | cœur | cœur | OCB |
| P8 `web_unsplash` sans auto-installation | cœur | cœur | cœur | cœur | - | - | - |
| P9 identifiant sans espace final | cœur | cœur | cœur | cœur | - | - | - |
| P10 correctifs propres à une version | cœur | - | cœur | cœur | - | - | - |

De 16 à 18, P1 à P4 viennent de `erplibre_odoo_cli_base` : les forks 16 et
17 sont OCB plus P5 et P7, le fork 18 est OCB plus P5 et P6. De 12 à 15, P1 à
P4 restent dans le cœur.

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

- 13 : `iap` et `partner_autocomplete` ; 16 et 17 : `partner_autocomplete`.
- 18 : OCB pose déjà `auto_install: False` pour les deux ; aucun correctif.

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