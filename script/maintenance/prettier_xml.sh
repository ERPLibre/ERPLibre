#!/usr/bin/env bash
# This will format all xml
# argument 1: directory or file to format
prettier --xml-whitespace-sensitivity "ignore" --prose-wrap always --tab-width 4 --no-bracket-spacing --print-width 120 --write $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error prettier format"
    exit 1
fi
