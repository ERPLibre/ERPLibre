#!/usr/bin/env bash
source $HOME/.poetry/env
poetry add -vv $(grep -v ";" ./.venv/build_dependancy.txt | grep -v "*" | sed 's/==/@^/' )
