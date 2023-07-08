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
    printf "${EL_HOME}/addons/CybroOdoo_OpenHRMS," >> ${EL_CONFIG_FILE}
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
    printf "${EL_HOME}/addons/OCA_connector," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_connector-ecommerce," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_connector-interfaces," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_connector-jira," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_connector-telephony," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_contract," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_credit-control," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_crm," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_currency," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_data-protection," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_ddmrp," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_delivery-carrier," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_donation," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_e-commerce," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_edi," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_event," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_field-service," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_fleet," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_geospatial," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_helpdesk," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_hr," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_interface-github," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_knowledge," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_l10n-canada," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_maintenance," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_management-system," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_manufacture," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_margin-analysis," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_mis-builder," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_multi-company," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_operating-unit," >> ${EL_CONFIG_FILE}
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
    printf "${EL_HOME}/addons/OCA_rma," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_sale-reporting," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_sale-workflow," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-auth," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-backend," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-brand," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-env," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-tools," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-ux," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_social," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_stock-logistics-warehouse," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_storage," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_timesheet," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_vertical-association," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_vertical-hotel," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_vertical-isp," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_vertical-travel," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_website," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_website-cms," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_wms," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OmniaGit_odooplm," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Smile-SA_odoo_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/ajepe_odoo-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/camptocamp_odoo-cloud-platform," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/dhongu_deltatech," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/it-projects-llc_saas-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/itpp-labs_access-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/itpp-labs_pos-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/itpp-labs_website-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_web," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/novacode-nl_odoo-formio," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/obayit_odoo_dhtmlxgantt," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/odoo_design-themes," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/odoomates_odooapps," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/openeducat_openeducat_erp," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/tegin_medical-fhir," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/doc/itpp-labs_odoo-development," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/doc/itpp-labs_odoo-port-docs," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/doc/itpp-labs_odoo-test-docs," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/script/OCA_maintainer-tools," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/script/OCA_odoo-module-migrator," >> ${EL_CONFIG_FILE}
fi
printf "\n" >> ${EL_CONFIG_FILE}

printf "max_cron_threads = 2\n" >> ${EL_CONFIG_FILE}

if [[ ${EL_INSTALL_NGINX} = "True" ]]; then
    printf "workers = 2\n" >> ${EL_CONFIG_FILE}
    printf "xmlrpc_interface = 127.0.0.1\n" >> ${EL_CONFIG_FILE}
    printf "netrpc_interface = 127.0.0.1\n" >> ${EL_CONFIG_FILE}
    printf "proxy_mode = True\n" >> ${EL_CONFIG_FILE}
else
    printf "workers = 0\n" >> ${EL_CONFIG_FILE}
fi
