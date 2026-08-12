#!/usr/bin/env bash

# Check if all 3 parameters are present
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
  echo "Error: One or more parameters are missing."
  echo "Usage: $0 <Context> <Venv_Path> <Python_Version>"
  exit 1
fi

# Assign arguments to variables
CONTEXT="$1"
VENV_PATH="$2"
PYTHON_VERSION="$3"

# Display variables (for verification)
echo "Context: $CONTEXT"
echo "Venv Path: $VENV_PATH"
echo "Python Version: $PYTHON_VERSION"

# Le CHOIX du fournisseur (mise ou pyenv) vit dans la bibliothèque : ce script
# ne connaît qu'un chemin d'interpréteur. C'est ce qui permet d'en ajouter un
# troisième sans toucher ici.
# shellcheck source=script/install/lib_python_provider.sh
. ./script/install/lib_python_provider.sh

PYTHON_EXEC="$(el_python_exec "${PYTHON_VERSION}")"
if [[ -z "${PYTHON_EXEC}" ]] || [[ ! -x "${PYTHON_EXEC}" ]]; then
  echo "Aucun interpreteur Python ${PYTHON_VERSION} n'a pu etre obtenu."
  echo "  Fournisseur demande : ${EL_PYTHON_PROVIDER:-auto}"
  echo "  Voir 'make install_mise', ou installez pyenv."
  exit 1
fi
echo "Interpreteur retenu : ${PYTHON_EXEC}"

if [[ ! -d ${VENV_PATH} ]]; then
  echo -e "\n---- Create Virtual environment Python ----"
  if ! "${PYTHON_EXEC}" -m venv "${VENV_PATH}"; then
    echo "Virtual environment, error when creating ${VENV_PATH}"
    exit 1
  fi
fi
