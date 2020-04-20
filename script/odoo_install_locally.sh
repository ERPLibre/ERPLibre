#!/bin/bash
################################################################################
# Script for installing Odoo on Ubuntu 14.04, 15.04, 16.04 and 18.04 (could be used for other version too)
# Author: Yenthe Van Ginneken
#-------------------------------------------------------------------------------
# This script will install Odoo on your Ubuntu 16.04 server. It can install multiple Odoo instances
# in one Ubuntu because of the different xmlrpc_ports
#-------------------------------------------------------------------------------
# Make a new file:
# sudo nano odoo-install.sh
# Place this content in it and then make the file executable:
# sudo chmod +x odoo-install.sh
# Execute the script to install Odoo:
# ./odoo-install
################################################################################

. ./env_var.sh

OE_USER=$(whoami)
OE_HOME=$PWD
OE_HOME_EXT="${OE_HOME}/odoo"
# The default port where this Odoo instance will run under (provided you use the command -c in the terminal)
# Set to true if you want to install it, false if you don't need it or have it already installed.
#INSTALL_WKHTMLTOPDF="True"
# Set the default Odoo port (you still have to use -c /etc/odoo-server.conf for example to use this.)
#OE_PORT="8069"
#OE_LONGPOLLING_PORT="8072"
# Choose the Odoo version which you want to install. For example: 12.0, 11.0, 10.0 or saas-18. When using 'master' the master version will be installed.
# IMPORTANT! This script contains extra libraries that are specifically needed for Odoo 12.0
#OE_VERSION="stable_prod_12.0"
# set the superadmin password
#OE_SUPERADMIN="admin"
OE_CONFIG_FILE="${OE_HOME}/config.conf"
#OE_CONFIG="${OE_USER}"
#MINIMAL_ADDONS="False"
#INSTALL_NGINX="True"

if hash python3.7 2>/dev/null; then
    PYTHON37="True"
    PYTHON36="False"
elif hash python3.6 2>/dev/null; then
    PYTHON37="False"
    PYTHON36="True"
else
    echo "Missing python3.7 or python3.6. Python3.8 is not compatible."
    exit 1
fi

echo -e "* Create server config file"

touch ${OE_CONFIG_FILE}
echo -e "* Creating server config file"
printf '[options] \n; This is the password that allows database operations:\n' > ${OE_CONFIG_FILE}
printf "admin_passwd = ${OE_SUPERADMIN}\n" >> ${OE_CONFIG_FILE}
printf "db_host = False\n" >> ${OE_CONFIG_FILE}
printf "db_port = False\n" >> ${OE_CONFIG_FILE}
printf "db_user = ${OE_USER}\n" >> ${OE_CONFIG_FILE}
printf "db_password = False\n" >> ${OE_CONFIG_FILE}
printf "xmlrpc_port = ${OE_PORT}\n" >> ${OE_CONFIG_FILE}
printf "longpolling_port = ${OE_LONGPOLLING_PORT}\n" >> ${OE_CONFIG_FILE}

printf "addons_path = ${OE_HOME_EXT}/addons,${OE_HOME}/addons/addons," >> ${OE_CONFIG_FILE}
printf "${OE_HOME}/addons/OCA_web," >> ${OE_CONFIG_FILE}
if [[ $MINIMAL_ADDONS = "False" ]]; then
    printf "${OE_HOME}/addons/ERPLibre_erplibre_addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/MathBenTech_development," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/MathBenTech_odoo-business-spending-management-quebec-canada," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/MathBenTech_scrummer," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-base-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-entertainment-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-git-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-hr-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-partner-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-product-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-project-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-purchase-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-stock-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-survey-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-timesheet-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Numigi_odoo-web-addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-analytic," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-budgeting," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-closing," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-consolidation," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-financial-reporting," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-financial-tools," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-fiscal-rule," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-invoice-reporting," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-invoicing," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-payment," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_account-reconcile," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_apps-store," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_bank-payment," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_bank-statement-import," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_brand," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_business-requirement," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_commission," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_community-data-files," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_connector-telephony," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_contract," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_credit-control," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_currency," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_data-protection," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_donation," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_e-commerce," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_edi," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_event," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_helpdesk," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_hr," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_knowledge," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_l10n-canada," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_maintenance," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_management-system," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_manufacture," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_margin-analysis," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_mis-builder," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_multi-company," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_partner-contact," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_pos," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_product-attribute," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_product-pack," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_product-variant," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_project," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_project-reporting," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_purchase-workflow," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_queue," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_reporting-engine," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_sale-workflow," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_server-auth," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_server-brand," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_server-env," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_server-tools," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_server-ux," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_social," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_stock-logistics-warehouse," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_timesheet," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_website," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/OCA_wms," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/SanteLibre_santelibre_addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/Smile-SA_odoo_addons," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_base," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_dms," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_docs," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_misc," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_quality," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_web," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/muk-it_muk_website," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/odooaktiv_QuotationRevision," >> ${OE_CONFIG_FILE}
    printf "${OE_HOME}/addons/openeducat_openeducat_erp," >> ${OE_CONFIG_FILE}
fi
printf "\n" >> ${OE_CONFIG_FILE}

printf "workers = 0\n" >> ${OE_CONFIG_FILE}
printf "max_cron_threads = 2\n" >> ${OE_CONFIG_FILE}

if [ ${INSTALL_NGINX} = "True" ]; then
    printf "xmlrpc_interface = 127.0.0.1\n" >> ${OE_CONFIG_FILE}
    printf "netrpc_interface = 127.0.0.1\n" >> ${OE_CONFIG_FILE}
    printf "proxy_mode = True\n" >> ${OE_CONFIG_FILE}
fi

echo -e "\n---- Install Odoo with addons module ----"
git submodule update --init

echo -e "\n---- Create Virtual environment Python ----"
cd ${OE_HOME}
if [[ ${PYTHON37} = "True" ]]; then
    python3.7 -m venv venv
elif [[ ${PYTHON36} = "True" ]]; then
    python3.6 -m venv venv
fi
cd -

echo -e "\n---- Install python packages/requirements ----"
${OE_HOME}/venv/bin/pip3 install --upgrade pip
${OE_HOME}/venv/bin/pip3 install wheel phonenumbers
${OE_HOME}/venv/bin/pip3 install -r "${OE_HOME}/odoo/requirements.txt"
${OE_HOME}/venv/bin/pip3 install -r "${OE_HOME}/requirements.txt"

# For dev/testing
${OE_HOME}/venv/bin/pip3 install websocket-client

echo -e "\n---- Add link dependency in site-packages of Python ----"
if [[ ${PYTHON37} = "True" ]]; then
    ln -fs ${OE_HOME_EXT}/odoo ${OE_HOME}/venv/lib/python3.7/site-packages/
elif [[ ${PYTHON36} = "True" ]]; then
    ln -fs ${OE_HOME_EXT}/odoo ${OE_HOME}/venv/lib/python3.6/site-packages/
fi
