#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# This will format all xml
# argument 1: directory or file to format
STR_ARG="'$*'"
if [[ "${STR_ARG}" = *"/data/"* ]]; then
  # Need to keep width with data, else add corrupted string data
  ./node_modules/.bin/prettier --plugin=@prettier/plugin-xml --xml-whitespace-sensitivity "ignore" --prose-wrap always --tab-width 4 --no-bracket-spacing --print-width 999999999 --write "$@"
else
  ./node_modules/.bin/prettier --plugin=@prettier/plugin-xml --xml-whitespace-sensitivity "ignore" --prose-wrap always --tab-width 4 --no-bracket-spacing --print-width 120 --write "$@"
  # strict xml-whitespace-sensitivity will keep space alignement
  #prettier --xml-whitespace-sensitivity "strict" --prose-wrap always --tab-width 4 --no-bracket-spacing --print-width 120 --write $@
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} prettier-xml format"
    exit 1
fi
