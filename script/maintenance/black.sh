#!/usr/bin/env bash
# This will format all python file
# argument 1: directory or file to format
source ./.venv/bin/activate
black -l 100 -t py37 $@
