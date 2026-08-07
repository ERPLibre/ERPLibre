#!/usr/bin/env bash

. ./env_var.sh

# Verbosité de l'installation (git-repo). Silencieuse par défaut ;
# EL_VERBOSE=1 rétablit les logs détaillés (repo sync, git daemon).
if [ "${EL_VERBOSE:-0}" = "1" ]; then
  REPO_VERBOSE="-v"; DAEMON_VERBOSE="--verbose"
else
  REPO_VERBOSE="-q"; DAEMON_VERBOSE=""
fi

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Generate local manifest
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA

# Update git-repo
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b $(git rev-parse --verify HEAD) -m ${EL_MANIFEST_DEV}
.venv.erplibre/bin/repo sync ${REPO_VERBOSE}
