#!/usr/bin/env bash
./script/addons/check_addons_exist.py -m "$2"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error install_addons.sh"
    exit 1
fi
./script/addons/uninstall_addons.sh "$1" "$2"
./script/addons/install_addons_dev.sh "$1" "$2"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error reinstall_addons.sh"
    exit 1
fi
