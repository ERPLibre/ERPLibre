#!/usr/bin/env bash

. ./env_var.sh

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Update git-repo
#./.venv/repo init -u https://github.com/ERPLibre/ERPLibre -b $(git rev-parse --verify HEAD)
 ./.venv/repo init -u $(git remote get-url origin) -b $(git rev-parse --verify HEAD)
#./.venv/repo sync --force-sync
./.venv/repo sync -v
