#!/usr/bin/env bash
# "$1" code_generator_name
./script/database/db_restore.py --database "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/database/db_restore.py into install_addons_restore_dev.sh"
  exit 1
fi

./script/addons/install_addons_dev.sh "$1" "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/addons/install_addons_dev.sh into install_addons_restore_dev.sh"
  exit 1
fi
