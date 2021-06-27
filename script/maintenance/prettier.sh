#!/usr/bin/env bash
# This will format all js,css,html
# argument 1: directory or file to format
prettier --write $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error prettier format"
    exit 1
fi
