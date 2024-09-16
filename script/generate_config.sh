#!/usr/bin/env bash

. ./env_var.sh

EL_USER=${USER}
EL_HOME=$PWD
EL_HOME_ODOO="${EL_HOME}/odoo"
#EL_PORT="8069"
#EL_LONGPOLLING_PORT="8072"
#EL_SUPERADMIN="admin"
EL_CONFIG_FILE="${EL_HOME}/config.conf"
#EL_MINIMAL_ADDONS="False"
#EL_INSTALL_NGINX="True"

echo -e "* Create server config file"

touch "${EL_CONFIG_FILE}"
echo -e "* Creating server config file"
printf '[options] \n; This is the password that allows database operations:\n' > "${EL_CONFIG_FILE}"
printf "admin_passwd = ${EL_SUPERADMIN}\n" >> "${EL_CONFIG_FILE}"
printf "db_host = False\n" >> "${EL_CONFIG_FILE}"
printf "db_port = False\n" >> "${EL_CONFIG_FILE}"
printf "db_user = ${EL_USER}\n" >> "${EL_CONFIG_FILE}"
printf "db_password = False\n" >> "${EL_CONFIG_FILE}"
printf "xmlrpc_port = ${EL_PORT}\n" >> "${EL_CONFIG_FILE}"
printf "longpolling_port = ${EL_LONGPOLLING_PORT}\n" >> "${EL_CONFIG_FILE}"

printf "addons_path = ${EL_HOME_ODOO}/addons,${EL_HOME}/addons/addons," >> "${EL_CONFIG_FILE}"
printf "${EL_HOME}/addons/OCA_web," >> "${EL_CONFIG_FILE}"
if [[ ${EL_MINIMAL_ADDONS} = "False" ]]; then
    printf "${EL_HOME}/addons/CybroOdoo_CybroAddons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/ERPLibre_erplibre_addons," >> ${EL_CONFIG_FILE}
<<<<<<< HEAD
=======
    printf "${EL_HOME}/addons/ERPLibre_erplibre_theme_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/JayVora-SerpentCS_SerpentCS_Contributions," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_QuotationRevision," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_development," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_erplibre-family-management," >> ${EL_CONFIG_FILE}
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
>>>>>>> 4b3ece52fa90618e255a713584238719e1f50e7f
    printf "${EL_HOME}/addons/OCA_account-invoicing," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_bank-payment," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_product-attribute," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_sale-workflow," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-auth," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-brand," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-tools," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_social," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_survey," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_website," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/TechnoLibre_nutrition_libre_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/odoomates_odooapps," >> ${EL_CONFIG_FILE}
fi
printf "\n" >> "${EL_CONFIG_FILE}"

printf "max_cron_threads = 2\n" >> "${EL_CONFIG_FILE}"

if [[ ${EL_INSTALL_NGINX} = "True" ]]; then
    printf "workers = 2\n" >> "${EL_CONFIG_FILE}"
    printf "xmlrpc_interface = 127.0.0.1\n" >> "${EL_CONFIG_FILE}"
<<<<<<< HEAD
    printf "netrpc_interface = 127.0.0.1\n" >> "${EL_CONFIG_FILE}"
=======
>>>>>>> 4b3ece52fa90618e255a713584238719e1f50e7f
    printf "proxy_mode = True\n" >> "${EL_CONFIG_FILE}"
else
    printf "workers = 0\n" >> "${EL_CONFIG_FILE}"
fi
