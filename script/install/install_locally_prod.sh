#!/usr/bin/env bash

. ./env_var.sh

./script/install/install_locally.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/install/install_locally.sh"
    exit 1
fi

# Update git-repo
./script/manifest/update_manifest_prod.sh
if [[ $retVal -ne 0 ]]; then
    echo "Error manifest update, check git-repo."
    exit 1
fi
