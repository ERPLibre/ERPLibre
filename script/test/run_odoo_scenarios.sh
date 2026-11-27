#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Scénarios du générateur de code Odoo : bases de données, installations
# Odoo, plusieurs minutes. Les options sont celles de
# run_odoo_scenarios.py, qui décrit le déroulé :
#
#   ./script/test/run_odoo_scenarios.sh [--scenario=NOM] [-k MOTIF]
#       [--failed] [--tui] [--junit=FICHIER] [--slowest=N] [--jobs=N]
#       [--timeout=S] [--coverage] [--keep_cache] [--ignore_init_check_git]
#   ./script/test/run_odoo_scenarios.sh --purge [--oui]
#   ODOO_SCENARIO_JOBS=4 ODOO_SCENARIO_TIMEOUT=5400 ...
#
# L'interpréteur est celui de .venv.erplibre, nommé ici : les scripts que
# les scénarios lancent trouvent ce venv en tête du PATH sans qu'il soit
# activé dans le shell.
set -uo pipefail

Red='\033[0;31m'
Color_Off='\033[0m'

cd "$(dirname "$0")/../.." || exit 1

PY=./.venv.erplibre/bin/python
if [[ ! -x "${PY}" ]]; then
    echo -e "${Red}✗ ${PY} absent : lancer l'installation ERPLibre d'abord.${Color_Off}"
    exit 1
fi

exec "${PY}" script/test/run_odoo_scenarios.py "$@"
