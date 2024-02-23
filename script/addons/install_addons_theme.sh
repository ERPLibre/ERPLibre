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
  ./run.sh --no-http --stop-after-init -d "$1" --install-theme "$2" -c "$3"
else
  ./run.sh --no-http --stop-after-init -d "$1" --install-theme "$2"
fi

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} run.sh into install_addons_theme.sh"
  exit 1
fi
