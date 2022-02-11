#!/usr/bin/env bash
# Argument 3 is config
if [[ $# -eq 3 ]]; then
  ./script/addons/check_addons_exist.py -m "$2" -c "$3"
else
  ./script/addons/check_addons_exist.py -m "$2"
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error check_addons_exist.py into reinstall_addons_dev.sh"
  exit 1
fi
if [[ $# -eq 3 ]]; then
  ./script/addons/uninstall_addons.sh "$1" "$2" "$3"
else
  ./script/addons/uninstall_addons.sh "$1" "$2"
fi
# Ignore if not uninstall
if [[ $# -eq 3 ]]; then
  ./script/addons/install_addons_dev.sh "$1" "$2" "$3"
else
  ./script/addons/install_addons_dev.sh "$1" "$2"
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error install_addons_dev.sh into reinstall_addons.sh"
  exit 1
fi
