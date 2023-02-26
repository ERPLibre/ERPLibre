#!/usr/bin/env bash

. ./env_var.sh
source .venv/bin/activate
#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Update git-repo
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &
DAEMON_PID=$!

./.venv/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --verify HEAD) -m ${EL_MANIFEST_DEV}
./.venv/repo sync -v --force-sync -m ${EL_MANIFEST_DEV}

kill ${DAEMON_PID}
