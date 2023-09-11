#!/usr/bin/env bash
# This will format all js,css,html
# argument 1: directory or file to format
./node_modules/.bin/prettier --tab-width 4 --print-width 120 --no-bracket-spacing --write "$@"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error prettier format"
    exit 1
fi
