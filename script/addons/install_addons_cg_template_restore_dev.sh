#!/usr/bin/env bash
# "$1" module_name
# "$1" code_generator_template_name
./script/database/db_restore.py --database "$2"
./script/addons/install_addons_dev.sh "$2" "$1"
./script/addons/install_addons_dev.sh "$2" "$2"
