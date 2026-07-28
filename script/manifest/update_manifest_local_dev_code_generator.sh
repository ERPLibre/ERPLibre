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

# Update git-repo
git daemon --base-path=. --export-all --reuseaddr --informative-errors ${DAEMON_VERBOSE} &
DAEMON_PID=$!

if [ -L "$EL_MANIFEST_DEV" ]; then
  MANIFEST_TARGET=$(readlink -f "$EL_MANIFEST_DEV")
else
  MANIFEST_TARGET="$EL_MANIFEST_DEV"
fi

if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc --all)"
else
  JOBS="$(sysctl -n hw.ncpu)"
fi

# Generate local manifest
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --verify HEAD) -m ${MANIFEST_TARGET} -g base,code_generator
.venv.erplibre/bin/repo sync -c -j "$JOBS" ${REPO_VERBOSE} -m ${MANIFEST_TARGET}

kill ${DAEMON_PID}
