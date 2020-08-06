#!/usr/bin/env bash
source $HOME/.poetry/env
poetry add -vv $(grep -v ";" ./.venv/build_dependency.txt | grep -v "*" )
