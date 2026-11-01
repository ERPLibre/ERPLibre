
# Poetry

## Add dependencies automatically

Add your dependencies in file [requirements.txt](../requirements.txt) and run script

```bash
./script/poetry/poetry_update.py
```

This will search all `requirements.txt` files and update `pyproject.toml` and it will update poetry

Priority dependencies in ./requirements.txt, after it's ./odoo/requirements.txt, after it's highest version values.

TODO add option to only add missing dependencies and ignore update.

## Minimum release age

`poetry.toml` sets `solver.min-release-age = 7`: when it resolves (`poetry
lock`, `poetry add`, thus `make poetry_update`), Poetry ignores any release
published less than 7 days ago. A malicious version of a legitimate package,
pushed from a stolen maintainer account or a compromised release pipeline, is
usually withdrawn within one to three days; the delay keeps it out of the lock.
`poetry install` follows the lock and is never held back. Poetry 1.8, used by
older Odoo versions, ignores the setting.

`make poetry_update` exempts every package pinned with `==` in
`requirement/requirements.<version>.txt`: such a pin is a reviewed choice,
often a security fix younger than the delay. To let a package that is not
pinned through the delay, name it, several separated by commas:

```bash
POETRY_SOLVER_MIN_RELEASE_AGE_EXCLUDE=nom make poetry_update
POETRY_SOLVER_MIN_RELEASE_AGE_EXCLUDE=pypdf,lxml-html-clean make poetry_update
```

The delay does not stop a backdoor planted patiently and found weeks later,
nor an old typosquat: the lock hashes, reading the lock diff and the CVE watch
remain needed. `POETRY_SOLVER_MIN_RELEASE_AGE=0` lifts the delay for one run.

## Add dependencies manually

The automatic script will erase this dependency, but you can add it for your local test.

```bash
poetry add PYTHON_MODULE
```

## Error `relative path can't be expressed as a file URI`

If you got this error `relative path can't be expressed as a file URI` when executing poetry, delete directory
artifacts: `rm -rf artifacts/` and rerun the update.

## Upgrade Poetry

The version of each Odoo version is `poetry_version` in
`conf/supported_version_erplibre.json`; a switch writes it to `.poetry-version`.
The installation replaces the Poetry of the Odoo virtual environment whenever
its version differs from `.poetry-version`, so an existing environment follows.
Relock with the new version to refresh the header of the lock.

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