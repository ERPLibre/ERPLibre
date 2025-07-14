#!/usr/bin/env bash

. ./env_var.sh

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Update git-repo
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &
DAEMON_PID=$!

if [ -L "$EL_MANIFEST_DEV" ]; then
  MANIFEST_TARGET=$(readlink -f "EL_MANIFEST_PROD")
else
  MANIFEST_TARGET="$EL_MANIFEST_DEV"
fi

./.venv/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --verify HEAD) -m ${MANIFEST_TARGET}
./.venv/repo sync -c -j $(nproc --all) -v -m ${MANIFEST_TARGET}

kill ${DAEMON_PID}
