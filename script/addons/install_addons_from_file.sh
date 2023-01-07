#!/usr/bin/env bash
# $1 BD NAME
# $2 file_path
./script/addons/install_addons.sh "$1" "$(<$2)"
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/addons/install_addons.sh  into install_addons_from_file.sh"
  exit 1
fi
