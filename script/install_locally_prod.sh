#!/usr/bin/env bash

. ./env_var.sh

./script/install_locally.sh

# Update git-repo
./script/update_manifest_prod.sh
