#!/usr/bin/env bash

. ./env_var.sh

EL_USER=${USER}
EL_HOME=$PWD
EL_HOME_ODOO="${EL_HOME}/odoo"
#EL_INSTALL_WKHTMLTOPDF="True"
#EL_PORT="8069"
#EL_LONGPOLLING_PORT="8072"
#EL_SUPERADMIN="admin"
#EL_CONFIG_FILE="${EL_HOME}/config.conf"
#EL_CONFIG="${EL_USER}"
#EL_MINIMAL_ADDONS="False"
#EL_INSTALL_NGINX="True"

./script/generate_config.sh

#echo -e "\n---- Install Odoo with addons module ----"
#git submodule update --init

# Generate empty addons if missing
if [[ ! -d "./addons/addons" ]]; then
    mkdir -p ./addons/addons
fi

PYENV_PATH=~/.pyenv
PYTHON_VERSION=3.7.12
PYENV_VERSION_PATH=${PYENV_PATH}/versions/${PYTHON_VERSION}
PYTHON_EXEC=${PYENV_VERSION_PATH}/bin/python
POETRY_PATH=~/.poetry
VENV_PATH=./.venv
LOCAL_PYTHON_EXEC=${VENV_PATH}/bin/python
VENV_REPO_PATH=${VENV_PATH}/repo
VENV_MULTILINGUAL_MARKDOWN_PATH=${VENV_PATH}/multilang_md.py
POETRY_VERSION=1.0.10

echo "Python path version home"
echo ${PYENV_VERSION_PATH}
echo "Python path version local"
echo ${LOCAL_PYTHON_EXEC}

if [[ ! -d "${PYENV_PATH}" ]]; then
    echo -e "\n---- Installing pyenv in ${PYENV_PATH} ----"
    curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash
fi

echo -e "\n---- Export pyenv in ${PYENV_PATH} ----"
export PATH="${PYENV_PATH}/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

if [[ ! -d "${PYENV_VERSION_PATH}" ]]; then
    echo -e "\n---- Installing python ${PYTHON_VERSION} with pyenv in ${PYENV_VERSION_PATH} ----"
    yes n|pyenv install ${PYTHON_VERSION}
    if [[ $retVal -ne 0 ]]; then
        echo "Error when installing pyenv"
        exit 1
    fi
fi

pyenv local ${PYTHON_VERSION}

if [[ ! -d ${VENV_PATH} ]]; then
    echo -e "\n---- Create Virtual environment Python ----"
    if [[ -e ${PYTHON_EXEC} ]]; then
        ${PYTHON_EXEC} -m venv .venv
        retVal=$?
          if [[ $retVal -ne 0 ]]; then
              echo "Virtual environment, error when creating .venv"
              exit 1
          fi
    else
        echo "Missing pyenv, please refer installation guide."
        exit 1
    fi
fi

if [[ ! -d "${POETRY_PATH}" ]]; then
    # Delete directory ~/.poetry and .venv to force update to new version
    echo -e "\n---- Installing poetry for reliable python package ----"
#     curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | ${PYTHON_EXEC}
    curl -fsS -o get-poetry.py https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py
    ${LOCAL_PYTHON_EXEC} get-poetry.py -y --preview --version ${POETRY_VERSION}
fi

# Install git-repo if missing
if [[ ! -f ${VENV_REPO_PATH} ]]; then
    echo "\n---- Install git-repo from Google APIS ----"
    curl https://storage.googleapis.com/git-repo-downloads/repo > ${VENV_REPO_PATH}
    chmod +x ${VENV_REPO_PATH}
    sed -i 1d ${VENV_REPO_PATH}
    PYTHON_HASHBANG="#!./.venv/bin/python"
    sed -i "1 i ${PYTHON_HASHBANG}" ${VENV_REPO_PATH}
fi

# Install Multilingual Markdown Generator if missing
if [[ ! -f ${VENV_MULTILINGUAL_MARKDOWN_PATH} ]]; then
    echo "\n---- Install Multilingual Markdown Generator ----"
    curl https://raw.githubusercontent.com/ERPLibre/multilingual-markdown/master/multilang_md.py > ${VENV_MULTILINGUAL_MARKDOWN_PATH}
    chmod +x ${VENV_MULTILINGUAL_MARKDOWN_PATH}
    sed -i 1d ${VENV_MULTILINGUAL_MARKDOWN_PATH}
    PYTHON_HASHBANG="#!./.venv/bin/python"
    sed -i "1 i ${PYTHON_HASHBANG}" ${VENV_MULTILINGUAL_MARKDOWN_PATH}
fi

echo -e "\n---- Installing poetry dependency ----"
${VENV_PATH}/bin/pip install --upgrade pip
# Force python instead of changing env
#/home/"${USER}"/.poetry/bin/poetry env use ${LOCAL_PYTHON_EXEC}
# source $HOME/.poetry/env
${LOCAL_PYTHON_EXEC} ~/.poetry/bin/poetry install
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Poetry installation error."
    exit 1
fi
# Delete artifacts created by pip, cause error in next "poetry install"
rm -rf artifacts

# Link for dev
echo -e "\n---- Add link dependency in site-packages of Python ----"
ln -fs ${EL_HOME_ODOO}/odoo ${EL_HOME}/.venv/lib/python3.7/site-packages/
