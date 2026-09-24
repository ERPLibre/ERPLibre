#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Auto-installation de TODO : install_erplibre.sh pose ou rebâtit le venv
# d'outillage, puis TODO repart sur l'interpréteur de ce venv.
# Se lance depuis la racine du dépôt.

if ! ./script/install/install_erplibre.sh; then
  echo "Installation d'ERPLibre en echec : TODO ne demarre pas."
  exit 1
fi
exec "./$(xargs < conf/python-erplibre-venv)/bin/python" ./script/todo/todo.py "$@"
