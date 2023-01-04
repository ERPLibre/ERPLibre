#!/usr/bin/env bash
# "$1" code_generator_name
./script/database/db_restore.py --database "$1"
./script/addons/coverage_install_addons_dev.sh "$1" "$1"
