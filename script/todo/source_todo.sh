#!/bin/bash
DIR_VENV_ERPLIBRE_EXIST=1
DIR_VENV_ERPLIBRE=".venv.erplibre"
# If not exist, create it and do installation
# Can be in conflict with ./script/install_locally.sh

if [[ ! -d "$DIR_VENV_ERPLIBRE" ]]; then
  DIR_VENV_ERPLIBRE_EXIST=0
  echo "$DIR_VENV_ERPLIBRE does not exist."
  if [[ ! -d "~/.pyenv/versions/$(< ./conf/python-erplibre-version)/bin/python" ]]; then
    "~/.pyenv/versions/$(< ./conf/python-erplibre-version)/bin/python" -m venv $DIR_VENV_ERPLIBRE
  else
    python -m venv $DIR_VENV_ERPLIBRE
  fi
fi

# If exist, source it and start installation
source ./.venv.erplibre/bin/activate
if [[ $DIR_VENV_ERPLIBRE_EXIST -eq 0 ]]; then
  pip install -r requirement/erplibre_require-ments.txt
fi

./script/todo/todo.py
