#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

./.venv/bin/poetry add -vv $(grep -v ";" ./.venv/build_dependency.txt | grep -v "*" )
# poetry add -vv $(grep -v ";" ./.venv/build_dependency.txt | grep -v "*" | sed 's/==/@^/' )
# poetry export -f ./.venv/build_dependency.txt --dev | poetry run -- pip install -r /dev/stdin
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/poetry/poetry_add_build_dependency.sh"
    cat ./.venv/build_dependency.txt
    exit 1
fi
