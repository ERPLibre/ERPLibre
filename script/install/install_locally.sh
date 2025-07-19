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

# Generate empty addons if missing
path_addons_addons="./addons.odoo${EL_ODOO_VERSION}/addons"
if [[ ! -d "${path_addons_addons}" ]]; then
    mkdir -p "${path_addons_addons}"
fi

# example, 3.7.8 will be 3.7 into PYTHON_VERSION_MAJOR
PYTHON_VERSION_MAJOR=$(echo "$EL_PYTHON_ODOO_VERSION" | sed 's/\.[^\.]*$//')
VENV_ERPLIBRE_PATH=.venv.erplibre
VENV_ODOO_PATH=".venv.${EL_ERPLIBRE_VERSION}"
POETRY_ODOO_PATH=${VENV_ERPLIBRE_PATH}/bin/poetry
export WITH_POETRY_INSTALLATION=1

if [[ ! -n "${DOCKER_BUILD}" ]]; then
  # Install ERPLibre venv
  echo -e "Install ${VENV_ERPLIBRE_PATH} with ${EL_PYTHON_ERPLIBRE_VERSION}"
  ./script/install/install_venv.sh "ERPLibre" "${VENV_ERPLIBRE_PATH}" "${EL_PYTHON_ERPLIBRE_VERSION}"
  # Install Odoo venv
  echo -e "Install ${VENV_ODOO_PATH} with ${EL_PYTHON_ODOO_VERSION}"
  ./script/install/install_venv.sh "Odoo" "${VENV_ODOO_PATH}" "${EL_PYTHON_ODOO_VERSION}"
else
  mkdir .venv
fi

source ./${VENV_ERPLIBRE_PATH}/bin/activate
echo -e "Upgrade pip to ${VENV_ERPLIBRE_PATH}"
pip install --upgrade pip
pip install -r requirement/erplibre_require-ments.txt

source ${VENV_ODOO_PATH}/bin/activate
echo -e "Upgrade pip to ${VENV_ODOO_PATH}"
pip install --upgrade pip

echo -e "\n---- Installing poetry dependency ----"

# Delete artifacts created by pip, cause error in next "poetry install"
if [[ ! -f "${POETRY_ODOO_PATH}" ]]; then
    echo -e "Install Poetry ${POETRY_ODOO_PATH}"
    pip install poetry==${EL_POETRY_VERSION}
    poetry --version
    # Fix broken poetry by installing ignored dependence
    #    poetry lock --no-update
    # To fix keyring problem when installation is blocked, use
    export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
    if [[ ${WITH_POETRY_INSTALLATION} -ne 0 ]]; then
      poetry install --no-root -vvv
    fi
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
        echo "Poetry installation error with status ${retVal}"
        exit 1
    fi
fi

# Delete artifacts created by pip, cause error in next "poetry install"
rm -rf artifacts

# Link for dev tools into Odoo
echo -e "\n---- Add link dependency in site-packages of Python ----"
# TODO this link can break, the symbolic link is maybe not created
ln -fs "${EL_HOME_ODOO}/odoo" "${EL_HOME}/${VENV_ODOO_PATH}/lib/python${PYTHON_VERSION_MAJOR}/site-packages/"

source ./${VENV_ERPLIBRE_PATH}/bin/activate

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