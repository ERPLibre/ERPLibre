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

Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

./script/generate_config.sh

#echo -e "\n---- Install Odoo with addons module ----"
#git submodule update --init

# Generate empty addons if missing
path_addons_addons="./addons.odoo${EL_ODOO_VERSION}/addons"
if [[ ! -d "${path_addons_addons}" ]]; then
    mkdir -p "${path_addons_addons}"
fi

PYENV_PATH=~/.pyenv
# example, 3.7.8 will be 3.7 into PYTHON_VERSION_MAJOR
PYTHON_VERSION_MAJOR=$(echo "$EL_PYTHON_VERSION" | sed 's/\.[^\.]*$//')
PYENV_VERSION_PATH=${PYENV_PATH}/versions/${EL_PYTHON_VERSION}
PYTHON_EXEC=${PYENV_VERSION_PATH}/bin/python
VENV_PATH=./.venv
LOCAL_PYTHON_EXEC=${VENV_PATH}/bin/python
VENV_REPO_PATH=${VENV_PATH}/repo
VENV_MULTILINGUAL_MARKDOWN_PATH=${VENV_PATH}/multilang_md.py
#POETRY_PATH=~/.local/bin/poetry
POETRY_PATH=${VENV_PATH}/bin/poetry
export WITH_POETRY_INSTALLATION=1

if [[ ! -n "${DOCKER_BUILD}" ]]; then
  echo "Python path version home"
  echo ${PYENV_VERSION_PATH}
  echo "Python path version local"
  echo ${LOCAL_PYTHON_EXEC}

  if [[ ! -d "${PYENV_PATH}" ]]; then
      echo -e "\n---- Installing pyenv in ${PYENV_PATH} ----"
      # export PYENV_GIT_TAG=v2.3.35
      # To change version
      # rm ~/.pyenv to uninstall it
      curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash
  fi

  echo -e "\n---- Export pyenv in ${PYENV_PATH} ----"
  export PATH="${PYENV_PATH}/bin:$PATH"
  eval "$(pyenv init -)"
  eval "$(pyenv virtualenv-init -)"

  if [[ ! -d "${PYENV_VERSION_PATH}" ]]; then
      echo -e "\n---- Installing python ${PYTHON_VERSION} with pyenv in ${PYENV_VERSION_PATH} ----"
      # Update all python version list
      cd "${PYENV_PATH}" && git pull && cd -
      yes n|pyenv install ${PYTHON_VERSION}
      if [[ $retVal -ne 0 ]]; then
          echo -e "${Red}Error${Color_Off} when installing pyenv"
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
  source ./.venv/bin/activate
else
  mkdir .venv
fi

#if [[ ! -d "${POETRY_PATH}" ]]; then
#    # Delete directory ~/.poetry and .venv to force update to new version
#    echo -e "\n---- Installing poetry ${LOCAL_PYTHON_EXEC} for reliable python package ----"
#    # TODO self update poetry with `poetry self update ${POETRY_VERSION}`
#    curl -sSL https://install.python-poetry.org | POETRY_VERSION=${EL_POETRY_VERSION} ${LOCAL_PYTHON_EXEC} - -y
#fi

# Install git-repo if missing
if [[ ! -f ${VENV_REPO_PATH} ]]; then
    echo "\n---- Install git-repo from Google APIS ----"
    curl https://storage.googleapis.com/git-repo-downloads/repo > ${VENV_REPO_PATH}
    chmod +x ${VENV_REPO_PATH}
    sed -i 1d ${VENV_REPO_PATH}
    PYTHON_HASHBANG="#!./.venv/bin/python"
    sed -i "1 i ${PYTHON_HASHBANG}" ${VENV_REPO_PATH}
fi

# Make .venv active
if [[ "${OSTYPE}" == "darwin"* ]]; then
  echo -e "=======>source .venv/bin/activate here!!!    <==============="
  source .venv/bin/activate
fi
echo -e "\n---- Installing poetry dependency ----"
${VENV_PATH}/bin/pip install --upgrade pip
# Force python instead of changing env
#/home/"${USER}"/.poetry/bin/poetry env use ${LOCAL_PYTHON_EXEC}
# source $HOME/.poetry/env
#${LOCAL_PYTHON_EXEC} ~/.poetry/bin/poetry env use ${VENV_PATH}/bin/python3
#${LOCAL_PYTHON_EXEC} ~/.poetry/bin/poetry install
#${POETRY_PATH} install

# Delete artifacts created by pip, cause error in next "poetry install"
if [[ ! -f "${POETRY_PATH}" ]]; then
    ${VENV_PATH}/bin/pip install poetry==${EL_POETRY_VERSION}
    ${VENV_PATH}/bin/poetry --version
    # Fix broken poetry by installing ignored dependence
    #    ${VENV_PATH}/bin/pip install vatnumber
    #    ${VENV_PATH}/bin/pip install suds-jurko
    #    ${VENV_PATH}/bin/poetry lock --no-update
    # To fix keyring problem when installation is blocked, use
    export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
    if [[ ${WITH_POETRY_INSTALLATION} -ne 0 ]]; then
      ${VENV_PATH}/bin/poetry install --no-root -vvv
    fi
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
        echo "Poetry installation error with status ${retVal}"
        exit 1
    fi
fi

# Delete artifacts created by pip, cause error in next "poetry install"
rm -rf artifacts

# Link for dev
echo -e "\n---- Add link dependency in site-packages of Python ----"
# TODO this link can break, the symbolic link is maybe not created
ln -fs "${EL_HOME_ODOO}/odoo" "${EL_HOME}/.venv/lib/python${PYTHON_VERSION_MAJOR}/site-packages/"
