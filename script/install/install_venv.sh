#!/usr/bin/env bash

# Check if all 3 parameters are present
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
  echo "Error: One or more parameters are missing."
  echo "Usage: $0 <Context> <Venv_Path> <Python_Version>"
  exit 1
fi

# Assign arguments to variables
CONTEXT="$1"
# Sans « / » final : « rm -rf lien/ » viderait la cible d'un lien.
VENV_PATH="${2%"${2##*[!/]}"}"
PYTHON_VERSION="$3"
if [ -z "${VENV_PATH}" ]; then
  echo "Error: Venv_Path '$2' designates the root."
  exit 1
fi

# Display variables (for verification)
echo "Context: $CONTEXT"
echo "Venv Path: $VENV_PATH"
echo "Python Version: $PYTHON_VERSION"

# Le CHOIX du fournisseur (mise ou pyenv) vit dans la bibliothèque : ce script
# ne connaît qu'un chemin d'interpréteur.
# shellcheck source=script/install/lib_python_provider.sh
. ./script/install/lib_python_provider.sh

# Ce qui borne le PATCH, et pour qui.
#
# Le venv d'Odoo est contraint par son pyproject (« >=3.12.10,<3.13 ») : un
# patch inférieur y serait refusé par Poetry. Rien n'épingle celui de
# l'outillage — exiger le patch y écarte le Python des distributions dès
# qu'il est d'un cran en retard, et force pyenv à compiler CPython pour rien.
EXIGENCE="patch"
[ "${CONTEXT}" = "ERPLibre" ] && EXIGENCE="mineure"

# Version RÉELLE d'un venv : celle que rend son interpréteur, jamais celle
# qu'annonce pyvenv.cfg, figée à la création et que rien ne revalide. Rien
# n'est rendu quand bin/python ne s'exécute plus — un venv bâti sur un CPython
# depuis retiré garde un lien mort, et c'est justement un venv à rebâtir.
el_venv_python_version() {
  local py="$1/bin/python"
  [ -x "${py}" ] || return 1
  "${py}" -c 'import platform;print(platform.python_version())' 2> /dev/null
}

# Le venv est-il HORS SERVICE — non pas d'une autre version, mais inutilisable
# tel quel ? Ce qui suit ne se répare pas : on rebâtit, quel que soit l'appelant.
el_venv_hors_service() {
  local py="$1/bin/python"
  if [[ ! -f "$1/pyvenv.cfg" ]]; then
    echo "aucun pyvenv.cfg"
  elif [[ -z "$(el_venv_python_version "$1")" ]]; then
    echo "son interpreteur ne s'execute plus"
  elif [[ ! -f "$1/bin/activate" ]] || ! "${py}" -m pip --version > /dev/null 2>&1; then
    # Ce que laisse un « python -m venv » sans ensurepip.
    echo "bin/activate ou pip manquant"
  fi
}

# Le venv tourne, mais pas sur la version demandée. La version est celle que
# rend bin/python, pas celle de pyvenv.cfg, figée à la création. Compatible et
# non identique : un python de distribution d'un patch plus récent convient, et
# l'égalité stricte rebâtirait à chaque appel.
el_venv_version_autre() {
  if ! el_python_is_compatible \
    "$1/bin/python" "${PYTHON_VERSION}" "${EXIGENCE}"; then
    echo "bin/python en $(el_venv_python_version "$1"), ${PYTHON_VERSION} exige"
  fi
}

# Ce qui oblige à rebâtir, ou rien.
#
# Une version qui diffère ne vaut destruction que pour le venv d'OUTILLAGE :
# le rebâtir coûte une installation pip, quand celui d'Odoo représente une
# installation Poetry entière — des centaines de paquets, dont certains se
# compilent. Un écart de patch ne l'empêche pas de servir ; on le dit, et on le
# laisse. Hors service, en revanche, il ne sert plus personne.
el_venv_a_rebatir() {
  local cause
  cause="$(el_venv_hors_service "$1")"
  if [[ -n "${cause}" ]]; then
    echo "${cause}"
    return
  fi
  cause="$(el_venv_version_autre "$1")"
  if [[ -n "${cause}" ]] && [[ "${CONTEXT}" == "ERPLibre" ]]; then
    echo "${cause}"
  fi
}

# Un checkout MONTÉ depuis une autre machine porte le venv de cette machine.
# Son interpréteur ne démarre pas ici — un CPython précompilé cherche sa
# bibliothèque standard sous le préfixe de sa construction —, ce qui le fait
# passer pour défectueux. Le détruire effacerait, à travers le réseau,
# l'installation de la machine à qui il appartient.
# findmnt vient d'util-linux : absent ailleurs, le contrôle s'abstient plutôt
# que de refuser à tort.
el_venv_est_distant() {
  local fs
  command -v findmnt > /dev/null 2>&1 || return 1
  fs="$(findmnt -n -o FSTYPE --target "$1" 2> /dev/null)"
  case "${fs}" in
    fuse* | sshfs | nfs* | cifs | smb*) return 0 ;;
    *) return 1 ;;
  esac
}

PYTHON_EXEC="$(el_python_exec "${PYTHON_VERSION}" "${EXIGENCE}")"
if [[ -z "${PYTHON_EXEC}" ]] || [[ ! -x "${PYTHON_EXEC}" ]]; then
  echo "Aucun interpreteur Python ${PYTHON_VERSION} n'a pu etre obtenu."
  echo "  Fournisseur demande : ${EL_PYTHON_PROVIDER:-auto}"
  if command -v mise > /dev/null 2>&1; then
    echo "  Voir : mise install python@${PYTHON_VERSION}   (reseau requis)"
  else
    echo "  Voir 'make install_mise', ou installez pyenv."
  fi
  exit 1
fi
echo "Interpreteur retenu : ${PYTHON_EXEC}"

# L'interpréteur est obtenu AVANT toute destruction : un provisionnement en
# échec laisse le venv en place.
if [[ -d ${VENV_PATH} ]]; then
  REASON="$(el_venv_a_rebatir "${VENV_PATH}")"
  CONSERVE="$(el_venv_version_autre "${VENV_PATH}")"
  if [[ -z "${REASON}" ]] && [[ -n "${CONSERVE}" ]]; then
    echo "Virtual environment ${VENV_PATH} conserve : ${CONSERVE}."
    echo "  Le rebatir refait toute son installation. Si vous le voulez :"
    echo "    rm -rf ${VENV_PATH} puis relancez."
  fi
  # rmdir n'écarte qu'un répertoire vide, ce que laisse une création
  # interrompue ; seul un pyvenv.cfg autorise le « rm -rf ».
  if [[ -n "${REASON}" ]] && ! rmdir "${VENV_PATH}" 2> /dev/null; then
    if [[ ! -f "${VENV_PATH}/pyvenv.cfg" ]]; then
      echo "Refus de detruire ${VENV_PATH} : ce n'est pas un venv (${REASON})."
      echo "  Ecartez-le vous-meme, puis relancez."
      exit 1
    fi
    if el_venv_est_distant "${VENV_PATH}"; then
      echo "Refus de detruire ${VENV_PATH} : il est sur un systeme de"
      echo "  fichiers monte a distance, donc il appartient a une autre"
      echo "  machine (${REASON} vu d'ici)."
      echo "  Installez SUR cette machine-la, pas au travers du montage."
      exit 1
    fi
    echo "DESTRUCTION de ${VENV_PATH} : ${REASON}."
    echo "  Ce qui y a ete pose a la main part avec lui ; il est rebati."
    if ! rm -rf "${VENV_PATH}"; then
      echo "Destruction de ${VENV_PATH} en echec, probablement faute de droits :"
      echo "  le venv est peut-etre partiellement detruit. Rien n'est rebati."
      echo "  Corrigez les droits, puis : rm -rf ${VENV_PATH} et relancez."
      exit 1
    fi
  fi
fi

if [[ "${PYTHON_VERSION}" == 2.* ]]; then
  # Python 2 n'a pas de module venv, et son Poetry vit ailleurs : le script
  # dédié pose les deux, et l'enveloppe bin/poetry qu'attend install_locally.
  if ! ./script/install/install_venv_python2.sh "${VENV_PATH}" \
    "${PYTHON_EXEC}" "$(xargs < .poetry-version)"; then
    exit 1
  fi
elif [[ ! -d ${VENV_PATH} ]]; then
  echo -e "\n---- Create Virtual environment Python ----"
  if ! "${PYTHON_EXEC}" -m venv "${VENV_PATH}"; then
    echo "Virtual environment, error when creating ${VENV_PATH}"
    exit 1
  fi
fi

# Contrôle final : l'appelant enchaîne sur ce venv, un 0 doit le garantir.
# Hors service seulement : un venv d'une autre version qu'on vient de conserver
# sciemment reste utilisable.
REASON="$(el_venv_hors_service "${VENV_PATH}")"
if [[ ! -d ${VENV_PATH} ]] || [[ -n "${REASON}" ]]; then
  echo "Virtual environment ${VENV_PATH} inutilisable : ${REASON:-absent}."
  exit 1
fi
echo "Virtual environment ${VENV_PATH} pret."
