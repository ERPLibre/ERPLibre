

# ERPLibre


ERPLibre est une plateforme CRM/ERP incluant l'installation, la maintenance et le developpement automatises de modules
open source de la version communautaire d'Odoo. C'est un "soft-fork" de l'Odoo Community Edition (OCE), ce qui signifie
qu'il vise a contribuer en amont.
Il est base sur un ensemble de modules prets pour la production, supportes par l'Odoo Community Association (OCA) et un
ecosysteme d'entreprises specialisees. Cette solution assure la souverainete numerique dans un environnement local tout
en integrant des Transformers Generatifs Pre-entraines (GPT), apportant une dimension supplementaire a la gestion des
donnees et a l'automatisation.


Suivez-nous sur Mastodon : https://fosstodon.org/@erplibre


# Fonctionnalites

- **Support multi-version Odoo** : executez Odoo 12.0, 13.0, 14.0, 15.0, 16.0, 17.0 et 18.0 dans le meme espace de travail, avec des environnements virtuels Python independants (`.venv.erplibre` et `.venv.odooXX`)
- **CLI interactif (TODO.py)** : outil interactif guide pour l'installation, l'execution, la gestion de bases de donnees, le formatage de code, la compilation mobile, et plus encore. Lancez-le avec `make`
- **Generateur de code** : generez des modules Odoo automatiquement avec support des vues, portail, snippets, heritage, i18n et JavaScript
- **Automatisation Selenium** : tests web et automatisation avec Selenium Grid, enregistrement video et automatisation de connexion
- **Application mobile** : ERPLibre Home Mobile (Owl + Capacitor), compilee et deployee via TODO.py
- **Deploiement Docker** : images Docker pretes pour la production avec PostgreSQL 18 et PostGIS
- **Outils de deploiement** : Nginx, Apache, Cloudflare DDNS, Certbot SSL, services systemd
- **Outils de base de donnees** : sauvegarde, restauration, clonage, migration entre versions, migration production vers developpement
- **Outils de performance** : mesure de requetes par seconde, execution de tests en parallele, analyse de couverture


# Versions Odoo supportees


| Odoo version | Python  | Status     |
|--------------|---------|------------|
| 18.0         | 3.12.10 | Active     |
| 17.0         | 3.10.18 | Inactive   |
| 16.0         | 3.10.18 | Inactive   |
| 15.0         | 3.8.20  | Deprecated |
| 14.0         | 3.8.20  | Deprecated |
| 13.0         | 3.7.17  | Deprecated |
| 12.0         | 3.7.17  | Deprecated |


Changez de version avec `make switch_odoo_18`, `make switch_odoo_16`, etc.


# Plateformes supportees

- **Linux** : Ubuntu 20.04, 22.04, 24.04, 25.04; Debian 12; Arch Linux
- **macOS** : via pyenv
- **Windows** : via WSL ou Docker
- **Mainframe** : architecture 390x


# Installation

## Installation facile sur Ubuntu ou Debian avec Docker

Ceci a ete teste sur Debian 12 et Ubuntu 24.04 LTS.

**Note** : Ceci est prevu pour un environnement de test, sur un reseau local ou un environnement similaire non expose
directement a Internet.


Clonez le projet :


```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```


Suivez les instructions du script suivant, il essaiera de detecter votre environnement.


```bash
make
```


### Manuellement

Sous Ubuntu, dependance minimale :


```bash
sudo apt install make git curl
```


Sous Ubuntu, dependance developpeur :


```bash
sudo apt install make build-essential libssl-dev zlib1g-dev libreadline-dev libsqlite3-dev curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev libbz2-dev libldap2-dev libsasl2-dev
```


Clonez le projet :


```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
```


Support Ubuntu 20.04, 22.04, 24.04, 25.04 et OSX.


```bash
make install_os
make install_odoo_18
```


Installez une version specifique d'Odoo :


```bash
make install_odoo_16
make install_odoo_17
make install_odoo_18
```


Mettez a jour votre configuration si vous devez executer depuis une autre interface que 127.0.0.1, fichier `config.conf`


```
xmlrpc_interface = 0.0.0.0
```


Afficher la version :


```bash
make version
```


Pret a executer :


```bash
make run
```


# Test

Executez les tests ERPLibre avec son generateur de code.


```bash
time make test_full_fast
```


# Documentation

| Guide | Description |
|-------|-------------|
| [DISCOVER](doc/DISCOVER.md) | Decouvrir et explorer ERPLibre |
| [DEVELOPMENT](doc/DEVELOPMENT.md) | Configuration de l'environnement de developpement |
| [PRODUCTION](doc/PRODUCTION.md) | Deploiement du serveur de production |
| [RUN](doc/RUN.md) | Modes d'execution et cas d'utilisation |
| [CODE_GENERATOR](doc/CODE_GENERATOR.md) | Generation de code de modules Odoo |
| [MIGRATION](doc/MIGRATION.md) | Migration de base de donnees entre versions |
| [GIT_REPO](doc/GIT_REPO.md) | Gestion des depots Git |
| [POETRY](doc/POETRY.md) | Gestion des dependances Python |
| [FAQ](doc/FAQ.md) | Foire aux questions |
| [HOWTO](doc/HOWTO.md) | Guides pratiques |
| [WINDOWS_INSTALLATION](doc/WINDOWS_INSTALLATION.md) | Installation sous Windows |


# Contribution

Consultez [CONTRIBUTION.md](doc/CONTRIBUTION.md) pour les directives.


# Licence

Ce projet est sous licence [GNU Affero General Public License v3.0](LICENSE).