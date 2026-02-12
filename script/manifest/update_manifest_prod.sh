#!/usr/bin/env bash

. ./env_var.sh

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc --all)"
else
  JOBS="$(sysctl -n hw.ncpu)"
fi

# Update git-repo
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b $(git rev-parse --verify HEAD)
.venv.erplibre/bin/repo sync -v -j "$JOBS"
