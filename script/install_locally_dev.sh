#!/usr/bin/env bash

. ./env_var.sh

./script/install_locally.sh
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/install_locally.sh"
    exit 1
fi

# Update git-repo
./script/update_manifest_local_dev.sh
if [[ $retVal -ne 0 ]]; then
    echo "Error manifest update, check git-repo."
    exit 1
fi

# Install maintainer-tools
cd script/OCA_maintainer-tools
# virtualenv is not installed by default
#virtualenv env
../../.venv/bin/python -m venv env
. env/bin/activate
pip install setuptools-rust
python setup.py install
#${VENV_PATH}/bin/pip install ./script/OCA_maintainer-tools/
cd -
