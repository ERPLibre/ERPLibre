
# Poetry

## Ajouter des dépendances automatiquement

Ajoutez vos dépendances dans le fichier [requirements.txt](../requirements.txt) et exécutez le script

```bash
./script/poetry/poetry_update.py
```

Cela va chercher tous les fichiers `requirements.txt` et mettre à jour `pyproject.toml` et mettre à jour poetry

Les dépendances prioritaires sont dans ./requirements.txt, ensuite ./odoo/requirements.txt, puis les valeurs de version les plus élevées.

À FAIRE : ajouter une option pour seulement ajouter les dépendances manquantes et ignorer la mise à jour.

## Délai minimal de publication

`poetry.toml` fixe `solver.min-release-age = 7` : quand il résout (`poetry
lock`, `poetry add`, donc `make poetry_update`), Poetry ignore toute version
publiée depuis moins de 7 jours. Une version malveillante d'un paquet légitime,
poussée depuis le compte volé d'un mainteneur ou une chaîne de publication
compromise, est en général retirée en un à trois jours ; le délai la tient hors
du verrou. `poetry install` suit le verrou et n'est jamais retenu. Poetry 1.8,
celui des anciennes versions d'Odoo, ignore ce réglage.

`make poetry_update` exempte chaque paquet épinglé par `==` dans
`requirement/requirements.<version>.txt` : une telle épingle est un choix relu,
souvent un correctif de sécurité plus récent que le délai. Pour laisser passer
un paquet qui n'est pas épinglé, nommez-le, plusieurs séparés par des virgules :

```bash
POETRY_SOLVER_MIN_RELEASE_AGE_EXCLUDE=nom make poetry_update
POETRY_SOLVER_MIN_RELEASE_AGE_EXCLUDE=pypdf,lxml-html-clean make poetry_update
```

Le délai n'arrête ni une porte dérobée posée patiemment et découverte des
semaines plus tard, ni un typosquat ancien : les hash du verrou, la relecture
du diff du verrou et la veille CVE restent nécessaires.
`POETRY_SOLVER_MIN_RELEASE_AGE=0` lève le délai pour une exécution.

## Ajouter des dépendances manuellement

Le script automatique va écraser cette dépendance, mais vous pouvez l'ajouter pour vos tests locaux.

```bash
poetry add PYTHON_MODULE
```

## Erreur `relative path can't be expressed as a file URI`

Si vous obtenez cette erreur `relative path can't be expressed as a file URI` lors de l'exécution de poetry, supprimez le répertoire artifacts : `rm -rf artifacts/` et relancez la mise à jour.

## Mettre à jour Poetry

La version de chaque version d'Odoo est `poetry_version` dans
`conf/supported_version_erplibre.json` ; un changement de version l'écrit dans
`.poetry-version`. L'installation remplace le Poetry du venv d'Odoo dès que sa
version diffère de `.poetry-version` : un venv existant suit. Reverrouillez avec
la nouvelle version pour rafraîchir l'en-tête du verrou.

# FAQ

## Erreur "file could not be opened successfully"

Supprimez le cache à la racine du projet

```bash
rm -r cache
```

## Configurer un proxy avec poetry

Le proxy va créer un cache de tous les téléchargements.

https://github.com/EpicWink/proxpi

Installez et exécutez le serveur

```bash
pip3 install 'git+https://github.com/EpicWink/proxpi.git'
PROXPI_BINARY_FILE_MIME_TYPE=1 FLASK_APP=proxpi.server flask run
```

Ou par docker-compose, ajoutez l'environnement

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

Ajoutez cette configuration dans le pyproject.toml

```toml
[[tool.poetry.source]]
name = "proxpi"
url = "http://localhost:5000/index/"
default = true
secondary = false
```

ASTUCE : peut-être qu'avant `poetry install` dans le script d'installation, il faut faire `poetry lock --no-update`

En développement, une solution sans configurer pyproject.toml, mettez à jour le script d'installation comme suit :

```bash
${VENV_PATH}/bin/poetry self add git+https://github.com/mathben/poetry-plugin-pypi-proxy.git[plugin]
PIP_INDEX_URL=http://127.0.0.1:5000/index/ ${VENV_PATH}/bin/poetry install
```