#!/usr/bin/env bash
# $1 is database name
# $2 is module name
# $3 is directory path to check

./script/addons/install_addons.sh $1 $2
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/addons/install_addons.sh ${1} ${2}"
    exit 1
fi
./script/repo_revert_git_diff_date_from_code_generator.py
# Remove pot and po diff
cd $3
BRANCH=$(git branch --show-current)
git restore --source="${BRANCH}" "*.po*"
cd -
./script/maintenance/black.sh $3
echo "TEST ${2}"
./script/code_generator/check_git_change_code_generator.sh $3
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/code_generator/check_git_change_code_generator.sh"
    exit 1
fi
