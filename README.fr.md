

# ERPLibre

[![License: AGPL v3](https://img.shields.io/github/license/ERPLibre/ERPLibre)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/ERPLibre/ERPLibre?label=version)](https://github.com/ERPLibre/ERPLibre/tags)
[![Stars](https://img.shields.io/github/stars/ERPLibre/ERPLibre?style=flat)](https://github.com/ERPLibre/ERPLibre/stargazers)
[![Contributors](https://img.shields.io/github/contributors/ERPLibre/ERPLibre)](https://github.com/ERPLibre/ERPLibre/graphs/contributors)
[![Commit activity](https://img.shields.io/github/commit-activity/y/ERPLibre/ERPLibre)](https://github.com/ERPLibre/ERPLibre/pulse)
[![Last commit](https://img.shields.io/github/last-commit/ERPLibre/ERPLibre)](https://github.com/ERPLibre/ERPLibre/commits)
[![Mastodon](https://img.shields.io/badge/Mastodon-@erplibre-6364FF?logo=mastodon&logoColor=white)](https://fosstodon.org/@erplibre)


**L'ERP/CRM libre et souverain, livré avec toute sa boîte à outils.**

Odoo Community livre le logiciel. ERPLibre livre tout ce qu'il faut pour
l'exploiter pendant des années : une installation en une commande sur dix
plateformes, onze versions d'Odoo côte à côte, la migration guidée d'une base
d'une version à la suivante, un générateur de modules, le déploiement en
conteneur, en machine virtuelle ou sur Proxmox, et un assistant IA qui peut
tourner entièrement sur votre propre matériel.

Vos données restent là où vous les mettez. Les modules viennent de l'Odoo
Community Association (OCA) et d'un écosystème d'entreprises spécialisées,
figés et reproductibles. Chaque modification qu'ERPLibre apporte à Odoo ou à
ces modules est destinée à retourner en amont.


# ERPLibre en chiffres

Les badges ci-dessus sont en direct. Le tableau ci-dessous a été relevé sur la
version 1.8.0.


| | |
|---|---|
| **11** versions d'Odoo | de 10.0 à 20.0, installables côte à côte |
| **3 300+** modules | installables sur Odoo 18, issus de **137** dépôts Git |
| **23** organisations | fournissent ces dépôts ; l'OCA en fournit à elle seule **109** |
| **10** plateformes | distributions Linux, macOS, Windows — en amd64, arm64 et s390x |
| **400+** commandes | dans le menu interactif TODO, en français et en anglais |
| **6 700+** tests | gardent l'outillage, de la numérotation des menus à l'installation de machines virtuelles |
| **1 500+** commits | depuis 2020, dont **845** dans les douze derniers mois |


# Fonctionnalités

### Installer partout, en une commande

`make` détecte le système, installe ce qui manque et ouvre **TODO**, un menu
guidé qui pilote tout ce qui suit — aucune commande à retenir. Ubuntu, Debian,
Fedora, AlmaLinux, openSUSE, Arch, NixOS (de façon déclarative), macOS et
Windows, sur trois architectures. Les images Docker, que Podman exécute aussi,
embarquent PostgreSQL 18 et PostGIS.

### Toutes les versions d'Odoo, côte à côte

Odoo 10.0 à 20.0 ont chacune leur Python et leur environnement virtuel, gérés
par mise ou pyenv. Changez avec `make switch_odoo_18` ; les autres versions
restent installées.

### Migrer vers l'avant sans tout recommencer

Une migration de base guidée monte d'une version d'Odoo à la fois avec
OpenUpgrade, garde sa progression, reprend après une interruption et peut
revenir à une étape précédente. Une base de production se neutralise en une
copie de développement sans risque.

### Bâtir des modules plus vite

Le générateur de code produit des modules Odoo complets — vues, portail,
snippets, héritage, i18n, JavaScript — ou en clone un existant. Formatage,
hooks Git, tests par module avec couverture et automatisation Selenium sont à
un menu de distance.

### Déployer et exploiter

Déployez en local, dans des machines virtuelles QEMU/KVM ou sur Proxmox VE.
Nginx, Apache, SSL Certbot, DNS dynamique et services systemd sont configurés
pour vous. VPN, SSH, secrets KeePass et audit de sécurité des dépendances sont
intégrés.

### Comprendre et transformer vos données

Sauvegardez, restaurez et clonez des bases ; analysez les modèles, les vues et
les champs personnalisés d'une base ; transformez et anonymisez les données
avant de les partager.

### L'IA, en local d'abord

Interrogez un modèle de langage local ou distant depuis le terminal, découvrez
les serveurs de modèles de votre réseau et utilisez des outils de
développement assistés par IA. Les commits faits avec l'IA sont déclarés,
jamais cachés — voir [AI_POLICY](AI_POLICY.md).

### Et encore

ERPLibre Home Mobile (Owl + Capacitor), un client de courriel en terminal, la
mesure de performance et l'exécution parallèle des tests.


# Versions Odoo supportées


| Odoo version | Python  | Status     |
|--------------|---------|------------|
| 20.0         | 3.14.7  | Upstream   |
| 19.0         | 3.12.10 | Upstream   |
| 18.0         | 3.12.10 | Active     |
| 17.0         | 3.10.18 | Inactive   |
| 16.0         | 3.10.18 | Inactive   |
| 15.0         | 3.8.20  | Deprecated |
| 14.0         | 3.8.20  | Deprecated |
| 13.0         | 3.7.17  | Deprecated |
| 12.0         | 3.7.17  | Deprecated |
| 11.0         | 3.7.17  | Upstream, deprecated |
| 10.0         | 2.7.18  | Upstream, deprecated |


Les versions **Upstream** ne portent que les dépôts d'Odoo et de l'OCA, plus
les modules de neutralisation ; elles servent d'étapes de migration.

Changez de version avec `make switch_odoo_18`, `make switch_odoo_16`, etc.

Le Python de ce tableau est celui de l'environnement virtuel Odoo.
L'environnement virtuel d'outillage `.venv.erplibre` (TODO, `repo`, formateurs)
tourne sur son propre interpréteur, **3.14.7**, fixé par
`conf/python-erplibre-version`. Là où une distribution ne le porte pas, pyenv
le compile.


# Plateformes supportées

- **Ubuntu** : 24.04, 25.10, 26.04 — 20.04 et 22.04 sont retirées, pikepdf réclamant un qpdf 12.2 bâti en C++20
- **Linux Mint** : 22.3
- **Debian** : 12 (bookworm) et 13 (trixie)
- **Fedora** : 41 et suivantes
- **AlmaLinux, Rocky Linux** : 9 et 10 — RHEL et CentOS Stream empruntent le même chemin
- **openSUSE** : Leap 16.0 et Tumbleweed
- **Arch Linux** : rolling release
- **NixOS** : 25.11 — les dépendances y sont DÉCLARÉES dans `conf/nixos/erplibre.nix` puis appliquées par `nixos-rebuild`, là où les quatre autres familles les installent commande par commande
- **macOS** : par mise ou pyenv
- **Windows** : par WSL ou Docker
- **Architectures** : amd64, arm64 et s390x (mainframe IBM Z)


# Installation en production

## Installation facile sur Ubuntu ou Debian avec Docker

Ceci a été testé sur Debian 12 et Ubuntu 24.04 LTS.

**Note** : Ceci est prévu pour un environnement de test, sur un réseau local ou un environnement similaire non exposé
directement à Internet.


1. Assurez-vous que Docker et le serveur web nginx sont installés :<BR>
   `sudo apt install docker.io docker-compose-v2 nginx`
1. Obtenez le dernier fichier Docker compose d'ERPLibre :<BR>
   `wget https://raw.githubusercontent.com/ERPLibre/ERPLibre/master/docker-compose.yml`
1. Installez et lancez ERPLibre avec Docker en mode daemon (serveur web) :<BR>
   ``sudo docker compose up -d`
1. Ouvrez l'étape finale d'installation à cette page web :<BR>
   `http://[server IP]:8069/web/database/manager`<BR>
   ![odoo_first_installation.png](doc/image/odoo_first_installation.png)
1. Terminez l'installation en fournissant un nom de base de données, un courriel et un mot de passe, puis cliquez sur **Create Database**.
   Selon les ressources de votre système, **cela peut prendre plus de 2 minutes sans retour visuel !** Vérifiez
   l'indicateur de chargement de votre navigateur.
1. Ensuite, la page web se rechargera automatiquement et vous devriez voir la liste des applications dans ERPLibre :<BR>
   ![odoo_application_list.png](doc/image/odoo_application_list.png)

   Vous pouvez maintenant personnaliser votre installation ERPLibre.


Pour plus d'informations, consultez le [guide Docker](./docker/README.md).

## Installation depuis le code source

### Installation automatisée


Pour Debian/Ubuntu


```bash
sudo apt install make python3
```


Clonez le projet :


```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```


Suivez les instructions du script suivant, il essaiera de détecter votre environnement.


```bash
make
```


`make` et `./install.sh` lancent TODO par l'interpréteur capable de le lire :
`.venv.erplibre` quand il porte la bonne version, sinon le `python3` du système
s'il est assez récent, sinon l'installation elle-même — un système plus ancien
que `conf/python-erplibre-version` ne sait pas analyser le code, donc
l'installation est proposée plutôt que de s'arrêter sur une erreur de syntaxe.
Elle ne part que sur un oui tapé au terminal (`o`, `oui`, `y` ou `yes`) ;
Entrée seule, ou l'absence de terminal, vaut non. Quand
l'environnement manque mais que le Python du système suffit, TODO propose de
lancer `./script/install/install_erplibre.sh` (dans un terminal) ou affiche
cette commande. L'installation bâtit l'environnement par
`EL_PYTHON_PROVIDER` (mise ou pyenv) ; un `.venv.erplibre` existant sur une
autre version de Python est SUPPRIMÉ puis rebâti, et ce qu'on y avait posé à la
main part avec lui.


### Manuellement

Sous Ubuntu, dépendance minimale :


```bash
sudo apt install make git curl
```


Sous Ubuntu, dépendance développeur :


```bash
sudo apt install make build-essential libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev libbz2-dev libldap2-dev libsasl2-dev
```


Clonez le projet :


```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```


`make install_os` détecte la distribution et choisit le bon script de dépendances : apt pour Ubuntu, Linux Mint et Debian, dnf pour Fedora et la famille RHEL, zypper pour openSUSE, pacman pour Arch, et un module déclaratif pour NixOS. Voir les plateformes supportées ci-dessus.


```bash
make install_os
make install_odoo_18
```


Installez une version spécifique d'Odoo :


```bash
make install_odoo_16
make install_odoo_17
make install_odoo_18
```


Mettez à jour votre configuration si vous devez exécuter depuis une autre interface que 127.0.0.1, fichier `config.conf`


```
xmlrpc_interface = 0.0.0.0
```


Afficher la version :


```bash
make version
```


Prêt à exécuter :


```bash
make run
```


# Migrer une base de données entre versions d'Odoo

Depuis un clone neuf, TODO installe toutes les versions d'Odoo de 10 à 20,
puis ouvre la migration de base de données. Chaque ligne `>` est une touche à
taper, suivie d'Entrée :

```text
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
make
> 2   Installer (make installe aussi ERPLibre en local et sur le système)
> y   Installer d'abord les dépendances système (n si c'est déjà fait)
> w   Installer toutes les versions d'Odoo, de 10 à 20
> 1   Exécuter
> 1   Code
> 7   Mise à jour
> 2   Mise à jour Odoo - Migration de base de données
```

À la fin de l'installation, TODO revient au menu principal : `0` y quitte au
lieu de revenir en arrière. Les numéros sont ceux d'un clone neuf ; une entrée
ajoutée à `code_from_makefile` ou `update_from_makefile` dans un `todo.json`
privé les décale.

`test/test_guide_migration.py` rejoue cette séquence, lue dans ce fichier,
contre les vrais menus. Le lancer après avoir modifié un menu :

```bash
.venv.erplibre/bin/python -m unittest test.test_guide_migration
```

La migration elle-même est décrite dans [MIGRATION](doc/MIGRATION.fr.md).


# Test

Exécutez les tests ERPLibre avec son générateur de code.


```bash
time make test_full_fast
```


# Documentation

| Guide | Description |
|-------|-------------|
| [DISCOVER](doc/DISCOVER.md) | Découvrir et explorer ERPLibre |
| [DEVELOPMENT](doc/DEVELOPMENT.md) | Configuration de l'environnement de développement |
| [PRODUCTION](doc/PRODUCTION.md) | Déploiement du serveur de production |
| [RUN](doc/RUN.md) | Modes d'exécution et cas d'utilisation |
| [CODE_GENERATOR](doc/CODE_GENERATOR.md) | Génération de code de modules Odoo |
| [MIGRATION](doc/MIGRATION.md) | Migration de base de données entre versions |
| [GIT_REPO](doc/GIT_REPO.md) | Gestion des dépôts Git |
| [POETRY](doc/POETRY.md) | Gestion des dépendances Python |
| [FAQ](doc/FAQ.md) | Foire aux questions |
| [HOWTO](doc/HOWTO.md) | Guides pratiques |
| [WINDOWS_INSTALLATION](doc/WINDOWS_INSTALLATION.md) | Installation sous Windows |


# Communauté

ERPLibre se construit en public depuis 2020, en français et en anglais, par
des développeurs, des intégrateurs et des utilisateurs qui l'exploitent en
production. Il repose sur le travail de l'[Odoo Community
Association](https://odoo-community.org), dont les dépôts forment l'essentiel
de ses modules, et lui retourne ses correctifs.

- **Suivez** le projet sur [Mastodon](https://fosstodon.org/@erplibre).
- **Posez une question ou signalez un problème** par les
  [issues GitHub](https://github.com/ERPLibre/ERPLibre/issues).
- **Contribuez** du code, des traductions ou de la documentation : commencez
  par [CONTRIBUTION](doc/CONTRIBUTION.md), qui remercie aussi les personnes et
  les organisations derrière le projet.
- **Utilisez l'IA ouvertement** : [AI_POLICY](AI_POLICY.md) explique comment
  les contributions assistées par IA sont déclarées.


# Licence

Ce projet est sous licence [GNU Affero General Public License v3.0](LICENSE).