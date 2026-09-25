<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [common] -->

# ERPLibre

[![License: AGPL v3](https://img.shields.io/github/license/ERPLibre/ERPLibre)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/ERPLibre/ERPLibre?label=version)](https://github.com/ERPLibre/ERPLibre/tags)
[![Stars](https://img.shields.io/github/stars/ERPLibre/ERPLibre?style=flat)](https://github.com/ERPLibre/ERPLibre/stargazers)
[![Contributors](https://img.shields.io/github/contributors/ERPLibre/ERPLibre)](https://github.com/ERPLibre/ERPLibre/graphs/contributors)
[![Commit activity](https://img.shields.io/github/commit-activity/y/ERPLibre/ERPLibre)](https://github.com/ERPLibre/ERPLibre/pulse)
[![Last commit](https://img.shields.io/github/last-commit/ERPLibre/ERPLibre)](https://github.com/ERPLibre/ERPLibre/commits)
[![Mastodon](https://img.shields.io/badge/Mastodon-@erplibre-6364FF?logo=mastodon&logoColor=white)](https://fosstodon.org/@erplibre)

<!-- [en] -->

**The free, sovereign ERP/CRM that comes with its whole toolbox.**

Odoo Community delivers the software. ERPLibre delivers everything needed to
run it for years: a one-command install on ten platforms, eleven Odoo versions
side by side, guided database migration from one version to the next, a module
generator, deployment to containers, virtual machines or Proxmox, and an AI
assistant that can run entirely on your own hardware.

Your data stays where you put it. The modules come from the Odoo Community
Association (OCA) and an ecosystem of specialized companies, pinned and
reproducible. Every change ERPLibre makes to Odoo or to those modules is meant
to go back upstream.

<!-- [fr] -->

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

<!-- [en] -->

# ERPLibre in numbers

The badges above are live. The table below was measured on version 1.8.0.

<!-- [fr] -->

# ERPLibre en chiffres

Les badges ci-dessus sont en direct. Le tableau ci-dessous a été relevé sur la
version 1.8.0.

<!-- [en] -->

| | |
|---|---|
| **11** Odoo versions | from 10.0 to 20.0, installable side by side |
| **3,300+** modules | installable on Odoo 18, from **137** Git repositories |
| **23** organizations | supply those repositories; the OCA alone supplies **109** |
| **10** platforms | Linux distributions, macOS, Windows — on amd64, arm64 and s390x |
| **400+** commands | in the interactive TODO menu, in English and French |
| **6,700+** tests | guard the tooling, from menu numbering to virtual machine installs |
| **1,500+** commits | since 2020, **845** of them over the last twelve months |

<!-- [fr] -->

| | |
|---|---|
| **11** versions d'Odoo | de 10.0 à 20.0, installables côte à côte |
| **3 300+** modules | installables sur Odoo 18, issus de **137** dépôts Git |
| **23** organisations | fournissent ces dépôts ; l'OCA en fournit à elle seule **109** |
| **10** plateformes | distributions Linux, macOS, Windows — en amd64, arm64 et s390x |
| **400+** commandes | dans le menu interactif TODO, en français et en anglais |
| **6 700+** tests | gardent l'outillage, de la numérotation des menus à l'installation de machines virtuelles |
| **1 500+** commits | depuis 2020, dont **845** dans les douze derniers mois |

<!-- [en] -->

# Features

### Install anywhere, in one command

`make` detects the system, installs what is missing and opens **TODO**, a
guided menu that drives everything below — no command to memorize. Ubuntu,
Debian, Fedora, AlmaLinux, openSUSE, Arch, NixOS (declaratively), macOS and
Windows, on three architectures. The Docker images, which Podman runs too,
ship with PostgreSQL 18 and PostGIS.

### Every Odoo version, side by side

Odoo 10.0 to 20.0 each get their own Python and virtual environment, managed
by mise or pyenv. Switch with `make switch_odoo_18`; the other versions stay
installed.

### Migrate forward without starting over

A guided database migration climbs one Odoo version at a time with
OpenUpgrade, keeps its progress, resumes after an interruption and can rewind
to a previous step. A production database can be neutralized into a safe
development copy.

### Build modules faster

The code generator produces complete Odoo modules — views, portal, snippets,
inheritance, i18n, JavaScript — or clones an existing one. Formatting, Git
hooks, per-module tests with coverage and Selenium automation are one menu
away.

### Deploy and operate

Deploy locally, in QEMU/KVM virtual machines or on Proxmox VE. Nginx, Apache,
Certbot SSL, dynamic DNS and systemd services are configured for you. VPN, SSH,
KeePass secrets and a dependency security audit are built in.

### Understand and transform your data

Back up, restore and clone databases; analyse a database's models, views and
custom fields; transform and anonymize data before sharing it.

### AI, local first

Ask a local or remote language model from the terminal, discover the model
servers on your network, and use AI-assisted development tools. Commits made
with AI are declared, never hidden — see [AI_POLICY](AI_POLICY.md).

### And more

ERPLibre Home Mobile (Owl + Capacitor), a terminal mail client, performance
measurement and parallel test execution.

<!-- [fr] -->

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

<!-- [en] -->

# Supported Odoo versions

<!-- [fr] -->

# Versions Odoo supportées

<!-- [common] -->

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

<!-- [en] -->

**Upstream** versions carry the Odoo and OCA repositories only, plus the
neutralization modules; they serve as migration steps.

Switch between versions with `make switch_odoo_18`, `make switch_odoo_16`, etc.

The Python in that table is the one of the Odoo virtual environment. The
tooling virtual environment `.venv.erplibre` (TODO, `repo`, formatters) runs
its own interpreter, **3.14.7**, set by `conf/python-erplibre-version`. Where a
distribution does not carry it, pyenv compiles it.

<!-- [fr] -->

Les versions **Upstream** ne portent que les dépôts d'Odoo et de l'OCA, plus
les modules de neutralisation ; elles servent d'étapes de migration.

Changez de version avec `make switch_odoo_18`, `make switch_odoo_16`, etc.

Le Python de ce tableau est celui de l'environnement virtuel Odoo.
L'environnement virtuel d'outillage `.venv.erplibre` (TODO, `repo`, formateurs)
tourne sur son propre interpréteur, **3.14.7**, fixé par
`conf/python-erplibre-version`. Là où une distribution ne le porte pas, pyenv
le compile.

<!-- [en] -->

# Supported platforms

- **Ubuntu** : 24.04, 25.10, 26.04 — 20.04 and 22.04 are dropped, pikepdf requiring a qpdf 12.2 built in C++20
- **Linux Mint** : 22.3
- **Debian** : 12 (bookworm) and 13 (trixie)
- **Fedora** : 41 and later
- **AlmaLinux, Rocky Linux** : 9 and 10 — RHEL and CentOS Stream take the same path
- **openSUSE** : Leap 16.0 and Tumbleweed
- **Arch Linux** : rolling release
- **NixOS** : 25.11 — the dependencies are DECLARED in `conf/nixos/erplibre.nix` and applied by `nixos-rebuild`, where the four other families install them one command at a time
- **macOS** : through mise or pyenv
- **Windows** : through WSL or Docker
- **Architectures** : amd64, arm64 and s390x (IBM Z mainframe)

<!-- [fr] -->

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

<!-- [en] -->

# Installation in production

## Easy installation on Ubuntu or Debian using Docker

This has been tested in Debian 12 and Ubuntu 24.04 LTS.

**Note** : This is meant for a test environment, on a local network or similar environment not directly exposed to the
Internet.

<!-- [fr] -->

# Installation en production

## Installation facile sur Ubuntu ou Debian avec Docker

Ceci a été testé sur Debian 12 et Ubuntu 24.04 LTS.

**Note** : Ceci est prévu pour un environnement de test, sur un réseau local ou un environnement similaire non exposé
directement à Internet.

<!-- [en] -->

1. Make sure Docker and nginx web server are installed:<BR>
   `sudo apt install docker.io docker-compose-v2 nginx`
1. Get the latest ERPLibre Docker compose file:<BR>
   `wget https://raw.githubusercontent.com/ERPLibre/ERPLibre/master/docker-compose.yml`
1. Install and run ERPLibre with Docker running as a daemon (web server):<BR>
   `sudo docker compose up -d`
1. Open the final installation step at this web page :<BR>
   `http://[server IP]:8069/web/database/manager`<BR>
   ![odoo_first_installation.png](doc/image/odoo_first_installation.png)
1. Finish the installation by providing a database name, email and password. then click on **Create Database**.
   Depending on your system resources **this may take more than 2 minutes without feedback !** Check your browser
   loading indicator.
1. Next, the web page will reload itself, and you should see the Applications list in ERPLibre:<BR>
   ![odoo_application_list.png](doc/image/odoo_application_list.png)

   You can now personalize your ERPLibre installation.

<!-- [fr] -->

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

<!-- [en] -->

For more information, read [Docker guide](./docker/README.md).

## Install from source code

### Automated installation

<!-- [fr] -->

Pour plus d'informations, consultez le [guide Docker](./docker/README.md).

## Installation depuis le code source

### Installation automatisée

<!-- [en] -->

For Debian/Ubuntu

<!-- [fr] -->

Pour Debian/Ubuntu

<!-- [common] -->

```bash
sudo apt install make python3
```

<!-- [en] -->

Clone the project:

<!-- [fr] -->

Clonez le projet :

<!-- [common] -->

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

<!-- [en] -->

Follow the instruction on the following script, it will try to detect your environment.

<!-- [fr] -->

Suivez les instructions du script suivant, il essaiera de détecter votre environnement.

<!-- [common] -->

```bash
make
```

<!-- [en] -->

`make` and `./install.sh` start TODO through the interpreter that can read it:
`.venv.erplibre` when it carries the right version, otherwise the system
`python3` when it is recent enough, otherwise the install itself — a system
older than `conf/python-erplibre-version` cannot parse the code, so it offers
the install rather than stopping on a syntax error. The install runs only on a
yes typed in a terminal (`o`, `oui`, `y` or `yes`); Enter alone, or no
terminal, means no. When the
environment is missing but the system Python suffices, TODO offers to run
`./script/install/install_erplibre.sh` (in a terminal) or prints that command. The install builds the environment
through `EL_PYTHON_PROVIDER` (mise or pyenv); an existing `.venv.erplibre` on
another Python version is DELETED and rebuilt, and whatever was installed in it
by hand goes with it.

<!-- [fr] -->

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

<!-- [en] -->

### Manually

Into Ubuntu, minimal dependency:

<!-- [fr] -->

### Manuellement

Sous Ubuntu, dépendance minimale :

<!-- [common] -->

```bash
sudo apt install make git curl
```

<!-- [en] -->

Into Ubuntu, developer dependency:

<!-- [fr] -->

Sous Ubuntu, dépendance développeur :

<!-- [common] -->

```bash
sudo apt install make build-essential libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev libbz2-dev libldap2-dev libsasl2-dev
```

<!-- [en] -->

Clone the project:

<!-- [fr] -->

Clonez le projet :

<!-- [common] -->

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```

<!-- [en] -->

`make install_os` detects the distribution and picks the right dependency script: apt for Ubuntu, Linux Mint and Debian, dnf for Fedora and the RHEL family, zypper for openSUSE, pacman for Arch, and a declarative module for NixOS. See the supported platforms above.

<!-- [fr] -->

`make install_os` détecte la distribution et choisit le bon script de dépendances : apt pour Ubuntu, Linux Mint et Debian, dnf pour Fedora et la famille RHEL, zypper pour openSUSE, pacman pour Arch, et un module déclaratif pour NixOS. Voir les plateformes supportées ci-dessus.

<!-- [common] -->

```bash
make install_os
make install_odoo_18
```

<!-- [en] -->

Install a specific Odoo version:

<!-- [fr] -->

Installez une version spécifique d'Odoo :

<!-- [common] -->

```bash
make install_odoo_16
make install_odoo_17
make install_odoo_18
```

<!-- [en] -->

Update your configuration if you need to run from another interface than 127.0.0.1, file `config.conf`

<!-- [fr] -->

Mettez à jour votre configuration si vous devez exécuter depuis une autre interface que 127.0.0.1, fichier `config.conf`

<!-- [common] -->

```
xmlrpc_interface = 0.0.0.0
```

<!-- [en] -->

Show version :

<!-- [fr] -->

Afficher la version :

<!-- [common] -->

```bash
make version
```

<!-- [en] -->

Ready to execute:

<!-- [fr] -->

Prêt à exécuter :

<!-- [common] -->

```bash
make run
```

<!-- [en] -->

# Migrate a database between Odoo versions

From a fresh clone, TODO installs every Odoo version from 10 to 20, then opens
the database migration. Each `>` line is a key to type, followed by Enter:

```text
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
make
> 2   Install (make also installs ERPLibre locally and on the system)
> y   Install the system dependencies first (n if already done)
> w   Install every Odoo version, from 10 to 20
> 1   Execute
> 1   Code
> 7   Update
> 2   Upgrade Odoo - Migration Database
```

At the end of the installation, TODO returns to the main menu: `0` there
quits instead of going back. The key numbers are those of a fresh clone; an
entry added to `code_from_makefile` or `update_from_makefile` in a private
`todo.json` shifts them.

`test/test_guide_migration.py` replays this sequence, read from this file,
against the real menus. Run it after changing a menu:

```bash
.venv.erplibre/bin/python -m unittest test.test_guide_migration
```

The migration itself is described in [MIGRATION](doc/MIGRATION.md).

<!-- [fr] -->

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

<!-- [en] -->

# Test

Execute ERPLibre test with his code generator.

<!-- [fr] -->

# Test

Exécutez les tests ERPLibre avec son générateur de code.

<!-- [common] -->

```bash
time make test_full_fast
```

<!-- [en] -->

# Documentation

| Guide | Description |
|-------|-------------|
| [DISCOVER](doc/DISCOVER.md) | Learn and explore ERPLibre |
| [DEVELOPMENT](doc/DEVELOPMENT.md) | Development environment setup |
| [PRODUCTION](doc/PRODUCTION.md) | Production server deployment |
| [RUN](doc/RUN.md) | Execution modes and use cases |
| [CODE_GENERATOR](doc/CODE_GENERATOR.md) | Odoo module code generation |
| [MIGRATION](doc/MIGRATION.md) | Database migration between versions |
| [GIT_REPO](doc/GIT_REPO.md) | Git repository management |
| [POETRY](doc/POETRY.md) | Python dependency management |
| [FAQ](doc/FAQ.md) | Frequently asked questions |
| [HOWTO](doc/HOWTO.md) | How-to guides |
| [WINDOWS_INSTALLATION](doc/WINDOWS_INSTALLATION.md) | Windows installation |

<!-- [fr] -->

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

<!-- [en] -->

# Community

ERPLibre has been built in the open since 2020, in English and French, by
developers, integrators and users who run it in production. It stands on the
work of the [Odoo Community Association](https://odoo-community.org), whose
repositories make up most of its modules, and gives its fixes back upstream.

- **Follow** the project on [Mastodon](https://fosstodon.org/@erplibre).
- **Ask or report** through [GitHub issues](https://github.com/ERPLibre/ERPLibre/issues).
- **Contribute** code, translations or documentation: start with
  [CONTRIBUTION](doc/CONTRIBUTION.md), which also thanks the people and
  organizations behind the project.
- **Use AI openly**: [AI_POLICY](AI_POLICY.md) explains how AI-assisted
  contributions are declared.

<!-- [fr] -->

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

<!-- [en] -->

# License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).

<!-- [fr] -->

# Licence

Ce projet est sous licence [GNU Affero General Public License v3.0](LICENSE).
