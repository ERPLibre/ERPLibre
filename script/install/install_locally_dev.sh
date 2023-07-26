#!/usr/bin/env bash

. ./env_var.sh

./script/install/install_locally.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/install/install_locally.sh"
    exit 1
fi

if [[ "${OSTYPE}" == "darwin"* ]]; then
  echo -e "====> in locally dev"
  echo -e "====> source .venv/bin/activate"
  source .venv/bin/activate
  echo -e "====> after source .venv/bin/activate"
fi

# Update git-repo
./script/manifest/update_manifest_local_dev.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error manifest update, check git-repo."
    exit 1
fi

## Install maintainer-tools
#cd script/OCA_maintainer-tools || exit
## virtualenv is not installed by default
##virtualenv env
#../../.venv/bin/python -m venv env
#. env/bin/activate
#pip install setuptools-rust
## Delete all tag before installing, or break installation, will generate a new one after
#git tag | xargs git tag -d
#python setup.py install
#git tag ERPLibre/v1.4.0
##${VENV_PATH}/bin/pip install ./script/OCA_maintainer-tools/
#cd -
