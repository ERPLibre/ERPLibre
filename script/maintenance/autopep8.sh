#!/usr/bin/env bash
# This will format all python file
# argument 1: directory or file to format
NPROC=$(nproc)
source ./script/OCA_maintainer-tools/env/bin/activate
oca-autopep8 -j ${NPROC} --max-line-length 79 -ari $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error oca-autopep8 format"
    exit 1
fi
