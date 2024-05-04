#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

echo "Update all on BD '$1'"

./run.sh --no-http --stop-after-init -d "$1" -u all

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} run.sh into update_addons_all.sh"
  exit 1
fi
