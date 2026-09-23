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

# Cause qui oblige à rebâtir le venv, ou rien s'il est utilisable. La version
# est celle que rend bin/python, pas celle de pyvenv.cfg, figée à la création.
# Compatible et non identique : un python de distribution d'un patch plus
# récent convient, et l'égalité stricte le rebâtirait à chaque appel.
el_venv_defect() {
  local py="$1/bin/python"
  if [[ ! -f "$1/pyvenv.cfg" ]]; then
    echo "aucun pyvenv.cfg"
  elif ! el_python_is_compatible "${py}" "${PYTHON_VERSION}"; then
    echo "bin/python en $("${py}" -V 2> /dev/null || echo "panne"), ${PYTHON_VERSION} exige"
  elif [[ ! -f "$1/bin/activate" ]] || ! "${py}" -m pip --version > /dev/null 2>&1; then
    # Ce que laisse un « python -m venv » sans ensurepip.
    echo "bin/activate ou pip manquant"
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

PYTHON_EXEC="$(el_python_exec "${PYTHON_VERSION}")"
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
  REASON="$(el_venv_defect "${VENV_PATH}")"
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

if [[ ! -d ${VENV_PATH} ]]; then
  echo -e "\n---- Create Virtual environment Python ----"
  if ! "${PYTHON_EXEC}" -m venv "${VENV_PATH}"; then
    echo "Virtual environment, error when creating ${VENV_PATH}"
    exit 1
  fi
fi

# Contrôle final : l'appelant enchaîne sur ce venv, un 0 doit le garantir.
REASON="$(el_venv_defect "${VENV_PATH}")"
if [[ ! -d ${VENV_PATH} ]] || [[ -n "${REASON}" ]]; then
  echo "Virtual environment ${VENV_PATH} inutilisable : ${REASON:-absent}."
  exit 1
fi
echo "Virtual environment ${VENV_PATH} pret."
