#!/usr/bin/env bash
./run.sh --no-http --stop-after-init --dev qweb -d $1 -i $2 -u $2
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error install_addons_dev.sh"
    exit 1
fi
