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

PYENV_PATH=~/.pyenv
PYENV_VERSION_PATH=${PYENV_PATH}/versions/${PYTHON_VERSION}
echo "Python path version home"
echo ${PYENV_VERSION_PATH}
#echo "Python path version local"
#echo ${LOCAL_PYTHON_EXEC}

if [[ ! -d "${PYENV_PATH}" ]]; then
    echo -e "\n---- Installing pyenv in ${PYENV_PATH} ----"
    # export PYENV_GIT_TAG=v2.3.35
    # To change version
    # rm ~/.pyenv to uninstall it
    curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash
fi

echo -e "\n---- Export pyenv in ${PYENV_PATH} ----"
export PATH="${PYENV_PATH}/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

if [[ ! -d "${PYENV_VERSION_PATH}" ]]; then
    echo -e "\n---- Installing python ${PYTHON_VERSION} with pyenv in ${PYENV_VERSION_PATH} ----"
    # Update all python version list
    cd "${PYENV_PATH}" && git pull && cd -
    yes n|pyenv install ${PYTHON_VERSION}
    if [[ $retVal -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} when installing pyenv"
        exit 1
    fi
fi

pyenv local ${PYTHON_VERSION}

if [[ ! -d ${VENV_PATH} ]]; then
    echo -e "\n---- Create Virtual environment Python ----"
    if [[ -e ${PYTHON_EXEC} ]]; then
        ${PYTHON_EXEC} -m venv "${VENV_PATH}"
        retVal=$?
          if [[ $retVal -ne 0 ]]; then
              echo "Virtual environment, error when creating ${VENV_PATH}"
              exit 1
          fi
    else
        echo "Missing pyenv, please refer installation guide."
        exit 1
    fi
fi