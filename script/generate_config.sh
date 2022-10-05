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
    printf "${EL_HOME}/addons/ERPLibre_erplibre_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/ERPLibre_erplibre_theme_addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_development," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_erplibre-family-management," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_odoo-business-spending-management-quebec-canada," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/MathBenTech_scrummer," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/Numigi_odoo-partner-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_contract," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_field-service," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_geospatial," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_helpdesk," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_hr," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_partner-contact," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-auth," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-brand," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_server-tools," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_social," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_vertical-association," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/OCA_website," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/TechnoLibre_odoo-code-generator," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/TechnoLibre_odoo-code-generator-template," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/ajepe_odoo-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/camptocamp_odoo-cloud-platform," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/dhongu_deltatech," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/it-projects-llc_saas-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/itpp-labs_access-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/itpp-labs_pos-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/itpp-labs_website-addons," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/kinjal-sorathiya_Property-Management_odoo," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_base," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_dms," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_misc," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_web," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/muk-it_muk_website," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/addons/odoo_design-themes," >> ${EL_CONFIG_FILE}
    printf "${EL_HOME}/script/OCA_maintainer-tools," >> ${EL_CONFIG_FILE}
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
