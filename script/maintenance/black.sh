#!/usr/bin/env bash
# This will format all python file
# argument 1: directory or file to format
source ./.venv/bin/activate
black -l 79 --preview -t py37 $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error black format"
    exit 1
fi
