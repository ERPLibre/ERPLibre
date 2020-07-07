#!/usr/bin/env bash

EL_USER="erplibre"
EL_HOME="/${EL_USER}"
EL_HOME_ERPLIBRE="${EL_HOME}/erplibre"
EL_HOME_ODOO="${EL_HOME_ERPLIBRE}/odoo"
# The default port where this Odoo instance will run under (provided you use the command -c in the terminal)
# Set to true if you want to install it, false if you don't need it or have it already installed.
EL_INSTALL_WKHTMLTOPDF="True"
# Set the default Odoo port
EL_PORT="8069"
EL_LONGPOLLING_PORT="8072"
# set the superadmin password
EL_SUPERADMIN="admin"
EL_CONFIG="${EL_USER}"
EL_MINIMAL_ADDONS="False"
# Set this to True if you want to install Nginx!
EL_INSTALL_NGINX="True"
# Set the website name
EL_WEBSITE_NAME="_"
EL_GITHUB_TOKEN=""
EL_MANIFEST_PROD="./default.xml"
EL_MANIFEST_DEV="./manifest/default.dev.xml"
