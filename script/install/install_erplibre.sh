#!/usr/bin/env bash
# TODO deprecated, this is moved into install_locally.sh to be sure venv is installed and force take specified supported version
python3 -m venv .venv.erplibre
source .venv.erplibre/bin/activate
pip3 install -r requirement/erplibre_require-ments.txt
npm install
