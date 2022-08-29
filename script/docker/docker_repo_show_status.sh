#!/usr/bin/env bash

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")
# Docker remove dot
BASENAME="${BASENAME//./}"
# Lowercase
BASENAME="${BASENAME,,}"

docker exec -u root -ti ${BASENAME}_ERPLibre_1 /bin/bash -c "\
cd /ERPLibre; \
./.venv/repo forall -pc 'git status -s'; \
echo ''; \
git status -s; \
"
