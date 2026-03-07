
# Poetry

## Add dependencies automatically

Add your dependencies in file [requirements.txt](../requirements.txt) and run script

```bash
./script/poetry/poetry_update.py
```

This will search all `requirements.txt` files and update `pyproject.toml` and it will update poetry

Priority dependencies in ./requirements.txt, after it's ./odoo/requirements.txt, after it's highest version values.

TODO add option to only add missing dependencies and ignore update.

## Add dependencies manually

The automatic script will erase this dependency, but you can add it for your local test.

```bash
poetry add PYTHON_MODULE
```

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

```bash
rm -r cache
```

## Configure a proxy with poetry

The proxy will create a cache of all downloads.

https://github.com/EpicWink/proxpi

Install and run the server

```bash
pip3 install 'git+https://github.com/EpicWink/proxpi.git'
PROXPI_BINARY_FILE_MIME_TYPE=1 FLASK_APP=proxpi.server flask run
```

Or by docker-compose, add the environment

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

Add this configuration into the pyproject.toml

```toml
[[tool.poetry.source]]
name = "proxpi"
url = "http://localhost:5000/index/"
default = true
secondary = false
```

TIPS, maybe before `poetry install` into installation script, need to do `poetry lock --no-update`

In development, a solution without configuring pyproject.toml, update installation script like :

```bash
${VENV_PATH}/bin/poetry self add git+https://github.com/mathben/poetry-plugin-pypi-proxy.git[plugin]
PIP_INDEX_URL=http://127.0.0.1:5000/index/ ${VENV_PATH}/bin/poetry install
```