#!/bin/bash

# If not exist, create it and do installation

if [[ ! -d "$DIRECTORY" ]]; then
  echo "$DIRECTORY does not exist."
  ~/.pyenv/versions/3.12.10/bin/python -m venv .venv.erplibre
fi

# If exist, source it and start installation
source ./.venv.erplibre/bin/activate

pip install -r requirement/erplibre_require-ments.txt

./script/todo/todo.py
