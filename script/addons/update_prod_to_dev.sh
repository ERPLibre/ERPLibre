#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# This script will remove mail configuration, remove backup configuration, and force admin user to test/test
echo "Update prod to dev on BD '$1'"

./script/addons/install_addons_dev.sh "$1" user_test,disable_mail_server,disable_auto_backup

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} install_addons.sh into update_prod_to_dev.sh"
  exit 1
fi
