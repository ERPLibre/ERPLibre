<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Selenium Installation

The scripts run in the tooling venv, `.venv.erplibre`, which already holds
`selenium` and `pykeepass`. `requirements.txt` adds the rest, none of which
needs a system library; `requirements-video.txt` adds the video recorder,
PyGObject, built against the system libraries below.
`script/install/install_debian_dependency.sh` installs them on Debian and
Ubuntu.

<!-- [fr] -->
# Installation de Selenium

Les scripts tournent dans le venv d'outillage, `.venv.erplibre`, qui contient
déjà `selenium` et `pykeepass`. `requirements.txt` ajoute le reste, dont
aucun ne demande de bibliothèque système ; `requirements-video.txt` ajoute
l'enregistreur vidéo, PyGObject, compilé contre les bibliothèques système
ci-dessous.
`script/install/install_debian_dependency.sh` les installe sur Debian et
Ubuntu.

<!-- [common] -->
```bash
.venv.erplibre/bin/pip install -r script/selenium/requirements.txt

sudo apt install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository-2.0-dev ffmpeg
.venv.erplibre/bin/pip install -r script/selenium/requirements-video.txt
```

<!-- [en] -->
PyGObject, which pulls pycairo, builds from 3.50 on against girepository-2.0
and requires GLib 2.80: Debian 13 and Ubuntu 24.04 have it, Debian 12 does
not, and there video recording is not available. `ffmpeg` converts the
recordings to MP4.

geckodriver needs no installation: Selenium Manager, shipped with `selenium`,
downloads it into `~/.cache/selenium` on first use. The Firefox driven is the
Ubuntu snap, else `firefox`, else `firefox-esr`, Debian's name.

Video recorder: https://github.com/szemate/pyselenium-video-recorder

<!-- [fr] -->
PyGObject, qui tire pycairo, se compile dès la 3.50 contre girepository-2.0
et exige GLib 2.80 : Debian 13 et Ubuntu 24.04 l'ont, Debian 12 non, et
l'enregistrement vidéo n'y est pas disponible. `ffmpeg` convertit les
enregistrements en MP4.

geckodriver ne demande aucune installation : Selenium Manager, livré avec
`selenium`, le télécharge dans `~/.cache/selenium` au premier usage. Le
Firefox piloté est le snap d'Ubuntu, sinon `firefox`, sinon `firefox-esr`,
son nom sous Debian.

Enregistreur vidéo : https://github.com/szemate/pyselenium-video-recorder

<!-- [en] -->
## In the ERPLibre container

The image has no browser and no display. The scripts drive a node of the
Selenium grid that `docker/docker-compose_odoo_18.0_selenium.yml` starts; the
node sends the downloads back to the script. Give `--url` too: the default,
`http://127.0.0.1:8069`, is read by the browser, on its node, where no Odoo
answers. The scripts run as `odoo`: the compose starts the container as root,
so `exec` opens root by default, and that root cannot read the password file
below.

<!-- [fr] -->
## Dans le conteneur ERPLibre

L'image n'a ni navigateur ni affichage. Les scripts pilotent un nœud de la
grille Selenium que démarre `docker/docker-compose_odoo_18.0_selenium.yml` ; le
nœud renvoie les téléchargements au script. Donnez aussi `--url` : la valeur
par défaut, `http://127.0.0.1:8069`, est lue par le navigateur, sur son nœud,
où aucun Odoo ne répond. Les scripts tournent sous `odoo` : le compose démarre
le conteneur en root, `exec` ouvre donc root par défaut, et ce root ne lit pas
le fichier du mot de passe ci-dessous.

<!-- [common] -->
```bash
docker compose --project-directory . -f docker/docker-compose_odoo_18.0_selenium.yml \
  exec -u odoo ERPLibre .venv.erplibre/bin/python script/selenium/SCRIPT.py \
  --use_network http://selenium-hub:4444 --url http://ERPLibre:8069
```

<!-- [en] -->
An ERPLibre image built from this version carries in `.venv.erplibre` the
packages the scripts import, listed in
`requirement/erplibre_require-ments-docker.txt`. The 1.8.0 image lacks them
and predates `KDBX_PASSWORD_FILE`: the compose can add the packages at each
start, but the scripts stay the image's older copies.

<!-- [fr] -->
Une image ERPLibre construite depuis cette version porte dans
`.venv.erplibre` les paquets qu'importent les scripts, listés dans
`requirement/erplibre_require-ments-docker.txt`. L'image 1.8.0 ne les a pas
et précède `KDBX_PASSWORD_FILE` : le compose peut ajouter les paquets à chaque
démarrage, mais les scripts restent les copies plus anciennes de l'image.

<!-- [common] -->
```yaml
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: "selenium pykeepass python-randomword-fr"
```

<!-- [en] -->
A script that logs in with the KeePass vault finds it at `kdbx.path` in
`private/todo/todo_override_private.json`. `KDBX_PASSWORD_FILE` names a file
that holds the password; the value itself stays out of the environment and of
the JSON. Once set, the variable wins over `kdbx.password` and over the
prompt, terminal or not, which lets a script run unattended; an unreadable
file, like a vault that does not open, stops the script with its cause. Two
commented lines of the compose set the variable and mount
`private/kdbx_password` read-only at that path:

<!-- [fr] -->
Un script qui se connecte avec le coffre KeePass le trouve à `kdbx.path` dans
`private/todo/todo_override_private.json`. `KDBX_PASSWORD_FILE` nomme un
fichier qui porte le mot de passe ; la valeur elle-même reste hors de
l'environnement et du JSON. Une fois posée, la variable l'emporte sur
`kdbx.password` et sur l'invite, terminal ou non, ce qui permet à un script de
tourner sans surveillance ; un fichier illisible, comme un coffre qui ne s'ouvre
pas, arrête le script avec sa cause. Deux lignes commentées du compose posent
la variable et montent `private/kdbx_password` en lecture seule à ce chemin :

<!-- [common] -->
```yaml
      KDBX_PASSWORD_FILE: /ERPLibre/private/kdbx_password
    volumes:
      - ./private/kdbx_password:/ERPLibre/private/kdbx_password:ro
```

<!-- [en] -->
The file belongs to uid 101, the image's `odoo` account, with mode 400. With a
Docker daemon run by root:

<!-- [fr] -->
Le fichier appartient à l'uid 101, le compte `odoo` de l'image, en mode 400.
Avec un démon Docker lancé par root :

<!-- [common] -->
```bash
sudo chown 101:101 private/kdbx_password && sudo chmod 400 private/kdbx_password
```

<!-- [en] -->
Rootless Docker maps the container's uid 101 to a host uid of its own: the
owner changes from a container of the compose's image, `IMAGE` below, as its
root.

<!-- [fr] -->
Docker sans root fait correspondre l'uid 101 du conteneur à un uid propre de
l'hôte : le propriétaire se change depuis un conteneur de l'image du compose,
`IMAGE` ci-dessous, sous son root.

<!-- [common] -->
```bash
chmod 400 private/kdbx_password
docker run --rm -u root -v "$PWD/private:/p" --entrypoint chown IMAGE 101:101 /p/kdbx_password
```
