#!/usr/bin/env bash
./.venv/bin/poetry add -vv $(grep -v ";" ./.venv/build_dependency.txt | grep -v "*" )
# poetry add -vv $(grep -v ";" ./.venv/build_dependency.txt | grep -v "*" | sed 's/==/@^/' )
# poetry export -f ./.venv/build_dependency.txt --dev | poetry run -- pip install -r /dev/stdin
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/poetry/poetry_add_build_dependency.sh"
    cat ./.venv/build_dependency.txt
    exit 1
fi
