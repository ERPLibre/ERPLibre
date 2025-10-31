#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# This will format all python file
# argument 1: directory or file to format
NPROC=$(nproc)
source ./.venv.erplibre/bin/activate
oca-autopep8 -j ${NPROC} --max-line-length 79 -ari $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} oca-autopep8 format"
    exit 1
fi
