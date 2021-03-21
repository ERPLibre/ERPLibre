#!/usr/bin/env bash

. ./env_var.sh

./script/install_locally.sh

# Update git-repo
./script/update_manifest_local_dev.sh

# Install maintainer-tools
cd script/OCA_maintainer-tools
virtualenv env
. env/bin/activate
python setup.py install
#${VENV_PATH}/bin/pip install ./script/OCA_maintainer-tools/
