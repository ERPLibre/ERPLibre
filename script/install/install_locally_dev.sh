#!/usr/bin/env bash

. ./env_var.sh

Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

echo ""
echo "RUN ./script/install/install_locally.sh"
echo ""
./script/install/install_locally.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/install/install_locally.sh"
    exit 1
fi

# Update git-repo
echo ""
echo "RUN ./script/manifest/update_manifest_local_dev.sh"
echo ""
./script/manifest/update_manifest_local_dev.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} manifest update, check git-repo."
    exit 1
fi

npm install

## Install maintainer-tools
#cd script/OCA_maintainer-tools || exit
## virtualenv is not installed by default
##virtualenv env
#../../.venv.erplibre/bin/python -m venv env
#. env/bin/activate
#pip install setuptools-rust
## Delete all tag before installing, or break installation, will generate a new one after
#git tag | xargs git tag -d
#python setup.py install
#git tag ERPLibre/v1.4.0
##${VENV_PATH}/bin/pip install ./script/OCA_maintainer-tools/
#cd -
