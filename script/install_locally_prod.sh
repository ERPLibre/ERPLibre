#!/usr/bin/env bash

. ./env_var.sh

EL_USER=$(whoami)
EL_HOME=$PWD
EL_HOME_ODOO="${EL_HOME}/odoo"
#EL_INSTALL_WKHTMLTOPDF="True"
#EL_PORT="8069"
#EL_LONGPOLLING_PORT="8072"
#EL_SUPERADMIN="admin"
EL_CONFIG_FILE="${EL_HOME}/config.conf"
#EL_CONFIG="${EL_USER}"
#EL_MINIMAL_ADDONS="False"
#EL_INSTALL_NGINX="True"
#EL_MANIFEST_PROD="./manifest/default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

./script/install_locally.sh

# Update git-repo
./venv/repo init -u http://git.erplibre.ca/ERPLibre -b master
#./venv/repo sync --force-sync
./venv/repo sync

echo -e "\n---- Install python packages/requirements ----"
${EL_HOME}/venv/bin/pip3 install --upgrade pip
${EL_HOME}/venv/bin/pip3 install wheel phonenumbers
${EL_HOME}/venv/bin/pip3 install -r "${EL_HOME}/odoo/requirements.txt"
${EL_HOME}/venv/bin/pip3 install -r "${EL_HOME}/requirements.txt"

# For dev/testing
${EL_HOME}/venv/bin/pip3 install websocket-client

echo -e "\n---- Add link dependency in site-packages of Python ----"
if [[ ${PYTHON37} = "True" ]]; then
    ln -fs ${EL_HOME_ODOO}/odoo ${EL_HOME}/venv/lib/python3.7/site-packages/
elif [[ ${PYTHON36} = "True" ]]; then
    ln -fs ${EL_HOME_ODOO}/odoo ${EL_HOME}/venv/lib/python3.6/site-packages/
fi
