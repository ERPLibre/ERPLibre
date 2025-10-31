#!/usr/bin/env bash
# Usage, ./test.sh -d test_addons_name -i module_name

#export ODOO_MODE_COVERAGE="true"
#export ODOO_MODE_TEST="true"

ODOO_MODE_TEST="true" ./run.sh --workers 0 "$@"
