#!/usr/bin/env bash

. ./env_var.sh
#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Update git-repo
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &
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
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_mobile

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --verify HEAD) -m ${MANIFEST_TARGET} "$@"
.venv.erplibre/bin/repo sync -c -j "$JOBS" -v -m ${MANIFEST_TARGET}

kill ${DAEMON_PID}
