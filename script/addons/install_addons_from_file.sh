#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# $1 BD NAME
# $2 file_path
./script/addons/install_addons.sh "$1" "$(<$2)"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} ./script/addons/install_addons.sh  into install_addons_from_file.sh"
  exit 1
fi
