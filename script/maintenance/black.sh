#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# This will format all python file
# argument 1: directory or file to format
# EL_BLACK_TARGET: black target version, py37 by default (the oldest Odoo
# addons still run 3.7); make format_script passes this repository's floor.
source ./.venv.erplibre/bin/activate
black -l 79 --preview -t "${EL_BLACK_TARGET:-py37}" "$@"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} black format"
    exit 1
fi
