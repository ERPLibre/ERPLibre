#!/usr/bin/env bash
source ./.venv/bin/activate
python3 ./odoo/odoo-bin -c ./config.conf --limit-time-real 99999 --limit-time-cpu 99999 $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error run.sh"
    exit 1
fi
