#!/usr/bin/env bash
# "$1" code_generator_name
./script/database/db_restore.py --database "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/database/db_restore.py into coverage_install_addons_restore_dev.sh"
  exit 1
fi

./script/addons/coverage_install_addons_dev.sh "$1" "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/addons/coverage_install_addons_dev.sh into coverage_install_addons_restore_dev.sh"
  exit 1
fi
