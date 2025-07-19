#!/usr/bin/env bash
# This is required to change environment for the running Odoo
source ./.venv.$(< .odoo-version)/bin/activate

ODOO_PATH="$(pwd)/odoo$(< .odoo-version)"
#export PATH=$ODOO_PATH:$PATH
#echo $PATH
#echo $PYTHONPATH
#export PYTHONPATH="${ODOO_PATH}:${ODOO_PATH}/addons:$PYTHONPATH"
export PYTHONPATH="${ODOO_PATH}:$PYTHONPATH"
#echo $PYTHONPATH

if [ "$ODOO_MODE_COVERAGE" = "true" ]; then
  coverage run -p ./odoo$(< .odoo-version)/odoo/odoo-bin "$@"
else
  python3 ./odoo$(< .odoo-version)/odoo/odoo-bin "$@"
fi
