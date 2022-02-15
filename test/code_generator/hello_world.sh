#!/usr/bin/env bash

Color_Off='\033[0m'      # Text Reset
Red='\033[0;31m'         # Red
Green='\033[0;32m'       # Green

tmp_dir=$(mktemp -d -t "erplibre_code_generator_helloworld-$(date +%Y-%m-%d-%H-%M-%S)-XXXXXXXXXX")

./script/code_generator/new_project.py -m test -d "${tmp_dir}"

MODULE_PATH="${tmp_dir}/test"
if [[ -d "${MODULE_PATH}" ]]; then
    echo -e "${Green}SUCCESS${Color_Off} ${MODULE_PATH} exists."
else
    echo -e "${Red}ERROR${Color_Off} ${MODULE_PATH} is missing."
fi

rm -rf "${tmp_dir}"
