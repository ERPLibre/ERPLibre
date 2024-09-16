#!/usr/bin/env bash
# "$1" module_name
# "$1" code_generator_template_name
./script/database/db_restore.py --database "$2"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/database/db_restore.py into install_addons_cg_template_restore_dev.sh"
  exit 1
fi
./script/addons/install_addons_dev.sh "$2" "$1"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/addons/install_addons_dev.sh install module into install_addons_cg_template_restore_dev.sh"
  exit 1
fi
./script/addons/install_addons_dev.sh "$2" "$2"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error ./script/addons/install_addons_dev.sh install template into install_addons_cg_template_restore_dev.sh"
  exit 1
fi
