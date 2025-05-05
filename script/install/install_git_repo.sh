#!/usr/bin/env bash

VENV_ERPLIBRE_PATH=$(cat "conf/python-erplibre-venv" | xargs)

VENV_REPO_PATH=${VENV_ERPLIBRE_PATH}/bin/repo
# Install git-repo if missing
if [[ ! -f ${VENV_REPO_PATH} ]]; then
    echo "\n---- Install git-repo from Google APIS ----"
    curl https://storage.googleapis.com/git-repo-downloads/repo > ${VENV_REPO_PATH}
    chmod +x ${VENV_REPO_PATH}
    sed -i 1d ${VENV_REPO_PATH}
    PYTHON_HASHBANG="#!./${VENV_ERPLIBRE_PATH}/bin/python"
    sed -i "1 i ${PYTHON_HASHBANG}" ${VENV_REPO_PATH}
fi
