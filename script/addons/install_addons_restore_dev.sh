#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# "$1" code_generator_name
./script/database/db_restore.py --database "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} ./script/database/db_restore.py into install_addons_restore_dev.sh"
  exit 1
fi

./script/addons/install_addons_dev.sh "$1" "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} ./script/addons/install_addons_dev.sh into install_addons_restore_dev.sh"
  exit 1
fi
