#!/usr/bin/env bash

. ./env_var.sh

EL_USER=${USER}
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

echo -e "* Create server config file"

touch ${EL_CONFIG_FILE}
echo -e "* Creating server config file"
printf '[options] \n; This is the password that allows database operations:\n' > ${EL_CONFIG_FILE}
printf "admin_passwd = ${EL_SUPERADMIN}\n" >> ${EL_CONFIG_FILE}
printf "db_host = False\n" >> ${EL_CONFIG_FILE}
printf "db_port = False\n" >> ${EL_CONFIG_FILE}
printf "db_user = ${EL_USER}\n" >> ${EL_CONFIG_FILE}
printf "db_password = False\n" >> ${EL_CONFIG_FILE}
printf "xmlrpc_port = ${EL_PORT}\n" >> ${EL_CONFIG_FILE}
printf "longpolling_port = ${EL_LONGPOLLING_PORT}\n" >> ${EL_CONFIG_FILE}

printf "addons_path = ${EL_HOME_ODOO}/addons,${EL_HOME}/addons/addons," >> ${EL_CONFIG_FILE}
printf "${EL_HOME}/addons/OCA_web," >> ${EL_CONFIG_FILE}
if [[ ${EL_MINIMAL_ADDONS} = "False" ]]; then
    printf "${EL_HOME}/addons/ERPLibre_erplibre_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_development," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_odoo-business-spending-management-quebec-canada," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_scrummer," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-base-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-entertainment-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-git-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-hr-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-partner-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-product-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-project-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-purchase-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-stock-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-survey-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-timesheet-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-web-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-analytic," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-budgeting," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-closing," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-consolidation," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-financial-reporting," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-financial-tools," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-fiscal-rule," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-invoice-reporting," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-invoicing," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-payment," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_account-reconcile," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_apps-store," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_bank-payment," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_bank-statement-import," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_brand," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_business-requirement," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_commission," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_community-data-files," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_connector-telephony," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_contract," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_credit-control," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_currency," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_data-protection," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_donation," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_e-commerce," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_edi," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_event," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_helpdesk," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_hr," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_knowledge," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_l10n-canada," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_maintenance," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_management-system," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_manufacture," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_margin-analysis," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_mis-builder," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_multi-company," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_partner-contact," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_pos," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_product-attribute," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_product-pack," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_product-variant," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_project," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_project-reporting," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_purchase-workflow," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_queue," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_reporting-engine," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_sale-workflow," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-auth," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-brand," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-env," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-tools," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-ux," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_social," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_stock-logistics-warehouse," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_timesheet," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_website," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_wms," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/SanteLibre_santelibre_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Smile-SA_odoo_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_base," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_dms," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_docs," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_misc," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_quality," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_web," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_website," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/odooaktiv_QuotationRevision," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/odooaktiv_product_rating_app," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/openeducat_openeducat_erp," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/pledra_odoo-product-configurator," >> ${EL_CONFIG_FILE}
fi
printf "\n" >> ${EL_CONFIG_FILE}

printf "workers = 2\n" >> ${EL_CONFIG_FILE}
printf "max_cron_threads = 2\n" >> ${EL_CONFIG_FILE}

if [[ ${EL_INSTALL_NGINX} = "True" ]]; then
    printf "xmlrpc_interface = 127.0.0.1\n" >> ${EL_CONFIG_FILE}
    printf "netrpc_interface = 127.0.0.1\n" >> ${EL_CONFIG_FILE}
    printf "proxy_mode = True\n" >> ${EL_CONFIG_FILE}
fi

echo -e "\n---- Install Odoo with addons module ----"
git submodule update --init

# Generate empty addons if missing
if [[ ! -d "./addons/addons" ]]; then
    mkdir -p ./addons/addons
fi

if [[ ! -f "./.venv" ]]; then
    echo -e "\n---- Create Virtual environment Python ----"
    if [[ -f "/home/"${USER}"/.pyenv/versions/3.7.7/bin/python3" ]]; then
        /home/"${USER}"/.pyenv/versions/3.7.7/bin/python3 -m venv .venv
    elif [[ -f "/Users/"${USER}"/.pyenv/versions/3.7.7/bin/python3" ]]; then
        /Users/"${USER}"/.pyenv/versions/3.7.7/bin/python3 -m venv .venv
    else
        echo "Missing pyenv, please refer installation guide."
        exit 1
    fi
fi

echo -e "\n---- Installing poetry dependancy ----"
.venv/bin/pip install --upgrade pip
source $HOME/.poetry/env
poetry install

# Link for dev
echo -e "\n---- Add link dependency in site-packages of Python ----"
ln -fs ${EL_HOME_ODOO}/odoo ${EL_HOME}/.venv/lib/python3.7/site-packages/

# Install git-repo if missing
if [[ ! -f "./.venv/repo" ]]; then
    echo "\n---- Install git-repo from Google APIS ----"
    curl https://storage.googleapis.com/git-repo-downloads/repo > ./.venv/repo
    chmod +x ./.venv/repo
fi
