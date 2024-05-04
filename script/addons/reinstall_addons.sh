#!/usr/bin/env bash
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
  echo -e "${Red}Error${Color_Off} check_addons_exist.py into reinstall_addons_dev.sh"
  exit 1
fi

echo "Uninstall module '$2' on BD '$1'"

if [[ $# -eq 3 ]]; then
  ./script/addons/uninstall_addons.sh "$1" "$2" "$3"
else
  ./script/addons/uninstall_addons.sh "$1" "$2"
fi
# Ignore if not uninstall
echo "Install module '$2' on BD '$1'"

if [[ $# -eq 3 ]]; then
  ./script/addons/install_addons_dev.sh "$1" "$2" "$3"
else
  ./script/addons/install_addons_dev.sh "$1" "$2"
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} install_addons_dev.sh into reinstall_addons.sh"
  exit 1
fi
