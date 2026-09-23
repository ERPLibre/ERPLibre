---
name: erplibre-deployment
description: >-
  Déploiement ERPLibre : Docker, systemd, nginx, SSL, DNS, plateformes
  supportées, et le choix de l'interpréteur Python (EL_PYTHON_PROVIDER)
  comme du gestionnaire de paquets (EL_PIP_PROVIDER). À charger pour
  déployer, installer ou changer de fournisseur Python.
---

- **Docker** : `docker-compose.yml` (PostgreSQL 18 + PostGIS 3.6)
- **Systemd** : `script/systemd/` pour les services
- **Nginx** : `script/nginx/` pour le reverse proxy
- **SSL** : Certbot pour les certificats
- **DNS** : `script/deployment/update_dns_cloudflare.py`
- **VPN** : `script/vpn/` — cinq pilotes (L2TP/IPsec PSK, WireGuard,
  OpenVPN, OpenConnect, sshuttle), profils en JSON et secrets dans un
  coffre KeePassXC. Mode d'emploi : `script/vpn/README.md`.

Plateformes supportées : Ubuntu 24.04 / 25.10 / 26.04, Linux Mint 22.3,
Debian 12, AlmaLinux 9+, Rocky Linux 9+, openSUSE Leap 16 et Tumbleweed,
Arch Linux,
macOS (mise ou pyenv),
Windows (WSL/Docker).

Ubuntu 20.04 et 22.04 sont abandonnées : pikepdf exige qpdf >= 12.2, compilé
en C++20, quand focal livre GCC 9.

## Interpréteur Python

`EL_PYTHON_PROVIDER` (dans `env_var.sh`) vaut `auto`, `mise` ou `pyenv`.
`auto` reprend un interpréteur DÉJÀ posé, quel que soit le fournisseur ; sinon
il préfère mise, qui pose un CPython précompilé, et retombe sur pyenv, qui le
compile.

Un seul fichier décide : `script/install/lib_python_provider.sh`. mise n'est
jamais installé automatiquement — `make install_mise` porte cette décision.
Pas de binaire mise pour s390x à ce jour : cette architecture reste sur pyenv.

## Le Python de l'outillage

`conf/python-erplibre-version` (3.14.7) donne l'interpréteur de
`.venv.erplibre`, le venv d'outillage, distinct du venv Odoo (3.12.10 pour
Odoo 18.0). C'est la seule version que `script/` vise : là où une distribution
ne la porte pas, pyenv la compile.

`install_erplibre.sh` passe par `install_venv.sh`, donc par
`EL_PYTHON_PROVIDER`. Un venv dont `bin/python` n'est pas compatible (même
majeure.mineure, patch au moins égal) est DÉTRUIT puis rebâti : ce qui y avait
été posé à la main part avec lui. La règle vaut pour tout venv que reçoit
`install_venv.sh`, donc aussi celui d'Odoo lors d'un `make install_odoo_*`. Un répertoire sans `pyvenv.cfg` n'est jamais
effacé.

`make` / `make todo` hors venv : TODO se relance dans `.venv.erplibre` ; si le
venv manque, il propose `install_erplibre.sh` en terminal, ou nomme la
commande.

Le hook `pre-commit` relaie `script/analyse/check_python_version.py` : il
signale le source qui ne parse pas sous cette version, sans bloquer, et dit
quand aucun interpréteur de cette version n'était là pour vérifier.

L'image Docker de production bâtit `.venv.erplibre` sur le Python d'Odoo de son
image de base, et s'arrête si ce Python ne sait pas lire `script/`.

## Paquets Python

`EL_PIP_PROVIDER` (dans `env_var.sh`) vaut `auto`, `uv` ou `pip`. `auto` prend
uv s'il est présent et si le venv visé est en Python ≥ 3.8, sinon pip ; un
échec d'uv retombe sur pip. Un seul fichier décide :
`script/install/lib_pip_provider.sh`. uv n'est jamais installé
automatiquement — `make install_uv` porte cette décision.

Portée réelle : le venv d'outils et l'amorçage de Poetry. **`poetry install`
n'est pas concerné** — uv ne lit pas `poetry.lock` — et c'est pourtant l'étape
qui domine. Sur s390x le gain est quasi nul : une trentaine de paquets sans
roue se compilent, et uv n'enlève pas une seconde de gcc.
