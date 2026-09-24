#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Formate un dépôt d'addons NOMMÉ, où qu'il soit rapatrié, et se tait s'il
# n'est pas là.
#
# Le chemin dépend du manifeste : la production range les addons sous
# « odoo<version>/addons/ », le manifeste de développement sous « addons/ ».
# Les cibles du Makefile ne connaissaient que la seconde forme, si bien
# qu'elles lançaient isort sur un chemin inexistant — une trace Python, et
# « make format_all » qui échoue sans avoir rien formaté.
#
# Un dépôt absent n'est pas une erreur : chaque version d'Odoo n'en rapatrie
# qu'une partie. On le dit, et on passe au suivant.
#
# Le formateur est celui de la communauté : ruff, réglé par
# conf/ruff.addons.toml, qui reprend le gabarit oca-addons-repo-template.
#
#   format_addons.sh [--xml] <nom de dépôt>...
#   --xml   passe aussi prettier sur les vues, quand le dépôt s'y prête

AVEC_XML=0
if [[ "$1" == "--xml" ]]; then
  AVEC_XML=1
  shift
fi

VENV="$(xargs < conf/python-erplibre-venv 2> /dev/null)"
ODOO="$(xargs < .odoo-version 2> /dev/null)"

# La cible de syntaxe suit la SÉRIE, comme chez OCA, qui en fixe une par
# branche : ici celle d'Odoo, lue dans .python-odoo-version. La figer
# rejetterait le code qu'une série récente autorise — Odoo 18 tourne en 3.12,
# où une f-string accepte un backslash que 3.10 refuse.
PY_ODOO="$(xargs < .python-odoo-version 2> /dev/null)"
CIBLE=()
if [[ "${PY_ODOO}" =~ ^([0-9]+)\.([0-9]+) ]]; then
  CIBLE=(--target-version "py${BASH_REMATCH[1]}${BASH_REMATCH[2]}")
fi

for nom in "$@"; do
  chemin=""
  for candidat in "odoo${ODOO}/addons/${nom}" "addons/${nom}"; do
    if [[ -n "${ODOO}" || "${candidat}" == addons/* ]] \
      && [[ -d "${candidat}" ]]; then
      chemin="${candidat}"
      break
    fi
  done
  if [[ -z "${chemin}" ]]; then
    echo "${nom} : absent de ce checkout, ignore."
    continue
  fi
  echo "---- ${chemin} ----"
  # La norme du dépôt s'il en porte une — c'est ainsi qu'OCA la distribue —,
  # sinon celle du gabarit OCA que ce dépôt-ci conserve.
  if [[ -f "${chemin}/.ruff.toml" ]] || [[ -f "${chemin}/pyproject.toml" ]]; then
    config=()
  else
    config=(--config conf/ruff.addons.toml)
  fi
  # Le tri des imports SEUL : « --select I » remplace la sélection du
  # fichier de configuration, dont le lint complet relève d'un autre chantier
  # — il rend des centaines d'avertissements, et ses correctifs touchent au
  # comportement, pas à la mise en forme.
  "./${VENV}/bin/ruff" check "${config[@]}" "${CIBLE[@]}" --select I --fix \
    --quiet "${chemin}/" || exit 1
  "./${VENV}/bin/ruff" format "${config[@]}" "${CIBLE[@]}" --quiet \
    "${chemin}/" || exit 1
  if [[ ${AVEC_XML} -eq 1 ]]; then
    ./script/maintenance/prettier_xml.sh "${chemin}/" || exit 1
  fi
done
