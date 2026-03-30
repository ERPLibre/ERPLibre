#!/usr/bin/env bash

. ./env_var.sh

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Generate local manifest
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA

# Update git-repo
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b $(git rev-parse --verify HEAD) -m ${EL_MANIFEST_DEV}
.venv.erplibre/bin/repo sync -v
