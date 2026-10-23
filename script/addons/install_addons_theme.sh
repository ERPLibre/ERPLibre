#!/usr/bin/env bash
# TODO addons website need to be install before to install the theme
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# Argument 3 is config
if [[ $# -eq 3 ]]; then
  ./script/addons/check_addons_exist.py -m "$2" -c "$3"
else
  ./script/addons/check_addons_exist.py -m "$2"
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} check_addons_exist.py into install_addons.sh"
  exit 1
fi

echo "Install theme module '$2' on BD '$1'"

if [[ $# -eq 3 ]]; then
  ./odoo_bin.sh theme apply -c "$3" -d "$1" "$2"
else
  ./odoo_bin.sh theme apply -d "$1" "$2"
fi

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} odoo_bin.sh theme apply into install_addons_theme.sh"
  exit 1
fi
