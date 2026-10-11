#!/usr/bin/env bash

. ./env_var.sh

Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# --freeze : transmis au script de manifeste, qui installe chaque dépôt sur
# le SHA de son freeze-revision (voir update_manifest_prod.sh). Les autres
# arguments sont ignorés.
MANIFEST_ARGS=()
for arg in "$@"; do
    if [ "${arg}" = "--freeze" ]; then
        MANIFEST_ARGS=(--freeze)
    fi
done

./script/install/install_locally.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/install/install_locally.sh"
    exit 1
fi

# Update git-repo
./script/manifest/update_manifest_prod.sh "${MANIFEST_ARGS[@]}"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} manifest update, check git-repo."
    exit 1
fi
