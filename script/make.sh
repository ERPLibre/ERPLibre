#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

echo "
===> ${@}
"
time make $@
retVal=$?

echo "
<=== ${@}
"

if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} make ${@}"
    exit 1
fi
