#!/usr/bin/env bash
Red='\033[0;31m'    # Red
Color_Off='\033[0m' # Text Reset

# you need odoo 18 installed
# you need $1 for the module name
output=$(./script/addons/check_addons_exist.py --output_path -m "$1")
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} check_addons_exist.py into odoo_upgrade_code_with_single_module_autosearch.sh"
  exit 1
fi

./script/code/odoo_upgrade_code_with_single_module.sh "$output"
