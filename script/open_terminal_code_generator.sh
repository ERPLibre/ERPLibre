#!/usr/bin/env bash
# Open a new gnome-terminal with different path on new tab
ODOO_VERSION=$(cat .odoo-version)
working_path=$(readlink -f .)
paths="${working_path}/
${working_path}/
${working_path}/addons.odoo${ODOO_VERSION}/ERPLibre_erplibre_addons
${working_path}/addons.odoo${ODOO_VERSION}/TechnoLibre_odoo-code-generator
${working_path}/addons.odoo${ODOO_VERSION}/TechnoLibre_odoo-code-generator-template"

#  "${working_path}/addons.odoo${ODOO_VERSION}/OCA_server-tools"

cmd="git status"
#echo "${paths}"
./script/terminal/open_terminal.sh "$cmd" "$paths"
