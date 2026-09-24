#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# Les MODULES ODOO, et eux seuls : les addons des séries encore supportées
# descendent jusqu'à Python 3.7, d'où la cible. L'outillage du dépôt passe par
# ruff — voir format_python.sh, qui aiguille, et .ruff.toml.
# argument 1: directory or file to format
source ./.venv.erplibre/bin/activate
black -l 79 --preview -t py37 "$@"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} black format"
    exit 1
fi
