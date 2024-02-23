#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# This will format all python file
# argument 1: directory or file to format
source ./.venv/bin/activate
black -l 79 --preview -t py37 "$@"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} black format"
    exit 1
fi
