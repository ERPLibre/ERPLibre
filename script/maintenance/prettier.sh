#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# This will format all js,css,html
# argument 1: directory or file to format
./node_modules/.bin/prettier --tab-width 4 --print-width 120 --no-bracket-spacing --write "$@"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} prettier format"
    exit 1
fi
