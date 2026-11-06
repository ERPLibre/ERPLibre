
# Installation de Selenium

Les scripts tournent dans le venv d'outillage, `.venv.erplibre`, qui contient
déjà `selenium` et `pykeepass`. `requirements.txt` ajoute le reste, dont rien
ne se compile ; `requirements-video.txt` ajoute l'enregistreur vidéo,
PyGObject, compilé contre les bibliothèques système ci-dessous.
`script/install/install_debian_dependency.sh` les installe sur Debian et
Ubuntu.

```bash
.venv.erplibre/bin/pip install -r script/selenium/requirements.txt

sudo apt install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository-2.0-dev ffmpeg
.venv.erplibre/bin/pip install -r script/selenium/requirements-video.txt
```

PyGObject, qui tire pycairo, se compile dès la 3.50 contre girepository-2.0
et exige GLib 2.80 : Debian 13 et Ubuntu 24.04 l'ont, Debian 12 non, et
l'enregistrement vidéo n'y est pas disponible. `ffmpeg` convertit les
enregistrements en MP4.

geckodriver ne demande aucune installation : Selenium Manager, livré avec
`selenium`, le télécharge dans `~/.cache/selenium` au premier usage. Le
Firefox piloté est le snap d'Ubuntu, sinon `firefox`, sinon `firefox-esr`,
son nom sous Debian.

Enregistreur vidéo : https://github.com/szemate/pyselenium-video-recorder

## Dans le conteneur ERPLibre

L'image n'a ni navigateur ni affichage. Les scripts pilotent un nœud Selenium
par `--use_network http://selenium-hub:4444`, comme le monte
`docker/docker-compose_odoo_18.0_selenium.yml` ; le nœud renvoie les
téléchargements au script. `requirements.txt` s'installe à chaque démarrage
par le compose :

```yaml
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: "-r /ERPLibre/script/selenium/requirements.txt"
      KDBX_PASSWORD_FILE: /ERPLibre/private/kdbx_password
```

Un script qui se connecte avec le coffre KeePass le trouve à `kdbx.path` dans
`private/todo/todo_override_private.json`. Sans terminal où taper le mot de
passe, `KDBX_PASSWORD_FILE` nomme un fichier qui le porte, lisible par
`odoo` seul ; la valeur elle-même reste hors de l'environnement et du JSON.
Un coffre qui ne s'ouvre pas arrête le script avec sa cause.