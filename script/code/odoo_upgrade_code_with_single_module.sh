#!/usr/bin/env bash

# you need odoo 18 installed
# you need $1 path to the module
./odoo18.0/odoo/odoo-bin upgrade_code --from 12.0 --addons-path "$1"
