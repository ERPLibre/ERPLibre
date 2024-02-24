#!/usr/bin/env bash
# $1 is database name
# $2 is module name separate by ,
# $3 is directory path to check
# $4 is generated module name separate by ,
# $5 optional, the config path
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

if [[ $# -lt 4 ]]; then
  echo -e "${Red}Error${Color_Off}, need 4 arguments: 1-database name, 2-list of module to install, 3-directory to check difference, 4-list of generated module"
  exit 1
fi

INIT_DATETIME=$(date +%s)

if [[ $# -eq 5 ]]; then
  ./script/addons/coverage_install_addons_dev.sh "$1" "$2" "$5"
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/addons/coverage_install_addons_dev.sh ${1} ${2} ${5}"
    exit 1
  fi
else
  ./script/addons/coverage_install_addons_dev.sh "$1" "$2"
  retVal=$?
  if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/addons/coverage_install_addons_dev.sh ${1} ${2}"
    exit 1
  fi
fi

# Check if the code was updated
./script/code_generator/test_code_generator_update_module.py -m "$4" -d "$3" --datetime "${INIT_DATETIME}"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} ./script/code_generator/test_code_generator_update_module.py ${4} ${3}"
  exit 1
fi

# TODO check output when got warning
./script/git/repo_revert_git_diff_date_from_code_generator.py --repo "$3"
# Remove pot and po diff
cd "$3" || exit 1
# git 2.22 and more, else use next command
#BRANCH=$(git branch --show-current)
#BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Support old version git < 2.23.0
# git restore --source="${BRANCH}" "*.po*"
git checkout -- "*.po*"

cd - || exit 1
./script/maintenance/black.sh "$3"
echo "TEST ${2}"
./script/code_generator/check_git_change_code_generator.sh "$3"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} ./script/code_generator/check_git_change_code_generator.sh"
  exit 1
fi
