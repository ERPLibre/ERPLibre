#!/usr/bin/env bash
# Open a new gnome-terminal with different path on new tab
working_path=`readlink -f .`
paths=(
"${working_path}/"
#"${working_path}/addons/TechnoLibre_odoo-code-generator"
#"${working_path}/addons/TechnoLibre_odoo-code-generator-template"
#"${working_path}/addons/ERPLibre_erplibre_addons"
#"${working_path}/addons/OCA_server-tools"

)
cmd_before="cd "
# when change directory, open a new tab with command to execute
cmd_after=";gnome-terminal --tab -- bash -c 'git status;bash';"
#cmd_after=";gnome-terminal --tab;"

LONGCMD=""
for t in "${paths[@]}"; do
  LONGCMD+=${cmd_before}${t}${cmd_after}
done

#echo $LONGCMD

# Open all terminal from paths list
#echo "gnome-terminal --window -- bash -c \"${LONGCMD}\""
gnome-terminal --window -- bash -c "${LONGCMD}"
