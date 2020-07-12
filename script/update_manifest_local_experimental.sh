#!/usr/bin/env bash

. ./env_var.sh

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"
#EL_MANIFEST_EXP="./manifest/default.experimental.xml"

# Update git-repo
git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &
DAEMON_PID=$!

./venv/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m ${EL_MANIFEST_EXP}
./venv/repo sync -v --force-sync -m ${EL_MANIFEST_EXP}

kill ${DAEMON_PID}
