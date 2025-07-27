#!/usr/bin/env bash
source ./.venv.erplibre/bin/activate
isort --profile black -l 79 "$@"
#./.venv.erplibre/bin/isort --profile black -l 79 "$@"
./script/maintenance/black.sh "$@"
