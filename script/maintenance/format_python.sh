#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Un fichier Python, le formateur de SON contexte.
#
# Un module Odoo et un script d'outillage ne suivent pas la même norme et ne
# tournent pas sur le même interpréteur : les addons vivent dans des dépôts
# séparés, dont la communauté fixe le style, quand script/ n'engage que ce
# dépôt. Un réglage unique servait donc mal les deux.
#
#   addons/…, odoo*/addons/…  isort + black, cible py37 : les séries d'Odoo
#                             encore supportées descendent jusque-là.
#   tout le reste             ruff, réglé par .ruff.toml à la racine.

VENV="$(xargs < conf/python-erplibre-venv 2> /dev/null)"
RUFF="./${VENV}/bin/ruff"

for fichier in "$@"; do
  case "${fichier}" in
    ./addons/* | addons/* | ./odoo*/addons/* | odoo*/addons/*)
      "./${VENV}/bin/isort" --profile black -l 79 "${fichier}"
      ./script/maintenance/black.sh "${fichier}"
      ;;
    *)
      if [[ ! -x "${RUFF}" ]]; then
        echo "ruff absent de ${VENV} : ./script/install/install_erplibre.sh" >&2
        exit 1
      fi
      # Le tri des imports d'abord : il déplace des lignes que le formatage
      # remet ensuite à la bonne largeur.
      "${RUFF}" check --select I --fix --quiet "${fichier}"
      "${RUFF}" format --quiet "${fichier}"
      ;;
  esac
done
