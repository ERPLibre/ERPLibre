#!/usr/bin/env bash
.venv/bin/isort --profile black -l 79 "$@"
./script/maintenance/black.sh "$@"
