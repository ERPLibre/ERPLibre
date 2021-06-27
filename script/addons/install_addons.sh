#!/usr/bin/env bash
./run.sh --no-http --stop-after-init -d $1 -i $2 -u $2
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error install_addons.sh"
    exit 1
fi
