#!/usr/bin/env bash
# Argument 3 is config
if [[ $# -eq 3 ]]; then
  ./script/addons/check_addons_exist.py -m "$2" -c "$3"
else
  ./script/addons/check_addons_exist.py -m "$2"
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error check_addons_exist.py into coverage_install_addons_dev.sh"
  exit 1
fi
if [[ $# -eq 3 ]]; then
  ./coverage_run.sh --no-http --stop-after-init --dev qweb -d "$1" -i "$2" -u "$2" -c "$3"
else
  ./coverage_run.sh --no-http --stop-after-init --dev qweb -d "$1" -i "$2" -u "$2"
fi

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error coverage_run.sh into coverage_install_addons_dev.sh"
  exit 1
fi
