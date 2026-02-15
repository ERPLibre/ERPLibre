<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Poetry

## Add dependencies automatically

Add your dependencies in file [requirements.txt](../requirements.txt) and run script

<!-- [fr] -->
# Poetry

## Ajouter des dépendances automatiquement

Ajoutez vos dépendances dans le fichier [requirements.txt](../requirements.txt) et exécutez le script

<!-- [common] -->
```bash
./script/poetry/poetry_update.py
```

<!-- [en] -->
This will search all `requirements.txt` files and update `pyproject.toml` and it will update poetry

Priority dependencies in ./requirements.txt, after it's ./odoo/requirements.txt, after it's highest version values.

TODO add option to only add missing dependencies and ignore update.

## Add dependencies manually

The automatic script will erase this dependency, but you can add it for your local test.

<!-- [fr] -->
Cela va chercher tous les fichiers `requirements.txt` et mettre à jour `pyproject.toml` et mettre à jour poetry

Les dépendances prioritaires sont dans ./requirements.txt, ensuite ./odoo/requirements.txt, puis les valeurs de version les plus élevées.

À FAIRE : ajouter une option pour seulement ajouter les dépendances manquantes et ignorer la mise à jour.

## Ajouter des dépendances manuellement

Le script automatique va écraser cette dépendance, mais vous pouvez l'ajouter pour vos tests locaux.

<!-- [common] -->
```bash
poetry add PYTHON_MODULE
```

<!-- [en] -->
## Error `relative path can't be expressed as a file URI`

If you got this error `relative path can't be expressed as a file URI` when executing poetry, delete directory
artifacts: `rm -rf artifacts/` and rerun the update.

## Upgrade Poetry

Change version in file `./script/install/install_locally.sh` into constant `POETRY_VERSION`.

Erase directory `~/.poetry` and `./get-poetry.py`.

Run installation script for OS, check `./script/install/install_locally.sh`.

# FAQ

## Got error "file could not be opened successfully"

Delete cache at root of the project

<!-- [fr] -->
## Erreur `relative path can't be expressed as a file URI`

Si vous obtenez cette erreur `relative path can't be expressed as a file URI` lors de l'exécution de poetry, supprimez le répertoire artifacts : `rm -rf artifacts/` et relancez la mise à jour.

## Mettre à jour Poetry

Changez la version dans le fichier `./script/install/install_locally.sh` dans la constante `POETRY_VERSION`.

Supprimez le répertoire `~/.poetry` et `./get-poetry.py`.

Exécutez le script d'installation pour votre OS, vérifiez `./script/install/install_locally.sh`.

# FAQ

## Erreur "file could not be opened successfully"

Supprimez le cache à la racine du projet

<!-- [common] -->
```bash
rm -r cache
```

<!-- [en] -->
## Configure a proxy with poetry

The proxy will create a cache of all downloads.

https://github.com/EpicWink/proxpi

Install and run the server

<!-- [fr] -->
## Configurer un proxy avec poetry

Le proxy va créer un cache de tous les téléchargements.

https://github.com/EpicWink/proxpi

Installez et exécutez le serveur

<!-- [common] -->
```bash
pip3 install 'git+https://github.com/EpicWink/proxpi.git'
PROXPI_BINARY_FILE_MIME_TYPE=1 FLASK_APP=proxpi.server flask run
```

<!-- [en] -->
Or by docker-compose, add the environment

<!-- [fr] -->
Ou par docker-compose, ajoutez l'environnement

<!-- [common] -->
```
services:
  proxpi:
    restart: unless-stopped
    ports:
      - '5000:5000'
    image: epicwink/proxpi:latest
    environment:
      - PROXPI_BINARY_FILE_MIME_TYPE=1
```

<!-- [en] -->
Add this configuration into the pyproject.toml

<!-- [fr] -->
Ajoutez cette configuration dans le pyproject.toml

<!-- [common] -->
```toml
[[tool.poetry.source]]
name = "proxpi"
url = "http://localhost:5000/index/"
default = true
secondary = false
```

<!-- [en] -->
TIPS, maybe before `poetry install` into installation script, need to do `poetry lock --no-update`

In development, a solution without configuring pyproject.toml, update installation script like :

<!-- [fr] -->
ASTUCE : peut-être qu'avant `poetry install` dans le script d'installation, il faut faire `poetry lock --no-update`

En développement, une solution sans configurer pyproject.toml, mettez à jour le script d'installation comme suit :

<!-- [common] -->
```bash
${VENV_PATH}/bin/poetry self add git+https://github.com/mathben/poetry-plugin-pypi-proxy.git[plugin]
PIP_INDEX_URL=http://127.0.0.1:5000/index/ ${VENV_PATH}/bin/poetry install
```
