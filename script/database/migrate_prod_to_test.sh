#!/usr/bin/env bash
if [ $# -lt 1 ]; then
    # TODO: print usage
    echo "Missing database name"
    exit 1
fi
source ./.venv/bin/activate
python3 ./odoo/odoo-bin -c ./config.conf --limit-time-real 99999 --limit-time-cpu 99999 --stop-after-init -i user_test,disable_mail_server,disable_auto_backup --dev prod -d $@
