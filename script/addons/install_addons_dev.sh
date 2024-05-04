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
  echo -e "${Red}Error${Color_Off} check_addons_exist.py into install_addons_dev.sh"
  exit 1
fi

echo "Install module '$2' on BD '$1'"

if [[ $# -eq 3 ]]; then
  ./run.sh --no-http --stop-after-init --limit-memory-soft=8589934592 --limit-memory-hard=10737418240 --dev cg -d "$1" -i "$2" -u "$2" -c "$3"
#  ./run.sh --no-http --stop-after-init fd --limit-memory-soft=2048*1024*1024 --dev cg -d "$1" -i "$2" -u "$2" -c "$3"
else
  ./run.sh --no-http --stop-after-init --limit-memory-soft=8589934592 --limit-memory-hard=10737418240 --dev cg -d "$1" -i "$2" -u "$2"
fi

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} run.sh into install_addons_dev.sh"
  exit 1
fi
